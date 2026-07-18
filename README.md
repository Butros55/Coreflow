# Coreflow

Central business management system for a self-employed software developer in Germany.

CRM, projects, sprints, tasks, time tracking, invoicing, Lexware Office integration, optional
Clockodo sync, appointments, revenue analysis and tax/reserve forecasting — in one application,
instead of switching between Lexware, Clockodo, spreadsheets, a calendar and a project tool.

> **Status:** all core phases delivered. Every navigation page is functional: dashboard, my tasks,
> clients (incl. client dashboard + GDPR tools), projects, kanban boards, time tracking with timer,
> calendar with ICS import/export, invoices (compose → Lexware draft → payment sync), finance with
> a traceable tax/reserve forecast, reports, files, and settings with the integration centre.
> Remaining polish is tracked in [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md).

**What it does, concretely:**

* **CRM** — clients with contacts, notes, activity feed, per-client dashboard (open hours, open
  value, projects, invoices), data export (Art. 15 DSGVO) and erasure with § 147 AO legal hold.
* **Projects & boards** — kanban with persisted drag-and-drop ordering, sprints, task drawer with
  comments/checklists, deep-linkable URLs.
* **Time tracking** — DB-enforced single running timer, manual entries, configurable rounding,
  billing lifecycle from *open* to *billed*; works fully without Clockodo.
* **Invoicing** — select open entries → grouped, editable draft → **Lexware draft** (never a final
  invoice unless you explicitly opt in) → status/number/payment mirrored back; double billing is
  blocked by a database constraint.
* **Finance** — revenue KPIs and breakdowns plus a step-by-step tax reserve forecast (§ 32a EStG
  as versioned, sourced data — not hardcoded), always marked as non-binding.
* **Integrations** — provider status cards, connection tests, manual sync, webhook setup helpers,
  sync-conflict resolution; both providers optional and off by default.
* **Audit log** — logins (incl. failures), settings changes, invoice sends, sync triggers, GDPR
  operations; admin-readable via API.

---

## Quickstart

You need **Docker** and **Docker Compose**. Nothing else — no Python, Node, or database on the host.

```bash
git clone <this-repo> && cd Coreflow
make setup
```

That creates `.env`, builds the images, runs migrations, and loads demo data. When it finishes:

| | URL |
| --- | --- |
| **Application** | <http://localhost:3000> |
| API docs (Swagger) | <http://localhost:8000/api/docs/> |
| Mailpit (dev email) | <http://localhost:8025> |
| MinIO console | <http://localhost:9001> |

Log in with the demo credentials `make setup` prints (default:
`demo@coreflow.local` / `coreflow-demo-1234`).

**No API credentials are required.** Lexware and Clockodo ship **disabled**; everything runs on
local demo data until you choose to connect them.

### Ports already in use?

Common — many machines already run Postgres on 5432 or Redis on 6379. Change the port in `.env`:

```bash
POSTGRES_PORT=5434
REDIS_PORT=6381
BACKEND_PORT=8001
FRONTEND_PORT=3000
```

Leave `APP_URL` and `API_URL` **empty**: Compose derives them from these ports, so the browser, the
CSRF allowlist and CORS all stay consistent automatically.

### Productive start — no demo data

`make setup` loads demo data for exploring. For real use (e.g. against your own Lexware account):

```bash
make up && make migrate                    # start the stack, no seeding
make bootstrap EMAIL=you@example.com NAME="Meine Firma"        # add SMALL_BUSINESS=1 for §19 UStG
```

That creates your user (password is generated and printed once — or pass `PASSWORD=...`), the
workspace, the current tax profile and the tax rulesets — nothing else. Then log in, complete the
company profile under *Einstellungen*, set `LEXWARE_ENABLED=true` + `LEXWARE_API_KEY` in `.env`,
restart (`make up`), and run the connection test under *Einstellungen → Integrationen*. Demo data
can always be added later with `make seed` (separate workspace) or removed with `make seed-reset`.

---

## Common commands

