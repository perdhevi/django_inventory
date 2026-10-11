# 04 — Accounts, business roles, and JWT

**Status: implementation plan.** Prerequisite: Phase 3. Preserve the existing user records and Django default user model.

## 1. Organize account behavior

Create an `accounts` app and register it. Use `get_user_model()` and `settings.AUTH_USER_MODEL` when referencing users. Add account behavior without silently replacing the user model. Access remains administrator-approved or invitation-based; public signup is not part of the base scope.

**Check:** existing users and stock actors remain valid.

## 2. Establish groups and permissions

Create Viewer, Sales, Procurement, Inventory manager, and Administrator groups through a repeatable setup command or migration. Implement permissions for sales, procurement receipts, adjustments, opening balances, sales reports, procurement reports, valuation, and role administration.

Use the matrix in [architecture](00_architecture.md#roles-and-permissions). Multiple groups combine permissions. Application roles do not automatically set `is_staff` or `is_superuser`.

**Check:** group initialization is repeatable and ordinary business users do not gain Admin access.

## 3. Enforce operation and data access

Replace broad `IsAdminUser` access with explicit DRF permission checks. Enforce capability checks in the stock service too. Filter transaction querysets and restrict serializer fields according to the role.

Sales sees sales revenue but no COGS/profit; Procurement sees procurement costs; Viewer sees movement quantities without restricted financial fields. Inventory manager and Administrator can see valuation/profit. Apply the same rules to totals, exports, and detail endpoints.

**Check:** knowing a forbidden record ID cannot bypass list filtering, and restricted fields never appear in responses.

## 4. Configure JWT

```sh
uv add djangorestframework-simplejwt
```

Configure JWT authentication, token obtain/refresh routes, short access-token lifetime, refresh rotation, and blacklist support. Apply the blacklist app migrations and arrange expired-token cleanup. Keep Basic authentication confined to the learning configuration if retained. Web/Admin session authentication remains available.

Never embed role claims as the sole authorization source; resolve current user permissions when serving requests.

**Check:** expired/invalid tokens fail and changed roles take effect without relying on stale JWT permission claims.

## 5. Add account endpoints

Planned routes: `POST /api/auth/token/`, `POST /api/auth/token/refresh/`, `POST /api/auth/logout/`, and `GET /api/accounts/me/`. The current-user response exposes approved identity fields and capabilities. Role changes require explicit administrator permission and must prevent unauthorized privilege escalation.

Logout blacklists the refresh token; an existing access token normally remains usable until expiry. Document that behavior.

**Check:** inactive users cannot log in or use the protected API; revoked refresh tokens cannot obtain new access tokens.

## 6. Verify the permission matrix

Test every role against allowed/forbidden operations, combined groups, financial field visibility, transaction detail access, changed permissions, inactive users, login/refresh/logout, and account administration. Include real token authentication tests rather than relying only on forced authentication.

**Deliverable:** account organization, repeatable groups, shared permission enforcement, JWT endpoints, and passing role/security tests.

Next: [Phase 5](05_web_interface.md). Return to [README](../README.md).
