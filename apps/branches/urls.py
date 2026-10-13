from django.urls import path
from .views import BranchListCreateView, BranchRetrieveUpdateDestroyView

urlpatterns = [
    path("branches/", BranchListCreateView.as_view(), name="branch-list-create"),
    path("branches/<int:pk>/", BranchRetrieveUpdateDestroyView.as_view(), name="branch-detail"),
]
