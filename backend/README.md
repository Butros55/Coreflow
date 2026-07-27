# Coreflow — Backend

Django + DRF backend for Coreflow, the central business management system.

The canonical entry point for running the whole stack is the repository root:

```bash
make up
```

See the [root README](../README.md) for the full quickstart, and
[docs/architecture.md](../docs/architecture.md) for how the backend is laid out.

## Layout

| Path | Purpose |
| --- | --- |
| `config/` | Django project: settings (split by environment), URLs, ASGI/WSGI, Celery app |
| `apps/core/` | Shared base models (UUID PK, timestamps), workspace scoping, health checks |
| `apps/accounts/` | User model, authentication, workspace membership and roles |
| `apps/crm/` | Clients, contacts, notes, activity feed |
| `apps/projects/` | Projects, phases, boards, views, sprints, tasks |
| `apps/timetracking/` | Time entries, service types, timers |
| `apps/invoicing/` | Local invoice mirror and the invoice-from-time-entries workflow |
| `apps/finance/` | Tax profile, versioned tax rules, reserve forecasting |
| `apps/scheduling/` | Appointments and calendar |
| `apps/files/` | File metadata and object storage |
| `apps/integrations/` | Provider/adapter system, external links, sync jobs, webhooks |

## Local commands

Run from the repository root (preferred, runs inside Docker):

```bash
make test        # pytest
make lint        # ruff
make typecheck   # mypy
make migrate     # apply migrations
make seed        # load demo data
```

To run directly on the host instead, from `backend/`:

```bash
uv sync --extra dev
uv run pytest
uv run ruff check .
uv run mypy .
```

Host runs need `DATABASE_URL` and `REDIS_URL` pointing at reachable services;
the Docker workflow wires these up for you.
