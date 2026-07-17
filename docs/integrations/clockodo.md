# Clockodo API integration

**Authoritative source:** the OpenAPI 3.1 spec at <https://docs.clockodo.com/openapi.yaml>
(`info.version: 2026-07-08`, ~20k lines) and the docs portal at <https://docs.clockodo.com/>.

> **⚠️ Do not use <https://www.clockodo.com/en/api/> or `/de/api/`.** Those pages are **explicitly
> legacy** — Clockodo's own footer labels them "API documentation (legacy)" and states they are no
> longer updated. Several are already factually wrong (they document `/api/v2/customers`, which does
> not exist in the current spec). Everything below comes from the OpenAPI spec.

> **Rule of precedence:** where this document and the official spec disagree, the spec wins and this
> file is a bug.

---

## 1. Role of Clockodo in Coreflow

Clockodo is **optional**. It is one implementation of the time-tracking provider port, and Coreflow
must be fully usable with `CLOCKODO_ENABLED=false` forever.

* **Coreflow's own time tracking is the primary system** and never depends on Clockodo being
  reachable, configured, or enabled.
* Clockodo is authoritative **only** for entries that originate in Clockodo, timers started there,
  and its own customer/project/service records.
* Everything synced is mirrored locally. If Clockodo disappears tomorrow, no Coreflow data is lost.

There is **no direct coupling**: no model imports the Clockodo client, no view calls it inline, and
every task begins with an enabled-check that no-ops when the integration is off.

### Environment variables

```bash
CLOCKODO_ENABLED=false
CLOCKODO_API_BASE_URL=https://my.clockodo.com/api
CLOCKODO_API_USER=                       # the account's email address
CLOCKODO_API_KEY=                        # found under "Personal data" in Clockodo
CLOCKODO_EXTERNAL_APP_NAME=Coreflow
CLOCKODO_EXTERNAL_APP_EMAIL=             # technical contact; REQUIRED by Clockodo (§3)
CLOCKODO_WEBHOOK_TOKEN=                  # shared secret pasted into the Clockodo UI (§7)
CLOCKODO_SYNC_INTERVAL_MINUTES=15
```

---

## 2. ⚠️ Versioning — four tiers, not two

**This is the single biggest correction to the original brief.** The brief assumed legacy v1
(`/api/customers`) plus newer v2 (`/api/v2/entries`). That model is outdated. The current API has
**four coexisting version tiers**, and each resource lives at **exactly one** of them.

| Resource | Version | Path |
| --- | --- | --- |
| **Entry** | **v2** | `/api/v2/entries` |
| **Clock** | **v2** | `/api/v2/clock` |
| **EntryGroup** | **v2** | `/api/v2/entrygroups` |
| **Customer** | **v3** | `/api/v3/customers` |
| **User** | **v3** | `/api/v3/users` |
| **Subproject** | **v3** | `/api/v3/subprojects` |
| **Project** | **v4** | `/api/v4/projects` |
| **Service** | **v4** | `/api/v4/services` |

`/api/customers` and `/api/v2/customers` are **not in the current spec**. Building against the
legacy docs will fail. Whether old versions still respond for backwards compatibility is
**UNVERIFIED** and no deprecation policy is published — Coreflow targets **only** the table above.

Projects are the worst offender, spanning **three** prefixes (not a typo):

* `GET/POST/PUT/DELETE /v4/projects`
* `PUT /v3/projects/{id}/setBilled`
* `POST /v2/projects/{id}/createNextInterval`

### 2.1 Response envelopes are per-endpoint, not per-version

The deserializer needs an **envelope key per endpoint**. There is no single rule.

| Endpoint group | List | Single |
| --- | --- | --- |
| **Entry (v2)** | `{"paging": …, "entries": [...]}` | `{"entry": {...}}` |
| **EntryGroup (v2)** | `{"groups": [...]}` | — |
| **Clock (v2)** | **no envelope** — `{"running", "stopped", "current_time"}` at top level | — |
| **v3 / v4 (all)** | `{"paging": …, "data": [...]}` | `{"data": {...}}` |
| **DELETE (all)** | `{"success": true}` | — |

---

## 3. Authentication

Two accepted schemes. **`X-Clockodo-External-Application` is mandatory in both.**

**Option A — custom headers (what Coreflow uses):**
```http
X-ClockodoApiUser: admin@example.com
X-ClockodoApiKey: nl9tzwlwr4kzmd1qcbmtli60jpwd2c9g
X-Clockodo-External-Application: Coreflow;tech@example.com
```

