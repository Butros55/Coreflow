"""Seed the demo workspace.

    python manage.py seed_demo            # idempotent: safe to re-run
    python manage.py seed_demo --reset    # wipe demo data first

This is what makes "runs with no external credentials" true rather than
aspirational: after seeding, every screen has real, persisted data behind real
endpoints, with both integrations disabled.
"""

from __future__ import annotations

import random
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.accounts.models import User, Workspace, WorkspaceMembership, WorkspaceRole
from apps.core.seeding import SeedContext, get_seeders, load_all_seeders

DEMO_WORKSPACE_SLUG = "demo"


class Command(BaseCommand):
    help = "Seed the demo workspace with realistic data. Idempotent."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--reset",
            action="store_true",
            help="Delete the demo workspace and everything in it before seeding.",
        )
        parser.add_argument(
            "--email",
            default=None,
            help="Demo user email (default: DEMO_USER_EMAIL or demo@coreflow.local).",
        )
        parser.add_argument(
            "--password",
            default=None,
            help="Demo user password (default: DEMO_USER_PASSWORD).",
        )
        parser.add_argument("--seed", type=int, default=20240101, help="RNG seed.")

    def handle(self, *args: Any, **options: Any) -> None:
        if settings.APP_ENV == "production":
            raise CommandError(
                "Refusing to seed demo data in production. "
                "Demo data in a real accounting system is a liability, not a convenience."
            )

        email = (
            options["email"] or getattr(settings, "DEMO_USER_EMAIL", None) or "demo@coreflow.local"
        )
        password = (
            options["password"]
            or getattr(settings, "DEMO_USER_PASSWORD", None)
            or "coreflow-demo-1234"
        )

        random.seed(options["seed"])

        with transaction.atomic():
            if options["reset"]:
                self._reset()

            workspace = self._create_workspace()
            user = self._create_user(email, password)
            self._create_membership(workspace, user)

            ctx = SeedContext(workspace=workspace, user=user, seed=options["seed"])

            load_all_seeders()
            seeders = get_seeders()

            for registered in seeders:
                summary = registered.fn(ctx)
                self.stdout.write(f"  {registered.name:<18} {summary}")

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("Demo data ready."))
        self.stdout.write("")
        self.stdout.write(f"  Workspace  {workspace.name} ({workspace.slug})")
        self.stdout.write(f"  Login      {email}")
        self.stdout.write(f"  Password   {password}")
        self.stdout.write("")
        self.stdout.write("  Lexware and Clockify are DISABLED — everything above is local data.")
        self.stdout.write("")

    def _reset(self) -> None:
        deleted, _ = Workspace.objects.filter(slug=DEMO_WORKSPACE_SLUG).delete()
        if deleted:
            self.stdout.write(self.style.WARNING(f"  reset              removed {deleted} rows"))

    def _create_workspace(self) -> Workspace:
        workspace, created = Workspace.objects.get_or_create(
            slug=DEMO_WORKSPACE_SLUG,
            defaults={
                "name": "Demo Softwareentwicklung",
                "legal_name": "Max Mustermann Softwareentwicklung",
                "legal_form": "Einzelunternehmen",
                "owner_name": "Max Mustermann",
                "email": "kontakt@demo.local",
                "phone": "+49 761 1234567",
                "website": "https://demo.local",
                "address_street": "Musterstraße 42",
                "address_zip": "79112",
                "address_city": "Freiburg",
                "address_country_code": "DE",
                "tax_number": "12345/67890",
                "vat_id": "DE123456789",
                "small_business": False,
                "bank_name": "Demo Bank",
                "bank_iban": "DE02120300000000202051",
                "bank_bic": "BYLADEM1001",
                "default_currency": "EUR",
                "default_hourly_rate": "95.00",
                "default_payment_term_days": 14,
            },
        )
        self.stdout.write(
            f"  workspace          {'created' if created else 'exists'}: {workspace.name}"
        )
        return workspace

    def _create_user(self, email: str, password: str) -> User:
        user, created = User.objects.get_or_create(
            email=email.lower(),
            defaults={
                "first_name": "Max",
                "last_name": "Mustermann",
                "is_staff": True,
                "is_superuser": True,
                "avatar_color": "#6366f1",
                "time_zone": "Europe/Berlin",
            },
        )
        # Always reset the password so a stale demo login can't lock anyone out.
        user.set_password(password)
        user.save()
        self.stdout.write(f"  user               {'created' if created else 'updated'}: {email}")
        return user

    def _create_membership(self, workspace: Workspace, user: User) -> None:
        WorkspaceMembership.objects.update_or_create(
            workspace=workspace,
            user=user,
            defaults={"role": WorkspaceRole.OWNER, "is_active": True, "is_default": True},
        )
        self.stdout.write("  membership         owner")
