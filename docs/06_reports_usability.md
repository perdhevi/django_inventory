# 06 — Reports and usability

**Status: implementation plan.** Prerequisite: Phase 5. Basic valuation already belongs to Phase 3; this phase expands reporting rather than postponing it.

## 1. Add low-stock policy

Add a nonnegative reorder level if not already present. Define low stock as quantity at or below that threshold, with a separate out-of-stock indicator. Show these on the dashboard and product list.

**Check:** zero stock and exact-threshold cases display correctly.

## 2. Standardize search and pagination

Support product SKU/name search and category/active/low-stock filters. Filter transactions by product, type, actor, and date. Apply stable ordering and bounded pagination to web and API lists.

**Check:** pagination does not skip/duplicate records under a fixed dataset; filters respect role-scoped querysets.

## 3. Build reports

Provide current stock and valuation snapshots, sales revenue/COGS/gross-profit totals, procurement quantity/cost totals, and movement history. Current valuation is a snapshot; date-filtered movement reports are a different calculation. Historical as-of valuation requires replay or stored snapshots and must not be implied without implementation.

Define date boundaries/timezone, rounding, and treatment of linked reversals. Reuse shared query/calculation code so web/API/exports agree.

**Check:** report totals reconcile with recorded movement snapshots and remaining inventory value.

## 4. Add CSV export

Require both export permission and access to the report's underlying fields. Restrict financial columns by role, preserve decimal precision, label the currency, and guard spreadsheet formula interpretation in user-entered text.

**Check:** exporting cannot reveal fields omitted from the screen/API.

## 5. Document and optimize

Add API schema documentation and examples reflecting actual implemented routes. Measure report/list queries, add justified indexes, and avoid related-record query loops. Bound export volume or add an explicit large-export strategy later.

**Deliverable:** reliable filtered reports, low-stock indicators, safe authorized CSV exports, API documentation, and reconciliation tests.

Next: [Phase 7](07_google_authentication.md). Return to [README](../README.md).
