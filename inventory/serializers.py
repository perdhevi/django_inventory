from rest_framework import serializers

from .models import Category, Product, StockTransaction
from .access import FINANCIAL_FIELDS, allowed_money_fields

class CategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = Category
        fields = ["id", "name"]
        read_only_fields = ["id"]


class ProductSerializer(serializers.ModelSerializer):
    category_name = serializers.CharField(source="category.name", read_only=True)

    class Meta:
        model = Product
        fields = [
            "id",
            "sku",
            "name",
            "description",
            "is_active",
            "average_unit_cost",
            "inventory_value",
            "category",
            "category_name",
            "price",
            "stock_quantity",
            "reorder_level",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "stock_quantity", "average_unit_cost", "inventory_value", "created_at", "updated_at"]

    def to_representation(self, instance):
        data = super().to_representation(instance)
        user = self.context["request"].user
        if not user.has_perm("inventory.view_inventory_valuation"):
            data.pop("average_unit_cost", None)
            data.pop("inventory_value", None)
        return data


class StockTransactionSerializer(serializers.ModelSerializer):
    class Meta:
        model = StockTransaction
        fields = ["id", "product", "transaction_type", "quantity", "unit_cost",
                  "selling_price", "value_change", "cogs", "revenue", "gross_profit",
                  "reference", "notes", "actor", "created_at", "request_key", "corrects"]
        read_only_fields = fields

    def to_representation(self, instance):
        data = super().to_representation(instance)
        user = self.context["request"].user
        for field in FINANCIAL_FIELDS - allowed_money_fields(user, instance.transaction_type):
            data.pop(field, None)
        return data

class StockOperationSerializer(serializers.Serializer):
    product_id = serializers.PrimaryKeyRelatedField(queryset=Product.objects.all(), source="product")
    transaction_type = serializers.ChoiceField(choices=StockTransaction.Type.choices)
    quantity = serializers.IntegerField(min_value=1, max_value=2147483647)
    request_key = serializers.UUIDField()
    unit_cost = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=0, required=False)
    selling_price = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=0, required=False)
    reference = serializers.CharField(max_length=100, required=False, allow_blank=True)
    notes = serializers.CharField(required=False, allow_blank=True)
    corrects_id = serializers.IntegerField(min_value=1, required=False)