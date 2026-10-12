# Optional integration — Google sign-in and explicit account linking

Prerequisite: complete [Phase 6](../06_reports_usability.md). This external integration is optional and is not required for [core deployment](../07_deployment.md). You will add Google as another login method for an already-approved local account. Password login, existing users, stock actors, and groups remain intact. A Google email match never silently merges accounts.

## 1. Understand the identity flow

```text
Approved local user signs in with password
  -> connects Google using a CSRF-protected OAuth flow
  -> allauth saves provider + stable Google account ID -> local user
Later Google login -> same local user -> same roles -> Django session
Session-authenticated POST -> our JWT pair -> existing inventory API
```

The API flow here is for a same-origin browser client: complete Google's browser flow, then exchange the resulting session for our own JWT. Native/mobile clients need a separate supported headless flow and redirect contract; do not invent a raw Google-token acceptance endpoint.

## 2. Install and configure optional allauth

```sh
uv add "django-allauth[socialaccount]"
```

Add to `INSTALLED_APPS` in `config/settings.py`:

```python
INSTALLED_APPS += [
    "allauth", "allauth.account", "allauth.socialaccount",
    "allauth.socialaccount.providers.google",
]
```

After Django's authentication middleware, add `allauth.account.middleware.AccountMiddleware` to `MIDDLEWARE`. Keep the existing request context processor. Merge these settings:

```python
AUTHENTICATION_BACKENDS = [
    "django.contrib.auth.backends.ModelBackend",
    "allauth.account.auth_backends.AuthenticationBackend",
]
ACCOUNT_LOGIN_METHODS = {"username"}
ACCOUNT_SIGNUP_FIELDS = ["username*", "password1*", "password2*", "email"]
ACCOUNT_EMAIL_VERIFICATION = "none"
ACCOUNT_ADAPTER = "accounts.adapters.ClosedAccountAdapter"
SOCIALACCOUNT_ADAPTER = "accounts.adapters.ApprovedSocialAdapter"
SOCIALACCOUNT_EMAIL_AUTHENTICATION = False
SOCIALACCOUNT_EMAIL_AUTHENTICATION_AUTO_CONNECT = False
SOCIALACCOUNT_LOGIN_ON_GET = False
SOCIALACCOUNT_STORE_TOKENS = False
GOOGLE_LOGIN_ENABLED = os.environ.get("GOOGLE_LOGIN_ENABLED", "false").lower() == "true"
if GOOGLE_LOGIN_ENABLED:
    SOCIALACCOUNT_PROVIDERS = {
        "google": {
            "APPS": [{"client_id": os.environ["GOOGLE_CLIENT_ID"],
                      "secret": os.environ["GOOGLE_CLIENT_SECRET"], "key": ""}],
            "SCOPE": ["profile", "email"],
            "AUTH_PARAMS": {"access_type": "online"},
            "OAUTH_PKCE_ENABLED": True,
        }
    }
```

