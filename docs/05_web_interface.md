# 05 — Build the browser workflows

Continue from [Phase 4](04_accounts_roles_jwt.md). You will add Django templates/forms, session login, catalog screens, procurement/sales/correction forms, and authorized movement history. No new dependency is needed. Keep the API; HTML views call the shared service directly.

This guide uses the tutorial package name `config`. In this checkout, edit `django_inventory/settings.py` and `django_inventory/urls.py` wherever `config/settings.py` or `config/urls.py` is mentioned. Complete Phase 4 migrations and `setup_roles` first, and keep the PostgreSQL environment variables from Phase 3 available in the terminal running these commands. Phase 5 introduces no model changes or migrations.

## 1. Understand the HTML request flow

```text
GET form -> session + permission checks -> render HTML with CSRF token
POST form -> CSRF middleware -> form validation -> post_stock()
  -> commit -> success message -> redirect -> GET detail
```

The redirect prevents browser refresh from resubmitting a successful POST. The UUID also protects retries. Django forms are the HTML equivalent of the input serializers; service validation remains authoritative. Templates never receive unrestricted financial records for history rendering.

In `config/settings.py` (`django_inventory/settings.py` in this checkout), keep the existing `TEMPLATES` configuration, including `OPTIONS` and its context processors. Inside its existing dictionary, set the directory entry to `'DIRS': [BASE_DIR / 'templates'],`. If you already have that entry, no further change to `TEMPLATES` is needed.

The additional settings belong at the top level of the file, **after the entire `TEMPLATES` block's closing `]`**, with no indentation. Do not put them before or inside `OPTIONS`. For example, your existing configuration and the new settings together should look like this. Update the existing block; do not add a second `TEMPLATES` definition. Keep any additional context processors you already have. If `STATIC_URL = 'static/'` already appears elsewhere in the file, keep that existing line and omit it from the example below.

```python
TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

# These settings are outside the TEMPLATES block.
STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "dashboard"
LOGOUT_REDIRECT_URL = "login"
```

Create the `templates`, `templates/registration`, `templates/inventory`, and `static` directories in the project root (alongside `manage.py`) before running checks.

## 2. Add shared layout and account pages

Create `templates/base.html`:

```html
{% load static %}
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{% block title %}Inventory{% endblock %}</title>
  <link rel="stylesheet" href="{% static 'inventory.css' %}">
</head>
<body>
<header>
  <a href="{% url 'dashboard' %}">Inventory</a>
  {% if user.is_authenticated %}
    {% if perms.inventory.view_product %}<a href="{% url 'web-products' %}">Products</a>{% endif %}
    {% if perms.inventory.view_category %}<a href="{% url 'web-categories' %}">Categories</a>{% endif %}
    <a href="{% url 'web-movements' %}">History</a>
    {% if perms.inventory.receive_procurement %}<a href="{% url 'web-post' 'PROCUREMENT' %}">Receive goods</a>{% endif %}
    {% if perms.inventory.record_sale %}<a href="{% url 'web-post' 'SALE' %}">Record sale</a>{% endif %}
    {% if perms.inventory.record_opening_balance %}<a href="{% url 'web-post' 'OPENING_BALANCE' %}">Opening balance</a>{% endif %}
    {% if perms.inventory.adjust_stock %}
      <a href="{% url 'web-post' 'ADJUSTMENT_IN' %}">Adjust in</a>
      <a href="{% url 'web-post' 'ADJUSTMENT_OUT' %}">Adjust out</a>
    {% endif %}
    <a href="{% url 'password_change' %}">Change password</a>
    <form method="post" action="{% url 'logout' %}">{% csrf_token %}<button>Log out</button></form>
  {% endif %}
</header>
<main>
  {% for message in messages %}<p role="status">{{ message }}</p>{% endfor %}
  {% block content %}{% endblock %}
</main>
</body>
</html>
```

Create `static/inventory.css`:

