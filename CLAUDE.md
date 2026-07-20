# CLAUDE.md — Polar-GIS (极地海洋环境信息平台)

## Project Overview

Polar-GIS is a full-stack GIS platform focused on polar/marine environmental data, supporting S-57 nautical charts, Arctic projection (EPSG:3413), and spatial querying.

- **Backend**: Python 3.12+ / FastAPI + SQLAlchemy + PostgreSQL/PostGIS + GDAL + GeoServer
- **Frontend**: Vue 3 + Vite + TypeScript + Element Plus + OpenLayers + ECharts + Pinia
- **Deployment**: Docker Compose (5 services: postgres, geoserver, backend, worker, web/nginx)

## Repository

- **GitHub**: https://github.com/shifengdongma/polar-gis.git
- **Default branch**: `master`

---

## ⚡ CRITICAL RULES — Must Follow

### 1. Virtual Environment Location

**ALL Python dependencies, packages, and virtual environment files MUST be stored under `F:\polar-gis\.venv\`.**

- Never create or place `.venv`, `venv`, `node_modules`, or any dependency/package files in `C:\` drive.
- All software paths, dependencies, and runtime data must live under `F:\polar-gis\`.
- When creating the virtual environment: `python -m venv F:\polar-gis\.venv`
- When installing Python packages, ensure the `.venv` is activated first.

### 2. Documentation Convention

Three documentation files MUST be maintained under `docs/`:

| File | Purpose |
|------|---------|
| `docs/09-system-architecture.md` | System architecture: front/backend code structure, file composition, code principles, data flow |
| `docs/10-work-log.md` | Work log: task plan for the current session, modifications made, decisions taken |
| `docs/11-work-summary.md` | Work summary: what was modified, what effects/goals were achieved |

**After every code change or update, you MUST update these three docs accordingly.**

The existing `docs/01-08` files are design-phase documents and should be preserved as reference but not modified.

### 3. Git Workflow

**After every update/change, you MUST:**

```bash
git add -A
git commit -m "<descriptive commit message>"
git push origin master
```

- Commit messages should be in Chinese or English, describing what changed and why.
- Push to `https://github.com/shifengdongma/polar-gis.git` immediately after each commit.
- Ensure the remote is configured: `git remote add origin https://github.com/shifengdongma/polar-gis.git`

---

## Project Structure

```
F:\polar-gis\
├── backend/                    # FastAPI Python backend
│   ├── app/
│   │   ├── api/                # REST API routers (auth, projects, datasets, layers, etc.)
│   │   ├── core/               # Config, database, security, middleware, errors
│   │   ├── services/           # Business logic (geoserver, importer, s57, storage, etc.)
│   │   ├── worker/             # Background worker (import job processing)
│   │   ├── models.py           # SQLAlchemy ORM models (16+ tables)
│   │   ├── schemas.py          # Pydantic request/response schemas
│   │   ├── main.py             # FastAPI app entry point
│   │   └── cli.py              # CLI admin creation tool
│   ├── migrations/             # Alembic database migrations
│   ├── tests/                  # pytest test suite (40 tests)
│   ├── pyproject.toml          # Dependencies & build config
│   ├── alembic.ini             # Migration config
│   └── Dockerfile              # Production container
├── frontend/                   # Vue 3 SPA frontend
│   ├── src/
│   │   ├── api/                # Axios client with auto-refresh
│   │   ├── components/         # Shared components (WeatherChart)
│   │   ├── layouts/            # AppLayout shell (sidebar + main)
│   │   ├── router/             # Vue Router with auth guards
│   │   ├── stores/             # Pinia stores (auth, projects)
│   │   ├── types/              # TypeScript type definitions
│   │   ├── utils/              # Utilities (mapExtent, s57ObjectNames)
│   │   └── views/              # Page components (login, map, projects, admin/)
│   ├── package.json            # Node dependencies
│   ├── vite.config.ts          # Vite build config (proxy to backend)
│   └── Dockerfile              # Multi-stage build (node → nginx)
├── deploy/                     # Docker Compose deployment
│   ├── compose.yml             # 5-service orchestration
│   ├── .env.example            # Production env template
│   └── nginx/                  # Reverse proxy config
├── docs/                       # Design docs (01-08) + living docs (09-11)
├── data/                       # Test data samples only
├── scripts/                    # Utility scripts (S-57 check)
└── .venv/                      # Python virtual environment (DO NOT USE C:\)
```

---

## Key Commands

### Backend Development

```bash
# Activate virtual environment
source F:/polar-gis/.venv/Scripts/activate

# Install backend dependencies (development mode)
cd F:/polar-gis/backend
pip install -e ".[dev]"

# Run backend dev server
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# Run tests
pytest tests/ -v

# Run tests with coverage
pytest tests/ -v --cov=app --cov-report=html

# Run linting
ruff check app/

# Create Alembic migration
alembic revision --autogenerate -m "description"

# Run migrations
alembic upgrade head

# Create admin user
python -m app.cli create-admin --username admin --password <password>
```

### Frontend Development

```bash
cd F:/polar-gis/frontend

# Install dependencies
npm ci

# Run dev server (port 5173, proxied to backend at 8000)
npm run dev

# Build for production
npm run build

# Run tests
npm test

# Type check
npm run typecheck
```

### Docker (Production)

```bash
# Start all services
cd F:/polar-gis/deploy
cp .env.example .env   # edit .env with real credentials first
docker compose up -d --build

# Stop all services
docker compose down

# View logs
docker compose logs -f backend
```

---

## Architecture Notes

### Backend API
- All endpoints under `/api/v1/`
- Auth: JWT access token (Bearer header) + refresh token (HTTP-only cookie)
- Two roles: `system_admin` and `user`
- Soft-delete pattern on all major entities
- Versioned datasets with parent-child chain for S-57 updates
- Background worker polls for import jobs separately from the API server

### Frontend SPA
- Vue Router with lazy-loaded routes and navigation guards
- Pinia stores for auth (login/bootstrap/logout) and projects
- Axios with automatic token refresh (deduplicated concurrent calls)
- OpenLayers map with EPSG:3413 (Arctic) and EPSG:3857 support
- Element Plus UI with Chinese locale
- Vite proxy: `/api` → backend, `/geoserver` → GeoServer

### Database
- PostgreSQL with PostGIS extension
- 16 tables across default schema and `geo` schema (for imported spatial data)
- Alembic manages schema migrations
