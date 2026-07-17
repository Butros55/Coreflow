# Coreflow — Data Model

Conventions that hold for **every** model:

* **PK** `id: UUID4`, non-editable.
* **Timestamps** `created_at`, `updated_at`, stored **UTC**.
* **Tenancy** every domain model has `workspace: FK → accounts.Workspace`.
* **Money** `DecimalField(max_digits=12, decimal_places=2)`. Never float. Serialised as a **string**.
* **Hours** `DecimalField(max_digits=10, decimal_places=4)` — 4 places so a 37-second entry does not
  round to 0.
* **Rates** `DecimalField(max_digits=10, decimal_places=2)`.
* **Percent** `DecimalField(max_digits=7, decimal_places=4)` (e.g. `19.0000`).

Legend: ✅ implemented · ⬜ planned (phase noted).

---

## 1. Accounts ✅ (Phase 0)

### `accounts.User`
Email-identified; no username.

| Field | Type | Notes |
| --- | --- | --- |
| `email` | EmailField, unique, indexed | lowercased on clean |
| `first_name`, `last_name` | CharField(150), blank | |
| `is_active`, `is_staff` | Boolean | |
| `date_joined` | DateTime | |
| `avatar_color` | CharField(7) | hex fallback tint |
| `locale`, `time_zone` | CharField | `de-DE`, `Europe/Berlin` |

### `accounts.Workspace`
The tenant, and the company profile (Settings → Unternehmensprofil).

`name`, `slug` (unique), `legal_name`, `legal_form`, `owner_name`, `email`, `phone`, `website`,
`address_{street,zip,city,country_code}`, `tax_number` (Steuernummer), `vat_id` (USt-IdNr.),
`small_business` (§19 UStG), `bank_{name,iban,bic}`, `default_currency`, `default_hourly_rate`,
`default_payment_term_days`, `time_rounding_increment_minutes`, `time_rounding_strategy`,
`is_active`.

> `small_business` mirrors the Lexware profile flag once connected. **It does not by itself decide
> the invoice tax type** — see [lexware.md §4.5](integrations/lexware.md); the documented source is
> `profile.taxType`.

### `accounts.WorkspaceMembership`
`workspace`, `user`, `role`, `is_active`, `is_default`, `invited_at`, `joined_at`.

**Roles** (`WorkspaceRole`, ranked): `owner`(40) > `admin`(30) > `member`(20) > `readonly`(10).

**Constraints**
* `unique(workspace, user)`
* `unique(user) where is_default` — at most one default per user, **enforced in the database**;
  two concurrent requests would otherwise both set it.

---

## 2. Integrations ✅ (Phase 0)

### `integrations.ExternalObjectLink`
The mapping between a local object and its remote counterpart. **The reason there are no
`lexware_id` columns on business tables.**

