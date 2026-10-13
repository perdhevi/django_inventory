"""
URL configuration for django_inventory project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.1/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import include, path
from django.contrib.auth import views as auth_views
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView
from rest_framework.permissions import IsAdminUser
from inventory.health import health
urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", include("accounts.urls")),
    path("api/", include("inventory.urls")),
    path("api-auth/", include("rest_framework.urls")),
    path("accounts/login/", auth_views.LoginView.as_view(), name="login"),
    path("accounts/logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("accounts/password-change/", auth_views.PasswordChangeView.as_view(), name="password_change"),
    path("accounts/password-change/done/", auth_views.PasswordChangeDoneView.as_view(), name="password_change_done"),
    path("health/", health, name="health"),
    path("", include("inventory.web_urls")),
    path("api/schema/", SpectacularAPIView.as_view(permission_classes=[IsAdminUser]), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema", permission_classes=[IsAdminUser]), name="api-docs"),
]
