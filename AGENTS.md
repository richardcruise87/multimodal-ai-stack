# AGENTS.md

## What this repo is

A self-hosted AI inference stack. The repo contains:
- `setup.py` — interactive Python script that generates the stack directory
- `docs/ai-stack-setup.md` — full manual setup guide with copy-pasteable config blocks
- `samples/` — reference `podman-compose.yml`, `config/litellm_config.yaml`, and OpenCode configs
- `tests/test_setup.py` — unit tests for pure functions in `setup.py`
- `pyproject.toml` — project metadata, ruff config, pytest config

The stack itself lives **outside this repo** in `~/ai-stack/` (or wherever the user chose).

---

## What lives where

| Path | What it is |
|---|---|
| `setup.py` | Interactive setup script — the real entrypoint |
| `docs/ai-stack-setup.md` | Full manual guide with all config templates as heredocs |
| `samples/podman-compose.yml` | Reference Compose file (copied into `~/ai-stack/` by setup) |
| `samples/config/litellm_config.yaml` | Reference LiteLLM config (copied by setup) |
| `samples/opencode.jsonc` | Reference OpenCode config (copy to `~/.config/opencode/opencode.jsonc`) |
| `samples/opencode-langfuse.json` | Reference Langfuse plugin credentials (copy to `~/.config/opencode/opencode-langfuse.json`, chmod 600) |
| `samples/claude-settings.json` | Reference Claude Code settings (copy to `~/.claude/settings.json`) |
| `tests/test_setup.py` | Unit tests for `setup.py` pure functions |
| `~/ai-stack/.env` | Generated secrets (passwords, keys) — never commit |
| `~/ai-stack/.endpoints.env` | User-managed GCP/Vertex + custom endpoint config — never commit; setup.py never overwrites it once created |
| `~/ai-stack/secrets/gcp-credentials.json` | GCP service account key — never commit |

---

## Developer commands

```bash
# Install dev dependencies
pip install -e ".[dev]"

# Run all tests
pytest

# Run a single test class or function
pytest tests/test_setup.py::TestBuildLitellmConfig
pytest tests/test_setup.py::TestWriteEnv::test_gcp_vars_written

# Lint (CI scope: setup.py and tests/ only — not docs/ or samples/)
ruff check setup.py tests/
ruff format --check setup.py tests/

# YAML lint (CI also runs this; config at .yamllint.yml)
yamllint -c .yamllint.yml samples/podman-compose.yml samples/config/litellm_config.yaml .github/workflows/ci.yml

# Format
ruff format .

# Run the interactive setup script
python setup.py
```

CI runs on every push/PR to `main`: three jobs — `lint-python` (ruff), `lint-yaml` (yamllint), `test` (pytest matrix: Python 3.8, 3.10, 3.12). No Makefile, no pre-commit hooks.

---

## Critical constraints

- **`LITELLM_SALT_KEY`** must be generated once and never changed after first use — rotating it corrupts the LiteLLM database. The setup script generates it automatically.
- **Never commit** `.env`, `.endpoints.env`, or `secrets/`. Setup adds all three to `.gitignore` in the stack directory.
- This stack uses **Podman Compose** (`podman compose`), not Docker Compose. The compose file uses `restart: always` (not `unless-stopped`) for rootless Podman compatibility. Local model URLs use `host.containers.internal`, not `host.docker.internal`.
- **`docs/ai-stack-setup.md` contains Docker-specific examples** (`host.docker.internal`, `unless-stopped`) — these are stale. Trust `samples/podman-compose.yml` and `setup.py` over prose docs.
- From the **host**, reach LiteLLM at `http://localhost:4000`. From inside the Podman network, use `http://litellm:4000`.

---

## Architecture

```
Open WebUI (port 8080) / OpenCode (host)
        │
        ▼  OpenAI-compatible API
  LiteLLM Proxy (port 4000)   [image: ghcr.io/berriai/litellm-database:main-latest]
  ├── Vertex AI — gemini-2-5-pro, gemini-2-5-flash
  ├── Vertex AI — claude-sonnet-4-6, claude-sonnet-4-5, claude-opus-4, claude-opus-4-5, claude-haiku-4-5
  ├── External vLLM endpoint — qwen3-14b (optional; QWEN3_API_BASE/KEY)
  └── Custom OpenAI-compatible endpoint — llama-local, qwen-coder (optional; CUSTOM_ENDPOINT_URL/KEY)
        │
        ├── Valkey (Redis-compatible) — response caching TTL 600s + rate-limit state; also used by Langfuse
        ├── postgres — LiteLLM spend tracking & virtual keys  [postgres:16-alpine]
        └── Langfuse (port 3000) — observability / trace logging  [langfuse/langfuse:2]
             └── langfuse-postgres — separate Postgres instance for Langfuse only
```

**Two independent PostgreSQL containers** — `postgres` (LiteLLM) and `langfuse-postgres` (Langfuse). Do not conflate them.

**Two independent optional endpoints:**
- Step 5 in setup = `QWEN3_API_BASE/KEY` — external vLLM serving Qwen3-14B
- Step 6 in setup = `CUSTOM_ENDPOINT_URL/KEY` — local Ollama or other OpenAI-compatible server

