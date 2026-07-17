# Coreflow

Central business management system for a self-employed software developer in Germany.

CRM, projects, sprints, tasks, time tracking, invoicing, Lexware Office integration, optional
Clockodo sync, appointments, revenue analysis and tax/reserve forecasting — in one application,
instead of switching between Lexware, Clockodo, spreadsheets, a calendar and a project tool.

> **Status:** Phase 0 of 12 complete (foundation, auth, workspaces, sync infrastructure, dark UI
> shell). See [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md) for what is built and what is next.

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
make test-e2e          # Playwright end-to-end
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
Lexware/Clockodo ──▶ POST /api/v1/webhooks/…   (inbound)
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
