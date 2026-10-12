from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import CategoryViewSet, ProductViewSet, StockTransactionViewSet, ValuationView


router = DefaultRouter()
router.register("categories", CategoryViewSet, basename="category")
router.register("products", ProductViewSet, basename="product")

router.register("stock_transactions", StockTransactionViewSet, basename="stock-transaction")

urlpatterns = [path("valuation/", ValuationView.as_view(), name="valuation")] + router.urls
# urlpatterns = router.urls