**Option B — HTTP Basic:** `Authorization: Basic base64(email:apikey)` + the same external-app header.

### The external-application header format

Confirmed verbatim from the spec: `[name of application or company];[email address]` —
**semicolon separator, no space**. Spec's own example: `Clockodo;admin@clockodo.com`.

Coreflow builds it as `f"{CLOCKODO_EXTERNAL_APP_NAME};{CLOCKODO_EXTERNAL_APP_EMAIL}"`. Because it is
required on **every** request, the connection test fails fast with an actionable message when
`CLOCKODO_EXTERNAL_APP_EMAIL` is blank, rather than letting every call fail obscurely.

**UNVERIFIED:** behaviour when the header is omitted or malformed (no status code documented);
whether the name may itself contain `;`; any length limit.

### Access rights shape responses

The API key is **per user** and inherits that user's rights. Fields silently vanish or degrade
without them: `revenue`, `hourly_rate`, `note`, `billed_money`, and `billable` can return **`-1`
(NotAvailable)**. Coreflow treats a missing `revenue`/`hourly_rate` as "unknown", never as zero —
that distinction is the difference between "this work earned nothing" and "we may not see it".

---

## 4. Transport rules

### 4.1 Rate limits — generous globally, brutal on entrygroups

| Window | Limit |
| --- | --- |
| 1 minute | 900 |
| 15 minutes | 2,250 |
| 1 hour | 4,500 |
| 1 day | 20,000 |

Endpoint-specific limits **stack on top** of the global quota:

| Endpoint | Method | Limit |
| --- | --- | --- |
| `/api/entries` | GET | **300 / 15 min — only when `enhanced_list=1`** |
| `/api/entrygroups` | GET / PUT / DELETE | **10 / 1 min** |

> "The limits apply to every version of an endpoint. Switching to a newer API version does not grant
> a separate quota."

**Design consequences:**
* The bulk billing path (`PUT /v2/entrygroups`) is capped at **10/min**. Coreflow therefore prefers
  **per-entry PUT** for typical invoice sizes and only uses entrygroups above a threshold.
* `enhanced_list=1` is **required** to read `text`, `revenue`, `hourly_rate` and `*_name` — i.e. we
  effectively always need it — which puts our real entry-sync budget at **300/15 min**, not 900/min.
  Incremental sync is windowed accordingly.

**Retry-After:** the docs say only "respect any `Retry-After` header **if present**" — the
conditional is theirs. **`X-Ratelimit-*` headers are not documented anywhere in the spec**
(**UNVERIFIED**). Coreflow honours `Retry-After` when present and otherwise falls back to
exponential backoff (1s, 2s, 4s…, capped).

### 4.2 Pagination — snake_case

Request: `page` (1-based), `items_per_page`. Maxima differ per endpoint: entries **1000**, customers
**5000**, projects **5000**, users **1000**.

```json
"paging": {"items_per_page": 1000, "current_page": 1, "count_pages": 1, "count_items": 4}
```

> **Correction:** these are **snake_case** (`items_per_page`, `current_page`, `count_pages`,
> `count_items`) — not the camelCase `itemsPerPage`/`countPages` the brief guessed.

### 4.3 Two — really three — error shapes

**`GeneralErrors`** — v3/v4 and most of v2 (clock, customers, projects, services, users):
```json
{"errors": [{"type": "General", "message": "The requested resource could not be found.",
             "details": null, "path": null}]}
```

**`SimpleErrorResponses`** — **`/v2/entries` uses this**, our highest-traffic resource:
```json
{"error": {"code": 400, "message": "An error occurred", "fields": ["..."]}}
```

**422 on v3/v4** — a third, nested shape: `{"errors": [{"error": {type, message, path, details}}]}`,
i.e. `errors[].error.type`.

> ⚠️ `errors` (array) vs `error` (object) — and **entries is the odd one out**.

**Error messages are localized** via `Accept-Language`. **Never match on `message`; match on
`type`.** Coreflow normalises all three shapes into one `ClockodoApiError` carrying the `type`.

### 4.4 Date/time

* **ISO 8601 UTC with `Z`** — `2023-02-28T12:00:00Z`. Used for `time_since`, `time_until`,
  `time_insert`, `time_last_change`, `time_clocked_since`, `occurred_at`.
* **Date-only** (`format: date`, `2023-02-28`) for `deadline`, `start_date`. Don't send datetimes.
* **Millisecond precision only on clock `current_time`** (`x-precision: millisecond`) — used for
  clock drift correction.
