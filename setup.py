#!/usr/bin/env python3
"""
setup.py — Interactive setup script for the LiteLLM AI stack.

Run from the repository root:
    python setup.py

Creates a stack directory (default: ~/ai-stack/) containing:
    .env                        — all secrets and config
    podman-compose.yml          — Podman Compose service definitions
    config/litellm_config.yaml  — LiteLLM proxy configuration
    secrets/                    — GCP credentials (symlink or copy)
    .gitignore                  — ensures secrets are never committed
"""

import secrets
import shutil
import sys
import textwrap
from pathlib import Path

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

BOLD = "\033[1m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
RED = "\033[31m"
CYAN = "\033[36m"
RESET = "\033[0m"


def bold(s):
    return f"{BOLD}{s}{RESET}"


def green(s):
    return f"{GREEN}{s}{RESET}"


def yellow(s):
    return f"{YELLOW}{s}{RESET}"


def red(s):
    return f"{RED}{s}{RESET}"


def cyan(s):
    return f"{CYAN}{s}{RESET}"


def hr(char="─", width=70):
    print(char * width)


def section(title):
    print()
    hr()
    print(bold(f"  {title}"))
    hr()


def prompt(message, default=None, secret=False):
    """Prompt the user for input, with an optional default value."""
    if default is not None:
        display_default = "****" if secret and default else default
        prompt_str = f"  {message} [{cyan(display_default)}]: "
    else:
        prompt_str = f"  {message}: "

    try:
        value = input(prompt_str).strip()
    except (KeyboardInterrupt, EOFError):
        print()
        print(red("\nAborted."))
        sys.exit(1)

    return value if value else (default or "")


def prompt_choice(message, choices):
    """
    Prompt the user to choose from a list of (key, description) tuples.
    Returns the chosen key (lowercased).
    choices: list of (key_char, description) e.g. [('s', 'Symlink'), ...]
    """
    options = "  " + " / ".join(f"[{bold(k)}] {desc}" for k, desc in choices)
    default_key = choices[0][0]
    print(f"  {message}")
    print(options)
    try:
        value = input(f"  Choice [{cyan(default_key)}]: ").strip().lower()
    except (KeyboardInterrupt, EOFError):
        print()
        print(red("\nAborted."))
        sys.exit(1)
    return value if value in [k for k, _ in choices] else default_key


def prompt_yes_no(message, default=True):
    """Prompt for yes/no. Returns bool."""
    hint = "[Y/n]" if default else "[y/N]"
    try:
        value = input(f"  {message} {cyan(hint)}: ").strip().lower()
    except (KeyboardInterrupt, EOFError):
        print()
        print(red("\nAborted."))
        sys.exit(1)
    if not value:
        return default
    return value.startswith("y")


def gen_password():
    """Generate a random URL-safe password (32 chars)."""
    return secrets.token_urlsafe(24)


