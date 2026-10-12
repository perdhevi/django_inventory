# Tutorial build validation — 11 October 2026

Core phases 3–7 plus the optional Google integration were assembled into a runnable application and checked against a real PostgreSQL database and a Linux production container. This validates the tutorial build; the main application checkout still contains its Phase 2 implementation. Existing application source, development SQLite data, and the user's dependency changes were preserved.

## Results

### Current Phase 6 verification through Step 5 — 13 October 2026

Final main-checkout checks passed: Django system checks, `migrate --check`, `makemigrations --check --dry-run`, and strict schema generation/validation with `--fail-on-warn`. The complete 29-test suite passed on PostgreSQL with zero skips. An additional disposable endpoint check confirmed `/api/schema/` and `/api/docs/` return 401 anonymously, 403 for a logged-in non-staff account, and 200 for an active staff session; the schema response contains OpenAPI and the Swagger HTML references the schema route. UTC remains configured. No implementation issue requiring a further change was found within the reviewed Steps 1–5.

These checks validate server responses and test behavior; they do not establish that Swagger's JavaScript rendered interactively in a real browser, or complete the visual/keyboard/viewport walkthrough. The generic schema/query descriptions still have the documented client-contract limitations. Step 7 of this phase and deployment are not claimed complete by this verification. Development data was not modified by the disposable tests.

### Phase 6 Step 5 implementation review — 13 October 2026

Follow-up after the user's annotations: all three object-response annotations are now present, applied at class level to `MeView`, `ReportView`, and `ValuationView`. This differs from the guide's method-level placement but is supported by the installed drf-spectacular version. Main-checkout system checks and `spectacular --file schema.yml --validate --fail-on-warn` both passed without warnings or errors. The generated root `schema.yml` includes the annotated object responses and the stock-posting request/response definitions. The previous serializer-inference failures are resolved. No application source was edited for this check; an actual Swagger browser walkthrough remains outstanding.

The current full suite passed all 29 tests on PostgreSQL with zero skips. Passing application tests does not resolve the separate schema-generation errors described below.

Steps 5.1–5.4 are implemented: `drf-spectacular` is in the dependency manifest and lock file, the app/schema settings are configured, the project schema/Swagger routes are registered with staff permissions, and stock posting has its request plus 200/201 response annotation. Step 5.5 is incomplete: all three modules import the schema helpers, but `ValuationView.get`, `ReportView.get`, and `MeView.get` lack their `@extend_schema(responses=OpenApiTypes.OBJECT)` decorators. System checks pass, but strict schema validation fails with three unique serializer-inference errors for those views. No successful root `schema.yml` output was found. Step 5.6 needs a successful schema run after adding the decorators; Step 5.7's actual Swagger browser walkthrough remains unverified. Application source was reviewed without edits during this check.

### Phase 6 Step 4 implementation review — 13 October 2026

Follow-up fixes and timezone decision: per the user's request, UTC remains the application default (`TIME_ZONE = 'UTC'`, `USE_TZ = True`); Jakarta is no longer a prerequisite. The browser import and API route placement were corrected in the main application, report navigation links were added, and the movement list now includes pagination. Report JSON returns `timezone.get_current_timezone_name()` as `timezone`, and the HTML report displays it beside an explanation of date-filter boundaries. The guide now documents UTC and how to inspect default/active timezones. No timezone selector or per-user timezone preference was introduced.

Verification after those changes: main-checkout system checks, applied-migration checks, and model/migration consistency checks passed. All 22 existing tests passed on PostgreSQL with zero skips. Seven newly added report tests also passed on PostgreSQL with zero skips, covering totals, financial visibility, permission denial, CSV, pagination, UTC date boundaries, and an activated Jakarta override that changes both the reported timezone and date-filter result. Development records were not changed by the tests. These results supersede the routing failures and missing-navigation findings below.

Steps 3 and 4's report calculation, report views, and report template match the guide. Two routing errors prevent the main checkout from working as intended: `inventory/web_urls.py` imports `report_views` without a leading dot, causing URL configuration loading to fail; `inventory/urls.py` creates the report `path()` outside `urlpatterns`, so it is not registered. The browser report paths are otherwise inside their list correctly. `templates/base.html` has no report navigation links yet. Step 4 is now divided into 4.1–4.6 with explicit imports, route placement, template behavior, permission-aware navigation, and request checks.