**Routing groups:**
- `smart` — tries Qwen3-14B first (if configured), then qwen2.5-coder:32b (if custom endpoint configured), then Gemini 2.5 Flash; final fallback to Gemini 2.5 Pro.
- `build` — tries Qwen3-14B first (`max_input_tokens: 40960` triggers context-window fallback to `claude-sonnet-4-6`). Designed for the OpenCode build agent.

**`context_window_fallbacks`** (separate from regular fallbacks): `qwen3-14b → claude-sonnet-4-6`, `build → claude-sonnet-4-6`, `smart → gemini-2-5-pro`.

**Gemini Flash model ID in config:** `vertex_ai/gemini-2.5-flash-preview-04-17` (preview suffix — not `gemini-2.5-flash`).

**Open WebUI** has `ENABLE_OLLAMA_API: "false"` — it routes exclusively through LiteLLM. `WEBUI_SECRET_KEY` reuses `${NEXTAUTH_SECRET}`.

**LiteLLM depends on** postgres (healthy), valkey (healthy), langfuse-web (started — not healthy). LiteLLM may start before Langfuse is fully ready; `podman compose restart litellm` is the fix.

---

## Stack commands (run from `~/ai-stack/`)

```bash
podman compose up -d
podman compose logs -f litellm          # wait for "Application startup complete"
curl localhost:4000/health/readiness    # unauthenticated; /health requires the master key
podman compose pull && podman compose up -d   # update images
podman compose restart litellm          # if LiteLLM fails because Postgres wasn't ready
```

---

## Service URLs

| Service | URL | Default credentials |
|---|---|---|
| LiteLLM API | `http://localhost:4000` | Master key from `.env` |
| LiteLLM Admin UI | `http://localhost:4000/ui` | Master key from `.env` |
| Langfuse | `http://localhost:3000` | `admin@local.dev` / password set during setup |
| Open WebUI | `http://localhost:8080` | First account created becomes admin |

---

## Editing rules

**`setup.py`** — all config generation lives here as pure functions. `tests/test_setup.py` covers most pure functions; `write_compose` (a verbatim file copy) is not tested. `main()` is not tested (requires interactive I/O). Tests load the module via `importlib` without executing `main()`.

**`docs/ai-stack-setup.md`** — contains complete, copy-pasteable heredoc blocks. Keep them complete — partial templates force readers to reconstruct context. Verify env var names stay consistent across: the `.env` block, `litellm_config.yaml`, `podman-compose.yml`, and any OpenCode config examples.

**`samples/`** — reference files that `setup.py` copies verbatim. Changes here must stay in sync with `build_litellm_config()` and `write_compose_file()` in `setup.py`.

**Ruff config:** line length 100, target `py38`. Rules: E, W, F, I, UP, B, C4, PTH. UP007 disabled (keeps `Optional[X]` for 3.8 compat). Tests ignore S101 (asserts allowed).

**`LITELLM_MASTER_KEY`:** if the user enters a key without `sk-` prefix, the setup script silently prepends it.

**`LANGFUSE_SECRET_KEY`** doubles as the langfuse-postgres password — one variable, two roles.

**Troubleshooting:** No traces in Langfuse → check `LANGFUSE_PUBLIC_KEY`/`SECRET_KEY` match between LiteLLM env and Langfuse init vars; check `podman compose logs litellm` for callback errors. Open WebUI shows no models → confirm `OPENAI_API_KEY` on `open-webui` container matches `LITELLM_MASTER_KEY`.

---

## OpenCode Langfuse observability

Two independent Langfuse integrations run simultaneously in the same Langfuse project:

| Integration | What it traces | Source |
|---|---|---|
| LiteLLM `success_callback: ["langfuse"]` | Per-completion cost, model, tokens, routing group | `litellm_config.yaml` |
| `@langfuse/opencode-observability-plugin` | Full session structure: turns, generations, tool calls, reasoning, compaction | OpenCode plugin |

The plugin is the richer source — it shows the full agentic loop. LiteLLM's callback is the cost source of truth.

**OpenCode config** (`~/.config/opencode/opencode.jsonc`): see `samples/opencode.jsonc` for the full reference config including all routing groups, agent assignments, and provider definitions.

**Plugin credentials** (`~/.config/opencode/opencode-langfuse.json`, chmod 600): see `samples/opencode-langfuse.json`. Fill in your keys from `~/ai-stack/.env` and set `baseUrl` to the **self-hosted** instance (`http://localhost:3000`), not `cloud.langfuse.com`.

The plugin is installed automatically by OpenCode via Bun at startup. No manual `npm install` is needed.

**Cost tracking note:** LiteLLM's pricing DB has no entries for `vertex_ai/gemini-2.5-flash-preview-04-17`, `vertex_ai/gemini-2.5-pro` (direct key), or `openai/Qwen/Qwen3-14B`. Explicit `input_cost_per_token`/`output_cost_per_token` overrides are set on every affected `litellm_params` block in `litellm_config.yaml` to prevent `$0` cost in Langfuse.
