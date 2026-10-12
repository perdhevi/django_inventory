from uuid import uuid4

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management import call_command
from django.urls import reverse
from rest_framework.test import APITestCase

from inventory.models import Category, Product
from inventory.services import post_stock


class RoleJWTTests(APITestCase):
    def setUp(self):
        call_command("setup_roles", verbosity=0)
        User = get_user_model()
        self.sales = User.objects.create_user(username="sales", password="test-password")
        self.sales.groups.add(Group.objects.get(name="Sales"))
        admin = User.objects.create_superuser(username="admin", password="test-password")
        product = Product.objects.create(sku="JWT-1", name="JWT", price="2.00",
                                         category=Category.objects.create(name="JWT"))
        self.receipt, _ = post_stock(actor=admin, product_id=product.pk, transaction_type="PROCUREMENT",
                                    quantity=2, unit_cost="1.00", request_key=uuid4())
        self.sale, _ = post_stock(actor=admin, product_id=product.pk, transaction_type="SALE",
                                 quantity=1, selling_price="2.00", request_key=uuid4())
        response = self.client.post(reverse("token-obtain"),
                                    {"username": "sales", "password": "test-password"})
        self.assertEqual(response.status_code, 200)
        self.tokens = response.data
        self.client.credentials(HTTP_AUTHORIZATION="Bearer " + self.tokens["access"])

    def test_sales_detail_scope_and_money_fields(self):
        forbidden = self.client.get(reverse("stock-transaction-detail", args=[self.receipt.pk]))
        self.assertEqual(forbidden.status_code, 404)
        sale = self.client.get(reverse("stock-transaction-detail", args=[self.sale.pk]))
        self.assertEqual(sale.status_code, 200)
        self.assertIn("revenue", sale.data)
        self.assertNotIn("cogs", sale.data)
        self.assertNotIn("gross_profit", sale.data)
        self.assertEqual(self.client.get(reverse("valuation")).status_code, 403)

    def test_current_roles_and_inactive_status_override_token(self):
        self.sales.groups.clear()
        self.assertEqual(self.client.get(reverse("product-list")).status_code, 403)
        self.sales.is_active = False
        self.sales.save()
        self.assertEqual(self.client.get(reverse("account-me")).status_code, 401)

    def test_rotated_and_revoked_refresh_cannot_be_reused(self):
        rotated = self.client.post(reverse("token-refresh"), {"refresh": self.tokens["refresh"]})
        self.assertEqual(rotated.status_code, 200)
        self.assertEqual(self.client.post(reverse("token-refresh"),
                                         {"refresh": self.tokens["refresh"]}).status_code, 401)
        self.assertEqual(self.client.post(reverse("token-logout"),
                                         {"refresh": rotated.data["refresh"]}).status_code, 200)
        self.assertEqual(self.client.post(reverse("token-refresh"),
                                         {"refresh": rotated.data["refresh"]}).status_code, 401)