The Step 2 product and movement filter forms are now present, and products include the pagination partial. The movement list still lacks that include. `TIME_ZONE` remains `UTC`, so Step 1.1's Jakarta boundaries remain outstanding. Main application source was reviewed without edits; corrected routing and the Jakarta setting were applied only to an isolated `.validation/step4-review/` copy for report tests. The Step 6 report tests were extracted into that copy because they have not yet been added to the main application.

Observed checks: the current checkout's system check failed with `ModuleNotFoundError: No module named 'report_views'` at `inventory/web_urls.py:3`, confirming the import issue. With routing corrected and Jakarta configured in the isolated copy, system checks passed, the combined 28-test suite passed on PostgreSQL with zero skips, and the migration dry run reported no changes. This supports the report calculations, endpoint responses, financial visibility, CSV behavior, date boundaries and pagination under those corrected conditions; it does not claim the main checkout currently passes or that navigation/visual checks are complete.

### Phase 6 documentation review — 12 October 2026

Follow-up review of the user's implementation: Step 1's reorder field is correctly placed on `Product`, exposed in the form/serializer, and accompanied by the correct applied `0004_product_reorder_level_and_more` migration and dashboard count/display. The settings still use `TIME_ZONE = 'UTC'`; date filters therefore use UTC boundaries until Step 1.1 changes it to Jakarta. Steps 2.1–2.4 match the guide: shared helpers, imports, API queryset methods, global pagination, and browser pagination are present. Step 2.5 is partial: `_pagination.html` exists but is not included in either list template. Step 2.6 is outstanding: neither list renders a GET filter form. The product-list stock warning is inside the loop and currently inside the product link; Step 1.4's example places it after the stock paragraph for clearer layout.

The current implementation passed all 22 existing tests on PostgreSQL with zero skips, system checks, applied-migration checks, and model/migration consistency checks. A separate disposable request test with 26 products/movements confirmed API 25-row pagination and second pages, product search/low-stock filtering, invalid-input handling in both interfaces, browser page context, and Sales role scoping. The rendered responses confirmed the missing pagination controls and filter forms. These checks used a test database and did not add development records. Step 2 is now organized as sub-steps 2.1–2.7 with explicit settings placement, template includes, a movement form example, and verification instructions. Main application files were reviewed without edits during this follow-up.

At the initial Phase 6 review, the application was a Phase 5 starting point: session/browser workflows, shared stock services, role-scoped history and JWT were present; reorder levels, shared query filters, report modules, pagination and schema endpoints had not yet been implemented in the main checkout. Its PostgreSQL baseline passed system checks and all 22 tests with zero skips. Every listed migration was applied, including inventory migrations 0001–0003, and the migration dry run reported no model drift.

Phase 6 examples were extracted into `.validation/phase6-review/` over a copy of that baseline. The isolated migration added only `Product.reorder_level` and `movement_date_idx`. The combined suite passed **28 tests with zero skips** on PostgreSQL, using a separate test database. System checks and the subsequent migration consistency check passed. OpenAPI generation passed `--validate --fail-on-warn` without warnings. No Phase 6 migration was applied to the development database, and no main application source was changed by this review.

The revised guide includes the actual `django_inventory` package paths, a Phase 5 handoff checklist, filter/error and pagination contracts, expected reconciliation amounts, report/export permission behavior, the export cap and concurrency limitations, and the distinction between staff schema access and business roles. Product dropdown examples now preserve selected filters. Six report tests cover reconciliation, sales financial visibility, Viewer export/valuation denial and quantity history, inclusive Jakarta end dates, role scoping, pagination totals, complete filtered exports, and HTTP validation errors.

This review does not establish visual browser/keyboard/narrow-viewport behavior, the 10,000-row cap under a large dataset, or report consistency during concurrent posting. Separate development role accounts and the Phase 5 manual walkthrough remain prerequisites unless completed since the previous review. The generic OpenAPI object annotations still need explicit report/query descriptions for a complete client contract. The ignored `.validation/review_phase6.py` helper repeats the baseline and isolated checks on this machine; it reads the local `.env.database` privately and uses the existing validation Python environment.

### Phase 5 documentation review — 12 October 2026

The current checkout now contains the Phase 3/4 models, services, roles, and JWT implementation. The historical Phase 2 checkout description above refers to the original full-tutorial rehearsal. For this review, Phase 5's Python, HTML, and CSS examples were extracted into `.validation/phase5-review/` on top of a copy of the current application; the main application source and database were not modified.