```css
body { margin: 0; font: 1rem/1.5 system-ui, sans-serif; color: #17202a; background: #f4f6f7; }
header { display: flex; flex-wrap: wrap; gap: 1rem; align-items: center; padding: 1rem; background: white; }
main { max-width: 68rem; margin: auto; padding: 1.5rem; }
a { color: #075ba3; }
label { display: block; font-weight: 600; }
input, select, textarea, button { font: inherit; padding: .5rem; max-width: 100%; box-sizing: border-box; }
textarea { width: 100%; }
button { cursor: pointer; }
header form { margin: 0; }
.errorlist { color: #a61919; }
.cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(14rem, 1fr)); gap: 1rem; }
article { background: white; padding: 1rem; border-radius: .5rem; }
dt { font-weight: 600; } dd { margin: 0 0 .5rem; overflow-wrap: anywhere; }
:focus-visible { outline: 3px solid #b76b00; outline-offset: 3px; }
```

Create `templates/registration/login.html`:

```html
{% extends 'base.html' %}
{% block content %}
<h1>Sign in</h1>
<form method="post">{% csrf_token %}
  {{ form.as_p }}
  <input type="hidden" name="next" value="{{ next }}">
  <button>Sign in</button>
</form>
{% endblock %}
```

Create `templates/registration/password_change_form.html`:

```html
{% extends 'base.html' %}
{% block content %}<h1>Change password</h1>
<form method="post">{% csrf_token %}{{ form.as_p }}<button>Save password</button></form>
{% endblock %}
```

Create `templates/registration/password_change_done.html`:

```html
{% extends 'base.html' %}
{% block content %}<h1>Password changed</h1><a href="{% url 'dashboard' %}">Continue</a>{% endblock %}
```

We will register only login/logout/password-change routes. Password reset requires email delivery and is outside this local walkthrough.

## 3. Create catalog and posting forms

Create `inventory/forms.py`:

```python
from uuid import uuid4

from django import forms

from .models import Category, Product, StockTransaction


class ProductForm(forms.ModelForm):
    class Meta:
        model = Product
        fields = ["sku", "name", "category", "description", "price", "is_active"]


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
```

The operation type comes from the route, never a client-controlled hidden type field. Correction screens require administrator capabilities before this form is constructed. The service validates correction targets belong to the product. Opening forms are for new zero-stock products; use Phase 3's command for existing legacy quantities.

## 4. Build session views with the same authorization

Create `inventory/web_views.py`:

```python
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Sum
from django.db.models.deletion import ProtectedError
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.views.generic import CreateView, UpdateView
from django.views.decorators.http import require_http_methods

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
    if request.user.has_perm("inventory.view_inventory_valuation"):
        totals["inventory_value"] = Product.objects.aggregate(value=Sum("inventory_value"))["value"] or 0
    rows = movement_data(request, visible_movements(request.user)[:5])
    return render(request, "inventory/dashboard.html", {
        "totals": totals, "rows": rows, "currency": settings.INVENTORY_CURRENCY
    })


@login_required
@permission_required("inventory.view_product", raise_exception=True)
def products(request):
    return render(request, "inventory/products.html", {
        "products": Product.objects.select_related("category").order_by("name", "id")
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
    require_history(request.user)
    return render(request, "inventory/movements.html", {
        "rows": movement_data(request, visible_movements(request.user)[:100])
    })


@login_required
def movement_detail(request, pk):
    require_history(request.user)
    movement = get_object_or_404(visible_movements(request.user), pk=pk)
    return render(request, "inventory/movements.html", {
        "rows": movement_data(request, [movement])
    })
```

`ProductForm` never accepts balance fields, so metadata edits cannot change inventory. Deactivate products by editing `is_active`; no browser product-delete screen is needed. API deletion remains protected. Dashboard units include inactive products because deactivation does not remove inventory.

## 5. Render catalog, dashboard, and history

Create `templates/inventory/form.html`:

```html
{% extends 'base.html' %}
{% block content %}<h1>{{ title|default:'Edit catalog' }}</h1>
<form method="post">{% csrf_token %}{{ form.as_p }}<button>Save</button></form>
{% endblock %}
```

Create `templates/inventory/_movements.html`:

```html
<div class="cards">
{% for row in rows %}
<article>
  <a href="{% url 'web-movement-detail' row.id %}">Movement {{ row.id }}</a>
  <dl>{% for field, value in row.items %}<dt>{{ field }}</dt><dd>{{ value|default_if_none:'—' }}</dd>{% endfor %}</dl>
</article>
{% empty %}<p>No movements to show.</p>{% endfor %}
</div>
```

