# 08 — Package, verify, and deploy the application

Continue from [Phase 7](07_google_authentication.md), or Phase 6 with Google disabled. You will add production settings, a Linux container, PostgreSQL CI, health checks, and backup/restore instructions. This walkthrough chooses Docker Compose behind an HTTPS reverse proxy. Complete a local/staging rehearsal before publishing a production service.

Use the package-name substitution from Phase 3. Commands below use `config.settings_production` and `config.wsgi`; this checkout needs `django_inventory.settings_production` and `django_inventory.wsgi` instead.

## 1. Separate development and production configuration

```sh
uv add gunicorn whitenoise
```

In the existing `config/settings.py`, replace the hardcoded `SECRET_KEY`, `DEBUG`, and `ALLOWED_HOSTS` assignments:

```python
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "local-learning-only-do-not-deploy")
DEBUG = os.environ.get("DJANGO_DEBUG", "true").lower() == "true"
ALLOWED_HOSTS = os.environ.get("DJANGO_ALLOWED_HOSTS", "127.0.0.1,localhost").split(",")
```

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

Keep development tests on the ordinary settings module. This production module reads the Phase 3 PostgreSQL variables and Phase 7 optional OAuth variables. WhiteNoise serves collected static assets; see [WhiteNoise Django setup](https://whitenoise.readthedocs.io/en/stable/django.html). Review the [Django deployment checklist](https://docs.djangoproject.com/en/5.2/howto/deployment/checklist/) as you configure the actual host/proxy.

The SMTP configuration prevents the development console backend from leaking into production settings. Configure and test actual delivery before adding password reset or email notifications; passing `check --deploy` does not prove email delivery.

The two named warning exceptions document the deliberate initial HSTS scope. Do not silence other deployment warnings. After HTTPS is verified, increase the HSTS duration; enable subdomain coverage/preload only after assessing all affected hosts, then remove the corresponding exceptions.

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
GOOGLE_LOGIN_ENABLED=false
# GOOGLE_CLIENT_ID=
# GOOGLE_CLIENT_SECRET=
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
      GOOGLE_LOGIN_ENABLED: "false"
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

## 5. Rehearse release ordering and HTTPS

### Run Caddy locally in Docker

Use a separate local rehearsal database: `compose.production.yml` has its own `postgres_data` volume, separate from Phase 3's `local_postgres_data`. It starts empty; following these steps does not transfer your Phase 3 data. To rehearse with existing data, use the backup/restore process in step 6. Keep the Phase 3 database until you have verified the restore.

For this local rehearsal, set these values in your ignored `.env.production`, keeping your generated Django secret and database password:

```dotenv
DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1
DJANGO_CSRF_TRUSTED_ORIGINS=https://localhost:8443
POSTGRES_HOST=db
POSTGRES_PORT=5432
GOOGLE_LOGIN_ENABLED=false
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

Start Caddy after those migrations and setup commands:

```sh
docker compose --env-file .env.production -f compose.production.yml -f compose.local-https.yml up -d caddy
docker compose --env-file .env.production -f compose.production.yml -f compose.local-https.yml ps
docker compose --env-file .env.production -f compose.production.yml -f compose.local-https.yml logs --tail 50 caddy web
```

Expect `db` healthy and `web`/`caddy` running. Export Caddy's public root certificate to an ignored directory after its first start:

```sh
docker compose --env-file .env.production -f compose.production.yml -f compose.local-https.yml cp caddy:/data/caddy/pki/authorities/local/root.crt backups/caddy-local-root.crt
curl --cacert backups/caddy-local-root.crt https://localhost:8443/health/
```

Create `backups` first (`New-Item -ItemType Directory -Force backups` in PowerShell, or `mkdir -p backups` in Bash). On Windows use `curl.exe` to avoid the older PowerShell alias. Expect HTTP 200 with `{"status":"ok"}`. This verifies the proxy, production app, and database together without disabling TLS verification.

Open **https://localhost:8443/accounts/login/** and sign in with the superuser you created. Caddy's internal CA is not automatically trusted by your host browser. For a warning-free browser rehearsal, import that public root certificate into your browser/OS trusted roots through its certificate settings and remove it when the rehearsal ends; only trust the CA you created. Keep Caddy's private keys inside its named volume. Check the dashboard and CSS, receive goods, record a sale, and compare history/report totals. Google stays disabled until the separate provider round trip.

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

Check `/health/`, local login, one receipt/sale, protected history, static CSS, schema docs, and role-specific exports. Enable Google only after setting its production HTTPS callback and separate secrets. Rate-limit local/JWT login at the proxy or an application login-throttling layer before public exposure. No reset-email flow is claimed; configure delivery/templates before adding password reset.

## 6. Back up and restore into a separate database

Use PostgreSQL client tools installed on the operator machine. Configure a PostgreSQL password file/secret mechanism and connection variables outside Git. Do not use binary `pg_dump` shell redirection in Windows PowerShell; `--file` preserves the archive bytes.

```sh
pg_dump --host YOUR_DB_HOST --username YOUR_DB_USER --dbname inventory --format custom --file inventory-backup.dump
createdb --host YOUR_RESTORE_HOST --username YOUR_RESTORE_ADMIN inventory_restore
pg_restore --host YOUR_RESTORE_HOST --username YOUR_RESTORE_ADMIN --dbname inventory_restore --no-owner --no-acl inventory-backup.dump
```

Restore to a separate database/server, never over the live inventory during a rehearsal. Start an isolated application instance with `POSTGRES_DB=inventory_restore`, separate secrets/provider settings, and no live traffic. Verify user counts, product balances, movement counts, references, and sums of `value_change` against product `inventory_value`. For each reconciled product, movement direction quantities should equal current stock. Revenue/COGS/profit must match recorded sale snapshots.

Store encrypted backups outside the database host with a defined retention policy (for example daily backups retained 30 days) and restrict access: they contain identity/password hashes and financial records. A backup is only useful after a tested restore. Do not commit `.dump` files.

Schedule daily expired-refresh cleanup using the hosting scheduler:

```sh
docker compose --env-file .env.production -f compose.production.yml run --rm web python manage.py flushexpiredtokens
```

Record the scheduler, backup destination, retention, monitoring contact, release/image identifier, and last restore rehearsal in your operations runbook. Do not send secrets/tokens in alerts.

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

Commit templates/configuration/code, not production secrets. Update README implementation status only after CI, staging workflow, provider round trip (if enabled), and restore rehearsal pass. Add a license before promising reuse terms. Return to [README](../README.md) and [roadmap](ROADMAP.md).

See [the actual build validation](VALIDATION.md) for the tested versions, local runtime/restore results, and checks that still require external services.
