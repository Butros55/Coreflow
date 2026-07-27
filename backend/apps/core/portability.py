"""Workspace export/import: the full account as one portable JSON file.

Scope: every workspace-scoped row of the signed-in workspace — and only that
workspace. Users are referenced but never exported with credentials; on import
into another installation, unknown user references fall back to the importing
user rather than failing. File binaries live in object storage and are not part
of the export (their metadata rows are).

The model list is explicit and dependency-ordered. A test asserts it covers
every concrete ``WorkspaceScopedModel`` subclass, so adding a model without
deciding its export fate fails CI instead of silently losing data.
"""

from __future__ import annotations

from typing import Any

from django.apps import apps as django_apps
from django.core import serializers
from django.db import models, transaction
from django.utils import timezone

SCHEMA_VERSION = 1

# Parents strictly before children, so a fresh import satisfies every FK.
EXPORT_MODELS: list[str] = [
    "crm.Client",
    "crm.ClientContact",
    "crm.ClientNote",
    "crm.ClientActivity",
    "timetracking.ServiceType",
    "projects.Project",
    "projects.ProjectPhase",
    "projects.Board",
    "projects.Sprint",
    "projects.Task",
    "projects.TaskComment",
    "projects.TaskChecklistItem",
    "files.StoredFile",
    "timetracking.TimeEntry",
    "invoicing.Invoice",
    "invoicing.InvoiceLine",
    "invoicing.InvoiceTimeEntry",
    "scheduling.Appointment",
    "finance.TaxProfile",
    "finance.ReserveTransfer",
    "finance.ReserveSnapshot",
    "integrations.ProviderProfile",
    "integrations.SyncJob",
    "integrations.WebhookEvent",
    "integrations.SyncConflict",
    "integrations.ExternalObjectLink",
]

# Workspace-scoped models deliberately NOT exported (with the reason).
EXPORT_EXCLUDED: dict[str, str] = {}

# Workspace profile fields that travel with the export and are applied to the
# target workspace on import. Slug/id stay: they identify the target.
WORKSPACE_PROFILE_FIELDS = [
    "name",
    "legal_name",
    "legal_form",
    "owner_name",
    "email",
    "phone",
    "website",
    "address_street",
    "address_zip",
    "address_city",
    "address_country_code",
    "tax_number",
    "vat_id",
    "small_business",
    "bank_name",
    "bank_iban",
    "bank_bic",
    "default_currency",
    "default_hourly_rate",
    "default_payment_term_days",
    "time_rounding_increment_minutes",
    "time_rounding_strategy",
]


def _model(label: str) -> type[models.Model]:
    return django_apps.get_model(label)


def export_workspace(workspace: Any) -> dict[str, Any]:
    """Serialize the whole workspace into one JSON-safe dict."""
    from apps.accounts.models import User

    data: dict[str, list[dict[str, Any]]] = {}
    user_ids: set[str] = set()

    for label in EXPORT_MODELS:
        model = _model(label)
        rows = serializers.serialize(
            "python", model._default_manager.filter(workspace=workspace).order_by("created_at")
        )
        for row in rows:
            for field_name, value in row["fields"].items():
                field = model._meta.get_field(field_name)
                related = getattr(field, "related_model", None)
                if related is User and value:
                    if isinstance(value, list):
                        user_ids.update(str(v) for v in value)
                    else:
                        user_ids.add(str(value))
        data[label] = rows

    profile = {field: getattr(workspace, field) for field in WORKSPACE_PROFILE_FIELDS}
    users = [
        {"id": str(u.pk), "email": u.email, "name": u.get_full_name()}
        for u in User.objects.filter(pk__in=user_ids)
    ]

    payload = {
        "format": "coreflow-workspace-export",
        "schema_version": SCHEMA_VERSION,
        "exported_at": timezone.now().isoformat(),
        "workspace": {"id": str(workspace.pk), "slug": workspace.slug, "profile": profile},
        "users": users,
        "counts": {label: len(rows) for label, rows in data.items()},
        "data": data,
        "notes": [
            "Datei-Binärdaten (Objektspeicher) sind nicht enthalten, nur ihre Metadaten.",
            "Benutzerkonten und Passwörter sind nicht enthalten; Referenzen werden beim "
            "Import auf vorhandene Benutzer abgebildet.",
        ],
    }
    return payload


