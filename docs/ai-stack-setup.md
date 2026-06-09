# Setup Procedure: LiteLLM Proxy + Vertex AI + OpenAI-Compatible Endpoints + Valkey + Langfuse + Open WebUI

## Overview

This guide sets up the following stack, all running locally via Docker Compose:

```
OpenCode / Open WebUI
        │
        ▼
  LiteLLM Proxy  (port 4000)
  ├── Vertex AI (Gemini models via GCP)
  └── Custom OpenAI-compatible endpoints (Ollama, etc.)
        │
        ├── Valkey  (port 6379) — caching & rate-limit state
        ├── PostgreSQL (port 5432) — spend tracking & virtual keys
        └── Langfuse (port 3000) — observability
```

**OpenCode retains a direct Vertex AI provider as a fallback**, bypassing LiteLLM entirely if needed.

---

## Prerequisites

- Docker and Docker Compose installed
- A Google Cloud project with Vertex AI API enabled
- A GCP service account JSON key file with `Vertex AI User` role
- Optional: Ollama or another local model server running

---

## Step 1: Directory Structure

Create a working directory:

```bash
mkdir ~/ai-stack && cd ~/ai-stack
mkdir -p config secrets
```

---

## Step 2: GCP Service Account Credentials

Copy your service account JSON file into the secrets directory:

```bash
cp /path/to/your-service-account.json secrets/gcp-credentials.json
chmod 600 secrets/gcp-credentials.json
```

---

## Step 3: Environment File

Create `.env` with all secrets. Replace every placeholder with real values:

```bash
cat > .env << 'EOF'
# ── LiteLLM ──────────────────────────────────────────────────────────────────
LITELLM_MASTER_KEY=sk-litellm-master-changeme
# Salt key: generate once, never change after first use
# Generate with: openssl rand -hex 32
LITELLM_SALT_KEY=your-salt-key-here

# ── PostgreSQL ────────────────────────────────────────────────────────────────
POSTGRES_USER=litellm
POSTGRES_PASSWORD=litellm-db-password-changeme
POSTGRES_DB=litellm

# ── Valkey ────────────────────────────────────────────────────────────────────
VALKEY_PASSWORD=valkey-password-changeme

# ── Langfuse ──────────────────────────────────────────────────────────────────
LANGFUSE_SECRET_KEY=lf-secret-changeme
LANGFUSE_PUBLIC_KEY=lf-public-changeme
# Generate with: openssl rand -base64 32
NEXTAUTH_SECRET=nextauth-secret-changeme
SALT=langfuse-salt-changeme

# ── GCP / Vertex AI ───────────────────────────────────────────────────────────
GOOGLE_CLOUD_PROJECT=your-gcp-project-id
VERTEX_LOCATION=us-central1

# ── Custom OpenAI-compatible endpoint (e.g. Ollama) ──────────────────────────
# Leave blank if not using
CUSTOM_ENDPOINT_URL=http://host.docker.internal:11434/v1
CUSTOM_ENDPOINT_KEY=unused
EOF
```

> **Security:** Add `.env` to `.gitignore`. Never commit it.

---

## Step 4: LiteLLM Configuration

