"""Workspace provisioning — shared by the API and the bootstrap command.

A workspace is never created bare: the creator becomes its owner, the current
tax year gets a profile, and the shipped tax rulesets are installed so the
reserve forecast works from minute one. Data separation needs no extra work
here — every domain model is workspace-scoped and every viewset filters by the
active membership, so a fresh workspace simply starts empty.
"""

from __future__ import annotations

import datetime as dt
from typing import TYPE_CHECKING

from django.db import transaction
from django.utils.text import slugify

from apps.accounts.models import User, Workspace, WorkspaceMembership, WorkspaceRole

if TYPE_CHECKING:
    pass


def unique_workspace_slug(name: str) -> str:
    """Slugify with a numeric suffix on collision."""
    base = slugify(name)[:70] or "workspace"
    candidate = base
    suffix = 2
    while Workspace.objects.filter(slug=candidate).exists():
        candidate = f"{base}-{suffix}"
        suffix += 1
    return candidate


@transaction.atomic
def provision_workspace(
    *,
    name: str,
    owner: User,
    small_business: bool = False,
    legal_name: str = "",
    owner_name: str = "",
    email: str = "",
) -> Workspace:
    """Create a workspace with owner membership, tax profile and rulesets.

    The new workspace becomes the owner's default only when they have none yet
    — creating a second workspace must not silently switch the active one.
    """
    from apps.finance.models import TaxProfile
    from apps.finance.rulesets import install_default_rulesets

    workspace = Workspace.objects.create(
        slug=unique_workspace_slug(name),
        name=name,
        legal_name=legal_name or name,
        owner_name=owner_name,
        email=email,
        small_business=small_business,
    )

    has_default = WorkspaceMembership.objects.filter(
        user=owner, is_default=True, is_active=True
    ).exists()
    WorkspaceMembership.objects.create(
        workspace=workspace,
        user=owner,
        role=WorkspaceRole.OWNER,
        is_active=True,
        is_default=not has_default,
    )

    install_default_rulesets()
    TaxProfile.objects.get_or_create(
        workspace=workspace,
        tax_year=dt.date.today().year,
        defaults={"small_business": small_business},
    )
    return workspace
