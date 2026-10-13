"""
Read surface other apps use to get at branch data, instead of querying
Branch directly. Same rationale as apps.bakong.services — this is the seam
a future split would extract along.
"""
from typing import List, Optional

from .models import INGEST_KEY_PREFIX, Branch, hash_ingest_key


def get_sibling_account_ids(branch: Branch) -> List[str]:
    """Bakong sub-account IDs configured on this branch's sibling branches
    (same business, excluding this branch itself)."""
    return list(
        Branch.objects.filter(business=branch.business)
        .exclude(pk=branch.pk)
        .exclude(bakong_account_id="")
        .values_list("bakong_account_id", flat=True)
    )


def has_unassigned_siblings(branch: Branch) -> bool:
    """True if another branch of the same business also has no Bakong
    sub-account — then the business's unattributed transactions can't be
    split between them."""
    return (
        Branch.objects.filter(business=branch.business, bakong_account_id="")
        .exclude(pk=branch.pk)
        .exists()
    )


def get_account_ids(business) -> List[str]:
    """Distinct Bakong sub-account IDs configured on the business's branches."""
    return list(
        Branch.objects.filter(business=business)
        .exclude(bakong_account_id="")
        .values_list("bakong_account_id", flat=True)
        .distinct()
    )


def get_branches(business) -> List[Branch]:
    return list(Branch.objects.filter(business=business))


def get_branch_by_ingest_key(key: str) -> Optional[Branch]:
    if not key or not key.startswith(INGEST_KEY_PREFIX):
        return None
    return Branch.objects.select_related("business").filter(ingest_key_hash=hash_ingest_key(key)).first()
