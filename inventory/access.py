from django.core.exceptions import PermissionDenied
from rest_framework.permissions import BasePermission, SAFE_METHODS

from .models import StockTransaction

OPERATION_PERMISSIONS = {
    "PROCUREMENT": "inventory.receive_procurement",
    "SALE": "inventory.record_sale",
    "OPENING_BALANCE": "inventory.record_opening_balance",
    "ADJUSTMENT_IN": "inventory.adjust_stock",
    "ADJUSTMENT_OUT": "inventory.adjust_stock",
}
FINANCIAL_FIELDS = {"unit_cost", "selling_price", "value_change", "cogs", "revenue", "gross_profit"}


def require_operation(actor, kind):
    permission = OPERATION_PERMISSIONS.get(kind)
    if not actor.is_authenticated or not actor.is_active or not permission or not actor.has_perm(permission):
        raise PermissionDenied("You cannot post this operation.")


def visible_movements(user):
    qs = StockTransaction.objects.select_related("product", "actor")
    if not user.is_authenticated or not user.is_active:
        return qs.none()
    if user.has_perm("inventory.view_all_movements") or user.has_perm("inventory.view_inventory_valuation"):
        return qs.all()
    kinds = []
    if user.has_perm("inventory.view_sales_report"):
        kinds.append("SALE")
    if user.has_perm("inventory.view_procurement_report"):
        kinds.append("PROCUREMENT")
    return qs.filter(transaction_type__in=kinds)


def allowed_money_fields(user, kind):
    if user.has_perm("inventory.view_inventory_valuation"):
        return FINANCIAL_FIELDS
    if kind == "SALE" and user.has_perm("inventory.view_sales_report"):
        return {"selling_price", "revenue"}
    if kind == "PROCUREMENT" and user.has_perm("inventory.view_procurement_report"):
        return {"unit_cost", "value_change"}
    return set()


class CatalogPermission(BasePermission):
    def has_permission(self, request, view):
        user = request.user
        if not user.is_authenticated or not user.is_active:
            return False
        model = view.queryset.model._meta.model_name
        if request.method in SAFE_METHODS:
            return user.has_perm(f"inventory.view_{model}")
        action = {"POST": "add", "PUT": "change", "PATCH": "change", "DELETE": "delete"}.get(request.method)
        return bool(action and user.has_perm(f"inventory.{action}_{model}"))


class MovementPermission(BasePermission):
    def has_permission(self, request, view):
        user = request.user
        if not user.is_authenticated or not user.is_active:
            return False
        if request.method == "POST":
            return any(user.has_perm(p) for p in OPERATION_PERMISSIONS.values())
        return any(user.has_perm(p) for p in (
            "inventory.view_all_movements", "inventory.view_sales_report",
            "inventory.view_procurement_report", "inventory.view_inventory_valuation"
        ))


class ValuationPermission(BasePermission):
    def has_permission(self, request, view):
        return bool(request.user.is_authenticated and request.user.is_active
                    and request.user.has_perm("inventory.view_inventory_valuation"))