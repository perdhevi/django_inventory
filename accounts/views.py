from django.shortcuts import render

from rest_framework.response import Response
from rest_framework.views import APIView


class MeView(APIView):
    def get(self, request):
        user = request.user
        return Response({"id": user.pk, "username": user.username, "email": user.email,
                         "capabilities": sorted(user.get_all_permissions())})