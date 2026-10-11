# 08 — Deployment and release readiness

**Status: implementation plan.** Prerequisite: tested application features. CI, tests, and secret hygiene should begin earlier; this phase completes operational preparation.

## 1. Separate production settings

Read secrets and connection credentials from the environment. Disable DEBUG, configure allowed hosts/trusted origins, and configure HTTPS, secure cookies, logging, and email where used. Document required variables in an example configuration without live secrets.

**Check:** missing production secrets fail clearly and development credentials are not deployed.

## 2. Package the runtime

Use the committed uv lockfile, a supported production WSGI/ASGI server, PostgreSQL, and configured static-file serving. Choose hosting/container details during implementation; Django runserver is not the production server.

**Check:** a fresh environment can install dependencies and start the application using documented commands.

## 3. Prepare database releases

Review migration impact and backups before applying changes. Document deployment ordering and recovery when a migration is incompatible with an older app release. Avoid modifying historical stock data as an incidental deployment step.

**Check:** migrations work against a representative database and recovery steps are explicit.

## 4. Automate verification

CI runs Django checks, migration consistency, application tests, and PostgreSQL-backed transaction/concurrency tests. Add production configuration checks using `manage.py check --deploy` with the intended settings.

**Check:** failures prevent a release and checks exercise the actual database backend.

## 5. Add operational visibility

Provide health checks, request/error logging without secrets, and actionable failure monitoring. Schedule expired refresh-token cleanup when blacklisting is enabled. Define database backup retention and test restoring a backup into a separate environment.

**Check:** restored users, stock balances, movement history, and valuation reconcile.

## 6. Finalize release documentation

Document deployment, migration, first-administrator setup, backup/restore, auth-provider configuration, and known limitations. Update README status only after verification. Add a license before claiming reuse terms.

**Deliverable:** reproducible deployment, passing CI, tested restore, and accurate operational documentation.

Return to [README](../README.md) or [roadmap](ROADMAP.md).
