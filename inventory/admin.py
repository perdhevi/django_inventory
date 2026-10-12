from django.contrib import admin

from .models import Category, Product, StockTransaction


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("id", "name")
    search_fields = ("name",)


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ("sku", "name", "category", "price", "stock_quantity")
    list_filter = ("category",)
    search_fields = ("sku", "name", "category__name")
    list_select_related = ("category",)
    readonly_fields = ("stock_quantity", "average_unit_cost", "inventory_value", "created_at", "updated_at")

@admin.register(StockTransaction)
class StockTransactionAdmin(admin.ModelAdmin):
    list_display = ("id", "product", "transaction_type", "quantity", "actor", "created_at")
    readonly_fields = tuple(field.name for field in StockTransaction._meta.fields)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False