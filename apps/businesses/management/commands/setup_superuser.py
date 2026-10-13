"""
Creates the superuser from environment variables if one does not already exist.
Safe to call on every deploy — no-ops if the user already exists.

Env vars (all optional, fall back to defaults shown):
  DJANGO_SUPERUSER_USERNAME  default: admin
  DJANGO_SUPERUSER_EMAIL     default: admin@khqr.local
  DJANGO_SUPERUSER_PASSWORD  default: admin1234
"""
import os
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Idempotently create a superuser from environment variables."

    def handle(self, *args, **options):
        User = get_user_model()

        username = os.environ.get("DJANGO_SUPERUSER_USERNAME", "admin")
        email = os.environ.get("DJANGO_SUPERUSER_EMAIL", "admin@khqr.local")
        password = os.environ.get("DJANGO_SUPERUSER_PASSWORD", "admin1234")

        if User.objects.filter(username=username).exists():
            self.stdout.write(self.style.WARNING(f"Superuser '{username}' already exists — skipped."))
            return

        User.objects.create_superuser(username=username, email=email, password=password)
        self.stdout.write(self.style.SUCCESS(f"Superuser '{username}' created (password: {password})."))
