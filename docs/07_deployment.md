# 07 — Package, verify, and deploy the application

Continue from [Phase 6](06_reports_usability.md). Local authentication is sufficient for this core deployment milestone. You will add production settings, a Linux container, PostgreSQL CI, health checks, and backup/restore instructions. This walkthrough chooses Docker Compose behind an HTTPS reverse proxy. Complete a local/staging rehearsal before publishing a production service.

Use the package-name substitution from Phase 3. Commands below use `config.settings_production` and `config.wsgi`; this checkout needs `django_inventory.settings_production` and `django_inventory.wsgi` instead.

## 0. Prepare the deployment tools

Run all commands from the repository root. Start Docker Desktop and select Linux containers, then verify Docker is available:

```powershell
docker version
docker compose version
```

`docker version` must show both client and server. If only the client appears, wait for Docker Desktop to finish starting before continuing.

Use a fresh PowerShell terminal for the deployment commands. Configure the deployment variables in `.env.production` as described below. Django does not automatically read environment files; Compose passes the file's values into the application container.

## 1. Separate development and production configuration

### 1.1 Install the runtime dependencies

Run the command below on Windows to update the dependency files. Gunicorn runs inside the Linux image later; continue using Django's development server for ordinary Windows development.

```sh
uv add gunicorn whitenoise
```

In the existing `config/settings.py`, replace the hardcoded `SECRET_KEY`, `DEBUG`, and `ALLOWED_HOSTS` assignments:

```python
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "local-learning-only-do-not-deploy")
DEBUG = os.environ.get("DJANGO_DEBUG", "true").lower() == "true"
ALLOWED_HOSTS = os.environ.get("DJANGO_ALLOWED_HOSTS", "127.0.0.1,localhost").split(",")
```

### 1.2 Add production settings

For this checkout, edit `django_inventory/settings.py` above and create `django_inventory/settings_production.py` below. Keep the existing PostgreSQL configuration, installed apps, templates, role settings, and JWT settings. The import below reuses them and overrides the deployment-specific values.

Create `config/settings_production.py`:

```python
import os
from django.core.exceptions import ImproperlyConfigured

from .settings import *

SECRET_KEY = os.environ["DJANGO_SECRET_KEY"]
if len(SECRET_KEY) < 50 or SECRET_KEY == "local-learning-only-do-not-deploy":
    raise ImproperlyConfigured("Set a strong production DJANGO_SECRET_KEY.")
DEBUG = False
ALLOWED_HOSTS = [host.strip() for host in os.environ["DJANGO_ALLOWED_HOSTS"].split(",") if host.strip()]
if not ALLOWED_HOSTS or "*" in ALLOWED_HOSTS:
    raise ImproperlyConfigured("Explicit production hosts are required.")
CSRF_TRUSTED_ORIGINS = [origin.strip() for origin in os.environ["DJANGO_CSRF_TRUSTED_ORIGINS"].split(",")]
SECURE_SSL_REDIRECT = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_HSTS_SECONDS = 3600
SECURE_HSTS_INCLUDE_SUBDOMAINS = False
SECURE_HSTS_PRELOAD = False
# This first release intentionally applies HSTS only to this host, without preload.
SILENCED_SYSTEM_CHECKS = ["security.W005", "security.W021"]
# Only trust this header behind a proxy that overwrites client-supplied forwarding headers.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
STATIC_ROOT = BASE_DIR / "staticfiles"
MIDDLEWARE = list(MIDDLEWARE)
MIDDLEWARE.insert(MIDDLEWARE.index("django.middleware.security.SecurityMiddleware") + 1,
                  "whitenoise.middleware.WhiteNoiseMiddleware")
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}
# Django 6.1 forbids combining MAILERS with deprecated EMAIL_* settings.
from django import VERSION as django_version

_smtp = {
    "host": os.environ.get("SMTP_HOST", "localhost"),
    "port": int(os.environ.get("SMTP_PORT", "587")),
    "username": os.environ.get("SMTP_USER", ""),
    "password": os.environ.get("SMTP_PASSWORD", ""),
    "use_tls": os.environ.get("SMTP_USE_TLS", "true").lower() == "true",
    "timeout": 10,
}
DEFAULT_FROM_EMAIL = os.environ.get("DEFAULT_FROM_EMAIL", "inventory@localhost")
if django_version >= (6, 1):
    for _name in ("EMAIL_BACKEND", "EMAIL_FILE_PATH", "EMAIL_HOST", "EMAIL_PORT", "EMAIL_HOST_USER",
                  "EMAIL_HOST_PASSWORD", "EMAIL_USE_TLS", "EMAIL_USE_SSL", "EMAIL_TIMEOUT",
                  "EMAIL_SSL_CERTFILE", "EMAIL_SSL_KEYFILE"):
        globals().pop(_name, None)
    MAILERS = {
        "default": {"BACKEND": "django.core.mail.backends.smtp.EmailBackend", "OPTIONS": _smtp}
    }
else:
    globals().pop("MAILERS", None)
    EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
    EMAIL_HOST, EMAIL_PORT = _smtp["host"], _smtp["port"]
    EMAIL_HOST_USER, EMAIL_HOST_PASSWORD = _smtp["username"], _smtp["password"]
    EMAIL_USE_TLS, EMAIL_TIMEOUT = _smtp["use_tls"], _smtp["timeout"]
LOGGING = {
    "version": 1, "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": "INFO"},
    "loggers": {"django": {"handlers": ["console"], "level": "INFO", "propagate": False}},
}
```

