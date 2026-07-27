# Lexware Office API integration

**Authoritative source:** <https://developers.lexware.io/docs/> (single-page doc; links below
are anchors on it). Everything in this file was verified against that page. Where the
documentation is silent or self-contradictory it is marked **UNVERIFIED** — those points must be
confirmed empirically before being relied on, and the code treats them defensively.

> **Rule of precedence:** where this document and the official documentation disagree, the
> official documentation wins and this file is a bug.

---

## 1. Role of Lexware in Coreflow

Lexware Office is the **system of record** for anything with legal or accounting weight:

| Lexware owns | Coreflow owns |
| --- | --- |
| Official invoice numbers | Clients, contacts, notes |
| Finalised invoices and their PDF/e-invoice | Projects, phases, boards, sprints, tasks |
| Invoice status and payment status | Time entries and their billing status |
| Incoming payments, open amounts | Appointments, files, forecasts |
| Bookkeeping vouchers, expenses | The invoice *draft* composition workflow |

Coreflow **mirrors** Lexware data locally so the dashboard works offline and stays fast, but never
treats its mirror as authoritative for the columns above. Lexware is a **pull-through cache with
webhook invalidation**, not a two-way sync of accounting records.

---

## 2. Connection basics

| Item | Value |
| --- | --- |
| Base URL | `https://api.lexware.io` |
| Version | `v1` |
| Auth | `Authorization: Bearer {LEXWARE_API_KEY}` |
| Content type | `application/json` on POST/PUT (missing → **415**) |
| API key source | <https://app.lexware.de/addons/public-api> |

