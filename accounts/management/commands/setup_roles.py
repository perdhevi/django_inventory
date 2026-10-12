from django.contrib.auth.models import Group, Permission
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

CATALOG_READ = {"inventory.view_product", "inventory.view_category"}
CATALOG_WRITE = {f"inventory.{action}_{model}" for action in ("add", "change", "delete")
                 for model in ("product", "category")}
MOVEMENT_READ = {"inventory.view_all_movements"}
SALE = {"inventory.record_sale", "inventory.view_sales_report"}
PROCUREMENT = {"inventory.receive_procurement", "inventory.view_procurement_report"}
VALUATION = {"inventory.view_inventory_valuation"}
CORRECTIONS = {"inventory.adjust_stock", "inventory.record_opening_balance"}
EXPORT = {"inventory.export_reports"}
ROLES = {
    "Viewer": CATALOG_READ | MOVEMENT_READ,
    "Sales": CATALOG_READ | SALE | EXPORT,
    "Procurement": CATALOG_READ | PROCUREMENT | EXPORT,
    "Inventory manager": CATALOG_READ | CATALOG_WRITE | MOVEMENT_READ | SALE | PROCUREMENT | VALUATION | EXPORT,
    "Administrator": CATALOG_READ | CATALOG_WRITE | MOVEMENT_READ | SALE | PROCUREMENT | VALUATION | CORRECTIONS | EXPORT
        | {"auth.view_user", "auth.add_user", "auth.change_user", "auth.view_group"},
}


class Command(BaseCommand):
    help = "Set the tutorial groups to the documented permission matrix."

    @transaction.atomic
    def handle(self, *args, **options):
        for name, capabilities in ROLES.items():
            permissions = []
            for capability in sorted(capabilities):
                app, code = capability.split(".", 1)
                try:
                    permissions.append(Permission.objects.get(content_type__app_label=app, codename=code))
                except Permission.DoesNotExist as exc:
                    raise CommandError(f"Missing {capability}; run migrate first") from exc
            group, _ = Group.objects.get_or_create(name=name)
            group.permissions.set(permissions)
        self.stdout.write(self.style.SUCCESS("Roles configured"))