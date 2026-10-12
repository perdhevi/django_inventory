# Django Inventory

An inventory web application and REST API built as a learning project with **uv, Django, and Django REST Framework**. The documentation includes FastAPI and Spring Boot comparisons.

The base functional application will manage categories/products, procurement receipts, sales, stock history, and **moving weighted-average inventory valuation**. It will provide Django-rendered user pages, a JSON API, and Django Admin, sharing business rules and permissions.

## Start here

Follow [Phase 1 — Getting started](docs/01_getting_started.md). Continue through the numbered guides in order.

## Phases

| Phase | What it builds | Guide |
| --- | --- | --- |
| 1 | uv setup, Category/Product models, SQLite, ORM, default Django users/superuser, Admin | [Getting started](docs/01_getting_started.md) |
| 2 | Category/product REST CRUD, serializers, ViewSets, routers, staff-only Basic/session auth, API tests | [REST API](docs/02_rest_api.md) |
| 3 | PostgreSQL, procurement, sales, opening balances, adjustments, atomic stock movements, weighted-average valuation | [Stock and valuation](docs/03_stock_transactions_valuation.md) |
| 4 | Viewer, Sales, Procurement, Inventory manager, Administrator roles; data permissions; JWT | [Accounts and authorization](docs/04_accounts_roles_jwt.md) |
| 5 | Login/account pages, dashboard, catalog, procurement/sales forms, transaction history | [Web interface](docs/05_web_interface.md) |
| 6 | Low-stock indicators, filters, pagination, reports, CSV export, API documentation | [Reports and usability](docs/06_reports_usability.md) |
| 7 | Optional Google sign-in, safe account linking, existing role enforcement | [Google authentication](docs/07_google_authentication.md) |
| 8 | Production configuration, deployment, CI, monitoring, backup/restore | [Deployment](docs/08_deployment.md) |

Each guide follows the same learning flow: prerequisites and request flow, concrete file changes, commands/migrations, manual examples with expected results, tests, and a changed-file review. Apply them in order; later phases extend earlier code. Tutorial availability does not mean the feature is implemented or verified in this checkout.

The tutorials call the Django settings package `config`. This checkout uses `django_inventory`: substitute that name in settings/URL paths, settings-module values, and WSGI targets. Phase 3 explains this convention and begins the stock/valuation walkthrough.

[Actual tutorial build validation](docs/VALIDATION.md) records the PostgreSQL test results, HTTPS/container rehearsal, fixes found, backup/restore comparison, and repeatable local commands. The validated build is isolated from this checkout's application source.

## Stack and interfaces

| Area | Design |
| --- | --- |
| Python environment | uv; Python 3.12 tutorial baseline |
| Backend | Django 5.2 and DRF 3.16 tutorial baseline |
| Database | SQLite in Phase 1/2; PostgreSQL in Phase 3 |
| User pages | Django templates/forms with session authentication |
| API authentication | Basic/session in Phase 2; JWT in Phase 4 |
| Optional identity provider | Google through django-allauth in Phase 7 |
| Authorization | Local Django users, groups, and explicit permissions |

## Core rules

- Retain the existing `stock_quantity` field and Python naming conventions.
- Procurement increases stock; sales reduce it. Quantities are positive whole units and transaction type determines direction.
- `Product.price` is the default selling price; acquisition cost is separate.
- Valuation, COGS, revenue, and gross-profit snapshots are part of Phase 3.
- Stock and valuation changes are atomic and recorded through shared services.
- Phase 2 blocks client stock updates; Phase 3 closes ordinary Admin balance edits too.
- Cost/profit visibility and operations are enforced on the server across web, API, and exports.
- Initial scope is one organization, one stock location, one currency, and one product per transaction.

See [architecture](docs/00_architecture.md) for the transaction types, valuation example, full role matrix, and authentication design.

## Run an existing implementation

Prerequisites: Git, [uv](https://docs.astral.sh/uv/getting-started/installation/), and the project source with `pyproject.toml`, `uv.lock`, and committed migrations. Replace the example URL:

```sh
git clone https://github.com/YOUR_USERNAME/django_inventory.git
cd django_inventory
uv sync --locked
uv run python manage.py migrate
uv run python manage.py createsuperuser
uv run python manage.py runserver
```

Open [Django Admin](http://127.0.0.1:8000/admin/). This command sequence assumes an implementation checkout, not a documentation-only folder. For initialization and code, use [Phase 1](docs/01_getting_started.md). Phase 3 additionally requires a running PostgreSQL database and connection configuration.

## Repository layout

```text
django_inventory/
├── README.md
├── pyproject.toml
├── uv.lock
├── manage.py
├── django_inventory/        # named config/ in the tutorial examples
├── inventory/
├── accounts/                 # planned Phase 4
└── docs/
    ├── 00_architecture.md
    ├── 01_getting_started.md
    ├── 02_rest_api.md
    ├── 03_stock_transactions_valuation.md
    ├── 04_accounts_roles_jwt.md
    ├── 05_web_interface.md
    ├── 06_reports_usability.md
    ├── 07_google_authentication.md
    ├── 08_deployment.md
    └── ROADMAP.md
```

## Development

Commit source, migrations, `.python-version`, `pyproject.toml`, and `uv.lock`. Ignore `.venv`, local databases, caches, and secrets. Keep changes focused, update the relevant phase guide, and run checks and meaningful tests:

```sh
uv run python manage.py check
uv run python manage.py makemigrations --check --dry-run
uv run python manage.py test
```

Generated empty tests do not verify behavior; Phase 2 supplies API test examples. See [architecture and development conventions](docs/00_architecture.md#development-conventions) for contribution details. No project license is assumed; add a LICENSE before specifying reuse terms.

## Future expansion

Multi-item purchase/sales orders, suppliers/customers, partial receipts, returns, taxes, freight allocation, warehouses/transfers, barcode scanning, imports, and notifications follow the base release.