The revised guide clarifies this checkout's `django_inventory` package paths, Phase 4 and PostgreSQL prerequisites, local role accounts, UUID retries, inactive-product behavior, and current history limits. Posting and category deletion explicitly accept GET/POST only. Its browser test examples now cover login/logout and safe redirects, password change, insufficient stock, retry conflicts, inactive products, role-filtered history, financial visibility, CSRF, and protected balances.

Observed results: Django system checks passed; all eight Phase 5 browser tests passed; the combined browser/account/inventory suite ran 22 tests with 21 passing and one PostgreSQL concurrency test skipped on the isolated in-memory SQLite database. `makemigrations --check --dry-run` reported no changes. This review does not claim a new PostgreSQL concurrency rehearsal or visual browser/viewport inspection. Those checks remain part of the documented manual workflow.

Follow-up validation of the user's implemented Phase 5 checkout: the forms, browser views, browser URLs, eight browser tests, and all documented HTML/CSS files match the guide. System checks passed, all migrations were applied, and no model changes were detected. The complete 22-test suite passed on the local Compose PostgreSQL database at port 55432 with zero skips, including the concurrency test; Django used a separate test database. All five business groups have the expected permissions, but none has an active assigned user in the checked development database. Provisioning separate role accounts and completing the Step 7 visual/keyboard/narrow-viewport walkthrough remain outstanding. Minor cleanup items are the duplicate identical `STATIC_URL` assignment and unused `templates/inventory/web_urls.py` copy; the working route module is `inventory/web_urls.py`.

Follow-up on 12 October 2026: Phase 3 now includes a Docker Compose PostgreSQL walkthrough, and Phase 7 includes a local Caddy HTTPS override. Both documented Compose configurations passed `docker compose config --quiet`; `Caddyfile.local` passed Caddy's container configuration validation. The Phase 3 database was started from an empty named volume, reached healthy status, and returned `inventory | inventory_app` from the documented SQL check. This rehearsal used host port 55433 because the existing validation database occupies 55432; its container/network were removed afterward, retaining the data volume. The new Caddy override was configuration-checked; the earlier HTTPS smoke results below belong to the previously tested validation runtime.

| Check | Observed result |
| --- | --- |
| Phase 2 baseline on PostgreSQL | 6 API tests passed before the extended schema was applied |
| SQLite → PostgreSQL transfer | Imported demo user, category, and product; stock 10 and selling price 40.00 preserved; sequences reset |
| Inventory migration and consistency | Generated/applied the extended inventory migration; `makemigrations --check --dry-run` reported no changes |
| Opening reconciliation | First run created movement 1; identical second run returned `created=False`; stock remained 10 and value became 200 |
| Full tutorial and extra integration suite | **33 tests passed, zero skips** on PostgreSQL |
| Authorization coverage | All five business roles, combined Sales/Procurement, operation denial, detail filtering, financial fields, and Viewer export denial |
| Stock coverage | Weighted average, fractional rounding/final withdrawal, opening balances, retries, rollback, inactive products, stale metadata saves, and real concurrent sales |
| Authentication coverage | Real JWT login/rotation/revocation, current-role and inactive-user checks, session CSRF, Google approval/link-conflict rules |
| OpenAPI | Schema generated and validated without errors/warnings |
| Production settings | `check --deploy --fail-level WARNING` passed on Windows and inside the Linux image; only the two documented initial HSTS warnings are intentionally silenced |
| Container/runtime | Locked Linux image built; non-root Gunicorn started; 160 static files collected and hashed/compressed |
| HTTPS/session/API smoke run | **19 real HTTPS checks passed** through a local Caddy reverse proxy, including secure session cookies, login, CSRF, JWT exchange, procurement/sale/retry, insufficient stock, reports, CSV, schema page, logout and revoked refresh |
| Compose | `docker compose ... config --quiet` passed; runtime rehearsal used the same application image with an isolated database/proxy network |
| Backup and restore | Custom-format `pg_dump` restored into a separate database; all rows matched across 12 checked tables |
| Restored reconciliation | All three demo products' quantities and inventory values matched movement history; sale revenue 320, COGS 200, gross profit 120 |

Each successful HTTP stock example received 10 at 20.00 and 10 at 30.00, then sold 4 at 40.00. Its final stock was 16 and inventory value 400.000000. Two demo products were created during the HTTP rehearsal, plus the legacy opening product; this explains the restored aggregate sale totals above.

