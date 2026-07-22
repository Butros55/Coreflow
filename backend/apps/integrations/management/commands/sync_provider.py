"""Run a provider sync from the command line (the Makefile's sync-* targets).

Runs synchronously in-process — no Celery worker needed — for every workspace
whose connection test has succeeded for that provider.
"""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand, CommandError

from apps.integrations.models import Provider, ProviderProfile


class Command(BaseCommand):
    help = "Run a Lexware or Clockify sync for every connected workspace."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("provider", choices=[Provider.LEXWARE.value, Provider.CLOCKIFY.value])
        parser.add_argument(
            "--full",
            action="store_true",
            help="Full sync (masters + long entry window) instead of incremental.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        provider = options["provider"]
        full = bool(options["full"])
        workspaces = [
            profile.workspace
            for profile in ProviderProfile.objects.filter(provider=provider).select_related(
                "workspace"
            )
        ]
        if not workspaces:
            raise CommandError(
                f"Kein Workspace mit erfolgreichem {provider}-Verbindungstest gefunden. "
                "Zuerst im Integrations-Center verbinden."
            )

        if provider == Provider.CLOCKIFY:
            from apps.integrations.clockify.tasks import (
                sync_clockify_full,
                sync_clockify_incremental,
            )

            if full:
                for workspace in workspaces:
                    result = sync_clockify_full(str(workspace.pk))
                    self.stdout.write(f"{workspace.slug}: {result}")
            else:
                self.stdout.write(str(sync_clockify_incremental()))
            return

        from apps.integrations.lexware.tasks import lexware_full_import, sync_lexware_incremental

        if full:
            for workspace in workspaces:
                result = lexware_full_import(str(workspace.pk))
                self.stdout.write(f"{workspace.slug}: {result}")
        else:
            self.stdout.write(str(sync_lexware_incremental()))
