# 04 — Accounts, business roles, and JWT

Continue from [Phase 3](03_stock_transactions_valuation.md). You will replace staff-only API access with business permissions and issue application JWTs. Keep the existing Django user model and users. Use the settings-package substitution described in Phase 3.

## 1. Understand authentication versus authorization

```text
Bearer access token -> JWTAuthentication -> local user
  -> permission checks against current groups
  -> role-scoped queryset + field filtering
  -> shared service checks the posting capability again
```

A token identifies the user; it does not grant an inventory role. Group permissions come from the database on each request. Accounts are created/approved by an administrator; there is no public signup. `is_staff` controls Django Admin access independently of business roles.

## 2. Create the accounts app and capabilities

```sh
uv run python manage.py startapp accounts
uv add djangorestframework-simplejwt
```

Add `accounts.apps.AccountsConfig` and `rest_framework_simplejwt.token_blacklist` to `INSTALLED_APPS`. Do not set `AUTH_USER_MODEL` or replace the user table.

Inside `StockTransaction.Meta` in `inventory/models.py`, add:

```python
        permissions = [
            ("record_sale", "Can record sales"),
            ("receive_procurement", "Can receive procurement"),
            ("adjust_stock", "Can adjust stock"),
            ("record_opening_balance", "Can record opening balances"),
            ("view_all_movements", "Can view all movement quantities"),
            ("view_sales_report", "Can view sales revenue"),
            ("view_procurement_report", "Can view procurement costs"),
            ("view_inventory_valuation", "Can view valuation and profit"),
            ("export_reports", "Can export permitted reports"),
        ]
```

```sh
uv run python manage.py makemigrations inventory
uv run python manage.py migrate
```

Migration creates the model options; Django's post-migration permission creation supplies the rows used next.

## 3. Seed repeatable roles and approve users

Create empty `accounts/management/__init__.py` and `accounts/management/commands/__init__.py`. Create `accounts/management/commands/setup_roles.py`:

```python
from django.contrib.auth.models import Group, Permission
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

CATALOG_READ = {"inventory.view_product", "inventory.view_category"}
CATALOG_WRITE = {f"inventory.{action}_{model}" for action in ("add", "change", "delete")
                 for model in ("product", "category")}
MOVEMENT_READ = {"inventory.view_all_movements"}
SALE = {"inventory.record_sale", "inventory.view_sales_report"}
PROCUREMENT = {"inventory.receive_procurement", "inventory.view_procurement_report"}
VALUATION = {"inventory.view_inventory_valuation"}
CORRECTIONS = {"inventory.adjust_stock", "inventory.record_opening_balance"}
EXPORT = {"inventory.export_reports"}
ROLES = {
    "Viewer": CATALOG_READ | MOVEMENT_READ,
    "Sales": CATALOG_READ | SALE | EXPORT,
    "Procurement": CATALOG_READ | PROCUREMENT | EXPORT,
    "Inventory manager": CATALOG_READ | CATALOG_WRITE | MOVEMENT_READ | SALE | PROCUREMENT | VALUATION | EXPORT,
    "Administrator": CATALOG_READ | CATALOG_WRITE | MOVEMENT_READ | SALE | PROCUREMENT | VALUATION | CORRECTIONS | EXPORT
        | {"auth.view_user", "auth.add_user", "auth.change_user", "auth.view_group"},
}


class Command(BaseCommand):
    help = "Set the tutorial groups to the documented permission matrix."

    @transaction.atomic
    def handle(self, *args, **options):
        for name, capabilities in ROLES.items():
            permissions = []
            for capability in sorted(capabilities):
                app, code = capability.split(".", 1)
                try:
                    permissions.append(Permission.objects.get(content_type__app_label=app, codename=code))
                except Permission.DoesNotExist as exc:
                    raise CommandError(f"Missing {capability}; run migrate first") from exc
            group, _ = Group.objects.get_or_create(name=name)
            group.permissions.set(permissions)
        self.stdout.write(self.style.SUCCESS("Roles configured"))
```

```sh
uv run python manage.py setup_roles
uv run python manage.py setup_roles
```

The second run should not duplicate roles. This command resets these groups to the matrix, so keep custom permissions in a separate group.

As the superuser in Admin, create local users with passwords, keep them active, and assign groups. Do not grant ordinary business users staff/superuser flags. To create a learning Sales account in `manage.py shell`:

```python
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from getpass import getpass

user = get_user_model().objects.create_user(username="sales_demo", password=getpass("Password: "))
user.groups.add(Group.objects.get(name="Sales"))
```

