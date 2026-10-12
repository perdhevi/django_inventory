from rest_framework import serializers

from .models import Category, Product, StockTransaction


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
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "stock_quantity", "average_unit_cost", "inventory_value", "created_at", "updated_at"]

class StockTransactionSerializer(serializers.ModelSerializer):
    class Meta:
        model = StockTransaction
        fields = ["id", "product", "transaction_type", "quantity", "unit_cost",
                  "selling_price", "value_change", "cogs", "revenue", "gross_profit",
                  "reference", "notes", "actor", "created_at", "request_key", "corrects"]
        read_only_fields = fields


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