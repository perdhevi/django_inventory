from datetime import date, datetime, time, timedelta

from django.core.exceptions import ValidationError
from django.db.models import F, Q
from django.utils import timezone


def integer(params, key):
    value = params.get(key)
    if not value:
        return None
    try:
        result = int(value)
        if result < 1:
            raise ValueError
        return result
    except (TypeError, ValueError):
        raise ValidationError(f"{key} must be a positive integer.")


def filter_products(qs, params):
    search = params.get("q", "").strip()
    if search:
        qs = qs.filter(Q(sku__icontains=search) | Q(name__icontains=search))
    category = integer(params, "category")
    if category:
        qs = qs.filter(category_id=category)
    active = params.get("active", "")
    if active not in {"", "true", "false"}:
        raise ValidationError("active must be true or false.")
    if active:
        qs = qs.filter(is_active=active == "true")
    low = params.get("low", "")
    if low not in {"", "true", "false"}:
        raise ValidationError("low must be true or false.")
    if low == "true":
        qs = qs.filter(stock_quantity__lte=F("reorder_level"))
    elif low == "false":
        qs = qs.filter(stock_quantity__gt=F("reorder_level"))
    return qs.order_by("name", "id")


def filter_movements(qs, params):
    for field in ("product", "actor"):
        value = integer(params, field)
        if value:
            qs = qs.filter(**{f"{field}_id": value})
    kind = params.get("type")
    if kind:
        from .models import StockTransaction
        if kind not in StockTransaction.Type.values:
            raise ValidationError("Unknown movement type.")
        qs = qs.filter(transaction_type=kind)
    try:
        start = date.fromisoformat(params["start"]) if params.get("start") else None
        end = date.fromisoformat(params["end"]) if params.get("end") else None
        if start and end and start > end:
            raise ValueError
        zone = timezone.get_current_timezone()
        if start:
            qs = qs.filter(created_at__gte=timezone.make_aware(datetime.combine(start, time.min), zone))
        if end:
            stop = timezone.make_aware(datetime.combine(end + timedelta(days=1), time.min), zone)
            qs = qs.filter(created_at__lt=stop)
    except (ValueError, OverflowError):
        raise ValidationError("Use YYYY-MM-DD dates with start at or before end.")
    return qs.order_by("-created_at", "-id")