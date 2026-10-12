# 06 — Reports, filters, pagination, and exports

Continue from [Phase 5](05_web_interface.md). You will add reorder levels, shared filters, bounded lists, reports, CSV exports, and API documentation. Basic valuation already works; this phase makes it easier to inspect and reconcile.

This guide uses `config` as the tutorial package name. In this checkout, use `django_inventory/settings.py` and `django_inventory/urls.py` wherever those `config` paths appear. Run commands from the directory containing `manage.py`. Keep the PostgreSQL environment variables from Phase 3 loaded in the same terminal; Django does not automatically read `.env.database`. Keep the existing authentication, permissions, templates, and session settings when merging the additions below.

## Before you start: confirm the Phase 5 handoff

The expected starting point is the completed Phase 5 application, not the Phase 2 API or the separately assembled `.validation/build` application. Check these files and behaviors:

| Area | Expected before Phase 6 |
| --- | --- |
| Models/services | Active products, stored stock/value, typed immutable movements, and atomic `post_stock()` with UUID retries; no `reorder_level` yet |
| Roles/API | Five business groups from `setup_roles`, JWT/session authentication, `visible_movements()` and financial-field restrictions |
| Browser | `inventory/forms.py`, `web_views.py`, `web_urls.py`, account templates, inventory templates, and `static/inventory.css` |
| Routes | Login/logout/password change, dashboard, catalog, posting and history; no report or schema routes yet |
| Lists | Products are unpaginated; movement list shows the latest 100 authorized rows; product detail shows 20 and dashboard shows five |
| Settings | PostgreSQL, `INVENTORY_CURRENCY`, template context processors and session redirects; no global API pagination/schema class yet |

Run the baseline checks before editing:

```sh
uv run python manage.py check
uv run python manage.py showmigrations --plan
uv run python manage.py makemigrations --check --dry-run
uv run python manage.py test
```

All required migrations should show `[X]`; the dry run should report no changes. In this checkout the inventory baseline ends at `0003_alter_stocktransaction_options`; migration numbers can differ in another tutorial implementation. The baseline suite currently has 22 tests. Run it on PostgreSQL so the concurrent-sale test executes rather than being skipped on SQLite. Phase 5 itself adds no migration. Resolve baseline failures before using Phase 6 results as evidence.

Also complete the Phase 5 role-account and browser walkthrough. Automated tests do not establish that development users have groups assigned or that keyboard/narrow-screen behavior is correct. See [validation notes](VALIDATION.md) for observed checks and remaining manual work.

## 1. Define report boundaries and add reorder levels

Current stock/valuation are **current snapshots**, not historical as-of reports. Sales/procurement/history may filter movement timestamps. Date inputs are inclusive calendar dates in the configured application timezone; implement an exclusive midnight boundary for the following day. Adjustment links do not reverse sale revenue in this base model.

### 1.1 Confirm the existing timezone settings

Open `django_inventory/settings.py` (`config/settings.py` in the tutorial project) and find the existing `TIME_ZONE` and `USE_TZ` assignments in the internationalization section. **Use the existing lines; do not add another copy.** This application uses UTC calendar dates:

```python
TIME_ZONE = "UTC"
USE_TZ = True
```

If these values are already configured, leave them as they are. Keep `USE_TZ = True`. Report dates therefore run from UTC midnight through, but excluding, the following day's UTC midnight. Django supports a separately activated timezone through `timezone.activate()` or `timezone.override()`; the filters below use `get_current_timezone()`, so they follow that active timezone when one is set and otherwise default to `TIME_ZONE`. No user-specific timezone selection is introduced here. Changing timezone settings does not rewrite stored timestamps and needs no migration.

To inspect the default and active timezone, run `uv run python manage.py shell` and enter:

```text
from django.conf import settings
from django.utils import timezone
print("Default:", settings.TIME_ZONE)
print("Active:", timezone.get_current_timezone_name())
```

Both should report `UTC` in an ordinary shell. A shell cannot inspect another request's activated timezone, so Step 3 also returns the active timezone in each report's JSON, and Step 4 displays it on the report page.

### 1.2 Add the product's reorder threshold

`reorder_level` is the number of units at which a product should be flagged for replenishment. It is a threshold you set, measured in the same units as `stock_quantity`. It does not add stock, change valuation, create a movement, or automatically place an order.

Open `inventory/models.py`, find `class Product(models.Model):`, and add this line **directly below `stock_quantity`**, with the same four-space indentation:

```python
    reorder_level = models.PositiveIntegerField(default=0)
```

The surrounding lines should look like this:

```text
class Product(models.Model):
    ... existing product fields ...
    stock_quantity = models.PositiveIntegerField(default=0)
    reorder_level = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    ... remaining fields and methods ...

    class Meta:
        ordering = ["name", "id"]
        ... existing constraints ...
```

This is a placement illustration; keep the actual surrounding code. **Do not put `reorder_level` inside `Product.Meta`, `save()`, or `StockTransaction`.** Model `Meta` configures ordering/constraints; database fields belong directly on the model class. If you already added this line inside `Product.Meta`, move that line to the position above instead of adding a duplicate.

`PositiveIntegerField` allows whole numbers including zero. Negative values and fractional thresholds are invalid. `default=0` gives existing products a threshold of zero when migrated and supplies the default for new model instances. A zero threshold flags only zero stock; it does not disable stock warnings. For example:

| Stock quantity | Reorder level | Display |
| --- | --- | --- |
| 16 | 10 | No stock warning |
| 10 | 10 | Low stock |
| 4 | 10 | Low stock |
| 0 | 10 | Out of stock |
| 0 | 0 | Out of stock |

Both low stock and out of stock count toward the dashboard's `stock_quantity <= reorder_level` total.

### 1.3 Allow authorized users to edit the threshold