Keep development tests on the ordinary settings module. This production module reads the Phase 3 PostgreSQL variables for the core application. WhiteNoise serves collected static assets; see [WhiteNoise Django setup](https://whitenoise.readthedocs.io/en/stable/django.html). Review the [Django deployment checklist](https://docs.djangoproject.com/en/5.2/howto/deployment/checklist/) as you configure the actual host/proxy.

The SMTP configuration prevents the development console backend from leaking into production settings. Configure and test actual delivery before adding password reset or email notifications; passing `check --deploy` does not prove email delivery.

The two named warning exceptions document the deliberate initial HSTS scope. Do not silence other deployment warnings. After HTTPS is verified, increase the HSTS duration; enable subdomain coverage/preload only after assessing all affected hosts, then remove the corresponding exceptions.

### 1.3 Create the environment template and local secret file

Create `.env.production.example` with placeholders only:

```dotenv
DJANGO_SETTINGS_MODULE=config.settings_production
DJANGO_SECRET_KEY=REPLACE_WITH_A_GENERATED_SECRET_AT_LEAST_50_CHARACTERS
DJANGO_ALLOWED_HOSTS=inventory.example.com
DJANGO_CSRF_TRUSTED_ORIGINS=https://inventory.example.com
POSTGRES_DB=inventory
POSTGRES_USER=inventory_app
POSTGRES_PASSWORD=REPLACE_WITH_A_DATABASE_SECRET
POSTGRES_HOST=db
POSTGRES_PORT=5432
# Set these when enabling email workflows; verify delivery separately.
# SMTP_HOST=
# SMTP_PORT=587
# SMTP_USER=
# SMTP_PASSWORD=
# SMTP_USE_TLS=true
# DEFAULT_FROM_EMAIL=
```

Use `django_inventory.settings_production` for this checkout. Copy it to ignored `.env.production` and replace placeholders using your secret manager or generated secrets; never run production with the example values. You can generate the Django key with `uv run python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"` in a private terminal.

Merge into `.gitignore`:

```gitignore
.env
.env.*
!.env.example
!.env.database.example
!.env.production.example
staticfiles/
backups/
sqlite-data.json
reset-sequences.sql
```

In PowerShell, copy the example only if `.env.production` does not already exist:

```powershell
if (-not (Test-Path -LiteralPath .env.production)) {
    Copy-Item -LiteralPath .env.production.example -Destination .env.production
}
git check-ignore .env.production
```

Expect `.env.production` from the ignore check. Edit that file privately, set `DJANGO_SETTINGS_MODULE=django_inventory.settings_production`, replace both secret placeholders, and use the local hosts/origin in step 5 for the rehearsal. Keep the example as placeholders. Never paste real environment values into a commit or support log.

Compose's `--env-file` supplies values for `${...}` substitution in the YAML; the web service's `env_file` passes values into its container. Both are needed here. Existing terminal environment variables can override Compose substitutions; use a fresh PowerShell terminal without the Phase 3 `POSTGRES_*` variables when operating this stack. Otherwise the database service and web container may receive different credentials. See [Compose variable interpolation](https://docs.docker.com/compose/how-tos/environment-variables/variable-interpolation/).

## 2. Add a minimal database health endpoint

Create `inventory/health.py`:

```python
from django.db import connection, DatabaseError
from django.http import JsonResponse
from django.views.decorators.http import require_GET


@require_GET
def health(request):
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except DatabaseError:
        return JsonResponse({"status": "unavailable"}, status=503)
    return JsonResponse({"status": "ok"})
```

In `config/urls.py`, import `health` and add `path("health/", health, name="health")` before the browser include. This endpoint returns no users, financial data, credentials, or exception details. HTTPS/host protections still apply. Have the external monitor request `https://YOUR_HOST/health/` and alert on repeated 503/timeouts. Application errors go to stdout; do not log request bodies or authentication headers.

For this checkout, the exact import is `from inventory.health import health` in `django_inventory/urls.py`. Insert the new route immediately before `path("", include("inventory.web_urls"))`; retain the existing API, authentication, and schema routes. Add the test file from step 7 now, so you can check the endpoint before building the container:

```powershell
uv run python manage.py test inventory.test_health
```

Expect two passing tests with development database variables loaded. The production HTTPS path is checked separately in step 5.

## 3. Build the Linux runtime

Create `Dockerfile`:

```dockerfile
ARG PYTHON_VERSION=3.14
FROM python:${PYTHON_VERSION}-slim
COPY --from=ghcr.io/astral-sh/uv:0.12.22 /uv /uvx /bin/
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_LINK_MODE=copy
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project
COPY . .
RUN mkdir -p /app/staticfiles && chown -R 10001:10001 /app
ENV PATH="/app/.venv/bin:$PATH" HOME=/app
USER 10001
EXPOSE 8000
CMD ["sh", "-c", "python manage.py collectstatic --noinput && exec gunicorn config.wsgi:application --bind 0.0.0.0:8000 --workers 2 --access-logfile - --error-logfile -"]
```

Replace `config.wsgi` with `django_inventory.wsgi` here. The image defaults to Python 3.14 to match this checkout's `requires-python`; a Phase 1 project pinned to Python 3.12 can use `--build-arg PYTHON_VERSION=3.12` with its matching lockfile. Use a uv image version available in your registry matching your development tool (`uv --version`); this checkout reports 0.12.22. Pin image digests for a controlled production release. See [uv's container guidance](https://docs.astral.sh/uv/guides/integration/docker/).

The explicit writable `HOME` also lets current Gunicorn versions create their local control socket as the non-root application user.

Create `.dockerignore`:

```dockerignore
.git
.venv
.validation
.idea
.codex
.agents
**/__pycache__
*.pyc
.env*
!.env.production.example
db.sqlite3*
sqlite-data.json
reset-sequences.sql
backups
staticfiles
```

Create `compose.production.yml`:

```yaml
services:
  db:
    image: postgres:17
    environment:
      POSTGRES_DB: ${POSTGRES_DB:?required}
      POSTGRES_USER: ${POSTGRES_USER:?required}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:?required}
    volumes:
      - postgres_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U $$POSTGRES_USER -d $$POSTGRES_DB"]
      interval: 5s
      timeout: 5s
      retries: 12
    restart: unless-stopped
  web:
    build: .
    env_file: .env.production
    ports:
      - "127.0.0.1:8000:8000"
    depends_on:
      db:
        condition: service_healthy
    restart: unless-stopped
volumes:
  postgres_data:
```

PostgreSQL is not exposed publicly; web listens on host loopback for the proxy. This Compose database initializes a local owner role on first boot. For a real production database, have its administrator provision a login/owner with **no superuser/CREATEDB** and inject its connection variables. The test/CI role is separate. Existing volume credentials are not changed by editing environment variables.

Validate the production Compose file before continuing:

```powershell
docker compose --env-file .env.production -f compose.production.yml config --quiet
```

Expect exit code 0 and no output. Use `--quiet` because a full rendered configuration can print secrets. This validates configuration structure/substitution; it does not prove the database, image, or HTTPS connection works.

Use only `compose.production.yml` at this step. Create and validate the HTTPS override in step 5 before starting the local rehearsal.

## 4. Add PostgreSQL-backed CI

Create `.github/workflows/ci.yml` if hosting the repository on GitHub:

```yaml
name: Django checks
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    services:
      postgres:
        image: postgres:17
        env:
          POSTGRES_DB: inventory
          POSTGRES_USER: inventory_app
          POSTGRES_PASSWORD: ci-only-password
        ports: ["5432:5432"]
        options: >-
          --health-cmd "pg_isready -U inventory_app -d inventory"
          --health-interval 5s --health-timeout 5s --health-retries 12
    env:
      POSTGRES_DB: inventory
      POSTGRES_USER: inventory_app
      POSTGRES_PASSWORD: ci-only-password
      POSTGRES_HOST: 127.0.0.1
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v6
        with:
          version: "0.12.22"
          python-version: "3.14"
      - run: uv sync --locked
      - run: uv run python manage.py check
      - run: uv run python manage.py makemigrations --check --dry-run
      - run: uv run python manage.py test
      - run: uv run python manage.py spectacular --file schema.yml --validate
      - name: Check production settings
        env:
          DJANGO_SETTINGS_MODULE: config.settings_production
          DJANGO_SECRET_KEY: ci-only-placeholder-key-with-more-than-fifty-characters-123456789
          DJANGO_ALLOWED_HOSTS: inventory.example.com
          DJANGO_CSRF_TRUSTED_ORIGINS: https://inventory.example.com
        run: uv run python manage.py check --deploy --fail-level WARNING
```

Use this checkout's settings package in CI and match Python/uv versions to the lockfile. The CI database is disposable and its role may create the test database. Pin third-party action commit SHAs in your release policy. A successful CI run must include the Phase 3 concurrency test on PostgreSQL, not a skip.

The production-check step must use `DJANGO_SETTINGS_MODULE: django_inventory.settings_production` in this repository. Its key/password are disposable CI values, never production credentials. After pushing the workflow, inspect the GitHub Actions run: all check, migration-consistency, test, schema, and production-check steps must pass. Running these commands locally does not establish a successful remote workflow. This workflow validates Django; the image build and HTTPS/restore rehearsal remain separate release checks.

## 5. Rehearse release ordering and HTTPS

### Run Caddy locally in Docker

Use a separate local rehearsal database: `compose.production.yml` has its own `postgres_data` volume, separate from Phase 3's `local_postgres_data`. It starts empty; following these steps does not transfer your Phase 3 data. To rehearse with existing data, use the backup/restore process in step 6. Keep the Phase 3 database until you have verified the restore.

For this local rehearsal, set these values in your ignored `.env.production`, keeping your generated Django secret and database password:

```dotenv
DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1
DJANGO_CSRF_TRUSTED_ORIGINS=https://localhost:8443
POSTGRES_HOST=db
POSTGRES_PORT=5432
```

Keep `DJANGO_SETTINGS_MODULE` set to your production settings package. Create `Caddyfile.local`:

```text
localhost:8443 {
    tls internal
    reverse_proxy web:8000
}
```

Create `compose.local-https.yml`, an override used together with `compose.production.yml`:

```yaml
services:
  caddy:
    image: caddy:2
    ports:
      - "127.0.0.1:8443:8443"
    volumes:
      - ./Caddyfile.local:/etc/caddy/Caddyfile:ro
      - caddy_local_data:/data
      - caddy_local_config:/config
    depends_on:
      - web
    restart: unless-stopped
volumes:
  caddy_local_data:
  caddy_local_config:
```

Compose connects these services on one network: Caddy reaches `web:8000`, and Django reaches `db:5432`. `127.0.0.1` inside Caddy would refer to Caddy itself. Your browser uses `https://localhost:8443`; the loopback app port is only for operator access. Commit the two configuration files, keeping private keys and env files out of Git.

Now that `Caddyfile.local` and `compose.local-https.yml` exist, validate the combined configuration before starting services:

```powershell
docker compose --env-file .env.production -f compose.production.yml -f compose.local-https.yml config --quiet
```

Expect exit code 0 and no output. Resolve any missing-file or configuration errors before running the deployment commands below.

With actual `.env.production` values and Docker available:

```sh
docker compose --env-file .env.production -f compose.production.yml build web
docker compose --env-file .env.production -f compose.production.yml up -d db
docker compose --env-file .env.production -f compose.production.yml run --rm web python manage.py migrate --plan
docker compose --env-file .env.production -f compose.production.yml run --rm web python manage.py migrate
docker compose --env-file .env.production -f compose.production.yml run --rm web python manage.py setup_roles
docker compose --env-file .env.production -f compose.production.yml run --rm web python manage.py createsuperuser
docker compose --env-file .env.production -f compose.production.yml run --rm web python manage.py check --deploy --fail-level WARNING
docker compose --env-file .env.production -f compose.production.yml up -d web
```

`createsuperuser` is for a new database only. For a later release: stop incoming writes, take a backup, review the migration plan, apply compatible migrations, run required setup commands, start the new image, verify health/login/stock/report totals, then reopen writes. Do not rerun opening-stock reconciliation as an ordinary deployment step.

Run the commands individually and stop if one fails. Their expected results are:

| Command | Expected result / decision |
| --- | --- |
| `build web` | Locked dependencies install and the Linux image finishes building |
| `up -d db` | Database starts; check its health before proceeding |
| `migrate --plan` | Only the committed migrations expected for this database appear |
| `migrate` | Pending migrations apply successfully |
| `setup_roles` | The five business groups and permissions are provisioned |
| `createsuperuser` | A local administrator is created interactively for a new database |
| `check --deploy --fail-level WARNING` | No unsilenced deployment warnings/errors |
| `up -d web` | Gunicorn starts after static collection; confirm with logs below |

If reusing restored data, inspect existing users before deciding whether to create an administrator. `setup_roles` defines groups; it does not automatically assign normal users to them.

Start Caddy after those migrations and setup commands:

```sh
docker compose --env-file .env.production -f compose.production.yml -f compose.local-https.yml up -d caddy
docker compose --env-file .env.production -f compose.production.yml -f compose.local-https.yml ps
docker compose --env-file .env.production -f compose.production.yml -f compose.local-https.yml logs --tail 50 caddy web
```

Expect `db` healthy and `web`/`caddy` running. Create the ignored backup directory, then export Caddy's public root certificate after its first start. In PowerShell, run:

```powershell
New-Item -ItemType Directory -Force -Path backups
docker compose --env-file .env.production -f compose.production.yml -f compose.local-https.yml cp caddy:/data/caddy/pki/authorities/local/root.crt backups/caddy-local-root.crt
curl.exe --cacert backups/caddy-local-root.crt https://localhost:8443/health/
```

In Bash, use `mkdir -p backups` and `curl` instead. Expect HTTP 200 with `{"status":"ok"}`. This verifies the proxy, production app, and database together without disabling TLS verification.

If Windows curl reports that the revocation status is unknown for Caddy's private local certificate, use this command for the local rehearsal. It keeps certificate authority and hostname verification enabled while disabling the revocation lookup for this request:

```powershell
curl.exe --cacert backups/caddy-local-root.crt --ssl-no-revoke https://localhost:8443/health/
```

Open **https://localhost:8443/accounts/login/** and sign in with the superuser you created. Caddy's internal CA is not automatically trusted by your host browser. For a warning-free browser rehearsal, import that public root certificate into your browser/OS trusted roots through its certificate settings and remove it when the rehearsal ends; only trust the CA you created. Keep Caddy's private keys inside its named volume. Check the dashboard and CSS, receive goods, record a sale, and compare history/report totals.

### Verify a complete browser workflow

Use a new rehearsal product so the expected balances are unambiguous:

1. Confirm the login page and dashboard have their CSS with debug disabled. Check browser network requests for missing static assets.
2. Create a product with selling price 40.00 and zero initial stock.
3. Receive 10 units at acquisition cost 20.00, then 10 at 30.00. Expect stock 20, inventory value 500.000000, and average unit cost 25.000000.
4. Sell 4 units at 40.00. Expect stock 16, inventory value 400.000000, revenue 160.00, COGS 100.000000, and gross profit 60.000000 for that sale.
5. Attempt to sell 17 units. Expect validation failure and unchanged stock/value/history. Check transaction history and the sales/valuation reports against the successful movements.
6. Assign a separate active user to Viewer in Admin. In a separate browser session, confirm permitted stock pages work and cost/profit data, posting actions, and forbidden exports remain blocked.
7. Log out and confirm protected pages require login again. Check the session cookie has the Secure flag while logged in.

Use the configured currency; these numbers are arithmetic examples, not a currency conversion. Record observed results, image identifier, and date in your runbook. These manual checks complement the automated suite.

### Troubleshoot the rehearsal

| Symptom | Check and correction |
| --- | --- |
| `KeyError` for a Django/PostgreSQL variable | Verify the variable exists in the container environment file and the settings package name is correct |
| Compose reports a missing variable | Pass `--env-file .env.production` and replace required placeholders |
| Database authentication fails | Check shell overrides and existing volume credentials; changing the file does not reset an initialized database password |
| Browser gets HTTP 400 | Use a hostname in `DJANGO_ALLOWED_HOSTS`; entries contain no scheme or port |
| Form submission gets CSRF 403 | Include the exact HTTPS origin, including `:8443` locally, in trusted origins; verify forwarded scheme and secure cookies |
| Repeated HTTPS redirects | Check the proxy forwards the HTTPS scheme and Django trusts the configured header |
| Caddy returns 502 | Check web logs for settings/import/static/database failures and confirm Gunicorn is listening on container port 8000 |
| Health returns 503 | Check database availability/credentials; health deliberately hides exception details |
| Certificate is untrusted | Use the exported public CA with `curl.exe --cacert`; use the documented trust process for the browser |
| Dashboard CSS is missing | Check `collectstatic` output, WhiteNoise middleware order, static source directories, and manifest configuration |

Do not erase a database volume to fix a configuration error. Inspect the service logs, correct the cause, and restart the affected service. Avoid sharing logs containing credentials or tokens.

Stop the rehearsal with:

```sh
docker compose --env-file .env.production -f compose.production.yml -f compose.local-https.yml stop
```

Restart with the same combined files and `up -d`. Always include both files when managing the complete local stack. Named volumes retain database data and the local CA; `down --volumes` erases them.

### Move from local rehearsal to a public host

Install a reverse proxy on the host, configure DNS for your real hostname, and use HTTPS. For Caddy, a minimal `Caddyfile` is:

```text
inventory.example.com {
    reverse_proxy 127.0.0.1:8000
}
```

Replace the hostname, ensure ports 80/443 reach the proxy, and confirm it overwrites forwarded scheme headers. The loopback-only app port keeps clients from directly spoofing those headers. An HTTP request to the app will redirect to HTTPS by design. For a local HTTPS rehearsal, use a local proxy/certificate and matching allowed hosts/trusted origins; do not disable production protections just to make an HTTP curl succeed.

Check `/health/`, local login, one receipt/sale, protected history, static CSS, schema docs, and role-specific exports. If adding [optional Google sign-in](integrations/google_authentication.md), configure its production HTTPS callback and separate secrets, then verify the real provider round trip. Rate-limit local/JWT login at the proxy or an application login-throttling layer before public exposure. No reset-email flow is claimed; configure delivery/templates before adding password reset.

## 6. Back up and restore into a separate database

Use PostgreSQL client tools installed on the operator machine. Configure a PostgreSQL password file/secret mechanism and connection variables outside Git. Do not use binary `pg_dump` shell redirection in Windows PowerShell; `--file` preserves the archive bytes.

```sh
pg_dump --host YOUR_DB_HOST --username YOUR_DB_USER --dbname inventory --format custom --file inventory-backup.dump
createdb --host YOUR_RESTORE_HOST --username YOUR_RESTORE_ADMIN inventory_restore
pg_restore --host YOUR_RESTORE_HOST --username YOUR_RESTORE_ADMIN --dbname inventory_restore --no-owner --no-acl inventory-backup.dump
```

Restore to a separate database/server, never over the live inventory during a rehearsal. Start an isolated application instance with `POSTGRES_DB=inventory_restore`, separate secrets/provider settings, and no live traffic. Verify user counts, product balances, movement counts, references, and sums of `value_change` against product `inventory_value`. For each reconciled product, movement direction quantities should equal current stock. Revenue/COGS/profit must match recorded sale snapshots.

Store encrypted backups outside the database host with a defined retention policy (for example daily backups retained 30 days) and restrict access: they contain identity/password hashes and financial records. A backup is only useful after a tested restore. Do not commit `.dump` files.

### Back up the local Compose database without installing Windows client tools

For the local rehearsal, use the PostgreSQL utilities already inside the database container. These commands save the custom archive in the container, then copy it out without binary shell redirection:

```powershell
New-Item -ItemType Directory -Force backups
docker compose --env-file .env.production -f compose.production.yml exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --format=custom --file=/tmp/inventory-rehearsal.dump'
docker compose --env-file .env.production -f compose.production.yml cp db:/tmp/inventory-rehearsal.dump backups/inventory-rehearsal.dump
docker compose --env-file .env.production -f compose.production.yml exec -T db sh -c 'createdb -U "$POSTGRES_USER" inventory_restore'
docker compose --env-file .env.production -f compose.production.yml exec -T db sh -c 'pg_restore -U "$POSTGRES_USER" --dbname=inventory_restore --no-owner --no-acl --exit-on-error /tmp/inventory-rehearsal.dump'
```

Use a new restore database name for each repeat; `createdb` should fail if that name already exists. The quoted shell variables above are expanded inside the Linux container. This example uses the disposable Compose owner role and local container authentication; follow your database administrator's credential/access process on a production host. PostgreSQL documents custom archives and `--file` in [pg_dump](https://www.postgresql.org/docs/17/app-pgdump.html).

To test a fresh app connection to the restored database without redirecting the running web service:

```powershell
docker compose --env-file .env.production -f compose.production.yml run --rm -e POSTGRES_DB=inventory_restore web python manage.py showmigrations
docker compose --env-file .env.production -f compose.production.yml run --rm -e POSTGRES_DB=inventory_restore web python manage.py shell
```

In that isolated shell, inspect Category/Product/StockTransaction counts and compare product quantities/values and sale snapshots with the pre-backup records. Counts alone do not prove financial consistency. Exit the shell afterward. Do not run the Django test suite against the restored dataset as a replacement for reconciliation; tests create their own test database.

Schedule daily expired-refresh cleanup using the hosting scheduler:

```sh
docker compose --env-file .env.production -f compose.production.yml run --rm web python manage.py flushexpiredtokens
```

Record the scheduler, backup destination, retention, monitoring contact, release/image identifier, and last restore rehearsal in your operations runbook. Do not send secrets/tokens in alerts.

Also schedule `python manage.py clearsessions` for expired database sessions. Define an acceptable amount of data loss and recovery time, then choose backup frequency and rehearse restoration against those targets. A daily backup can lose up to roughly a day's writes; choose more frequent backups or PostgreSQL point-in-time recovery when that is unacceptable. Monitor backup job failures and external `/health/` failures, and verify alerts reach the responsible operator.

## 7. Add a focused health test and verify release readiness

Create `inventory/test_health.py`:

```python
from unittest.mock import patch
from django.db import DatabaseError
from django.test import TestCase
from django.urls import reverse


class HealthTests(TestCase):
    def test_database_available(self):
        response = self.client.get(reverse("health"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})

    def test_database_failure_has_no_details(self):
        with patch("inventory.health.connection.cursor", side_effect=DatabaseError("secret connection details")):
            response = self.client.get(reverse("health"))
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {"status": "unavailable"})
```

```sh
uv run python manage.py test
uv run python manage.py check
uv run python manage.py makemigrations --check --dry-run
```

Production verification runs inside the image with real deployment variables; ordinary local settings cannot establish deployment readiness. If migration rollback is incompatible, restore the verified backup and previous image during a planned outage, accepting/documenting any post-backup data loss. Never assume switching the image also reverses schema/data migrations.

## 8. Review changed files

Review the diff before committing. Confirm production settings select PostgreSQL, runtime paths use `django_inventory`, migrations are committed, and real secrets/backups remain ignored. The guide's file list below uses the tutorial package name; use the equivalent paths in this checkout.

```text
config/settings.py + settings_production.py
config/urls.py                           health route
inventory/health.py + test_health.py
Dockerfile + .dockerignore + compose.production.yml
Caddyfile.local + compose.local-https.yml  local HTTPS rehearsal
.github/workflows/ci.yml
.env.production.example + .gitignore
pyproject.toml + uv.lock
```

Commit templates/configuration/code, not production secrets. Record the deployment commands and restore procedure in README after completing the rehearsal. Add a license before promising reuse terms. Return to [README](../README.md) and [roadmap](ROADMAP.md).

### Completion checklist

- [ ] Run the application suite and health tests on PostgreSQL, including the concurrency test.
- [ ] Production settings pass deployment checks and static files collect successfully.
- [ ] Linux image starts as the configured non-root user.
- [ ] Local HTTPS health, login, stock workflow, role restrictions, and reports pass.
- [ ] Backup restores to a separate database and balances/sale snapshots reconcile.
- [ ] GitHub CI passes remotely when that workflow is in use.
- [ ] The public host has valid DNS/TLS, appropriate database privileges, login rate limiting, working alerts, and scheduled backups/cleanup before release.
- [ ] The runbook records the release, restore result, recovery targets, and rollback procedure.

Review the [Django deployment checklist](https://docs.djangoproject.com/en/6.1/howto/deployment/checklist/).
