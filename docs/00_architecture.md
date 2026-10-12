# Architecture and application scope

This document records the agreed design. Core phases 1–7 provide follow-along code tutorials for applying it; neither the design nor tutorial availability establishes verified implementation in this checkout.

## Familiar concepts

| Concern | Django / DRF | FastAPI ecosystem | Spring Boot ecosystem |
| --- | --- | --- | --- |
| Application configuration | `config/settings.py` | Settings object, often Pydantic Settings | `application.yml`, configuration classes |
| Functional module | Django app, such as `inventory` | Python package and `APIRouter` | Java package/module |
| Persistent entity | `models.Model` | Usually SQLAlchemy model | JPA `@Entity` |
| Database access | Manager and QuerySet, e.g. `Product.objects` | SQLAlchemy session; optional repository | Spring Data repository / Hibernate |
| Schema evolution | Django migrations | Usually Alembic | Flyway or Liquibase |
| Request/response data | DRF serializer | Pydantic model | DTO and Bean Validation |
| HTTP handler | DRF view or ViewSet | Path operation | `@RestController` method |
| URL registration | `urls.py` and DRF router | `APIRouter` | `@RequestMapping` |
| Authentication/access | Django auth plus DRF authentication/permissions | Dependencies plus chosen auth tooling | Spring Security |
| Business operations | Optional service functions | Optional service layer | Usually `@Service` |
| Internal management UI | Django Admin | Requires additional tooling | Requires additional tooling |

These are analogies, not exact equivalents. SQLAlchemy and Alembic are separate choices in FastAPI; Django includes its ORM and migrations. A DRF serializer can both validate input and serialize model instances. Django Admin is a staff management interface, not the inventory API.

The intended request flow is:

```text
HTTP request
  -> config/urls.py + DRF router
  -> ViewSet + serializer + permissions
  -> optional service for business operations
  -> Django ORM
  -> database
```

Simple CRUD can use the ORM directly from a ViewSet. Introduce a service when an operation has business rules, such as recording a stock movement and updating its balance together. Django does not require a separate repository class around every model.

## Interfaces and authentication

| Interface | Planned technology | Authentication |
| --- | --- | --- |
| End-user pages | Django templates, forms, and views | Session cookies and CSRF protection |
| JSON API | Django REST Framework | Basic/session in Phase 2; application JWT in Phase 4 |
| Administration | Django Admin | Django sessions; staff access |

Web views and API handlers share inventory services and authorization rules. Server-rendered pages need not call the application's REST API.

Phase 1 retains SQLite. Phase 3 adds PostgreSQL, a configured database/user, environment-based connection settings, and `uv add "psycopg[binary]"`. Applying migrations creates the schema; copying existing SQLite records requires a separate verified data-transfer step. Concurrency tests run against PostgreSQL.

Phase 4 adds Simple JWT (`uv add djangorestframework-simplejwt`), short-lived access tokens, refresh rotation, and refresh-token blacklisting. Revoking a refresh token does not normally invalidate an already issued access token before its expiry. API clients send `Authorization: Bearer <access_token>`.

The optional [Google sign-in integration](integrations/google_authentication.md) adds django-allauth outside the core feature path. Local login, users, roles, permissions, sessions, and application JWT remain core features; deployment does not require an external identity provider. Local password login and Google sign-in resolve to the same local user, roles, and permissions. Google establishes identity; our application grants access and issues its own session or JWT. Use authenticated account linking rather than automatically merging matching email addresses. Access remains invite-only or administrator-approved.

An `accounts` app can organize these features without replacing the existing user model. A custom-user migration requires a separate plan if it becomes necessary; it is not a prerequisite for roles or Google login.

## Domain, transactions, and valuation

The base functional release covers one organization, one stock location, whole-unit quantities, and one currency. Procurement means goods actually received; a sale means goods actually issued. Orders, payment processing, taxes, and accounting integration are later expansions.

| Entity | Scope |
| --- | --- |
| Category | Unique name and related products; Phase 1 |
| Product | Unique SKU, name, category, selling price, `stock_quantity`, timestamps; Phase 1 |
| Product extensions | Description, reorder level, active status, average unit cost, remaining inventory cost; later migrations |
| StockTransaction | Product, type, positive quantity, applicable unit cost/selling price, reference, notes, actor, timestamp; Phase 3 |
| User | Existing Django user with groups and permissions; expanded in Phase 4 |

Retain `stock_quantity` from the established tutorials; do not silently rename it to `current_stock`. `Product.price` is the default selling price, not acquisition cost. A sale records its actual selling price separately.

### Base transaction types

| Type | Stock effect | Valuation rule |
| --- | --- | --- |
| `PROCUREMENT` | Increase | Acquisition unit cost is required; recalculate weighted-average cost |
| `SALE` | Decrease | Consume inventory at current average cost; record selling price and cost consumed |
| `OPENING_BALANCE` | Establish initial balance | Quantity and acquisition cost establish starting inventory value |
| `ADJUSTMENT_IN` | Increase | Cost and correction reason are required |
| `ADJUSTMENT_OUT` | Decrease | Consume inventory at current average cost; correction reason is required |

Every operation has a positive quantity; its type determines the direction. The initial transaction contains one product. Record historical unit costs, selling prices, and totals so subsequent price changes cannot rewrite history.

