from uuid import NAMESPACE_URL, uuid5

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError, PermissionDenied
from django.core.management.base import BaseCommand, CommandError

from inventory.models import Product, StockTransaction
from inventory.services import post_stock


class Command(BaseCommand):
    help = "Record existing stock without adding it twice."

    def add_arguments(self, parser):
        parser.add_argument("product_id", type=int)
        parser.add_argument("unit_cost")
        parser.add_argument("--actor", required=True)

    def handle(self, *args, **options):
        try:
            actor = get_user_model().objects.get(username=options["actor"])
            product = Product.objects.get(pk=options["product_id"])
            key = uuid5(NAMESPACE_URL, f"inventory-opening:{product.pk}")
            existing = StockTransaction.objects.filter(request_key=key).first()
            quantity = existing.quantity if existing else product.stock_quantity
            if not quantity:
                raise CommandError("Zero stock needs no opening record.")
            movement, created = post_stock(
                actor=actor, product_id=product.pk, transaction_type="OPENING_BALANCE",
                quantity=quantity, unit_cost=options["unit_cost"], request_key=key,
                reference="Phase 3 cutover", reconcile_existing=True,
            )
        except (ValidationError, PermissionDenied, Product.DoesNotExist,
                get_user_model().DoesNotExist) as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(f"Movement {movement.pk}; created={created}")