def gen_hex(n=32):
    """Generate n random hex characters."""
    return secrets.token_hex(n // 2)


def gen_master_key():
    """Generate a random LiteLLM master key."""
    return "sk-" + secrets.token_hex(16)


def gen_langfuse_public_key():
    """Generate a Langfuse-style public key."""
    return "lf-pk-" + secrets.token_hex(16)


# ---------------------------------------------------------------------------
# Repo root (used to locate sample files in samples/)
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parent
SAMPLE_COMPOSE = REPO_ROOT / "samples" / "podman-compose.yml"


# ---------------------------------------------------------------------------
# Banner
# ---------------------------------------------------------------------------


def print_banner():
    print()
    hr("═")
    print(bold("  LiteLLM AI Stack — Interactive Setup"))
    hr("═")
    print(
        textwrap.dedent("""\

      This script will create a stack directory containing:

        • .env                        (all secrets — never commit this)
        • podman-compose.yml          (Podman Compose service definitions)
        • config/litellm_config.yaml  (LiteLLM proxy configuration)
        • secrets/                    (GCP credentials)
        • .gitignore                  (protects secrets from accidental commits)

      Press Ctrl-C at any time to abort without writing any files.
    """)
    )


# ---------------------------------------------------------------------------
# Step 1 — Output directory
# ---------------------------------------------------------------------------


def get_output_dir():
    section("Step 1 of 7 — Output directory")
    default = str(Path.home() / "ai-stack")
    raw = prompt("Stack directory", default=default)
    out = Path(raw).expanduser().resolve()
    print(f"\n  Will create: {cyan(str(out))}")
    return out


# ---------------------------------------------------------------------------
# Step 2 — Existing .env check
# ---------------------------------------------------------------------------


def check_existing_env(out_dir):
    env_path = out_dir / ".env"
    if not env_path.exists():
        return True  # nothing to worry about

    section("Step 2 of 7 — Existing .env detected")
    print(yellow(f"  Found existing .env at: {env_path}"))
    print()
    choice = prompt_choice(
        "What would you like to do?",
        [
            ("o", "Overwrite — generate a fresh .env (existing secrets will be lost)"),
            ("k", "Keep — abort setup and leave the existing .env untouched"),
        ],
    )
    if choice == "k":
        print()
        print(yellow("  Keeping existing .env. Aborting setup."))
        sys.exit(0)
    print()
    print(yellow("  Will overwrite existing .env."))
    return True


# ---------------------------------------------------------------------------
# Step 3 — GCP credentials
# ---------------------------------------------------------------------------


def setup_gcp_credentials(out_dir):
    section("Step 3 of 7 — GCP credentials")
    secrets_dir = out_dir / "secrets"
    dest = secrets_dir / "gcp-credentials.json"

    print(
        textwrap.dedent("""\
      LiteLLM needs a GCP service account JSON key to call Vertex AI models.
      The key must have the "Vertex AI User" role on your GCP project.

      Options:
        [s] Symlink  — create a symlink pointing to your existing file (default)
        [c] Copy     — copy the file into the stack directory
        [k] Skip     — skip this step (you can add it manually later)
    """)
    )

    choice = prompt_choice(
        "How would you like to provide the credentials file?",
        [
            ("s", "Symlink (default)"),
            ("c", "Copy"),
            ("k", "Skip"),
        ],
    )

    if choice == "k":
        print()
        print(yellow("  Skipping GCP credentials. Remember to add:"))
        print(yellow(f"    {dest}"))
        print(yellow("  before starting the stack."))
        return False

    while True:
        src_raw = prompt("Path to your service account JSON file")
        if not src_raw:
            print(red("  Path cannot be empty. Try again, or press Ctrl-C to abort."))
            continue
        src = Path(src_raw).expanduser().resolve()
        if not src.exists():
            print(red(f"  File not found: {src}"))
            continue
        if not src.is_file():
            print(red(f"  Not a file: {src}"))
            continue
        # Minimal JSON sanity check
        try:
            import json

            with src.open() as f:
                data = json.load(f)
            if "type" not in data:
                print(
                    yellow(
                        "  Warning: file does not look like a GCP service account key (missing 'type' field)."
                    )
                )
                if not prompt_yes_no("  Continue anyway?", default=False):
                    continue
        except Exception as e:
            print(yellow(f"  Warning: could not parse file as JSON: {e}"))
            if not prompt_yes_no("  Continue anyway?", default=False):
                continue
        break

    # We'll write the file during the write phase; store the action for later
    return {"action": choice, "src": src, "dest": dest}


# ---------------------------------------------------------------------------
# Step 4 — GCP project config
# ---------------------------------------------------------------------------


def get_gcp_config():
    section("Step 4 of 7 — GCP / Vertex AI project")
    project = prompt("GOOGLE_CLOUD_PROJECT (your GCP project ID)")
    while not project:
        print(red("  Project ID cannot be empty."))
        project = prompt("GOOGLE_CLOUD_PROJECT")

    location = prompt("VERTEX_LOCATION", default="us-central1")
    return project, location


# ---------------------------------------------------------------------------
# Step 5 — Custom endpoint (Ollama / local models)
# ---------------------------------------------------------------------------


def get_custom_endpoint():
    section("Step 5 of 7 — Local model endpoint (Ollama / custom)")
    print(
        textwrap.dedent("""\
      If you have a local model server (e.g. Ollama), LiteLLM can route
      requests to it. The 'smart' routing group will try the local model
      first before falling back to Gemini Flash and then Gemini Pro.

      If you skip this, 'smart' will route directly to Gemini Flash → Pro.
    """)
    )

    use_custom = prompt_yes_no("Do you have a local model endpoint to configure?", default=False)
    if not use_custom:
        return None

    default_url = "http://host.containers.internal:11434/v1"
    url = prompt("Endpoint URL", default=default_url)
    key = prompt("API key (use 'unused' for Ollama with no auth)", default="unused")
    return {"url": url, "key": key}


# ---------------------------------------------------------------------------
# Step 6 — Secret generation
# ---------------------------------------------------------------------------


def generate_secrets(custom_endpoint):
    section("Step 6 of 7 — Secrets")
    print(
        textwrap.dedent("""\
      Generating random values for all secrets.
      For LITELLM_MASTER_KEY and the Langfuse admin password you can press
      Enter to accept the generated value or type your own.

      Save the values shown at the end of this script — they will not be
      displayed again.
    """)
    )

    # Auto-generated, no user override
    salt_key = gen_hex(32)
    postgres_password = gen_password()
    valkey_password = gen_password()
    langfuse_secret_key = gen_password()
    langfuse_public_key = gen_langfuse_public_key()
    nextauth_secret = gen_password()
    langfuse_salt = gen_hex(32)

    # User may override master key
    generated_master = gen_master_key()
    print(f"  Generated LITELLM_MASTER_KEY: {cyan(generated_master)}")
    master_key = prompt(
        "  LITELLM_MASTER_KEY (Enter to accept)", default=generated_master, secret=False
    )
    # Ensure it starts with sk-
    if not master_key.startswith("sk-"):
        master_key = "sk-" + master_key
        print(f"  Prefixed with 'sk-': {cyan(master_key)}")

    # User may override Langfuse admin password
    generated_lf_pass = gen_password()
    print()
    print(f"  Generated Langfuse admin password: {cyan(generated_lf_pass)}")
    langfuse_init_password = prompt(
        "  Langfuse admin password (Enter to accept)", default=generated_lf_pass, secret=False
    )
    if not langfuse_init_password:
        langfuse_init_password = generated_lf_pass

    return {
        "LITELLM_MASTER_KEY": master_key,
        "LITELLM_SALT_KEY": salt_key,
        "POSTGRES_USER": "litellm",
        "POSTGRES_PASSWORD": postgres_password,
        "POSTGRES_DB": "litellm",
        "VALKEY_PASSWORD": valkey_password,
        "LANGFUSE_SECRET_KEY": langfuse_secret_key,
        "LANGFUSE_PUBLIC_KEY": langfuse_public_key,
        "NEXTAUTH_SECRET": nextauth_secret,
        "SALT": langfuse_salt,
        "LANGFUSE_INIT_USER_PASSWORD": langfuse_init_password,
        "CUSTOM_ENDPOINT_URL": custom_endpoint["url"] if custom_endpoint else "",
        "CUSTOM_ENDPOINT_KEY": custom_endpoint["key"] if custom_endpoint else "",
    }


# ---------------------------------------------------------------------------
# Step 7 — Write files
# ---------------------------------------------------------------------------


def write_env(out_dir, gcp_project, vertex_location, sec, custom_endpoint):
    lines = [
        "# ── LiteLLM ──────────────────────────────────────────────────────────────────",
        f"LITELLM_MASTER_KEY={sec['LITELLM_MASTER_KEY']}",
        "# Salt key: generated once by setup.py — NEVER change after first use.",
        "# Rotating this value will corrupt the LiteLLM database.",
        f"LITELLM_SALT_KEY={sec['LITELLM_SALT_KEY']}",
        "",
        "# ── PostgreSQL ────────────────────────────────────────────────────────────────",
        f"POSTGRES_USER={sec['POSTGRES_USER']}",
        f"POSTGRES_PASSWORD={sec['POSTGRES_PASSWORD']}",
        f"POSTGRES_DB={sec['POSTGRES_DB']}",
        "",
        "# ── Valkey ────────────────────────────────────────────────────────────────────",
        f"VALKEY_PASSWORD={sec['VALKEY_PASSWORD']}",
        "",
        "# ── Langfuse ──────────────────────────────────────────────────────────────────",
        f"LANGFUSE_SECRET_KEY={sec['LANGFUSE_SECRET_KEY']}",
        f"LANGFUSE_PUBLIC_KEY={sec['LANGFUSE_PUBLIC_KEY']}",
        f"NEXTAUTH_SECRET={sec['NEXTAUTH_SECRET']}",
        f"SALT={sec['SALT']}",
        f"LANGFUSE_INIT_USER_PASSWORD={sec['LANGFUSE_INIT_USER_PASSWORD']}",
        "",
        "# ── GCP / Vertex AI ───────────────────────────────────────────────────────────",
        f"GOOGLE_CLOUD_PROJECT={gcp_project}",
        f"VERTEX_LOCATION={vertex_location}",
        "",
        "# ── Custom OpenAI-compatible endpoint (e.g. Ollama) ──────────────────────────",
        "# Leave blank if not using a local model endpoint.",
        f"CUSTOM_ENDPOINT_URL={sec['CUSTOM_ENDPOINT_URL']}",
        f"CUSTOM_ENDPOINT_KEY={sec['CUSTOM_ENDPOINT_KEY']}",
    ]
    env_path = out_dir / ".env"
    env_path.write_text("\n".join(lines) + "\n")
    print(f"  {green('✓')} Written: {env_path}")


def build_litellm_config(custom_endpoint):
    """
    Build litellm_config.yaml content based on whether a custom endpoint
    is configured. Constructs the file from fixed blocks.
    """
    vertex_model_block = """\
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
"""

    custom_model_block = """\

  # ── Custom OpenAI-compatible endpoint (e.g. Ollama) ───────────────────────
  # Duplicate and rename this block for additional local models.
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
"""

    smart_block_with_custom = """\

  # ── Routing group: "smart" ─────────────────────────────────────────────────
  # Cost-based routing: tries local model first, falls back to Gemini Flash,
  # then to Gemini Pro via router_settings.fallbacks.
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
"""

    smart_block_without_custom = """\

  # ── Routing group: "smart" ─────────────────────────────────────────────────
  # No local endpoint configured. Routes: Gemini Flash → Gemini Pro.
  # To add a local model later, add a smart entry with api_base pointing to
  # your local endpoint above this block.
  - model_name: smart
    litellm_params:
      model: vertex_ai/gemini-2.5-flash-preview-04-17
      vertex_project: os.environ/GOOGLE_CLOUD_PROJECT
      vertex_location: os.environ/VERTEX_LOCATION
      vertex_credentials: /secrets/gcp-credentials.json
"""

    router_and_settings = """\

# =============================================================================
# Router settings
# =============================================================================
router_settings:
  routing_strategy: cost-based-routing
  num_retries: 2
  timeout: 60
  fallbacks:
    - {"smart": ["gemini-2-5-pro"]}

  # Valkey for shared rate-limit state across restarts
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
# Caching and observability
# =============================================================================
litellm_settings:
  cache: true
  cache_params:
    type: redis
    host: valkey
    port: 6379
    password: os.environ/VALKEY_PASSWORD
    ttl: 600         # cache responses for 10 minutes

  # Langfuse observability — traces appear within seconds of a successful call
  success_callback: ["langfuse"]
  failure_callback: ["langfuse"]
"""

    header = """\
# =============================================================================
# LiteLLM Proxy Configuration
# Generated by setup.py — edit as needed.
# To add more models, duplicate the relevant block and update model_name and
# litellm_params.model.
# =============================================================================

model_list:

"""

    parts = [header, vertex_model_block]
    if custom_endpoint:
        parts.append(custom_model_block)
        parts.append(smart_block_with_custom)
    else:
        parts.append(smart_block_without_custom)
    parts.append(router_and_settings)

    return "".join(parts)


def write_litellm_config(out_dir, custom_endpoint):
    config_dir = out_dir / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    dest = config_dir / "litellm_config.yaml"
    content = build_litellm_config(custom_endpoint)
    dest.write_text(content)
    print(f"  {green('✓')} Written: {dest}")


def write_compose(out_dir):
    dest = out_dir / "podman-compose.yml"
    shutil.copy2(SAMPLE_COMPOSE, dest)
    print(f"  {green('✓')} Written: {dest}")


def write_gitignore(out_dir):
    gitignore = out_dir / ".gitignore"
    required = [".env", "secrets/"]
    if gitignore.exists():
        existing = gitignore.read_text()
        lines_to_add = [e for e in required if e not in existing.splitlines()]
        if lines_to_add:
            with gitignore.open("a") as f:
                f.write("\n" + "\n".join(lines_to_add) + "\n")
            print(f"  {green('✓')} Updated: {gitignore} (added: {', '.join(lines_to_add)})")
        else:
            print(f"  {green('✓')} .gitignore already covers .env and secrets/")
    else:
        gitignore.write_text("\n".join(required) + "\n")
        print(f"  {green('✓')} Written: {gitignore}")


def apply_gcp_credentials(gcp_creds, out_dir):
    """Perform the symlink/copy action for GCP credentials."""
    if not gcp_creds:
        return
    secrets_dir = out_dir / "secrets"
    dest = gcp_creds["dest"]
    src = gcp_creds["src"]
    action = gcp_creds["action"]

    secrets_dir.mkdir(parents=True, exist_ok=True)

    if dest.exists() or dest.is_symlink():
        dest.unlink()

    if action == "s":
        dest.symlink_to(src)
        print(f"  {green('✓')} Symlinked: {dest} -> {src}")
    elif action == "c":
        shutil.copy2(src, dest)
        dest.chmod(0o600)
        print(f"  {green('✓')} Copied: {src} -> {dest} (chmod 600)")


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------


def print_summary(out_dir, sec, gcp_project, vertex_location, custom_endpoint):
    section("Setup complete — save these values")

    print(
        textwrap.dedent(f"""\
      {yellow("These secrets are written to .env and will not be shown again.")}
      Store them somewhere safe (e.g. a password manager).
    """)
    )

    col = 36

    def row(k, v):
        print(f"  {bold(k.ljust(col))}  {cyan(v)}")

    row("LITELLM_MASTER_KEY", sec["LITELLM_MASTER_KEY"])
    row("LITELLM_SALT_KEY", sec["LITELLM_SALT_KEY"])
    row("POSTGRES_PASSWORD", sec["POSTGRES_PASSWORD"])
    row("VALKEY_PASSWORD", sec["VALKEY_PASSWORD"])
    row("LANGFUSE_SECRET_KEY", sec["LANGFUSE_SECRET_KEY"])
    row("LANGFUSE_PUBLIC_KEY", sec["LANGFUSE_PUBLIC_KEY"])
    row("NEXTAUTH_SECRET", sec["NEXTAUTH_SECRET"])
    row("LANGFUSE_INIT_USER_PASSWORD", sec["LANGFUSE_INIT_USER_PASSWORD"])
    row("GOOGLE_CLOUD_PROJECT", gcp_project)
    row("VERTEX_LOCATION", vertex_location)

    if custom_endpoint:
        row("CUSTOM_ENDPOINT_URL", custom_endpoint["url"])
    else:
        print(
            f"\n  {yellow('smart model:')} routes Gemini Flash → Gemini Pro (no local endpoint configured)"
        )

    print()
    hr()
    print(bold("  Next steps"))
    hr()
    print(
        textwrap.dedent(f"""\

      1. Make sure secrets/gcp-credentials.json is in place (if you skipped that step).

      2. Start the stack:
           cd {out_dir}
           podman compose up -d

      3. Watch LiteLLM start up (wait for "Application startup complete"):
           podman compose logs -f litellm

      4. Verify:
           curl http://localhost:4000/health

      5. Service URLs:
           LiteLLM API    http://localhost:4000
           LiteLLM UI     http://localhost:4000/ui     (master key: {sec["LITELLM_MASTER_KEY"]})
           Langfuse       http://localhost:3000         (admin@local.dev / {sec["LANGFUSE_INIT_USER_PASSWORD"]})
           Open WebUI     http://localhost:8080         (first account becomes admin)

      6. If LiteLLM fails to start because Postgres wasn't ready:
           podman compose restart litellm

      7. To update all images later:
           podman compose pull && podman compose up -d
    """)
    )
    hr("═")
    print()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    print_banner()

    # Collect all inputs before writing anything
    out_dir = get_output_dir()
    check_existing_env(out_dir)
    gcp_creds = setup_gcp_credentials(out_dir)
    gcp_project, vertex_location = get_gcp_config()
    custom_endpoint = get_custom_endpoint()
    sec = generate_secrets(custom_endpoint)

    # Confirm before writing
    section("Step 7 of 7 — Writing files")
    print(f"  Output directory: {cyan(str(out_dir))}")
    print()
    if not prompt_yes_no("Proceed and write all files?", default=True):
        print(red("\n  Aborted. No files were written."))
        sys.exit(0)
    print()

    # Create directory structure
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "secrets").mkdir(exist_ok=True)

    # Write files
    apply_gcp_credentials(gcp_creds, out_dir)
    write_env(out_dir, gcp_project, vertex_location, sec, custom_endpoint)
    write_litellm_config(out_dir, custom_endpoint)
    write_compose(out_dir)
    write_gitignore(out_dir)

    print_summary(out_dir, sec, gcp_project, vertex_location, custom_endpoint)


if __name__ == "__main__":
    main()
