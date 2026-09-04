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

## Step 3: Environment Files

Create `.env` with generated secrets. Replace every placeholder with real values:

```bash
cat > .env << 'EOF'
# ── LiteLLM ──────────────────────────────────────────────────────────────────
LITELLM_MASTER_KEY=sk-litellm-master-changeme
# Salt key: generate once, never change after first use
# Generate with: openssl rand -hex 32
LITELLM_SALT_KEY=<your-salt-key-here>

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
EOF
```

Create `.endpoints.env` with your GCP/Vertex project and any optional custom
endpoints. This file is user-managed — the setup script never overwrites it
once it exists, so you can freely edit endpoint URLs/keys later without
losing changes on the next upgrade:

```bash
cat > .endpoints.env << 'EOF'
# ── GCP / Vertex AI ───────────────────────────────────────────────────────────
GOOGLE_CLOUD_PROJECT=<your-gcp-project-id>
VERTEX_LOCATION=<your-gcp-region>

# ── Custom OpenAI-compatible endpoint (e.g. Ollama) ──────────────────────────
# Leave blank if not using
CUSTOM_ENDPOINT_URL=http://host.containers.internal:11434/v1
CUSTOM_ENDPOINT_KEY=unused

# ── Qwen3-14B (custom external endpoint) ─────────────────────────────────────
QWEN3_API_BASE=<your-qwen3-endpoint-here>
QWEN3_API_KEY=<your-bearer-token-here>
EOF
```

> **Security:** Add both `.env` and `.endpoints.env` to `.gitignore`. Never commit either.

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

  # ── Anthropic Claude models (via Vertex AI) ────────────────────────────────
  - model_name: claude-sonnet-4-6
    litellm_params:
      model: vertex_ai/claude-sonnet-4-6
      vertex_project: os.environ/GOOGLE_CLOUD_PROJECT
      vertex_location: os.environ/VERTEX_LOCATION
      vertex_credentials: /secrets/gcp-credentials.json

  - model_name: claude-sonnet-4-5
    litellm_params:
      model: vertex_ai/claude-sonnet-4-5
      vertex_project: os.environ/GOOGLE_CLOUD_PROJECT
      vertex_location: os.environ/VERTEX_LOCATION
      vertex_credentials: /secrets/gcp-credentials.json

  - model_name: claude-opus-4
    litellm_params:
      model: vertex_ai/claude-opus-4
      vertex_project: os.environ/GOOGLE_CLOUD_PROJECT
      vertex_location: os.environ/VERTEX_LOCATION
      vertex_credentials: /secrets/gcp-credentials.json

  - model_name: claude-opus-4-5
    litellm_params:
      model: vertex_ai/claude-opus-4-5
      vertex_project: os.environ/GOOGLE_CLOUD_PROJECT
      vertex_location: os.environ/VERTEX_LOCATION
      vertex_credentials: /secrets/gcp-credentials.json

  - model_name: claude-haiku-4-5
    litellm_params:
      model: vertex_ai/claude-haiku-4-5
      vertex_project: os.environ/GOOGLE_CLOUD_PROJECT
      vertex_location: os.environ/VERTEX_LOCATION
      vertex_credentials: /secrets/gcp-credentials.json

  # ── Qwen3-14B (Custom external endpoint, OpenAI-compatible / vLLM) ─────────
  # max_input_tokens reflects the actual deployed limit (original_max_position_embeddings).
  # Requests exceeding this will be routed to the fallback before being sent.
  - model_name: qwen3-14b
    max_input_tokens: 40960
    litellm_params:
      model: openai/Qwen/Qwen3-14B
      api_base: os.environ/QWEN3_API_BASE
      api_key: os.environ/QWEN3_API_KEY

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

  # ── Routing group: "build" ─────────────────────────────────────────────────
  # Used by the OpenCode build agent: tries Qwen3-14B first (free), falls back
  # to Claude Sonnet 4.6 via router_settings.fallbacks.
  - model_name: build
    max_input_tokens: 40960
    litellm_params:
      model: openai/Qwen/Qwen3-14B
      api_base: os.environ/QWEN3_API_BASE
      api_key: os.environ/QWEN3_API_KEY

  - model_name: build
    litellm_params:
      model: vertex_ai/claude-sonnet-4-6
      vertex_project: os.environ/GOOGLE_CLOUD_PROJECT
      vertex_location: os.environ/VERTEX_LOCATION
      vertex_credentials: /secrets/gcp-credentials.json

  # ── Routing group: "smart" ─────────────────────────────────────────────────
  # Cost-based routing: qwen3-14b first (free), then local Ollama, then Gemini Flash.
  - model_name: smart
    max_input_tokens: 40960
    litellm_params:
      model: openai/Qwen/Qwen3-14B
      api_base: os.environ/QWEN3_API_BASE
      api_key: os.environ/QWEN3_API_KEY

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
    - {"build": ["claude-sonnet-4-6"]}
  context_window_fallbacks:
    - {"qwen3-14b": ["claude-sonnet-4-6"]}
    - {"build": ["claude-sonnet-4-6"]}
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
  # database_url is passed via DATABASE_URL environment variable in compose