* `duration`, `duration_transfer`, `away` are **integer seconds**, not ISO durations.
* **UNVERIFIED:** whether non-`Z` offsets are accepted. Every example is `Z` → we always send
  `Z`-normalised UTC.

---

## 5. Resources

### 5.1 Customers — `/api/v3/customers`

`CustomerV3` required: `id, name, number, color, active, billable_default, test_data`.

* `active` and `billable_default` are **booleans**, not 0/1 integers.
* `color` is an int 1–9 (1 BloodOrange … 9 ChewingGum).
* `note` requires admin / `manage_customers_and_projects`.
* Filters: `filter[active]`, `filter[fulltext]`.

### 5.2 Projects — `/api/v4/projects`

`ProjectV4` required: `id, customers_id, name, number, active, billable_default, completed,
completed_at, test_data, count_subprojects, service_assignments`.

* `billed_money` / `billed_completely` — **"only with necessary access rights"**.
* `budget` (`ProjectBudgetV4`): `monetary`, `hard`, `from_subprojects`, `interval`, `amount`,
  `subprojects_budget_total`.
* Filters: `filter[active]`, `filter[completed]`, `filter[customers_id]`, `filter[fulltext]`.

### 5.3 Services — `/api/v4/services`

`ServiceV4` required: `id, name, number, active`. `active` is boolean. Maps to Coreflow's
`ServiceType`.

### 5.4 Entries — `/api/v2/entries`

**`time_since` and `time_until` are required top-level query params** (not inside `filter`),
`format: date-time`.

`filter` uses `style: deepObject, explode: true` → serialises as **`filter[customers_id]=123`**.
Filterable: `billable`, `budget_type`, `customers_id`, `lumpsum_services_id`, `projects_id`,
`services_id`, `subprojects_id`, `text`, `texts_id`, `users_id`.

#### `EntryV2` is a union discriminated by `type`

| `type` | Meaning |
| --- | --- |
| `1` | Time |
| `2` | LumpsumValue |
| `3` | LumpsumService |

Time entries (type 1) split further:

| Variant | `clocked` | `time_until` | `duration` |
| --- | --- | --- | --- |
| Running | `true` | **`null`** | **`null`** |
| Stopped | `true` | date-time | int seconds |
| Manual | **`false`** | date-time | int seconds |

So `clocked` means "tracked with the clock" (vs entered manually), and a **running entry is
`clocked: true` with null `time_until`/`duration`** — not a separate flag.

Key fields: `customers_id`, `projects_id` (nullable), `subprojects_id` (nullable), `users_id`,
`services_id`, `texts_id` (nullable), `text`, `time_since`, `time_insert`, `time_last_change`,
`time_clocked_since`, `clocked_offline`, `test_data`.

**Only with `enhanced_list=true`:** `text`, `revenue`, `hourly_rate`, and `customers_name` /
`projects_name` / `subprojects_name` / `users_name` / `services_name`. `revenue` and `hourly_rate`
additionally need access rights.

> **Correction:** ⚠️ **entries have no `offset` field.** The brief asked for one. `offset` exists
> only on `WorkTimeV2` ("additional work time… only possible for days before 2023-01-01"). Not
> modelled.

> **Correction:** the field is **`lumpsum`** (snake_case) — plus `lumpsum_services_id`,
> `lumpsum_services_amount`, `lumpsum_services_price`. **Never `lumpSum`.** camelCase appears only in
> the `/v4/lumpSumServices` *path*.

**POST** requires `customers_id` and `billable`. **PUT** takes all fields optional.

### 5.5 The four `billable` enums

| Enum | Used by | Values |
| --- | --- | --- |
| `ApiEntriesV2_Billability` | entry **responses** | `-1` NotAvailable, `0` NotBillable, `1` Billable, `2` Billed |
| `Billable` | GET filters, **PUT** `/v2/entries/{id}` | `0`, `1`, `2`, `12` BillableOrBilled |
| `BillableDistinct` | PUT `/v2/entrygroups` | `0`, `1`, `2` |
| `BillableWithoutBilled` | **POST** `/v2/entries` | `0`, `1` |

* **`-1` appears only in responses** — it means "you lack the rights to see this". Handled explicitly.
* **`12` is a filter convenience** ("billable OR billed"). It is in the enum PUT accepts, but writing
  it is meaningless — **UNVERIFIED** what it does. Coreflow never sends it.
* **You cannot create an already-billed entry**: POST is restricted to `0|1`.

