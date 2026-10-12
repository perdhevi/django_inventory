# 06 — Reports, filters, pagination, and exports

Continue from [Phase 5](05_web_interface.md). You will add reorder levels, shared filters, bounded lists, reports, CSV exports, and API documentation. Basic valuation already works; this phase makes it easier to inspect and reconcile.

## 1. Define report boundaries and add reorder levels

Current stock/valuation are **current snapshots**, not historical as-of reports. Sales/procurement/history may filter movement timestamps. Date inputs are inclusive calendar dates in the configured application timezone; implement an exclusive midnight boundary for the following day. Adjustment links do not reverse sale revenue in this base model.

Set in `config/settings.py`:

```python
TIME_ZONE = "Asia/Jakarta"
USE_TZ = True
```

Add inside `Product` in `inventory/models.py`:

```python
    reorder_level = models.PositiveIntegerField(default=0)
```

Add `reorder_level` to `ProductForm.Meta.fields` and `ProductSerializer.Meta.fields`; it is writable metadata. Low stock means `stock_quantity <= reorder_level`, including zero stock. Add this display to each product card in `templates/inventory/products.html` and to the detail template:

```html
{% if product.stock_quantity == 0 %}<p>Out of stock</p>
{% elif product.stock_quantity <= product.reorder_level %}<p>Low stock</p>{% endif %}
```

The product edit form now requires this field. In Phase 5's `test_metadata_form_ignores_balance_input` payload, add `"reorder_level": 0` so the valid metadata submission still redirects.

In `inventory/web_views.py`, import `F` alongside `Sum`. In `dashboard`, after assigning `totals`, add `totals["low_stock_products"] = Product.objects.filter(stock_quantity__lte=F("reorder_level")).count()`. In the dashboard template, display `<p>Products at or below reorder level: {{ totals.low_stock_products }}</p>`. This count includes inactive inventory and zero-stock products, matching the current-stock policy.

Add an index inside `StockTransaction.Meta` (its product/actor foreign keys are already indexed):

```python
        indexes = [models.Index(fields=["created_at", "id"], name="movement_date_idx")]
```

```sh
uv run python manage.py makemigrations inventory
uv run python manage.py migrate
```

## 2. Write filters once for web/API/reports

Create `inventory/queries.py`:

```python
from datetime import date, datetime, time, timedelta

from django.core.exceptions import ValidationError
from django.db.models import F, Q
from django.utils import timezone


def integer(params, key):
    value = params.get(key)
    if not value:
        return None
    try:
        result = int(value)
        if result < 1:
            raise ValueError
        return result
    except (TypeError, ValueError):
        raise ValidationError(f"{key} must be a positive integer.")


def filter_products(qs, params):
    search = params.get("q", "").strip()
    if search:
        qs = qs.filter(Q(sku__icontains=search) | Q(name__icontains=search))
    category = integer(params, "category")
    if category:
        qs = qs.filter(category_id=category)
    active = params.get("active", "")
    if active not in {"", "true", "false"}:
        raise ValidationError("active must be true or false.")
    if active:
        qs = qs.filter(is_active=active == "true")
    low = params.get("low", "")
    if low not in {"", "true", "false"}:
        raise ValidationError("low must be true or false.")
    if low == "true":
        qs = qs.filter(stock_quantity__lte=F("reorder_level"))
    elif low == "false":
        qs = qs.filter(stock_quantity__gt=F("reorder_level"))
    return qs.order_by("name", "id")


def filter_movements(qs, params):
    for field in ("product", "actor"):
        value = integer(params, field)
        if value:
            qs = qs.filter(**{f"{field}_id": value})
    kind = params.get("type")
    if kind:
        from .models import StockTransaction
        if kind not in StockTransaction.Type.values:
            raise ValidationError("Unknown movement type.")
        qs = qs.filter(transaction_type=kind)
    try:
        start = date.fromisoformat(params["start"]) if params.get("start") else None
        end = date.fromisoformat(params["end"]) if params.get("end") else None
        if start and end and start > end:
            raise ValueError
        zone = timezone.get_current_timezone()
        if start:
            qs = qs.filter(created_at__gte=timezone.make_aware(datetime.combine(start, time.min), zone))
        if end:
            stop = timezone.make_aware(datetime.combine(end + timedelta(days=1), time.min), zone)
            qs = qs.filter(created_at__lt=stop)
    except (ValueError, OverflowError):
        raise ValidationError("Use YYYY-MM-DD dates with start at or before end.")
    return qs.order_by("-created_at", "-id")
```