```bash
make help              # list every target

make up                # start        make down     # stop
make logs              # follow logs  make ps       # status
make clean             # stop and DELETE all volumes

make migrate           # apply migrations
make seed              # (re)load demo data — idempotent
make seed-reset        # wipe and reload demo data
make superuser         # create a Django superuser

make test              # backend + frontend unit tests
make test-e2e          # full journey: client → time → invoice → paid
make lint              # ruff + eslint
make typecheck         # mypy + tsc
make check             # everything CI runs

make backup                              # dump the database to backups/
make restore FILE=backups/xxx.dump       # restore

make shell   # Django shell        make psql    # Postgres shell
make bash    # shell in backend    make schema  # write the OpenAPI schema
```

---

## Documentation

| Document | What's in it |
| --- | --- |
| [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md) | Phase plan, stack decisions and *why*, definition of done |
| [docs/architecture.md](docs/architecture.md) | System design, ownership boundaries, integration layer, what's deliberately absent |
| [docs/data-model.md](docs/data-model.md) | Every model and field, constraints, and the reasoning behind them |
| [docs/integrations/lexware.md](docs/integrations/lexware.md) | Verified Lexware API contract, traps, and what remains UNVERIFIED |
| [docs/integrations/clockodo.md](docs/integrations/clockodo.md) | Verified Clockodo API contract, incl. the v3/v4 correction |

The two integration documents were written from the **official API documentation**, not from
assumptions, and they flag every point where the documentation is silent or self-contradictory.
They are the reference for anything provider-related.

---

## Architecture in one screen

```
browser ──▶ Next.js (:3000) ──▶ Django/DRF (:8000) ──┬─▶ PostgreSQL   system of record
                                                     ├─▶ Redis        cache + broker
                                                     ├─▶ Celery       sync, webhooks
                                                     └─▶ MinIO/S3     files

Celery ──▶ Lexware Office · Clockodo   (outbound only)
Clockodo ──▶ POST /webhooks/clockodo/          (inbound, token-verified)
```

**Who owns what** — the decision everything else follows from:

* **Coreflow** owns clients, projects, boards, sprints, tasks, time entries, appointments, budgets,
  files, forecasts, settings.
* **Lexware** owns invoice numbers, finalised invoices, invoice status, PDFs, payments, open
  amounts, bookkeeping vouchers. Coreflow **mirrors** these and never invents them.
* **Clockodo** is **optional** and owns only what originates there. The internal time tracking is
  the primary implementation and works forever with `CLOCKODO_ENABLED=false`.

No request path calls an external provider — all provider I/O runs in Celery, so a slow Lexware
degrades one feature instead of hanging the app.

---

## Integrations

Both are **off by default** and fully disableable at any time.

### Lexware Office

Set in `.env`, then restart:

```bash
LEXWARE_ENABLED=true
LEXWARE_API_KEY=<from https://app.lexware.de/addons/public-api>
```

Two things worth knowing before you switch it on:

* **Invoices are created as DRAFTS** for you to review and finalise in Lexware.
  `LEXWARE_CREATE_FINAL_INVOICES` defaults to `false` and should stay there. Lexware's API cannot
  finalise an existing draft — `?finalize=true` only works **at creation** — so setting this to
  `true` issues a legally binding invoice with a real number **immediately, with no review step**.
* **Regenerating your API key deletes every webhook subscription made with it.** Re-register them
  in the integration centre afterwards.

Full setup, webhook configuration and the verified API contract:
[docs/integrations/lexware.md](docs/integrations/lexware.md).

### Clockodo

```bash
CLOCKODO_ENABLED=true
CLOCKODO_API_USER=<your account email>
CLOCKODO_API_KEY=<Clockodo → "Personal data">
CLOCKODO_EXTERNAL_APP_EMAIL=<technical contact>   # required — every request fails without it
```

* **Webhooks cannot be registered via the API.** Clockodo has no subscription endpoint: you create
  the webhook in the Clockodo UI, and it sends a secret that a human must paste back. The
  integration centre shows you the secret when it arrives.
* Coreflow's time tracking does not depend on any of this.

Details: [docs/integrations/clockodo.md](docs/integrations/clockodo.md).

---

## Development without Docker

Docker is the supported path. To run on the host instead:

```bash
# Backend (needs a reachable Postgres + Redis)
cd backend
uv sync --extra dev
export DATABASE_URL=postgresql://coreflow:coreflow@localhost:5432/coreflow
export REDIS_URL=redis://localhost:6379/0
uv run python manage.py migrate
uv run python manage.py seed_demo
uv run python manage.py runserver

# Frontend
cd frontend
npm install
npm run dev
```