# =============================================================================
# Caching (using Valkey)
# =============================================================================
litellm_settings:
  ssl_verify: false   # required for internal endpoints with self-signed certs
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
    env_file:
      # User-managed: GOOGLE_CLOUD_PROJECT, VERTEX_LOCATION, CUSTOM_ENDPOINT_URL/KEY,
      # QWEN3_API_BASE/KEY. Not overwritten by setup.py on re-runs.
      - .endpoints.env
    environment:
      LITELLM_MASTER_KEY: ${LITELLM_MASTER_KEY}
      LITELLM_SALT_KEY: ${LITELLM_SALT_KEY}
      VALKEY_PASSWORD: ${VALKEY_PASSWORD}
      POSTGRES_USER: ${POSTGRES_USER}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
      POSTGRES_DB: ${POSTGRES_DB}
      DATABASE_URL: "postgresql://${POSTGRES_USER}:${POSTGRES_PASSWORD}@postgres:5432/${POSTGRES_DB}"
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
    image: langfuse/langfuse:2
    restart: unless-stopped
    ports:
      - "3000:3000"
    environment:
      DATABASE_URL: "postgresql://langfuse:${LANGFUSE_SECRET_KEY}@langfuse-postgres:5432/langfuse"
      NEXTAUTH_URL: http://localhost:3000
      NEXTAUTH_SECRET: ${NEXTAUTH_SECRET}
      SALT: ${SALT}
      LANGFUSE_INIT_ORG_ID: local-org
      LANGFUSE_INIT_ORG_NAME: local
      LANGFUSE_INIT_PROJECT_ID: litellm-project
      LANGFUSE_INIT_PROJECT_NAME: litellm
      LANGFUSE_INIT_PROJECT_PUBLIC_KEY: ${LANGFUSE_PUBLIC_KEY}
      LANGFUSE_INIT_PROJECT_SECRET_KEY: ${LANGFUSE_SECRET_KEY}
      LANGFUSE_INIT_USER_EMAIL: admin@local.dev
      LANGFUSE_INIT_USER_PASSWORD: ${LANGFUSE_INIT_USER_PASSWORD}
      LANGFUSE_INIT_USER_NAME: Admin
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
Open `http://localhost:3000` and log in with `admin@local.dev` / `<your-langfuse-admin-password>`. After a successful LiteLLM call, a trace should appear under your project within a few seconds.

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
    //   GOOGLE_CLOUD_PROJECT=<your-project-id>
    //   VERTEX_LOCATION=<your-gcp-region>
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
export GOOGLE_CLOUD_PROJECT=<your-gcp-project-id>
export VERTEX_LOCATION=<your-gcp-region>
```

Or use `/connect` in the OpenCode TUI and select **Google Vertex AI**.

---

## Step 10: Headroom Token Compression (Optional)

[Headroom](https://headroom-docs.vercel.app/docs) is a local token compression service that reduces input token costs by 15–95% depending on content type (code, JSON, logs, prose). It runs as a sidecar container alongside LiteLLM and is registered as a `pre_call` guardrail — LiteLLM compresses each request before forwarding it to the upstream provider.

### Architecture

```
Client (Open WebUI / OpenCode)
    │
    ▼  OpenAI-compatible API
LiteLLM Proxy (port 4000)
    │  pre_call guardrail
    ▼
Headroom (port 8787) — compresses messages
    │  returns compressed messages
    ▼
LLM Provider (Vertex AI / vLLM / Ollama)
```

### Add the Headroom service to `podman-compose.yml`

```yaml
  # ── Headroom (token compression sidecar) ──────────────────────────────
  headroom:
    image: ghcr.io/chopratejas/headroom:latest
    restart: always
    ports:
      - "8787:8787"
    environment:
      HEADROOM_TELEMETRY: "off"
    command: ["headroom", "proxy", "--host", "0.0.0.0", "--port", "8787"]
    volumes:
      - headroom_cache:/app/.headroom
    healthcheck:
      test: ["CMD-SHELL", "curl -sf http://localhost:8787/health || exit 1"]
      interval: 10s
      timeout: 5s
      retries: 5
