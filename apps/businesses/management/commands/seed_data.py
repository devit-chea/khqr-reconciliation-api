"""
Seeds the database with sample businesses, branches, sales records,
Bakong transactions, and reconciliation results.

Safe to re-run — uses get_or_create throughout.
Options:
  --flush              Wipe ALL seed companies before re-seeding.
  --company "Name"     Seed (or flush+seed) only that company.
"""
from datetime import timedelta, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo
import random

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.businesses.models import Business, UserProfile
from apps.branches.models import Branch
from apps.sales.models import DailySalesRecord
from apps.bakong.models import BakongTransaction
from apps.reconciliation.engine import reconcile_branch_date

User = get_user_model()
PHNOM_PENH_TZ = ZoneInfo("Asia/Phnom_Penh")

# ---------------------------------------------------------------------------
# Company definitions — add more entries here to seed more companies.
# scenario format per branch: list of 7 tuples (sales_total, bakong_total)
#   day -7 → day -1.  bakong_total=None means no Bakong data yet → pending.
# ---------------------------------------------------------------------------

COMPANIES = [
    {
        "name": "Angkor Restaurant Group",
        "slug": "angkor",
        "bakong_account": "012345678@nbc",
        "branches": [
            {"name": "Siem Reap Main",     "location": "Pub Street, Siem Reap",  "bakong_account_id": "sr001@nbc"},
            {"name": "Phnom Penh Central", "location": "BKK1, Phnom Penh",       "bakong_account_id": "pp001@nbc"},
            {"name": "Battambang Branch",  "location": "Street 2, Battambang",   "bakong_account_id": ""},
        ],
        "scenario": {
            "Siem Reap Main": [
                (4_850_000, 4_850_000),   # matched
                (5_120_000, 5_120_000),   # matched
                (4_680_000, 4_680_000),   # matched
                (6_200_000, 5_800_000),   # discrepancy  −400,000
                (5_500_000, 5_500_000),   # matched
                (7_100_000, 7_100_000),   # matched
                (4_950_000, 4_950_000),   # matched
            ],
            "Phnom Penh Central": [
                (8_200_000,  8_200_000),  # matched
                (9_100_000,  9_100_000),  # matched
                (7_750_000,  9_300_000),  # discrepancy  +1,550,000
                (8_800_000,  8_800_000),  # matched
                (10_500_000, 10_500_000), # matched
                (9_200_000,  7_900_000),  # discrepancy  −1,300,000
                (8_400_000,  8_400_000),  # matched
            ],
            "Battambang Branch": [
                (3_200_000, None),
                (2_900_000, None),
                (3_450_000, None),
                (3_100_000, None),
                (2_800_000, None),
                (3_600_000, None),
                (3_300_000, None),
            ],
        },
    },
    {
        "name": "Lucky Market Chain",
        "slug": "lucky",
        "bakong_account": "087654321@nbc",
        "branches": [
            {"name": "Toul Kork",          "location": "St 315, Toul Kork, Phnom Penh",    "bakong_account_id": "lm-tk@nbc"},
            {"name": "Tuol Tom Poung",     "location": "Russian Market, Phnom Penh",        "bakong_account_id": "lm-ttp@nbc"},
            {"name": "Kandal Province",    "location": "National Rd 1, Kandal",             "bakong_account_id": ""},
        ],
        "scenario": {
            "Toul Kork": [
                (24_300_000, 24_300_000),  # matched
                (27_800_000, 27_800_000),  # matched
                (22_500_000, 22_500_000),  # matched
                (29_100_000, 29_100_000),  # matched
                (31_200_000, 28_700_000),  # discrepancy  −2,500,000
                (26_400_000, 26_400_000),  # matched
                (30_000_000, 30_000_000),  # matched
            ],
            "Tuol Tom Poung": [
                (18_500_000, 21_000_000),  # discrepancy  +2,500,000
                (19_200_000, 19_200_000),  # matched
                (20_100_000, 20_100_000),  # matched
                (17_800_000, 17_800_000),  # matched
                (22_400_000, 22_400_000),  # matched
                (21_000_000, 18_300_000),  # discrepancy  −2,700,000
                (19_700_000, 19_700_000),  # matched
            ],
            "Kandal Province": [
                (11_200_000, None),
                (10_800_000, None),
                (12_100_000, None),
                (11_500_000, None),
                (10_300_000, None),
                (12_800_000, None),
                (11_900_000, None),
            ],
        },
    },
]