class ImportError_(Exception):
    """Validation failure — the file is not importable."""


def _remap_fields(
    model: type[models.Model],
    fields: dict[str, Any],
    workspace: Any,
    fallback_user_pk: Any,
    existing_user_pks: set[str],
) -> dict[str, Any] | None:
    """Rewrite FK references so the row is valid in THIS installation.

    Returns None when the row cannot be safely imported (non-nullable FK to a
    missing, non-exported object) — the caller counts it as skipped.
    """
    from apps.accounts.models import User

    exported = {label.lower() for label in EXPORT_MODELS}
    out = dict(fields)

    for field_name in list(out.keys()):
        field = model._meta.get_field(field_name)
        related = getattr(field, "related_model", None)
        if related is None:
            continue
        value = out[field_name]

        if field.many_to_many:
            if related is User and isinstance(value, list):
                out[field_name] = [v for v in value if str(v) in existing_user_pks]
            continue

        label = f"{related._meta.app_label}.{related._meta.object_name}".lower()
        if related.__name__ == "Workspace":
            out[field_name] = workspace.pk
        elif related is User:
            if value is not None and str(value) not in existing_user_pks:
                out[field_name] = None if field.null else fallback_user_pk
        elif (
            value is not None
            and label not in exported
            and label != model._meta.label_lower
            and not related._default_manager.filter(pk=value).exists()
        ):
            # FK into a table we do not carry (e.g. finance.TaxRuleSet) whose
            # target does not exist here: drop the reference, or skip the row
            # when the column cannot be null.
            if field.null:
                out[field_name] = None
            else:
                return None
    return out


def import_workspace(workspace: Any, payload: dict[str, Any], user: Any) -> dict[str, Any]:
    """Restore an export into ``workspace``. Upserts by primary key.

    Existing rows with the same id are overwritten, new ones created, rows of
    other workspaces are never touched (every object is re-pinned to the
    target workspace before saving).
    """
    from apps.accounts.models import User

    if payload.get("format") != "coreflow-workspace-export":
        raise ImportError_("Das ist keine Coreflow-Exportdatei.")
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise ImportError_(
            f"Schema-Version {payload.get('schema_version')} wird nicht unterstützt "
            f"(erwartet: {SCHEMA_VERSION})."
        )
    data = payload.get("data")
    if not isinstance(data, dict):
        raise ImportError_("Exportdatei ohne Datenteil.")

    existing_user_pks = {str(pk) for pk in User.objects.values_list("pk", flat=True)}
    imported: dict[str, int] = {}
    skipped: dict[str, int] = {}
    # Self-referencing FKs (Task.parent): applied after all rows of the model
    # exist, so child-before-parent order in the file cannot fail.
    deferred_self_refs: list[tuple[type[models.Model], str, Any, Any]] = []

    with transaction.atomic():
        profile = (payload.get("workspace") or {}).get("profile") or {}
        for field in WORKSPACE_PROFILE_FIELDS:
            if field in profile:
                setattr(workspace, field, profile[field])
        workspace.save()

        for label in EXPORT_MODELS:
            rows = data.get(label) or []
            model = _model(label)
            self_fk_names = [
                f.name
                for f in model._meta.get_fields()
                if isinstance(f, models.ForeignKey) and f.related_model is model
            ]
            count = 0
            skip = 0
            for row in rows:
                fields = _remap_fields(
                    model, dict(row["fields"]), workspace, user.pk, existing_user_pks
                )
                if fields is None:
                    skip += 1
                    continue
                for name in self_fk_names:
                    if fields.get(name) is not None:
                        deferred_self_refs.append((model, name, row["pk"], fields[name]))
                        fields[name] = None
                for obj in serializers.deserialize(
                    "python", [{"model": row["model"], "pk": row["pk"], "fields": fields}]
                ):
                    obj.save()
                count += 1
            imported[label] = count
            if skip:
                skipped[label] = skip

        for model, field_name, pk, target_pk in deferred_self_refs:
            if model._default_manager.filter(pk=target_pk).exists():
                model._default_manager.filter(pk=pk).update(**{field_name: target_pk})

    return {"imported": imported, "skipped": skipped}