In `inventory/forms.py`, append `"reorder_level"` to the existing `ProductForm.Meta.fields` list. The resulting list is `["sku", "name", "category", "description", "price", "is_active", "reorder_level"]`. The shared product form template renders the new field automatically. Keep `stock_quantity`, `average_unit_cost`, and `inventory_value` excluded from this metadata form.

In `inventory/serializers.py`, add `"reorder_level"` to `ProductSerializer.Meta.fields`, for example immediately after `"stock_quantity"`. Do not add it to `read_only_fields`: users already authorized to create/change product metadata should be able to set it. Keep the existing balance fields read-only and preserve the financial visibility checks. No stock-service change is needed; the existing metadata-save behavior includes this new ordinary field.

The browser form requires a value because the model field does not use `blank=True`; enter `0` when no positive threshold is needed. In Phase 5's `test_metadata_form_ignores_balance_input` payload in `inventory/test_web.py`, add `"reorder_level": 0` so the valid metadata submission still redirects. Model defaults do not make a missing browser form field valid.

### 1.4 Display stock warnings and the dashboard count

This step changes three templates and the dashboard view. Complete the field and migration steps before loading these pages. Low stock means `stock_quantity <= reorder_level`, including zero stock.

**A. Add a warning to each product card.** Open `templates/inventory/products.html`. Find `{% for product in products %}` and the `<article>` inside that loop. Insert the following immediately after the stock paragraph and **before that article's closing `</article>`**:

```html
{% if product.stock_quantity == 0 %}<p>Out of stock</p>
{% elif product.stock_quantity <= product.reorder_level %}<p>Low stock</p>{% endif %}
```

Your existing stock paragraph and `</article>` may share one line. Split them so there is room for the warning. The complete product-list template at this point should look like this; retain any additional content you have already added:

```django
{% extends 'base.html' %}
{% block content %}
<h1>Products</h1>
{% if perms.inventory.add_product %}
  <a href="{% url 'web-product-create' %}">Add product</a>
{% endif %}
<div class="cards">
  {% for product in products %}
    <article>
      <a href="{% url 'web-product-detail' product.pk %}">{{ product.sku }} — {{ product.name }}</a>
      <p>Stock: {{ product.stock_quantity }} · Active: {{ product.is_active|yesno:'Yes,No' }}</p>
      {% if product.stock_quantity == 0 %}
        <p>Out of stock</p>
      {% elif product.stock_quantity <= product.reorder_level %}
        <p>Low stock</p>
      {% endif %}
    </article>
  {% empty %}
    <p>No products yet.</p>
  {% endfor %}
</div>
{% endblock %}
```

The loop supplies a different `product` for each card. A warning placed after `{% endfor %}` is outside that loop and cannot show each product's status. If you already placed the warning there, move it into the article and remove the outside copy. Leave `{% empty %}` for the no-products message.

The zero-stock check comes first so a product with zero units displays only “Out of stock.” Otherwise, a positive quantity at or below the threshold displays “Low stock.” Above the threshold, neither warning appears. These text labels work without additional CSS and do not rely on color to communicate the status.

**B. Add the same warning to product detail.** Open `templates/inventory/product_detail.html`. Find the paragraph containing SKU, category, and stock. Insert the same conditional immediately below it, before the description/selling-price paragraphs. This page already receives one `product` from `product_detail()`, so no loop or view change is needed. Keep the warning outside `{% if perms.inventory.view_inventory_valuation %}` so anyone allowed to view the product sees its quantity status. Keep average cost and inventory value inside their existing permission check. If the conditional is already on this page, move it if necessary instead of adding another copy.

**C. Calculate the dashboard count.** Open `inventory/web_views.py`. Find the existing `from django.db.models import Sum` import and add `F`, resulting in `from django.db.models import F, Sum`. If both are already imported, leave the import as it is; their order does not matter.

Inside `dashboard()`, immediately below `totals = Product.objects.aggregate(units=Sum("stock_quantity"))`, add this assignment, indented four spaces like the other function statements:

```text
    totals["low_stock_products"] = Product.objects.filter(stock_quantity__lte=F("reorder_level")).count()
```

Keep it **before** the `if request.user.has_perm("inventory.view_inventory_valuation"):` line. The start of the function should have this structure:

```text
@login_required
@permission_required("inventory.view_product", raise_exception=True)
def dashboard(request):
    totals = Product.objects.aggregate(units=Sum("stock_quantity"))
    totals["low_stock_products"] = Product.objects.filter(stock_quantity__lte=F("reorder_level")).count()
    if request.user.has_perm("inventory.view_inventory_valuation"):
        totals["inventory_value"] = Product.objects.aggregate(value=Sum("inventory_value"))["value"] or 0
    ... keep the existing rows assignment and render() call ...
```

Do not replace the function with the illustration's `...` line. Its existing `render()` already passes `"totals": totals` to the template, so no new context entry is needed. If the count assignment is already present, keep one copy.

`stock_quantity__lte` means “stock quantity less than or equal to.” `F("reorder_level")` compares each product's stock against that same product's threshold in the database. `.count()` counts matching **products**, not their units. For example, three products with stock/threshold pairs `0/0`, `4/10`, and `16/10` produce a dashboard count of **2**. This includes inactive products and zero-stock products, matching the current-stock policy. The count contains no financial data; the existing dashboard product-view permission still applies.

**D. Display the count on the dashboard.** Open `templates/inventory/dashboard.html`. Insert this paragraph after the “Units in stock” paragraph and before the valuation conditional:

```django
<p>Products at or below reorder level: {{ totals.low_stock_products }}</p>
```

The template at this point should look like this:

```django
{% extends 'base.html' %}
{% block content %}
<h1>Dashboard</h1>
<p>Units in stock: {{ totals.units|default_if_none:0 }}</p>
<p>Products at or below reorder level: {{ totals.low_stock_products }}</p>
{% if perms.inventory.view_inventory_valuation %}
  <p>Inventory value ({{ currency }}): {{ totals.inventory_value }}</p>
{% endif %}
<h2>Recent movements</h2>
{% include 'inventory/_movements.html' %}
{% endblock %}
```

After applying the migration in Step 1.5, open the product list, a product detail page, and the dashboard. Check zero stock, stock exactly equal to the threshold, and stock above it against the examples in Step 1.2. The list/detail labels should agree, and the dashboard should count all products at or below their thresholds. With no matching products, it should display `0`. A blank dashboard count usually means the view assignment or the template variable name is missing; missing list warnings usually mean the conditional sits outside the loop. Use an account with `view_product` permission for these checks.

### 1.5 Create and apply the database migration

The model edits describe the new database structure, but they do not change the database until you generate and apply a migration. This step adds two things: the product's reorder threshold column and an index for movement date/order queries. Timezone and template changes do not generate migrations.

**A. Add the movement date index.** Open `inventory/models.py`, find `class StockTransaction(models.Model):`, then find its existing nested `class Meta:` near the bottom. Add the following immediately after its `ordering` line, with the same eight-space indentation:

```python
        indexes = [models.Index(fields=["created_at", "id"], name="movement_date_idx")]
```

The placement should look like this:

```text
class StockTransaction(models.Model):
    ... existing movement fields ...

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [models.Index(fields=["created_at", "id"], name="movement_date_idx")]
        constraints = [
            ... keep the existing quantity constraint ...
        ]
        permissions = [
            ... keep all existing business permissions ...
        ]
```

Keep the actual fields, constraints, and permissions; the `...` lines only illustrate placement. Use the existing `StockTransaction.Meta`, not a second `Meta` block and not `Product.Meta`. If an `indexes` list already exists, append this index to that list instead of defining `indexes` twice. If `movement_date_idx` is already present, do not add another copy.

This index stores an efficient lookup/order structure for `created_at` and `id`. It can help the dated movement lists added in Step 2; actual query performance still needs measurement. It does not change movement data or permissions. The product/actor foreign keys already have indexes, so this step does not add duplicate indexes for them.

**B. Check the model and database connection.** Save the edited files. Open a terminal in the project root containing `manage.py`, using the Phase 3 PostgreSQL connection variables. If you opened a new terminal, load/set those variables again. Django does not read `.env.database` automatically, and Compose's `--env-file` does not set variables in your Django terminal. If you use the local Compose database and it is stopped, start it:

```sh
docker compose --env-file .env.database -f compose.database.yml up -d --wait db
```

Skip that command if you use an installed PostgreSQL server. Then run:

```sh
uv run python manage.py check
```

Expect `System check identified no issues (0 silenced).` Resolve errors before generating the migration. In particular, `reorder_level` belongs directly on `Product`, whereas `indexes` belongs inside `StockTransaction.Meta`.

**C. Generate the migration file.** Run:

```sh
uv run python manage.py makemigrations inventory
```

For the Phase 5 baseline in this checkout, expected output is similar to:

```text
Migrations for 'inventory':
  inventory/migrations/0004_product_reorder_level_and_more.py
    + Add field reorder_level to product
    + Create index movement_date_idx on field(s) created_at, id of model stocktransaction
```

Use the filename Django actually generates; numbering can differ if you already have additional migrations. Open that file in `inventory/migrations/` and review its `operations`: an `AddField` for `Product.reorder_level` with default zero and an `AddIndex` for `StockTransaction`. It should depend on your latest inventory migration. There should be no field removals, table deletions, balance changes, or recreation of Phase 3 fields. Unexpected operations indicate other model changes that need review before applying.

`makemigrations` writes a versioned Python file; it does not yet add the column/index to PostgreSQL. Keep the generated migration with the application source so another environment can apply the same change.

If you already generated this migration, `No changes detected in app 'inventory'` can be correct. Inspect the existing migration and its application state below rather than forcing a duplicate migration.

**D. Preview and apply it to the configured database.** Run these commands one at a time:

```sh
uv run python manage.py showmigrations inventory
uv run python manage.py migrate --plan
uv run python manage.py migrate
```

Before applying, the new inventory migration should have `[ ]` in `showmigrations`; earlier completed migrations should have `[X]`. The plan shows pending operations across all apps. At the validated Phase 5 baseline, only the new inventory migration should be pending. Review any additional pending migrations before continuing.

Successful application should include a line similar to:

```text
Applying inventory.0004_product_reorder_level_and_more... OK
```

Existing products receive `reorder_level=0`; existing balances and movement amounts are preserved. Set realistic thresholds through product editing afterward. Do not run opening reconciliation again just to add reorder levels. If the migration is already applied, `No migrations to apply` is expected. Do not use `--fake` to bypass a missing column or index.

**E. Verify database state and behavior.** Run:

```sh
uv run python manage.py showmigrations inventory
uv run python manage.py migrate --check
uv run python manage.py makemigrations --check --dry-run
uv run python manage.py check
uv run python manage.py test inventory.test_web
```

The new migration should now show `[X]`. `migrate --check` should exit successfully with no pending migrations; the migration dry run should report `No changes detected`. These check different things: the first checks whether migration files have been applied, and the second checks whether models need another migration. System checks and the browser tests should pass. The tests use a separate test database; ensure your local PostgreSQL user can create it. Step 1.3's metadata test payload must include `reorder_level`.

Restart the development server if it stopped on a model/schema error, then open the product edit form. Note the product's stock and, for an authorized valuation user, its inventory value. Set the threshold equal to a positive stock quantity and save: the list/detail should show Low stock. Set it below the stock quantity and save: the warning should disappear. A zero-stock product should always show Out of stock. Confirm saving either threshold leaves stock quantity and inventory value unchanged, and check the dashboard count as described in Step 1.4.

