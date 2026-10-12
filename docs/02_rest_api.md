# 02 — Build the inventory REST API

Continue from [phase 1](01_getting_started.md). You already have `Category` and `Product` models, migrations, Django admin, and a superuser. This phase exposes authenticated CRUD endpoints using Django REST Framework (DRF).

Run terminal commands from the repository root containing `manage.py`. Keep the Python 3.12, Django 5.2, and DRF 3.16 dependencies from phase 1. No additional packages are required.

## 1. Understand the request flow

```text
Client sends HTTP request
    ↓
Django middleware and URL resolution
    ↓
DRF ViewSet dispatch: authentication and permission checks
    ↓
Selected action (list, retrieve, create, update, or destroy)
    ↓
For writes: parse request body → serializer validation
    ↓
Django ORM reads or writes database records
    ↓
For data responses: serializer produces Python response data
    ↓
DRF Response → renderer (JSON or browsable HTML) → Django middleware
    ↓
Client receives HTTP status, headers, and body
```

Authentication identifies the caller, and permissions decide whether the caller can proceed before the action runs.

| DRF component | Responsibility | FastAPI / Spring comparison |
| --- | --- | --- |
| Serializer | Validate input and shape output | Pydantic schema / request-response DTO |
| ViewSet | Group related endpoint actions | Related route handlers / REST controller |
| Router | Generate URLs for those actions | `APIRouter` registration / request mappings |
| Permission class | Control access | Authorization dependency / security rule |

A `ModelSerializer` also knows how to create/update ORM objects; that is broader than a Pydantic schema alone. A Django model describes persistence, while the serializer defines the public API contract.

This diagram describes the main application flow, not every internal lifecycle operation. Reads do not need input serializer validation, and a successful delete has no response body. Authentication and validation can themselves query the database before the main action reads or writes a product.

### Follow a product-creation request

Imagine a staff user sends this request after you complete the implementation below. Category `3` must already exist; use an actual category ID when trying it:

```http
POST /api/products/ HTTP/1.1
Host: 127.0.0.1:8000
Content-Type: application/json
Accept: application/json
Authorization: Basic <credentials supplied by your client>

{
  "sku": "FLOW-KB-001",
  "name": "Flow Demo Keyboard",
  "category": 3,
  "price": "79.90"
}
```

This is an illustrative HTTP message, not a terminal command. Step 7 provides executable requests without putting your password in the document.

**1. Django finds the matching URL.** The server passes the request through Django's request handling and middleware. In `config/urls.py`, the `api/` prefix delegates to `inventory/urls.py`. The router-generated pattern matches `products/`, and its method mapping selects `ProductViewSet.create` for `POST`. The router generates URL patterns when the URL configuration loads; it is not a separate network service that forwards each request.

**2. DRF checks who is calling and whether they have access.** DRF wraps the request in its `Request` interface. With this guide's settings, Basic authentication or a browser session identifies the user, accessible as `request.user`. `IsAdminUser` then checks whether that user is staff. These checks run before the create action. A failure ends the request before product creation. See the [DRF view lifecycle](https://www.django-rest-framework.org/api-guide/views/).

