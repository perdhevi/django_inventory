from django.urls import path
from rest_framework.routers import DefaultRouter
from .views import CategoryViewSet, ProductViewSet, StockTransactionViewSet, ValuationView
from .report_views import ReportView

router = DefaultRouter()
router.register("categories", CategoryViewSet, basename="category")
router.register("products", ProductViewSet, basename="product")

router.register("stock_transactions", StockTransactionViewSet, basename="stock-transaction")

urlpatterns = [
    path("valuation/", ValuationView.as_view(), name="valuation"),
    path("reports/<str:kind>/", ReportView.as_view(), name="api-report"),
] + router.urls
# urlpatterns = router.urls


