from rest_framework.exceptions import PermissionDenied


def get_request_business(request):
    """
    Returns the Business for the current user.
    Superusers return None (no filter — they see everything).
    Regular users without a profile raise 403.
    """
    if request.user.is_superuser:
        return None
    try:
        return request.user.profile.business
    except Exception:
        raise PermissionDenied("No business profile configured for this account.")


def ensure_can_write(request, message="Viewers have read-only access."):
    """Raises 403 for viewer-role users. Superusers (no profile) may write."""
    try:
        role = request.user.profile.role
    except Exception:
        role = None
    if role == "viewer":
        raise PermissionDenied(message)