```

Also add `headroom_cache:` to the top-level `volumes:` block.

### Add the guardrail and compressed routing groups to `litellm_config.yaml`

Add the `guardrails` block (before `general_settings`):

```yaml
guardrails:
  - guardrail_name: headroom-compression
    litellm_params:
      guardrail: headroom
      mode: pre_call
      api_base: http://headroom:8787
      default_on: false  # opt-in; set true to compress every request
```

Add compressed routing group entries (after the existing `build` / `smart` blocks):

```yaml
  # ── Routing group: "build-compressed" ─────────────────────────────────────
  - model_name: build-compressed
    max_input_tokens: 40960
    litellm_params:
      model: openai/Qwen/Qwen3-14B
      api_base: os.environ/QWEN3_API_BASE
      api_key: os.environ/QWEN3_API_KEY

  - model_name: build-compressed
    litellm_params:
      model: vertex_ai/claude-sonnet-4-6
      vertex_project: os.environ/GOOGLE_CLOUD_PROJECT
      vertex_location: os.environ/VERTEX_LOCATION
      vertex_credentials: /secrets/gcp-credentials.json

  # ── Routing group: "smart-compressed" ─────────────────────────────────────
  - model_name: smart-compressed
    max_input_tokens: 40960
    litellm_params:
      model: openai/Qwen/Qwen3-14B
      api_base: os.environ/QWEN3_API_BASE
      api_key: os.environ/QWEN3_API_KEY

  - model_name: smart-compressed
    litellm_params:
      model: vertex_ai/gemini-2.5-flash-preview-04-17
      vertex_project: os.environ/GOOGLE_CLOUD_PROJECT
      vertex_location: os.environ/VERTEX_LOCATION
      vertex_credentials: /secrets/gcp-credentials.json
```

Add fallbacks for the compressed groups in `router_settings`:

```yaml
router_settings:
  fallbacks:
    - {"smart": ["gemini-2-5-pro"]}
    - {"build": ["claude-sonnet-4-6"]}
    - {"smart-compressed": ["gemini-2-5-pro"]}
    - {"build-compressed": ["claude-sonnet-4-6"]}
  context_window_fallbacks:
    - {"qwen3-14b": ["claude-sonnet-4-6"]}
    - {"build": ["claude-sonnet-4-6"]}
    - {"build-compressed": ["claude-sonnet-4-6"]}
    - {"smart": ["gemini-2-5-pro"]}
    - {"smart-compressed": ["gemini-2-5-pro"]}
```

### Verify Headroom is running

```bash
curl http://localhost:8787/health
```

### Using compression

**Option A — select a compressed routing group:**

```bash
curl http://localhost:4000/v1/chat/completions \
  -H "Authorization: Bearer $LITELLM_MASTER_KEY" \
  -H "Content-Type: application/json" \
  -d '{"model": "build-compressed", "messages": [{"role": "user", "content": "..."}]}'
```

**Option B — opt in per request (any model):**

```bash
  -d '{"model": "claude-sonnet-4-6", "guardrails": ["headroom-compression"], "messages": [...]}'
```

**Option C — issue a virtual key with compression always on:**

```bash
curl -X POST http://localhost:4000/key/generate \
  -H "Authorization: Bearer $LITELLM_MASTER_KEY" \
  -H "Content-Type: application/json" \
  -d '{"key_alias": "my-compressed-key", "guardrails": ["headroom-compression"]}'
