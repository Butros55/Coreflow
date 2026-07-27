# Coreflow — Architecture

## 1. What this system is

One workspace for a self-employed German software developer, replacing the daily loop of
Lexware ↔ Clockify ↔ spreadsheets ↔ calendar ↔ project tool.

The design question that shapes everything: **who owns which fact?**

```
┌──────────────────────────────┬──────────────────────────────────────────────┐
│ Coreflow owns (system of     │ Clients, contacts, notes, projects, phases,  │
│ record — nothing else has    │ boards, sprints, tasks, time entries,        │
│ these)                       │ appointments, budgets, files, forecasts,     │
│                              │ settings                                     │
├──────────────────────────────┼──────────────────────────────────────────────┤
│ Lexware owns (we mirror,     │ Invoice numbers, finalised invoices, invoice │
│ never invent)                │ status, PDF/e-invoice, payments, open        │
│                              │ amounts, bookkeeping vouchers, expenses      │
├──────────────────────────────┼──────────────────────────────────────────────┤
│ Clockify (optional, two-way  │ Its copies of clients, projects, tags and    │
│ mirror — no owner, one state)│ time entries — kept in step with Coreflow's  │
└──────────────────────────────┴──────────────────────────────────────────────┘
```

Two rules follow, and they are absolute:

1. **Coreflow never invents an accounting fact.** It cannot mint an invoice number or decide that an
   invoice is paid. Those come from Lexware or they do not exist.
2. **Clockify is never required.** The internal time tracking is the primary implementation, not a
   fallback. `CLOCKIFY_ENABLED=false` is a fully supported, permanent configuration. When enabled,
   both sides converge on the same state (entries deduplicated against Lexware imports — one entry,
   two provenance tags).

## 2. Runtime topology

```
                        ┌───────────────┐
   browser ────────────▶│   Next.js     │  SSR shell + React SPA
                        │   :3000       │
                        └───────┬───────┘
                                │ fetch(credentials: include)
                                │ session cookie + X-CSRFToken + X-Workspace-ID
                                ▼
                        ┌───────────────┐        ┌──────────────┐
                        │  Django/DRF   │───────▶│ PostgreSQL   │  system of record
                        │   :8000       │        └──────────────┘
                        └───┬───────┬───┘
                            │       │            ┌──────────────┐
                            │       └───────────▶│ Redis        │  cache + broker
                            │                    └──────┬───────┘
                            │                           │
                            │                    ┌──────▼───────┐
                            │                    │ Celery       │  sync, webhooks,
                            │                    │ worker+beat  │  snapshots
                            │                    └──────┬───────┘
                            │                           │
                            ▼                           ▼
                     ┌──────────────┐         ┌───────────────────┐
                     │ MinIO / S3   │         │ Lexware · Clockify│
                     │ files        │         │ (outbound only)   │
                     └──────────────┘         └─────────┬─────────┘
                                                        │ webhooks (inbound)
                                                        ▼
                                               POST /api/v1/webhooks/…
```

**Nothing in a request path calls an external provider.** Provider I/O happens in Celery tasks. A
user action that needs a provider (e.g. "create invoice draft") enqueues work and reports status —
so Lexware being slow or down degrades one feature instead of hanging the app.

## 3. Backend layout

```
backend/
├── config/
│   ├── settings/{base,dev,test,prod}.py   prod refuses to boot when misconfigured
│   ├── urls.py / api_urls.py              everything the SPA uses is /api/v1/*
│   └── celery.py                          periodic schedules, guarded by *_ENABLED
└── apps/
    ├── core/          base models, money, pagination, errors, logging, health, seeding
    ├── accounts/      User, Workspace, Membership, roles, permissions
    ├── crm/           Client, ClientContact, ClientNote, ClientActivity
    ├── projects/      Project, Phase, Board, BoardView, Sprint, Task + satellites
    ├── timetracking/  TimeEntry, ServiceType, timer
    ├── invoicing/     Invoice, InvoiceLine, InvoiceTimeEntry, the draft workflow
    ├── finance/       TaxProfile, TaxRuleSet, ReserveSnapshot, forecasting
    ├── scheduling/    Appointment
    ├── files/         StoredFile
    └── integrations/  provider port + adapters, links, sync jobs, webhooks, conflicts
        ├── lexware/
        └── clockify/
```

Apps depend **downward only**: `core` ← `accounts` ← domain apps ← `integrations`. `integrations`
knows about domain models; no domain model imports a provider client. That is what keeps the
"no direct coupling to Clockify" requirement true structurally rather than by discipline. (The
time-tracking views call one integration *hook* to mirror local changes — a thin, enabled-guarded
enqueue, not a provider client.)

## 4. Cross-cutting decisions

### UUID primary keys
Every table. Costs some index space versus `bigserial`; buys IDs that are safe in URLs (a
sequential ID leaks how many clients you have and invites enumeration), and objects that can be
created or merged from a provider without a round-trip.

