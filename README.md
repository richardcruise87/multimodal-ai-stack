# multimodal-ai-stack

A self-hosted AI inference stack running entirely via Podman Compose. Routes
prompts through a [LiteLLM](https://github.com/BerriAI/litellm) proxy to
Google Vertex AI (Gemini models) and optionally to local models via Ollama or
any OpenAI-compatible endpoint.

## What's in the stack

```
OpenCode / Open WebUI  (browser chat UI, port 8080)
        │
        ▼  OpenAI-compatible API
  LiteLLM Proxy  (port 4000)
  ├── Vertex AI — gemini-2-5-pro, gemini-2-5-flash
  └── Local endpoint — llama-local, qwen-coder  (optional)
        │
        ├── Valkey  — response caching + rate-limit state
        ├── PostgreSQL  — LiteLLM spend tracking & virtual keys
        └── Langfuse  (port 3000) — observability & trace logging
             └── (separate PostgreSQL instance for Langfuse)
```

The `smart` model uses cost-based routing: tries a local model first (if
configured), falls back to Gemini Flash, then Gemini Pro.

## Repository layout

```
docs/ai-stack-setup.md          Full setup guide (start here for manual setup)
samples/
  setup.py                      Interactive setup script
  podman-compose.yml            Podman Compose service definitions
  config/litellm_config.yaml    Reference LiteLLM proxy configuration
```

## Quick start

### Prerequisites

- Python 3.8+
- [Podman](https://podman.io/) with Podman Compose (`podman compose` or `podman-compose`)
- A GCP project with the Vertex AI API enabled and a service account JSON key
  with the **Vertex AI User** role
- Optional: [Ollama](https://ollama.com/) or another local model server

### 1. Run the setup script

```bash
python samples/setup.py
```

The script will walk you through:

- Choosing an output directory (default: `~/ai-stack/`)
- Providing your GCP service account credentials (symlink or copy)
- Entering your GCP project ID and region
- Optionally configuring a local model endpoint (Ollama, etc.)
- Generating all secrets and passwords

It writes the following into your stack directory:

| File | Purpose |
|---|---|
| `.env` | All secrets — **never commit this** |
| `podman-compose.yml` | Podman Compose service definitions |
| `config/litellm_config.yaml` | LiteLLM proxy configuration |
| `secrets/gcp-credentials.json` | Symlink or copy of your GCP key |
| `.gitignore` | Protects `.env` and `secrets/` from accidental commits |

At the end, the script prints all generated secrets and your next steps.

### 2. Start the stack

```bash
cd ~/ai-stack   # or whichever directory you chose
podman compose up -d

# Watch LiteLLM start up (wait for "Application startup complete")
podman compose logs -f litellm
```

### 3. Verify

```bash
curl http://localhost:4000/health
```

## Service URLs

| Service | URL | Default credentials |
|---|---|---|
| LiteLLM API | `http://localhost:4000` | Master key from `.env` |
| LiteLLM Admin UI | `http://localhost:4000/ui` | Master key from `.env` |
| Langfuse | `http://localhost:3000` | `admin@local.dev` / password set during setup |
| Open WebUI | `http://localhost:8080` | First account created becomes admin |

## Updating

```bash
cd ~/ai-stack
podman compose pull && podman compose up -d
```

## Manual setup

See [`docs/ai-stack-setup.md`](docs/ai-stack-setup.md) for a full step-by-step
guide with all configuration templates.

## Important notes

- **`LITELLM_SALT_KEY`** is generated once by the setup script and must never
  be changed after first use — rotating it corrupts the LiteLLM database.
- **Never commit `.env` or `secrets/`** — the setup script adds both to
  `.gitignore` in your stack directory automatically.
- From the host, reach LiteLLM at `http://localhost:4000`. From inside the
  Podman network, use `http://litellm:4000`.
