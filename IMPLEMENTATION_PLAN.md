# Coreflow — Implementation Plan

> Central business management system for a self-employed software developer in Germany:
> CRM, projects, sprints, time tracking, invoicing, Lexware Office, optional Clockodo,
> appointments, revenue analysis, and tax/reserve forecasting in one application.

**Status legend:** ✅ done · 🟡 core delivered, full scope pending · 🚧 in progress · ⬜ planned

| Phase | Scope | Status |
| --- | --- | --- |
| 0 | Repo analysis, planning docs, scaffold, auth, workspaces, dark UI shell | ✅ |
| 1 | CRM: clients, contacts, notes, activities, client dashboard | 🟡 |
| 2 | Projects, phases, boards, sprints, tasks, kanban, task drawer | 🟡 |
| 3 | Internal time tracking (fully Clockodo-independent) | 🟡 |

**🟡 delivered so far (phases 1–3):** full data layer + API with tests, demo seeds, and the
reference-design UI: grouped client tables + client dashboard tabs, kanban with persisted
drag-and-drop + deep-linkable task drawer, table view, week-based time tracking with timer
(DB-enforced single running timer), manual entries, rounding, billing-status lifecycle, global
timer widget, My-Tasks buckets.
**Still open for the full phase scope:** client card view + bulk actions (P1); subtasks UI,
dependencies, timeline/gantt, custom fields, saved views (P2); favourites, overlap warning,
PDF/CSV export, change log (P3). Tracked per phase below.
| 4 | Clockodo integration (optional provider) | ✅ |
| 5 | Lexware Office integration + invoice workflow | ✅ |
| 6 | Finance dashboard + tax/reserve forecast | ✅ |
| 7 | Appointments, files, global activity feed | ✅ |
| 8 | Settings + integration centre | ✅ |
| 9 | Security, privacy, production hardening | ⬜ |
| 10 | Test suite (backend, frontend, E2E) | ⬜ |
| 11 | Documentation + deployment | ⬜ |

**✅ delivered (phases 5–8):** Lexware invoice workflow (compose open entries → 6 grouping
strategies → editable preview → **Lexware draft**, drafts by default, double-billing blocked by a
partial unique index, not just a status check); finance dashboard with revenue breakdowns and a
**transparent step-by-step tax/reserve forecast** (versioned `TaxRuleSet`, §32a EStG as sourced
data — nothing hardcoded — with the non-binding-advice disclaimer on every output); appointments +
ICS import/export + task-from-appointment; file storage in MinIO with type/size guards; and the
settings + integration centre (company profile, service types, tax profile, team, and provider
cards that show real connection state with `.env` enablement hints instead of dead buttons).
**All navigation pages now resolve to real, functional screens — no `ComingSoon` placeholders
remain.**

**✅ Clockodo (phase 4):** full sync engine — customers/projects/services mirrored structurally
both ways (name-match or create, mapping via `ExternalObjectLink` only, CRM fields never
overwritten), users matched by e-mail only, entries pulled inbound with hash idempotency, local
edits pushed back when remote is unchanged, and every true divergence (or any remote change to a
locked/billed entry) surfacing as a `SyncConflict` — never auto-merged. Webhook receiver with
persist-then-ack, constant-time token check, dedupe constraint, and the UI-only registration
handshake surfaced in the integration centre (URL + secret to paste into Clockodo). Billed
invoices push `billable=2` per entry (retried task). Beat: incremental entry sync + Lexware
invoice-status/payment refresh + webhook backstop — all previously referenced task modules now
actually exist and register with the worker.

---

## 0. Repository analysis (done)

The repository was **effectively empty**: one commit (`first commit`) containing a 12-byte
`README.md` with the single line `# Coreflow`. There was no `AGENTS.md`, `pyproject.toml`,
`package.json`, Dockerfile, Makefile, or any existing architecture to preserve.