Common issues at this step:

| Message or symptom | What to check |
| --- | --- |
| `class Meta` has an invalid `reorder_level` attribute | Move the field out of `Product.Meta` and directly below `Product.stock_quantity` |
| `KeyError: 'POSTGRES_DB'` (or another PostgreSQL variable) | Set the Phase 3 connection variables in this terminal |
| Connection refused | Start PostgreSQL and check host/port; the documented Compose host port is 55432 |
| Password authentication failed | Use the database role's actual password; editing an env file does not change an initialized database's credentials |
| Database column `reorder_level` does not exist | Apply the migration to the same database used by the server; check both terminals' connection settings |
| `No changes detected` before a migration exists | Save `models.py` and confirm the field/index are in the correct classes |
| Product edit returns form errors or the metadata test fails | Supply a nonnegative integer `reorder_level`; include it in the test POST payload |

Once these checks pass, continue to Step 2. Keep the generated migration in your eventual Phase 6 commit alongside the model, form, serializer, view, and template changes.

## 2. Write filters once for web/API/reports

Complete the following sub-steps in order. Paginating a view does not automatically display navigation links; both list templates must include the partial in Step 2.5.

### 2.1 Create the shared query helpers

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

Product filters are `q` (SKU/name substring), `category` (positive ID), `active` and `low` (exact lowercase `true`/`false`). Movement filters are `product`, `actor` (positive IDs), `type` (for example `SALE` or `PROCUREMENT`), `start`, and `end`. Blank supported parameters are ignored; unknown parameter names are ignored by these helpers. A valid nonexistent ID produces an empty result. Invalid supported values produce API 400 responses; browser list views show an error and empty results. Report views return 400 for invalid input.

### 2.2 Connect filters to the API views

In `inventory/views.py`, add this import at the top of the file alongside the existing local imports, **outside all classes and methods**:

```text
from .queries import filter_products, filter_movements
```

The leading dot imports from `inventory/queries.py`, which you created above. Do not use `import queries` or place the import inside `ProductViewSet`. Both view sets use these helpers.

Also confirm these existing Phase 3/4 imports are present. Keep one copy of each, merging with existing imports where needed:

```text
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework.exceptions import APIException, ValidationError
from .access import CatalogPermission, MovementPermission, ValuationPermission, visible_movements
```

Here `DjangoValidationError` is raised by the shared query helpers; DRF's `ValidationError` converts it into an API 400 response. Keep the alias so these two different exception classes do not overwrite each other's names.

Add the following method inside `ProductViewSet`, with the same indentation as `perform_destroy()`; retain the existing class attributes and methods:

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

### 2.3 Enable API pagination in the existing settings

Open `django_inventory/settings.py` (`config/settings.py` in the tutorial project). Find the existing active `REST_FRAMEWORK = {...}` dictionary. Add this update immediately after its closing `}`, at the top level with no indentation. Preserve its authentication and permission settings. If the update is already present, keep one copy; do not create a second dictionary:

```python
REST_FRAMEWORK.update({
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 25,
})
```

API lists now return `{count, next, previous, results}` instead of arrays; update any consumers accordingly. Explicit secondary IDs keep ordering stable for a fixed dataset. Page numbers are not a consistent snapshot of a changing dataset.

The global setting paginates category lists too. Existing detail and stock-posting responses keep their shape. Browser lists and reports use `Paginator.get_page()`: invalid page text falls back to page one, and out-of-range numbers resolve to the last page. DRF list endpoints instead reject invalid/out-of-range pages with 404. Reset `page` when submitting a new filter form, and preserve the other filters in navigation links.

### 2.4 Filter and paginate the browser views

For browser pagination, open `inventory/web_views.py` and add these imports at the top of the file, outside all functions:

```text
from django.core.paginator import Paginator
from .queries import filter_products, filter_movements
```

Keep the existing browser-view imports used by the replacement bodies:

```text
from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from .access import OPERATION_PERMISSIONS, require_operation, visible_movements
from .models import Category, Product
```

Unlike the API module, browser views catch Django's `ValidationError` directly and display its messages. Do not import DRF's `ValidationError` into this file. Keep any additional imports needed by the other browser views, including `F` and `Sum` from Step 1.4.

Replace the `products` function body (retain its `def products(request):` line and both existing decorators):

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

### 2.5 Add visible pagination links to both lists

Create `templates/inventory/_pagination.html` with the following content. It uses the `page` and `query` context values supplied by Step 2.4:

```html
{% if page %}<nav aria-label="Pagination">
{% if page.has_previous %}<a href="?{{ query }}&amp;page={{ page.previous_page_number }}">Previous</a>{% endif %}
<span>Page {{ page.number }} of {{ page.paginator.num_pages }}</span>
{% if page.has_next %}<a href="?{{ query }}&amp;page={{ page.next_page_number }}">Next</a>{% endif %}
</nav>{% endif %}
```

Creating the partial does not display it automatically. In `templates/inventory/products.html`, insert `{% include 'inventory/_pagination.html' %}` after the cards' closing `</div>` and before `{% endblock %}`. Place it outside the product loop. In `templates/inventory/movements.html`, add the same include after `{% include 'inventory/_movements.html' %}` and before `{% endblock %}`. Keep both includes inside the content block.

The movement detail view shares `movements.html` but does not supply `page`; the partial's conditional hides pagination on that detail page. With 25 or fewer matching rows, the list shows its page number but has no Next link. Use more than 25 matching rows to check navigation. The `query` value preserves filters while excluding the old page number.

### 2.6 Add product and movement filter forms

In `templates/inventory/products.html`, add this GET form after the heading/Add product link and before `<div class="cards">`, outside the product loop:

```html
<form method="get">
<label for="q">SKU or name</label><input id="q" name="q" value="{{ request.GET.q }}">
<label for="category">Category ID</label><input id="category" name="category" value="{{ request.GET.category }}">
<label for="active">Active status</label><select id="active" name="active"><option value="">All</option><option value="true" {% if request.GET.active == 'true' %}selected{% endif %}>Active</option><option value="false" {% if request.GET.active == 'false' %}selected{% endif %}>Inactive</option></select>
<label for="low">Stock status</label><select id="low" name="low"><option value="">All</option><option value="true" {% if request.GET.low == 'true' %}selected{% endif %}>Low stock</option><option value="false" {% if request.GET.low == 'false' %}selected{% endif %}>Above reorder level</option></select>
<button>Filter</button>
</form>
```

In `templates/inventory/movements.html`, add a GET form before the `_movements.html` include with labeled `product`, `actor`, `type`, `start`, `end` inputs (use `type="date"` for dates). These names map directly to the shared filters. Preserve selected controls using `request.GET` when extending the form. Wrap that form in `{% if page %}...{% endif %}` to hide it on the shared movement detail page. Neither form should submit a `page` field: changing filters starts from page one.

Use this movement form:

```django
{% if page %}
<form method="get">
  <label for="product">Product ID</label>
  <input id="product" name="product" type="number" min="1" value="{{ request.GET.product }}">
  <label for="actor">Actor ID</label>
  <input id="actor" name="actor" type="number" min="1" value="{{ request.GET.actor }}">
  <label for="type">Movement type</label>
  <input id="type" name="type" value="{{ request.GET.type }}" placeholder="SALE or PROCUREMENT">
  <label for="start">From</label>
  <input id="start" name="start" type="date" value="{{ request.GET.start }}">
  <label for="end">Through</label>
  <input id="end" name="end" type="date" value="{{ request.GET.end }}">
  <button type="submit">Filter</button>
</form>
{% endif %}
```

Movement type accepts the exact uppercase values `SALE`, `PROCUREMENT`, `OPENING_BALANCE`, `ADJUSTMENT_IN`, and `ADJUSTMENT_OUT`; leave it blank for all movements allowed by the user's role. The server validates all input even when browser controls provide basic validation. These read-only GET forms do not need a CSRF token.

### 2.7 Verify filtering and pagination

After saving, run `uv run python manage.py check`, then open `/products/?q=YOUR_SKU` and `/movements/?type=SALE` with an authorized account. Check the API equivalents `/api/products/?q=YOUR_SKU` and `/api/stock_transactions/?type=SALE` with the same role. If you get `NameError` for `filter_products`/`filter_movements`, check the `.queries` import in the module named by the error; if `Paginator` is undefined, check the browser module's paginator import. A missing `queries` module usually means `inventory/queries.py` has not been created or the relative import's leading dot is missing. System checks alone may not detect names used only when a request executes a view, so exercise both filtered lists.

Check a second page with more than 25 matching rows and verify that links retain filters. Try `category=-1` on products and `start=bad` on movements: APIs should return 400; browser lists should show an error and empty results. Use a Sales account to confirm `type=PROCUREMENT` cannot expose procurement history. Run `uv run python manage.py test` and the migration consistency checks from Step 1.5 afterward. The Phase 5 tests alone do not cover every new filter or pagination link.

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
        "timezone": timezone.get_current_timezone_name(),
        "generated_at": timezone.now().isoformat(), "columns": columns, "rows": rows,
        "totals": {k: (format(v or Decimal("0"), ".6f") if k != "quantity" else str(v or 0))
                   for k, v in totals.items()},
        "count": count, "page": number, "pages": pages,
    }
