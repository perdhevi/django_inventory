from uuid import uuid4

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.management import call_command
from django.test import TestCase

from .models import Category, Product
from .queries import filter_products
from .report_views import csv_cell
from .reports import report_payload
from .services import post_stock


class ReportTests(TestCase):
    def setUp(self):
        call_command("setup_roles", verbosity=0)
        self.admin = get_user_model().objects.create_superuser(username="report-admin", password="test-password")
        self.sales = get_user_model().objects.create_user(username="report-sales")
        self.sales.groups.add(Group.objects.get(name="Sales"))
        self.product = Product.objects.create(sku="REPORT-1", name="Report", price="40.00", reorder_level=16,
                                             category=Category.objects.create(name="Report"))
        for cost in ("20.00", "30.00"):
            post_stock(actor=self.admin, product_id=self.product.pk, transaction_type="PROCUREMENT",
                       quantity=10, unit_cost=cost, request_key=uuid4())
        post_stock(actor=self.admin, product_id=self.product.pk, transaction_type="SALE",
                   quantity=4, selling_price="40.00", request_key=uuid4())

    def test_totals_match_history_and_snapshot(self):
        sales = report_payload(self.admin, "sales", {})
        self.assertEqual(sales["totals"]["revenue"], "160.000000")
        self.assertEqual(sales["totals"]["cogs"], "100.000000")
        self.assertEqual(report_payload(self.admin, "valuation", {})["totals"]["inventory_value"], "400.000000")
        self.assertEqual(filter_products(Product.objects.all(), {"low": "true"}).count(), 1)

    def test_export_reuses_visibility_and_dates_are_validated(self):
        sales = report_payload(self.sales, "sales", {}, exporting=True)
        self.assertIn("revenue", sales["columns"])
        self.assertNotIn("cogs", sales["columns"])
        with self.assertRaises(PermissionDenied):
            report_payload(self.sales, "valuation", {}, exporting=True)
        with self.assertRaises(ValidationError):
            report_payload(self.admin, "sales", {"start": "not-a-date"})
        self.assertEqual(csv_cell("  =1+1"), "'  =1+1")

    def test_viewer_can_read_stock_and_quantity_history_but_cannot_export(self):
        viewer = get_user_model().objects.create_user(username="report-viewer")
        viewer.groups.add(Group.objects.get(name="Viewer"))
        self.client.force_login(viewer)
        self.assertEqual(self.client.get("/reports/stock/").status_code, 200)
        self.assertEqual(self.client.get("/reports/stock/csv/").status_code, 403)
        history = self.client.get("/api/reports/movements/")
        self.assertEqual(history.status_code, 200)
        self.assertNotIn("revenue", history.json()["columns"])
        self.assertEqual(self.client.get("/api/reports/valuation/").status_code, 403)

    def test_end_date_uses_local_midnight_and_scope_cannot_expand(self):
        from datetime import datetime
        from django.utils import timezone
        from .models import StockTransaction

        sale = StockTransaction.objects.get(transaction_type="SALE")
        zone = timezone.get_current_timezone()
        self.assertEqual(report_payload(self.admin, "stock", {})["timezone"], timezone.get_current_timezone_name())
        StockTransaction.objects.filter(pk=sale.pk).update(
            created_at=datetime(2026, 10, 12, 23, 59, 59, tzinfo=zone))
        params = {"start": "2026-10-12", "end": "2026-10-12"}
        self.assertEqual(report_payload(self.sales, "sales", params)["count"], 1)
        StockTransaction.objects.filter(pk=sale.pk).update(
            created_at=datetime(2026, 10, 13, 0, 0, tzinfo=zone))
        self.assertEqual(report_payload(self.sales, "sales", params)["count"], 0)
        self.assertEqual(report_payload(self.sales, "movements", {"type": "PROCUREMENT"})["count"], 0)
        with self.assertRaises(ValidationError):
            report_payload(self.admin, "stock", params)

    def test_pagination_keeps_totals_and_export_includes_all_rows(self):
        # Use procurement rows to exceed the page size without exhausting stock.
        for _ in range(26):
            post_stock(actor=self.admin, product_id=self.product.pk, transaction_type="PROCUREMENT",
                       quantity=1, unit_cost="25.00", request_key=uuid4())
        first = report_payload(self.admin, "procurement", {})
        second = report_payload(self.admin, "procurement", {"page": "2"})
        exported = report_payload(self.admin, "procurement", {"page": "2"}, exporting=True)
        self.assertEqual((len(first["rows"]), len(second["rows"])), (25, 3))
        self.assertEqual(first["totals"], second["totals"])
        self.assertEqual(first["totals"]["quantity"], "46")
        self.assertEqual(len(exported["rows"]), 28)

    def test_http_reports_validate_filters_and_preserve_sales_visibility(self):
        # The API envelope and browser display both identify the active timezone.
        self.client.force_login(self.sales)
        api = self.client.get("/api/reports/sales/")
        self.assertEqual(api.status_code, 200)
        self.assertNotIn("cogs", api.json()["rows"][0])
        csv_response = self.client.get("/reports/sales/csv/")
        self.assertEqual(csv_response.status_code, 200)
        self.assertNotIn("cogs", csv_response.content.decode().splitlines()[0])
        self.assertEqual(self.client.get("/api/reports/sales/?start=bad").status_code, 400)
        self.assertEqual(self.client.get("/reports/sales/?product=-1").status_code, 400)

    def test_active_timezone_is_reported_and_used_for_date_filters(self):
        from datetime import datetime, timezone as datetime_timezone
        from django.utils import timezone
        from .models import StockTransaction

        StockTransaction.objects.filter(transaction_type="SALE").update(
            created_at=datetime(2026, 10, 12, 20, tzinfo=datetime_timezone.utc))
        params = {"start": "2026-10-12", "end": "2026-10-12"}
        with timezone.override("UTC"):
            data = report_payload(self.admin, "sales", params)
            self.assertEqual((data["timezone"], data["count"]), ("UTC", 1))
            self.client.force_login(self.admin)
            self.assertContains(self.client.get("/reports/sales/"), "Report timezone: UTC")
        with timezone.override("Asia/Jakarta"):
            data = report_payload(self.admin, "sales", params)
            self.assertEqual((data["timezone"], data["count"]), ("Asia/Jakarta", 0))