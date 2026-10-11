from decimal import Decimal

from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from .models import Category, Product


class InventoryAPITests(APITestCase):
    def setUp(self):
        User = get_user_model()
        self.staff = User.objects.create_user(
            username="inventory_staff", password="test-only-password", is_staff=True
        )
        self.regular_user = User.objects.create_user(
            username="regular_user", password="test-only-password"
        )
        self.category = Category.objects.create(name="Test Accessories")
        self.product = Product.objects.create(
            sku="TEST-KB-001",
            name="Test Keyboard",
            category=self.category,
            price=Decimal("79.90"),
            stock_quantity=10,
        )
        self.client.force_authenticate(user=self.staff)

    def test_anonymous_cannot_list_products(self):
        self.client.force_authenticate(user=None)
        response = self.client.get(reverse("product-list"))
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_regular_user_cannot_list_products(self):
        self.client.force_authenticate(user=self.regular_user)
        response = self.client.get(reverse("product-list"))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_create_product_ignores_client_stock_balance(self):
        response = self.client.post(
            reverse("product-list"),
            {
                "sku": "TEST-MOUSE-001",
                "name": "Test Mouse",
                "category": self.category.pk,
                "price": "25.00",
                "stock_quantity": 999,
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        product = Product.objects.get(pk=response.data["id"])
        self.assertEqual(product.stock_quantity, 0)
        self.assertEqual(response.data["category_name"], self.category.name)

    def test_negative_price_does_not_change_product(self):
        response = self.client.patch(
            reverse("product-detail", args=[self.product.pk]),
            {"price": "-1.00"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("price", response.data)
        self.product.refresh_from_db()
        self.assertEqual(self.product.price, Decimal("79.90"))

    def test_duplicate_sku_is_rejected(self):
        response = self.client.post(
            reverse("product-list"),
            {
                "sku": self.product.sku,
                "name": "Duplicate Keyboard",
                "category": self.category.pk,
                "price": "10.00",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("sku", response.data)
        self.assertEqual(Product.objects.count(), 1)

    def test_used_category_cannot_be_deleted(self):
        response = self.client.delete(
            reverse("category-detail", args=[self.category.pk])
        )
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        self.assertTrue(Category.objects.filter(pk=self.category.pk).exists())
        self.assertTrue(Product.objects.filter(pk=self.product.pk).exists())