Only already-authorized serialized fields reach this partial. Autoescaping remains enabled for references/notes.

Create `templates/inventory/movements.html`:

```html
{% extends 'base.html' %}
{% block content %}<h1>Stock history</h1>{% include 'inventory/_movements.html' %}{% endblock %}
```

Create `templates/inventory/dashboard.html`:

```html
{% extends 'base.html' %}
{% block content %}
<h1>Dashboard</h1><p>Units in stock: {{ totals.units|default_if_none:0 }}</p>
{% if perms.inventory.view_inventory_valuation %}<p>Inventory value ({{ currency }}): {{ totals.inventory_value }}</p>{% endif %}
<h2>Recent movements</h2>{% include 'inventory/_movements.html' %}
{% endblock %}
```

Create `templates/inventory/products.html`:

```html
{% extends 'base.html' %}
{% block content %}<h1>Products</h1>
{% if perms.inventory.add_product %}<a href="{% url 'web-product-create' %}">Add product</a>{% endif %}
<div class="cards">{% for product in products %}
<article><a href="{% url 'web-product-detail' product.pk %}">{{ product.sku }} — {{ product.name }}</a>
<p>Stock: {{ product.stock_quantity }} · Active: {{ product.is_active|yesno:'Yes,No' }}</p></article>
{% empty %}<p>No products yet.</p>{% endfor %}</div>
{% endblock %}
```

Create `templates/inventory/product_detail.html`:

```html
{% extends 'base.html' %}
{% block content %}<h1>{{ product.name }}</h1>
<p>{{ product.sku }} · {{ product.category }} · Stock: {{ product.stock_quantity }}</p>
<p>{{ product.description }}</p><p>Selling price: {{ product.price }}</p>
{% if perms.inventory.view_inventory_valuation %}
  <p>Average cost: {{ product.average_unit_cost }} · Inventory value: {{ product.inventory_value }}</p>
{% endif %}
{% if perms.inventory.change_product %}<a href="{% url 'web-product-edit' product.pk %}">Edit or deactivate</a>{% endif %}
<h2>Recent authorized history</h2>{% include 'inventory/_movements.html' %}
{% endblock %}
```

Create `templates/inventory/categories.html`:

```html
{% extends 'base.html' %}
{% block content %}<h1>Categories</h1>
{% if perms.inventory.add_category %}<a href="{% url 'web-category-create' %}">Add category</a>{% endif %}
<ul>{% for category in categories %}<li>{{ category.name }}
{% if perms.inventory.change_category %}<a href="{% url 'web-category-edit' category.pk %}">Edit</a>{% endif %}
{% if perms.inventory.delete_category %}<a href="{% url 'web-category-delete' category.pk %}">Delete</a>{% endif %}
</li>{% empty %}<li>No categories yet.</li>{% endfor %}</ul>
{% endblock %}
```

Create `templates/inventory/confirm_delete.html`:

```html
{% extends 'base.html' %}
{% block content %}<h1>Delete {{ category.name }}?</h1>
<form method="post">{% csrf_token %}<button>Delete category</button></form>
{% endblock %}
```

## 6. Register browser and account URLs

### 6.1. Create the browser route file

Create `inventory/web_urls.py` beside `inventory/web_views.py`. This is a new file for HTML pages; keep the existing `inventory/urls.py` for the REST API. Finish the forms, views, and templates from Steps 2–5 first so these routes have something to import and render.

```python
from django.urls import path
from . import web_views as views

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("products/", views.products, name="web-products"),
    path("products/new/", views.ProductCreate.as_view(), name="web-product-create"),
    path("products/<int:pk>/", views.product_detail, name="web-product-detail"),
    path("products/<int:pk>/edit/", views.ProductUpdate.as_view(), name="web-product-edit"),
    path("categories/", views.categories, name="web-categories"),
    path("categories/new/", views.CategoryCreate.as_view(), name="web-category-create"),
    path("categories/<int:pk>/edit/", views.CategoryUpdate.as_view(), name="web-category-edit"),
    path("categories/<int:pk>/delete/", views.category_delete, name="web-category-delete"),
    path("stock/<str:kind>/", views.post_operation, name="web-post"),
    path("movements/", views.movements, name="web-movements"),
    path("movements/<int:pk>/", views.movement_detail, name="web-movement-detail"),
]
```

