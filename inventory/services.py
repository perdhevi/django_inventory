from decimal import Decimal, ROUND_HALF_UP
from uuid import UUID

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction

from .models import Product, StockTransaction

from .access import require_operation

T = StockTransaction.Type
INBOUND = {T.PROCUREMENT, T.OPENING_BALANCE, T.ADJUSTMENT_IN}
ADJUSTMENTS = {T.ADJUSTMENT_IN, T.ADJUSTMENT_OUT}
SIX = Decimal("0.000001")


# def require_operation(actor, kind):
#     # Phase 4 replaces this body with capability checks.
#     if not actor.is_authenticated or not actor.is_active or not actor.is_staff:
#         raise PermissionDenied("An active staff account is required.")


def money(value):
    try:
        amount = Decimal(str(value))
        if not amount.is_finite() or amount < 0 or amount >= Decimal("10000000000"):
            raise ValueError
        if amount != amount.quantize(Decimal("0.01")):
            raise ValueError
        return amount.quantize(Decimal("0.01"))
    except (ValueError, ArithmeticError):
        raise ValidationError("Prices must be nonnegative with at most two decimal places.")


def post_stock(*, actor, product_id, transaction_type, quantity, request_key,
               unit_cost=None, selling_price=None, reference="", notes="",
               corrects_id=None, reconcile_existing=False):
    require_operation(actor, transaction_type)
    if transaction_type not in T.values:
        raise ValidationError("Unknown transaction type.")
    if type(quantity) is not int or not 1 <= quantity <= 2147483647:
        raise ValidationError("Quantity must be a positive whole number.")
    try:
        request_key = UUID(str(request_key))
    except (ValueError, TypeError, AttributeError):
        raise ValidationError("A UUID request key is required.")
    if len(reference) > 100:
        raise ValidationError("Reference is limited to 100 characters.")
    if transaction_type in ADJUSTMENTS and not notes.strip():
        raise ValidationError("Adjustments require a reason in notes.")
    if transaction_type in INBOUND:
        if unit_cost is None or selling_price is not None:
            raise ValidationError("Receipts require unit_cost and no selling_price.")
        unit_cost = money(unit_cost)
    elif unit_cost is not None:
        raise ValidationError("Withdrawals do not accept unit_cost.")
    if transaction_type == T.SALE:
        if selling_price is None:
            raise ValidationError("Sales require selling_price.")
        selling_price = money(selling_price)
    elif selling_price is not None:
        raise ValidationError("Only sales accept selling_price.")
    if reconcile_existing and transaction_type != T.OPENING_BALANCE:
        raise ValidationError("Only opening balances can reconcile existing stock.")
    payload = {
        "product_id": int(product_id), "transaction_type": str(transaction_type),
        "quantity": quantity, "unit_cost": None if unit_cost is None else str(unit_cost),
        "selling_price": None if selling_price is None else str(selling_price),
        "reference": reference, "notes": notes, "corrects_id": corrects_id,
        "reconcile_existing": reconcile_existing,
    }

    def replay(existing):
        if existing.actor_id != actor.pk or existing.request_data != payload:
            raise ValidationError("Request key already used with different input or actor.")
        return existing, False

    try:
        with transaction.atomic():
            product = Product.objects.select_for_update().get(pk=product_id)
            existing = StockTransaction.objects.filter(request_key=request_key).first()
            if existing:
                return replay(existing)
            if not product.is_active:
                raise ValidationError("This product is inactive.")
            has_history = product.movements.exists()
            if transaction_type == T.OPENING_BALANCE:
                if has_history or (product.stock_quantity and not reconcile_existing):
                    raise ValidationError("Opening balance must be first; reconcile existing stock.")
                if reconcile_existing and quantity != product.stock_quantity:
                    raise ValidationError("Opening quantity must equal existing stock.")
            elif product.stock_quantity and not has_history:
                raise ValidationError("Reconcile existing opening stock first.")
            if corrects_id is not None:
                if transaction_type not in ADJUSTMENTS:
                    raise ValidationError("Only adjustments can link a correction.")
                if not product.movements.filter(pk=corrects_id).exists():
                    raise ValidationError("Correction target must belong to this product.")
            old_quantity, old_value = product.stock_quantity, product.inventory_value
            cogs = revenue = Decimal("0")
            if transaction_type in INBOUND:
                delta = (quantity * unit_cost).quantize(SIX, rounding=ROUND_HALF_UP)
                new_quantity = quantity if reconcile_existing else old_quantity + quantity
                new_value = delta if reconcile_existing else old_value + delta
            else:
                if quantity > old_quantity:
                    raise ValidationError("Insufficient stock.")
                consumed = old_value if quantity == old_quantity else (
                    old_value * quantity / old_quantity
                ).quantize(SIX, rounding=ROUND_HALF_UP)
                delta = -consumed
                new_quantity, new_value = old_quantity - quantity, old_value - consumed
                if transaction_type == T.SALE:
                    cogs, revenue = consumed, quantity * selling_price
            if new_quantity > 2147483647 or new_value >= Decimal("1000000000000000000"):
                raise ValidationError("Balance exceeds storage limits.")
            product.stock_quantity, product.inventory_value = new_quantity, new_value
            product.average_unit_cost = (
                (new_value / new_quantity).quantize(SIX, rounding=ROUND_HALF_UP)
                if new_quantity else Decimal("0")
            )
            movement = StockTransaction.objects.create(
                product=product, actor=actor, transaction_type=transaction_type,
                quantity=quantity, unit_cost=unit_cost, selling_price=selling_price,
                value_change=delta, cogs=cogs, revenue=revenue, gross_profit=revenue-cogs,
                reference=reference, notes=notes, corrects_id=corrects_id,
                request_key=request_key, request_data=payload,
            )
            product.save(update_fields=["stock_quantity", "inventory_value", "average_unit_cost", "updated_at"])
            return movement, True
    except IntegrityError:
        # Same globally unique key racing on different product locks.
        existing = StockTransaction.objects.filter(request_key=request_key).first()
        if existing:
            return replay(existing)
        raise