from uuid import uuid4

from django import forms

from .models import Category, Product, StockTransaction


class ProductForm(forms.ModelForm):
    class Meta:
        model = Product
        fields = ["sku", "name", "category", "description", "price", "is_active", "reorder_level"]


class CategoryForm(forms.ModelForm):
    class Meta:
        model = Category
        fields = ["name"]


class StockOperationForm(forms.Form):
    product = forms.ModelChoiceField(queryset=Product.objects.filter(is_active=True))
    quantity = forms.IntegerField(min_value=1, max_value=2147483647)
    unit_cost = forms.DecimalField(max_digits=12, decimal_places=2, min_value=0, required=False)
    selling_price = forms.DecimalField(max_digits=12, decimal_places=2, min_value=0, required=False)
    reference = forms.CharField(max_length=100, required=False)
    notes = forms.CharField(widget=forms.Textarea, required=False)
    corrects = forms.ModelChoiceField(queryset=StockTransaction.objects.all(), required=False)
    request_key = forms.UUIDField(widget=forms.HiddenInput, initial=uuid4)

    def __init__(self, *args, kind, **kwargs):
        super().__init__(*args, **kwargs)
        if kind in {"PROCUREMENT", "OPENING_BALANCE", "ADJUSTMENT_IN"}:
            self.fields["unit_cost"].required = True
        else:
            self.fields.pop("unit_cost")
        if kind == "SALE":
            self.fields["selling_price"].required = True
        else:
            self.fields.pop("selling_price")
        if kind in {"ADJUSTMENT_IN", "ADJUSTMENT_OUT"}:
            self.fields["notes"].required = True
        else:
            self.fields.pop("corrects")