The public API documents **API-key auth only**. OAuth belongs to the separate
[Partner API](https://developers.lexware.io/partner/docs/) and is out of scope.

The gateway moved to `api.lexware.io` on 2025-05-26; the previous gateway was retired in
December 2025. `LEXWARE_API_BASE_URL` stays configurable so a future move needs no code change.

### Environment variables

```bash
LEXWARE_ENABLED=false                          # master switch; false ⇒ no code path calls Lexware
LEXWARE_API_BASE_URL=https://api.lexware.io
LEXWARE_API_KEY=                               # server-side only, never sent to the browser
LEXWARE_WEBHOOK_PUBLIC_URL=                    # public HTTPS base for callbacks
LEXWARE_WEBHOOK_SECRET=                        # unguessable path segment (see §7.2)
LEXWARE_SYNC_INTERVAL_MINUTES=30
LEXWARE_CREATE_FINAL_INVOICES=false            # MUST stay false by default (see §6.3)
```

---

## 3. Transport rules the client must obey

These are the constraints that make a naive HTTP client fail in production. All are implemented in
`apps/integrations/lexware/client.py`.

### 3.1 Rate limit — 2 requests/second, global

* The limit is **2 req/s across all endpoints collectively**, token bucket.
* Exceeding it returns **429** and *the call is not performed*.
* **`Retry-After` is NOT documented and does not appear anywhere in the docs.** Backoff must be
  entirely client-side. Any code reading `Retry-After` is coding against a header that may not exist.
* **A 429 is not the only rate-limit signal.** The documented body for **500** is
  `{"message": "Internal server error or rate limit exceeded"}` — so 500 is ambiguous and must be
  retried with backoff rather than treated as a hard failure.
* The authorization server has separate, undocumented limits. A client that does not back off
  "will stay blocked permanently until the number of requests is reduced."

**Design consequence:** requests are **serialised through a process-wide token-bucket limiter**, not
parallelised per resource. Fanning out per-resource sync tasks would breach the shared budget.

### 3.2 Pagination

Params `page` (0-indexed), `size`, `sort`. Envelope:

```json
{ "content": [], "first": true, "last": true, "totalPages": 1,
  "totalElements": 13, "numberOfElements": 13, "size": 25, "number": 0, "sort": [] }
```

* Default `size` 25; **max 250** for `articles`, `contacts`, `recurring-templates`, `voucherlist`,
  `vouchers`. (Prose mentions a 100 cap for some endpoints but never says which — **UNVERIFIED**;
  we use 250 only for the listed five and 25 elsewhere.)
* **Hard 10,000-element search window.** `totalElements` is capped; exceeding it errors with
  `Maximum search window size exceeded`.
  **Design consequence:** full sync is **windowed by date** (month-by-month), never a naive
  page-until-empty loop.
* `event-subscriptions` list returns a bare `{"content": [...]}` with **no paging fields** — do not
  feed it through the generic paginator.

### 3.3 Optimistic locking

* Versioned resources carry an integer `version`.
* **POST:** send `version: 0`. **PUT:** GET first, merge, send the current `version`.
* Stale version → **409 Conflict** → we raise a `SyncConflict` rather than clobbering.
* The docs label `version` "Read-only" on invoices/articles but explicitly writable on vouchers, and
  required on contact create. The label is inconsistent; **always send `version` on PUT**.

### 3.4 Status codes that differ from the obvious

| Code | Meaning here |
| --- | --- |
| **406** | **Validation failure.** This is the main validation status — *not* 400 or 422. |
| 402 | Payment Required — the customer's Lexware contract has an issue. Surfaced verbatim to the user. |
| 409 | Conflict — stale `version`, duplicate subscription, or PDF requested for a draft. |
| 429 | Rate limited. |
| 500 | Server error **or rate limit** — ambiguous, retried. |
| 504 | Gateway timeout after 30 s. **"It is possible that your request has been processed successfully."** |

**504 is a non-idempotent retry hazard.** A blindly retried invoice POST can produce a duplicate
invoice. Mitigation in §6.4.

### 3.5 Three error body shapes

The client normalises all three into one `LexwareApiError`.

1. **Legacy `IssueList`** — used by `contacts`, `files`, `vouchers`:
   ```json
   {"IssueList": [{"i18nKey": "missing_entity", "source": "company.name",
                   "type": "validation_failure", "additionalData": null, "args": null}]}
   ```
2. **Regular** — everything else (`invoices`, `profile`, `voucherlist`, `event-subscriptions`):
   ```json
   {"timestamp": "...", "status": 406, "error": "Not Acceptable", "path": "/v1/invoices",
    "traceId": "90d78d0777be", "message": "Validation failed...",
    "details": [{"violation": "NOTNULL", "field": "lineItems[0].unitPrice.taxRatePercentage",
                 "message": "darf nicht leer sein"}]}
   ```
3. **Bare message** — auth/connection errors: `{"message": "Unauthorized"}`.

`message` may be **German** and the docs say it is "not suitable for presenting to end-users". We
log it and show our own text, keeping `traceId` for support.

### 3.6 Datetime format

Exactly `yyyy-MM-ddTHH:mm:ss.SSSXXX` — literal `T`, **exactly three** millisecond digits, offset
`Z` or `+00:00` **with a colon**. Anything else → 406. Note `vouchers` use plain `yyyy-MM-dd`
instead, and `voucherlist` date filters use `yyyy-MM-dd` interpreted as full days in **CET/CEST**.

---

## 4. Resources used

| Resource | Endpoint | Used for |
| --- | --- | --- |
| Profile | `GET /v1/profile` | Connection test, `organizationId`, tax type, small-business flag |
| Contacts | `/v1/contacts` | Client ↔ contact mapping, optional contact creation |
| Invoices | `/v1/invoices` | Draft creation, mirroring |
| Invoice file | `GET /v1/invoices/{id}/file` | PDF / e-invoice download |
| Voucherlist | `GET /v1/voucherlist` | Discovery of invoices & expenses |
| Vouchers | `/v1/vouchers` | Bookkeeping vouchers, expenses |
| Payments | `GET /v1/payments/{voucherId}` | Payment status, open amount |
| Event subscriptions | `/v1/event-subscriptions` | Webhook registration |

### 4.1 Profile

```json
{"organizationId": "aa93e8a8-...", "companyName": "Testfirma GmbH",
 "connectionId": "3dea098a-...", "taxType": "net", "smallBusiness": false,
 "businessFeatures": ["INVOICING", "BOOKKEEPING"], "subscriptionStatus": "active"}
```

* `taxType` here is only `net` | `gross` | `vatfree` — **narrower than the invoice enum**.
* `distanceSalesPrinciple` (`ORIGIN`|`DESTINATION`) is in the property table but absent from the
  sample.
* **`subscriptionStatus` and `features` appear only in the sample response and are absent from the
  property table. Their enums are UNVERIFIED.** We store and display `subscriptionStatus` verbatim
  but **never branch on it**.

`organizationId` is stored on connect and used to verify every inbound webhook (§7.3).

### 4.2 Contacts

* `roles` — **presence implies the role**: `{"customer": {}}`. At least one role required. On create
  the role **must be an empty object**; `number` is Lexware-generated and read-only.
* `company` and `person` are **mutually exclusive**; exactly one required.
* `emailAddresses` keys: `business`, `office`, `private`, `other`.
  `phoneNumbers` keys: `business`, `office`, `mobile`, `private`, `fax`, `other`. Values are lists
  of plain strings.
* **⚠️ Write constraint that shapes our model:** create/update accepts a **maximum of ONE entry per
  list** (one billing address, one shipping, one per email/phone type, one contactPerson). Contacts
  with more can be **read** but **any PUT fails**.

  **Design consequence:** Coreflow keeps its own richer `ClientContact` model and pushes only a
  reduced projection to Lexware. Before any PUT we check the remote contact for multi-entry lists
  and, if found, refuse to write and raise a conflict for manual resolution rather than failing
  opaquely. A contact edited in the Lexware web UI can permanently break the PUT path — this is a
  documented dead end, not a bug we can fix.
* Search filters (`email`, `name`, ≥3 chars) support `_`/`%` **wildcards**, so user input must be
  escaped, and `&`/`<`/`>` need **HTML-encoding *and* URL-encoding**.

### 4.3 Invoices

**Required on create:** `voucherDate`, `address`, `lineItems`, `totalPrice`, `taxConditions`,
`shippingConditions`. Read-only fields must not be sent.

* `lineItems` — max **300**. `type` ∈ `service` | `material` | `custom` | `text` (**lowercase**;
  note `articles.type` is uppercase `PRODUCT`/`SERVICE`).
  * `service`/`material` require an `id` referencing an article — and still require all properties.
  * `custom` has no id. `text` carries only `name`/`description`, no price.
* `unitPrice.currency` — **`EUR` only**.
* `totalPrice` — only `currency` is required on create; the amounts are **read-only** and computed.
* `taxAmounts[]` — **read-only, submitted content is ignored**.
* `address` — either `contactId` (contact must hold role `customer`) **or** a one-time address
  (`name` + `countryCode` required).
* `shippingConditions.shippingType` ∈ `service` | `serviceperiod` | `delivery` | `deliveryperiod` |
  `none`; `shippingDate` required unless `none`; period types need `shippingEndDate`.
  Coreflow bills work over a period → we send **`serviceperiod`** with the time-entry range.
* `voucherNumber` and `dueDate` are **read-only** — Lexware assigns them.

### 4.4 Tax types — three different enums

Do **not** share one type across resources:

| Context | Field | Values |
| --- | --- | --- |
| Invoices | `taxConditions.taxType` | `net`, `gross`, `vatfree`, `intraCommunitySupply`, `constructionService13b`, `externalService13b`, `thirdPartyCountryService`, `thirdPartyCountryDelivery`, `photovoltaicEquipment` |
| Profile | `taxType` | `net`, `gross`, `vatfree` |
| Vouchers | `taxType` | `net`, `gross` |

* Vat-free vouchers require `unitPrice.taxRatePercentage = 0`.
* All vat-free types **other than `vatfree`** require a **referenced contact** (`address.contactId`),
  not a one-time address.
* **UNVERIFIED:** the properties table lists 9 `taxType` values but the *create* table lists 8,
  omitting `photovoltaicEquipment`. We do not offer it as a create option.

### 4.5 Kleinunternehmer (§19 UStG) — what is actually documented

Only three things are documented:

1. `profile.smallBusiness` is a boolean reflecting §19 UStG status.
2. `profile.taxType` may be `vatfree`, and "for tax-exempt organizations vat-free invoices can be
   created exclusively."
3. The bookkeeping category `f5c7fee8-f184-4e7a-ab04-8f7e7ad6c207` = "Einnahmen als
   Kleinunternehmer" (**changed 2026-04-28** from `7a1efa0e-...`).

> **🚩 UNVERIFIED — this is the single most important caveat in this document.**
> The docs **never state how `smallBusiness` affects an invoice payload**. There is no section
> linking it to a required `taxConditions.taxType`, and no worked Kleinunternehmer example. The
> chain "smallBusiness ⇒ vatfree invoices" is an *inference*, and the two profile fields are
> independent, so they are not guaranteed to co-vary.

**How Coreflow handles this** (satisfying "Steuerart nicht blind hardcoden"):

* We **never hardcode** a tax type.
* The default `taxConditions.taxType` for a new invoice is read from **`profile.taxType`**, which is
  documented and authoritative — not inferred from `smallBusiness`.
* `smallBusiness` is surfaced in the invoice preview as an informational banner.
* The tax type is an **explicit, user-editable field in the invoice preview**, defaulted but always
  overridable, with the resolved value shown before submission.
* If the profile has not been fetched, invoice creation is **blocked** with a clear message rather
  than guessing.

### 4.6 Invoice PDF — use `/file`, not the deprecated flow

**✅ `GET /v1/invoices/{id}/file`** returns the binary directly with `Content-Disposition`.

| Profile | `Accept: */*` | `application/xml` | `application/pdf` |
| --- | --- | --- | --- |
| XRechnung | .xml | .xml | .pdf (preview only, **not a valid e-invoice**) |
| ZUGFeRD | .pdf | 404 | .pdf |
| Regular | .pdf | 404 | .pdf |

Draft invoice → **409**. Missing → 404. Other media types → 406.

**⚠️ Deprecated (2025-08-13):** `GET /v1/invoices/{id}/document` → `documentFileId` →
`GET /v1/files/{id}`. The `files` object, `documentFileId`, and downloading *sales*-voucher
documents via `/v1/files/{id}` are all deprecated. **Coreflow does not use them.**
(`/v1/files/{id}` remains correct for *bookkeeping* voucher documents.)

Inconsistency to code around: a draft returns **406** from `/document` but **409** from `/file`.

### 4.7 Voucherlist

`voucherType` and `voucherStatus` are **both mandatory** (comma-separated, or the literal `any`).

* `openAmount` **may be null** (e.g. drafts). `contactId` is **null for the Collective Contact**.
* **`overdue` cannot be combined with other status filters.**
* The docs warn new types/states may be added → unknown values are stored verbatim and ignored, not
  crashed on.

### 4.8 Payments

`GET /v1/payments/{voucherId}` — the path param is the **voucher id**, not a payment id.

* `paymentStatus` ∈ `balanced` | `openRevenue` | `openExpense`. `openAmount` is **positive for both
  revenue and expense**.
* `paidDate` present **only** when `paid`/`paidoff`.
* **Drafts return 406 — the docs stress "this is not an error condition."** We treat 406 here as
  "no payment info yet", not as an error.
* Voided vouchers report as balanced with zero open amount.
* One doc sample shows `openAmount` as a **string** while others show a number — **UNVERIFIED**;
  we parse leniently via `Decimal(str(value))`.

---

## 5. Local mirror

See [`docs/data-model.md`](../data-model.md) for full field lists. Every mirrored object is tied to
its remote counterpart through `ExternalObjectLink`, never by storing a foreign ID on the domain
model:

```
ExternalObjectLink(provider="lexware", resource_type="invoice",
                   local_object_type="invoicing.Invoice", local_object_id=<uuid>,
                   external_id="e9066f04-...", external_version=3,
                   sync_hash="sha256:...", last_synced_at=..., deleted_remotely=false)
```

`sync_hash` is a stable hash of the normalised remote payload. If the hash is unchanged we skip the
write entirely — this is what makes repeated webhooks and overlapping syncs idempotent.

---

## 6. Invoice workflow

### 6.1 Steps

1. User selects open time entries (client or project scope).
2. Chooses grouping: per entry / per day / per service type / per phase / per task / one lump sum.
3. Coreflow builds a **local `Invoice` in status `draft_local`** with `InvoiceLine`s and
   `InvoiceTimeEntry` links — **before** any network call.
4. The preview is fully editable: texts, quantities, hours, prices, address, payment term, tax type.
5. On confirm, Coreflow POSTs to Lexware **without `finalize`** → a Lexware **draft**.
6. `ExternalObjectLink` stores the Lexware id + version; local status → `draft_remote`.
7. Selected time entries → `invoice_draft_created` (they are now locked against re-billing).
8. The user reviews and **finalises in Lexware**.
9. `invoice.status.changed` webhook (or the periodic sync) pulls status, `voucherNumber` and PDF.
10. Local status → `open`; time entries → `billed`.
11. `payment.changed` updates paid amount / open amount / `paidDate`.

### 6.2 Draft is the default, and finalisation is not ours to do

`LEXWARE_CREATE_FINAL_INVOICES` defaults to **false** and gates step 5 only.

> **⚠️ Documented hard constraint:** *"The status of an invoice cannot be changed via the api."*
> There is **no draft → open transition endpoint**. `?finalize=true` works **only at creation**.

Consequences, which are product-visible and not worked around:

* Coreflow **cannot** offer a "finalise this draft" button. Once created as a draft, the invoice can
  only be finalised **in Lexware**. The UI says so explicitly and deep-links to Lexware.
* Setting `LEXWARE_CREATE_FINAL_INVOICES=true` makes step 5 issue a **legally binding invoice with a
  real number immediately**, with no review. It is therefore off by default, marked as such in the
  settings UI, and requires an explicit typed confirmation.

### 6.3 Double-billing protection

Defence in depth — a time entry must never land on two invoices:

1. A **partial unique index** in PostgreSQL: a `TimeEntry` may appear in at most one
   `InvoiceTimeEntry` whose invoice is not `cancelled`. This is the real guarantee.
2. `TimeEntry.billing_status` moves `open → invoice_draft_created → billed` and the selection
   endpoint only accepts `open`.
3. Selection is re-validated inside the same transaction with `SELECT ... FOR UPDATE`, so two
   concurrent requests cannot both pass the check.

### 6.4 The 504 duplicate-invoice hazard

A 504 may mean the invoice **was** created. Blind retry ⇒ duplicate invoice. Therefore:

* Invoice POST is **excluded from automatic retry**.
* On timeout the local invoice is parked in `send_pending` and a **reconciliation task** searches
  the voucherlist by date + amount + contact for a matching invoice created in the window.
* If exactly one match is found we adopt it; otherwise a `SyncConflict` is raised for the human.
  We never silently retry.

---

## 7. Webhooks

### 7.1 Event types (complete documented list — 41)

`article.created|changed|deleted` · `contact.created|changed|deleted` ·
`credit-note.created|changed|deleted|status.changed` ·
`delivery-note.created|changed|deleted|status.changed` ·
`down-payment-invoice.created|changed|deleted|status.changed` ·
`dunning.created|changed|deleted` (**no `.status.changed`** — asymmetry is in the source) ·
`invoice.created|changed|deleted|status.changed` ·
`order-confirmation.created|changed|deleted|status.changed` · **`payment.changed`** ·
`quotation.created|changed|deleted|status.changed` ·
`recurring-template.created|changed|deleted` · `token.revoked` ·
`voucher.created|changed|deleted|status.changed`

Coreflow subscribes to: `contact.*`, `invoice.*`, `payment.changed`, `voucher.*`, `token.revoked`.

Notes:
* **`payment.changed` is shared by credit-notes, invoices AND vouchers.** `resourceId` alone does
  not say which endpoint to call — we resolve via our local link table, then voucherlist.
* **`token.revoked`'s `resourceId` is the `connectionId`, not a resource id.** We store
  `connectionId` from the profile at connect time so the event can be matched.
* `voucher.created` fires **after OCR**, and extra `voucher.changed` events arrive unprompted.

### 7.2 Callback body

```json
{"organizationId": "aa93e8a8-...", "eventType": "contact.changed",
 "resourceId": "4d43ad14-...", "eventDate": "2023-04-11T12:30:00.000+02:00"}
```

Exactly four fields. **The payload carries no resource data** — it is a pointer. We must GET the
resource. This is why every webhook handler is a fetch-then-reconcile, never a blind apply.

### 7.3 Authenticity — three independent layers

> **Correction to the original brief.** The brief said not to rely on invented signature headers.
> **Lexware does document a real signature mechanism**, so we use it. The secret path is kept as
> defence in depth.

1. **Secret path segment** — the callback URL is
   `{LEXWARE_WEBHOOK_PUBLIC_URL}/api/v1/webhooks/lexware/{LEXWARE_WEBHOOK_SECRET}/`. Unguessable, so
   scanners never reach the handler. Compared in constant time.
2. **RSA-SHA512 signature** — header **`X-Lxo-Signature`**, base64, over **the JSON body without
   whitespace or linebreaks**, verified with the published public key:
   <https://developers.lexware.io/webhookSignature/public/public_key.pub> (4096-bit RSA).
   * Verified against **the raw request body bytes**, captured *before* JSON parsing —
     re-serialising will not reproduce the signed bytes.
   * The key is **bundled in the repo** (it is public, not a secret) and pinned. No key-rotation
     policy or key-id header is documented — **UNVERIFIED**; a rotation therefore needs a release,
     and the verification failure is loud.
   * Doc-published test fixtures (`sample_payload.json`, `sample_signature_base64`) are used as
     real test vectors in `apps/integrations/lexware/tests/test_webhook_signature.py`.
3. **`organizationId` check** — must equal the stored profile `organizationId`.

**Replay protection:** no timestamp/nonce scheme is documented (**UNVERIFIED**). We deduplicate on
`(eventType, resourceId, eventDate)` and, because handling is a fetch-then-reconcile against
`sync_hash`, a replayed event is a no-op regardless.

### 7.4 Delivery, retries, timeout — why we ack immediately

* Success = 200/201/202/204. 401/403/429/5xx → retried.
* **404 or DNS failure → the subscription is auto-deleted.** **410 → removed immediately.**
* Retries: 5 at 10/20/40/80/160 s, then after a 30 min pause, 20 more at 2 h intervals.
* **HTTP read timeout: 5000 ms.**

**Design consequence:** the endpoint does the absolute minimum — verify, persist a `WebhookEvent`,
enqueue a Celery task, return 204. Processing inline would exceed 5 s under load, trigger retries,
and a persistent 404 would silently delete our subscription.

### 7.5 Subscription lifecycle

* Both `eventType` and `callbackUrl` required; URL must be **HTTPS** and is validated with a HEAD
  request (failure → 406).
* Duplicates → 409. **There is no update — delete and recreate.**
* **⚠️ Invalidating an API key deletes every subscription created with it.** The integration page
  therefore shows live subscription state from `GET /v1/event-subscriptions` rather than a local
  flag, and offers a re-register action.
* **Field-name asymmetry:** create returns **`id`**; GET/list return **`subscriptionId`** and no
  `version`. Modelled as two distinct types.

---

## 8. Sync strategy

| Trigger | Scope |
| --- | --- |
| Connect / manual full sync | Profile → contacts → invoices → vouchers → payments, windowed by month |
| Celery Beat every `LEXWARE_SYNC_INTERVAL_MINUTES` | Voucherlist `updatedDateFrom` = last success − 5 min overlap |
| Webhook | Single resource by id |
| Manual per-object | Single resource by id |

The 5-minute overlap covers clock skew; idempotency via `sync_hash` makes the overlap free.

Because of the 10,000-element window (§3.2), full sync iterates **month by month** from the earliest
invoice date. Progress is recorded in `SyncJob` so a failure resumes rather than restarting.

### Time-entry matching on import

After an invoice mirror lands (and again on every re-run, for mirrors that have no links yet),
`apps/integrations/lexware/matching.py` assigns its hour lines to open local time entries — same
client, inside the mirrored service period, and only when the hours add up **exactly**; anything
ambiguous stays unmatched rather than guessed. Created links carry `source="lexware_import"` (vs.
`compose` for the local composer), which the UI shows as an "aus Lexware" marker on both the invoice
lines and the time entries. Matched entries move to `billed` (finalised vouchers) or
`invoice_draft_created` (remote drafts), closing the double-billing gap for hours that were invoiced
in Lexware before Coreflow existed.

### Conflict handling

Lexware wins for accounting fields — always. A `SyncConflict` is raised only where Coreflow is
allowed to write (contacts, and invoice drafts we created):

* Remote `version` advanced while we held a stale copy (409).
* Remote contact has multi-entry lists we cannot write (§4.2).
* A local draft's remote counterpart vanished (`deleted_remotely`).

Conflicts surface in the integration centre with both snapshots and are resolved manually. Nothing
is auto-merged and nothing is silently dropped.

---

## 9. Testing

* **No sandbox exists.** The strings `sandbox`/`test environment`/`staging` appear **zero times** in
  the docs. There is one base URL and no test mode.
* The sanctioned approach is **disposable 30-day trial accounts** against production
  (<https://app.lexware.de/signup/app/trial>, "as many accounts as you need").
* **Therefore the automated suite never touches the network.** All Lexware tests use `respx` to mock
  HTTP, driven by fixtures captured from the documented examples
  (`apps/integrations/lexware/tests/fixtures/`). `config.settings.test` force-disables the
  integration and blanks the key, so a missing mock fails loudly instead of dialling out.
* The webhook signature test uses Lexware's **own published sample payload and signature** as a
  vector, so our verification is checked against real data.

---

## 10. Trap list (all doc-sourced)

1. `Retry-After` does not exist; **500 can mean rate-limited**.
2. 2 req/s is **global** — serialise, don't parallelise.
3. Validation failures are **406**, not 400/422.
4. Three error shapes; auth errors are a bare `message`.
5. **Invoice finalisation is create-time only.**
6. Field drift: `taxRatePercentage` (invoices) vs `taxRatePercent` (vouchers); `id` (subscription
   create) vs `subscriptionId` (get); RFC-3339 (invoices) vs `yyyy-MM-dd` (vouchers).
7. Contacts with >1 entry per list are **read-only via API**.
8. Deleting an API key **deletes all its event subscriptions**.
9. **10,000-result search window** — window syncs by date.
10. **504 does not mean failure.**
11. `voucher.created` fires post-OCR; unprompted `voucher.changed` events occur.
12. Omitting existing file ids when updating a voucher **permanently deletes them**.
13. `documentFileId` / `/document` / `files` objects are **deprecated**.
14. Search strings need HTML- **and** URL-encoding.
15. Datetime must be exactly `yyyy-MM-ddTHH:mm:ss.SSSXXX`.

---

## 11. Reference links

| Topic | URL |
| --- | --- |
| Introduction / base URL | <https://developers.lexware.io/docs/#lexware-api-documentation-introduction> |
| Rate limits | <https://developers.lexware.io/docs/#api-rate-limits> |
| Paging | <https://developers.lexware.io/docs/#paging-of-resources> |
| Optimistic locking | <https://developers.lexware.io/docs/#optimistic-locking> |
| Error codes | <https://developers.lexware.io/docs/#error-codes> |
| Profile | <https://developers.lexware.io/docs/#profile-endpoint> |
| Contacts | <https://developers.lexware.io/docs/#contacts-endpoint> |
| Invoices | <https://developers.lexware.io/docs/#invoices-endpoint> |
| Invoice file download | <https://developers.lexware.io/docs/#invoices-endpoint-download-an-invoice-file> |
| Voucherlist | <https://developers.lexware.io/docs/#voucherlist-endpoint> |
| Vouchers | <https://developers.lexware.io/docs/#vouchers-endpoint> |
| Payments | <https://developers.lexware.io/docs/#payments-endpoint> |
| Files | <https://developers.lexware.io/docs/#files-endpoint> |
| Event subscriptions | <https://developers.lexware.io/docs/#event-subscriptions-endpoint> |
| Event types | <https://developers.lexware.io/docs/#event-subscriptions-endpoint-event-types> |
| Webhook signature | <https://developers.lexware.io/docs/#event-subscriptions-endpoint-verify-authenticity> |
| Webhook public key | <https://developers.lexware.io/webhookSignature/public/public_key.pub> |
| Change log | <https://developers.lexware.io/docs/#change-log> |
