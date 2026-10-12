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

### Prepare your terminal and create the app

Run these commands from the project root containing `manage.py`. Set the Phase 3 PostgreSQL connection variables in this terminal first, and make sure the database is running. If you use the Phase 3 Docker setup:

```sh
docker compose --env-file .env.database -f compose.database.yml up -d --wait db
```

Create the app and install the JWT package:

```sh
uv run python manage.py startapp accounts
uv add djangorestframework-simplejwt
```

`startapp` creates the `accounts/` directory with `apps.py`, `models.py`, `views.py`, `tests.py`, and a migrations directory. It does not register the app or create users. If `accounts/` already exists from a previous attempt, inspect and reuse it rather than running `startapp` again. `uv add` updates `pyproject.toml`, `uv.lock`, and your environment; commit both dependency files.

### Register both apps in settings

Open `config/settings.py` (this checkout: `django_inventory/settings.py`). Find the existing `INSTALLED_APPS` list and append these two entries **inside that list**, keeping all existing Django, DRF, and inventory entries:

```py
    "accounts.apps.AccountsConfig",
    "rest_framework_simplejwt.token_blacklist",
```

Do not replace the whole list or create a second `INSTALLED_APPS` assignment. Check that `accounts/apps.py` defines `AccountsConfig` with `name = "accounts"`; Django's generated file already does this.

The `accounts` app will hold your account endpoints and role-setup command. SimpleJWT's blacklist app stores refresh-token records and revocations; its package includes migrations that you will apply below. Keep the existing Django user model and users: do not set `AUTH_USER_MODEL` or replace the user table. Leave the Phase 3 `REST_FRAMEWORK` authentication settings as they are for now; Step 5 replaces them with JWT/session authentication.

### Add business capabilities to the movement model

Open `inventory/models.py` and find **`StockTransaction`'s** existing `class Meta`, near the end of the file. Add `permissions` alongside its existing `ordering` and `constraints`; do not put it in `Product.Meta` or create another `Meta` class. The assignment below uses eight spaces of indentation because it is inside `Meta`, which is inside `StockTransaction`:

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

Keep the existing `ordering` and positive-quantity constraint. These permission codenames describe actions such as receiving goods or viewing valuation. Adding them does not automatically grant access to any user; Step 3 assigns them to groups, and Step 4 makes the application enforce them.

### Generate and apply migrations

Save the edited files, then run each command separately:

```sh
uv run python manage.py check
uv run python manage.py makemigrations inventory
uv run python manage.py migrate --plan
uv run python manage.py migrate
uv run python manage.py makemigrations --check --dry-run
uv run python manage.py migrate --check
```

Expect the following:

- `check` reports no system-check issues. An import error for SimpleJWT usually means the package is missing from the environment running Django.
- `makemigrations inventory` creates a migration such as `0003_alter_stocktransaction_options.py`. Its operation changes model options; it does not add another stock-transaction table. If you already generated it, `No changes detected` is expected.
- `migrate --plan` previews unapplied migrations, including the inventory options migration and the `token_blacklist` migrations on their first installation.
- `migrate` applies those migrations. Django's post-migration permission creation then supplies the custom permission rows used in Step 3.
- The final two checks report no model changes and exit successfully with no pending migrations.

If you see `KeyError: 'POSTGRES_DB'`, set the Phase 3 variables in this terminal. If the database connection fails, check the running container, host port, and credentials before proceeding. Do not run `setup_roles` until migration succeeds; it needs the permission rows.

### Verify that the capabilities exist

Start the Django shell against the same PostgreSQL database:

```sh
uv run python manage.py shell
```

Paste:

```py
from django.contrib.auth.models import Permission
codes = list(Permission.objects.filter(content_type__app_label="inventory", content_type__model="stocktransaction").order_by("codename").values_list("codename", flat=True))
print(codes)
print("record_sale" in codes, "receive_procurement" in codes, "view_inventory_valuation" in codes)
exit()
```

Expect all nine custom codenames from the `permissions` list, alongside Django's four standard add/change/delete/view permissions for this model. The final print should show `True True True`. If custom permissions are missing, check the placement of `permissions` in `StockTransaction.Meta`, then repeat the migration commands against this database. Continue to Step 3 to create the groups and approve users.

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

This step replaces Phase 3's staff-only rule with the capabilities assigned in Step 3. Keep existing users and stock history. Save each file before moving on; this step changes Python behavior and does not need another migration.

| Layer | File | Purpose |
| --- | --- | --- |
| Shared rules | `inventory/access.py` | Decide who may post, which movements they see, and which financial fields they receive |
| Posting service | `inventory/services.py` | Reject a forbidden operation before changing stock or history |
| API views | `inventory/views.py` | Check endpoint permissions and restrict both list and detail queries |
| Response serializers | `inventory/serializers.py` | Remove financial fields the caller cannot view |