```bash
cat > config/litellm_config.yaml << 'EOF'
# =============================================================================
# LiteLLM Proxy Configuration
# =============================================================================

model_list:

  # ── Vertex AI: Gemini models ───────────────────────────────────────────────
  - model_name: gemini-2-5-pro
    litellm_params:
      model: vertex_ai/gemini-2.5-pro
      vertex_project: os.environ/GOOGLE_CLOUD_PROJECT
      vertex_location: os.environ/VERTEX_LOCATION
      vertex_credentials: /secrets/gcp-credentials.json

  - model_name: gemini-2-5-flash
    litellm_params:
      model: vertex_ai/gemini-2.5-flash-preview-04-17
      vertex_project: os.environ/GOOGLE_CLOUD_PROJECT
      vertex_location: os.environ/VERTEX_LOCATION
      vertex_credentials: /secrets/gcp-credentials.json

  # ── Custom OpenAI-compatible endpoint (e.g. Ollama) ───────────────────────
  # Duplicate and rename this block for additional local endpoints
  - model_name: llama-local
    litellm_params:
      model: openai/llama3.3:70b
      api_base: os.environ/CUSTOM_ENDPOINT_URL
      api_key: os.environ/CUSTOM_ENDPOINT_KEY

  - model_name: qwen-coder
    litellm_params:
      model: openai/qwen2.5-coder:32b
      api_base: os.environ/CUSTOM_ENDPOINT_URL
      api_key: os.environ/CUSTOM_ENDPOINT_KEY

  # ── Routing group: "smart" ─────────────────────────────────────────────────
  # Try local first, fall back to Vertex AI
  - model_name: smart
    litellm_params:
      model: openai/qwen2.5-coder:32b
      api_base: os.environ/CUSTOM_ENDPOINT_URL
      api_key: os.environ/CUSTOM_ENDPOINT_KEY

  - model_name: smart
    litellm_params:
      model: vertex_ai/gemini-2.5-flash-preview-04-17
      vertex_project: os.environ/GOOGLE_CLOUD_PROJECT
      vertex_location: os.environ/VERTEX_LOCATION
      vertex_credentials: /secrets/gcp-credentials.json

# =============================================================================
# Router settings
# =============================================================================
router_settings:
  routing_strategy: cost-based-routing
  num_retries: 2
  timeout: 60
  fallbacks:
    - {"smart": ["gemini-2-5-pro"]}

  # Valkey for shared state (rate limiting, caching across restarts)
  redis_host: valkey
  redis_port: 6379
  redis_password: os.environ/VALKEY_PASSWORD

# =============================================================================
# General proxy settings
# =============================================================================
general_settings:
  master_key: os.environ/LITELLM_MASTER_KEY
  database_url: "postgresql://os.environ/POSTGRES_USER:os.environ/POSTGRES_PASSWORD@postgres:5432/os.environ/POSTGRES_DB"

# =============================================================================
# Caching (using Valkey)
# =============================================================================
litellm_settings:
  cache: true
  cache_params:
    type: redis
    host: valkey
    port: 6379
    password: os.environ/VALKEY_PASSWORD
    ttl: 600         # cache responses for 10 minutes

  # Langfuse observability
  success_callback: ["langfuse"]
  failure_callback: ["langfuse"]
EOF
```

---

## Step 5: Docker Compose