```

Totals cover the entire filtered queryset, not just the displayed page. Movement quantity totals are unsigned activity units, not net stock change. Unit price fields are not summed. Mixed history reports omit financial columns; typed reports apply the Phase 4 matrix.

For a controlled example, receive 10 units at 20.00 and another 10 at 30.00, then sell four at 40.00. Current stock is 16, average cost is 25.000000, and inventory value is 400.000000. The sales report totals are quantity 4, revenue 160.000000, COGS 100.000000, and gross profit 60.000000. Procurement quantity is 20 with value change 500.000000; mixed movement quantity is 24. Use the same product filter on each report when other products already exist.

Sales users see sale price/revenue; Procurement users see procurement cost/value change; users with valuation permission see the full financial field set. Viewer can read stock but cannot export. Export requires both permission for the requested report and `export_reports`. Role scoping shows permitted movement types across actors; it is not an “only my movements” rule. Inactive products remain in snapshots unless `active=true` is supplied.

The report envelope contains `columns`, `rows`, `totals`, `count`, `page`, `pages`, `currency`, `timezone`, and `generated_at`. The `timezone` value comes from Django's active timezone, which defaults to UTC in this application; it identifies the date boundaries used by the filters. `generated_at` remains an ISO timestamp with an explicit offset. The envelope differs from the DRF list envelope. CSV exports include all matching rows up to 10,000, ignore the displayed page, and contain column headers/rows only; totals, timezone, and generation time are not additional CSV records. Above the cap, narrow the filters. Totals and rows are separate database reads, so concurrent posting may change values between reads; this is an operational view, not a guaranteed database snapshot for an audit.

## 4. Add authorized JSON, HTML, and CSV endpoints

This step exposes Step 3's `report_payload()` through three interfaces. Supported report kinds are `stock`, `valuation`, `sales`, `procurement`, and `movements`. No new model change or migration is needed. Complete the routes before adding navigation links, because Django must be able to reverse their names.

### 4.1 Create the report views and their imports

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

Keep all imports at the top of this module. `.reports` refers to `inventory/reports.py` from Step 3. Django's validation exception is aliased as `DjangoValidationError`, while DRF's `ValidationError` turns invalid API filters into 400 responses. The browser handlers return a plain-text 400 for invalid filters. Permission failures remain 403; do not catch them as empty results.

`ReportView.get()` serves JSON. `report_page()` renders HTML and removes `page` from the query string used by links. `report_csv()` calls the same calculation with `exporting=True`, so it checks export permission and includes all matching rows up to the cap. `csv_cell()` guards spreadsheet formula prefixes on every exported cell; retain it even though `csv.writer` already handles delimiters and quoting. API calls use the existing JWT/session authentication; browser reports and CSV downloads require a logged-in session. An anonymous browser request redirects to login.

### 4.2 Register the API route inside urlpatterns

Open `inventory/urls.py`. Add `from .report_views import ReportView` alongside the existing imports. Keep `from django.urls import path` and the router registrations. Add this entry **inside the existing explicit `urlpatterns` list**, before the list is combined with `router.urls`:

```python
path("reports/<str:kind>/", ReportView.as_view(), name="api-report"),
```

For this checkout, replace the existing single-line `urlpatterns` assignment with this structure:

```text
urlpatterns = [
    path("valuation/", ValuationView.as_view(), name="valuation"),
    path("reports/<str:kind>/", ReportView.as_view(), name="api-report"),
] + router.urls
```

A standalone `path(...)` expression above or below `urlpatterns` does not register a route. Do not remove `router.urls`: the existing category/product/stock API depends on it. The project URL configuration already includes `inventory.urls` under `api/`, so this route becomes `/api/reports/sales/`, for example. Do not add another `api/` prefix here or duplicate the project include.

### 4.3 Register both browser routes with a relative import

Open `inventory/web_urls.py`. Add this import at the top of the file:

```text
from .report_views import report_page, report_csv
```

The leading dot is required: this module belongs to the `inventory` package. `from report_views import ...` tries to import a top-level module and prevents Django from loading the URL configuration. Keep the existing `from . import web_views as views` import.

Add these two entries **inside the existing `urlpatterns = [...]` list**, before its closing `]`:

```python
path("reports/<str:kind>/", report_page, name="web-report"),
path("reports/<str:kind>/csv/", report_csv, name="web-report-csv"),
```

Keep all existing browser routes. The project already includes `inventory.web_urls` at the root, so these entries become `/reports/sales/` and `/reports/sales/csv/`. Their names, `web-report` and `web-report-csv`, must match the template URL tags below. The `<str:kind>` argument is passed to the view and validated by `report_payload()`; no separate view is needed for each kind.

### 4.4 Create the shared report template

Create `templates/inventory/report.html`:

```html
{% extends 'base.html' %}
{% block content %}
<h1>{{ report.kind|title }} report</h1><p>Currency: {{ report.currency }} · Rows: {{ report.count }}</p>
<p>Report timezone: {{ report.timezone }}. Date filters use this timezone.</p>
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

The view supplies a `report` dictionary, not the `page` object used by list templates. Keep this template's `report.page`/`report.pages` navigation rather than including `_pagination.html`. `report.count` and totals cover all matching rows; `report.rows` contains the current page. Empty results display the explicit empty message.

Stock and valuation show SKU/name search; dated reports show start/end/product controls. Other shared filters can still be supplied in the query string. The export link preserves filters and drops the displayed page number. No CSRF token is required for this read-only GET form. Keep the export-permission conditional; the endpoint independently enforces both report and export permissions.

### 4.5 Add permission-aware report navigation

Open `templates/base.html`. Inside `<header>`, within the existing `{% if user.is_authenticated %}` block, add the following after History and before the operation links. Keep the existing links and logout form:

```django
{% if perms.inventory.view_product %}
  <a href="{% url 'web-report' 'stock' %}">Stock report</a>
{% endif %}
{% if perms.inventory.view_sales_report %}
  <a href="{% url 'web-report' 'sales' %}">Sales report</a>
{% endif %}
{% if perms.inventory.view_procurement_report %}
  <a href="{% url 'web-report' 'procurement' %}">Procurement report</a>
{% endif %}
{% if perms.inventory.view_inventory_valuation %}
  <a href="{% url 'web-report' 'valuation' %}">Valuation report</a>
{% endif %}
```

Use Django permission checks rather than group-name or staff checks, so combined roles work correctly. Mixed movement reports are also available at `/reports/movements/` for users with the history capabilities described in Step 3; the existing History link continues to open the movement list. Hidden links are a convenience, and endpoint authorization remains mandatory when a URL is entered directly.

### 4.6 Check routes, responses, and permissions

Save the files and run `uv run python manage.py check` before starting/reloading the server. Then use an authorized session to check:

| URL | Expected result |
| --- | --- |
| `/reports/stock/` | HTML stock report with thresholds and total quantity |
| `/reports/sales/?product=YOUR_PRODUCT_ID` | HTML sales report filtered to that product |
| `/api/reports/sales/?product=YOUR_PRODUCT_ID` | JSON report envelope with matching totals and role-visible columns |
| `/reports/sales/csv/?product=YOUR_PRODUCT_ID` | CSV attachment with the same permitted columns and all matching rows |
| `/reports/sales/?start=bad` | 400 validation response |
| `/api/reports/unknown/` | 400 unknown-report response for an authenticated user |

Check Viewer stock/history access, Viewer export/valuation denial, Sales cost/profit omission, and unauthorized direct report URLs. Compare the controlled amounts in Step 3 using the same role and filters. Include a second page if you have more than 25 matching rows and confirm export includes the full result, not just that page. Step 6 provides the automated report tests; run the existing suite now with `uv run python manage.py test` to check for regressions.