| Field | Notes |
| --- | --- |
| `provider` | `lexware` \| `clockodo` |
| `resource_type` | `contact`, `invoice`, `entry`, … (provider-side name) |
| `local_object_type` | Django label, e.g. `crm.Client` |
| `local_object_id` | UUID (untyped — every PK is a UUID; contenttypes joins aren't worth it) |
| `external_id` | remote id |
| `external_version` | Lexware `version`; Clockodo has none |
| `sync_hash` | `sha256:` of the normalised remote payload |
| `last_synced_at`, `last_remote_modified_at` | |
| `deleted_remotely` | tombstone rather than a local delete |
| `metadata` | JSONB |

**Constraints — these *are* the idempotency guarantee**
* `unique(workspace, provider, resource_type, external_id)` — a replayed webhook updates; it cannot
  duplicate.
* `unique(workspace, provider, resource_type, local_object_id)` — one link per direction.

### `integrations.SyncJob`
`provider`, `resource_type`, `direction`, `status`, `trigger`, `is_full_sync`, `started_at`,
`finished_at`, `records_{processed,created,updated,skipped,failed}`, `error_summary` (truncated to
5 000 — provider bodies are unbounded), `cursor` (JSONB resume point), `triggered_by`.

`cursor` exists because Lexware's 10 000-element search window forces month-by-month full syncs; a
failure resumes rather than restarting.

### `integrations.WebhookEvent`
`provider`, `event_type`, `external_resource_id`, `payload`, `headers` (scrubbed), `received_at`,
`processed_at`, `processing_status`, `retry_count`, `error_message`, `dedupe_key`,
`signature_verified`.

`unique(provider, dedupe_key) where dedupe_key != ''` — **partial**, so the many rows with no
dedupe key don't collide.

### `integrations.SyncConflict`
`provider`, `resource_type`, `local_object_type`, `local_object_id`, `external_id`,
**`local_snapshot`**, **`remote_snapshot`**, `reason`, `detected_at`, `resolution_status`,
`resolution`, `resolved_at`, `resolved_by`, `sync_job`.

Both snapshots are kept so a human can see exactly what diverged. No auto-merge.

### `integrations.ProviderProfile`
`provider`, `external_organization_id`, `connection_id`, `company_name`, `tax_type`,
`small_business`, `subscription_status`, `raw_profile`, `fetched_at`. `unique(workspace, provider)`.

* `external_organization_id` authenticates inbound Lexware webhooks.
* `connection_id` is what a `token.revoked` event carries as its `resourceId`.
* `tax_type` is the **documented, authoritative** default for invoice `taxConditions.taxType`.
* `subscription_status` is stored and displayed but **never branched on** — its enum is undocumented.

---

## 3. CRM ⬜ (Phase 1)

### `crm.Client`
`name`, `short_name`, `legal_form`, `client_number` (unique per workspace), `status`
(`prospect|active|paused|former`), `industry`, `website`, `email`, `phone`,
`billing_address_*`, `shipping_address_*`, `tax_number`, `vat_id`, `default_hourly_rate`,
`payment_term_days`, `default_currency`, `notes`, `tags` (M2M), `acquisition_source`,
`customer_since`, `archived`.

Lexware/Clockodo mapping lives in `ExternalObjectLink`, **not** here.

> Lexware write constraint that shapes this: a contact accepts **at most one entry per list** (one
> billing address, one per email/phone type, one contact person). Coreflow keeps the richer model
> and pushes a **reduced projection**; a remote contact with multi-entry lists is unwritable and
> raises a `SyncConflict` instead of failing opaquely.

### `crm.ClientContact`
`client`, `first_name`, `last_name`, `position`, `email`, `phone`, `mobile`,
`preferred_channel`, `is_primary`, `notes`.
`unique(client) where is_primary` — one primary contact, enforced in the DB.

### `crm.ClientNote`
`client`, `author`, `content` (rich text), `note_type`, `created_at`, `follow_up_at`.

### `crm.ClientActivity`
`client`, `event_type`, `description`, `occurred_at`, plus nullable FKs to `project`, `invoice`,
`appointment`, `note`. Append-only; feeds both the client and global activity streams.

---

## 4. Projects ⬜ (Phase 2)

### `projects.Project`
`client`, `name`, `description`, `status`, `priority`, `start_date`, `target_date`, `lead`,
`team` (M2M User), `default_hourly_rate`, `budget_hours`, `budget_amount`, `billing_model`
(`hourly|fixed|retainer|non_billable`), `progress`, `tags`, `color`, `archived`.

### `projects.ProjectPhase`
`project`, `name`, `order`, `status`, `planned_hours`, `actual_hours`, `start_date`, `end_date`.

### `projects.Board` / `projects.BoardView`
`Board`: `name`, `project`, `board_type`, `default_view`.
`BoardView`: `name`, `view_type` (`table|kanban|list|sprint|calendar|timeline|gantt|dashboard`),
`filters`, `sorting`, `grouping`, `visible_fields`, `owner` (null = workspace-wide), `is_public`.

### `projects.Sprint`
`project`, `board`, `name`, `goal`, `start_date`, `end_date`, `status`, `capacity_hours`.

### `projects.Task`
`project`, `phase`, `board`, `sprint`, `parent` (self-FK for subtasks), `title`, `description`,
`status`, `priority`, `assignees` (M2M), `created_by`, `start_date`, `due_date`,
`estimated_hours`, `actual_hours` (denormalised from time entries), `billable`, `tags`,
**`order`**, `story_points`, `progress`, `archived`.

> **`order` is a fractional rank** (`Decimal`), not an integer index. Dropping a card between two
> others computes the midpoint — **one UPDATE**. Integer positions would renumber the whole column
> on every drag and race under concurrent moves.

### Satellites
`TaskComment`, `TaskAttachment`, `TaskDependency` (`from_task`, `to_task`, `dependency_type`;
`unique(from,to)` + a cycle check), `TaskChecklistItem`, `TaskCustomFieldDefinition`,
`TaskCustomFieldValue`, `TaskActivity`.

### Custom fields
Core fields are **real typed columns**. Only user-defined extras live in JSONB, validated against
their `TaskCustomFieldDefinition` on write. Supported types: text, rich text, number, money, status,
priority, tag, date, date range, person, client, project, task, link, checkbox, progress, hours,
hourly rate, formula.

---

## 5. Time tracking ⬜ (Phase 3)

### `timetracking.ServiceType`
`name`, `description`, `default_hourly_rate`, `default_invoice_text`, `active`.
Maps to a Clockodo *service* when that integration is on.

### `timetracking.TimeEntry`

| Field | Notes |
| --- | --- |
| `user`, `client`, `project`, `phase`, `task` | task/phase optional |
| `service_type` | |
| `description` | |
| `started_at`, `ended_at` | UTC; `ended_at` null ⇒ running |
| `duration_seconds` | integer, the source of truth for duration |
| `source` | `manual` \| `timer` |
| `billable` | Boolean |
| `hourly_rate` | **snapshotted** at creation |
| `computed_amount` | `line_amount(duration, rate)` |
| `billing_status` | see below |
| `invoice_line` | FK, set when invoiced |
| `rounded_from_seconds` | pre-rounding value, kept for the audit trail |

> `hourly_rate` is **copied, not referenced**. Raising a client's rate must not retroactively change
> what last quarter's unbilled work is worth.

**`billing_status` lifecycle**
```
not_billable
open ──▶ marked_for_invoice ──▶ invoice_draft_created ──▶ billed
                                        └──▶ cancelled ──▶ open
```

**Constraints**
* `unique(user) where ended_at IS NULL` — **one running timer per user, in the database**. An
  application-level check loses the race between two tabs.
* `duration_seconds >= 0`.
* Overlap detection warns (does not block) — real work sometimes legitimately overlaps.

---

## 6. Invoicing ⬜ (Phase 5)

### `invoicing.Invoice`
`client`, `project` (optional), **`lexware_id`** (via `ExternalObjectLink`), `invoice_number`
(**Lexware-assigned, read-only**), `status`, `invoice_date`, `due_date`, `net_amount`, `tax_amount`,
`gross_amount`, `open_amount`, `paid_at`, `currency`, `pdf_file`, `lexware_version`,
`last_synced_at`, `tax_type`, `tax_type_note`.

**Status**
```
draft_local ──▶ send_pending ──▶ draft_remote ──▶ open ──▶ paid
                     │                                └──▶ overdue
                     └──▶ (reconciliation) ──▶ draft_remote | SyncConflict
                                                    voided
```
`draft_local` exists before any network call, so composing an invoice never depends on Lexware
being up. `send_pending` exists because **a Lexware 504 may mean the invoice was created** — that
POST is never blindly retried; a reconciliation task searches the voucherlist for a match.

> There is no `finalise` transition. Lexware: *"The status of an invoice cannot be changed via the
> api."* Finalisation happens **in Lexware**; we sync the result.

### `invoicing.InvoiceLine`
`invoice`, `title`, `description`, `quantity`, `unit`, `unit_price`, `tax_rate`, `total_price`,
`order`.

### `invoicing.InvoiceTimeEntry`
`invoice_line`, `time_entry`, `duration_seconds_taken`, `amount_taken`.

> **Double-billing protection — the actual guarantee:**
> ```sql
> CREATE UNIQUE INDEX one_active_invoice_per_time_entry
>   ON invoicing_invoicetimeentry (time_entry_id)
>   WHERE invoice_status != 'cancelled';
> ```
> A status check alone is not enough: two concurrent requests can both read `open` and both pass.
> The index cannot be raced. `billing_status` and a `SELECT … FOR UPDATE` re-check are defence in
> depth on top of it.

---

## 7. Finance ⬜ (Phase 6)

### `finance.TaxProfile`
`tax_year`, `legal_form`, `small_business`, `other_taxable_income`, `trade_tax_multiplier`
(Hebesatz), `trade_tax_allowance` (Freibetrag), `church_tax`, `federal_state`,
`health_insurance_status`, `estimated_health_insurance`, `safety_margin_percent`,
`prepayments_made`, `existing_reserve`.

### `finance.TaxRuleSet`
`tax_year`, `rule_version`, `valid_from`, **`config`** (JSONB), **`sources`** (JSONB), `enabled`.
`unique(tax_year, rule_version)`.

> Rates live in **versioned, sourced data — never in code**. Every value carries a citation to an
> official German source. A tax rate hardcoded in a function is a rate nobody can audit, and it is
> silently wrong the year it changes.

### `finance.ReserveSnapshot`
`snapshot_date`, `revenue_ytd`, `expenses_ytd`, `profit_ytd`, `estimated_income_tax`,
`estimated_soli`, `estimated_church_tax`, `estimated_trade_tax`, `trade_tax_credit`,
`vat_reserve`, `health_insurance_buffer`, `safety_buffer`, `recommended_reserve`,
`actual_reserve`, `reserve_gap`, `calculation_trace` (JSONB), `rule_set`.

`calculation_trace` stores **every step** — the requirement is that the forecast is explainable, and
a number without its derivation is not.

Output always carries: **„Unverbindliche Prognose. Kein Ersatz für eine steuerliche Beratung."**

---

## 8. Scheduling ⬜ (Phase 7)

### `scheduling.Appointment`
`client`, `project`, `title`, `description`, `starts_at`, `ends_at`, `location`, `video_link`,
`participants` (M2M), `status`, `reminder_minutes_before`, `outcome_notes`, `next_steps`,
`ics_uid` (stable across ICS export/import round-trips).

---

## 9. Files ⬜ (Phase 7)

### `files.StoredFile`
`client`, `project`, `task`, `invoice` (all optional), `filename`, `content_type`, `size_bytes`,
`storage_key`, `version`, `description`, `uploaded_by`, `checksum` (sha256, for dedupe).

> **Binaries never go in PostgreSQL.** Object storage (MinIO/S3); the DB holds metadata and a key.
> Downloads are short-lived presigned URLs. Type and size are validated **server-side** — an
> extension is a claim, not a fact.

---

## 10. Relationship overview

```
Workspace ─┬─ Membership ── User
           ├─ Client ─┬─ ClientContact
           │          ├─ ClientNote
           │          ├─ ClientActivity
           │          ├─ Appointment
           │          └─ Project ─┬─ ProjectPhase
           │                      ├─ Board ── BoardView
           │                      ├─ Sprint
           │                      └─ Task ─┬─ Task (parent/subtask)
           │                               ├─ TaskComment / Checklist / Attachment
           │                               ├─ TaskDependency
           │                               └─ TimeEntry
           ├─ ServiceType ── TimeEntry
           ├─ TimeEntry ── InvoiceTimeEntry ── InvoiceLine ── Invoice ── Client
           ├─ TaxProfile / TaxRuleSet / ReserveSnapshot
           ├─ StoredFile
           └─ ExternalObjectLink / SyncJob / WebhookEvent / SyncConflict / ProviderProfile
```

## 11. Deletion and retention

German commercial and tax law (§147 AO, §257 HGB) requires invoices and bookkeeping records to be
kept for **10 years**. This collides with GDPR erasure, so:

* `SoftDeleteModel` for anything with retention weight. `objects` hides deleted rows;
  `all_objects` is for admin/export/retention. **`objects` is declared first on purpose** — Django
  makes the first manager `_default_manager`, which related descriptors and the admin use, so
  ordering them the other way would silently resurrect deleted rows across every relation.
* A GDPR erasure request **pseudonymises** personal fields on retained records rather than deleting
  them, and hard-deletes only what carries no legal hold. Retention is configured by
  `RETENTION_*` env vars.
