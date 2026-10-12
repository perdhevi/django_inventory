# 03 — PostgreSQL, stock transactions, and valuation

Continue from [Phase 2](02_rest_api.md). You will receive goods, sell goods, and keep their quantity and cost history consistent. Apply the steps in order from the directory containing `manage.py`. These are tutorial changes to apply, not a claim that this checkout already implements them.

The earlier tutorials call the settings package `config`. This checkout calls it `django_inventory`: use `django_inventory/settings.py` and `django_inventory/urls.py` wherever these guides say `config/settings.py` and `config/urls.py`. Keep your existing package name and working Python environment. The examples retain the Django 5.2 tutorial baseline.

## 1. Understand the request flow and valuation policy

```text
POST /api/stock_transactions/
  -> authenticate -> serializer validates input
  -> shared post_stock() service
  -> atomic transaction + PostgreSQL product row lock
  -> insert movement + update product balance
  -> commit -> return historical snapshots
```

Unlike Phase 2 CRUD, this write changes two records together. The service is equivalent to a Spring service method or a FastAPI business function. Phase 5 pages will call it too.

Use **IDR**, whole units, two decimal places for unit prices, six for inventory cost, and `ROUND_HALF_UP`. `price` remains the default selling price. Withdrawals calculate cost from stored remaining value divided by stock, not the rounded display average. The final withdrawal consumes all remaining value.

Each operation has a UUID `request_key`. An identical retry returns the original movement; reuse with different input/actor fails. Posted history has no API/Admin edit/delete. Adjustments correct inventory and can link to an earlier movement; they do not cancel sales revenue. Full sales returns remain a later extension.

## 2. Move to PostgreSQL

```sh
uv add "psycopg[binary]"
```

### Create a local PostgreSQL container

Start Docker Desktop (or Docker Engine with the Compose plugin), then check `docker version` and `docker compose version`. Keep Django running in your Python environment for Phases 3–7; only the database runs in Docker. Create `.env.database.example`:

```dotenv
POSTGRES_DB=inventory
POSTGRES_USER=inventory_app
POSTGRES_PASSWORD=REPLACE_WITH_A_LOCAL_DATABASE_PASSWORD
```

Copy this to `.env.database`, choose a local password, and merge these entries into `.gitignore`. Commit only the example:

```gitignore
.env.database
!.env.database.example
```

Create `compose.database.yml`:

```yaml
services:
  db:
    image: postgres:17
    environment:
      POSTGRES_DB: ${POSTGRES_DB:?required}
      POSTGRES_USER: ${POSTGRES_USER:?required}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:?required}
    ports:
      - "127.0.0.1:55432:5432"
    volumes:
      - local_postgres_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U $$POSTGRES_USER -d $$POSTGRES_DB"]
      interval: 5s
      timeout: 5s
      retries: 12
volumes:
  local_postgres_data:
```

From the project root, run:

```sh
docker compose --env-file .env.database -f compose.database.yml up -d --wait db
docker compose --env-file .env.database -f compose.database.yml ps
docker compose --env-file .env.database -f compose.database.yml exec db psql -U inventory_app -d inventory -c "SELECT current_database(), current_user;"
```