```bash
cat > docker-compose.yml << 'EOF'
services:

  # ── PostgreSQL ──────────────────────────────────────────────────────────────
  postgres:
    image: postgres:16-alpine
    restart: unless-stopped
    environment:
      POSTGRES_USER: ${POSTGRES_USER}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
      POSTGRES_DB: ${POSTGRES_DB}
    volumes:
      - postgres_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER} -d ${POSTGRES_DB}"]
      interval: 10s
      timeout: 5s
      retries: 5

  # ── Valkey (Redis-compatible) ───────────────────────────────────────────────
  valkey:
    image: valkey/valkey:latest
    restart: unless-stopped
    command: valkey-server --requirepass ${VALKEY_PASSWORD} --save 60 1 --loglevel warning
    volumes:
      - valkey_data:/data
    healthcheck:
      test: ["CMD", "valkey-cli", "-a", "${VALKEY_PASSWORD}", "ping"]
      interval: 10s
      timeout: 5s
      retries: 5

  # ── LiteLLM Proxy ──────────────────────────────────────────────────────────
  litellm:
    image: ghcr.io/berriai/litellm-database:main-latest
    restart: unless-stopped
    ports:
      - "4000:4000"
    volumes:
      - ./config/litellm_config.yaml:/app/config.yaml:ro
      - ./secrets/gcp-credentials.json:/secrets/gcp-credentials.json:ro
    environment:
      LITELLM_MASTER_KEY: ${LITELLM_MASTER_KEY}
      LITELLM_SALT_KEY: ${LITELLM_SALT_KEY}
      GOOGLE_CLOUD_PROJECT: ${GOOGLE_CLOUD_PROJECT}
      VERTEX_LOCATION: ${VERTEX_LOCATION}
      VALKEY_PASSWORD: ${VALKEY_PASSWORD}
      CUSTOM_ENDPOINT_URL: ${CUSTOM_ENDPOINT_URL}
      CUSTOM_ENDPOINT_KEY: ${CUSTOM_ENDPOINT_KEY}
      POSTGRES_USER: ${POSTGRES_USER}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
      POSTGRES_DB: ${POSTGRES_DB}
      # Langfuse connection for callbacks
      LANGFUSE_PUBLIC_KEY: ${LANGFUSE_PUBLIC_KEY}
      LANGFUSE_SECRET_KEY: ${LANGFUSE_SECRET_KEY}
      LANGFUSE_HOST: http://langfuse-web:3000
    command: ["--config", "/app/config.yaml", "--port", "4000"]
    depends_on:
      postgres:
        condition: service_healthy
      valkey:
        condition: service_healthy
      langfuse-web:
        condition: service_started

  # ── Langfuse ────────────────────────────────────────────────────────────────
  # Langfuse uses its own Postgres instance (separate from LiteLLM's)
  langfuse-postgres:
    image: postgres:16-alpine
    restart: unless-stopped
    environment:
      POSTGRES_USER: langfuse
      POSTGRES_PASSWORD: ${LANGFUSE_SECRET_KEY}
      POSTGRES_DB: langfuse
    volumes:
      - langfuse_postgres_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U langfuse -d langfuse"]
      interval: 10s
      timeout: 5s
      retries: 5

  langfuse-web:
    image: langfuse/langfuse:latest
    restart: unless-stopped
    ports:
      - "3000:3000"
    environment:
      DATABASE_URL: "postgresql://langfuse:${LANGFUSE_SECRET_KEY}@langfuse-postgres:5432/langfuse"
      NEXTAUTH_URL: http://localhost:3000
      NEXTAUTH_SECRET: ${NEXTAUTH_SECRET}
      SALT: ${SALT}
      LANGFUSE_INIT_USER_EMAIL: admin@local.dev
      LANGFUSE_INIT_USER_PASSWORD: ${LANGFUSE_INIT_USER_PASSWORD}
      LANGFUSE_INIT_USER_NAME: Admin
      LANGFUSE_INIT_ORG_NAME: local
      LANGFUSE_INIT_PROJECT_NAME: litellm
      LANGFUSE_INIT_PROJECT_PUBLIC_KEY: ${LANGFUSE_PUBLIC_KEY}
      LANGFUSE_INIT_PROJECT_SECRET_KEY: ${LANGFUSE_SECRET_KEY}
      REDIS_CONNECTION_STRING: redis://:${VALKEY_PASSWORD}@valkey:6379
    depends_on:
      langfuse-postgres:
        condition: service_healthy
      valkey:
        condition: service_healthy

  # ── Open WebUI ──────────────────────────────────────────────────────────────
  open-webui:
    image: ghcr.io/open-webui/open-webui:main
    restart: unless-stopped
    ports:
      - "8080:8080"
    volumes:
      - open_webui_data:/app/backend/data
    environment:
      # Point Open WebUI at LiteLLM as its OpenAI-compatible backend
      OPENAI_API_BASE_URL: http://litellm:4000/v1
      OPENAI_API_KEY: ${LITELLM_MASTER_KEY}
      # Disable Ollama auto-detection since we're using LiteLLM
      ENABLE_OLLAMA_API: "false"
      WEBUI_SECRET_KEY: ${NEXTAUTH_SECRET}
    depends_on:
      - litellm

volumes:
  postgres_data:
  valkey_data:
  langfuse_postgres_data:
  open_webui_data:
EOF
```

---

## Step 6: Start the Stack

```bash
# Start everything
docker compose up -d

# Watch logs to confirm startup (wait ~60 seconds for first boot)
docker compose logs -f litellm
```

Wait until you see `LiteLLM Proxy: Application startup complete` in the logs.

---

## Step 7: Verify Each Service

**LiteLLM proxy health:**
```bash
curl http://localhost:4000/health
```

**Test a model call through LiteLLM:**
```bash
curl -s http://localhost:4000/chat/completions \
  -H "Authorization: Bearer sk-litellm-master-changeme" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gemini-2-5-flash",
    "messages": [{"role": "user", "content": "Say hello in one word."}]
  }' | python3 -m json.tool
```

**LiteLLM Admin UI:**
Open `http://localhost:4000/ui` and log in with your master key.

**Langfuse UI:**
Open `http://localhost:3000` and log in with `admin@local.dev` / `changeme-example`. After a successful LiteLLM call, a trace should appear under your project within a few seconds.

**Open WebUI:**
Open `http://localhost:8080`. Create your admin account on first login. Models from LiteLLM will appear in the model selector automatically.

---

## Step 8: Create a LiteLLM Virtual Key (Optional)

Virtual keys let you issue per-user or per-application keys with spend limits:

```bash
curl -s -X POST http://localhost:4000/key/generate \
  -H "Authorization: Bearer sk-litellm-master-changeme" \
  -H "Content-Type: application/json" \
  -d '{
    "key_alias": "opencode-key",
    "models": ["gemini-2-5-pro", "gemini-2-5-flash", "smart"],
    "max_budget": 10.0,
    "budget_duration": "30d"
  }' | python3 -m json.tool
```

The returned `key` value (starts with `sk-`) can be used in OpenCode instead of the master key.

