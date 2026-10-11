# 07 — Google sign-in and account linking

**Status: implementation plan.** Prerequisite: established Phase 4 accounts/permissions and Phase 5 pages. Google sign-in is optional and can be disabled.

## 1. Configure the provider

Integrate django-allauth with social-account support. Register a Google OAuth client, configure the consent screen and exact callback URLs, and keep client secrets in environment configuration. Separate development and production configuration. Consult the current [Google provider guide](https://docs.allauth.org/en/latest/socialaccount/providers/google.html) during implementation.

**Check:** password login continues working when Google is disabled or unconfigured.

## 2. Preserve one local identity

Map the provider's stable account identifier to a local Django user. Do not use a changeable email as the only external identity key. Add an authenticated account-linking flow and explicit conflict handling; do not silently merge accounts by matching email.

**Check:** linking preserves the existing user's roles and stock transaction history.

## 3. Preserve approval and authorization

Successful Google authentication does not grant inventory access. Retain invitation/administrator approval, inactive-account rejection, and the existing permission matrix. Request only identity scopes needed for sign-in.

**Check:** unapproved users cannot reach inventory data and Google sign-in cannot grant staff/superuser flags.

## 4. Support web and API clients

For browser pages, complete the validated provider flow and establish a Django session. For API clients, validate the provider result through a supported flow, resolve the approved local user, and issue our own application JWT. Do not accept Google API access tokens as inventory API bearer tokens.

Specify the API client's redirect/exchange contract during implementation. Keep JWTs out of redirect query strings and do not log credentials/tokens.

**Check:** password and Google users receive identical access for identical roles.

## 5. Test linking and recovery

Cover state/callback validation, provider failures, invalid identity results, account conflicts, disabled users, approvals, linking/unlinking, and role persistence. Prevent unlinking the last usable login method without establishing another recovery path.

**Deliverable:** optional Google sign-in, safe account linking, web/API authentication flows, and setup instructions with tested access rules.

Next: [Phase 8](08_deployment.md). Return to [README](../README.md).