Apply filters **after** role scoping. No filter may broaden a user's queryset.

In `inventory/views.py`, import these helpers. Add inside `ProductViewSet`:

```python
    def get_queryset(self):
        try:
            return filter_products(super().get_queryset(), self.request.query_params)
        except DjangoValidationError as exc:
            raise ValidationError(exc.messages) from exc
```

Replace `StockTransactionViewSet.get_queryset`:

```python
    def get_queryset(self):
        try:
            return filter_movements(visible_movements(self.request.user), self.request.query_params)
        except DjangoValidationError as exc:
            raise ValidationError(exc.messages) from exc
```

In settings, merge into `REST_FRAMEWORK`:

```python
REST_FRAMEWORK.update({
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 25,
})
```

API lists now return `{count, next, previous, results}` instead of arrays; update any consumers accordingly. Explicit secondary IDs keep ordering stable for a fixed dataset. Page numbers are not a consistent snapshot of a changing dataset.

For browser pagination, import `Paginator` and the filter helpers in `inventory/web_views.py`. Replace the `products` function body (retain its decorators):

```python
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
```

Replace the `movements` function body (retain `@login_required`):

```python
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
```

Create `templates/inventory/_pagination.html` and include it in products/movements templates after the results:

```html
{% if page %}<nav aria-label="Pagination">
{% if page.has_previous %}<a href="?{{ query }}&amp;page={{ page.previous_page_number }}">Previous</a>{% endif %}
<span>Page {{ page.number }} of {{ page.paginator.num_pages }}</span>
{% if page.has_next %}<a href="?{{ query }}&amp;page={{ page.next_page_number }}">Next</a>{% endif %}
</nav>{% endif %}
```

Add a GET search form before product results:

```html
<form method="get">
<label for="q">SKU or name</label><input id="q" name="q" value="{{ request.GET.q }}">
<label for="category">Category ID</label><input id="category" name="category" value="{{ request.GET.category }}">
<label for="active">Active status</label><select id="active" name="active"><option value="">All</option><option value="true">Active</option><option value="false">Inactive</option></select>
<label for="low">Stock status</label><select id="low" name="low"><option value="">All</option><option value="true">Low stock</option><option value="false">Above reorder level</option></select>
<button>Filter</button>
</form>
```

For movement lists, add a GET form with labeled `product`, `actor`, `type`, `start`, `end` inputs (use `type="date"` for dates). These names map directly to the shared filters. Preserve selected controls using `request.GET` when extending the form.

## 3. Build one report calculation for all interfaces

Create `inventory/reports.py`:

```python
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
        "generated_at": timezone.now().isoformat(), "columns": columns, "rows": rows,
        "totals": {k: (format(v or Decimal("0"), ".6f") if k != "quantity" else str(v or 0))
                   for k, v in totals.items()},
        "count": count, "page": number, "pages": pages,
    }
```

Totals cover the entire filtered queryset, not just the displayed page. Movement quantity totals are unsigned activity units, not net stock change. Unit price fields are not summed. Mixed history reports omit financial columns; typed reports apply the Phase 4 matrix.

## 4. Add authorized JSON, HTML, and CSV endpoints

Create `inventory/report_views.py`:

```python
import csv

from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError as DjangoValidationError
from django.http import HttpResponse
from django.shortcuts import render
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from .reports import report_payload


class ReportView(APIView):
    def get(self, request, kind):
        try:
            data = report_payload(request.user, kind, request.query_params)
        except DjangoValidationError as exc:
            raise ValidationError(exc.messages) from exc
        return Response(data)


def csv_cell(value):
    text = "" if value is None else str(value)
    # Protect user text even when a formula marker follows whitespace/control characters.
    if text.lstrip().startswith(("=", "+", "-", "@")) or text.startswith(("\t", "\r", "\n")):
        return "'" + text
    return text


@login_required
def report_page(request, kind):
    try:
        data = report_payload(request.user, kind, request.GET)
    except DjangoValidationError as exc:
        return HttpResponse("; ".join(exc.messages), status=400, content_type="text/plain")
    query = request.GET.copy()
    query.pop("page", None)
    return render(request, "inventory/report.html", {"report": data, "query": query.urlencode()})


@login_required
def report_csv(request, kind):
    try:
        data = report_payload(request.user, kind, request.GET, exporting=True)
    except DjangoValidationError as exc:
        return HttpResponse("; ".join(exc.messages), status=400, content_type="text/plain")
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="{kind}-{data["currency"]}.csv"'
    writer = csv.writer(response)
    writer.writerow([f"{column} ({data['currency']})" if column in {
        "unit_cost", "selling_price", "revenue", "cogs", "gross_profit", "value_change",
        "average_unit_cost", "inventory_value"
    } else column for column in data["columns"]])
    for row in data["rows"]:
        writer.writerow([csv_cell(row[column]) for column in data["columns"]])
    return response
```

