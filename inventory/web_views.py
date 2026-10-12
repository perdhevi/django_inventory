from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Sum, F
from django.db.models.deletion import ProtectedError
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.views.generic import CreateView, UpdateView
from django.views.decorators.http import require_http_methods

from django.core.paginator import Paginator
from .queries import filter_products, filter_movements

from .access import OPERATION_PERMISSIONS, require_operation, visible_movements
from .forms import CategoryForm, ProductForm, StockOperationForm
from .models import Category, Product
from .serializers import StockTransactionSerializer
from .services import post_stock


def movement_data(request, queryset):
    return StockTransactionSerializer(queryset, many=True, context={"request": request}).data


@login_required
@permission_required("inventory.view_product", raise_exception=True)
def dashboard(request):
    totals = Product.objects.aggregate(units=Sum("stock_quantity"))
    totals["low_stock_products"] = Product.objects.filter(stock_quantity__lte=F("reorder_level")).count()
    if request.user.has_perm("inventory.view_inventory_valuation"):
        totals["inventory_value"] = Product.objects.aggregate(value=Sum("inventory_value"))["value"] or 0
    rows = movement_data(request, visible_movements(request.user)[:5])
    return render(request, "inventory/dashboard.html", {
        "totals": totals, "rows": rows, "currency": settings.INVENTORY_CURRENCY
    })


@login_required
@permission_required("inventory.view_product", raise_exception=True)
def products(request):
    # return render(request, "inventory/products.html", {
    #     "products": Product.objects.select_related("category").order_by("name", "id")
    # })
    try:
        qs = filter_products(Product.objects.select_related("category"), request.GET)
        page = Paginator(qs, 25).get_page(request.GET.get("page"))
    except ValidationError as exc:
        messages.error(request, "; ".join(exc.messages))
        page = Paginator(Product.objects.none(), 25).get_page(1)
    query = request.GET.copy()
    query.pop("page", None)
    return render(request, "inventory/products.html", {
        "products": page, "page": page, "query": query.urlencode()
    })

@login_required
@permission_required("inventory.view_product", raise_exception=True)
def product_detail(request, pk):
    product = get_object_or_404(Product.objects.select_related("category"), pk=pk)
    rows = movement_data(request, visible_movements(request.user).filter(product=product)[:20])
    return render(request, "inventory/product_detail.html", {"product": product, "rows": rows})


@login_required
@permission_required("inventory.view_category", raise_exception=True)
def categories(request):
    return render(request, "inventory/categories.html", {"categories": Category.objects.all()})


class ProductCreate(LoginRequiredMixin, PermissionRequiredMixin, CreateView):
    model = Product
    form_class = ProductForm
    permission_required = "inventory.add_product"
    template_name = "inventory/form.html"
    success_url = reverse_lazy("web-products")


class ProductUpdate(LoginRequiredMixin, PermissionRequiredMixin, UpdateView):
    model = Product
    form_class = ProductForm
    permission_required = "inventory.change_product"
    template_name = "inventory/form.html"
    success_url = reverse_lazy("web-products")


class CategoryCreate(LoginRequiredMixin, PermissionRequiredMixin, CreateView):
    model = Category
    form_class = CategoryForm
    permission_required = "inventory.add_category"
    template_name = "inventory/form.html"
    success_url = reverse_lazy("web-categories")


class CategoryUpdate(LoginRequiredMixin, PermissionRequiredMixin, UpdateView):
    model = Category
    form_class = CategoryForm
    permission_required = "inventory.change_category"
    template_name = "inventory/form.html"
    success_url = reverse_lazy("web-categories")


@login_required
@permission_required("inventory.delete_category", raise_exception=True)
@require_http_methods(["GET", "POST"])
def category_delete(request, pk):
    category = get_object_or_404(Category, pk=pk)
    if request.method == "POST":
        try:
            category.delete()
        except ProtectedError:
            messages.error(request, "This category still contains products.")
        else:
            messages.success(request, "Category deleted.")
        return redirect("web-categories")
    return render(request, "inventory/confirm_delete.html", {"category": category})


@login_required
@require_http_methods(["GET", "POST"])
def post_operation(request, kind):
    if kind not in OPERATION_PERMISSIONS:
        raise Http404
    require_operation(request.user, kind)
    form = StockOperationForm(request.POST if request.method == "POST" else None, kind=kind)
    if request.method == "POST" and form.is_valid():
        data = dict(form.cleaned_data)
        data["product_id"] = data.pop("product").pk
        correction = data.pop("corrects", None)
        data["corrects_id"] = correction.pk if correction else None
        try:
            movement, created = post_stock(actor=request.user, transaction_type=kind, **data)
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            messages.success(request, "Movement posted." if created else "Movement already posted.")
            return redirect("web-movement-detail", pk=movement.pk)
    return render(request, "inventory/form.html", {"form": form, "title": kind.replace("_", " ").title()})


def require_history(user):
    if not any(user.has_perm(p) for p in (
        "inventory.view_all_movements", "inventory.view_sales_report",
        "inventory.view_procurement_report", "inventory.view_inventory_valuation"
    )):
        raise PermissionDenied


@login_required
def movements(request):
    # require_history(request.user)
    # return render(request, "inventory/movements.html", {
    #     "rows": movement_data(request, visible_movements(request.user)[:100])
    # })
    require_history(request.user)
    try:
        qs = filter_movements(visible_movements(request.user), request.GET)
        page = Paginator(qs, 25).get_page(request.GET.get("page"))
    except ValidationError as exc:
        messages.error(request, "; ".join(exc.messages))
        page = Paginator(visible_movements(request.user).none(), 25).get_page(1)
    query = request.GET.copy()
    query.pop("page", None)
    return render(request, "inventory/movements.html", {
        "rows": movement_data(request, page.object_list), "page": page, "query": query.urlencode()
    })

@login_required
def movement_detail(request, pk):
    require_history(request.user)
    movement = get_object_or_404(visible_movements(request.user), pk=pk)
    return render(request, "inventory/movements.html", {
        "rows": movement_data(request, [movement])
    })