class Command(BaseCommand):
    help = "Seed sample data for development. Supports multiple companies."

    def add_arguments(self, parser):
        parser.add_argument(
            "--flush",
            action="store_true",
            help="Delete existing seed data before re-seeding.",
        )
        parser.add_argument(
            "--company",
            type=str,
            default=None,
            help='Seed only this company by name (e.g. --company "Lucky Market Chain").',
        )

    def handle(self, *args, **options):
        target = options["company"]
        companies = COMPANIES

        if target:
            companies = [c for c in COMPANIES if c["name"] == target]
            if not companies:
                names = ", ".join(f'"{c["name"]}"' for c in COMPANIES)
                self.stderr.write(self.style.ERROR(
                    f'Company "{target}" not found. Available: {names}'
                ))
                return

        if options["flush"]:
            self._flush(companies)

        admin = self._ensure_admin()

        for company_def in companies:
            self.stdout.write(f'\n--- {company_def["name"]} ---')
            business = self._seed_business(company_def)
            self._seed_owner_user(business, company_def["slug"])
            branches = self._seed_branches(business, company_def["branches"])
            self._seed_records(branches, business, admin, company_def["scenario"])

        self.stdout.write(self.style.SUCCESS("\nSeed complete."))

    # ------------------------------------------------------------------ #

    def _flush(self, companies):
        self.stdout.write("Flushing existing seed data…")
        for company_def in companies:
            name = company_def["name"]
            slug = company_def["slug"]
            BakongTransaction.objects.filter(business__name=name).delete()
            DailySalesRecord.objects.filter(branch__business__name=name).delete()
            Branch.objects.filter(business__name=name).delete()
            Business.objects.filter(name=name).delete()
            User.objects.filter(username=f"{slug}_owner").delete()
            self.stdout.write(self.style.WARNING(f"  Flushed: {name}"))

    def _ensure_admin(self):
        user, created = User.objects.get_or_create(
            username="admin",
            defaults={"email": "admin@khqr.local", "is_staff": True, "is_superuser": True},
        )
        if created:
            user.set_password("admin1234")
            user.save()
            self.stdout.write(self.style.SUCCESS("  Created admin user (admin / admin1234)"))
        return user

    def _seed_owner_user(self, business, slug):
        username = f"{slug}_owner"
        password = f"{slug}1234"
        user, created = User.objects.get_or_create(
            username=username,
            defaults={"email": f"{username}@khqr.local"},
        )
        if created:
            user.set_password(password)
            user.save()
        UserProfile.objects.get_or_create(
            user=user,
            defaults={"business": business, "role": UserProfile.ROLE_OWNER},
        )
        self.stdout.write(
            ("  Created" if created else "  Exists ") + f" owner: {username} / {password}"
        )

    def _seed_business(self, company_def):
        business, created = Business.objects.get_or_create(
            name=company_def["name"],
            defaults={"bakong_account_id": company_def["bakong_account"]},
        )
        if created:
            business.set_bakong_token("SEED_DUMMY_TOKEN_NOT_A_REAL_API_KEY")
            business.save()
            self.stdout.write(f"  Created business: {business.name}")
        else:
            self.stdout.write(f"  Exists  business: {business.name}")
        return business

    def _seed_branches(self, business, branch_defs):
        result = {}
        for data in branch_defs:
            branch, created = Branch.objects.get_or_create(
                business=business,
                name=data["name"],
                defaults={
                    "location": data["location"],
                    "bakong_account_id": data["bakong_account_id"],
                },
            )
            result[data["name"]] = branch
            self.stdout.write(
                ("  Created" if created else "  Exists ") + f" branch: {branch.name}"
            )
        return result

    def _seed_records(self, branches, business, admin, scenario):
        today = timezone.localdate()

        for branch_name, branch in branches.items():
            days = scenario[branch_name]
            for offset, (sales_total, bakong_total) in enumerate(days):
                target_date = today - timedelta(days=7 - offset)

                DailySalesRecord.objects.get_or_create(
                    branch=branch,
                    date=target_date,
                    defaults={
                        "expected_total": Decimal(sales_total),
                        "source": DailySalesRecord.SOURCE_MANUAL,
                        "created_by": admin,
                    },
                )

                if bakong_total is not None:
                    self._create_transactions(business, branch, target_date, Decimal(bakong_total))

                reconcile_branch_date(branch, target_date)

        self.stdout.write(f"  Seeded 7 days × {len(branches)} branches.")

    def _create_transactions(self, business, branch, target_date, total_amount):
        branch_name = branch.name
        account_id = branch.bakong_account_id
        rng = random.Random(f"{business.name}:{branch_name}:{target_date}")
        num_txns = rng.randint(2, 4)
        splits = [rng.random() for _ in range(num_txns)]
        factor = sum(splits)
        amounts = [round(total_amount * Decimal(str(s / factor)), 0) for s in splits]
        amounts[-1] = total_amount - sum(amounts[:-1])

        # Unique prefix per company+branch to avoid hash collisions across companies
        prefix = f"{business.name[:3].upper()}-{branch_name[:3].upper()}"

        for i, amount in enumerate(amounts):
            hour = rng.randint(8, 21)
            minute = rng.randint(0, 59)
            ts = datetime(
                target_date.year, target_date.month, target_date.day,
                hour, minute, tzinfo=PHNOM_PENH_TZ,
            )
            ref = f"QR-{branch_name[:2].upper()}{target_date.strftime('%Y%m%d')}{i:02d}"
            txn_hash = f"SEED-{prefix}-{target_date}-{i}"
            payload = {
                "hash": txn_hash,
                "amount": str(amount),
                "currency": "KHR",
                "transactionDate": ts.isoformat(),
                "reference": ref,
            }
            if account_id:
                payload["accountId"] = account_id

            BakongTransaction.objects.get_or_create(
                hash=txn_hash,
                defaults={
                    "business": business,
                    "timestamp": ts,
                    "amount": amount,
                    "currency": "KHR",
                    "account_id": account_id or business.bakong_account_id,
                    "reference": ref,
                    "raw_payload": payload,
                },
            )
