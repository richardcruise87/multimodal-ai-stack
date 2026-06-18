# AGENTS.md

## What this repo is

Documentation-only. No source code, build system, tests, CI, or package manager.
The single substantive file is `docs/ai-stack-setup.md` — a complete setup guide
for a local Docker Compose AI stack. It is not yet committed to git (only `LICENSE`
and `README.md` are in git history).

Do not go looking for `package.json`, `Makefile`, `pyproject.toml`, test suites,
or CI workflows. They do not exist.

---

## What lives where

| Location | What it is |
|---|---|
| `docs/ai-stack-setup.md` | The only doc; contains all config templates as heredocs |
| `~/ai-stack/` | Where the user creates the actual stack (outside this repo) |
| `~/ai-stack/.env` | All secrets — never commit |
| `~/ai-stack/secrets/gcp-credentials.json` | GCP service account key — never commit |
| `~/ai-stack/config/litellm_config.yaml` | LiteLLM proxy config |
| `~/ai-stack/docker-compose.yml` | Compose file defining all services |
| `~/.config/opencode/opencode.json` | OpenCode config — outside this repo |
| `~/.local/share/opencode/auth.json` | OpenCode API key store — outside this repo |

---

## Critical constraints

- **`LITELLM_SALT_KEY`** must be generated once (`openssl rand -hex 32`) and never
  changed after first use. Rotating it corrupts the LiteLLM database.
- **Never commit** `.env` or `secrets/gcp-credentials.json`. The doc says to add
  `.env` to `.gitignore`.
- Use **`docker compose`** (Compose v2), not `docker-compose`.
- From the **host**, reach LiteLLM at `http://localhost:4000`. From inside the Docker
  network, use `http://litellm:4000`. OpenCode runs on the host, so it uses `localhost`.

---

## Architecture notes

```
OpenCode / Open WebUI (host port 8080)
        │
        ▼ OpenAI-compatible API
  LiteLLM Proxy (host port 4000)
  ├── Vertex AI — gemini-2-5-pro, gemini-2-5-flash
  └── Custom OpenAI-compatible endpoint — llama-local, qwen-coder
        │
        ├── Valkey (Redis-compatible) — caching (TTL 600s) + rate-limit state
        ├── postgres — LiteLLM spend tracking & virtual keys
        └── Langfuse (host port 3000) — observability / trace logging
             └── langfuse-postgres — separate Postgres instance for Langfuse only
```

**Two PostgreSQL containers** — `postgres` (LiteLLM) and `langfuse-postgres` (Langfuse).
They are independent; do not conflate them.

**`smart` model routing** — cost-based, tries local Qwen 2.5 Coder 32B first, falls back
to Gemini 2.5 Flash, with a final router fallback to Gemini 2.5 Pro.

**OpenCode fallback** — `google-vertex` provider is configured as a direct Vertex AI
fallback that bypasses LiteLLM entirely. Switch with `/models` in the TUI or change
`"model"` in `opencode.json`.

---

## Key commands (run from `~/ai-stack/`)

```bash
# Start the stack
docker compose up -d

# Watch LiteLLM startup (wait for "Application startup complete")
docker compose logs -f litellm

# Health check
curl http://localhost:4000/health

# Update all images
docker compose pull && docker compose up -d

# LiteLLM fails to start because Postgres wasn't ready yet
docker compose restart litellm
```

---

## Service URLs

| Service | URL | Default credentials |
|---|---|---|
| LiteLLM API | `http://localhost:4000` | Master key from `.env` |
| LiteLLM Admin UI | `http://localhost:4000/ui` | Master key from `.env` |
| Langfuse UI | `http://localhost:3000` | `admin@local.dev` / `<your-langfuse-admin-password>` |
| Open WebUI | `http://localhost:8080` | First account becomes admin |

---

## If you edit `docs/ai-stack-setup.md`

The file contains complete, copy-pasteable heredoc blocks. Keep them that way —
partial templates require the user to reconstruct context across multiple reads.
Verify that env var names are consistent between the `.env` block (Step 3),
`litellm_config.yaml` (Step 4), `docker-compose.yml` (Step 5), and the OpenCode
config (Step 9).
