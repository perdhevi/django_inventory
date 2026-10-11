# 01 — Getting started with Django inventory and uv

Build the foundation of a simple inventory application: categories, products, a database, and a usable Django admin. The REST API comes next.

This guide assumes you know basic Python and FastAPI; Spring comparisons are included where useful. It uses Python 3.12, Django 5.2, Django REST Framework (DRF) 3.16, and SQLite. These version ranges provide a consistent learning baseline rather than always selecting the newest major release.

## 1. Initialize the project

Install [uv](https://docs.astral.sh/uv/getting-started/installation/) if necessary, then confirm it is available:

```sh
uv --version
```

From the parent directory where you want your repository, run:

```sh
uv init --app --python 3.12 django_inventory
cd django_inventory
uv add "django>=5.2,<5.3" "djangorestframework>=3.16,<3.17"
```

These commands work in PowerShell, Bash, and Zsh. Run all subsequent terminal commands from `django_inventory`, the directory that will contain `manage.py`.

`uv` records dependencies in `pyproject.toml`, resolves exact versions in `uv.lock`, and manages the local `.venv`. `uv run` executes commands using that environment, so manual activation and separate `pip install` commands are unnecessary. See [uv's project workflow](https://docs.astral.sh/uv/guides/projects/).

`uv init` may create a sample `main.py`. Delete that sample file using your editor; Django will use `manage.py` as its command entry point. Keep `README.md`, `pyproject.toml`, `.python-version`, and `uv.lock`.

Use underscores for Python package/module identifiers and `snake_case` for fields and functions. Classes use `PascalCase`, such as `StockTransaction`. Repository folder names can use hyphens, but this guide uses `django_inventory` for consistency. A distribution name normalized to `django-inventory` in package metadata is fine; it is not a Python import identifier.

## 2. Create the Django project and app

```sh
uv run django-admin startproject config .
uv run python manage.py startapp inventory
```

The final `.` places `manage.py` in the current directory, avoiding another nested repository folder.

- **Project (`config`)**: application-wide settings, URL routing, and server entry points.
- **App (`inventory`)**: a feature/domain module containing models, views, and migrations. One Django project can contain several apps.

| Django | FastAPI comparison | Spring comparison |
| --- | --- | --- |
| `config/settings.py` | Central application settings | `application.yml` plus configuration |
| `config/urls.py` | App/router registration | Request mapping configuration |
| `inventory` app | A feature package | A domain package/module |
| `models.Model` | SQLAlchemy/SQLModel persistence model | JPA entity |
| Model manager and QuerySet | ORM queries/session operations | Repository queries |
| `manage.py` | Project management command entry point | Some application/build tooling responsibilities |

These are conceptual comparisons, not exact equivalents. Django includes an ORM, migrations, authentication, and an admin interface; FastAPI typically combines separate libraries for these jobs.

## 3. Register the apps

In `config/settings.py`, replace the `INSTALLED_APPS` list with:

```python
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "inventory.apps.InventoryConfig",
]
```

`InventoryConfig` is generated in `inventory/apps.py`. Keep the default SQLite `DATABASES` setting for this tutorial; no separate database server is needed. Installing DRF makes its Python code available; registering `rest_framework` enables its Django integration. Neither step creates API endpoints yet.

## 4. Define Category and Product

Replace `inventory/models.py` with:

```python
from decimal import Decimal

from django.core.validators import MinValueValidator
from django.db import models


class Category(models.Model):
    name = models.CharField(max_length=100, unique=True)

    class Meta:
        ordering = ["name"]
        verbose_name_plural = "categories"

    def __str__(self):
        return self.name


class Product(models.Model):
    sku = models.CharField(max_length=50, unique=True)
    name = models.CharField(max_length=200)
    category = models.ForeignKey(
        Category,
        on_delete=models.PROTECT,
        related_name="products",
    )
    price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.00"))],
    )
    stock_quantity = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name", "id"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(price__gte=0),
                name="inventory_product_price_nonnegative",
            ),
        ]

    def __str__(self):
        return f"{self.sku} — {self.name}"
```

Each product has one category. `PROTECT` prevents deleting a category referenced by products; `related_name` enables `category.products.all()`. Django adds an `id` primary key automatically.

Use `Decimal` for monetary values to avoid binary floating-point rounding. `max_digits=10` includes the two fractional digits. The price validator supports form/model validation, while the check constraint also enforces nonnegative prices in the database. `PositiveIntegerField` accepts zero, which is appropriate for out-of-stock products.

`stock_quantity` is a simple starting balance. Later, stock movements will be recorded explicitly rather than freely editing this field.

## 5. Create and apply migrations

```sh
uv run python manage.py makemigrations inventory
uv run python manage.py migrate
uv run python manage.py check
```

`makemigrations` generates `inventory/migrations/0001_initial.py` from the model definitions. `migrate` applies pending migrations, including Django's authentication/admin tables, to `db.sqlite3`. A successful `check` should report no issues.

After future schema changes, repeat `makemigrations` and `migrate`. Commit migration files with the model changes. This plays a similar role to Alembic in a FastAPI stack or Flyway/Liquibase in Spring, though Django generates migrations from its model definitions.

Optional inspection:

```sh
uv run python manage.py showmigrations
uv run python manage.py sqlmigrate inventory 0001
```

## 6. Explore the ORM in the Django shell

Open a shell with Django settings loaded:

```sh
uv run python manage.py shell
```

Paste this Python code into the shell. It uses `get_or_create` so repeating it does not duplicate the sample SKU/category:

```python
from decimal import Decimal
from inventory.models import Category, Product

category, _ = Category.objects.get_or_create(name="Accessories")
product, created = Product.objects.get_or_create(
    sku="KB-001",
    defaults={
        "name": "Mechanical Keyboard",
        "category": category,
        "price": Decimal("79.90"),
        "stock_quantity": 10,
    },
)

print(product.sku, product.stock_quantity)
print(list(Product.objects.values("sku", "name", "stock_quantity")))
print(list(category.products.all()))
print(list(Product.objects.filter(stock_quantity__lt=5)))
```

On a fresh database, the first print shows `KB-001 10`, and the low-stock query returns an empty list. `defaults` is used only when creating the product; it does not reset an existing record.

Retrieve and update the product:

```python
product = Product.objects.select_related("category").get(sku="KB-001")
print(product.category.name)
product.price = Decimal("74.90")
product.full_clean()
product.save()
```

`select_related` fetches the foreign-key category in the same query. `full_clean()` explicitly validates the model; ordinary `save()` does not automatically call it. The ORM uses model managers and QuerySets rather than requiring a separate repository class.

Exit the shell:

```python
exit()
```

## 7. Create a superuser

```sh
uv run python manage.py createsuperuser
```

Follow the username, email, and password prompts. Password characters are hidden while typing. This account can sign into Django's admin interface; creating it requires the authentication migrations from step 5.

### Update the superuser's email or password

You can change both later without recreating the account.

Once the server is running (step 9), sign in at `http://127.0.0.1:8000/admin/`, open **Users**, and select your username. Update **Email address** and click **Save**. To change the password, use the password-change link on the user form and follow its prompts.

You can also reset the password from the terminal, even if you cannot sign in:

```sh
uv run python manage.py changepassword your_username
```

Replace `your_username` with the username you created. Django prompts for the new password twice; typed characters are hidden. See the [changepassword command reference](https://docs.djangoproject.com/en/5.2/ref/django-admin/#changepassword).

To update the email through the Django shell:

```sh
uv run python manage.py shell
```

Paste the following Python code, replacing the example username and email with your own values:

```python
from django.contrib.auth import get_user_model

User = get_user_model()
user = User.objects.get(username="your_username")
user.email = "new_email@example.com"
user.save(update_fields=["email"])
exit()
```

With this tutorial's default Django user model, you still sign in using your **username**, even after changing your email. For more details, see [Django's authentication documentation](https://docs.djangoproject.com/en/5.2/topics/auth/default/#changing-passwords).

## 8. Register models in Django admin

For the simplest registration, replace `inventory/admin.py` with:

```python
from django.contrib import admin

from .models import Category, Product

admin.site.register(Category)
admin.site.register(Product)
```

This gives you generated create, edit, list, and delete screens.

To improve those screens, replace the entire file again with the following. Do not append this to the basic registration, because registering the same model twice raises `AlreadyRegistered`.

```python
from django.contrib import admin

from .models import Category, Product


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("id", "name")
    search_fields = ("name",)


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ("sku", "name", "category", "price", "stock_quantity")
    list_filter = ("category",)
    search_fields = ("sku", "name", "category__name")
    list_select_related = ("category",)
    readonly_fields = ("created_at", "updated_at")
```

The product list now shows useful columns, category filters, and search. `category__name` traverses the relationship for search; `list_select_related` avoids an extra category lookup for every displayed product. See the [admin reference](https://docs.djangoproject.com/en/5.2/ref/contrib/admin/) for these options.

## 9. Run the development server

```sh
uv run python manage.py runserver
```

Open [http://127.0.0.1:8000/admin/](http://127.0.0.1:8000/admin/) and sign in. You should see Categories and Products, including the shell sample. Create another category and product to try the forms, filters, and search.

The generated `config/urls.py` already includes the admin route:

```python
from django.contrib import admin
from django.urls import path

urlpatterns = [
    path("admin/", admin.site.urls),
]
```

There is no inventory API route yet. Stop the server with `Ctrl+C`. If port 8000 is occupied, use `uv run python manage.py runserver 8001` and visit the corresponding URL. This server and the generated settings are for local development; production deployment requires separate configuration.

## 10. Expected project structure

After the steps above and placing this guide in the repository:

```text
django_inventory/
├── .gitignore
├── .python-version
├── .venv/                       # local, ignored
├── README.md
├── pyproject.toml
├── uv.lock
├── manage.py
├── db.sqlite3                   # local, ignored
├── docs/
│   └── 01_getting_started.md
├── config/
│   ├── __init__.py
│   ├── settings.py
│   ├── urls.py
│   ├── asgi.py
│   └── wsgi.py
└── inventory/
    ├── __init__.py
    ├── admin.py
    ├── apps.py
    ├── models.py
    ├── tests.py
    ├── views.py
    └── migrations/
        ├── __init__.py
        └── 0001_initial.py
```

Generated `.git/` and `__pycache__/` directories are omitted from this diagram.

Ensure `.gitignore` includes the following (keep any existing entries):

```gitignore
.venv/
__pycache__/
*.py[cod]
db.sqlite3
db.sqlite3-journal
db.sqlite3-wal
db.sqlite3-shm
.env
```

Commit source files, documentation, `pyproject.toml`, `uv.lock`, `.python-version`, and migration files. The local database contains your sample data and superuser, so each reader creates their own database/account. Before publishing the source, move Django's generated `SECRET_KEY` into environment configuration and document how contributors supply it locally.

For a fresh clone of the completed repository, run these commands inside its root:

```sh
uv sync --locked
uv run python manage.py migrate
uv run python manage.py createsuperuser
uv run python manage.py runserver
```

Existing migration files are already committed, so a new contributor does not need to generate them just to start the app.

## 11. Next: build the REST API and track stock movements

| Next component | Purpose | Familiar comparison |
| --- | --- | --- |
| `inventory/serializers.py` | Validate incoming data and serialize models | Pydantic schemas; Spring request/response DTOs |
| `ModelViewSet` in `inventory/views.py` | Implement list/retrieve/create/update/delete actions | FastAPI handlers; Spring REST controllers |
| Router in `inventory/urls.py` | Generate routes for registered ViewSets | `APIRouter`; controller mappings |
| `StockTransaction` model | Record stock movement history | Domain entity plus business service |

Follow this sequence:

1. Add `CategorySerializer` and `ProductSerializer` using DRF `ModelSerializer`, with explicit fields and read-only IDs/timestamps. Keep stock balances read-only once movement tracking is introduced.
2. Add Category and Product `ModelViewSet` classes. Use `Product.objects.select_related("category")` for the product queryset.
3. Register the ViewSets with a `DefaultRouter` in `inventory/urls.py`; include those URLs under `path("api/", include("inventory.urls"))` in `config/urls.py`. The intended collection URLs are `/api/categories/` and `/api/products/`.
4. Configure authentication and permissions deliberately, then test successful requests and invalid payloads. The admin login does not automatically protect new API endpoints.
5. Add `StockTransaction` with a product relation, a signed quantity change, reason, timestamp, and optionally the acting user. Decide how to record opening balances for existing products.
6. Apply stock movements and update balances atomically in a service function. Reject zero movements and changes that would make stock negative; choose concurrency controls suited to the database, and test simultaneous withdrawals. For a PostgreSQL implementation, a transaction plus row locking is one option; SQLite does not provide equivalent `select_for_update` row locks.
7. Add a migration and tests for receipts, withdrawals, insufficient stock, and rollback. Keep movement history immutable or use explicit reversing movements for corrections.

At this point you have the persistence/admin foundation. The next tutorial can build on it without repeating environment setup.

## References

- [uv: creating projects](https://docs.astral.sh/uv/concepts/projects/init/)
- [Django: creating a project](https://docs.djangoproject.com/en/5.2/intro/tutorial01/)
- [Django: models, migrations, shell, and admin](https://docs.djangoproject.com/en/5.2/intro/tutorial02/)
- [DRF quickstart: serializers, ViewSets, and routers](https://www.django-rest-framework.org/tutorial/quickstart/)