If Django reports `No module named 'report_views'`, correct Step 4.3's relative import. An API report 404 usually means its `path()` was not inserted into `urlpatterns`. `NoReverseMatch` for `web-report`/`web-report-csv` means the named browser routes are missing or spelled differently. A missing-template error means `report.html` is not under `templates/inventory/`. A 403 for a logged-in user means the report/export permissions need checking; changing navigation does not grant access.

## 5. Document the actual API

This step adds an OpenAPI schema and a Swagger UI page for the existing API. Work from the repository root containing `manage.py` and `pyproject.toml`. In this checkout, the project package is `django_inventory`, so edit `django_inventory/settings.py` and `django_inventory/urls.py`, not a new `config` directory. Keep the Step 4 report routes and permissions.

### 5.1 Add the schema dependency

Run from the repository root:

```sh
uv add drf-spectacular
```

This updates `pyproject.toml`, `uv.lock`, and the project's environment. This checkout already lists `drf-spectacular` in `pyproject.toml`; if it is already installed and locked, no second dependency entry is needed. The dependency uses a hyphen in its package name but an underscore in Python imports and Django app configuration. No database migration is required for this step.

### 5.2 Configure the existing project settings

Open `django_inventory/settings.py`. Find the existing `INSTALLED_APPS = [...]` list and add `"drf_spectacular",` inside it, alongside `"rest_framework"`. Keep all existing apps and add this entry only once.

In the same file, find the active `REST_FRAMEWORK` dictionary and Step 2.3's pagination update. Add the following **after** those definitions, at the top level with no indentation:

```python
REST_FRAMEWORK["DEFAULT_SCHEMA_CLASS"] = "drf_spectacular.openapi.AutoSchema"
SPECTACULAR_SETTINGS = {"TITLE": "Inventory API", "VERSION": "1.0.0", "SERVE_INCLUDE_SCHEMA": False}
```

Keep the existing JWT/session authentication, default permissions, and pagination. `DEFAULT_SCHEMA_CLASS` changes how endpoints are described; it does not change their access rules. `SPECTACULAR_SETTINGS` is a separate top-level dictionary, not an entry inside `REST_FRAMEWORK`. If either setting already exists, update it rather than introducing a second conflicting definition.

### 5.3 Register the schema and Swagger routes in the project URL file

Open **`django_inventory/urls.py`**, the project URL file containing the Admin, account, and `inventory` includes. This is not `inventory/urls.py` or `inventory/web_urls.py`. Add these imports at the top alongside the existing imports:

```text
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView
from rest_framework.permissions import IsAdminUser
```

Keep the existing `from django.urls import include, path`. Insert these entries **inside the existing `urlpatterns = [...]` list**, before its closing `]`:

```python
path("api/schema/", SpectacularAPIView.as_view(permission_classes=[IsAdminUser]), name="schema"),
path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema", permission_classes=[IsAdminUser]), name="api-docs"),
```

Because this is the project URL file, these paths include the `api/` prefix explicitly. Preserve the existing account and inventory includes, browser routes, and Admin route. A standalone `path(...)` expression outside `urlpatterns` does not register a URL. The Swagger view's `url_name="schema"` must match the schema route's `name="schema"`.

### 5.4 Describe the stock-posting request and response

Open `inventory/views.py`. At the top of the file, alongside the existing imports, add:

```text
from drf_spectacular.utils import extend_schema, OpenApiTypes
```

Keep the existing `StockOperationSerializer` and `StockTransactionSerializer` imports. Inside `StockTransactionViewSet`, locate **`def create(self, request):`**. Add this decorator immediately above that method, indented four spaces to match the method definition:

```python
    @extend_schema(request=StockOperationSerializer,
                   responses={201: StockTransactionSerializer, 200: StockTransactionSerializer})
```

Keep the method's existing body. This declares the operation input separately from the stored movement response and describes both a newly posted movement (201) and a successful UUID retry (200). Do not attach this decorator to `get_queryset()`, to the class itself, or to the browser posting view. The router already exposes the method; this step only adds schema information.

### 5.5 Describe the object responses on the API views

Three `APIView` methods return dictionaries rather than a declared response serializer. Add the following decorator immediately above each method, inside its class with four-space indentation:

```text
    @extend_schema(responses=OpenApiTypes.OBJECT)
```

| File from the repository root | Class and method | Import needed at the top |
| --- | --- | --- |
| `inventory/views.py` | `ValuationView.get(self, request)` | Already added in Step 5.4 |
| `inventory/report_views.py` | `ReportView.get(self, request, kind)` | `from drf_spectacular.utils import extend_schema, OpenApiTypes` |
| `accounts/views.py` | `MeView.get(self, request)` | `from drf_spectacular.utils import extend_schema, OpenApiTypes` |

Keep all existing authentication, permission checks, response logic, and validation handlers. Do not decorate the HTML `report_page()` or CSV `report_csv()` functions; these are browser endpoints, outside this API schema. Add each import once per file; imports in `inventory/views.py` are not available automatically in the other modules.

