from unittest.mock import patch
from django.db import DatabaseError
from django.test import TestCase
from django.urls import reverse


class HealthTests(TestCase):
    def test_database_available(self):
        response = self.client.get(reverse("health"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})

    def test_database_failure_has_no_details(self):
        with patch("inventory.health.connection.cursor", side_effect=DatabaseError("secret connection details")):
            response = self.client.get(reverse("health"))
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {"status": "unavailable"})