```

**Option D — configure OpenCode to use the compressed build group:**

```json
{
  "model": {
    "modelId": "build-compressed",
    "provider": {
      "name": "openai",
      "apiUrl": "http://localhost:4000/v1",
      "apiKey": "<your-litellm-key>"
    }
  }
}
```

### Notes

- Headroom defaults to **not compressing** `user`/`system` messages unless `HEADROOM_COMPRESS_USER_MESSAGES=1` is set on the Headroom container — most coding-agent traffic is in user messages, so set this if you want compression to apply.
- Compression adds ~100–200 ms latency (local, CPU-bound); subsequent turns on the same session reuse the cache.
- The CCR (Compressed Content Retrieval) cache is persisted in the `headroom_cache` volume so the LLM can retrieve original content across container restarts.
- LiteLLM requires **v1.92.x or later** for the Headroom guardrail integration.
- To verify compression ran on a request, check the `x-litellm-applied-guardrails: headroom-compression` response header or inspect **Logs → Guardrails & Policy Compliance** in the LiteLLM Admin UI.

---

## Step 11: Upgrading an Existing Installation

If you already have the stack deployed and want to add new features (Headroom, new endpoints) or update your configuration, run `setup.py` again from the repo root:

```bash
cd ~/multimodal-ai-stack
python setup.py
```

When the script detects an existing `.env`, it will offer three options:

### Upgrade Modes

**[m] Merge — RECOMMENDED**

Preserves all existing secrets and passwords while updating configuration files from the latest templates. Use this when you want to:

- Enable Headroom token compression on an existing stack
- Update `podman-compose.yml` or `litellm_config.yaml` to the latest version

To add a new model endpoint (Qwen3, Ollama) or change your GCP project/region,
edit `.endpoints.env` directly — the setup script never touches this file once
it exists, so your changes always take effect on the next `podman compose up -d`
without needing to re-run setup.

What merge keeps:

| Secret | Why it must be preserved |
|---|---|
| `LITELLM_SALT_KEY` | Database encryption key — changing it **corrupts the LiteLLM database** |
| `POSTGRES_PASSWORD` | If changed, the existing `postgres_data` volume becomes inaccessible |
| `LANGFUSE_SECRET_KEY` | Doubles as the `langfuse-postgres` password — changing locks out all trace history |
| `LITELLM_MASTER_KEY` | Changing invalidates all existing API clients and virtual keys |
| `LANGFUSE_PUBLIC_KEY` | Changing breaks the LiteLLM → Langfuse trace callback |
| `NEXTAUTH_SECRET` | Changing invalidates all Langfuse and Open WebUI sessions |
| `SALT` | Changing breaks Langfuse password verification |
| `VALKEY_PASSWORD` | Changing makes the existing cache/rate-limit volume inaccessible |

**[o] Overwrite — ⚠️ DATA LOSS**

Regenerates all secrets from scratch. You will be asked to type `Yes` exactly, twice, before this proceeds. Only use this for a complete fresh start — all existing data in the persistent volumes becomes inaccessible.

**[a] Abort**

Exits immediately without making any changes.

---

### Backups

After confirming the write, the script prompts:

```
The following files will be overwritten:
  • .env
  • podman-compose.yml
  • config/litellm_config.yaml

Create numbered backups of existing files? [Y/n]:
```

Note: `.endpoints.env` is never listed here and never overwritten — it's
user-managed. If it already exists, setup skips it and prints a warning
instead.

Backups use incremental `.bak.N` suffixes and preserve directory structure:

```
~/ai-stack/
  .env
  .env.bak.1          ← first backup
  .env.bak.2          ← second backup
  podman-compose.yml
  podman-compose.yml.bak.1
  config/
    litellm_config.yaml
    litellm_config.yaml.bak.1
```

The names of all backup files created are printed immediately and again in the final summary.

**To restore a backup manually:**

```bash
cd ~/ai-stack
cp .env.bak.1 .env
cp podman-compose.yml.bak.1 podman-compose.yml
cp config/litellm_config.yaml.bak.1 config/litellm_config.yaml
```

**To clean up old backups:**

```bash
cd ~/ai-stack
rm -f .env.bak.* podman-compose.yml.bak.* config/litellm_config.yaml.bak.*
```

---

### After Upgrading

```bash
cd ~/ai-stack
podman compose pull      # pull any new images (e.g. headroom)
podman compose up -d     # restart with updated config
```

If you added Headroom, verify it started:

```bash
curl http://localhost:8787/health
podman compose logs headroom
```

If LiteLLM fails to start (Postgres not yet ready):

```bash
podman compose restart litellm
```

---

## Step 12: Updating Images

```bash
# Pull latest images and restart
podman compose pull
podman compose up -d
```

---

## Troubleshooting

| Symptom | Check |
|---|---|
| `401` on `curl localhost:4000/health` | `/health` always requires auth — use `curl localhost:4000/health/readiness` (no key needed) or pass `-H "Authorization: Bearer $LITELLM_MASTER_KEY"` |
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
| Langfuse UI | `http://localhost:3000` | `admin@local.dev` / `<your-langfuse-admin-password>` |
| Open WebUI | `http://localhost:8080` | First account becomes admin |
| Headroom (optional) | `http://localhost:8787` | No auth by default |
| Valkey | `localhost:6379` | Password from `.env` |
| PostgreSQL (LiteLLM) | `localhost:5432` | Credentials from `.env` |
