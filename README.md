# CodeMind

CodeMind is an AI-powered codebase intelligence and developer assistant. It connects public GitHub repositories and provides source scanning, parsing, semantic search, cited codebase Q&A, dependency and architecture analytics, static security scanning, and AI-assisted documentation and test generation.

## Architecture

- **Frontend:** React, TypeScript, Vite, React Router, and Nginx for production static hosting.
- **Backend:** FastAPI, Pydantic v2, SQLAlchemy, and Uvicorn.
- **Relational database:** MySQL stores users, repositories, and analysis metadata.
- **Vector search:** ChromaDB runs in embedded persistent mode inside the backend. It is not a separate service.
- **Embeddings:** Sentence Transformers runs locally in the backend; the model is downloaded when first needed.
- **AI provider:** Groq supports codebase Q&A, documentation, and test generation when configured.
- **Repository files:** Public GitHub repositories are cloned into backend-managed storage. Git is installed in the backend image.

```text
Browser ── HTTP ──> Nginx frontend ── /api/* ──> FastAPI backend ──> MySQL
                                             ├──> persistent ChromaDB
                                             └──> repository storage
```

In Compose, the browser uses the same-origin Nginx proxy. MySQL and the backend are not published to host ports by default.

## Features

- User registration, JSON login, OAuth2 password-token endpoint, and protected routes.
- Connect, clone, analyze, and manage public GitHub repositories.
- Source scanning, multi-language parsing, code chunking, and vector indexing.
- Semantic code search and repository Q&A with citations.
- Dependency graph and architecture analytics.
- Static security analysis through Semgrep when installed.
- AI-generated documentation and unit tests through Groq.

Generated tests are not executed or verified automatically. Security scanning returns an unavailable response when Semgrep is not installed.

## Prerequisites

### Docker deployment

- Docker Engine with Docker Compose v2 (`docker compose`).
- Enough disk space for MySQL, repository clones, ChromaDB vectors, and the local embedding model cache.
- Outbound network access for public GitHub clones, package/model downloads, and Groq calls when enabled.

Docker Desktop is suitable for local development. No host MySQL or Git installation is required for the Compose deployment.

### Local development

- Python 3.11 and Git.
- Node.js 22 or a compatible current LTS release and npm.
- MySQL compatible with the existing schema.

## Docker setup

### Configure environment

From the project root, copy the example only when a root `.env` does not already exist:

```powershell
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
```

Edit the new root `.env` and replace `MYSQL_PASSWORD`, `MYSQL_ROOT_PASSWORD`, and `JWT_SECRET_KEY`. Use different strong database passwords and a unique random JWT secret. For example, generate a random secret in PowerShell:

```powershell
$bytes = New-Object byte[] 48
$rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
$rng.GetBytes($bytes)
[Convert]::ToBase64String($bytes)
$rng.Dispose()
```

Set `GROQ_API_KEY` only when using AI documentation, test generation, or Q&A. Leaving it blank is supported; those endpoints will report that AI is unavailable. CodeMind uses GitHub's public API and does not require a GitHub token.

`CORS_ORIGINS` is a comma-separated list. `VITE_API_BASE_URL` should remain empty for the default same-origin Nginx proxy. If you change `FRONTEND_PORT`, update the corresponding origins if the browser will call the backend directly.

### Build and start

```powershell
docker compose config --quiet
docker compose up --build -d
docker compose ps
```

Open:

- Application: `http://localhost:8080` (or the configured `FRONTEND_PORT`).
- FastAPI Swagger documentation: `http://localhost:8080/docs`.
- Backend health via Nginx: `http://localhost:8080/health`.

View logs:

```powershell
docker compose logs -f backend frontend mysql
```

Stop the services without deleting persistent data:

```powershell
docker compose down
```

Do **not** use `docker compose down --volumes` unless you intentionally want to permanently delete the Compose-managed database, repositories, vector index, and model cache.

### Data persistence and existing installations

Compose creates named volumes for MySQL, cloned repositories, ChromaDB, and the embedding model cache. These are separate from any existing host MySQL database or repository/vector directories; Compose does not import, replace, or delete those existing locations. Back up and migrate existing data deliberately before switching deployments. MySQL initialization variables apply when its data volume is first created; changing a password in `.env` does not change credentials inside an already-initialized database.

The backend runs SQLAlchemy `create_all` at startup. The repository currently has no migration directory; `create_all` creates missing tables but is not a schema migration system.

## Local development