### 5.6 Clock — `/api/v2/clock`

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/v2/clock` | Currently running entry |
| POST | `/v2/clock` | **Start** |
| PUT | `/v2/clock/{id}` | **Change duration** |
| DELETE | `/v2/clock/{id}` | **Stop** |

> **Correction:** ⚠️ **there is no `/clock/update` endpoint.** The update is `PUT /v2/clock/{id}`.
> The path param is `{id}`, not `{entryId}`.

* **POST (start)** requires `customers_id` and `services_id`. Optional `billable`, `projects_id`,
  `subprojects_id`, `text` (≤1000), `time_since`, `users_id`, `duration_transfer`. May return
  **409 Conflict**.
* **DELETE (stop)** takes **query params, not a body**: `away`, `start_new`, `time_until`, `users_id`.
* `ClockStartV2` returns `stopped` — the entry this start **implicitly stopped** — plus
  `stopped_has_been_truncated` ("shortened to comply with maximum duration of 24h") and an optional
  `additional_message` warning when the started entry deviates from the request. All three are
  surfaced to the user rather than swallowed.

### 5.7 Marking entries billed — **yes, this is supported**

The brief hedged with "soweit von der API unterstützt". It **is** supported. There is no separate
`invoiced` flag: **`billable = 2` *is* the billed state.**

| Approach | Endpoint | Notes |
| --- | --- | --- |
| **Single entry** | `PUT /v2/entries/{id}` `{"billable": 2}` | ✅ Precise. Coreflow's default. |
| **Bulk** | `PUT /v2/entrygroups` | ✅ But **10/min** and a **two-phase `confirm_key`** round-trip |
| **Project level** | `PUT /v3/projects/{id}/setBilled` | ✅ `billed_money` **only for hard-budget projects** |
| Create as billed | `POST /v2/entries` | ❌ Impossible — POST accepts `0|1` only |
| Link to an external invoice id | — | ❌ Not documented |

The `entrygroups` **`confirm_key`** flow: the first PUT returns
`{confirm_key: string, affected_entries: int64}` and applies nothing; you must resend **with** the
key to commit. This is a safety interlock, not an error.

Clockodo's own 422 messages confirm the intended model:
> `BilledMoneyCanOnlyBeSetWithHardBudget`: "The project does not have a hard budget so that the
> billed amount can't be set. **You have to set the single entries to billed.**"

**Coreflow's choice:** per-entry `PUT` with `billable: 2` after a Coreflow invoice reaches `billed`,
because it is exact, needs no confirm round-trip, and works for every budget type. Only entries that
actually came from Clockodo (i.e. have an `ExternalObjectLink`) are pushed.

---

## 6. Sync strategy

| Trigger | Scope |
| --- | --- |
| Connect / manual full sync | customers → projects → services → users → entries (windowed by month) |
| Celery Beat every `CLOCKODO_SYNC_INTERVAL_MINUTES` | Entries where `time_last_change` > last success − 5 min |
| Webhook | Single entity by id |

Entries are **always** windowed because `time_since`/`time_until` are required.

### Conflict strategy

Per the brief, and unchanged by the research:

* **Local tasks, boards, sprints are never touched by Clockodo.** Clockodo has no concept of them.
* Clockodo customers/projects/services map to local objects **via `ExternalObjectLink`** only. A
  Clockodo customer never overwrites a local `Client`'s CRM fields.
* Remotely-changed entries update the local mirror (compare `time_last_change` vs our
  `last_remote_modified_at`).
* Locally-changed synced entries are pushed back.
* **Concurrent divergence → `SyncConflict`**, surfaced in the integration centre with both snapshots
  and resolved by a human. Never auto-merged, never silently dropped.

Idempotency: every write compares `sync_hash` of the normalised remote payload first. A replayed
webhook or an overlapping window is a no-op.

---

## 7. Webhooks — supported, but **registration is UI-only**

> **Correction:** the brief's uncertainty ("does Clockodo support webhooks?") resolves to **yes** —
> the spec has a top-level `webhooks:` section with **47 events**, including `entry.started` and
> `entry.stopped`. **We do not need to poll for change detection.**
>
> **But there is no API endpoint to register a webhook.** I enumerated every path in the spec:
> subscription CRUD does not exist. (`/v2/subscription` is the *billing plan*, unrelated.)

### 7.1 Setup is a manual, human step

> "You can create a new webhook or edit an existing one via the **Webhooks section in the Clockodo
> menu**. Simply select the desired event, enter the target URL and a token."

On creation or URL change, Clockodo POSTs a validation handshake to the URL:

```json
{"secret": "XXXXXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXX"}
```

…and **a human must paste that secret back into the Clockodo UI**. It cannot be completed
programmatically.

**Design consequence:** Coreflow's webhook endpoint detects a handshake body (a lone `secret` key),
persists it, and **surfaces it in the integration centre** so the user can copy it into Clockodo.
The setup UI is a documented checklist, not a "Connect" button. This is the real integration
constraint — not polling.

### 7.2 Payload — IDs only

```json
{"subscription_id": 42, "company_id": 1337, "occurred_at": "1986-05-10T17:02:00Z",
 "payload": {"entry": {"id": 9001}}, "event_name": "entry.created", "token": "My_Sup3r_T0k3n"}