Multiple groups combine capabilities. A user with no business group has no inventory access. Role assignments use the superuser Admin workflow in this tutorial. Do not expose a generic user/group editing API: preventing privilege escalation needs a separate restricted account-management workflow. Administrator is a business role; grant `is_staff` only through the trusted superuser if that person must use Admin. Django's default UserAdmin permission editor is reserved for trusted administrators.

## 4. Centralize operation and financial access

Create `inventory/access.py`:

```python
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
```

Remove the old `require_operation` function from `inventory/services.py` and import `require_operation` from `.access`. This replaces staff access even for shell commands and future HTML forms.

In `inventory/views.py`, import these permission classes and `visible_movements`. Set `permission_classes = [CatalogPermission]` on both catalog ViewSets, `[MovementPermission]` on `StockTransactionViewSet`, and `[ValuationPermission]` on `ValuationView`. Add inside `StockTransactionViewSet`:

```python
    def get_queryset(self):
        return visible_movements(self.request.user)
```

This scopes detail lookups too: a Sales user requesting a procurement ID gets 404.

In `inventory/serializers.py`, import `FINANCIAL_FIELDS`, `allowed_money_fields` from `.access`. Add inside `StockTransactionSerializer`:

```python
    def to_representation(self, instance):
        data = super().to_representation(instance)
        user = self.context["request"].user
        for field in FINANCIAL_FIELDS - allowed_money_fields(user, instance.transaction_type):
            data.pop(field, None)
        return data
```

Add inside `ProductSerializer`:

```python
    def to_representation(self, instance):
        data = super().to_representation(instance)
        user = self.context["request"].user
        if not user.has_perm("inventory.view_inventory_valuation"):
            data.pop("average_unit_cost", None)
            data.pop("inventory_value", None)
        return data
```

Require request context whenever using these serializers. Phase 5 does so explicitly. Filtering only lists or hiding buttons is insufficient: serializers, details, totals, and the service all enforce access.

## 5. Configure JWT and account endpoints

In `config/settings.py`, merge/replace these settings:

```python
from datetime import timedelta

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework_simplejwt.authentication.JWTAuthentication",
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
}
SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=5),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=1),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
}
```

Basic authentication is removed; Phase 3's terminal helper must now send Bearer credentials. Refresh rotation requires clients to replace both saved tokens with the refreshed pair. See [Simple JWT settings](https://django-rest-framework-simplejwt.readthedocs.io/en/stable/settings.html).

Create `accounts/views.py`:

```python
from rest_framework.response import Response
from rest_framework.views import APIView


class MeView(APIView):
    def get(self, request):
        user = request.user
        return Response({"id": user.pk, "username": user.username, "email": user.email,
                         "capabilities": sorted(user.get_all_permissions())})
```

Create `accounts/urls.py`:

```python
from django.urls import path
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView, TokenBlacklistView

from .views import MeView

urlpatterns = [
    path("auth/token/", TokenObtainPairView.as_view(), name="token-obtain"),
    path("auth/token/refresh/", TokenRefreshView.as_view(), name="token-refresh"),
    path("auth/logout/", TokenBlacklistView.as_view(), name="token-logout"),
    path("accounts/me/", MeView.as_view(), name="account-me"),
]
```

In `config/urls.py`, add `path("api/", include("accounts.urls"))` before the existing inventory include. `TokenBlacklistView` validates/blacklists the submitted refresh token; logout does not immediately revoke the five-minute access token. A holder of a refresh token can revoke it without a separate access token.

```sh
uv run python manage.py migrate
uv run python manage.py check
```

## 6. Try real tokens and forbidden operations

In a new Python prompt (`uv run python`), use:

```python
import getpass
import json
from urllib.error import HTTPError
from urllib.request import Request, urlopen


def request(method, path, payload=None, access=None):
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if access:
        headers["Authorization"] = f"Bearer {access}"
    req = Request("http://127.0.0.1:8000/api/" + path, method=method, headers=headers,
                  data=None if payload is None else json.dumps(payload).encode())
    try:
        with urlopen(req, timeout=10) as response:
            raw = response.read()
            print(response.status)
            return json.loads(raw) if raw else None
    except HTTPError as exc:
        print(exc.code, exc.read().decode())


tokens = request("POST", "auth/token/", {
    "username": input("Username: "), "password": getpass.getpass("Password: ")
})
request("GET", "accounts/me/", access=tokens["access"])
request("GET", "products/", access=tokens["access"])
request("GET", "valuation/", access=tokens["access"])
old_refresh = tokens["refresh"]
tokens = request("POST", "auth/token/refresh/", {"refresh": old_refresh})
request("POST", "auth/token/refresh/", {"refresh": old_refresh})  # 401 after rotation
request("POST", "auth/logout/", {"refresh": tokens["refresh"]})  # 200
request("POST", "auth/token/refresh/", {"refresh": tokens["refresh"]})  # 401
```