### Create the shared access module

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

`OPERATION_PERMISSIONS` maps each posting type to its required capability. `visible_movements` returns the caller's permitted rows, and `allowed_money_fields` decides which financial fields survive serialization. The permission classes use those same capabilities at the API boundary. `SAFE_METHODS` means GET, HEAD, and OPTIONS; the catalog class treats these as reads.

### Replace the service's old staff-only check

In `inventory/services.py`, delete the **entire existing** `def require_operation(actor, kind):` function, including its indented body. Add this import near the other local imports:

```py
from .access import require_operation
```

Keep `post_stock` and its existing `require_operation(actor, transaction_type)` call at the start. Do not delete that call or leave the old function below the import: a later function definition would override the imported rule. If `PermissionDenied` is no longer used anywhere else in this file, remove it from the `django.core.exceptions` import, keeping `ValidationError`.

This replaces staff access even for shell commands and future HTML forms. An active staff user without the appropriate capability now fails; an active business-role user can post the permitted operation without being staff. In Phase 4, `reconcile_opening` requires an actor with `record_opening_balance`, such as an Administrator or superuser.

### Apply endpoint permissions and movement visibility

In `inventory/views.py`, add:

```py
from .access import CatalogPermission, MovementPermission, ValuationPermission, visible_movements
```

Inside each existing class, add or replace its `permission_classes` assignment using this table. Use four spaces of indentation, alongside `queryset` and `serializer_class`; keep all existing methods:

| Existing class | Assignment to place inside the class |
| --- | --- |
| `CategoryViewSet` | `permission_classes = [CatalogPermission]` |
| `ProductViewSet` | `permission_classes = [CatalogPermission]` |
| `StockTransactionViewSet` | `permission_classes = [MovementPermission]` |
| `ValuationView` | `permission_classes = [ValuationPermission]` |

Importing the classes is not enough: each view must have its own assignment. For example, the beginning of the existing product view becomes:

```py
class ProductViewSet(viewsets.ModelViewSet):
    permission_classes = [CatalogPermission]
    queryset = Product.objects.select_related("category").all()
    serializer_class = ProductSerializer
```

Keep its existing methods below those lines. Apply the table's assignments to the other three views too. Without them, Step 5's global `IsAuthenticated` rule allows a groupless authenticated user to access endpoints, and role tests expecting 403 will fail.

The explicit classes override the global Phase 3 `IsAdminUser` default for these endpoints. Do not replace their view base classes or remove `create`, `perform_destroy`, or `get`. Step 5 changes the global default for account endpoints.

Add the following method **inside `StockTransactionViewSet`**, at the same indentation level as its existing `create` method. Keep its existing `queryset` assignment for router metadata. If `get_queryset` already exists, replace that method rather than defining it twice:

```python
    def get_queryset(self):
        return visible_movements(self.request.user)
```

This scopes detail lookups too: a Sales user requesting a procurement ID gets 404. It does not delete or alter the hidden movement. `MovementPermission` allows a user who can post at least one operation to reach `create`; the service then checks the specific requested type. For example, Sales cannot post procurement even though Sales can POST a sale to the same endpoint.

### Filter financial fields in responses

In `inventory/serializers.py`, add this import:

```py
from .access import FINANCIAL_FIELDS, allowed_money_fields
```

Add the following method inside `StockTransactionSerializer`, with four spaces of indentation. It is a sibling of `class Meta`, **not inside `Meta`**. Keep the existing fields and `read_only_fields`:

```python
    def to_representation(self, instance):
        data = super().to_representation(instance)
        user = self.context["request"].user
        for field in FINANCIAL_FIELDS - allowed_money_fields(user, instance.transaction_type):
            data.pop(field, None)
        return data
```

Add the following inside `ProductSerializer`, also alongside its `Meta` class. Keep the existing read-only balance fields, which prevent clients from changing stock/value:

```python
    def to_representation(self, instance):
        data = super().to_representation(instance)
        user = self.context["request"].user
        if not user.has_perm("inventory.view_inventory_valuation"):
            data.pop("average_unit_cost", None)
            data.pop("inventory_value", None)
        return data
```

`to_representation` changes the output for the current caller; it does not change the stored movement or its valuation calculations. With the Step 3 groups, expect:

| Role | Movement visibility | Movement financial fields | Product cost/value |
| --- | --- | --- | --- |
| Viewer | All movement types | None | Hidden |
| Sales | Sales only | Selling price and revenue | Hidden |
| Procurement | Procurement only | Unit cost and value change | Hidden |
| Inventory manager / Administrator | All movement types | All financial fields | Visible |

