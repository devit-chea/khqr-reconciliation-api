"""
Write/read surface for the audit trail. Other apps call record() after a
change; they never touch AuditLogEntry directly.
"""
from decimal import Decimal
from typing import Iterable, Optional, Tuple

from .models import AuditLogEntry


def _jsonable(value):
    if isinstance(value, Decimal):
        return str(value)
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if hasattr(value, "pk"):
        return value.pk
    return value


def diff(old: dict, new: dict) -> dict:
    """{field: [old, new]} for the fields whose value changed."""
    return {
        k: [_jsonable(old.get(k)), _jsonable(v)]
        for k, v in new.items()
        if _jsonable(old.get(k)) != _jsonable(v)
    }


def record(actor, business, action: str, obj, summary: str = "", changes: Optional[dict] = None) -> AuditLogEntry:
    user = actor if getattr(actor, "is_authenticated", False) else None
    return AuditLogEntry.objects.create(
        business=business,
        actor=user,
        action=action,
        object_type=obj._meta.model_name,
        object_id=str(obj.pk),
        summary=summary[:500],
        changes={k: [_jsonable(a) for a in v] if isinstance(v, (list, tuple)) else _jsonable(v)
                 for k, v in (changes or {}).items()},
    )


def entries_for(objects: Iterable[Tuple[str, object]]):
    """Entries about any of the given (object_type, object_id) pairs."""
    from django.db.models import Q
    q = Q(pk__in=[])
    for object_type, object_id in objects:
        q |= Q(object_type=object_type, object_id=str(object_id))
    return AuditLogEntry.objects.filter(q).select_related("actor")
