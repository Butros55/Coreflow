"""Demo data seeding registry.

Each phase contributes a seeder rather than growing one monolithic command. A
seeder is a callable taking a :class:`SeedContext` and returning a short summary
line. They run in ``order`` sequence, so later phases can rely on earlier data.

Seeders must be **idempotent** — ``make seed`` is expected to be safe to run
repeatedly against an existing database.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from apps.accounts.models import User, Workspace


@dataclass
class SeedContext:
    """Shared state handed to every seeder."""

    workspace: Workspace
    user: User
    # Deterministic so a reseeded database produces identical demo data —
    # snapshot tests and screenshots stay stable.
    seed: int = 20240101
    verbose: bool = False
    created: dict[str, int] = field(default_factory=dict)

    def record(self, label: str, count: int) -> None:
        self.created[label] = self.created.get(label, 0) + count


SeederFn = Callable[[SeedContext], str]


@dataclass(order=True)
class _Registered:
    order: int
    name: str = field(compare=False)
    fn: SeederFn = field(compare=False)


_REGISTRY: list[_Registered] = []


def register_seeder(name: str, order: int = 100) -> Callable[[SeederFn], SeederFn]:
    """Register a demo-data seeder.

    Usage::

        @register_seeder("clients", order=10)
        def seed_clients(ctx: SeedContext) -> str:
            ...
            return "12 clients"
    """

    def decorator(fn: SeederFn) -> SeederFn:
        _REGISTRY.append(_Registered(order=order, name=name, fn=fn))
        return fn

    return decorator


def get_seeders() -> list[_Registered]:
    """Return registered seeders in run order."""
    return sorted(_REGISTRY)


def load_all_seeders() -> None:
    """Import every app's ``seeds`` module so its decorators run.

    Import-time registration means a phase adds a seeder by creating one file,
    with no central list to update and forget.
    """
    from importlib import import_module

    from django.apps import apps as django_apps

    for app_config in django_apps.get_app_configs():
        if not app_config.name.startswith("apps."):
            continue
        try:
            import_module(f"{app_config.name}.seeds")
        except ModuleNotFoundError as exc:
            # The app simply has no seeder — fine. But a genuine ImportError
            # *inside* a seeds module would also surface here as
            # ModuleNotFoundError for a nested import, so only swallow the case
            # where the seeds module itself is absent.
            if exc.name not in (f"{app_config.name}.seeds", "seeds"):
                raise