---

## Step 9: Configure OpenCode

### Primary path: via LiteLLM proxy

```jsonc
// ~/.config/opencode/opencode.json
{
  "$schema": "https://opencode.ai/config.json",

  // Default model: routes through LiteLLM
  "model": "litellm/smart",

  "provider": {
    // ── LiteLLM as a custom OpenAI-compatible provider ───────────────────────
    "litellm": {
      "npm": "@ai-sdk/openai-compatible",
      "name": "LiteLLM (local proxy)",
      "options": {
        "baseURL": "http://localhost:4000/v1"
      },
      "models": {
        "smart":            { "name": "Smart (auto-route)" },
        "gemini-2-5-pro":   { "name": "Gemini 2.5 Pro (via LiteLLM)" },
        "gemini-2-5-flash": { "name": "Gemini 2.5 Flash (via LiteLLM)" },
        "llama-local":      { "name": "Llama 3.3 70B (local)" },
        "qwen-coder":       { "name": "Qwen 2.5 Coder 32B (local)" }
      }
    },

    // ── Fallback: Vertex AI directly (bypasses LiteLLM) ─────────────────────
    // Use /connect to set up credentials, or set env vars:
    //   GOOGLE_CLOUD_PROJECT=your-project-id
    //   VERTEX_LOCATION=us-central1
    //   GOOGLE_APPLICATION_CREDENTIALS=/path/to/gcp-credentials.json
    "google-vertex": {}
  },

  "agent": {
    "build": {
      "model": "litellm/smart"
    },
    "plan": {
      "model": "litellm/gemini-2-5-flash"
    },
    "explore": {
      "model": "litellm/gemini-2-5-flash"
    }
  }
}
```

Store the LiteLLM key in OpenCode's auth store by adding it to
`~/.local/share/opencode/auth.json`:

```json
{
  "litellm": {
    "type": "api",
    "key": "sk-litellm-master-changeme"
  }
}
```

Or pass it inline in the provider options (less secure):

```jsonc
"litellm": {
  "options": {
    "baseURL": "http://localhost:4000/v1",
    "apiKey": "sk-litellm-master-changeme"
  }
}
```

### Fallback path: direct Vertex AI

If LiteLLM is down, switch in-session with `/models` and select a `google-vertex`
model, or temporarily change `"model"` in `opencode.json` to
`"google-vertex/gemini-2.5-pro"`.

Configure Vertex AI credentials for direct use in OpenCode by setting environment
variables in your shell profile:

```bash
export GOOGLE_APPLICATION_CREDENTIALS="$HOME/ai-stack/secrets/gcp-credentials.json"
export GOOGLE_CLOUD_PROJECT="your-gcp-project-id"
export VERTEX_LOCATION="us-central1"
```

Or use `/connect` in the OpenCode TUI and select **Google Vertex AI**.

---

## Step 10: Updating the Stack

```bash
# Pull latest images and restart
docker compose pull
docker compose up -d
```

---

## Troubleshooting

| Symptom | Check |
|---|---|
| LiteLLM 500 on Vertex calls | Verify `gcp-credentials.json` is mounted and the service account has `Vertex AI User` role |
| Valkey auth errors | Confirm `VALKEY_PASSWORD` matches in `.env` and `litellm_config.yaml` |
| No traces in Langfuse | Check `LANGFUSE_PUBLIC_KEY`/`SECRET_KEY` match between LiteLLM env and Langfuse init vars; check `docker compose logs litellm` for callback errors |
| Open WebUI shows no models | Confirm LiteLLM is healthy (`curl localhost:4000/health`) and the `OPENAI_API_KEY` env matches `LITELLM_MASTER_KEY` |
| LiteLLM DB errors on startup | PostgreSQL may not be ready yet; run `docker compose restart litellm` after postgres is healthy |
| OpenCode can't reach LiteLLM | Use `http://localhost:4000` (not `http://litellm:4000`) — the `litellm` hostname only works inside Docker |

---

## Service URLs Summary

| Service | URL | Credentials |
|---|---|---|
| LiteLLM Proxy API | `http://localhost:4000` | Master key from `.env` |
| LiteLLM Admin UI | `http://localhost:4000/ui` | Master key from `.env` |
| Langfuse UI | `http://localhost:3000` | `admin@local.dev` / `changeme-example` |
| Open WebUI | `http://localhost:8080` | First account becomes admin |
| Valkey | `localhost:6379` | Password from `.env` |
| PostgreSQL (LiteLLM) | `localhost:5432` | Credentials from `.env` |
