# Implementation roadmap

Phases 1 and 2 are existing code tutorials. Phases 3–8 are detailed implementation plans; they are not complete copy-paste code tutorials yet. Follow the numbered guide for each phase. Do not infer feature completion from documentation availability.

Phase 1 and Phase 2 documentation already exists. The milestones below preserve those guides and extend them; documentation availability is not proof of completed implementation.

### Phase 1 — Existing foundation and Admin

- uv setup, Django/DRF dependencies, `config` and `inventory` creation.
- Category/Product models with `stock_quantity`, SQLite migrations, and ORM exercises.
- Default Django user model, superuser creation, email/password changes.
- Basic and enhanced Admin, server startup, and repository conventions.

**Completion:** the tutorial implementation runs with category/product Admin and a local superuser. No custom user model, end-user account screens, JWT, or business roles are claimed.

### Phase 2 — Existing base REST tutorial

- Serializers, ViewSets, routers, and request lifecycle.
- Category/product CRUD, protected-category deletion, read-only API stock.
- Basic/session authentication and staff-only `IsAdminUser` access.
- Manual requests and six focused API test examples.

**Completion:** authenticated staff can manage the catalog through the API; tests pass in the implementation checkout. Advanced filters, pagination, JWT, and valuation are later additions.

### Phase 3 — PostgreSQL, procurement, sales, and valuation

- PostgreSQL connection configuration and verified transfer of any existing SQLite records.
- Product extensions for active status and valuation; documented cost precision/rounding.
- Typed stock transactions: procurement, sale, opening balance, adjustment in/out.
- Required procurement costs, sale-price snapshots, inventory cost consumed, revenue, and gross profit.
- Atomic shared services, concurrency protection, insufficient-stock rejection, duplicate submission handling.
- Opening-balance reconciliation, read-only Admin balances, immutable history, protected product deletion.
- Transaction endpoints, basic valuation totals, and meaningful PostgreSQL-backed tests.

**Completion:** procurement increases stock/value, sales decrease stock/value and capture COGS/revenue, and failed operations change neither history nor balances.

### Phase 4 — Accounts, business roles, and JWT

- Organize account behavior in `accounts` while retaining the existing user model.
- Create Viewer, Sales, Procurement, Inventory manager, and Administrator groups.
- Replace broad staff access with explicit capabilities; enforce field/query restrictions.
- JWT login, refresh rotation/revocation, current-user endpoint, and access approval.
- Test allowed/forbidden actions and cost/profit visibility for every role.

**Completion:** users access only their permitted operations and data, regardless of client.

### Phase 5 — End-user web application

- Session-based local login/logout and password-change pages.
- Shared responsive layout, role-aware navigation, validation and empty states.
- Dashboard, category/product lists and forms, product detail/deactivation.
- Receive Procurement, Record Sale, opening-balance/correction screens, and transaction history.
- Display stock, valuation, revenue, and profit only to authorized roles.
- Use the same stock/valuation services and server-side checks as the API.

**Completion:** users can perform their daily permitted inventory workflows through the browser. This is the first complete web-and-API application milestone.

### Phase 6 — Reports and usability

- Reorder levels, low-stock indicators, search/filtering, and pagination.
- Current-stock, valuation, procurement, sales, and movement reports.
- Permission-controlled CSV exports and expanded dashboard summaries.
- API schema documentation, query optimization, and report reconciliation tests.

**Completion:** operational reports match recorded movements and expose only authorized fields.

### Phase 7 — Google sign-in

- django-allauth Google provider, per-environment credentials/callbacks, feature configuration.
- Explicit account linking, local login retention, invite/approval enforcement.
- Google-to-session and Google-to-application-JWT flows.
- Tests covering disabled users, account linking, and unchanged role enforcement.

**Completion:** approved users can choose password or Google login with the same permissions.

### Phase 8 — Deployment readiness

- Production secrets/settings, HTTPS, static files, PostgreSQL deployment.
- CI checks, logging, health checks, backup and tested restore procedures.
- Reproducible deployment/migrations and accurate implementation documentation.

**Completion:** the application can be deployed, monitored, backed up, and restored. Tests and configuration hygiene accompany all phases; CI should begin earlier when practical.

### Later expansion

Multi-item purchase/sales orders, suppliers/customers, draft/posting workflows, partial receipts, returns, linked reversals, discounts/taxes, freight allocation, multiple warehouses/transfers, barcode scanning, bulk imports, notifications, and additional identity providers. These are outside the single-product transaction base release.

See the [README](../README.md) for links to every phase and [architecture](00_architecture.md) for domain and permission policies.
