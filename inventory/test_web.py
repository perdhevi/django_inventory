from uuid import uuid4

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management import call_command
from django.test import Client, TestCase
from django.urls import reverse

from .models import Category, Product, StockTransaction
from .services import post_stock


class BrowserWorkflowTests(TestCase):
    def setUp(self):
        call_command("setup_roles", verbosity=0)
        self.sales = get_user_model().objects.create_user(username="web-sales", password="test-password")
        self.sales.groups.add(Group.objects.get(name="Sales"))
        self.admin = get_user_model().objects.create_superuser(username="web-admin", password="test-password")
        self.product = Product.objects.create(sku="WEB-1", name="Web", price="40.00",
                                             category=Category.objects.create(name="Web"))
        post_stock(actor=self.admin, product_id=self.product.pk, transaction_type="PROCUREMENT",
                   quantity=10, unit_cost="20.00", request_key=uuid4())
        self.client.force_login(self.sales)

    def test_sales_post_and_retry_without_cost_leak(self):
        payload = {"product": self.product.pk, "quantity": 4, "selling_price": "40.00",
                   "request_key": str(uuid4())}
        url = reverse("web-post", args=["SALE"])
        first = self.client.post(url, payload)
        self.assertEqual(first.status_code, 302)
        self.assertEqual(self.client.post(url, payload).status_code, 302)
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, 6)
        detail = self.client.get(first.url)
        self.assertContains(detail, "revenue")
        self.assertNotContains(detail, "cogs")
        self.assertNotContains(detail, "gross_profit")

    def test_direct_correction_url_and_csrf_are_protected(self):
        self.assertEqual(self.client.get(reverse("web-post", args=["ADJUSTMENT_OUT"])).status_code, 403)
        strict = Client(enforce_csrf_checks=True)
        strict.force_login(self.sales)
        response = strict.post(reverse("web-post", args=["SALE"]), {
            "product": self.product.pk, "quantity": 1, "selling_price": "40.00", "request_key": str(uuid4())
        })
        self.assertEqual(response.status_code, 403)

    def test_metadata_form_ignores_balance_input(self):
        self.client.force_login(self.admin)
        response = self.client.post(reverse("web-product-edit", args=[self.product.pk]), {
            "sku": "WEB-1", "name": "Updated", "category": self.product.category_id,
            "price": "40.00", "is_active": "on", "stock_quantity": 999, "inventory_value": "999"
        })
        self.assertEqual(response.status_code, 302)
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, 10)

    def test_login_logout_and_safe_redirect(self):
        self.client.logout()
        self.assertRedirects(self.client.get(reverse("dashboard")),
                             reverse("login") + "?next=/", fetch_redirect_response=False)
        response = self.client.post(reverse("login"), {
            "username": "web-sales", "password": "test-password",
            "next": "https://example.com/",
        })
        self.assertRedirects(response, reverse("dashboard"))
        self.assertEqual(self.client.get(reverse("logout")).status_code, 405)
        self.assertRedirects(self.client.post(reverse("logout")), reverse("login"))

    def test_failed_sale_preserves_balances_and_history(self):
        before = StockTransaction.objects.count()
        response = self.client.post(reverse("web-post", args=["SALE"]), {
            "product": self.product.pk, "quantity": 11, "selling_price": "40.00",
            "request_key": str(uuid4()),
        })
        self.assertContains(response, "Insufficient stock.")
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, 10)
        self.assertEqual(self.product.inventory_value, 200)
        self.assertEqual(StockTransaction.objects.count(), before)

    def test_viewer_history_and_sales_detail_filter(self):
        procurement = StockTransaction.objects.get(transaction_type="PROCUREMENT")
        self.assertEqual(self.client.get(reverse("web-movement-detail", args=[procurement.pk])).status_code, 404)
        viewer = get_user_model().objects.create_user(username="web-viewer", password="test-password")
        viewer.groups.add(Group.objects.get(name="Viewer"))
        self.client.force_login(viewer)
        response = self.client.get(reverse("web-movements"))
        self.assertContains(response, "PROCUREMENT")
        for field in ("unit_cost", "selling_price", "value_change", "cogs", "revenue", "gross_profit"):
            self.assertNotContains(response, field)
        self.assertEqual(self.client.get(reverse("web-post", args=["SALE"])).status_code, 403)

    def test_inactive_product_and_changed_retry_are_rejected(self):
        payload = {"product": self.product.pk, "quantity": 1, "selling_price": "40.00",
                   "request_key": str(uuid4())}
        url = reverse("web-post", args=["SALE"])
        self.assertEqual(self.client.post(url, payload).status_code, 302)
        payload["quantity"] = 2
        self.assertContains(self.client.post(url, payload), "Request key already used")
        self.product.is_active = False
        self.product.save(update_fields=["is_active"])
        payload["request_key"] = str(uuid4())
        self.assertEqual(self.client.post(url, payload).status_code, 200)
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, 9)
        self.assertEqual(StockTransaction.objects.count(), 2)

    def test_password_change_preserves_current_session(self):
        response = self.client.post(reverse("password_change"), {
            "old_password": "test-password", "new_password1": "New-strong-web-password-927!",
            "new_password2": "New-strong-web-password-927!",
        })
        self.assertRedirects(response, reverse("password_change_done"))
        self.assertEqual(self.client.get(reverse("dashboard")).status_code, 200)
        self.sales.refresh_from_db()
        self.assertTrue(self.sales.check_password("New-strong-web-password-927!"))