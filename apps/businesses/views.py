from rest_framework import generics, permissions
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Business, UserProfile
from .serializers import BusinessSerializer, UserProfileSerializer
from .utils import get_request_business


class BusinessListCreateView(generics.ListCreateAPIView):
    serializer_class = BusinessSerializer

    def get_permissions(self):
        # Only superusers may create new businesses
        if self.request.method == "POST":
            return [permissions.IsAdminUser()]
        return [permissions.IsAuthenticated()]

    def get_queryset(self):
        business = get_request_business(self.request)
        if business is None:
            return Business.objects.all()
        return Business.objects.filter(pk=business.pk)


class BusinessRetrieveUpdateView(generics.RetrieveUpdateAPIView):
    serializer_class = BusinessSerializer

    def get_permissions(self):
        if self.request.method in ("PUT", "PATCH"):
            return [permissions.IsAuthenticated()]
        return [permissions.IsAuthenticated()]

    def get_queryset(self):
        business = get_request_business(self.request)
        if business is None:
            return Business.objects.all()
        return Business.objects.filter(pk=business.pk)


class MeView(APIView):
    """Returns the current user's profile — used by the frontend on login."""
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        user = request.user
        data = {
            "id": user.id,
            "username": user.username,
            "email": user.email,
            "is_superuser": user.is_superuser,
        }
        try:
            profile = user.profile
            data["business_id"] = profile.business.id
            data["business_name"] = profile.business.name
            data["role"] = profile.role
        except Exception:
            data["business_id"] = None
            data["business_name"] = None
            data["role"] = "superuser" if user.is_superuser else None
        return Response(data)
