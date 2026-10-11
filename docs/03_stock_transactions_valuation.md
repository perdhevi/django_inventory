# 03 — PostgreSQL, procurement, sales, and valuation

**Status: implementation plan.** Prerequisite: complete the Phase 2 tutorial. This guide defines the sequence and acceptance criteria; it does not supply a finished implementation.

## 1. Move the database foundation to PostgreSQL

Add the driver:

```sh
uv add "psycopg[binary]"
```

Create a PostgreSQL database and application user. Read connection name, host, port, username, and password from environment variables; use `django.db.backends.postgresql`. Document local configuration without committing credentials.

If SQLite contains useful data, back it up, apply migrations to PostgreSQL, transfer records in dependency order, reset sequences where necessary, and verify users, relationships, record counts, stock balances, and prices. `migrate` alone does not transfer records. Keep SQLite until verification succeeds.

**Check:** Django connects, migrations apply, Admin works, and existing Phase 2 tests pass against PostgreSQL.

## 2. Add product fields for the expanded domain

Keep `stock_quantity` and `price`; `price` means default selling price. Add description, active status, average unit cost, and remaining inventory cost through explicit migrations. Add reorder level when low-stock reporting is introduced.

Choose Decimal precision and a single currency. Store inventory value with enough precision for the rounding policy, rather than reconstructing it from a rounded display average. Define zero-stock behavior. Reject new sales/procurement for inactive products.

**Check:** existing products survive the migration and monetary values never use binary floats.

## 3. Model a single-product StockTransaction

Record product, transaction type, positive whole-unit quantity, reference, notes, actor, and server-controlled timestamp. Types are `PROCUREMENT`, `SALE`, `OPENING_BALANCE`, `ADJUSTMENT_IN`, and `ADJUSTMENT_OUT`.

Capture applicable acquisition cost, actual selling price, inventory value added/consumed, revenue, and gross profit. These snapshots preserve historical results. The server derives monetary totals and stock direction; clients do not set derived fields or the actor.

**Check:** invalid types, zero quantities, negative prices/costs, and missing required costs/reasons are rejected.

## 4. Reconcile opening stock

Phase 1 allowed initial stock through Admin/shell. For each existing balance, obtain an opening cost and create a matching opening record. Recording that history must not add the existing stock twice. Use a controlled, repeatable reconciliation process with a documented cutover.

**Check:** opening quantity/value agree with product balances and rerunning reconciliation cannot duplicate them.

## 5. Implement one shared posting service

Within `transaction.atomic()`, lock the product, verify actor permissions, validate the operation, calculate quantity/cost changes, create the immutable movement, and update product balances. Until Phase 4, keep the existing active-staff access policy; organize checks so business permissions can replace it.

Procurement adds received quantity and acquisition cost. Sales subtract quantity and average acquisition cost, while recording actual revenue. Reject sales/withdrawals above available stock. Adjustments require a reason; increases require a cost.

Validate a duplicate-request key and protect its uniqueness so client retries do not post twice. Define whether a repeated key returns the original result or a conflict; reject reuse with a different payload.

**Check:** failure rolls back both movement and balances, and simultaneous sales cannot oversell.

## 6. Implement weighted-average valuation

```text
new_value = previous_value + received_quantity * acquisition_unit_cost
new_average_cost = new_value / new_quantity
sale_cogs = sold_quantity * average_cost_at_sale
sale_revenue = sold_quantity * actual_selling_price
gross_profit = sale_revenue - sale_cogs
```

A final withdrawal consumes all remaining recorded cost and resets quantity/value/average to zero. Define and test rounding at persistence and display boundaries. Procurement/adjustments do not count as sales revenue.

Example: receive 10 at 20.00 and 10 at 30.00; stock is 20, average cost 25.00, value 500.00. Sell 4 at 40.00; remaining value is 400.00, revenue 160.00, COGS 100.00, gross profit 60.00.

**Check:** arithmetic matches the example and repeated partial withdrawals leave no residual value when stock reaches zero.

## 7. Expose API operations and secure Admin

Add proposed list/create `/api/stock_transactions/`, retrieve `/api/stock_transactions/{id}/`, and `/api/valuation/` totals. Creation accepts a typed business operation and calls the service. Do not expose generic movement update/delete.

Make stock/cost balances read-only in Admin. Prevent Admin from bypassing the posting service. Protect products with history from deletion and offer deactivation. Posted corrections must be linked compensating movements.

**Check:** direct product PATCH cannot change stock/cost, and generic Admin editing cannot rewrite posted movements.

## 8. Test and document completion

Cover receipts, sales, adjustment rules, opening balances, cost snapshots, rounding, rollback, inactive products, deletion protection, duplicate requests, and concurrent sales. Use PostgreSQL and meaningful transaction tests for locking behavior; SQLite cannot validate equivalent row locking.

```sh
uv run python manage.py check
uv run python manage.py makemigrations --check --dry-run
uv run python manage.py test
```

**Deliverable:** migration/model/service/API changes, PostgreSQL setup instructions, passing tests, and documented stock/valuation policies.

Next: [Phase 4](04_accounts_roles_jwt.md). See [architecture](00_architecture.md) and [README](../README.md).