```

> "We only transmit the ID of the created, modified, or deleted entity. We don't transmit full
> datasets or deltas."

So — exactly as with Lexware — the architecture is **webhook-as-trigger, API-as-source-of-truth**:
persist the event, ack, then fetch the entity. `payload` is keyed by entity name, each `{id: int}`.

**Verification:** `token` is the plaintext shared secret we configured (`CLOCKODO_WEBHOOK_TOKEN`),
compared in **constant time**. The docs say: "Always verify the token and structure of incoming
webhook data." Return **200** to ack.

> ⚠️ This is a **plaintext bearer token in the body**, not a signature. It is therefore replayable by
> anyone who obtains it, which is why the endpoint is also HTTPS-only and idempotent by `sync_hash`.
> Unlike Lexware, there is **no cryptographic signature** (**UNVERIFIED** whether one exists).

### 7.3 Events Coreflow subscribes to

All 11 events the brief listed **do exist**, using dotted names:

`customer.created` · `customer.updated` · `customer.deleted` · `project.created` ·
`project.updated` · `project.deleted` · `entry.created` · `entry.updated` · `entry.deleted` ·
`entry.started` · `entry.stopped`

> ⚠️ The OpenAPI **keys** use underscores (`entry_created`) but the wire value of `event_name` uses
> **dots** (`entry.created`). **Match on the dotted form.**

> ⚠️ **There is no `entry.billed` event.** Billing-status changes arrive as `entry.updated`; we fetch
> and compare `billable`.

**UNVERIFIED:** retry/redelivery policy, delivery ordering, timeout, max subscriptions. None
documented — so the handler is written to tolerate duplicates, gaps and out-of-order delivery, and
the periodic sync remains the backstop that guarantees eventual consistency.

---

## 8. Testing

* **No sandbox exists.** The spec declares exactly one server. No `sandbox`/`staging` host anywhere.
* `test_data` (boolean) marks demo records **inside** a normal account — and they are
  **write-protected** (`CannotModifyDemoData`: "You must not edit demo data"), so they are useless as
  write fixtures.
* **Therefore the automated suite never touches the network.** All Clockodo tests use `respx` with
  fixtures derived from the spec's own examples. `config.settings.test` force-disables the
  integration and blanks the credentials, so a missing mock fails loudly rather than dialling out.
* For manual verification, use a **separate free/trial Clockodo account** as a test tenant.

---

## 9. Trap list

1. **Resources are on v3/v4, not v2.** `/api/v2/customers` does not exist. The legacy docs are wrong.
2. **Webhooks cannot be self-provisioned** — UI-only, plus a human-in-the-loop secret handshake.
3. **`/v2/entries` uses `{"error": {…}}`** while everything else uses `{"errors": [ … ]}`.
4. `paging` is **snake_case**.
5. **No `offset` field on entries.** It belongs to `WorkTimeV2`.
6. **`lumpsum`, never `lumpSum`.**
7. **No `/clock/update`** — it is `PUT /v2/clock/{id}`.
8. `billable = -1` means "no rights", not "not billable".
9. `enhanced_list=1` is needed for text/revenue/rate — and drops the budget to **300/15 min**.
10. `entrygroups` PUT is **10/min** and needs a **`confirm_key`** round-trip.
11. `time_since`/`time_until` are **required** on entry listing.
12. Error messages are **localized** — match on `type`, never on `message`.
13. Starting a clock **implicitly stops** the running entry and may **truncate it at 24h**.
14. The spec is **OpenAPI 3.1** — 3.0-pinned generators choke on `type: [string, 'null']` and `const`.

---

## 10. Reference links

| Topic | URL |
| --- | --- |
| OpenAPI spec (source of truth) | <https://docs.clockodo.com/openapi.yaml> |
| Docs portal | <https://docs.clockodo.com/> |
| ⚠️ Legacy docs — do not use | <https://www.clockodo.com/en/api/> |
