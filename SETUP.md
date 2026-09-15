# Setup Guide — Global Energy & Maritime Intelligence Dashboard

This document rebuilds the application from a clean checkout. It deliberately contains no real API key or user-uploaded data.

## 1. Runtime

| Component | Used here | Rebuild target |
|---|---:|---:|
| Python | 3.12.14 | Python 3.12.x |
| pip | 25.0.1 | pip bundled with Python 3.12 |
| Node.js | 24.19.0 | Optional: JavaScript syntax checks only |
| npm | 11.17.0 | Optional: no frontend npm install exists |

The backend is Python/FastAPI. The frontend is static HTML/CSS/browser JavaScript, served by FastAPI. There is no Node build, package-lock, database server, ORM migration, Poetry, Conda, Go module, Yarn, or pnpm setup.

## 2. Install

### Windows PowerShell

```powershell
git clone <YOUR_REPOSITORY_URL> hrp-dashboard
Set-Location hrp-dashboard
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

If PowerShell blocks activation, run this once for the current terminal and retry:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

### macOS / Linux

```bash
git clone <YOUR_REPOSITORY_URL> hrp-dashboard
cd hrp-dashboard
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

## 3. Exact Python dependencies

`requirements.txt` is authoritative:

```text
fastapi==0.139.2
uvicorn[standard]==0.51.0
pandas==3.0.3
python-multipart==0.0.32
aiofiles==24.1.0
duckdb==1.5.5
openpyxl==3.1.5
xlrd==2.0.2
httpx==0.28.1
pydantic==2.11.7
gunicorn==23.0.0
searoute>=1.4.0
shapely==2.1.1
websockets>=12.0
python-dotenv>=1.0
pypdf>=5.0
pycountry>=24.6.1
```

## 4. Environment variables and secrets

Create the local environment file; `app.py` loads it automatically with `python-dotenv`.

```powershell
Copy-Item .env.example .env
```

Use this full template. Optional integrations may be left blank.

```dotenv
ALLOWED_ORIGINS=http://localhost:8000,http://127.0.0.1:8000

# Required for administrator-only upload, refresh, and relationship approval operations.
APP_ADMIN_TOKEN=replace-with-a-long-random-secret

# Optional live AIS vessel collection.
AISSTREAM_API_KEY=
AIS_RAW_RETENTION_DAYS=90
AIS_MAX_OBSERVATIONS=2000000

# Optional live dry-bulk news feeds.
NEWS_DATA_API_KEY=
NEWS_API_KEY=
NEWS_CACHE_TTL_SECONDS=1800

# Optional xAI/Grok-compatible integration. Either name is accepted.
XAI_API_KEY=
# GROK_API_KEY=

# Optional persistent storage. Leave blank locally to use ./uploads.
HRP_STORAGE_DIR=

# Docker/Render provides this automatically; optional for local use.
# PORT=8000
```

Never commit `.env`, browser-side JavaScript credentials, or uploaded source data. Keep all provider keys in environment settings. The `.env.example` file must remain key-free.

## 5. Data, database, and storage

The checkout must include `data/` and `static/`; these contain bundled reference data, map data, Coal India inputs, and frontend assets. User uploads, provider caches, AIS data, and refresh state use `uploads/` by default.

There is no external SQL service and no migration command. DuckDB is embedded. For production, set `HRP_STORAGE_DIR` to persistent writable storage; otherwise uploads and refresh state can disappear after a container restart.

## 6. Run locally

### Development

```powershell
.\.venv\Scripts\Activate.ps1
uvicorn app:app --host 127.0.0.1 --port 8000 --reload
```

Open <http://127.0.0.1:8000/>.

One-click alternatives:

```powershell
.\start.bat
```

```bash
chmod +x start.sh
./start.sh
```

### Production-style local start

```powershell
.\.venv\Scripts\Activate.ps1
uvicorn app:app --host 0.0.0.0 --port 8000 --workers 1
```

`python app.py` is also supported; it listens on `0.0.0.0` and reads `PORT`, defaulting to `8000`.

## 7. Test and validate

Node is only required for these optional checks:

```powershell
.\.venv\Scripts\Activate.ps1
python -m unittest discover -s tests -v
node --check static\js\app.js
node --check static\js\app-map.js
node --check static\js\broker-tools.js
```

After the server starts:

```powershell
Invoke-WebRequest http://127.0.0.1:8000/api/health
Invoke-WebRequest http://127.0.0.1:8000/api/coal/dashboard/periods
```

## 8. Docker and Render

The included Dockerfile uses `python:3.12-slim`; `render.yaml` defines the Render Blueprint.

```powershell
docker build -t hrp-dashboard .
docker run --rm -p 8000:8000 --env-file .env hrp-dashboard
```

For persistent Docker storage:

```powershell
New-Item -ItemType Directory -Force runtime-data
docker run --rm -p 8000:8000 --env-file .env -e HRP_STORAGE_DIR=/var/data/hrp -v "${PWD}\runtime-data:/var/data/hrp" hrp-dashboard
```

Render deployment steps:

1. Push the repository to GitHub.
2. Create a Blueprint from the repo, or a Docker Web Service manually.
3. Use health check path `/api/health`.
4. Add secrets in Render Environment; do not place them in `render.yaml`.
5. Attach a persistent disk and set `HRP_STORAGE_DIR=/var/data/hrp` for retained uploads and caches.
6. Render provides `PORT`; the Docker command already honours it.

## 9. OS notes

- **Windows:** use `py -3.12` where multiple Pythons are installed. `start.bat` needs `python` on `PATH`.
- **macOS/Linux:** use `python3.12`. Install compiler tools if a platform does not provide wheels for `shapely` or another dependency.
- **All systems:** port 8000 must be available. If changing it, update both the Uvicorn command and `ALLOWED_ORIGINS`.
- **External data:** weather, AIS, news, and official-source refreshes remain dependent on their upstream services and configured credentials.

## 10. Clean Windows rebuild checklist

```powershell
git clone <YOUR_REPOSITORY_URL> hrp-dashboard
Set-Location hrp-dashboard
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
Copy-Item .env.example .env
# Edit .env and add only the keys you need.
uvicorn app:app --host 127.0.0.1 --port 8000 --reload
```

Then open <http://127.0.0.1:8000/>.
