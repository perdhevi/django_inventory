import csv

from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError as DjangoValidationError
from django.http import HttpResponse
from django.shortcuts import render
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView
from drf_spectacular.utils import extend_schema, OpenApiTypes

from .reports import report_payload

@extend_schema(responses=OpenApiTypes.OBJECT)
class ReportView(APIView):
    def get(self, request, kind):
        try:
            data = report_payload(request.user, kind, request.query_params)
        except DjangoValidationError as exc:
            raise ValidationError(exc.messages) from exc
        return Response(data)


def csv_cell(value):
    text = "" if value is None else str(value)
    # Protect user text even when a formula marker follows whitespace/control characters.
    if text.lstrip().startswith(("=", "+", "-", "@")) or text.startswith(("\t", "\r", "\n")):
        return "'" + text
    return text


@login_required
def report_page(request, kind):
    try:
        data = report_payload(request.user, kind, request.GET)
    except DjangoValidationError as exc:
        return HttpResponse("; ".join(exc.messages), status=400, content_type="text/plain")
    query = request.GET.copy()
    query.pop("page", None)
    return render(request, "inventory/report.html", {"report": data, "query": query.urlencode()})


@login_required
def report_csv(request, kind):
    try:
        data = report_payload(request.user, kind, request.GET, exporting=True)
    except DjangoValidationError as exc:
        return HttpResponse("; ".join(exc.messages), status=400, content_type="text/plain")
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="{kind}-{data["currency"]}.csv"'
    writer = csv.writer(response)
    writer.writerow([f"{column} ({data['currency']})" if column in {
        "unit_cost", "selling_price", "revenue", "cogs", "gross_profit", "value_change",
        "average_unit_cost", "inventory_value"
    } else column for column in data["columns"]])
    for row in data["rows"]:
        writer.writerow([csv_cell(row[column]) for column in data["columns"]])
    return response