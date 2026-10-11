from django.db.models.deletion import ProtectedError
from rest_framework import status, viewsets
from rest_framework.exceptions import APIException

from .models import Category, Product
from .serializers import CategorySerializer, ProductSerializer


class CategoryInUse(APIException):
    status_code = status.HTTP_409_CONFLICT
    default_detail = "This category still has products. Reassign or delete them first."
    default_code = "category_in_use"


class CategoryViewSet(viewsets.ModelViewSet):
    queryset = Category.objects.all()
    serializer_class = CategorySerializer

    def perform_destroy(self, instance):
        try:
            instance.delete()
        except ProtectedError as exc:
            raise CategoryInUse() from exc


class ProductViewSet(viewsets.ModelViewSet):
    queryset = Product.objects.select_related("category").all()
    serializer_class = ProductSerializer