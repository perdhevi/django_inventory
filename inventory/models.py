from decimal import Decimal

from django.core.validators import MinValueValidator
from django.db import models
from django.conf import settings


class Category(models.Model):
    name = models.CharField(max_length=100, unique=True)

    class Meta:
        ordering = ["name"]
        verbose_name_plural = "categories"

    def __str__(self):
        return self.name


class Product(models.Model):
    sku = models.CharField(max_length=50, unique=True)
    name = models.CharField(max_length=200)
    category = models.ForeignKey(
        Category,
        on_delete=models.PROTECT,
        related_name="products",
    )
    price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.00"))],
    )
    stock_quantity = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    average_unit_cost = models.DecimalField(max_digits=24, decimal_places=6, default=0)
    inventory_value = models.DecimalField(max_digits=24, decimal_places=6, default=0)

    def save(self, *args, **kwargs):
        # An ordinary metadata save must not overwrite balances read before another posting.
        # The posting service supplies explicit update_fields for its balance writes.
        if not self._state.adding and kwargs.get("update_fields") is None:
            balances = {"stock_quantity", "average_unit_cost", "inventory_value"}
            kwargs["update_fields"] = [
                field.name for field in self._meta.concrete_fields
                if not field.primary_key and field.name not in balances
            ]
        return super().save(*args, **kwargs)

    class Meta:
        ordering = ["name", "id"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(price__gte=0),
                name="inventory_product_price_nonnegative",
            ),
        ]

    def __str__(self):
        return f"{self.sku} — {self.name}"


class StockTransaction(models.Model):
    class Type(models.TextChoices):
        PROCUREMENT = "PROCUREMENT", "Procurement"
        SALE = "SALE", "Sale"
        OPENING_BALANCE = "OPENING_BALANCE", "Opening balance"
        ADJUSTMENT_IN = "ADJUSTMENT_IN", "Adjustment in"
        ADJUSTMENT_OUT = "ADJUSTMENT_OUT", "Adjustment out"

    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="movements")
    transaction_type = models.CharField(max_length=20, choices=Type.choices)
    quantity = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    unit_cost = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    selling_price = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    value_change = models.DecimalField(max_digits=24, decimal_places=6)
    cogs = models.DecimalField(max_digits=24, decimal_places=6, default=0)
    revenue = models.DecimalField(max_digits=24, decimal_places=6, default=0)
    gross_profit = models.DecimalField(max_digits=24, decimal_places=6, default=0)
    reference = models.CharField(max_length=100, blank=True)
    notes = models.TextField(blank=True)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)
    request_key = models.UUIDField(unique=True)
    request_data = models.JSONField(editable=False)
    corrects = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.PROTECT, related_name="corrections"
    )

    class Meta:
        ordering = ["-created_at", "-id"]
        constraints = [
            models.CheckConstraint(condition=models.Q(quantity__gt=0), name="movement_quantity_positive"),
        ]
        permissions = [
            ("record_sale", "Can record sales"),
            ("receive_procurement", "Can receive procurement"),
            ("adjust_stock", "Can adjust stock"),
            ("record_opening_balance", "Can record opening balances"),
            ("view_all_movements", "Can view all movement quantities"),
            ("view_sales_report", "Can view sales revenue"),
            ("view_procurement_report", "Can view procurement costs"),
            ("view_inventory_valuation", "Can view valuation and profit"),
            ("export_reports", "Can export permitted reports"),
        ]