### Decimal money, rounded once
`apps.core.money` is the only place money arithmetic happens. `ROUND_HALF_UP` to 2 places (the
German invoice convention — Python's default is banker's rounding, which would be wrong).
`line_amount()` multiplies exactly and rounds **once at the end**; quantising hours first and
multiplying second double-rounds and drifts by a cent on long entries.

Money crosses the wire as a **string** (`COERCE_DECIMAL_TO_STRING`), so JSON never turns 19.99 into
19.989999999999998. The frontend parses it for *display only*.

### Time
Stored UTC (`USE_TZ=True`). `Europe/Berlin` affects presentation and the boundaries of
"day"/"month" in reports. The two only diverge visibly around DST, which is exactly when a naive
implementation puts an evening entry on the wrong day.

### Workspace scoping and IDOR
Every domain model carries `workspace_id`. The client may *ask* for a workspace via
`X-Workspace-ID`, but the header is only ever used to **look up a membership row** — it never
grants anything. An ID from another workspace 404s rather than resolving, because the queryset is
filtered before `get_object()` runs. A malformed or unknown header **denies**; it never falls back
to a default, because falling back would mean a client bug writes to the wrong tenant.

### Auth
Django session cookie: `HttpOnly` (XSS cannot exfiltrate it), `SameSite=Lax`, plus Django's
double-submit CSRF token, which the SPA reads from a readable cookie and echoes in `X-CSRFToken`.
A JWT in `localStorage` would be strictly worse here — frontend and API are same-site, so the
cookie costs nothing and cannot be read by script.

`localhost:3000` and `localhost:8000` are cross-**origin** but same-**site** (SameSite ignores
port), so `Lax` cookies are sent. In production both sit behind one domain.

> **CORS trap, learned the hard way:** `django-cors-headers` advertises a fixed default
> allow-list. `X-Workspace-ID` is a non-simple header, so the browser preflights it — and without
> it in `CORS_ALLOW_HEADERS`, the preflight *succeeds* while the real request dies with an opaque
> `net::ERR_FAILED`. `curl` never preflights, so it cannot catch this. Pinned by
> `apps/accounts/tests/test_cors.py`.

### Errors
One envelope:
```json
{"error": {"code": "…", "message": "…", "request_id": "…", "detail": {"field": ["…"]}}}
```
`code` is stable and machine-readable. Unexpected exceptions are logged with the request ID and
returned as an opaque 500 — an internal message can carry table names, file paths, or fragments of
customer data.

### Logging
structlog, JSON in production. A `scrub_secrets` processor sits **last before rendering**, so
nothing added later can leak: keys matching `password|token|api_key|authorization|…` are redacted,
and `Bearer …` / `?token=…` are stripped from free text. This is what makes it safe for the
provider clients to log request metadata at all.

### Health vs readiness
`/healthz` answers "is this process wedged?" and checks **nothing** else. `/readyz` answers "can it
serve traffic?" and checks DB + cache. Both are **exempt from `ATOMIC_REQUESTS`** — otherwise they
would open a transaction before their own code ran, so a DB outage would turn liveness into a 500
and restart-loop every container instead of just draining traffic.

## 5. The integration layer

### Ports and adapters
A provider implements a port; nothing else changes.

```
apps/integrations/
├── models.py            ExternalObjectLink, SyncJob, WebhookEvent, SyncConflict, ProviderProfile
├── base.py              the port: test_connection / fetch / push / handle_webhook
├── lexware/{client,mapping,sync,webhooks,tasks}.py
└── clockify/{client,mapping,sync,hooks,tasks}.py
```

Adding a third provider = a new `Provider` choice + a package. No schema change.

### Why a link table instead of `lexware_id` columns
`ExternalObjectLink(provider, resource_type, local_object_type, local_object_id, external_id,
external_version, sync_hash, last_synced_at, last_remote_modified_at, deleted_remotely, metadata)`

* Keeps provider concerns out of business tables.
* One local object can link to several providers.
* Sync metadata (version, hash, remote deletion) has somewhere to live.

### Idempotency — the load-bearing mechanism
Neither provider guarantees exactly-once delivery, so **we** guarantee it:

1. A **unique constraint** on `(workspace, provider, resource_type, external_id)`. A repeated
   webhook updates; it cannot insert a duplicate.
2. `sync_hash` = SHA-256 of the normalised remote payload with **sorted keys**. Unchanged hash ⇒
   skip the write entirely. This makes replayed webhooks and overlapping sync windows free.
