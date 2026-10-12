from django.shortcuts import render
from drf_spectacular.utils import extend_schema, OpenApiTypes

from rest_framework.response import Response
from rest_framework.views import APIView

@extend_schema(responses=OpenApiTypes.OBJECT)
class MeView(APIView):
    def get(self, request):
        user = request.user
        return Response({"id": user.pk, "username": user.username, "email": user.email,
                         "capabilities": sorted(user.get_all_permissions())})