Sales should get products with no cost balances and 403 for valuation. Procurement sees only receipts and their cost snapshots. Viewer sees movement quantities without financial fields. Inventory manager sees valuation but cannot adjust/open stock. Administrator can correct stock. The full comparison is in [the role matrix](00_architecture.md#roles-and-permissions).

## 7. Update earlier tests and add role tests

Staff alone no longer authorizes inventory. In both earlier test classes' `setUp`, call `setup_roles` and assign their staff/posting actor to `Administrator` after creation:

```python
from django.contrib.auth.models import Group
from django.core.management import call_command

call_command("setup_roles", verbosity=0)
self.staff.groups.add(Group.objects.get(name="Administrator"))
```

Use `self.actor.groups.add(...)` in `StockPostingTests`. Keep the regular user groupless: its forbidden test remains valid. Existing forced authentication tests still exercise API behavior; append real JWT tests in `accounts/tests.py`:

```python
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management import call_command
from django.urls import reverse
from rest_framework.test import APITestCase

from inventory.models import Category, Product
from inventory.services import post_stock


class RoleJWTTests(APITestCase):
    def setUp(self):
        call_command("setup_roles", verbosity=0)
        User = get_user_model()
        self.sales = User.objects.create_user(username="sales", password="test-password")
        self.sales.groups.add(Group.objects.get(name="Sales"))
        admin = User.objects.create_superuser(username="admin", password="test-password")
        product = Product.objects.create(sku="JWT-1", name="JWT", price="2.00",
                                         category=Category.objects.create(name="JWT"))
        self.receipt, _ = post_stock(actor=admin, product_id=product.pk, transaction_type="PROCUREMENT",
                                    quantity=2, unit_cost="1.00", request_key=uuid4())
        self.sale, _ = post_stock(actor=admin, product_id=product.pk, transaction_type="SALE",
                                 quantity=1, selling_price="2.00", request_key=uuid4())
        response = self.client.post(reverse("token-obtain"),
                                    {"username": "sales", "password": "test-password"})
        self.assertEqual(response.status_code, 200)
        self.tokens = response.data
        self.client.credentials(HTTP_AUTHORIZATION="Bearer " + self.tokens["access"])

    def test_sales_detail_scope_and_money_fields(self):
        forbidden = self.client.get(reverse("stock-transaction-detail", args=[self.receipt.pk]))
        self.assertEqual(forbidden.status_code, 404)
        sale = self.client.get(reverse("stock-transaction-detail", args=[self.sale.pk]))
        self.assertEqual(sale.status_code, 200)
        self.assertIn("revenue", sale.data)
        self.assertNotIn("cogs", sale.data)
        self.assertNotIn("gross_profit", sale.data)
        self.assertEqual(self.client.get(reverse("valuation")).status_code, 403)

    def test_current_roles_and_inactive_status_override_token(self):
        self.sales.groups.clear()
        self.assertEqual(self.client.get(reverse("product-list")).status_code, 403)
        self.sales.is_active = False
        self.sales.save()
        self.assertEqual(self.client.get(reverse("account-me")).status_code, 401)

    def test_rotated_and_revoked_refresh_cannot_be_reused(self):
        rotated = self.client.post(reverse("token-refresh"), {"refresh": self.tokens["refresh"]})
        self.assertEqual(rotated.status_code, 200)
        self.assertEqual(self.client.post(reverse("token-refresh"),
                                         {"refresh": self.tokens["refresh"]}).status_code, 401)
        self.assertEqual(self.client.post(reverse("token-logout"),
                                         {"refresh": rotated.data["refresh"]}).status_code, 200)
        self.assertEqual(self.client.post(reverse("token-refresh"),
                                         {"refresh": rotated.data["refresh"]}).status_code, 401)
```

```sh
uv run python manage.py check
uv run python manage.py makemigrations --check --dry-run
uv run python manage.py test inventory accounts
```

Repeat the manual role comparison using all five groups and combined Sales/Procurement membership. Test posting a forbidden operation as Inventory manager and as Viewer: service permission denial must leave both history/balance unchanged. The code tests above are focused examples, not a claim of exhaustive security coverage.

## 8. Review changed files

```text
accounts/apps.py + views.py + urls.py + tests.py
accounts/management/commands/setup_roles.py
inventory/models.py + migrations/        custom capabilities
inventory/access.py                     shared authorization and visibility
inventory/services.py                   replace staff-only operation check
inventory/serializers.py + views.py      scope and field permissions
inventory/tests.py                      assign business roles in fixtures
config/settings.py + urls.py            JWT + blacklist + account routes
pyproject.toml + uv.lock
```

Commit after checks and role experiments pass. Next: [Phase 5 — Browser workflows](05_web_interface.md).