These generic object annotations are a starting point. The movement serializer schema is a superset: financial keys are omitted by role at runtime. For a complete client contract, describe the report envelope (including `timezone`), permissions, error responses, and supported query parameters. Import `OpenApiParameter` from `drf_spectacular.utils` when adding parameter annotations as a follow-up exercise. See [drf-spectacular setup](https://drf-spectacular.readthedocs.io/en/latest/readme.html).

### 5.6 Generate and validate the schema

With the Phase 3 database variables still available in your terminal, run these commands from the repository root:

```sh
uv run python manage.py check
```

```sh
uv run python manage.py spectacular --file schema.yml --validate
```

`schema.yml` is written into the repository root beside `manage.py`. Open it and confirm the product/category/history operations, stock POST request and 200/201 responses, valuation, current-user, and report endpoints appear. Treat warning messages as work to resolve even if the command exits successfully. For a stricter check after resolving warnings, run `uv run python manage.py spectacular --file schema.yml --validate --fail-on-warn`. Do not call the client contract complete solely because schema generation succeeds.

Typical failures: `No module named 'drf_spectacular'` means the dependency is missing from the environment running Django; `Unknown command: spectacular` means the app entry is missing or different settings are being used; `NameError` for `extend_schema`/`OpenApiTypes` means the import is missing from that particular module. A schema warning about an `APIView` response can indicate a missing annotation from Step 5.5.

### 5.7 Open the documentation with a staff session

Start or reload the development server and sign in through `/accounts/login/` with an active Django staff account. Open `/api/docs/` for Swagger UI and `/api/schema/` for the schema. A 404 usually indicates Step 5.3's routes are outside `urlpatterns` or in the wrong URL module. If Swagger loads but cannot retrieve the schema, check the named schema route and the signed-in account's staff access.

`IsAdminUser` checks Django's `is_staff`, which is separate from membership in the business Administrator group. A business user without staff status can use authorized reports but cannot open these schema/docs endpoints. The generic object annotations make schema generation possible, but do not fully describe report envelopes, role-dependent fields, or query parameters. Add those descriptions before treating the schema as a complete client contract.

Run `uv run python manage.py test` after the changes. Review `django_inventory/settings.py`, `django_inventory/urls.py`, `inventory/views.py`, `inventory/report_views.py`, `accounts/views.py`, `pyproject.toml`, and `uv.lock`. Generated `schema.yml` can be retained as a review artifact according to your repository convention. No report template changes or database migration are required by Step 5.

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

    def test_viewer_can_read_stock_and_quantity_history_but_cannot_export(self):
        viewer = get_user_model().objects.create_user(username="report-viewer")
        viewer.groups.add(Group.objects.get(name="Viewer"))
        self.client.force_login(viewer)
        self.assertEqual(self.client.get("/reports/stock/").status_code, 200)
        self.assertEqual(self.client.get("/reports/stock/csv/").status_code, 403)
        history = self.client.get("/api/reports/movements/")
        self.assertEqual(history.status_code, 200)
        self.assertNotIn("revenue", history.json()["columns"])
        self.assertEqual(self.client.get("/api/reports/valuation/").status_code, 403)

    def test_end_date_uses_local_midnight_and_scope_cannot_expand(self):
        from datetime import datetime
        from django.utils import timezone
        from .models import StockTransaction

        sale = StockTransaction.objects.get(transaction_type="SALE")
        zone = timezone.get_current_timezone()
        self.assertEqual(report_payload(self.admin, "stock", {})["timezone"], timezone.get_current_timezone_name())
        StockTransaction.objects.filter(pk=sale.pk).update(
            created_at=datetime(2026, 10, 12, 23, 59, 59, tzinfo=zone))
        params = {"start": "2026-10-12", "end": "2026-10-12"}
        self.assertEqual(report_payload(self.sales, "sales", params)["count"], 1)
        StockTransaction.objects.filter(pk=sale.pk).update(
            created_at=datetime(2026, 10, 13, 0, 0, tzinfo=zone))
        self.assertEqual(report_payload(self.sales, "sales", params)["count"], 0)
        self.assertEqual(report_payload(self.sales, "movements", {"type": "PROCUREMENT"})["count"], 0)
        with self.assertRaises(ValidationError):
            report_payload(self.admin, "stock", params)

    def test_pagination_keeps_totals_and_export_includes_all_rows(self):
        # Use procurement rows to exceed the page size without exhausting stock.
        for _ in range(26):
            post_stock(actor=self.admin, product_id=self.product.pk, transaction_type="PROCUREMENT",
                       quantity=1, unit_cost="25.00", request_key=uuid4())
        first = report_payload(self.admin, "procurement", {})
        second = report_payload(self.admin, "procurement", {"page": "2"})
        exported = report_payload(self.admin, "procurement", {"page": "2"}, exporting=True)
        self.assertEqual((len(first["rows"]), len(second["rows"])), (25, 3))
        self.assertEqual(first["totals"], second["totals"])
        self.assertEqual(first["totals"]["quantity"], "46")
        self.assertEqual(len(exported["rows"]), 28)

    def test_http_reports_validate_filters_and_preserve_sales_visibility(self):
        # The API envelope and browser display both identify the active timezone.
        self.client.force_login(self.sales)
        api = self.client.get("/api/reports/sales/")
        self.assertEqual(api.status_code, 200)
        self.assertNotIn("cogs", api.json()["rows"][0])
        csv_response = self.client.get("/reports/sales/csv/")
        self.assertEqual(csv_response.status_code, 200)
        self.assertNotIn("cogs", csv_response.content.decode().splitlines()[0])
        self.assertEqual(self.client.get("/api/reports/sales/?start=bad").status_code, 400)
        self.assertEqual(self.client.get("/reports/sales/?product=-1").status_code, 400)

    def test_active_timezone_is_reported_and_used_for_date_filters(self):
        from datetime import datetime, timezone as datetime_timezone
        from django.utils import timezone
        from .models import StockTransaction

        StockTransaction.objects.filter(transaction_type="SALE").update(
            created_at=datetime(2026, 10, 12, 20, tzinfo=datetime_timezone.utc))
        params = {"start": "2026-10-12", "end": "2026-10-12"}
        with timezone.override("UTC"):
            data = report_payload(self.admin, "sales", params)
            self.assertEqual((data["timezone"], data["count"]), ("UTC", 1))
            self.client.force_login(self.admin)
            self.assertContains(self.client.get("/reports/sales/"), "Report timezone: UTC")
        with timezone.override("Asia/Jakarta"):
            data = report_payload(self.admin, "sales", params)
            self.assertEqual((data["timezone"], data["count"]), ("Asia/Jakarta", 0))
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