Each `path()` connects a URL to a view and gives it a name that templates and redirects can use. For example, `/products/3/` passes `pk=3` to `product_detail`; `/stock/SALE/` passes `kind="SALE"` to `post_operation`. Function views are referenced directly. Class-based views such as `ProductCreate` use `.as_view()` to create the callable Django needs. The view still checks permissions; registering a URL does not grant access.

### 6.2. Connect browser and login routes to the project

Open the **project-level** `config/urls.py`, which is `django_inventory/urls.py` in this checkout. Do not add these routes to `accounts/urls.py` or the API's `inventory/urls.py`.

Keep the existing imports and `urlpatterns = [...]` containing Admin and the API includes. Add the `auth_views` import near the other imports, then add the `urlpatterns += [...]` section **below the existing list's closing `]`**, outside that list. Here is the code to add; `path` and `include` are already imported in this checkout:

```python
from django.contrib.auth import views as auth_views

# Keep the existing urlpatterns = [...] above this additional section.
urlpatterns += [
    path("accounts/login/", auth_views.LoginView.as_view(), name="login"),
    path("accounts/logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("accounts/password-change/", auth_views.PasswordChangeView.as_view(), name="password_change"),
    path("accounts/password-change/done/", auth_views.PasswordChangeDoneView.as_view(), name="password_change_done"),
    path("", include("inventory.web_urls")),
]
```

`+=` adds routes to the existing list. If you prefer, you can place these five `path(...)` entries inside the existing list instead; use one approach only. Keep the existing Admin, API, and API-auth entries. Do not include `django.contrib.auth.urls` as well: this walkthrough deliberately registers only login, logout, and password change.

The final `path("", include("inventory.web_urls"))` mounts the browser routes at the site root. Its empty prefix means `products/` becomes `/products/`, rather than `/inventory/products/`. Keep it after the account routes. Django tries routes in order and the included route file must also match the remaining path; its dashboard's empty path matches `/` only.

### 6.3. Check which pages the routes open

| URL | Handler or template | Expected behavior |
| --- | --- | --- |
| `/` | `dashboard` | Redirects anonymous visitors to login; requires product-view permission after login |
| `/accounts/login/` | `LoginView` → `registration/login.html` | Shows the session sign-in form; successful login uses a safe `next` target or the dashboard |
| `/accounts/logout/` | `LogoutView` | The layout's POST form logs out and redirects to login; opening it with GET returns 405 |
| `/accounts/password-change/` | `PasswordChangeView` → `registration/password_change_form.html` | Requires login; a successful POST redirects to the completion page |
| `/accounts/password-change/done/` | `PasswordChangeDoneView` → `registration/password_change_done.html` | Shows the confirmation to a signed-in user |
| `/products/`, `/categories/` | Catalog views from Step 4 | Show lists and permitted catalog actions |
| `/stock/PROCUREMENT/`, `/stock/SALE/` | `post_operation` | Show the authorized stock form; POST validates and posts through the shared service |
| `/movements/`, `/movements/3/` | History views from Step 4 | Show only movements and financial fields the user may access |

The names must match the earlier settings and templates: `LOGIN_URL = "login"`, `LOGIN_REDIRECT_URL = "dashboard"`, and `LOGOUT_REDIRECT_URL = "login"`. The default password-change success route is named `password_change_done`; retain the underscore spelling. Use the exact uppercase stock operation names from Step 3; an unknown kind returns 404 and a known operation without permission returns 403.

