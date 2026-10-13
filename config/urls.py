from django.contrib import admin
from django.urls import path, include
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView
from apps.businesses.serializers import CustomTokenObtainPairSerializer
from .views import health_check

CustomLoginView = TokenObtainPairView.as_view(serializer_class=CustomTokenObtainPairSerializer)

# Everything client-facing lives under /api/v1/ so a future v2 can be added
# alongside it without breaking whoever's still calling v1 — including a
# split-out service down the line that only implements part of this surface.
v1_patterns = [
    path("auth/login/", CustomLoginView, name="token_obtain_pair"),
    path("auth/refresh/", TokenRefreshView.as_view(), name="token_refresh"),
    path("", include("apps.businesses.urls")),
    path("", include("apps.branches.urls")),
    path("", include("apps.sales.urls")),
    path("", include("apps.reconciliation.urls")),
]

urlpatterns = [
    path("admin/", admin.site.urls),
    # Unversioned and outside /api/v1/ on purpose: infra shouldn't need to
    # track API version bumps just to know if the process is alive.
    path("api/health/", health_check, name="health-check"),
    path("api/v1/", include(v1_patterns)),
]