Expect a healthy database and `inventory | inventory_app`. The image creates the database and role on its first start, so skip the manual SQL below when using Docker. Its initialization role is a superuser and can create Django test databases; use it only for local learning. Port **55432** is the host port; PostgreSQL listens on **5432** inside Docker. If 55432 is already occupied (including by this repository's validation demo), choose another free host port and use that same value in `POSTGRES_PORT`.

`docker compose --env-file .env.database -f compose.database.yml stop` stops the database; `up -d --wait db` starts it again with the same data. `down` removes containers but keeps the named volume. Do not add `--volumes` unless you intend to erase the local database. Changing the password in the env file does not change credentials in an initialized volume.

### Alternative: an installed PostgreSQL server

If you already run PostgreSQL directly, use its port (usually 5432). In `psql`, connected as your local database administrator, run once:

```sql
CREATE ROLE inventory_app LOGIN;
\password inventory_app
CREATE DATABASE inventory OWNER inventory_app;
ALTER ROLE inventory_app CREATEDB;
```

`\password` prompts for a password. `CREATEDB` enables Django's local test database; Phase 8 separates the production role.

Add `import os` to `config/settings.py`; replace `DATABASES` and add currency:

```python
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ["POSTGRES_DB"],
        "USER": os.environ["POSTGRES_USER"],
        "PASSWORD": os.environ["POSTGRES_PASSWORD"],
        "HOST": os.environ.get("POSTGRES_HOST", "127.0.0.1"),
        "PORT": os.environ.get("POSTGRES_PORT", "5432"),
    }
}
INVENTORY_CURRENCY = "IDR"
```

Set variables in every terminal running Django. PowerShell:

```powershell
$env:POSTGRES_DB = "inventory"
$env:POSTGRES_USER = "inventory_app"
$env:POSTGRES_PASSWORD = Read-Host "Local database password"
$env:POSTGRES_HOST = "127.0.0.1"
$env:POSTGRES_PORT = "55432"
```

Bash/Zsh:

```sh
export POSTGRES_DB=inventory POSTGRES_USER=inventory_app POSTGRES_HOST=127.0.0.1
export POSTGRES_PORT=55432
read -rs POSTGRES_PASSWORD
export POSTGRES_PASSWORD
```

Django does not automatically load `.env`; these are terminal session variables. Enter the same password as `.env.database`. For an installed server, replace 55432 with its port. Compose's `--env-file` configures its containers, not your Django terminal. Never commit passwords.

### Transfer existing SQLite data

Before changing settings, stop writes, copy `db.sqlite3` to a backup, and export with the old SQLite configuration:

```sh
uv run python manage.py dumpdata --natural-foreign --natural-primary --exclude contenttypes --exclude auth.permission --exclude sessions --indent 2 --output sqlite-data.json
```

Ignore `sqlite-data.json` in Git: it contains password hashes. After switching settings, **before adding the models in step 3**, run:

```sh
uv run python manage.py migrate
uv run python manage.py loaddata sqlite-data.json
uv run python manage.py shell -c "from django.core.management import call_command; output = open('reset-sequences.sql', 'w', encoding='utf-8'); call_command('sqlsequencereset', 'auth', 'inventory', stdout=output, no_color=True); output.close()"
psql -h 127.0.0.1 -p 55432 -U inventory_app -d inventory -f reset-sequences.sql
```

If you use Docker without host PostgreSQL client tools, replace the last `psql` command with:

```sh
docker compose --env-file .env.database -f compose.database.yml cp reset-sequences.sql db:/tmp/reset-sequences.sql
docker compose --env-file .env.database -f compose.database.yml exec db psql -U inventory_app -d inventory -f /tmp/reset-sequences.sql
```

Compare user/category/product counts, relationships, prices, stock, and Admin login against the backup. Keep the backup until verified. An empty database needs only `migrate` and `createsuperuser`; skip export/import. Run Phase 2's six tests against PostgreSQL before continuing:

```sh
uv run python manage.py check
uv run python manage.py test inventory
```

Expected: Django reports no issues and the six Phase 2 tests pass. Keep this database container and terminal connection variables for Phases 4–7. Phase 8 adds the application and Caddy containers and explains the transition to a separate rehearsal database.

## 3. Extend the models and migrate

Add to `inventory/models.py` imports:

```python
from django.conf import settings
```

Inside `Product`, add the following once before its `class Meta`, with four spaces of indentation. Keep the existing `Meta` and `__str__` methods:

```python
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    average_unit_cost = models.DecimalField(max_digits=24, decimal_places=6, default=0)
    inventory_value = models.DecimalField(max_digits=24, decimal_places=6, default=0)

    def save(self, *args, **kwargs):
        # An ordinary metadata save must not overwrite balances read before another posting.
        # The posting service supplies explicit update_fields for its balance writes.
        if not self._state.adding and kwargs.get("update_fields") is None:
            balances = {"stock_quantity", "average_unit_cost", "inventory_value"}
            kwargs["update_fields"] = [
                field.name for field in self._meta.concrete_fields
                if not field.primary_key and field.name not in balances
            ]
        return super().save(*args, **kwargs)
```

This override keeps API, form, and Admin metadata saves from writing stale stock/cost columns. New products still use defaults; only the shared posting service supplies explicit balance `update_fields`. A trusted ORM caller can still bypass this convention.

Append the following at the end of `inventory/models.py`, **outside `Product`**, after its existing `__str__` method. `class StockTransaction` must start at column 1, aligned with `class Product` and `class Category`; its fields are indented four spaces. Nesting it inside `Product` causes `NameError: name 'Product' is not defined` because Python has not finished defining `Product` yet:

```python
class StockTransaction(models.Model):
    class Type(models.TextChoices):
        PROCUREMENT = "PROCUREMENT", "Procurement"
        SALE = "SALE", "Sale"
        OPENING_BALANCE = "OPENING_BALANCE", "Opening balance"
        ADJUSTMENT_IN = "ADJUSTMENT_IN", "Adjustment in"
        ADJUSTMENT_OUT = "ADJUSTMENT_OUT", "Adjustment out"

    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="movements")
    transaction_type = models.CharField(max_length=20, choices=Type.choices)
    quantity = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    unit_cost = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    selling_price = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    value_change = models.DecimalField(max_digits=24, decimal_places=6)
    cogs = models.DecimalField(max_digits=24, decimal_places=6, default=0)
    revenue = models.DecimalField(max_digits=24, decimal_places=6, default=0)
    gross_profit = models.DecimalField(max_digits=24, decimal_places=6, default=0)
    reference = models.CharField(max_length=100, blank=True)
    notes = models.TextField(blank=True)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)
    request_key = models.UUIDField(unique=True)
    request_data = models.JSONField(editable=False)
    corrects = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.PROTECT, related_name="corrections"
    )

    class Meta:
        ordering = ["-created_at", "-id"]
        constraints = [
            models.CheckConstraint(condition=models.Q(quantity__gt=0), name="movement_quantity_positive"),
        ]
```

`PROTECT` preserves referenced products, actors, and correction targets. The service owns business checks. Trusted shell/SQL writes can bypass it; never use raw balance updates as a workflow.

```sh
uv run python manage.py makemigrations inventory
uv run python manage.py migrate
```

Commit the generated migration. Existing quantities survive with initially zero cost. Reconcile nonzero stock in step 5 before accepting movements.

## 4. Create the atomic posting service

Create `inventory/services.py`:

```python
from decimal import Decimal, ROUND_HALF_UP
from uuid import UUID

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction

from .models import Product, StockTransaction

T = StockTransaction.Type
INBOUND = {T.PROCUREMENT, T.OPENING_BALANCE, T.ADJUSTMENT_IN}
ADJUSTMENTS = {T.ADJUSTMENT_IN, T.ADJUSTMENT_OUT}
SIX = Decimal("0.000001")


def require_operation(actor, kind):
    # Phase 4 replaces this body with capability checks.
    if not actor.is_authenticated or not actor.is_active or not actor.is_staff:
        raise PermissionDenied("An active staff account is required.")


def money(value):
    try:
        amount = Decimal(str(value))
        if not amount.is_finite() or amount < 0 or amount >= Decimal("10000000000"):
            raise ValueError
        if amount != amount.quantize(Decimal("0.01")):
            raise ValueError
        return amount.quantize(Decimal("0.01"))
    except (ValueError, ArithmeticError):
        raise ValidationError("Prices must be nonnegative with at most two decimal places.")


def post_stock(*, actor, product_id, transaction_type, quantity, request_key,
               unit_cost=None, selling_price=None, reference="", notes="",
               corrects_id=None, reconcile_existing=False):
    require_operation(actor, transaction_type)
    if transaction_type not in T.values:
        raise ValidationError("Unknown transaction type.")
    if type(quantity) is not int or not 1 <= quantity <= 2147483647:
        raise ValidationError("Quantity must be a positive whole number.")
    try:
        request_key = UUID(str(request_key))
    except (ValueError, TypeError, AttributeError):
        raise ValidationError("A UUID request key is required.")
    if len(reference) > 100:
        raise ValidationError("Reference is limited to 100 characters.")
    if transaction_type in ADJUSTMENTS and not notes.strip():
        raise ValidationError("Adjustments require a reason in notes.")
    if transaction_type in INBOUND:
        if unit_cost is None or selling_price is not None:
            raise ValidationError("Receipts require unit_cost and no selling_price.")
        unit_cost = money(unit_cost)
    elif unit_cost is not None:
        raise ValidationError("Withdrawals do not accept unit_cost.")
    if transaction_type == T.SALE:
        if selling_price is None:
            raise ValidationError("Sales require selling_price.")
        selling_price = money(selling_price)
    elif selling_price is not None:
        raise ValidationError("Only sales accept selling_price.")
    if reconcile_existing and transaction_type != T.OPENING_BALANCE:
        raise ValidationError("Only opening balances can reconcile existing stock.")
    payload = {
        "product_id": int(product_id), "transaction_type": str(transaction_type),
        "quantity": quantity, "unit_cost": None if unit_cost is None else str(unit_cost),
        "selling_price": None if selling_price is None else str(selling_price),
        "reference": reference, "notes": notes, "corrects_id": corrects_id,
        "reconcile_existing": reconcile_existing,
    }

    def replay(existing):
        if existing.actor_id != actor.pk or existing.request_data != payload:
            raise ValidationError("Request key already used with different input or actor.")
        return existing, False

    try:
        with transaction.atomic():
            product = Product.objects.select_for_update().get(pk=product_id)
            existing = StockTransaction.objects.filter(request_key=request_key).first()
            if existing:
                return replay(existing)
            if not product.is_active:
                raise ValidationError("This product is inactive.")
            has_history = product.movements.exists()
            if transaction_type == T.OPENING_BALANCE:
                if has_history or (product.stock_quantity and not reconcile_existing):
                    raise ValidationError("Opening balance must be first; reconcile existing stock.")
                if reconcile_existing and quantity != product.stock_quantity:
                    raise ValidationError("Opening quantity must equal existing stock.")
            elif product.stock_quantity and not has_history:
                raise ValidationError("Reconcile existing opening stock first.")
            if corrects_id is not None:
                if transaction_type not in ADJUSTMENTS:
                    raise ValidationError("Only adjustments can link a correction.")
                if not product.movements.filter(pk=corrects_id).exists():
                    raise ValidationError("Correction target must belong to this product.")
            old_quantity, old_value = product.stock_quantity, product.inventory_value
            cogs = revenue = Decimal("0")
            if transaction_type in INBOUND:
                delta = (quantity * unit_cost).quantize(SIX, rounding=ROUND_HALF_UP)
                new_quantity = quantity if reconcile_existing else old_quantity + quantity
                new_value = delta if reconcile_existing else old_value + delta
            else:
                if quantity > old_quantity:
                    raise ValidationError("Insufficient stock.")
                consumed = old_value if quantity == old_quantity else (
                    old_value * quantity / old_quantity
                ).quantize(SIX, rounding=ROUND_HALF_UP)
                delta = -consumed
                new_quantity, new_value = old_quantity - quantity, old_value - consumed
                if transaction_type == T.SALE:
                    cogs, revenue = consumed, quantity * selling_price
            if new_quantity > 2147483647 or new_value >= Decimal("1000000000000000000"):
                raise ValidationError("Balance exceeds storage limits.")
            product.stock_quantity, product.inventory_value = new_quantity, new_value
            product.average_unit_cost = (
                (new_value / new_quantity).quantize(SIX, rounding=ROUND_HALF_UP)
                if new_quantity else Decimal("0")
            )
            movement = StockTransaction.objects.create(
                product=product, actor=actor, transaction_type=transaction_type,
                quantity=quantity, unit_cost=unit_cost, selling_price=selling_price,
                value_change=delta, cogs=cogs, revenue=revenue, gross_profit=revenue-cogs,
                reference=reference, notes=notes, corrects_id=corrects_id,
                request_key=request_key, request_data=payload,
            )
            product.save(update_fields=["stock_quantity", "inventory_value", "average_unit_cost", "updated_at"])
            return movement, True
    except IntegrityError:
        # Same globally unique key racing on different product locks.
        existing = StockTransaction.objects.filter(request_key=request_key).first()
        if existing:
            return replay(existing)
        raise
```

The lock serializes writes to the same balance; `atomic()` rolls back both writes on failure. See [Django row locking](https://docs.djangoproject.com/en/5.2/ref/models/querysets/#select-for-update).

## 5. Record existing opening stock once

Create empty `inventory/management/__init__.py` and `inventory/management/commands/__init__.py`. Create `inventory/management/commands/reconcile_opening.py`:

```python
from uuid import NAMESPACE_URL, uuid5

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError, PermissionDenied
from django.core.management.base import BaseCommand, CommandError

from inventory.models import Product, StockTransaction
from inventory.services import post_stock


class Command(BaseCommand):
    help = "Record existing stock without adding it twice."

    def add_arguments(self, parser):
        parser.add_argument("product_id", type=int)
        parser.add_argument("unit_cost")
        parser.add_argument("--actor", required=True)

    def handle(self, *args, **options):
        try:
            actor = get_user_model().objects.get(username=options["actor"])
            product = Product.objects.get(pk=options["product_id"])
            key = uuid5(NAMESPACE_URL, f"inventory-opening:{product.pk}")
            existing = StockTransaction.objects.filter(request_key=key).first()
            quantity = existing.quantity if existing else product.stock_quantity
            if not quantity:
                raise CommandError("Zero stock needs no opening record.")
            movement, created = post_stock(
                actor=actor, product_id=product.pk, transaction_type="OPENING_BALANCE",
                quantity=quantity, unit_cost=options["unit_cost"], request_key=key,
                reference="Phase 3 cutover", reconcile_existing=True,
            )
        except (ValidationError, PermissionDenied, Product.DoesNotExist,
                get_user_model().DoesNotExist) as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(f"Movement {movement.pk}; created={created}")
```

### Choose or create the user who records opening balances

`--actor` is a **Django username**, not the PostgreSQL login `inventory_app`. This phase requires an existing active staff user (or superuser). SQLite imports in step 2 transfer existing users; an empty PostgreSQL database has none until you create them. Keep the Phase 3 PostgreSQL environment variables set so these commands use the same database as reconciliation.

Use [Phase 2's user-list commands](02_rest_api.md#list-existing-users) to see all accounts and active staff candidates in the PostgreSQL database. If you have the `inventory_staff` account from Phase 2's account setup, confirm it exists in PostgreSQL:

```sh
uv run python manage.py shell
```

Paste the following into the Django shell:

```py
from django.contrib.auth import get_user_model
User = get_user_model()
list(User.objects.filter(username="inventory_staff").values("username", "is_active", "is_staff", "is_superuser"))
exit()
```

Expect `is_active=True` and `is_staff=True`. An empty list means that account is absent from this database: follow Phase 2's staff-account creation steps now, or create a new local administrator instead:

```sh
uv run python manage.py createsuperuser --username opening_admin
```

Enter the email/password when prompted. Run this only if `opening_admin` does not already exist. You may use any existing active staff/superuser username; do not create another account merely to repeat reconciliation. If using the new administrator, replace `inventory_staff` below with `opening_admin`. Phase 4 introduces more specific role permissions.

### Record and verify the opening movements

`reconcile_opening` does **not create a product**. It looks up an existing product by ID and records the cost/history for its existing nonzero quantity, without adding that quantity again. If you imported Phase 1's sample `KB-001`, it should already have 10 units. Phase 2 API-created products start with zero stock, and its cleanup examples delete their demo records.

First inspect the products in the PostgreSQL database:

```sh
uv run python manage.py shell
```

```py
from inventory.models import Product
print(list(Product.objects.order_by("id").values("id", "sku", "name", "stock_quantity")))
print(list(Product.objects.filter(stock_quantity__gt=0, movements__isnull=True).values("id", "sku", "stock_quantity")))
exit()
```

The second query lists products with existing stock and no movements yet. Use one of their actual IDs below; **do not assume ID 1 exists**. An empty list means there is no existing stock to reconcile. For a fresh application, skip opening reconciliation and create zero-stock products, then receive goods through the procurement workflow in step 8.

#### Optional: create a local opening-stock example

If your local learning database is empty and you want to practice this cutover step, simulate a product carried over from the earlier phases. This is a one-time learning fixture, not the normal way to receive goods. In `uv run python manage.py shell`, paste:

```py
from decimal import Decimal
from inventory.models import Category, Product
category, _ = Category.objects.get_or_create(name="Opening Demo")
product, created = Product.objects.get_or_create(
    sku="OPENING-DEMO-001",
    defaults={
        "name": "Opening Demo Keyboard",
        "category": category,
        "price": Decimal("40.00"),
        "stock_quantity": 10,
    },
)
print(product.pk, product.sku, product.stock_quantity, created)
exit()
```

On first creation, expect 10 units and `created=True`; note the printed ID. A repeat reuses the product without resetting its stock. For this fictional example, use an acquisition cost of `20.00` below: after reconciliation, quantity stays 10 and inventory value becomes `200.000000`. For real products, use their actual acquisition costs. After opening reconciliation, all further quantity changes must go through the posting service.

Obtain actual acquisition costs for every nonzero product; do not infer them from selling prices. During the write freeze, use the actual product ID, cost, and confirmed username:

```sh
uv run python manage.py reconcile_opening 1 20.00 --actor inventory_staff
```

Here `1` is only an example: replace it with the ID you just inspected or created. Expect `Movement <id>; created=True` on the first successful run.

Repeat the command: expect `created=False`, with unchanged quantity. Reusing the key with a different cost fails. Reconcile every nonzero balance, verify stock/value, then end the freeze. Zero-stock products start with procurement.

## 6. Add API inputs, outputs, and routes

Import `StockTransaction` in `inventory/serializers.py`. Extend `ProductSerializer.Meta.fields` with `description`, `is_active`, `average_unit_cost`, `inventory_value`; extend `read_only_fields` with the two cost balances. Append:

```python
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
```

Append to `inventory/views.py`, merging imports:

```python
from django.conf import settings
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models import Sum
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import StockTransaction
from .serializers import StockOperationSerializer, StockTransactionSerializer
from .services import post_stock


class StockTransactionViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = StockTransaction.objects.select_related("product", "actor").all()
    serializer_class = StockTransactionSerializer

    def create(self, request):
        incoming = StockOperationSerializer(data=request.data)
        incoming.is_valid(raise_exception=True)
        data = dict(incoming.validated_data)
        data["product_id"] = data.pop("product").pk
        try:
            movement, created = post_stock(actor=request.user, **data)
        except DjangoValidationError as exc:
            raise ValidationError(exc.messages) from exc
        return Response(self.get_serializer(movement).data, status=201 if created else 200)


class ValuationView(APIView):
    def get(self, request):
        totals = StockTransaction.objects.filter(transaction_type="SALE").aggregate(
            revenue=Sum("revenue"), cogs=Sum("cogs"), gross_profit=Sum("gross_profit")
        )
        totals["inventory_value"] = Product.objects.aggregate(value=Sum("inventory_value"))["value"]
        return Response({"currency": settings.INVENTORY_CURRENCY,
                         **{key: format(value or 0, ".6f") for key, value in totals.items()}})
```

`ReadOnlyModelViewSet` supplies list/retrieve; the explicit `create` adds POST. There is no movement update/delete. Add inside `ProductViewSet`:

```python
    def perform_destroy(self, instance):
        try:
            instance.delete()
        except ProtectedError as exc:
            error = APIException("Products with movements must be deactivated.")
            error.status_code = 409
            raise error from exc
```

`path` is Django's URL-routing function. It maps a URL pattern to a view and gives the route a name. Import it from `django.urls`, not from your application's `.views` module.

In `inventory/urls.py`, update the imports to:

```py
from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import CategoryViewSet, ProductViewSet, StockTransactionViewSet, ValuationView
```

Keep the existing category/product router registrations. Before `urlpatterns`, add the stock-transaction registration; replace the `urlpatterns` assignment:

```python
router.register("stock_transactions", StockTransactionViewSet, basename="stock-transaction")
urlpatterns = [path("valuation/", ValuationView.as_view(), name="valuation")] + router.urls
```

Here `path("valuation/", ValuationView.as_view(), name="valuation")` connects `/api/valuation/` to the class-based `ValuationView`; `as_view()` turns that class into a callable Django can invoke. The `api/` prefix comes from the project URL configuration. `name="valuation"` lets code look up this route with `reverse("valuation")`. The DRF router generates the category, product, and stock-transaction routes separately.

## 7. Make Admin balances/history read-only

Import `StockTransaction` in `inventory/admin.py`. Replace `ProductAdmin.readonly_fields`:

```python
    readonly_fields = ("stock_quantity", "average_unit_cost", "inventory_value", "created_at", "updated_at")
```

Append:

```python
@admin.register(StockTransaction)
class StockTransactionAdmin(admin.ModelAdmin):
    list_display = ("id", "product", "transaction_type", "quantity", "actor", "created_at")
    readonly_fields = tuple(field.name for field in StockTransaction._meta.fields)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
```

## 8. Try procurement and sales

### Terminal A: check configuration, schema, and database access

Open a terminal in the project root containing `manage.py`. Use the same Python environment and PostgreSQL connection variables from step 2. If this is a new terminal, set those variables again; Django does not load `.env.database` automatically. Start the Phase 3 database if it is stopped:

```sh
docker compose --env-file .env.database -f compose.database.yml up -d --wait db
uv run python manage.py check
uv run python manage.py makemigrations --check --dry-run
uv run python manage.py migrate --check
uv run python manage.py shell -c "from django.db import connection; cursor = connection.cursor(); cursor.execute('SELECT current_database(), current_user'); print(cursor.fetchone()); cursor.close()"
```

Skip the Docker command if you use an installed PostgreSQL server. Run these commands one at a time and resolve any failure before starting the server:

| Command | What it verifies | Expected result |
| --- | --- | --- |
| `check` | Django can load models, settings, Admin, and URL configuration | `System check identified no issues` |
| `makemigrations --check --dry-run` | Your model changes have matching migration files | `No changes detected` |
| `migrate --check` | The configured database has no unapplied migrations | Successful exit, usually with no output |
| SQL query through Django | Django can connect to the intended PostgreSQL database | `('inventory', 'inventory_app')`, or your configured names |

`check` alone does not prove database connectivity or that migrations have been applied. If model changes are detected, review and run `uv run python manage.py makemigrations inventory`; if migrations are pending, run `uv run python manage.py migrate`. Then repeat the affected check. Neither check command applies migrations for you.

Common failures at this point:

- `KeyError: 'POSTGRES_DB'`: set the Phase 3 environment variables in this terminal.
- Connection refused: check that PostgreSQL is running and `POSTGRES_HOST`/`POSTGRES_PORT` match the Docker host mapping (55432 by default).
- Password authentication failed: use the credentials that initialized the database; editing `.env.database` does not update an existing database role's password.
- Import/URL errors: verify the Step 6 imports, including `from django.urls import path`, and that the view classes exist in `inventory/views.py`.

### Terminal A: start the development server

After the checks pass, run:

```sh
uv run python manage.py runserver 127.0.0.1:8000
```

Expect `Starting development server at http://127.0.0.1:8000/`. Leave this terminal running; it displays request logs and errors as you try the API. `Ctrl+C` stops the server. This is the local development server; the production container and HTTPS proxy come in Phase 8.

Open [the browsable API](http://127.0.0.1:8000/api/) in your browser. Sign in using **Log in** with your active staff account, or use your existing Admin session. You should see the category, product, and stock-transaction routes. Visit [valuation](http://127.0.0.1:8000/api/valuation/) separately; it is a manually registered route and may not appear in the router's API root. An unauthenticated request can return `401`; that is an access check, not evidence the server failed to start.

If port 8000 is occupied, run `uv run python manage.py runserver 127.0.0.1:8001` instead. Use port 8001 in all browser links and in the request helper's `base_url` below.

### Terminal B: prepare authenticated requests

Open a second terminal while Terminal A keeps serving requests. From the project root, start a plain Python prompt:

```sh
uv run python
```

This client uses HTTP rather than the ORM, so it does not need PostgreSQL variables. Paste the following helper (the same approach as Phase 2), then enter the active staff username and password when prompted. If your terminal cannot accept a multiline paste, enter the imports and login lines first, then paste the function definition and finish it with a blank line.

```py
import base64
import getpass
import json
from urllib.error import HTTPError
from urllib.request import Request, urlopen

base_url = "http://127.0.0.1:8000/api/"
username = input("Staff username: ")
password = getpass.getpass("Password: ")
credentials = base64.b64encode(f"{username}:{password}".encode()).decode()

def api_request(method, path, payload=None):
    body = None if payload is None else json.dumps(payload).encode()
    request = Request(
        base_url + path,
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
            result = json.loads(raw) if raw else None
            print(response.status)
            print(json.dumps(result, indent=2))
            return result
    except HTTPError as exc:
        print(exc.code, exc.read().decode())
        return None

```

First confirm authenticated access:

```py
api_request("GET", "products/")
```

Expect `200` and a product list, which may be empty. A `401` means credentials are missing/invalid or the user is inactive; a `403` means the authenticated account lacks staff access at this phase. Connection refused means the server is stopped or the helper uses the wrong port. Resolve that before creating demo records.

### Terminal B: receive goods and record a sale

Run the following at the same Python prompt, not in PowerShell/Bash or in a source file. Choose unused category names/SKUs if you previously ran this example. Execute each request separately and inspect its response; if category/product creation returns `None` after an error, fix it before using its ID in the next request:

```python
from uuid import uuid4

category = api_request("POST", "categories/", {"name": "Phase 3 Demo"})
product = api_request("POST", "products/", {
    "sku": "P3-001", "name": "Valuation Demo", "category": category["id"], "price": "40.00"
})
receipt = {"product_id": product["id"], "transaction_type": "PROCUREMENT",
           "quantity": 10, "unit_cost": "20.00", "request_key": str(uuid4())}
api_request("POST", "stock_transactions/", receipt)  # 201
api_request("POST", "stock_transactions/", receipt)  # 200, same movement
api_request("POST", "stock_transactions/", {
    **receipt, "unit_cost": "30.00", "request_key": str(uuid4())
})
api_request("POST", "stock_transactions/", {
    "product_id": product["id"], "transaction_type": "SALE", "quantity": 4,
    "selling_price": "40.00", "request_key": str(uuid4())
})
api_request("GET", f"products/{product['id']}/")
api_request("GET", "valuation/")
```

Expect 16 units, average `25.000000`, value `400.000000`; sale revenue 160, COGS 100, profit 60. Global valuation includes other inventory. Selling 17 fails with 400 and no write. DELETE this product gives 409; deactivate using PATCH `is_active: false`.

The two procurements receive 10 units each: first at 20, then at 30. The retry of the first request adds no stock. Before the sale, there are 20 units worth 500; selling four consumes 100 of cost and leaves 16 units worth 400. Terminal A should show the corresponding HTTP status codes, including `201` for a new movement and `200` for an identical retry.

Finish Terminal B with `exit()`. Keep Terminal A running to inspect the API in your browser, or stop it with `Ctrl+C` before continuing to the tests.

## 9. Add service and concurrency tests

Keep Phase 2's tests; append to `inventory/tests.py`, merging imports:

```python
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import patch
from uuid import uuid4

from django.core.exceptions import ValidationError
from django.db import close_old_connections, connection
from django.test import TransactionTestCase

from .models import StockTransaction
from .services import post_stock


class StockPostingTests(TransactionTestCase):
    def setUp(self):
        self.actor = get_user_model().objects.create_user(username="poster", is_staff=True)
        self.product = Product.objects.create(
            sku="POST-1", name="Posting", category=Category.objects.create(name="Posting"), price="40.00"
        )

    def post(self, kind, quantity, **extra):
        return post_stock(actor=self.actor, product_id=self.product.pk,
                          transaction_type=kind, quantity=quantity, request_key=uuid4(), **extra)

    def test_weighted_average_and_final_withdrawal(self):
        self.post("PROCUREMENT", 10, unit_cost="20.00")
        self.post("PROCUREMENT", 10, unit_cost="30.00")
        sale, _ = self.post("SALE", 4, selling_price="40.00")
        self.assertEqual(sale.cogs, Decimal("100"))
        self.assertEqual(sale.gross_profit, Decimal("60"))
        self.product.refresh_from_db()
        self.assertEqual(self.product.inventory_value, Decimal("400"))
        self.post("SALE", 16, selling_price="40.00")
        self.product.refresh_from_db()
        self.assertEqual((self.product.stock_quantity, self.product.inventory_value), (0, Decimal("0")))

    def test_duplicate_and_changed_payload(self):
        data = dict(actor=self.actor, product_id=self.product.pk, transaction_type="PROCUREMENT",
                    quantity=3, unit_cost="1.00", request_key=uuid4())
        first, _ = post_stock(**data)
        second, created = post_stock(**data)
        self.assertEqual(first.pk, second.pk)
        self.assertFalse(created)
        with self.assertRaises(ValidationError):
            post_stock(**{**data, "quantity": 4})
        self.assertEqual(StockTransaction.objects.count(), 1)

    def test_balance_failure_rolls_back_movement(self):
        with patch.object(Product, "save", side_effect=RuntimeError("write failed")):
            with self.assertRaises(RuntimeError):
                self.post("PROCUREMENT", 3, unit_cost="1.00")
        self.assertFalse(StockTransaction.objects.exists())
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, 0)

    def test_stale_catalog_save_cannot_overwrite_a_posting(self):
        stale_product = Product.objects.get(pk=self.product.pk)
        self.post("PROCUREMENT", 3, unit_cost="1.00")
        stale_product.name = "Renamed"
        stale_product.save()
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, 3)
        self.assertEqual(self.product.inventory_value, Decimal("3"))

    def test_concurrent_sales_cannot_oversell(self):
        if connection.vendor != "postgresql":
            self.skipTest("Row-lock behavior requires PostgreSQL")
        self.post("PROCUREMENT", 1, unit_cost="1.00")
        barrier = Barrier(2)

        def sell():
            close_old_connections()
            try:
                actor = get_user_model().objects.get(pk=self.actor.pk)
                barrier.wait(timeout=10)
                post_stock(actor=actor, product_id=self.product.pk, transaction_type="SALE",
                           quantity=1, selling_price="2.00", request_key=uuid4())
                return "posted"
            except ValidationError:
                return "rejected"
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: sell(), range(2)))
        self.assertCountEqual(results, ["posted", "rejected"])
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, 0)
```

`TransactionTestCase` allows real commits/connections so this tests PostgreSQL locks. See [Django transaction tests](https://docs.djangoproject.com/en/5.2/topics/testing/tools/#transactiontestcase).

```sh
uv run python manage.py check
uv run python manage.py makemigrations --check --dry-run
uv run python manage.py test inventory
```

Also verify opening reconciliation twice, required adjustment reasons, inactive-product rejection, forbidden history edits, and read-only balance PATCH/Admin fields before continuing.

## 10. Review the changed files

```text
config/settings.py                       PostgreSQL + currency
compose.database.yml + .env.database.example + .gitignore
inventory/models.py + migrations/        valuation fields + movement model
inventory/services.py                    atomic posting
inventory/management/commands/reconcile_opening.py
inventory/serializers.py                  operation inputs + snapshots
inventory/views.py + inventory/urls.py    stock + valuation endpoints
inventory/admin.py                       protected balances/history
inventory/tests.py                       valuation, retries, rollback, concurrency
pyproject.toml + uv.lock                  PostgreSQL driver
```

Commit code, generated migration, and lockfile after checks pass; exclude exports/credentials. Next: [Phase 4 — Roles and JWT](04_accounts_roles_jwt.md).
