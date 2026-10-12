from django.urls import path
from . import web_views as views

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("products/", views.products, name="web-products"),
    path("products/new/", views.ProductCreate.as_view(), name="web-product-create"),
    path("products/<int:pk>/", views.product_detail, name="web-product-detail"),
    path("products/<int:pk>/edit/", views.ProductUpdate.as_view(), name="web-product-edit"),
    path("categories/", views.categories, name="web-categories"),
    path("categories/new/", views.CategoryCreate.as_view(), name="web-category-create"),
    path("categories/<int:pk>/edit/", views.CategoryUpdate.as_view(), name="web-category-edit"),
    path("categories/<int:pk>/delete/", views.category_delete, name="web-category-delete"),
    path("stock/<str:kind>/", views.post_operation, name="web-post"),
    path("movements/", views.movements, name="web-movements"),
    path("movements/<int:pk>/", views.movement_detail, name="web-movement-detail"),
]