The assembler generates the final core Phase 3–7 schema plus optional Google integration in one inventory migration after the Phase 2 baseline. The individual phase migration files a reader creates while learning will have different names/order; the cutover itself was rehearsed before the new fields existed.

## Issues found and corrected

1. **Production mail settings:** this checkout runs Django 6.1, whose development `MAILERS` backend fails deployment checks. Phase 7 now configures SMTP using the appropriate Django-version interface and avoids combining `MAILERS` with deprecated `EMAIL_*` settings. SMTP delivery itself was not exercised; no reset-email workflow is claimed.
2. **Non-root Gunicorn startup:** the container lacked a writable home, causing a control-socket permission error. Phase 7's Dockerfile now sets `HOME=/app`; the rebuilt container started with its socket at `/app/.gunicorn/gunicorn.ctl` and no such error.
3. The HTTP check initially requested JSON from Swagger's HTML page, producing the correct 406 response. The validation client now requests HTML for `/api/docs/`; no application workaround was needed.

## Environment and artifacts

| Component | Tested version |
| --- | --- |
| Python | 3.14.7 on Windows; 3.14.8 in the Linux image |
| Django / DRF | 6.1.2 / 3.18.3 |
| PostgreSQL | 17.11 |
| psycopg / Simple JWT | 3.3.6 / 5.5.1 |
| django-allauth / drf-spectacular | 65.19.7 / 0.30.0 |
| Gunicorn / WhiteNoise | 26.2.0 / 6.12.0 |
| uv | 0.12.22 |

The ignored `.validation/` directory contains:

- `build/`: runnable Django application, generated migration, OpenAPI schema, locked dependencies, Dockerfile and Compose/CI examples.
- `legacy/`: isolated Phase 2 build and SQLite cutover demo.
- `venv/`: separate validation dependencies.
- `http-results.json` and `restore-results.json`: observed HTTP checks and restored table counts/digests.
- `inventory-validation.dump`: the rehearsal backup, containing demo records only.
- Environment/secret files for the disposable services; keep these ignored.

The local HTTPS client trusted only the generated proxy certificate within its own process. No certificate was installed into the user's system trust store. No public site was deployed. Validation containers were stopped after the checks; the generated files, image, and disposable database containers remain available for another run.

## Repeat the checks on this machine

Run from the repository root in PowerShell. Docker Desktop must be running. Start the existing disposable database and rerun the application checks:

```powershell
docker start django-inventory-validation-pg
.validation/venv/Scripts/python.exe tools/run_tutorial_validation.py check
.validation/venv/Scripts/python.exe tools/run_tutorial_validation.py makemigrations --check --dry-run
.validation/venv/Scripts/python.exe tools/run_tutorial_validation.py test
.validation/venv/Scripts/python.exe tools/run_tutorial_validation.py spectacular --file schema.yml --validate
.validation/venv/Scripts/python.exe tools/run_tutorial_validation.py --production check --deploy --fail-level WARNING
```

To repeat actual HTTPS requests:

```powershell
docker start django-inventory-validation-web django-inventory-validation-proxy
.validation/venv/Scripts/python.exe tools/smoke_tutorial_http.py
```

Each smoke run creates a new demo product and movements. A new backup must be taken/restored before rerunning the restore comparison; the saved restore reflects the snapshot documented above.

The assembly helper is [tools/validate_tutorials.py](../tools/validate_tutorials.py). It explicitly maps code blocks from the current guides and builds the isolated application. It assumes a Phase 2 source checkout and fails if the documented block layout changes; update the mapping when restructuring a guide. Regenerating source alone does not apply migrations or rebuild the Docker image. Its companion [runner](../tools/run_tutorial_validation.py) connects only to the disposable local database configured in `.validation/`.

Stop the disposable services when finished:

```powershell
docker stop django-inventory-validation-proxy django-inventory-validation-web django-inventory-validation-pg
```

## Remaining external checks

Per the user's choice, **the real Google OAuth provider round trip is deferred**. Local approval, linking conflicts, role persistence, and CSRF/session-to-JWT rules passed with the actual allauth dependency. Live Google consent/callback/recovery must still be checked with configured OAuth credentials as described in the [optional Google integration guide](integrations/google_authentication.md).

Public-host DNS/certificates, a remote GitHub Actions run, production database-role provisioning, scheduled operations, and actual SMTP delivery depend on the chosen deployment environment. The local container/HTTPS/restore rehearsal does not establish those external services are configured.