Django `PermissionDenied` produces 403 in both frameworks. CSV is delivered through the session-protected browser endpoint, including for users whose API also uses JWT. Preserve decimal strings; formula guarding may prefix negative textual amounts with an apostrophe for safe spreadsheet opening.

In `inventory/urls.py`, import `ReportView` and add to its explicit path list:

```python
path("reports/<str:kind>/", ReportView.as_view(), name="api-report"),
```

In `inventory/web_urls.py`, import `report_page`, `report_csv` and add:

```python
path("reports/<str:kind>/", report_page, name="web-report"),
path("reports/<str:kind>/csv/", report_csv, name="web-report-csv"),
```

Create `templates/inventory/report.html`:

```html
{% extends 'base.html' %}
{% block content %}
<h1>{{ report.kind|title }} report</h1><p>Currency: {{ report.currency }} · Rows: {{ report.count }}</p>
<form method="get">
{% if report.kind == 'stock' or report.kind == 'valuation' %}
<label for="q">SKU/name</label><input id="q" name="q" value="{{ request.GET.q }}">
{% else %}
<label for="start">From</label><input type="date" id="start" name="start" value="{{ request.GET.start }}">
<label for="end">Through</label><input type="date" id="end" name="end" value="{{ request.GET.end }}">
<label for="product">Product ID</label><input id="product" name="product" value="{{ request.GET.product }}">
{% endif %}<button>Filter</button></form>
<dl>{% for key, value in report.totals.items %}<dt>{{ key }}</dt><dd>{{ value }}</dd>{% endfor %}</dl>
{% if perms.inventory.export_reports %}<a href="{% url 'web-report-csv' report.kind %}?{{ query }}">Export CSV</a>{% endif %}
<div class="cards">{% for row in report.rows %}<article><dl>
{% for key, value in row.items %}<dt>{{ key }}</dt><dd>{{ value }}</dd>{% endfor %}
</dl></article>{% empty %}<p>No matching records.</p>{% endfor %}</div>
<p>Page {{ report.page }} of {{ report.pages }}</p>
{% if report.page > 1 %}<a href="?{{ query }}&amp;page={{ report.page|add:'-1' }}">Previous</a>{% endif %}
{% if report.page < report.pages %}<a href="?{{ query }}&amp;page={{ report.page|add:'1' }}">Next</a>{% endif %}
{% endblock %}
```

Add role-aware report links to `base.html`: stock for `view_product`, sales for `view_sales_report`, procurement for `view_procurement_report`, valuation for `view_inventory_valuation`, using `{% url 'web-report' 'sales' %}` etc. The endpoint checks remain mandatory even if links are hidden.

## 5. Document the actual API

```sh
uv add drf-spectacular
```

Add `drf_spectacular` to `INSTALLED_APPS`; merge in settings:

```python
REST_FRAMEWORK["DEFAULT_SCHEMA_CLASS"] = "drf_spectacular.openapi.AutoSchema"
SPECTACULAR_SETTINGS = {"TITLE": "Inventory API", "VERSION": "1.0.0", "SERVE_INCLUDE_SCHEMA": False}
```

In `config/urls.py`, import `SpectacularAPIView`, `SpectacularSwaggerView` and `IsAdminUser`. Add:

```python
path("api/schema/", SpectacularAPIView.as_view(permission_classes=[IsAdminUser]), name="schema"),
path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema", permission_classes=[IsAdminUser]), name="api-docs"),
```