Tests run without Docker too — `uv run pytest` needs only a reachable PostgreSQL. The test settings
**force both integrations off** and block real network calls, so the suite can never reach a live
Lexware or Clockodo account.

---

## Updating

```bash
git pull
make build        # rebuild images (dependencies may have changed)
make up           # restart the stack
make migrate      # apply new migrations
```

Migrations are always additive-safe to run; `make backup` first if you want a restore point.
`make seed` is idempotent and never overwrites data you changed.

---

## Production notes

The dev compose file is for development. For a production deployment:

* Run with `DJANGO_SETTINGS_MODULE=config.settings.prod` — it **refuses to boot** on a weak
  `SECRET_KEY`, wildcard `ALLOWED_HOSTS`, non-HTTPS `APP_URL`, or an enabled integration without
  credentials, so a misconfigured deploy fails loudly instead of running insecurely.
* Terminate TLS in a reverse proxy (Caddy/nginx/Traefik) and forward `X-Forwarded-Proto: https` —
  `SECURE_PROXY_SSL_HEADER` and HSTS (1 year, preload) are already configured.
* Set `APP_URL`/`API_URL` to the public HTTPS origins; they drive CORS, CSRF and webhook URLs.
* Webhook endpoints must be publicly reachable (`/webhooks/clockodo/`); everything else can sit
  behind whatever access restrictions you like.
* Postgres and Redis should not publish ports publicly. MinIO can be replaced by any S3 bucket via
  the `OBJECT_STORAGE_*` variables.
* Schedule `make backup` (pg_dump custom format into `backups/`) via cron; restores are
  `make restore FILE=…`. Invoices/bookkeeping data are subject to the 10-year retention duty —
  back up accordingly.

---

## Troubleshooting

| Symptom | Cause / fix |
| --- | --- |
| `make setup` fails on ports | Another service owns 5432/6379/8000. Set `POSTGRES_PORT` etc. in `.env` (see Quickstart) and rerun. |
| Browser shows `net::ERR_FAILED` on API calls | `API_URL` doesn't match the published backend port. Leave `APP_URL`/`API_URL` empty in dev — compose derives them. |
| Login loops back to the login page | Stale cookies from a different port/origin. Clear cookies for `localhost`, reload. |
| "Lexware ist nicht aktiviert" when sending an invoice | Expected with `LEXWARE_ENABLED=false`: the draft stays local and fully editable. Enable the integration to transfer it. |
| Connection test fails with 401 | Wrong/rotated API key. Lexware: regenerate under *Public API*; note that rotation kills webhook subscriptions. Clockodo: key is under *Personal data*, and `CLOCKODO_EXTERNAL_APP_EMAIL` must be set. |
| Clockodo sync runs but no entries appear | Check the user mapping: entries are only imported for Clockodo users whose e-mail matches a workspace member. The sync-job counters in the integration centre show what was skipped. |
| Webhook returns 404 | `CLOCKODO_ENABLED=false` — the endpoint stays dark while disabled. |
| Sync conflict shown in the integration centre | Local and remote changed concurrently (or a billed entry changed remotely). Nothing was overwritten — pick local/remote/ignore; the decision is audit-logged. |
| Tests fail with `getaddrinfo failed` for host `postgres` | You ran host-side pytest with a Docker-internal `DATABASE_URL`. Either run `make test-backend` (in-container) or export `DATABASE_URL=postgresql://coreflow:coreflow@localhost:<POSTGRES_PORT>/coreflow`. |

---

## Security notes

* API keys are **server-side only** and never reach the browser.
* Auth is a `HttpOnly` session cookie + Django's CSRF token — no token in `localStorage`.
* Logs are **scrubbed**: credentials, `Bearer …` tokens and `?token=…` parameters are redacted by a
  structlog processor before rendering.
* `.env` is gitignored. **Never commit it.** `.env.example` documents every variable.
* Production settings **refuse to boot** on a weak `SECRET_KEY`, a wildcard `ALLOWED_HOSTS`, a
  non-HTTPS `APP_URL`, or an integration enabled without credentials.
* Invoices and bookkeeping records are subject to a **10-year retention obligation**
  (§147 AO, §257 HGB); GDPR erasure pseudonymises them rather than deleting them.

---

## Licence

Private project. Not for redistribution.