**Conclusion:** greenfield. The recommended stack from the brief was initialised from scratch,
with the deviations recorded in [§ Stack decisions](#stack-decisions).

### Toolchain verified present on the host

| Tool | Version |
| --- | --- |
| Python | 3.11.5 (3.13 installed via `uv` for the project) |
| uv | 0.11.28 |
| Node | 25.2.1 |
| Docker / Compose | 27.5.1 / v2.32.4 |
| GNU Make | 4.4.1 |

---

## Stack decisions

Resolved versions, and where a deliberate choice differs from "newest available":

| Component | Chosen | Rationale |
| --- | --- | --- |
| Python | **3.13** | Current stable; Django 5.2 LTS supports it. |
| Django | **5.2.16 LTS** | LTS matters for a system holding 10-year accounting records. |
| DRF | 3.17.1 | |
| PostgreSQL | 17 | |
| Celery | 5.6.3 + Beat + django-celery-results | |
| Next.js / React | **16.2.10 / 19.2.7** | Current stable. |
| **TypeScript** | **5.9.3, not 7.0.2** | 7.0 (`latest`) is the brand-new native rewrite. The lint/build ecosystem around it is still settling, and this project needs a reliable build more than it needs the newest compiler. Revisit once `typescript-eslint` support is mature. |
| Tailwind | **4.3.3** | CSS-first config (`@theme` in `globals.css`); no `tailwind.config.js`. |
| **PDF rendering** | **reportlab, not WeasyPrint** | WeasyPrint needs native Pango/Cairo. The developer works on Windows; that would break local `pytest` on import and make host-side dev painful. reportlab is pure Python and renders tabular documents (timesheets) well. |
| shadcn/ui | **hand-written Radix primitives** | The CLI needs interactive network scaffolding; the components here are few and benefit from being fully owned and token-driven. Radix + CVA is the same underlying pattern. |
| Auth | **session cookie, not JWT** | `HttpOnly` cookie cannot be exfiltrated by XSS; frontend and API are same-site, so a token in `localStorage` would trade away security for nothing. |

---

## Architecture principles (established in Phase 0, binding on all later phases)

1. **UUID primary keys everywhere** — safe to expose in URLs, no enumeration, no round-trip for IDs.
2. **`Decimal` money, never float** — via `apps.core.money`. Rounding is `ROUND_HALF_UP` (German
   invoice convention), applied **once**, at the end of a calculation.
3. **UTC storage, `Europe/Berlin` presentation.**
4. **Workspace-scoped from day one** — retrofitting tenancy would mean migrating every table.
5. **Coreflow is authoritative** for clients, projects, boards, sprints, tasks, time entries,
   appointments, budgets, files, forecasts, settings.
6. **Lexware is authoritative** for invoice numbers, finalised invoices, invoice status, PDFs,
   payments, open amounts, and bookkeeping vouchers. We mirror; we never invent.
7. **Clockodo is optional** and authoritative only for records that originate there. The internal
   time tracking must work forever with `CLOCKODO_ENABLED=false`.
8. **All external data is mirrored locally** through `ExternalObjectLink`; sync is idempotent via
   `sync_hash`; conflicts surface to a human and are never auto-merged or silently dropped.
9. **Webhooks are persisted first, processed asynchronously** — both providers send *pointers, not
   data*, so every handler is fetch-then-reconcile.
10. **The server enforces every rule.** UI capability flags hide controls; they are not access
    control.

---

## Phase 0 — delivered

### Backend
* Django project split into `config.settings.{base,dev,test,prod}`. `prod` **refuses to boot** on a
  weak/absent `SECRET_KEY`, a wildcard `ALLOWED_HOSTS`, a non-HTTPS `APP_URL`, or an integration
  enabled without credentials.
* `apps.core`: `UUIDModel`, `TimestampedModel`, `SoftDeleteModel`, `WorkspaceScopedModel`, money
  helpers, pagination, the error envelope, request-ID middleware, structlog with **secret
  scrubbing**, health/readiness/version probes, and a pluggable demo-seed registry.
* `apps.accounts`: email-identified `User`, `Workspace` (company profile), `WorkspaceMembership`
  with the four roles (Owner/Admin/Member/Read-only), workspace resolution from `X-Workspace-ID`,
  and the permission classes every later viewset uses.
* `apps.integrations`: `ExternalObjectLink`, `SyncJob`, `WebhookEvent`, `SyncConflict`,
  `ProviderProfile` — the provider-agnostic backbone, with database-level uniqueness constraints
  that make repeated webhooks idempotent.
* Auth API: CSRF bootstrap, login, logout, session, password change, profile, workspace switch,
  membership management.

### Frontend
* Next.js App Router, TypeScript strict (+ `noUncheckedIndexedAccess`), Tailwind v4.
* **Design tokens** derived from the reference screenshots (very dark navy/violet canvas, panels a
  step lighter, hairline borders, saturated status pills, coloured group bars, dense 13–14px type).
  Every colour is a token; no component hardcodes a hex.
* App shell: fixed left navigation (grouped, collapsible, mobile drawer), topbar with global search
  → command palette (Ctrl/Cmd+K), notifications, user menu, workspace switcher.
* Session-cookie API client handling CSRF bootstrap, the workspace header, the error envelope, and
  401-vs-403.
* Login page and a dashboard that shows **only real data** (company profile + live system and
  integration status) — no placeholder KPIs.

### Infrastructure
* Docker Compose: postgres, redis, backend, celery-worker, celery-beat, frontend, mailpit, minio
  (+ a one-shot bucket initialiser). Healthchecks on everything; dependents wait on them.
* Makefile with `setup`, `up`, `test`, `lint`, `typecheck`, `migrate`, `seed`, `backup`, `restore`.
* Complete `.env.example`; both integrations **default to disabled**.

### Verified, not assumed
* `mypy --strict` clean (68 files), `ruff` clean, `pytest` 71 passed against a real PostgreSQL.
* Frontend: `tsc` clean, `eslint` clean, `prettier` clean, 39 vitest tests, production build OK.
* Full stack `docker compose up -d --wait` reaches healthy on all 8 services.
* Login driven end-to-end **in a real browser**; dashboard renders live data from PostgreSQL.

### Bugs found and fixed while verifying (all caught by actually running it)

| Bug | Why it mattered | Caught by |
| --- | --- | --- |
| Health probes ran inside `ATOMIC_REQUESTS` | A DB outage would make **liveness** 500 → the orchestrator restart-loops every container, and readiness could never report its own 503. | A query-count test |
| `CORS_ALLOW_HEADERS` omitted `X-Workspace-ID` | The browser preflight passed but the real request was blocked with an opaque `net::ERR_FAILED`. **Every** workspace-scoped request was broken in the browser. `curl` cannot catch this — it never preflights. | Driving the real UI |
| `Button asChild` emitted two children into Radix `Slot` | `Slot` requires exactly one element child → runtime crash on **every authenticated page** (the Topbar uses `asChild`). | Driving the real UI |
| Login returned DRF's generic `invalid` code | The SPA could not distinguish bad credentials from a validation error. | An auth test |
| `DEFAULT_THROTTLE_RATES: {}` in test settings | `ScopedRateThrottle` raises on an *unknown* scope → every login test 500'd. | An auth test |
| `API_URL` / `BACKEND_PORT` could disagree | Changing the port (needed when 8000 is taken) silently pointed the browser at nothing. Now derived in compose. | Driving the real UI |

Regression tests were added for each.

---

## Phase 1 — CRM

**Models:** `Client`, `ClientContact`, `ClientNote`, `ClientActivity` (fields per the brief;
see [docs/data-model.md](docs/data-model.md)).

**API:** workspace-scoped CRUD, search, tag/status/archived filters, aggregates.

**UI:** client list (table + card view), and the client dashboard with tabs — Übersicht, Projekte,
Aufgaben, Zeiten, Rechnungen, Kontakte, Termine, Notizen, Dateien, Aktivität.

**Note on the Übersicht KPIs:** total revenue, open receivables, unbilled hours and their value
depend on Phases 3 and 5. They are computed from whatever data exists and render honestly as
"—"/zero until those phases land — never as invented numbers.

**Acceptance:** clients fully manageable; dashboard tabs functional; every figure traceable to a
real query.

## Phase 2 — Projects, boards, sprints, tasks

`Project`, `ProjectPhase`, `Board`, `BoardView`, `Sprint`, `Task`, `TaskComment`,
`TaskAttachment`, `TaskDependency`, `TaskChecklistItem`, `TaskCustomFieldDefinition/Value`,
`TaskActivity`.

Kanban with dnd-kit and **persisted ordering** (fractional ranking so a reorder is one UPDATE, not
a renumbering of the column), table view, sprint planning, backlog, subtasks, dependencies,
timeline/gantt, budget vs actual, and a right detail drawer whose **URL updates and is
deep-linkable**.

## Phase 3 — Internal time tracking

`TimeEntry`, `ServiceType`, and the billing lifecycle
`not_billable → open → marked_for_invoice → invoice_draft_created → billed → cancelled`.

Timer with a **database-level single-running-timer constraint per user** (a partial unique index —
a check in application code loses a race), manual entries, week/day views, favourites, quick-start
from a task, global running timer, configurable rounding, change log, overlap warning, open hours
by client/project, and PDF/CSV timesheet export.

**Must work entirely without Clockodo.** This is verified by a test that runs the full flow with
the integration disabled.

## Phase 4 — Clockodo integration

Per [docs/integrations/clockodo.md](docs/integrations/clockodo.md) — which corrects several
assumptions in the brief:

* Resources are on **v3/v4**, not v2 (`/v3/customers`, `/v4/projects`, `/v2/entries`).
* **Webhooks exist** (47 events, incl. `entry.started`/`entry.stopped`) but **cannot be registered
  via API** — setup is a manual UI step with a human-in-the-loop secret handshake. That, not
  polling, is the real constraint.
* Marking entries billed **is** supported: `PUT /v2/entries/{id}` with `billable: 2`.
* Entries have **no `offset` field**; paging keys are snake_case; the field is `lumpsum`.

## Phase 5 — Lexware + invoice workflow

Per [docs/integrations/lexware.md](docs/integrations/lexware.md) — which corrects three points:

* Lexware **does sign webhooks** (`X-Lxo-Signature`, RSA-SHA512, published public key). We verify
  the signature **and** keep the secret path segment.
* **Invoice finalisation is create-time only** (`?finalize=true`); there is no draft→open API
  transition. A "finalise" button is therefore impossible — the UI says so and links to Lexware.
* Rate limit is **2 req/s globally**, with **no `Retry-After`**, and can surface as a **500**.

Invoice workflow: select open time entries → group → editable preview → **Lexware draft** →
sync status/number/PDF → mark entries billed. Double-billing is prevented by a **partial unique
index**, not just a status check.

## Phase 6 — Finance + tax forecast

Cashflow vs accrual views, revenue by client/project/service type, forecast.
`TaxProfile`, **versioned `TaxRuleSet`** with sourced values (no silently hardcoded rates),
a transparent step-by-step calculation, monthly `ReserveSnapshot`s, and scenarios.

Every output carries: **„Unverbindliche Prognose. Kein Ersatz für eine steuerliche Beratung."**

## Phase 7 — Appointments, files, activity

`Appointment` + calendar, ICS import/export, outcome notes, tasks-from-appointment.
Files in object storage (**never blobs in PostgreSQL**), versioned. Global activity stream.

## Phase 8 — Settings + integration centre

All settings from the brief. Integration page showing live connection state, profile info, last
success/failure, imported object counts, open conflicts, manual/full sync triggers, webhook status,
and a privacy-safe error log.

## Phase 9 — Security & privacy hardening

CSRF, secure cookies, CSP, rate limiting, server-side permission checks, audit log, safe uploads,
IDOR/XSS/SQLi defence, no secrets in the frontend or logs, backups + documented restore,
health/readiness, Celery monitoring, dependency/licence overview, GDPR export/erasure/retention
with **legal hold** (§147 AO / §257 HGB: 10 years — erasure must not delete invoices).

## Phase 10 — Tests

Backend: models, permissions, every domain area, invoice creation, **double-billing protection**,
provider payload mapping, **webhook idempotency**, sync conflicts, tax calculation, Decimal
rounding, timezones, pagination, error handling.
Frontend: component tests. E2E: the full demo-client → invoice-draft → payment-sync journey against
**mocked** providers (neither vendor offers a sandbox).

## Phase 11 — Docs + deployment

Full README, quickstart, dev/prod setup, Docker, backup/restore, provider setup, webhook setup,
every `.env` variable, data model, architecture diagram, sync logic, conflict handling, invoicing,
tax forecast, troubleshooting, update guide.

---

## Definition of done (from the brief)

- [x] Starts locally via Docker with one documented command (`make setup`)
- [x] Login works
- [x] Demo mode works without any API credentials
- [x] No credentials in the repository
- [x] Navigation matches the reference design — **every nav page is built and functional**
- [x] Clients manageable · client dashboards · projects & sprints · table + kanban · persisted
      drag-and-drop · internal time tracking · timer · Lexware connects from `.env` · **draft
      invoice from open hours** · finance dashboard · **traceable reserve forecast** · all
      integrations disableable
- [x] Clockodo connects from `.env` — full customer/project/service/user/entry sync, webhook
      receiver, billed-status push, invoice/payment sync from Lexware (scheduled polling)
- [ ] Lexware contacts import · Lexware inbound webhook receiver (polling covers status today)
- [x] Tests, linter, type check and builds pass *(for the code that exists)*
- [ ] Documentation complete

**Nothing is marked done until it is verified by running it.**