### Stock and valuation rules

Phase 1 permits direct introductory stock entry. Phase 2 makes stock read-only in the API, while Admin/shell edits remain possible. Phase 3 makes transaction services the supported path for changing balances and makes stock read-only in Admin too.

The shared service will authenticate/authorize the operation, validate inputs, lock the product in PostgreSQL, and record the transaction plus stock/cost changes inside `transaction.atomic()`. Reject insufficient stock, protect against concurrent sales, and handle duplicate submissions. Failed operations must roll back all changes.

Posted history cannot be edited/deleted through the tutorial API or Admin. Inventory corrections use adjustments linked to the original movement; they do not cancel sale revenue. Full returns/cancellations with financial reversals are a later extension. Protect products with history from deletion and use deactivation. Reconcile existing Phase 1 balances through opening-balance records before enabling transaction-only stock updates. Trusted shell/SQL access must follow the same service convention.

### Inventory valuation — included in Phase 3

Use **moving weighted-average acquisition cost** as the initial application policy:

```text
new_inventory_value = previous_inventory_value + received_quantity * acquisition_unit_cost
new_average_unit_cost = new_inventory_value / new_stock_quantity
sale_cost_of_goods_sold = sold_quantity * current_average_unit_cost
sale_revenue = sold_quantity * actual_selling_unit_price
gross_profit = sale_revenue - sale_cost_of_goods_sold
```

Use the stored remaining inventory cost as the balance source, with an explicit Decimal precision/rounding policy. Do not repeatedly reconstruct it from a rounded display average. When a withdrawal consumes all remaining stock, consume the entire remaining inventory cost and reset the balance/average to zero to avoid rounding residue.

| Operation | Remaining units | Average cost | Remaining value |
| --- | ---: | ---: | ---: |
| Receive 10 at 20.00 | 10 | 20.00 | 200.00 |
| Receive 10 at 30.00 | 20 | 25.00 | 500.00 |
| Sell 4 at 40.00 | 16 | 25.00 | 400.00 |

The sale records revenue of 160.00, cost of goods sold of 100.00, and gross profit of 60.00 before other expenses. Procurement and stock adjustments are not sales revenue. This is a base operational valuation model; tax, freight allocation, financial accounting, and advanced costing need separate policies later.

Phase 3 includes valuation API output and basic totals for inventory value, sales revenue, cost of goods sold (COGS), and gross profit. Phase 5 displays them to authorized users; Phase 6 expands filtering, reporting, and export.

## Roles and permissions

Phase 4 uses Django groups plus built-in/custom permissions. A user may belong to several groups; their granted capabilities combine. Application roles do not automatically grant `is_staff` or `is_superuser`.

| Capability | Viewer | Sales | Procurement | Inventory manager | Administrator |
| --- | :---: | :---: | :---: | :---: | :---: |
| View products and available stock | Yes | Yes | Yes | Yes | Yes |
| Record sales | No | Yes | No | Yes | Yes |
| Record procurement receipts | No | No | Yes | Yes | Yes |
| Manage products/categories | No | No | No | Yes | Yes |
| View all stock movements* | Yes | No | No | Yes | Yes |
| View sales history and revenue | No | Yes | No | Yes | Yes |
| View procurement history and costs | No | No | Yes | Yes | Yes |
| View inventory valuation, COGS, gross profit | No | No | No | Yes | Yes |
| Record opening balances/adjustments | No | No | No | No | Yes |
| Manage users and assign roles | No | No | No | No | Yes |

*Viewer movement history exposes quantities, types, references, and dates, while excluding acquisition costs, revenue, valuation, and profit. Sales sees sales history without COGS/profit. Procurement sees procurement acquisition costs, without sales revenue or overall valuation. Export requires the relevant report permission and uses the same field restrictions.

Phase 4's tutorial creates `record_sale`, `receive_procurement`, `adjust_stock`, `record_opening_balance`, `view_all_movements`, `view_sales_report`, `view_procurement_report`, `view_inventory_valuation`, and `export_reports`. Enforce permissions in web views, API handlers, and shared stock operations. Hiding buttons alone is insufficient. Until Phase 4, Phase 3 follows the existing staff-only API access policy. Role assignment remains a trusted superuser Admin workflow; a generic role-editing API is not exposed.

## Development conventions

Use a focused branch and keep changes small. Explain the behavior being added, update this README when implementation status changes, and include relevant tests. For model changes, commit their migrations in the same change. For dependency changes, commit both `pyproject.toml` and `uv.lock`.

Add or merge these patterns into `.gitignore`:

```gitignore
.venv/
__pycache__/
*.py[cod]
db.sqlite3
db.sqlite3-*
.env
.env.*
!.env.example
```

Commit `.python-version` and migration source files. Keep credentials and local databases out of Git. Before submitting changes, run Django checks, applicable tests, and the migration consistency check from the command table.

Before deployment, move secrets out of committed settings, disable `DEBUG`, configure `ALLOWED_HOSTS`, choose a production server/database, and define authentication and stock permissions. The baseline is a learning environment rather than a deployment configuration.

No project license is assumed here. Add a `LICENSE` file and state its terms before inviting reuse under a particular license.

Return to [README](../README.md).