In `inventory/views.py`, import `extend_schema`, `OpenApiTypes` from `drf_spectacular.utils`. Decorate stock `create` with:

```python
    @extend_schema(request=StockOperationSerializer,
                   responses={201: StockTransactionSerializer, 200: StockTransactionSerializer})
```

Decorate `ValuationView.get` and `ReportView.get` with `@extend_schema(responses=OpenApiTypes.OBJECT)`; import the helpers in `report_views.py` too. Mark `MeView.get` the same way in `accounts/views.py`. Add filter query parameters with `OpenApiParameter` as the next documentation exercise. The history schema is a superset: document that financial keys are omitted by role. See [drf-spectacular setup](https://drf-spectacular.readthedocs.io/en/latest/readme.html).

```sh
uv run python manage.py spectacular --file schema.yml --validate
```

Inspect warnings and generated stock request/response methods before calling the schema complete. Open `/api/docs/` with your staff session.

## 6. Verify report reconciliation and export permissions

Create `inventory/test_reports.py`:

```python
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.management import call_command
from django.test import TestCase

from .models import Category, Product
from .queries import filter_products
from .report_views import csv_cell
from .reports import report_payload
from .services import post_stock


class ReportTests(TestCase):
    def setUp(self):
        call_command("setup_roles", verbosity=0)
        self.admin = get_user_model().objects.create_superuser(username="report-admin", password="test-password")
        self.sales = get_user_model().objects.create_user(username="report-sales")
        self.sales.groups.add(Group.objects.get(name="Sales"))
        self.product = Product.objects.create(sku="REPORT-1", name="Report", price="40.00", reorder_level=16,
                                             category=Category.objects.create(name="Report"))
        for cost in ("20.00", "30.00"):
            post_stock(actor=self.admin, product_id=self.product.pk, transaction_type="PROCUREMENT",
                       quantity=10, unit_cost=cost, request_key=uuid4())
        post_stock(actor=self.admin, product_id=self.product.pk, transaction_type="SALE",
                   quantity=4, selling_price="40.00", request_key=uuid4())

    def test_totals_match_history_and_snapshot(self):
        sales = report_payload(self.admin, "sales", {})
        self.assertEqual(sales["totals"]["revenue"], "160.000000")
        self.assertEqual(sales["totals"]["cogs"], "100.000000")
        self.assertEqual(report_payload(self.admin, "valuation", {})["totals"]["inventory_value"], "400.000000")
        self.assertEqual(filter_products(Product.objects.all(), {"low": "true"}).count(), 1)

    def test_export_reuses_visibility_and_dates_are_validated(self):
        sales = report_payload(self.sales, "sales", {}, exporting=True)
        self.assertIn("revenue", sales["columns"])
        self.assertNotIn("cogs", sales["columns"])
        with self.assertRaises(PermissionDenied):
            report_payload(self.sales, "valuation", {}, exporting=True)
        with self.assertRaises(ValidationError):
            report_payload(self.admin, "sales", {"start": "not-a-date"})
        self.assertEqual(csv_cell("  =1+1"), "'  =1+1")
```

```sh
uv run python manage.py test
uv run python manage.py check
uv run python manage.py makemigrations --check --dry-run
```

Manually open `/reports/sales/?product=YOUR_PRODUCT_ID`, export CSV, and compare with `/api/reports/sales/` using the same filters and role. Check exact reorder threshold, zero stock, inclusive end dates, invalid dates, empty reports, second pages, and Viewer export denial. Use Django's query inspection tools to measure before adding further indexes; `select_related` already avoids product/actor query loops.

## 7. Review changed files

```text
inventory/models.py + migrations/        reorder level + timestamp index
inventory/forms.py + serializers.py      expose reorder metadata
inventory/queries.py                     shared validated filters
inventory/reports.py + report_views.py   shared totals and safe exports
inventory/views.py + web_views.py        filtered paginated lists
inventory/urls.py + web_urls.py          report routes
inventory/test_reports.py
templates/inventory/ + base.html         filters, pagination, reports, indicators
config/settings.py + urls.py            timezone, pagination, schema
pyproject.toml + uv.lock
```

Commit after reports reconcile and role checks pass. Next: [Phase 7 — Deployment](07_deployment.md). You can separately add [optional Google sign-in](integrations/google_authentication.md) after this phase.
