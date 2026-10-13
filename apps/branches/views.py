from rest_framework import generics, permissions
from .models import Branch
from .serializers import BranchSerializer
from apps.businesses.utils import get_request_business


class BranchListCreateView(generics.ListCreateAPIView):
    serializer_class = BranchSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        business = get_request_business(self.request)
        qs = Branch.objects.select_related("business")
        if business is not None:
            return qs.filter(business=business)
        # Superuser: allow optional ?business= filter
        business_id = self.request.query_params.get("business")
        if business_id:
            qs = qs.filter(business_id=business_id)
        return qs

    def perform_create(self, serializer):
        business = get_request_business(self.request)
        if business is not None:
            serializer.save(business=business)
        else:
            serializer.save()


class BranchRetrieveUpdateDestroyView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = BranchSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        business = get_request_business(self.request)
        qs = Branch.objects.select_related("business")
        if business is not None:
            return qs.filter(business=business)
        return qs
