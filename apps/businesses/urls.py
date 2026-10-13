from django.urls import path
from .views import BusinessListCreateView, BusinessRetrieveUpdateView, MeView

urlpatterns = [
    path("businesses/", BusinessListCreateView.as_view(), name="business-list-create"),
    path("businesses/<int:pk>/", BusinessRetrieveUpdateView.as_view(), name="business-detail"),
    path("auth/me/", MeView.as_view(), name="auth-me"),
]