Logout uses POST with CSRF. Django handles safe login redirect targets and password-change session behavior; see [Django authentication views](https://docs.djangoproject.com/en/5.2/topics/auth/default/#all-authentication-views).

### 6.4. Verify the wiring

Run `uv run python manage.py check`, then start the server as shown in Step 7. Visit `/` while signed out and confirm it redirects to `/accounts/login/?next=/`. Sign in with an active Phase 4 business account and check the dashboard, catalog links, and permitted stock forms. Use the logout button to end the session.

If Django reports `NoReverseMatch`, check the route names against the template's `{% url ... %}` calls and confirm the project includes `inventory.web_urls`. If it reports `TemplateDoesNotExist`, check the Step 2/5 template paths and the Step 1 `TEMPLATES` directory. An import error for `web_views` usually means Step 4's file is missing or has a syntax error. A 403 after successful login means the account lacks the required business permission; assign the appropriate Phase 4 group and retry.

## 7. Follow the daily workflow

```sh
uv run python manage.py check
uv run python manage.py runserver
```

Open [the login page](http://127.0.0.1:8000/accounts/login/). As a manager/admin, create a category and zero-stock product. As Procurement, receive 10 at 20 and 10 at 30. As Sales, sell 4 at 40. Expect 16 remaining; manager valuation is 400. Sales history shows revenue 160 with no COGS/profit. Viewer history shows quantities only.

Use separate active local accounts assigned to the Phase 4 groups: Inventory manager, Procurement, Sales, Viewer, and Administrator. A superuser can provision them in Django Admin; business users do not need `is_staff` to use these browser pages. A user with no business permissions can sign in but receives 403 on the dashboard. Check that logout is submitted through the button and that password change keeps the current session signed in.

Try selling 17: the form displays the service error and stock stays 16. Replay the same POST body/key: stock changes only once. As Sales, visit `/stock/ADJUSTMENT_OUT/` directly: expect 403. As Administrator, submit an adjustment with a reason and optionally a matching correction target. Edit a product to deactivate it; subsequent new movements must fail. Inspect keyboard focus, labels, errors, empty lists, and a narrow browser viewport.

The hidden UUID is generated when an unbound form is rendered and retained on a failed bound submission. To test a retry, resend the original POST with its original UUID; opening a fresh form produces a new UUID. The browser form excludes inactive products, including for a retry after deactivation; the shared service itself can still return an already-posted movement for an identical authorized retry. History currently shows at most 100 movements and product detail at most 20; filtering and pagination arrive in Phase 6.

## 8. Add browser tests

Create `inventory/test_web.py`. Django discovers files beginning with `test` automatically:

```python
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management import call_command
from django.test import Client, TestCase
from django.urls import reverse

from .models import Category, Product, StockTransaction
from .services import post_stock


class BrowserWorkflowTests(TestCase):
    def setUp(self):
        call_command("setup_roles", verbosity=0)
        self.sales = get_user_model().objects.create_user(username="web-sales", password="test-password")
        self.sales.groups.add(Group.objects.get(name="Sales"))
        self.admin = get_user_model().objects.create_superuser(username="web-admin", password="test-password")
        self.product = Product.objects.create(sku="WEB-1", name="Web", price="40.00",
                                             category=Category.objects.create(name="Web"))
        post_stock(actor=self.admin, product_id=self.product.pk, transaction_type="PROCUREMENT",
                   quantity=10, unit_cost="20.00", request_key=uuid4())
        self.client.force_login(self.sales)

    def test_sales_post_and_retry_without_cost_leak(self):
        payload = {"product": self.product.pk, "quantity": 4, "selling_price": "40.00",
                   "request_key": str(uuid4())}
        url = reverse("web-post", args=["SALE"])
        first = self.client.post(url, payload)
        self.assertEqual(first.status_code, 302)
        self.assertEqual(self.client.post(url, payload).status_code, 302)
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, 6)
        detail = self.client.get(first.url)
        self.assertContains(detail, "revenue")
        self.assertNotContains(detail, "cogs")
        self.assertNotContains(detail, "gross_profit")

    def test_direct_correction_url_and_csrf_are_protected(self):
        self.assertEqual(self.client.get(reverse("web-post", args=["ADJUSTMENT_OUT"])).status_code, 403)
        strict = Client(enforce_csrf_checks=True)
        strict.force_login(self.sales)
        response = strict.post(reverse("web-post", args=["SALE"]), {
            "product": self.product.pk, "quantity": 1, "selling_price": "40.00", "request_key": str(uuid4())
        })
        self.assertEqual(response.status_code, 403)

    def test_metadata_form_ignores_balance_input(self):
        self.client.force_login(self.admin)
        response = self.client.post(reverse("web-product-edit", args=[self.product.pk]), {
            "sku": "WEB-1", "name": "Updated", "category": self.product.category_id,
            "price": "40.00", "is_active": "on", "stock_quantity": 999, "inventory_value": "999"
        })
        self.assertEqual(response.status_code, 302)
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, 10)

    def test_login_logout_and_safe_redirect(self):
        self.client.logout()
        self.assertRedirects(self.client.get(reverse("dashboard")),
                             reverse("login") + "?next=/", fetch_redirect_response=False)
        response = self.client.post(reverse("login"), {
            "username": "web-sales", "password": "test-password",
            "next": "https://example.com/",
        })
        self.assertRedirects(response, reverse("dashboard"))
        self.assertEqual(self.client.get(reverse("logout")).status_code, 405)
        self.assertRedirects(self.client.post(reverse("logout")), reverse("login"))

    def test_failed_sale_preserves_balances_and_history(self):
        before = StockTransaction.objects.count()
        response = self.client.post(reverse("web-post", args=["SALE"]), {
            "product": self.product.pk, "quantity": 11, "selling_price": "40.00",
            "request_key": str(uuid4()),
        })
        self.assertContains(response, "Insufficient stock.")
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, 10)
        self.assertEqual(self.product.inventory_value, 200)
        self.assertEqual(StockTransaction.objects.count(), before)

    def test_viewer_history_and_sales_detail_filter(self):
        procurement = StockTransaction.objects.get(transaction_type="PROCUREMENT")
        self.assertEqual(self.client.get(reverse("web-movement-detail", args=[procurement.pk])).status_code, 404)
        viewer = get_user_model().objects.create_user(username="web-viewer", password="test-password")
        viewer.groups.add(Group.objects.get(name="Viewer"))
        self.client.force_login(viewer)
        response = self.client.get(reverse("web-movements"))
        self.assertContains(response, "PROCUREMENT")
        for field in ("unit_cost", "selling_price", "value_change", "cogs", "revenue", "gross_profit"):
            self.assertNotContains(response, field)
        self.assertEqual(self.client.get(reverse("web-post", args=["SALE"])).status_code, 403)

    def test_inactive_product_and_changed_retry_are_rejected(self):
        payload = {"product": self.product.pk, "quantity": 1, "selling_price": "40.00",
                   "request_key": str(uuid4())}
        url = reverse("web-post", args=["SALE"])
        self.assertEqual(self.client.post(url, payload).status_code, 302)
        payload["quantity"] = 2
        self.assertContains(self.client.post(url, payload), "Request key already used")
        self.product.is_active = False
        self.product.save(update_fields=["is_active"])
        payload["request_key"] = str(uuid4())
        self.assertEqual(self.client.post(url, payload).status_code, 200)
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, 9)
        self.assertEqual(StockTransaction.objects.count(), 2)

    def test_password_change_preserves_current_session(self):
        response = self.client.post(reverse("password_change"), {
            "old_password": "test-password", "new_password1": "New-strong-web-password-927!",
            "new_password2": "New-strong-web-password-927!",
        })
        self.assertRedirects(response, reverse("password_change_done"))
        self.assertEqual(self.client.get(reverse("dashboard")).status_code, 200)
        self.sales.refresh_from_db()
        self.assertTrue(self.sales.check_password("New-strong-web-password-927!"))
```

Run the browser tests and then the complete suite:

```sh
uv run python manage.py test inventory.test_web
uv run python manage.py test
uv run python manage.py makemigrations --check --dry-run
```

## 9. Review changed files

```text
config/settings.py + urls.py              templates/static and session routes
inventory/forms.py                        metadata and operation forms
inventory/web_views.py + web_urls.py       authorized browser workflows
inventory/test_web.py                      posting, visibility, CSRF, metadata tests
templates/base.html + registration/       layout and account pages
templates/inventory/                      catalog, dashboard, history, forms
static/inventory.css                      responsive styles
```

Commit after tests and browser checks pass. This is the first daily-use web/API milestone. Next: [Phase 6 — Reports and usability](06_reports_usability.md).