3. `WebhookEvent.dedupe_key` unique per provider (partial index, so blank keys don't collide).

### Webhooks: persist first, process later
* Lexware sends **pointers, not data**: `{organizationId, eventType, resourceId, eventDate}`
* Clockify sends the **full entity**, with the event name and per-webhook signing token in headers

Either way every handler is **fetch-then-reconcile**, never blind-apply — a webhook body can be
stale by the time it is processed. And the endpoint does the minimum:
verify → persist `WebhookEvent` → enqueue → return 204. Lexware's read timeout is **5000 ms**, and
a persistent failure to respond causes it to **delete the subscription**. Inline processing would
eventually unsubscribe us from our own accounting events.

### Authenticity
| | Lexware | Clockify |
| --- | --- | --- |
| Signature | **RSA-SHA512** `X-Lxo-Signature` over the raw body, public key published | `clockify-signature` header = the webhook's signing token, constant-time compared against `CLOCKIFY_WEBHOOK_TOKEN` (comma-separated, one per webhook) |
| Secret path | yes (`LEXWARE_WEBHOOK_SECRET`) | no — the signature header is the secret |
| Tenant check | `organizationId` must match the stored profile | events attach to the single connected workspace |

Lexware's signature is verified against the **raw request bytes**, captured before JSON parsing —
re-serialising will not reproduce the signed bytes.

### Conflicts
A `SyncConflict` stores **both snapshots** and is resolved by a human. Raised when local and remote
both changed, on a `version` 409, when a remote object we link to disappears, or when a remote write
is structurally impossible (e.g. a Lexware contact with multi-entry lists). Nothing is auto-merged.
Nothing is silently dropped.

### Rate limits shape the design
| | Limit | Consequence |
| --- | --- | --- |
| Lexware | **2 req/s globally**, no `Retry-After`, 500 can mean throttled | Requests are **serialised** through a token bucket. Fanning out per-resource would breach the shared budget. |
| Clockify | ~50 req/s per key | Self-throttled to 5 req/s; entry listing is per user and windowed (31 days), so even a year's full sync stays cheap. |

Lexware's **10,000-element search window** is why full sync iterates month by month rather than
paging until empty, with progress in `SyncJob.cursor` so a failure resumes.

## 6. Frontend

```
frontend/src/
├── app/
│   ├── layout.tsx / providers.tsx    QueryClient (per-request on server, singleton in browser)
│   ├── login/
│   └── (app)/                        authenticated group: shell + routes
├── components/
│   ├── layout/                       sidebar, topbar, command palette, shell
│   └── ui/                           Radix + CVA primitives, token-driven
└── lib/
    ├── api/                          client (CSRF, workspace header, error envelope), types
    ├── session.tsx                   session query, permissions, workspace switch
    └── utils.ts                      money/hours/duration formatting
```

* **Server state is TanStack Query only.** No Redux — nearly all state here *is* server state, and
  a second copy of it is a bug farm.
* **Mutations never auto-retry** (a retried POST can double-create). Queries retry only transient
  failures — never 4xx, which would burn a throttled budget.
* `(app)/layout.tsx` gating is **UX, not security**: it avoids rendering a shell for a logged-out
  user. Someone who defeats it sees an empty shell and 401s.
* **Design tokens**: every colour, radius, and size is a CSS variable in `globals.css` (`@theme`).
  A status must read identically as a pill, a column header, and a row tint — that is only true if
  they share one token.
* Dark-first (per the reference designs), with the tokens indirected so a light theme is a variable
  swap.

## 7. Background jobs

| Task | Cadence | Guard |
| --- | --- | --- |
| `lexware.sync_incremental` | `LEXWARE_SYNC_INTERVAL_MINUTES` (30) | no-op when disabled |
| `clockify.sync_incremental` | `CLOCKIFY_SYNC_INTERVAL_MINUTES` (15) | no-op when disabled |
| `process_pending_webhook_events` | every 5 min | retries failed events |
| `finance.create_monthly_reserve_snapshot` | 1st of month, 03:00 | — |

Incremental syncs use a **5-minute overlap** against the last success to absorb clock skew;
idempotency makes the overlap free. The periodic sync is also the **backstop** that guarantees
eventual consistency when a webhook is missed — which matters, because Clockify documents no
retry/ordering guarantees at all.

## 8. What is deliberately *not* here

* **No microservices.** One Django app, one database. A single-user business system has no scaling
  problem that justifies distributed transactions across an invoice and its time entries.
* **No event sourcing.** An audit log and `ClientActivity` give the traceability required, without
  making every read a fold.
* **No GraphQL.** The client is one known SPA; REST + a generated OpenAPI schema is less machinery.
* **No provider SDKs.** Both are thin HTTP APIs with quirks (three error shapes; snake_case paging;
  version drift across resources) that a hand-written client documents better than a dependency
  hides.

## 9. See also

* [data-model.md](data-model.md) — every model and field
* [integrations/lexware.md](integrations/lexware.md) — verified API contract, traps, UNVERIFIED flags
* [integrations/clockify.md](integrations/clockify.md) — same, plus sync directions and the Lexware dedup rule
* [../IMPLEMENTATION_PLAN.md](../IMPLEMENTATION_PLAN.md) — phase plan and stack decisions
