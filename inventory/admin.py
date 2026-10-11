from django.contrib import admin

from .models import Category, Product


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
    readonly_fields = ("created_at", "updated_at")