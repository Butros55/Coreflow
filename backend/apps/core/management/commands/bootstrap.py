"""Create a real user + workspace for productive use — no demo data.

    python manage.py bootstrap --email you@example.com --workspace-name "Meine Firma"

Also installs the shipped tax rulesets (needed for the reserve forecast) and an
empty tax profile for the current year. Idempotent: an existing user's password
is NEVER reset (unlike the demo seed), an existing workspace is reused.
"""

from __future__ import annotations

import datetime as dt
import secrets
from typing import Any

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.accounts.models import User, Workspace, WorkspaceMembership, WorkspaceRole
from apps.accounts.services import provision_workspace
from apps.finance.models import TaxProfile
from apps.finance.rulesets import install_default_rulesets


class Command(BaseCommand):
    help = "Create a productive user + workspace without any demo data."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--email", required=True, help="Login e-mail of the owner.")
        parser.add_argument(
            "--workspace-name", required=True, help='Company/workspace name, e.g. "Meine Firma".'
        )
        parser.add_argument(
            "--password",
            default=None,
            help="Owner password. Omitted ⇒ a secure one is generated and printed ONCE.",
        )
        parser.add_argument("--owner-name", default="", help='Display name, e.g. "Max Mustermann".')
        parser.add_argument(
            "--small-business",
            action="store_true",
            help="Kleinunternehmer nach §19 UStG (drives the invoice tax default).",
        )
        parser.add_argument(
            "--superuser",
            action="store_true",
            help="Also grant Django-admin access (break-glass tooling).",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        email = str(options["email"]).lower().strip()
        workspace_name = str(options["workspace_name"]).strip()
        if not workspace_name:
            raise CommandError("--workspace-name darf nicht leer sein.")

        password = options["password"]
        generated = False
        if not password:
            password = secrets.token_urlsafe(12)
            generated = True

        owner_name = str(options["owner_name"]).strip()
        first_name, _, last_name = owner_name.partition(" ")

        with transaction.atomic():
            user, user_created = User.objects.get_or_create(
                email=email,
                defaults={
                    "first_name": first_name,
                    "last_name": last_name,
                    "is_staff": bool(options["superuser"]),
                    "is_superuser": bool(options["superuser"]),
                    "time_zone": "Europe/Berlin",
                },
            )
            if user_created:
                user.set_password(password)
                user.save()

            existing = Workspace.objects.filter(
                name=workspace_name,
                memberships__user=user,
                memberships__role=WorkspaceRole.OWNER,
            ).first()
            if existing is not None:
                workspace, ws_created = existing, False
                WorkspaceMembership.objects.update_or_create(
                    workspace=workspace,
                    user=user,
                    defaults={"role": WorkspaceRole.OWNER, "is_active": True, "is_default": True},
                )
            else:
                # Same provisioning path as the in-app "Neuer Workspace" flow.
                workspace = provision_workspace(
                    name=workspace_name,
                    owner=user,
                    small_business=bool(options["small_business"]),
                    owner_name=owner_name,
                    email=email,
                )
                ws_created = True

            rulesets_installed = install_default_rulesets()
            year = dt.date.today().year
            _, profile_created = TaxProfile.objects.get_or_create(
                workspace=workspace,
                tax_year=year,
                defaults={"small_business": bool(options["small_business"])},
            )

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("Bootstrap complete — no demo data was created."))
        self.stdout.write("")
        self.stdout.write(f"  Workspace   {workspace.name} ({workspace.slug})")
        self.stdout.write(
            f"              {'created' if ws_created else 'already existed — reused'}"
        )
        self.stdout.write(f"  Login       {email}")
        if user_created:
            if generated:
                self.stdout.write(f"  Password    {password}")
                self.stdout.write("              (generated — shown only this once, store it now)")
            else:
                self.stdout.write("  Password    as provided")
        else:
            self.stdout.write("  Password    unchanged (existing user is never reset)")
        self.stdout.write(
            f"  Tax         profile {year} {'created' if profile_created else 'exists'}, "
            f"{rulesets_installed} ruleset(s) newly installed"
        )
        self.stdout.write("")
        self.stdout.write("  Next steps:")
        self.stdout.write("    1. Log in and complete the company profile under Einstellungen.")
        self.stdout.write("    2. Review the Steuerprofil (Hebesatz, Krankenversicherung, …).")
        self.stdout.write("    3. Set LEXWARE_ENABLED/LEXWARE_API_KEY in .env and run the")
        self.stdout.write("       connection test in Einstellungen → Integrationen.")
        self.stdout.write("")