**3. The create action reads parsed input.** When the action accesses `request.data`, DRF uses a parser selected from the request's `Content-Type`. For `application/json`, valid JSON becomes Python data, such as a dictionary. Parsing handles the body's format; it does not establish whether the SKU, category, or price is acceptable. `Accept` has a different role: it requests a response format. See [DRF requests](https://www.django-rest-framework.org/api-guide/requests/).

**4. The serializer validates the input.** The inherited create action constructs `ProductSerializer(data=request.data)` and calls `is_valid(raise_exception=True)`. It checks required values, field formats, unique SKU, category existence, and price validation. Valid input becomes `serializer.validated_data`; for example, the category ID becomes a `Category` instance and the price becomes a `Decimal`. Validation may issue database queries, but it has not inserted the product yet. Read-only fields are excluded from writable input.

**5. The ORM creates the record.** After validation, the action calls `perform_create(serializer)`, whose default implementation calls `serializer.save()`. Because this serializer has no existing instance, `ModelSerializer` uses its create behavior to create a `Product` through Django's ORM. The database assigns the ID, and model defaults/timestamps supply the stock balance and dates. Database constraints still apply; serializer validation does not replace them or automatically call the model's `full_clean()`. See [generic-view save hooks](https://www.django-rest-framework.org/api-guide/generic-views/#save-and-deletion-hooks).

**6. The serializer shapes the result.** The saved model is represented through `serializer.data`, using the explicit public field list. The result contains the ID, category ID/name, decimal price string, stock balance, and timestamps. This is Python response data at this point, not yet JSON bytes.

**7. DRF renders and returns the response.** The action returns a DRF `Response` with status `201 Created`. Content negotiation selects a renderer; with `Accept: application/json`, the JSON renderer turns the response data into the HTTP body. Django's response middleware also gets a chance to process the response before it reaches the client. In a browser, negotiation can instead select DRF's HTML browsable API. See [renderers](https://www.django-rest-framework.org/api-guide/renderers/).

The core create action can be pictured as the following simplified pseudocode. You do **not** need to paste this into the ViewSet; `ModelViewSet` already provides it:

```python
serializer = self.get_serializer(data=request.data)
serializer.is_valid(raise_exception=True)
self.perform_create(serializer)
return Response(serializer.data, status=201)
```

### How reading and updating differ

For `GET /api/products/`, the router selects `list`. After the access checks, the ViewSet obtains its queryset and serializes the results with `many=True`. QuerySets are lazy: building one does not immediately fetch all records; evaluation triggers the query. Our `select_related("category")` loads the category alongside each product for `category_name`. The read returns `200 OK` and does not create or modify products.

For `GET /api/products/12/`, the router selects `retrieve` and supplies the lookup value `12`. The ViewSet finds that product, serializes one instance, and returns `200`; if it does not exist, it returns `404`.

For `PATCH /api/products/12/`, the action first obtains the existing product, then constructs a serializer with both the instance and incoming data, with `partial=True`. After validation, `serializer.save()` updates that instance. Only supplied writable fields change. `PUT` uses the full-update path and requires required writable fields to be supplied.

For `DELETE /api/categories/3/`, the action obtains the category and calls `perform_destroy`. Our override converts Django's protection error into `409 Conflict` if products still reference it. A successful deletion returns `204 No Content` without serializing a deleted object.

### Know where errors come from

| Stage | Example | Response in this tutorial |
| --- | --- | --- |
| Authentication | Missing credentials or invalid Basic credentials | 401 |
| Permission check | Authenticated user is not staff | 403 |
| Parsing | Malformed JSON body | 400 |
| Serializer validation | Negative price, duplicate SKU, or unknown category ID | 400 with field errors |
| Object lookup | Product ID does not exist | 404 |
| Method dispatch | Unsupported method, such as POST to a detail URL | 405 |
| Delete/business rule | Category still has products | 409 with a detail message |

An error stops the normal success path. For example, a negative price fails validation before a product write. DRF converts its supported exceptions into HTTP error responses; unexpected database or programming errors still need appropriate handling and are not automatically meaningful client errors.

### Connect this to FastAPI and Spring

In FastAPI, you might write a route that receives a Pydantic request model, checks a dependency, uses an ORM session, and returns a response model. In DRF, `ModelViewSet` supplies the common action code and `ModelSerializer` combines much of the validation and model conversion. You configure these pieces through `queryset`, `serializer_class`, and permission settings, then override hooks when domain behavior needs to change.

In Spring, the nearest conceptual flow is request mapping → security checks → controller → DTO validation/mapping → persistence → response serialization. For this simple CRUD phase, DRF's defaults cover the persistence step without a separate service class. Phase 3 will introduce a service function for stock movements, because creating a movement and updating the balance must follow shared business rules.

When debugging a request, follow the same boundaries: confirm the URL/action, check `request.user`, inspect parsed `request.data`, inspect serializer errors, then inspect the ORM write and output representation. This makes it easier to locate whether the problem concerns routing, access, validation, persistence, or presentation.

## 2. Create the serializers

Create `inventory/serializers.py`:

```python
from rest_framework import serializers

from .models import Category, Product


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
            "category",
            "category_name",
            "price",
            "stock_quantity",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "stock_quantity", "created_at", "updated_at"]
```

Clients send a category's numeric primary key in `category`. Responses include both that ID and the convenient `category_name` string. DRF validates that the referenced category exists. Model-derived validation also checks unique SKUs, required fields, maximum lengths, and the price's nonnegative validator from phase 1. See [ModelSerializer](https://www.django-rest-framework.org/api-guide/serializers/#modelserializer).

The explicit field list keeps future model fields from automatically becoming public. Prices are represented as decimal strings such as `"79.90"` under DRF's default settings.

Stock is read-only in the API now, preparing for phase 3's movement history. A newly created product uses the model default of zero. Existing phase 1 products retain their current stock. DRF ignores incoming read-only fields rather than reporting them as invalid; a request containing `stock_quantity` will not change the balance. Admin and shell edits still remain possible at this stage.

## 3. Choose authentication and permissions

Add this setting at the end of `config/settings.py`. If you already have `REST_FRAMEWORK`, merge these entries into it instead of defining it twice:

```python
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.BasicAuthentication",
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAdminUser",
    ],
}
```

This learning API is for inventory staff: every action, including reading data, requires an active authenticated staff user. `IsAdminUser` checks `is_staff`; it does not require `is_superuser`. The phase 1 superuser qualifies. A regular authenticated user receives `403 Forbidden`. An unauthenticated request receives `401 Unauthorized` with this authentication order. See [permissions](https://www.django-rest-framework.org/api-guide/permissions/#isadminuser).

Session authentication supports browser login. Basic authentication makes terminal experiments straightforward; use it only on localhost here and HTTPS if used remotely. Browser session writes require CSRF protection; the browsable API forms supply the token. An existing admin login supplies a session, while the permission setting controls API access. See [authentication](https://www.django-rest-framework.org/api-guide/authentication/).

## 4. Create the ViewSets

Replace `inventory/views.py` with:

```python
from django.db.models.deletion import ProtectedError
from rest_framework import status, viewsets
from rest_framework.exceptions import APIException

from .models import Category, Product
from .serializers import CategorySerializer, ProductSerializer


class CategoryInUse(APIException):
    status_code = status.HTTP_409_CONFLICT
    default_detail = "This category still has products. Reassign or delete them first."
    default_code = "category_in_use"


class CategoryViewSet(viewsets.ModelViewSet):
    queryset = Category.objects.all()
    serializer_class = CategorySerializer

    def perform_destroy(self, instance):
        try:
            instance.delete()
        except ProtectedError as exc:
            raise CategoryInUse() from exc


class ProductViewSet(viewsets.ModelViewSet):
    queryset = Product.objects.select_related("category").all()
    serializer_class = ProductSerializer
```

`ModelViewSet` supplies list, retrieve, create, update, partial update, and delete actions. The serializers handle validated writes. `select_related` loads each product's category in the same query, so rendering `category_name` does not cause a separate lookup for each product. See [ViewSets](https://www.django-rest-framework.org/api-guide/viewsets/).

Phase 1's category relation uses `PROTECT`. Converting `ProtectedError` into a `409` response gives callers a useful conflict message when they try to delete a category that still contains products.

This phase allows product deletion. Before introducing movement history, decide how products with recorded movements will be retained or archived.

## 5. Register the routes

Create `inventory/urls.py`:

```python
from rest_framework.routers import DefaultRouter

from .views import CategoryViewSet, ProductViewSet

router = DefaultRouter()
router.register("categories", CategoryViewSet, basename="category")
router.register("products", ProductViewSet, basename="product")

urlpatterns = router.urls
```

Replace `config/urls.py` with:

```python
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", include("inventory.urls")),
    path("api-auth/", include("rest_framework.urls")),
]
```

`DefaultRouter` generates resource routes and an API root at `/api/`. `basename` controls URL names, such as `product-list` and `product-detail`; the registration prefix controls the URL path. `api-auth/` adds login/logout for the browsable API. See [routers](https://www.django-rest-framework.org/api-guide/routers/).

| Method | URL | Action | Success status |
| --- | --- | --- | --- |
| GET | `/api/products/` | List | 200 |
| POST | `/api/products/` | Create | 201 |
| GET | `/api/products/{id}/` | Retrieve | 200 |
| PUT | `/api/products/{id}/` | Replace writable fields | 200 |
| PATCH | `/api/products/{id}/` | Update selected fields | 200 |
| DELETE | `/api/products/{id}/` | Delete | 204 |

Categories have the same actions under `/api/categories/`. Use the actual numeric ID in place of `{id}` and include the trailing slash, especially for writes. Use `PATCH` for partial changes; `PUT` requires all required writable fields. Lists are JSON arrays because this guide does not enable pagination yet.

## 6. Check and run the application

### Create login accounts before trying the API

Users are database records, not source-code changes. Apply the existing migrations first:

```sh
uv run python manage.py migrate
```

If you do not already have the Phase 1 administrator, create a superuser:

```sh
uv run python manage.py createsuperuser --username inventory_admin
```

Enter an email (optional with Django's default user model) and a password when prompted. A superuser has `is_active=True`, `is_staff=True`, and `is_superuser=True` and can manage users in Admin. If that username already exists, reuse it rather than creating it again. Reset a forgotten password with `uv run python manage.py changepassword inventory_admin`.

Create a separate staff account for the inventory API and a regular user for checking denied access. Start the Django shell:

```sh
uv run python manage.py shell
```

Paste the following into the Django shell. Choose unused usernames and strong local passwords. `getpass` prompts without including passwords in the code:

```py
from getpass import getpass
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
User = get_user_model()
staff = User(username="inventory_staff", is_active=True, is_staff=True, is_superuser=False)
password = getpass("New staff password: ")
validate_password(password, user=staff)
staff.set_password(password)
staff.save()
regular = User(username="inventory_reader", is_active=True, is_staff=False, is_superuser=False)
password = getpass("New regular-user password: ")
validate_password(password, user=regular)
regular.set_password(password)
regular.save()
list(User.objects.filter(username__in=["inventory_staff", "inventory_reader"]).values("username", "is_active", "is_staff", "is_superuser"))
exit()
```

If password validation raises an error, enter a new password and repeat `validate_password` before continuing. `set_password` hashes the password; never assign a raw password to `user.password`. Run account creation once; if a username exists, reuse it or choose another. Expect both accounts active, only `inventory_staff` marked staff, and neither marked superuser.

Alternatively, after starting the server below, sign into `/admin/` as `inventory_admin`, open **Users → Add**, enter the username/password, then edit the saved user's permissions. Set **Active** and **Staff status** for the staff account; keep **Superuser status** unchecked. A regular user has only **Active** checked. Staff status grants this phase's API access; it does not grant all Django Admin model permissions.

### List existing users

Before creating another account or choosing a username for later commands, list the users in the currently configured database:

```sh
uv run python manage.py shell
```

Paste the following into the Django shell:

```py
from django.contrib.auth import get_user_model
User = get_user_model()
list(User.objects.order_by("username").values("id", "username", "is_active", "is_staff", "is_superuser"))
list(User.objects.filter(is_active=True, is_staff=True).order_by("username").values("id", "username"))
exit()
```

The first query lists all accounts and their permission flags. The second lists active staff users, including superusers, suitable for this phase's API and Phase 3's opening reconciliation. An empty list means there are no matching users in this database. These queries do not display passwords or password hashes.

Once the server is running, you can also sign into `/admin/` as a superuser and open **Users** to browse, search, and filter accounts.

### Delete or deactivate a user

For an unused local account, start `uv run python manage.py shell` and look up the exact username before deleting it. Replace `inventory_reader` with the account you intend to remove:

```py
from django.contrib.auth import get_user_model
User = get_user_model()
user = User.objects.get(username="inventory_reader")
print(user.pk, user.username, user.is_active, user.is_staff, user.is_superuser)
```

Check the printed identity. Only after confirming it is the intended account, run:

```py
user.delete()
print(User.objects.filter(username="inventory_reader").exists())
exit()
```

Expect `False` from the existence check. Deletion is permanent and may delete related records through cascading relationships; review those relationships before deleting users with application data. Do not delete your only administrator. A missing username raises `User.DoesNotExist`; use the user-list steps above to choose an existing account.

From Phase 3 onward, stock transactions reference their actor with `on_delete=PROTECT`. Deleting a user with recorded movements raises `ProtectedError`, preserving the audit history. Deactivate that user instead, keeping their identity attached to past movements:

```sh
uv run python manage.py shell
```

```py
from django.contrib.auth import get_user_model
User = get_user_model()
user = User.objects.get(username="inventory_reader")
user.is_active = False
user.save(update_fields=["is_active"])
print(user.username, user.is_active)
exit()
```

Use the actual username and expect `False` for active status. With the tutorial's authentication configuration, an inactive user cannot authenticate; deactivation does not erase their history. It also leaves their staff/superuser flags unchanged if you later reactivate them.

Alternatively, sign into `/admin/` as a superuser, open **Users**, and select the exact account. Use **Delete** and review Django's related-object confirmation page before confirming. To deactivate, uncheck **Active** and save. If protected stock movements block deletion, use deactivation rather than removing the movements.

### Start the server and verify access

```sh
uv run python manage.py check
uv run python manage.py makemigrations --check --dry-run
uv run python manage.py runserver
```

You should see no system-check issues and no model changes. Serializers, views, URLs, and DRF settings do not change the database schema, so this phase needs no new migration.

Open [http://127.0.0.1:8000/api/](http://127.0.0.1:8000/api/). If you are not authenticated, the API returns an authorization error; use the browsable API's **Log in** link or your existing admin session. Then open `/api/categories/` and `/api/products/` to inspect the data and use the generated forms.

## 7. Try requests from any terminal

Keep the server running. In another terminal at the repository root, run:

```sh
uv run python
```

Paste this helper into the Python prompt. It uses only the standard library, so the same example works in PowerShell, Bash, and Zsh. Enter `inventory_staff` (or your chosen active staff/superuser account) and its password when prompted; the password is not included in the code or saved to a file. To verify permissions afterward, restart the helper with `inventory_reader` and request the product list: expect `403`, while the staff account receives `200`.

```python
import base64
import getpass
import json
from urllib.error import HTTPError
from urllib.request import Request, urlopen

username = input("Username: ")
password = getpass.getpass("Password: ")
credentials = base64.b64encode(f"{username}:{password}".encode()).decode()


def api_request(method, path, payload=None):
    body = None if payload is None else json.dumps(payload).encode()
    request = Request(
        f"http://127.0.0.1:8000/api/{path}",
        data=body,
        method=method,
        headers={
            "Authorization": f"Basic {credentials}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
    )
    try:
        with urlopen(request, timeout=10) as response:
            raw = response.read().decode()
            print(response.status)
            result = json.loads(raw) if raw else None
            print(json.dumps(result, indent=2))
            return result
    except HTTPError as exc:
        print(exc.code, exc.read().decode())
        return None

```

Run these examples in order. Choose different names/SKUs if you have already run them; unique values cannot be created twice.

```python
category = api_request("POST", "categories/", {"name": "API Demo"})
```

Expect `201` and a category object with an `id`. If creation failed, fix the error before continuing; the later examples require that object.

```python
product = api_request("POST", "products/", {
    "sku": "API-KB-001",
    "name": "API Keyboard",
    "category": category["id"],
    "price": "79.90",
})
```

Expect `201`, `stock_quantity: 0`, and `category_name: "API Demo"`. Use the returned product ID for retrieval and updates:

```python
api_request("GET", "products/")
api_request("GET", f"products/{product['id']}/")
api_request("PATCH", f"products/{product['id']}/", {"price": "74.90"})
api_request("PATCH", f"products/{product['id']}/", {"price": "-1.00"})
```

The first three requests return `200`. The last returns `400` with a `price` validation error; the stored price stays `74.90`. Missing resources return `404`. A duplicate SKU or a nonexistent category ID also produces a `400` validation error.

Try deleting the category while it still contains the product, then remove the demo records in dependency order:

```python
api_request("DELETE", f"categories/{category['id']}/")
api_request("DELETE", f"products/{product['id']}/")
api_request("DELETE", f"categories/{category['id']}/")
exit()
```

Expect `409`, `204`, then `204`. A `204` has no response body; the helper prints `null` for it. These delete commands remove only the demo records referenced by the returned IDs.

## 8. Add focused API tests

Replace the generated placeholder `inventory/tests.py` with the following. If you have already written tests there, add this class and merge the imports instead.

```python
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from .models import Category, Product


class InventoryAPITests(APITestCase):
    def setUp(self):
        User = get_user_model()
        self.staff = User.objects.create_user(
            username="inventory_staff", password="test-only-password", is_staff=True
        )
        self.regular_user = User.objects.create_user(
            username="regular_user", password="test-only-password"
        )
        self.category = Category.objects.create(name="Test Accessories")
        self.product = Product.objects.create(
            sku="TEST-KB-001",
            name="Test Keyboard",
            category=self.category,
            price=Decimal("79.90"),
            stock_quantity=10,
        )
        self.client.force_authenticate(user=self.staff)

    def test_anonymous_cannot_list_products(self):
        self.client.force_authenticate(user=None)
        response = self.client.get(reverse("product-list"))
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_regular_user_cannot_list_products(self):
        self.client.force_authenticate(user=self.regular_user)
        response = self.client.get(reverse("product-list"))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_create_product_ignores_client_stock_balance(self):
        response = self.client.post(
            reverse("product-list"),
            {
                "sku": "TEST-MOUSE-001",
                "name": "Test Mouse",
                "category": self.category.pk,
                "price": "25.00",
                "stock_quantity": 999,
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        product = Product.objects.get(pk=response.data["id"])
        self.assertEqual(product.stock_quantity, 0)
        self.assertEqual(response.data["category_name"], self.category.name)

    def test_negative_price_does_not_change_product(self):
        response = self.client.patch(
            reverse("product-detail", args=[self.product.pk]),
            {"price": "-1.00"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("price", response.data)
        self.product.refresh_from_db()
        self.assertEqual(self.product.price, Decimal("79.90"))

    def test_duplicate_sku_is_rejected(self):
        response = self.client.post(
            reverse("product-list"),
            {
                "sku": self.product.sku,
                "name": "Duplicate Keyboard",
                "category": self.category.pk,
                "price": "10.00",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("sku", response.data)
        self.assertEqual(Product.objects.count(), 1)

    def test_used_category_cannot_be_deleted(self):
        response = self.client.delete(
            reverse("category-detail", args=[self.category.pk])
        )
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        self.assertTrue(Category.objects.filter(pk=self.category.pk).exists())
        self.assertTrue(Product.objects.filter(pk=self.product.pk).exists())
```

Run:

```sh
uv run python manage.py test inventory
```

Expect six passing tests. Django uses a separate test database; these tests do not alter your development inventory. `force_authenticate` isolates permission/API behavior; it does not test the real password or browser CSRF flow. The manual requests in step 7 exercise Basic authentication with an actual account.

## 9. Review the changed files

```text
django_inventory/
├── config/
│   ├── settings.py              # DRF authentication and permissions
│   └── urls.py                  # API and browser login routes
├── inventory/
│   ├── serializers.py           # new: input/output contracts
│   ├── views.py                 # CRUD ViewSets
│   ├── urls.py                  # new: router registration
│   └── tests.py                 # API behavior tests
└── docs/
    ├── 01_getting_started.md
    └── 02_rest_api.md
```

This diagram shows only files relevant to phase 2; keep the rest of phase 1's structure. Commit these changes after checks and tests pass. No dependency or migration changes are needed.

## 10. Next: StockTransaction and inventory rules

Phase 3 will add stock receipts and withdrawals with an auditable movement history:

1. Define `StockTransaction` with a product, typed operation, positive whole-unit quantity, notes/reference, timestamp, and actor; the type determines stock direction.
2. Record opening balances for existing products so history agrees with current stock.
3. Put stock updates and movement creation in a single database transaction; prevent negative balances and handle concurrent requests for the chosen database.
4. Expose a controlled movement endpoint instead of generic edits to transaction history.
5. Make stock balances read-only in admin too, and protect products with recorded movements from deletion or introduce archiving.
6. Test receipts, withdrawals, insufficient stock, rollback, permissions, and concurrency.

Pagination, search/filtering, API schema documentation, and production authentication can follow once the core inventory rules are in place.

## References

- [DRF serializers](https://www.django-rest-framework.org/api-guide/serializers/)
- [DRF ViewSets](https://www.django-rest-framework.org/api-guide/viewsets/)
- [DRF routers](https://www.django-rest-framework.org/api-guide/routers/)
- [DRF authentication](https://www.django-rest-framework.org/api-guide/authentication/)
- [DRF permissions](https://www.django-rest-framework.org/api-guide/permissions/)
- [DRF testing](https://www.django-rest-framework.org/api-guide/testing/)