Combined groups grant the union of their capabilities. Only Inventory manager, Administrator, or a superuser can access the valuation endpoint under this matrix. Inventory manager cannot post adjustments/opening balances; Administrator can.

Require request context whenever using these serializers. DRF supplies it through `self.get_serializer(...)` in the existing views. If you construct a serializer directly, pass the request explicitly:

```py
serializer = ProductSerializer(product, context={"request": request})
```

This line illustrates use inside code that already has `product` and `request` variables; it is not a standalone shell command. Omitting context causes `KeyError: 'request'`. Phase 5 supplies it explicitly for its own uses. Filtering only lists or hiding buttons is insufficient: serializers, details, totals, and the service all enforce access.

### Check the edits before adding JWT

In your terminal with the Phase 3 database variables set, run:

```sh
uv run python manage.py check
uv run python manage.py makemigrations --check --dry-run
```

Expect no system-check issues and `No changes detected`. If imports fail, confirm `access.py` is in `inventory/`, the imported names match, and `services.py` no longer defines its old `require_operation`. If a serializer method is not taking effect, check that it is inside the serializer class rather than its `Meta`.

At this point Basic/session authentication still identifies users; access is already controlled by their capabilities. Make sure Step 3's `setup_roles` ran after migrations and the intended users belong to their groups. Staff status alone is no longer sufficient. Continue to Step 5 for JWT, then Step 7 to update the earlier staff-only test fixtures and run the complete suite. Those fixtures need role assignments before their old success tests can pass under these new rules.

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

### Terminal A: check and start the server

Open a terminal in the project root containing `manage.py`. Set the Phase 3 PostgreSQL environment variables in this terminal again if needed. Start the database if you use the local Docker setup, then run the checks:

```sh
docker compose --env-file .env.database -f compose.database.yml up -d --wait db
uv run python manage.py check
uv run python manage.py makemigrations --check --dry-run
uv run python manage.py migrate --check
```

Skip the Docker command if you use an installed PostgreSQL server. Expect no system-check issues, no model changes, and no unapplied migrations. If migrations are pending, run `uv run python manage.py migrate` before continuing. Complete Step 3's `setup_roles` and user/group assignment first; token login identifies a user, but does not assign their role.

Start the development server:

```sh
uv run python manage.py runserver 127.0.0.1:8000
```

Expect `Starting development server at http://127.0.0.1:8000/`. Leave Terminal A running while making requests below; it shows their HTTP status codes and any server errors. Stop it afterward with `Ctrl+C`.

If port 8000 is occupied, use `uv run python manage.py runserver 127.0.0.1:8001` and change the request helper's URL from port 8000 to 8001. A database connection error usually means the container is stopped or the terminal's PostgreSQL variables do not match its host port/credentials.

### Terminal B: obtain tokens and try the API

Open a second terminal at the project root while Terminal A stays running. The following examples go in a Python prompt, not directly in PowerShell/Bash. They make HTTP requests, so this client terminal does not need PostgreSQL variables. If you already have a Python prompt open, reuse it and paste the helper below; otherwise start one with:

```sh
uv run python
```

Use an active account assigned to the Sales group, such as `sales_demo` from Step 3. Basic authentication from Phase 3 has been removed; this helper obtains JWTs and uses Bearer authentication. Keep tokens in this local session and do not commit them.

Paste the helper and run the requests one at a time in Terminal B's Python prompt. If token login fails, resolve the reported error before using `tokens["access"]`:

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

This step verifies two things: the Phase 3 stock rules still work under business permissions, and actual JWT-authenticated requests respect roles and token revocation. Keep the earlier test classes and assertions; update their users to match the new authorization rules.

### Give the earlier test users a business role

Open `inventory/tests.py`. Add these imports at the top, merging with existing imports rather than duplicating them:

```py
from django.contrib.auth.models import Group
from django.core.management import call_command
```

Tests use a separate database, so groups created by `setup_roles` in your development database are not available to them automatically. Each test fixture needs to seed the groups and assign the appropriate role. Django creates the permission rows when migrating the test database.

Staff alone no longer authorizes inventory. In both earlier test classes' `setUp`, call `setup_roles` and assign their staff/posting actor to `Administrator` after creation:

```python
from django.contrib.auth.models import Group
from django.core.management import call_command

call_command("setup_roles", verbosity=0)
self.staff.groups.add(Group.objects.get(name="Administrator"))
```

For `InventoryAPITests.setUp`, run `call_command("setup_roles", verbosity=0)` before looking up the group, then add the group to `self.staff` immediately after creating that user. Keep the existing category/product fixtures and `self.client.force_authenticate(user=self.staff)`.

For `StockPostingTests.setUp`, use the actor variable instead. The beginning of that method should be:

