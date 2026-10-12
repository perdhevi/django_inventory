from types import SimpleNamespace
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db.models import Sum
from django.utils import timezone

from .access import allowed_money_fields, visible_movements
from .models import Product
from .queries import filter_movements, filter_products
from .serializers import StockTransactionSerializer

REPORT_PERMISSION = {
    "stock": "inventory.view_product",
    "valuation": "inventory.view_inventory_valuation",
    "sales": "inventory.view_sales_report",
    "procurement": "inventory.view_procurement_report",
}


def report_payload(user, kind, params, exporting=False):
    if not user.is_authenticated or not user.is_active:
        raise PermissionDenied
    if kind == "movements":
        if not any(user.has_perm(p) for p in (
            "inventory.view_all_movements", "inventory.view_sales_report",
            "inventory.view_procurement_report", "inventory.view_inventory_valuation"
        )):
            raise PermissionDenied
    elif kind not in REPORT_PERMISSION:
        raise ValidationError("Unknown report.")
    elif not user.has_perm(REPORT_PERMISSION[kind]):
        raise PermissionDenied
    if exporting and not user.has_perm("inventory.export_reports"):
        raise PermissionDenied
    if kind in {"stock", "valuation"}:
        if params.get("start") or params.get("end"):
            raise ValidationError("Current snapshots do not accept historical dates.")
        qs = filter_products(Product.objects.all(), params)
        columns = ["id", "sku", "name", "stock_quantity", "reorder_level", "is_active"]
        if kind == "valuation":
            columns += ["average_unit_cost", "inventory_value"]
        totals = qs.aggregate(quantity=Sum("stock_quantity"))
        if kind == "valuation":
            totals.update(qs.aggregate(inventory_value=Sum("inventory_value")))
    else:
        qs = visible_movements(user)
        if kind == "sales":
            qs = qs.filter(transaction_type="SALE")
        elif kind == "procurement":
            qs = qs.filter(transaction_type="PROCUREMENT")
        qs = filter_movements(qs, params)
        columns = ["id", "product", "transaction_type", "quantity", "reference", "notes", "created_at"]
        totals = qs.aggregate(quantity=Sum("quantity"))
        if kind in {"sales", "procurement"}:
            operation = "SALE" if kind == "sales" else "PROCUREMENT"
            fields = sorted(allowed_money_fields(user, operation))
            columns += fields
            sums = [f for f in fields if f in {"revenue", "cogs", "gross_profit", "value_change"}]
            totals.update(qs.aggregate(**{f: Sum(f) for f in sums}))
        # Mixed history exports are quantity-only even for managers; use typed reports for money.
    if exporting:
        objects = list(qs[:10001])
        if len(objects) > 10000:
            raise ValidationError("Export is limited to 10,000 rows; narrow your filters.")
        count, number, pages = len(objects), 1, 1
    else:
        page = Paginator(qs, 25).get_page(params.get("page"))
        objects = list(page.object_list)
        count, number, pages = page.paginator.count, page.number, page.paginator.num_pages
    if kind in {"stock", "valuation"}:
        rows = [{column: getattr(product, column) for column in columns} for product in objects]
    else:
        data = StockTransactionSerializer(objects, many=True, context={"request": SimpleNamespace(user=user)}).data
        rows = [{column: record.get(column) for column in columns} for record in data]
    return {
        "kind": kind, "currency": settings.INVENTORY_CURRENCY,
        "timezone": timezone.get_current_timezone_name(),
        "generated_at": timezone.now().isoformat(), "columns": columns, "rows": rows,
        "totals": {k: (format(v or Decimal("0"), ".6f") if k != "quantity" else str(v or 0))
                   for k, v in totals.items()},
        "count": count, "page": number, "pages": pages,
    }