Do not also create a Google `SocialApp` in Admin when using environment-based `APPS`: duplicate provider configurations can conflict. The retained ModelBackend supports the existing local learning login; production login rate limiting must cover it and the JWT login endpoint. Provider setup follows [allauth installation](https://docs.allauth.org/en/latest/installation/quickstart.html) and [Google configuration](https://docs.allauth.org/en/latest/socialaccount/providers/google.html).

## 3. Enforce approval, explicit linking, and recovery

Create `accounts/adapters.py`:

```python
from allauth.account.adapter import DefaultAccountAdapter
from allauth.core.exceptions import ImmediateHttpResponse
from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from django.core.exceptions import ValidationError
from django.http import HttpResponseForbidden


def approved(user):
    return bool(user.is_authenticated and user.is_active and user.has_perm("inventory.view_product"))


class ClosedAccountAdapter(DefaultAccountAdapter):
    def is_open_for_signup(self, request):
        return False


class ApprovedSocialAdapter(DefaultSocialAccountAdapter):
    def is_open_for_signup(self, request, sociallogin):
        return False

    def pre_social_login(self, request, sociallogin):
        if sociallogin.state.get("process") == "connect":
            if not approved(request.user):
                raise ImmediateHttpResponse(HttpResponseForbidden("Sign in to an approved account before linking."))
            if sociallogin.is_existing and sociallogin.user.pk != request.user.pk:
                raise ImmediateHttpResponse(HttpResponseForbidden("Google identity is linked to another account."))
            return
        if not sociallogin.is_existing or not approved(sociallogin.user):
            raise ImmediateHttpResponse(HttpResponseForbidden("Ask an administrator for a local account, then link Google."))

    def validate_disconnect(self, account, accounts):
        super().validate_disconnect(account, accounts)
        other_logins = [item for item in accounts if item.pk != account.pk]
        if not account.user.has_usable_password() and not other_logins:
            raise ValidationError("Set a local password before removing your last login method.")
```

Allauth validates the OAuth state/code and stores the stable provider UID. Our adapter controls local approval and conflict handling, without assigning groups/staff flags. See [allauth adapter hooks](https://docs.allauth.org/en/latest/socialaccount/adapter.html).

Keep `GOOGLE_LOGIN_ENABLED=false` while adding code; password login should still work. Run:

```sh
uv run python manage.py migrate
uv run python manage.py check
```

## 4. Register optional URLs and login/link buttons

In `config/urls.py`, import `settings` from `django.conf`. Register allauth only when enabled, using a separate prefix so Phase 5's route names are unchanged:

```python
if settings.GOOGLE_LOGIN_ENABLED:
    urlpatterns = [path("identity/", include("allauth.urls"))] + urlpatterns
```

Create `accounts/context_processors.py`:

```python
from django.conf import settings


def google_login(request):
    return {"google_login_enabled": settings.GOOGLE_LOGIN_ENABLED}
```

Append `accounts.context_processors.google_login` to `TEMPLATES[0]["OPTIONS"]["context_processors"]`.

In `templates/registration/login.html`, add after the password form, inside the content block:

```html
{% if google_login_enabled %}
{% load socialaccount %}
<form method="post" action="{% provider_login_url 'google' process='login' %}">
  {% csrf_token %}<button>Sign in with Google</button>
</form>
<p>First sign in with your approved local account to connect Google.</p>
{% endif %}
```

Inside `base.html`'s authenticated navigation, add:

```html
{% if google_login_enabled %}
{% load socialaccount %}
<form method="post" action="{% provider_login_url 'google' process='connect' %}">
  {% csrf_token %}<button>Connect Google</button>
</form>
<a href="{% url 'socialaccount_connections' %}">Connected accounts</a>
{% endif %}
```

Allauth supplies connection and error templates. Their visual styling can be customized later; login/link/error handling works without copying provider templates. Disconnect stays POST-based and uses the adapter's recovery check.

## 5. Configure the Google OAuth client

In the Google Cloud console, create/select your project, configure Google Auth Platform branding/audience and test users, then create an OAuth client of type **Web application**. For the local walkthrough use:

| Field | Value |
| --- | --- |
| Authorized JavaScript origin, if requested | `http://127.0.0.1:8000` |
| Authorized redirect URI | `http://127.0.0.1:8000/identity/google/login/callback/` |

Use exactly the same host throughout (`localhost` and `127.0.0.1` are different). Follow [Google's web-server OAuth setup](https://developers.google.com/identity/protocols/oauth2/web-server) for console changes. Keep testing access restricted to your selected test accounts.

Set PowerShell variables in the server terminal:

```powershell
$env:GOOGLE_LOGIN_ENABLED = "true"
$env:GOOGLE_CLIENT_ID = Read-Host "Google client ID"
$env:GOOGLE_CLIENT_SECRET = Read-Host "Google client secret"
```

Bash/Zsh users can `export` the same names. Restart `runserver`. Sign in locally as an approved user, click **Connect Google**, complete consent, log out, then use **Sign in with Google**. Verify the local user ID/groups are unchanged. An unlinked Google identity must receive the approval/link message, even if its email matches a local user.

Production uses a separate OAuth client and HTTPS callback. Keep provider secrets out of Git and logs.

## 6. Exchange a validated session for application JWTs

Append to `accounts/views.py` (merge imports):

```python
from django.core.exceptions import PermissionDenied
from rest_framework.authentication import SessionAuthentication
from rest_framework.permissions import IsAuthenticated
from rest_framework_simplejwt.tokens import RefreshToken
from drf_spectacular.utils import extend_schema, OpenApiTypes


class SessionTokenView(APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticated]

    @extend_schema(request=None, responses=OpenApiTypes.OBJECT)
    def post(self, request):
        if not request.user.is_active or not request.user.has_perm("inventory.view_product"):
            raise PermissionDenied("An approved inventory account is required.")
        refresh = RefreshToken.for_user(request.user)
        response = Response({"refresh": str(refresh), "access": str(refresh.access_token)})
        response["Cache-Control"] = "no-store"
        return response
```

Import it in `accounts/urls.py` and add:

```python
path("auth/session-token/", SessionTokenView.as_view(), name="session-token"),
```

This route intentionally accepts session authentication only: authenticated POSTs require CSRF. A linked user's password session may use it too; permissions are identical regardless of login method. Tokens appear only in the response body, never redirect URLs.

To try it, while signed in open the browser developer console on a page containing a CSRF form and run:

```javascript
const csrf = document.querySelector('[name=csrfmiddlewaretoken]').value;
const response = await fetch('/api/auth/session-token/', {
  method: 'POST', credentials: 'same-origin', headers: {'X-CSRFToken': csrf}
});
const tokens = await response.json();
const products = await fetch('/api/products/', {
  headers: {'Authorization': `Bearer ${tokens.access}`}
});
console.log(products.status);
```

Expect 200. Keep tokens in memory; do not paste them into URLs or commit/log them. Without CSRF expect 403. This demonstrates the browser API contract without adding a separate token-storage UI.

## 7. Add local tests and exercise the actual provider

Create `accounts/test_google.py`:

```python
from types import SimpleNamespace

from allauth.core.exceptions import ImmediateHttpResponse
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser, Group
from django.core.management import call_command
from django.test import Client, RequestFactory, TestCase
from django.urls import reverse

from .adapters import ApprovedSocialAdapter


class GoogleAccessTests(TestCase):
    def setUp(self):
        call_command("setup_roles", verbosity=0)
        self.user = get_user_model().objects.create_user(username="google-demo", password="test-password")
        self.user.groups.add(Group.objects.get(name="Sales"))
        self.request = RequestFactory().get("/")
        self.request.user = AnonymousUser()
        self.adapter = ApprovedSocialAdapter()

    def test_unlinked_identity_is_not_merged(self):
        login = SimpleNamespace(state={}, is_existing=False, user=self.user)
        with self.assertRaises(ImmediateHttpResponse):
            self.adapter.pre_social_login(self.request, login)

    def test_linked_active_user_preserves_roles_and_inactive_fails(self):
        login = SimpleNamespace(state={}, is_existing=True, user=self.user)
        self.adapter.pre_social_login(self.request, login)
        self.assertEqual(list(self.user.groups.values_list("name", flat=True)), ["Sales"])
        self.user.is_active = False
        with self.assertRaises(ImmediateHttpResponse):
            self.adapter.pre_social_login(self.request, login)

    def test_session_exchange_requires_csrf(self):
        strict = Client(enforce_csrf_checks=True)
        strict.force_login(self.user, backend="django.contrib.auth.backends.ModelBackend")
        self.assertEqual(strict.post(reverse("session-token")).status_code, 403)
        strict.get(reverse("dashboard"))  # base.html's logout form sets the CSRF cookie
        token = strict.cookies["csrftoken"].value
        response = strict.post(reverse("session-token"), HTTP_X_CSRFTOKEN=token)
        self.assertEqual(response.status_code, 200)
        self.assertIn("access", response.json())
        self.assertEqual(response["Cache-Control"], "no-store")
```

```sh
uv run python manage.py test
uv run python manage.py check
uv run python manage.py makemigrations --check --dry-run
```

These tests verify our approval/session policy; they do not simulate Google's cryptography or validate a real callback. With the configured test OAuth client, verify connect/login, rejected unlinked users, linking conflicts, cancelled consent, invalid callback/state, disabled accounts, and unlinking recovery. Disable `GOOGLE_LOGIN_ENABLED`, restart, and verify password login and existing API JWTs still work. Do not mark this integration complete until the real provider round trip succeeds.

## 8. Review changed files

```text
accounts/adapters.py + context_processors.py
accounts/views.py + urls.py               session-to-JWT exchange
accounts/test_google.py                   approval and CSRF tests
config/settings.py + urls.py              optional allauth/provider settings
templates/base.html + registration/login.html
pyproject.toml + uv.lock
```

Commit code and dependency lock, not OAuth credentials. For deployment, follow [Phase 7 — Deployment](../07_deployment.md). Configure the production HTTPS callback and pass provider credentials separately to the application environment only when enabling this integration.
