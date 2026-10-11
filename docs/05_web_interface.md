# 05 — End-user web interface

**Status: implementation plan.** Prerequisite: Phase 4. Use Django templates/forms and session authentication; the pages call shared services directly.

## 1. Create the shared layout

Add a base template, static styles, navigation, messages, error display, and responsive page structure. Keep Admin separate from the end-user workflow. Show only permitted navigation items while checking permissions on every server request.

**Check:** desktop/mobile layouts work and direct URL access cannot bypass hidden navigation.

## 2. Build account pages

Provide login, POST-based logout, and password-change templates using Django authentication behavior. Configure redirects and friendly errors. Include CSRF protection on forms. Add password reset only when email delivery and reset templates are configured.

**Check:** login redirects work, unauthenticated access is protected, and invalid CSRF requests fail.

## 3. Build the dashboard and catalog

Show stock summaries, recent authorized movements, and authorized financial totals. Add product/category lists, detail pages, forms, and product deactivation. Add reusable search/filter/pagination components now or extend them in Phase 6.

Product forms edit metadata and selling price, never stock or inventory cost balances. Protect referenced categories and present understandable deletion errors.

**Check:** role-specific dashboard values match the API and catalog permissions match Phase 4.

## 4. Add procurement and sales workflows

Provide Receive Procurement and Record Sale screens. Procurement requests product, received quantity, acquisition unit cost, reference, and notes. Sales requests product, quantity, actual unit selling price, reference, and notes. Show a review of totals before posting where helpful.

Both workflows call Phase 3 services, use duplicate-submission protection, and display insufficient-stock/validation errors. Redirect after success to avoid accidental form resubmission.

**Check:** stock, valuation, COGS, and revenue update exactly once and match API behavior.

## 5. Add controlled corrections and history

Provide Administrator-only opening balance and adjustment forms, with required reasons/costs. Do not use opening balance as a repeated replenishment operation. Show movement history/detail with role-filtered quantities and financial fields. No ordinary editing/deleting of posted history.

**Check:** Sales and Procurement cannot open or submit correction forms, and prohibited cost/profit fields are absent from rendered HTML.

## 6. Validate the complete workflow

Test login, roles, forms, CSRF, successful posting, duplicate submissions, failure handling, direct URL access, and financial visibility. Review keyboard navigation, labels, empty states, and mobile layouts.

**Deliverable:** a usable browser workflow: sign in, manage permitted catalog data, receive goods, sell goods, and inspect stock/history. This completes the first web-and-API application milestone.

Next: [Phase 6](06_reports_usability.md). Return to [README](../README.md).
