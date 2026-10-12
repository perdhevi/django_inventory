from django.db.models.deletion import ProtectedError
from rest_framework import status, viewsets
from rest_framework.exceptions import APIException,ValidationError
from django.conf import settings
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models import Sum
from rest_framework.response import Response
from rest_framework.views import APIView
from drf_spectacular.utils import extend_schema, OpenApiTypes


from .models import Category, Product, StockTransaction
from .serializers import CategorySerializer, ProductSerializer
from .serializers import StockOperationSerializer, StockTransactionSerializer
from .services import post_stock

from .access import CatalogPermission, MovementPermission, ValuationPermission, visible_movements
from .queries import filter_products, filter_movements



class CategoryInUse(APIException):
    status_code = status.HTTP_409_CONFLICT
    default_detail = "This category still has products. Reassign or delete them first."
    default_code = "category_in_use"


class CategoryViewSet(viewsets.ModelViewSet):
    permission_classes = [CatalogPermission]
    queryset = Category.objects.all()
    serializer_class = CategorySerializer

    def perform_destroy(self, instance):
        try:
            instance.delete()
        except ProtectedError as exc:
            raise CategoryInUse() from exc


class ProductViewSet(viewsets.ModelViewSet):
    permission_classes = [CatalogPermission]
    queryset = Product.objects.select_related("category").all()
    serializer_class = ProductSerializer

    def get_queryset(self):
        try:
            return filter_products(super().get_queryset(), self.request.query_params)
        except DjangoValidationError as exc:
            raise ValidationError(exc.messages) from exc
    def perform_destroy(self, instance):
        try:
            instance.delete()
        except ProtectedError as exc:
            error = APIException("Products with movements must be deactivated.")
            error.status_code = 409
            raise error from exc


class StockTransactionViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = [MovementPermission]
    queryset = StockTransaction.objects.select_related("product", "actor").all()
    serializer_class = StockTransactionSerializer

    @extend_schema(request=StockOperationSerializer,
                   responses={201: StockTransactionSerializer, 200: StockTransactionSerializer})
    def create(self, request):
        incoming = StockOperationSerializer(data=request.data)
        incoming.is_valid(raise_exception=True)
        data = dict(incoming.validated_data)
        data["product_id"] = data.pop("product").pk
        try:
            movement, created = post_stock(actor=request.user, **data)
        except DjangoValidationError as exc:
            raise ValidationError(exc.messages) from exc
        return Response(self.get_serializer(movement).data, status=201 if created else 200)

    # def get_queryset(self):
    #     return visible_movements(self.request.user)
    def get_queryset(self):
        try:
            return filter_movements(visible_movements(self.request.user), self.request.query_params)
        except DjangoValidationError as exc:
            raise ValidationError(exc.messages) from exc

@extend_schema(responses=OpenApiTypes.OBJECT)
class ValuationView(APIView):
    permission_classes = [ValuationPermission]

    def get(self, request):
        totals = StockTransaction.objects.filter(transaction_type="SALE").aggregate(
            revenue=Sum("revenue"), cogs=Sum("cogs"), gross_profit=Sum("gross_profit")
        )
        totals["inventory_value"] = Product.objects.aggregate(value=Sum("inventory_value"))["value"]
        return Response({"currency": settings.INVENTORY_CURRENCY,
                         **{key: format(value or 0, ".6f") for key, value in totals.items()}})
