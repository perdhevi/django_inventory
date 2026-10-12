from decimal import Decimal

from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from .models import Category, Product

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import patch
from uuid import uuid4

from django.core.exceptions import ValidationError
from django.db import close_old_connections, connection
from django.test import TransactionTestCase

from .models import StockTransaction
from .services import post_stock


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


class StockPostingTests(TransactionTestCase):
    def setUp(self):
        self.actor = get_user_model().objects.create_user(username="poster", is_staff=True)
        self.product = Product.objects.create(
            sku="POST-1", name="Posting", category=Category.objects.create(name="Posting"), price="40.00"
        )

    def post(self, kind, quantity, **extra):
        return post_stock(actor=self.actor, product_id=self.product.pk,
                          transaction_type=kind, quantity=quantity, request_key=uuid4(), **extra)

    def test_weighted_average_and_final_withdrawal(self):
        self.post("PROCUREMENT", 10, unit_cost="20.00")
        self.post("PROCUREMENT", 10, unit_cost="30.00")
        sale, _ = self.post("SALE", 4, selling_price="40.00")
        self.assertEqual(sale.cogs, Decimal("100"))
        self.assertEqual(sale.gross_profit, Decimal("60"))
        self.product.refresh_from_db()
        self.assertEqual(self.product.inventory_value, Decimal("400"))
        self.post("SALE", 16, selling_price="40.00")
        self.product.refresh_from_db()
        self.assertEqual((self.product.stock_quantity, self.product.inventory_value), (0, Decimal("0")))

    def test_duplicate_and_changed_payload(self):
        data = dict(actor=self.actor, product_id=self.product.pk, transaction_type="PROCUREMENT",
                    quantity=3, unit_cost="1.00", request_key=uuid4())
        first, _ = post_stock(**data)
        second, created = post_stock(**data)
        self.assertEqual(first.pk, second.pk)
        self.assertFalse(created)
        with self.assertRaises(ValidationError):
            post_stock(**{**data, "quantity": 4})
        self.assertEqual(StockTransaction.objects.count(), 1)

    def test_balance_failure_rolls_back_movement(self):
        with patch.object(Product, "save", side_effect=RuntimeError("write failed")):
            with self.assertRaises(RuntimeError):
                self.post("PROCUREMENT", 3, unit_cost="1.00")
        self.assertFalse(StockTransaction.objects.exists())
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, 0)

    def test_stale_catalog_save_cannot_overwrite_a_posting(self):
        stale_product = Product.objects.get(pk=self.product.pk)
        self.post("PROCUREMENT", 3, unit_cost="1.00")
        stale_product.name = "Renamed"
        stale_product.save()
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, 3)
        self.assertEqual(self.product.inventory_value, Decimal("3"))

    def test_concurrent_sales_cannot_oversell(self):
        if connection.vendor != "postgresql":
            self.skipTest("Row-lock behavior requires PostgreSQL")
        self.post("PROCUREMENT", 1, unit_cost="1.00")
        barrier = Barrier(2)

        def sell():
            close_old_connections()
            try:
                actor = get_user_model().objects.get(pk=self.actor.pk)
                barrier.wait(timeout=10)
                post_stock(actor=actor, product_id=self.product.pk, transaction_type="SALE",
                           quantity=1, selling_price="2.00", request_key=uuid4())
                return "posted"
            except ValidationError:
                return "rejected"
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: sell(), range(2)))
        self.assertCountEqual(results, ["posted", "rejected"])
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, 0)