Use the existing backend `.env` carefully if present; do not overwrite it. Backend settings are read from `backend/.env` and can also be supplied through environment variables. For a local backend, set MySQL host to `127.0.0.1` (or your MySQL host), and set the required database and JWT values.

### Backend

```powershell
Set-Location backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --reload
```

The local API is `http://127.0.0.1:8000`; Swagger is at `http://127.0.0.1:8000/docs`. The default development CORS origins allow Vite on ports 5173 and 5181 for both `localhost` and `127.0.0.1`.

### Frontend

In another PowerShell terminal:

```powershell
Set-Location frontend
npm ci
npm run dev -- --host 127.0.0.1 --port 5173
```

Open `http://127.0.0.1:5173`. Vite proxies `/api` requests to the local backend at `http://127.0.0.1:8000`. For Docker, leave `VITE_API_BASE_URL` empty so browser API requests use Nginx's internal backend proxy. A non-empty `VITE_API_BASE_URL` overrides the proxy destination and is embedded at build time.

## Configuration reference

| Variable | Purpose |
| --- | --- |
| `MYSQL_HOST`, `MYSQL_PORT` | MySQL hostname and port; Compose sets the backend host to `mysql`. |
| `MYSQL_DATABASE`, `MYSQL_USER`, `MYSQL_PASSWORD` | Application database and user. |
| `MYSQL_ROOT_PASSWORD` | MySQL container initialization only; not used by the backend. |
| `JWT_SECRET_KEY`, `JWT_ALGORITHM`, `ACCESS_TOKEN_EXPIRE_MINUTES` | Signed access-token settings. Keep the secret private and stable for the deployment. |
| `GROQ_API_KEY`, `GROQ_MODEL` | Optional Groq provider configuration. |
| `CORS_ORIGINS` | Comma-separated allowed browser origins, including scheme and port. |
| `CODEMIND_STORAGE_DIR` | Persistent location for cloned repositories; Compose mounts `repository_data` here. |
| `VECTOR_DB_DIR` | Persistent ChromaDB directory; Compose mounts `vector_data` here. |
| `VITE_API_BASE_URL` | Frontend API base embedded at build time; empty uses the same-origin Nginx proxy. |
| `FRONTEND_PORT` | Host port published by the frontend container; defaults to 8080. |
| `DEBUG` | Debug and SQL logging switch; defaults to `false`. Keep it disabled in production. |

No GitHub credential is currently used; repository connections are limited to public GitHub repositories. The Semgrep scanner is optional and is not included in the base backend image.

## Troubleshooting

- **Compose reports a missing variable:** Check the root `.env` exists and required password/JWT placeholders have been replaced.
- **MySQL is unhealthy:** Check `docker compose logs mysql`; ensure the volume is writable and credentials match the first-time volume initialization.
- **Backend does not start:** Check `docker compose logs backend`. The backend waits for MySQL health and creates missing tables during startup.
- **Frontend cannot reach the API:** Keep `VITE_API_BASE_URL` empty for the standard Compose setup; verify the backend is healthy and inspect `docker compose logs frontend backend`.
- **Browser CORS errors during local development:** Include the exact frontend origin (scheme, hostname, and port) in backend `CORS_ORIGINS`.
- **Indexing is slow on first use:** The local Sentence Transformers model is loaded/downloaded on first embedding request. Its cache is persisted in the `model_cache` volume.
- **AI endpoint reports unavailable:** Set a valid `GROQ_API_KEY` and recreate the backend container. No Groq request is needed for startup or health checks.
- **Security scan reports unavailable:** Install and configure Semgrep in a deliberate custom backend image; the default image returns a clear unavailable response.
- **Host port is occupied:** Change `FRONTEND_PORT` in the root `.env`, rebuild/restart, and update any direct-access CORS origin.

## Security and deployment notes

- Never commit `.env` files or put secrets in Docker build arguments or image layers. Compose passes secret values as runtime environment variables; use your deployment platform's secret manager in production.
- The Docker build context excludes `.env` files, virtual environments, node modules, local build output, and repository/vector data.
- The backend runs as a non-root user. MySQL and FastAPI are only reachable on the internal Compose network; only Nginx publishes a host port.
- Keep `DEBUG=false`, use a unique JWT secret, back up persistent volumes, and terminate HTTPS at a trusted reverse proxy for public deployments.
- Restrict `CORS_ORIGINS` to the actual frontend origins. The example origins are for local development only.
- AI-generated documentation and tests may be inaccurate; generated tests are not run. Review generated content before use.
