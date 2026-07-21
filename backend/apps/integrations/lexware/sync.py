"""Full import from Lexware: contacts → clients, invoices → local mirrors.

Direction rules (docs/integrations/lexware.md §8):

* **Contacts** seed local clients ONCE: matched by exact name to unlinked
  clients, otherwise created with the Lexware master data. After linking,
  Coreflow owns the CRM fields — the import never overwrites an existing
  client (mapping lives in ``ExternalObjectLink``).
* **Invoices** are Lexware-owned mirrors: number, status, totals, dates come
  from the voucher and are not locally editable (status ≠ draft_local). After
  each mirror lands, open local time entries are conservatively matched to its
  lines (see ``matching.py``) and marked as billed via Lexware.
* Everything is idempotent via links + ``sync_hash`` — the import button can
  be pressed any number of times without duplicating a single record.

Lexware has NO project resource — projects remain Coreflow-only.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING, Any

from django.db import transaction
from django.db.models import Q

from apps.core.logging import get_logger
from apps.core.money import money
from apps.crm.models import Client, ClientStatus
from apps.integrations.lexware.client import LexwareClient
from apps.integrations.lexware.mapping import apply_lexware_invoice
from apps.integrations.models import (
    ExternalObjectLink,
    Provider,
    SyncDirection,
    SyncJob,
    SyncStatus,
)
from apps.invoicing.models import Invoice, InvoiceLine, InvoiceStatus, TaxType

if TYPE_CHECKING:
    from apps.accounts.models import User, Workspace

logger = get_logger("integrations.lexware.sync")

# The voucherlist search window hard-caps at 10,000 elements (§3.2). A
# one-person company will not reach it; if one ever does, the import refuses
# loudly instead of silently truncating.
MAX_SEARCH_WINDOW = 9_500


class LexwareImport:
    """One workspace's full import session."""

    def __init__(
        self,
        workspace: Workspace,
        *,
        trigger: str = "manual",
        triggered_by: User | None = None,
    ) -> None:
        self.workspace = workspace
        self.trigger = trigger
        self.triggered_by = triggered_by

    # -- plumbing ----------------------------------------------------------

    def _job(self, resource_type: str) -> SyncJob:
        return SyncJob.objects.create(
            workspace=self.workspace,
            provider=Provider.LEXWARE,
            resource_type=resource_type,
            direction=SyncDirection.INBOUND,
            trigger=self.trigger,
            is_full_sync=True,
            triggered_by=self.triggered_by,
        )

    def _links(self, resource_type: str) -> dict[str, ExternalObjectLink]:
        return {
            link.external_id: link
            for link in ExternalObjectLink.objects.filter(
                workspace=self.workspace,
                provider=Provider.LEXWARE,
                resource_type=resource_type,
            )
        }

    def _create_link(
        self, resource_type: str, external_id: str, local_type: str, local_id: Any
    ) -> ExternalObjectLink:
        link = ExternalObjectLink.objects.create(
            workspace=self.workspace,
            provider=Provider.LEXWARE,
            resource_type=resource_type,
            external_id=external_id,
            local_object_type=local_type,
            local_object_id=local_id,
        )
        link.mark_synced({"imported": True})
        return link

    @staticmethod
    def _iter_spring_pages(fetch: Any) -> list[dict[str, Any]]:
        """Collect a Spring-paginated listing ({content, last, number}, §3.2)."""
        items: list[dict[str, Any]] = []
        page = 0
        while True:
            data = fetch(page)
            total = int(data.get("totalElements") or 0)
            if total > MAX_SEARCH_WINDOW:
                raise RuntimeError(
                    f"Lexware meldet {total} Einträge — über dem 10.000er-Suchfenster. "
                    "Import bitte melden; er muss dann nach Datum gefenstert werden."
                )
            items.extend(data.get("content") or [])
            if data.get("last", True):
                return items
            page += 1

    # -- contacts → clients ------------------------------------------------

    def import_contacts(self, client_conn: LexwareClient) -> SyncJob:
        job = self._job("contact")
        job.mark_running()
        links = self._links("contact")

        contacts = self._iter_spring_pages(lambda p: client_conn.list_contacts(page=p, size=250))
        for contact in contacts:
            roles = contact.get("roles") or {}
            if "customer" not in roles:
                # Vendors etc. — Coreflow's CRM models customers only.
                job.records_skipped += 1
                continue
            job.records_processed += 1
            external_id = str(contact.get("id"))
            if external_id in links:
                job.records_skipped += 1
                # Clients imported before richer master data existed (contact
                # persons, tax ids) get the gaps filled — empty fields only,
                # Coreflow-owned CRM data is never overwritten.
                self._backfill_client_master_data(links[external_id], contact)
                continue
            outcome = self._link_or_create_client(contact)
            if outcome == "created":
                job.records_created += 1
            elif outcome == "linked":
                job.records_updated += 1
            else:
                job.records_failed += 1

        job.save()
        job.mark_finished(SyncStatus.SUCCESS if job.records_failed == 0 else SyncStatus.PARTIAL)
        return job

    def _link_or_create_client(self, contact: dict[str, Any]) -> str:
        external_id = str(contact.get("id"))
        name = _contact_display_name(contact)
        if not name:
            return "failed"

        linked_ids = ExternalObjectLink.objects.filter(
            workspace=self.workspace, provider=Provider.LEXWARE, resource_type="contact"
        ).values_list("local_object_id", flat=True)
        match = (
            Client.objects.filter(workspace=self.workspace, name__iexact=name)
            .exclude(pk__in=linked_ids)
            .first()
        )
        if match is not None:
            link = self._create_link("contact", external_id, "crm.Client", match.pk)
            self._backfill_client_master_data(link, contact)
            return "linked"

        billing = _first(contact.get("addresses", {}).get("billing"))
        shipping = _first(contact.get("addresses", {}).get("shipping"))
        company = contact.get("company") or {}
        customer_number = str((contact.get("roles", {}).get("customer") or {}).get("number") or "")
        # Never collide with the local K-… numbering; on clash keep it blank.
        if (
            customer_number
            and Client.objects.filter(
                workspace=self.workspace, client_number=customer_number
            ).exists()
        ):
            customer_number = ""

        with transaction.atomic():
            local_client = Client.objects.create(
                workspace=self.workspace,
                name=name,
                client_number=customer_number,
                status=ClientStatus.ACTIVE,
                archived=bool(contact.get("archived", False)),
                email=_first_of_any(contact.get("emailAddresses")),
                phone=_first_of_any(contact.get("phoneNumbers")),
                billing_street=str(billing.get("street") or ""),
                billing_zip=str(billing.get("zip") or ""),
                billing_city=str(billing.get("city") or ""),
                billing_country_code=str(billing.get("countryCode") or "DE")[:2],
                shipping_street=str(shipping.get("street") or ""),
                shipping_zip=str(shipping.get("zip") or ""),
                shipping_city=str(shipping.get("city") or ""),
                shipping_country_code=str(shipping.get("countryCode") or "")[:2],
                tax_number=str(company.get("taxNumber") or ""),
                vat_id=str(company.get("vatRegistrationId") or ""),
                notes=str(contact.get("note") or ""),
            )
            self._create_link("contact", external_id, "crm.Client", local_client.pk)
            self._import_contact_persons(local_client, contact)
        return "created"

    def _backfill_client_master_data(
        self, link: ExternalObjectLink, contact: dict[str, Any]
    ) -> None:
        """Fill EMPTY client fields from Lexware; local values always win."""
        client = Client.objects.filter(workspace=self.workspace, pk=link.local_object_id).first()
        if client is None:
            return
        company = contact.get("company") or {}
        billing = _first(contact.get("addresses", {}).get("billing"))
        shipping = _first(contact.get("addresses", {}).get("shipping"))
        updates: list[str] = []
        fillable = {
            "tax_number": str(company.get("taxNumber") or ""),
            "vat_id": str(company.get("vatRegistrationId") or ""),
            "email": _first_of_any(contact.get("emailAddresses")),
            "phone": _first_of_any(contact.get("phoneNumbers")),
            "billing_street": str(billing.get("street") or ""),
            "billing_zip": str(billing.get("zip") or ""),
            "billing_city": str(billing.get("city") or ""),
            "shipping_street": str(shipping.get("street") or ""),
            "shipping_zip": str(shipping.get("zip") or ""),
            "shipping_city": str(shipping.get("city") or ""),
            "shipping_country_code": str(shipping.get("countryCode") or "")[:2],
            "notes": str(contact.get("note") or ""),
        }
        for field, value in fillable.items():
            if value and not getattr(client, field):
                setattr(client, field, value)
                updates.append(field)

        # The Lexware customer number fills an empty local one — with the same
        # collision guard as on create, since K-… numbering may have claimed it.
        customer_number = str((contact.get("roles", {}).get("customer") or {}).get("number") or "")
        if (
            customer_number
            and not client.client_number
            and not Client.objects.filter(workspace=self.workspace, client_number=customer_number)
            .exclude(pk=client.pk)
            .exists()
        ):
            client.client_number = customer_number
            updates.append("client_number")

        if updates:
            client.save(update_fields=[*updates, "updated_at"])
        if not client.contacts.exists():
            self._import_contact_persons(client, contact)

    def _import_contact_persons(self, client: Client, contact: dict[str, Any]) -> None:
        """Mirror Lexware contact persons as CRM contacts (once, never merged)."""
        from apps.crm.models import ClientContact

        persons = (contact.get("company") or {}).get("contactPersons") or []
        has_primary = client.contacts.filter(is_primary=True).exists()
        for person in persons:
            first = str(person.get("firstName") or "").strip()
            last = str(person.get("lastName") or "").strip()
            if not (first or last):
                continue
            is_primary = bool(person.get("primary")) and not has_primary
            ClientContact.objects.create(
                workspace=self.workspace,
                client=client,
                first_name=first,
                last_name=last,
                email=str(person.get("emailAddress") or ""),
                phone=str(person.get("phoneNumber") or ""),
                is_primary=is_primary,
            )
            has_primary = has_primary or is_primary

    # -- invoices ----------------------------------------------------------

    def import_invoices(self, client_conn: LexwareClient) -> SyncJob:
        from apps.integrations.lexware.matching import match_invoice_time_entries
        from apps.integrations.lexware.tasks import _apply_payment_state

        job = self._job("invoice")
        job.mark_running()
        links = self._links("invoice")
        contact_links = self._links("contact")

        entries = self._iter_spring_pages(
            lambda p: client_conn.voucherlist("invoice", "any", page=p)
        )
        entries_matched = 0
        for entry in entries:
            external_id = str(entry.get("id"))
            if external_id in links:
                # Already mirrored (either imported before or created by us) —
                # the periodic status sync keeps those fresh. Matching still
                # runs so mirrors from before the matcher existed (or whose
                # hours arrived later, e.g. via Clockodo) get their entries.
                job.records_skipped += 1
                entries_matched += self._match_existing(links[external_id])
                continue
            job.records_processed += 1
            try:
                full = client_conn.get_invoice(external_id)
                local_client = self._resolve_invoice_client(full, contact_links, client_conn)
                if local_client is None:
                    job.records_failed += 1
                    continue
                invoice = self._create_invoice_mirror(full, local_client)
                if invoice.status in (InvoiceStatus.OPEN, InvoiceStatus.PAID):
                    _apply_payment_state(client_conn, invoice, external_id)
                    invoice.save()
                self._create_link("invoice", external_id, "invoicing.Invoice", invoice.pk)
                entries_matched += match_invoice_time_entries(
                    invoice, fallback_user=self.triggered_by
                )
                job.records_created += 1
            except Exception as exc:
                job.records_failed += 1
                logger.warning(
                    "lexware_invoice_import_failed", external_id=external_id, error=str(exc)
                )

        if entries_matched:
            logger.info(
                "lexware_import_matched_entries",
                workspace_id=str(self.workspace.pk),
                entries=entries_matched,
            )
        try:
            self._derive_client_master_from_invoices()
        except Exception as exc:
            logger.warning("lexware_client_master_derivation_failed", error=str(exc))
        job.save()
        job.mark_finished(SyncStatus.SUCCESS if job.records_failed == 0 else SyncStatus.PARTIAL)
        return job

    def _derive_client_master_from_invoices(self) -> int:
        """Fill Zahlungsziel + „Kunde seit" from Lexware-linked invoices.

        The contacts API exposes neither payment terms nor a created date
        (lexware.md §4.2), so the vouchers are the only source: customer_since
        = date of the earliest invoice, payment_term_days = the most recent
        invoice's term. Empty local fields only — Coreflow-owned values win.
        """
        linked_ids = ExternalObjectLink.objects.filter(
            workspace=self.workspace, provider=Provider.LEXWARE, resource_type="invoice"
        ).values_list("local_object_id", flat=True)
        invoices = (
            Invoice.objects.filter(workspace=self.workspace, pk__in=linked_ids)
            .exclude(status=InvoiceStatus.VOIDED)
            .exclude(invoice_date=None)
            .order_by("invoice_date")
            .only("client", "invoice_date", "payment_term_days")
        )
        earliest_date: dict[Any, Any] = {}
        latest_term: dict[Any, int | None] = {}
        for invoice in invoices:
            earliest_date.setdefault(invoice.client_id, invoice.invoice_date)
            latest_term[invoice.client_id] = invoice.payment_term_days

        updated = 0
        clients = Client.objects.filter(
            workspace=self.workspace, pk__in=earliest_date.keys()
        ).filter(Q(customer_since=None) | Q(payment_term_days=None))
        for client in clients:
            updates: list[str] = []
            if client.customer_since is None:
                client.customer_since = earliest_date[client.pk]
                updates.append("customer_since")
            if client.payment_term_days is None and latest_term.get(client.pk):
                client.payment_term_days = latest_term[client.pk]
                updates.append("payment_term_days")
            if updates:
                client.save(update_fields=[*updates, "updated_at"])
                updated += 1
        if updated:
            logger.info(
                "lexware_client_master_derived",
                workspace_id=str(self.workspace.pk),
                clients=updated,
            )
        return updated

    def _match_existing(self, link: ExternalObjectLink) -> int:
        """Retrofit time-entry matches onto an already-mirrored invoice."""
        from apps.integrations.lexware.matching import match_invoice_time_entries

        invoice = Invoice.objects.filter(workspace=self.workspace, pk=link.local_object_id).first()
        if invoice is None:
            return 0
        try:
            return match_invoice_time_entries(invoice, fallback_user=self.triggered_by)
        except Exception as exc:
            logger.warning("lexware_entry_match_failed", invoice_id=str(invoice.pk), error=str(exc))
            return 0

    def _resolve_invoice_client(
        self,
        full: dict[str, Any],
        contact_links: dict[str, ExternalObjectLink],
        client_conn: LexwareClient,
    ) -> Client | None:
        address = full.get("address") or {}
        contact_id = address.get("contactId")
        if contact_id:
            link = contact_links.get(str(contact_id))
            if link is None:
                # Contact not imported yet (e.g. lost the customer role):
                # fetch it directly so the invoice still lands attached.
                contact = client_conn.get_contact(str(contact_id))
                self._link_or_create_client(contact)
                contact_links.update(self._links("contact"))
                link = contact_links.get(str(contact_id))
            if link is not None:
                return Client.objects.filter(pk=link.local_object_id).first()
            return None

        # One-time address: match by name, otherwise create a minimal client —
        # the person WAS billed, they belong in the CRM.
        name = str(address.get("name") or "").strip()
        if not name:
            return None
        match: Client | None = Client.objects.filter(
            workspace=self.workspace, name__iexact=name
        ).first()
        if match is not None:
            return match
        return Client.objects.create(
            workspace=self.workspace,
            name=name,
            status=ClientStatus.ACTIVE,
            billing_street=str(address.get("street") or ""),
            billing_zip=str(address.get("zip") or ""),
            billing_city=str(address.get("city") or ""),
            billing_country_code=str(address.get("countryCode") or "DE")[:2],
        )

    def _create_invoice_mirror(self, full: dict[str, Any], local_client: Client) -> Invoice:
        tax_conditions = full.get("taxConditions") or {}
        raw_tax_type = str(tax_conditions.get("taxType") or "")
        tax_type = (
            raw_tax_type
            if raw_tax_type in (TaxType.NET, TaxType.GROSS, TaxType.VATFREE)
            else TaxType.NET
        )

        line_items = [item for item in (full.get("lineItems") or []) if item.get("type") != "text"]
        tax_rate = _first_line_tax_rate(line_items, tax_type)

        payment_conditions = full.get("paymentConditions") or {}
        term_days = payment_conditions.get("paymentTermDuration")

        with transaction.atomic():
            invoice = Invoice.objects.create(
                workspace=self.workspace,
                client=local_client,
                status=InvoiceStatus.DRAFT_REMOTE,  # apply() sets the real one
                tax_type=tax_type,
                tax_rate=tax_rate,
                currency="EUR",
                title=str(full.get("title") or "Rechnung"),
                introduction=str(full.get("introduction") or ""),
                remark=str(full.get("remark") or ""),
                payment_term_days=int(term_days)
                if term_days
                else self.workspace.default_payment_term_days,
            )
            for order, item in enumerate(line_items):
                unit_price = item.get("unitPrice") or {}
                price = _decimal(unit_price.get("netAmount"))
                if price is None:
                    price = _decimal(unit_price.get("grossAmount")) or Decimal("0.00")
                quantity = _decimal(item.get("quantity")) or Decimal("0")
                line = InvoiceLine(
                    workspace=self.workspace,
                    invoice=invoice,
                    title=str(item.get("name") or "Leistung"),
                    description=str(item.get("description") or ""),
                    quantity=quantity,
                    unit=str(item.get("unitName") or ""),
                    unit_price=money(price),
                    tax_rate=_decimal(unit_price.get("taxRatePercentage")) or Decimal("0.00"),
                    order=order,
                )
                line.recompute()
                line.save()

            # Lexware-owned fields: number, status, dates, totals.
            apply_lexware_invoice(invoice, full)
            if invoice.status == InvoiceStatus.DRAFT_LOCAL:
                invoice.status = InvoiceStatus.DRAFT_REMOTE
            invoice.save()
        return invoice

    # -- orchestration -----------------------------------------------------

    def full_import(self, client_conn: LexwareClient) -> list[SyncJob]:
        jobs = [
            self.import_contacts(client_conn),
            self.import_invoices(client_conn),
        ]
        logger.info(
            "lexware_full_import_done",
            workspace_id=str(self.workspace.pk),
            jobs={job.resource_type: job.status for job in jobs},
        )
        return jobs


# -- small parsers ---------------------------------------------------------


def _contact_display_name(contact: dict[str, Any]) -> str:
    company = contact.get("company") or {}
    if company.get("name"):
        return str(company["name"]).strip()
    person = contact.get("person") or {}
    parts = [str(person.get("firstName") or ""), str(person.get("lastName") or "")]
    return " ".join(part for part in parts if part).strip()


def _first(value: Any) -> dict[str, Any]:
    if isinstance(value, list) and value and isinstance(value[0], dict):
        return value[0]
    return {}


def _first_of_any(mapping: Any) -> str:
    """First entry across the typed lists (business, office, …), §4.2."""
    if not isinstance(mapping, dict):
        return ""
    for key in ("business", "office", "mobile", "private", "fax", "other"):
        values = mapping.get(key)
        if isinstance(values, list) and values:
            return str(values[0])
    return ""


def _decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _first_line_tax_rate(line_items: list[dict[str, Any]], tax_type: str) -> Decimal:
    if tax_type == TaxType.VATFREE:
        return Decimal("0.00")
    for item in line_items:
        rate = _decimal((item.get("unitPrice") or {}).get("taxRatePercentage"))
        if rate is not None and rate > 0:
            return rate
    return Decimal("19.00")