```py
    def setUp(self):
        call_command("setup_roles", verbosity=0)
        self.actor = get_user_model().objects.create_user(username="poster", is_staff=True)
        self.actor.groups.add(Group.objects.get(name="Administrator"))
```

Replace the existing beginning of `StockPostingTests.setUp` with these lines; do not append another `create_user(username="poster", ...)` call. Creating `poster` twice in the same fixture raises a duplicate-username `IntegrityError` before the test can run. Keep the existing `self.product = Product.objects.create(...)` immediately after these lines, inside the same method. Do not replace the whole fixture with this partial example or add a second `setUp`: Python would use only the last definition.

Administrator is used here so the existing stock tests can concentrate on valuation, rollback, and concurrency. It is a business group, not a superuser flag. Keep the regular user groupless: its forbidden test remains valid. Staff alone no longer grants inventory access.

### Add tests that obtain and use real JWTs

Open `accounts/tests.py`. Replace its generated placeholder with the following, or merge these imports and append the class if it already contains tests. Do not put this class inside a view or another test class:

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

The `setUp` method runs before every test. It creates isolated users, groups, a product, one receipt, and one sale. It then posts the Sales user's credentials to the actual token endpoint and puts the returned access token in the client's Bearer header. Unlike the older `force_authenticate` fixtures, these requests exercise JWT authentication itself. The password shown is only for the disposable test user; do not reuse it for your real accounts.

| Test | Behavior it verifies | Why the expected status matters |
| --- | --- | --- |
| `test_sales_detail_scope_and_money_fields` | Sales can read its sale but cannot see procurement details, cost/profit, or global valuation | Hidden procurement returns 404; forbidden valuation returns 403 |
| `test_current_roles_and_inactive_status_override_token` | Removing groups affects an already-issued token, and deactivation blocks authentication | Missing role returns 403; an inactive account returns 401 |
| `test_rotated_and_revoked_refresh_cannot_be_reused` | Refresh rotation invalidates the old refresh token, and logout invalidates its replacement | Successful rotation/logout returns 200; reuse returns 401 |

Logout revokes the submitted refresh token; an existing access token may remain usable until its five-minute expiry. These tests do not claim immediate access-token revocation.

### Run checks and tests against PostgreSQL

Use a terminal at the project root with the Phase 3 PostgreSQL variables set and the database running. Run commands separately so a failed check is resolved before the next step:

```sh
uv run python manage.py check
uv run python manage.py makemigrations --check --dry-run
uv run python manage.py migrate --check
uv run python manage.py test inventory accounts --verbosity 2
```

Expect no system-check issues, no model changes, no pending migrations, and **14 passing tests** if you kept Phase 2's six, Phase 3's five, and added these three. Additional tests can increase the count. The concurrency test must run on PostgreSQL rather than being skipped. Django creates a separate `test_<database-name>` database and removes it afterward; it does not run the fixtures against your development inventory. The local database role needs permission to create a test database, as configured in Phase 3.

To isolate failures, run one class or method:

```sh
uv run python manage.py test accounts.tests.RoleJWTTests --verbosity 2
uv run python manage.py test inventory.tests.StockPostingTests --verbosity 2
uv run python manage.py test accounts.tests.RoleJWTTests.test_rotated_and_revoked_refresh_cannot_be_reused --verbosity 2
```

Common failures:

- `Group.DoesNotExist`: run `setup_roles` inside each relevant `setUp` before assigning the group; development groups are not test fixtures.
- `Missing inventory...; run migrate first`: check the custom permission options and their migration from Step 2.
- `403` in an old success test: check the fixture's group assignment and that the intended permission class is installed; setting `is_staff=True` alone is insufficient.
- `NoReverseMatch`: check Step 5's account route names and project URL include, plus the Phase 3 stock router registration.
- Old refresh token still succeeds: check `ROTATE_REFRESH_TOKENS`, `BLACKLIST_AFTER_ROTATION`, and the installed blacklist app.
- Permission denied creating the test database: use the local test-capable PostgreSQL role, not a restricted production role.

### Compare the remaining roles manually

Repeat Step 6's authenticated requests using all five groups and combined Sales/Procurement membership. Viewer can read catalog and movement quantities but cannot post. Sales can post sales; Procurement can receive goods. Inventory manager can manage catalog and view valuation, but adjustments/opening balances require Administrator. Combined Sales/Procurement membership permits both workflows without exposing cost/profit beyond the field rules in Step 4.

For a forbidden posting, compare the product quantity/value and movement count before and after: expect 403 and no changes. If changing groups while experimenting in the Django shell, reload the user before checking permissions because Django can cache permissions on that user instance. HTTP requests load the current user again. The code tests above are focused examples, not a claim of exhaustive security coverage.

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
