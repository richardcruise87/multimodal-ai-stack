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

When an existing .env is detected the script offers three modes:
    Merge    — preserve existing secrets, add/update configuration (default)
    Overwrite — regenerate all secrets (requires double confirmation; data loss)
    Abort    — exit without making any changes
"""

import secrets
import shutil
import sys
import textwrap
from pathlib import Path
from typing import Dict, List, Optional

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


def prompt_explicit_yes(message):
    """
    Prompt requiring the user to type exactly 'Yes' (case-sensitive) to confirm.
    Any other input is treated as No.  Returns bool.
    """
    try:
        value = input(f"  {message} {cyan('[Yes/no]')}: ").strip()
    except (KeyboardInterrupt, EOFError):
        print()
        print(red("\nAborted."))
        sys.exit(1)
    return value == "Yes"


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
    section("Step 1 of 9 — Output directory")
    default = str(Path.home() / "ai-stack")
    raw = prompt("Stack directory", default=default)
    out = Path(raw).expanduser().resolve()
    print(f"\n  Will create: {cyan(str(out))}")
    return out


# ---------------------------------------------------------------------------
# Step 2 — Existing .env check
# ---------------------------------------------------------------------------


def parse_env(env_path: Path) -> Dict[str, str]:
    """
    Parse an existing .env file into a dict.

    Rules:
      - Lines starting with '#' are comments and are ignored.
      - Blank lines are ignored.
      - Each remaining line must contain '='; the key is everything before
        the first '=' (stripped), the value is everything after (stripped).
        This correctly handles values that themselves contain '=' such as
        DATABASE_URL=postgresql://user:pass@host/db.

    Returns: {"KEY": "value", ...}
    """
    result: Dict[str, str] = {}
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            key, value = line.split("=", 1)
            result[key.strip()] = value.strip()
    return result


def confirm_overwrite_data_loss() -> bool:
    """
    Double-confirmation gate for the destructive overwrite path.

    The user must type exactly 'Yes' (case-sensitive) at both prompts.
    Any other response at either prompt returns False immediately.
    """
    print()
    print(red("  ⚠️  WARNING: Overwriting will PERMANENTLY LOSE ACCESS to:"))
    print()
    print(red("    • LiteLLM virtual keys and spend history  (postgres_data volume)"))
    print(red("    • Langfuse traces and observability logs  (langfuse_postgres_data volume)"))
    print(red("    • Open WebUI chat history                 (open_webui_data volume)"))
    print()
    print(yellow("  If you have existing data, choose Merge mode instead."))
    print()

    if not prompt_explicit_yes(
        "Proceed with overwrite? Type 'Yes' to confirm, anything else cancels"
    ):
        return False

    print()
    print(red("  ⚠️  SECOND CONFIRMATION: This action cannot be undone."))
    return prompt_explicit_yes("Are you absolutely sure? Type 'Yes' to confirm")


def check_existing_env(out_dir: Path) -> Optional[Dict[str, str]]:
    """
    Check whether an existing .env is present in out_dir.

    Returns:
      None            — fresh install (no existing .env, or user chose Overwrite)
      dict            — merge mode (parsed contents of the existing .env)

    The function may call sys.exit(0) if the user chooses Abort or cancels
    the overwrite confirmation.
    """
    env_path = out_dir / ".env"
    if not env_path.exists():
        return None  # Fresh install — nothing to worry about

    section("Step 2 of 9 — Existing .env detected")
    print(yellow(f"  Found existing .env at: {env_path}"))
    print()

    choice = prompt_choice(
        "What would you like to do?",
        [
            ("m", "Merge  — preserve existing secrets, add new config (RECOMMENDED)"),
            ("o", "Overwrite — generate fresh secrets (⚠️  DATA LOSS)"),
            ("a", "Abort  — exit setup without making any changes"),
        ],
    )

    if choice == "a":
        print()
        print(yellow("  Setup aborted. No changes made."))
        sys.exit(0)

    if choice == "o":
        if not confirm_overwrite_data_loss():
            print()
            print(yellow("  Overwrite cancelled. Setup aborted."))
            sys.exit(0)
        print()
        print(yellow("  Proceeding with overwrite. All secrets will be regenerated."))
        return None  # Treat as fresh install

    # Merge mode
    print()
    print(green("  Merge mode: existing secrets will be preserved."))
    return parse_env(env_path)


# ---------------------------------------------------------------------------
# Step 2b — Backup
# ---------------------------------------------------------------------------


def prompt_and_create_backups(out_dir: Path) -> List[str]:
    """
    Prompt the user whether they want numbered backups of files that are
    about to be overwritten.  Creates .bak.N siblings (preserving directory
    structure) for each file that exists.

    Returns a list of relative path strings for every backup file created,
    or an empty list if the user declined or no files existed.
    """
    candidates = [
        ".env",
        "podman-compose.yml",
        "config/litellm_config.yaml",
    ]

    existing = [f for f in candidates if (out_dir / f).exists()]
    if not existing:
        return []

    print()
    print(yellow("  The following files will be overwritten:"))
    for f in existing:
        print(f"    • {f}")
    print()

    if not prompt_yes_no("Create numbered backups of existing files?", default=True):
        print(yellow("  Skipping backups."))
        return []

    backed_up: List[str] = []
    for rel in existing:
        src = out_dir / rel

        # Find the next unused .bak.N number
        n = 1
        while (out_dir / f"{rel}.bak.{n}").exists():
            n += 1
        dest = out_dir / f"{rel}.bak.{n}"

        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        backed_up.append(str(dest.relative_to(out_dir)))

    if backed_up:
        print()
        print(green(f"  {green('✓')} Created {len(backed_up)} backup(s):"))
        for f in backed_up:
            print(green(f"      • {f}"))

    return backed_up


# ---------------------------------------------------------------------------
# Step 3 — GCP credentials
# ---------------------------------------------------------------------------


def _prompt_gcp_credentials_file(dest: Path) -> dict:
    """Inner loop: ask the user for a credentials file path and validate it."""
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
                        "  Warning: file does not look like a GCP service account key"
                        " (missing 'type' field)."
                    )
                )
                if not prompt_yes_no("  Continue anyway?", default=False):
                    continue
        except Exception as e:
            print(yellow(f"  Warning: could not parse file as JSON: {e}"))
            if not prompt_yes_no("  Continue anyway?", default=False):
                continue
        return src


def setup_gcp_credentials(out_dir: Path, existing_secrets: Optional[Dict] = None):
    """
    Step 3: configure the GCP service-account credentials file.

    In merge mode, if a credentials file already exists at the expected path
    the user is offered the option to keep it (default) or reconfigure.
    Choosing 'skip' at any point returns None, which signals apply_gcp_credentials
    to leave existing credentials untouched.
    """
    section("Step 3 of 9 — GCP credentials")
    secrets_dir = out_dir / "secrets"
    dest = secrets_dir / "gcp-credentials.json"

    # In merge mode, if credentials are already in place offer to skip
    if existing_secrets is not None and dest.exists():
        print(green(f"  ✓ Existing credentials found: {dest}"))
        if dest.is_symlink():
            try:
                print(f"    (symlink → {dest.resolve()})")
            except OSError:
                print("    (symlink — target may be missing)")
        print()
        if not prompt_yes_no("Reconfigure GCP credentials?", default=False):
            print(yellow("  Keeping existing credentials."))
            return None  # Leave them untouched
        print()

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
        return None  # Same as declining reconfigure — leave existing untouched

    src = _prompt_gcp_credentials_file(dest)
    return {"action": choice, "src": src, "dest": dest}


# ---------------------------------------------------------------------------
# Step 4 — GCP project config
# ---------------------------------------------------------------------------


def get_gcp_config(existing_secrets: Optional[Dict] = None):
    """
    Step 4: GCP project ID and Vertex AI location.

    In merge mode the current values are shown and kept by default.
    """
    section("Step 4 of 9 — GCP / Vertex AI project")

    if existing_secrets:
        current_project = existing_secrets.get("GOOGLE_CLOUD_PROJECT", "")
        current_location = existing_secrets.get("VERTEX_LOCATION", "us-central1")
        if current_project:
            print(f"  Current project:  {cyan(current_project)}")
            print(f"  Current location: {cyan(current_location)}")
            print()
            if prompt_yes_no("Keep existing GCP configuration?", default=True):
                return current_project, current_location
            print()

    project = prompt("GOOGLE_CLOUD_PROJECT (your GCP project ID)")
    while not project:
        print(red("  Project ID cannot be empty."))
        project = prompt("GOOGLE_CLOUD_PROJECT")

    location = prompt("VERTEX_LOCATION", default="us-central1")
    return project, location


# ---------------------------------------------------------------------------
# Step 5 — Qwen3 endpoint
# ---------------------------------------------------------------------------


def get_qwen3_endpoint(existing_secrets: Optional[Dict] = None):
    """
    Step 5: optional external Qwen3-14B vLLM endpoint.

    In merge mode, an existing URL is shown and kept by default.
    """
    section("Step 5 of 9 — Qwen3-14B endpoint")

    if existing_secrets:
        existing_url = existing_secrets.get("QWEN3_API_BASE", "")
        if existing_url:
            print(f"  Currently configured: {cyan(existing_url)}")
            print()
            if prompt_yes_no("Keep existing Qwen3 endpoint?", default=True):
                return {
                    "url": existing_url,
                    "key": existing_secrets.get("QWEN3_API_KEY", ""),
                }
            print()

    print(
        textwrap.dedent("""\
      LiteLLM can route requests to an external Qwen3-14B model served via a
      vLLM / OpenAI-compatible endpoint. This is used as the primary model in
      the 'smart' and 'build' routing groups.

      If you skip this, 'smart' and 'build' will start with Gemini models instead.
    """)
    )

    use_qwen3 = prompt_yes_no("Do you have a Qwen3-14B endpoint to configure?", default=False)
    if not use_qwen3:
        return None

    url = prompt("Qwen3 API base URL (e.g. https://qwen3-14b.example.com/v1)")
    while not url:
        print(red("  URL cannot be empty."))
        url = prompt("Qwen3 API base URL")
    key = prompt("Qwen3 API key / bearer token", default="unused")
    return {"url": url, "key": key}


# ---------------------------------------------------------------------------
# Step 6 — Custom endpoint (Ollama / local models)
# ---------------------------------------------------------------------------


def get_custom_endpoint(existing_secrets: Optional[Dict] = None):
    """
    Step 6: optional local model server (Ollama / OpenAI-compatible).

    In merge mode, an existing URL is shown and kept by default.
    """
    section("Step 6 of 9 — Local model endpoint (Ollama / custom)")

    if existing_secrets:
        existing_url = existing_secrets.get("CUSTOM_ENDPOINT_URL", "")
        if existing_url:
            print(f"  Currently configured: {cyan(existing_url)}")
            print()
            if prompt_yes_no("Keep existing custom endpoint?", default=True):
                return {
                    "url": existing_url,
                    "key": existing_secrets.get("CUSTOM_ENDPOINT_KEY", ""),
                }
            print()

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
# Step 7 — Headroom token compression
# ---------------------------------------------------------------------------


def get_headroom_config(existing_secrets: Optional[Dict] = None):
    """
    Step 7: optional Headroom token compression sidecar.

    Always prompts (no .env marker stored) — compose is the runtime source of
    truth.  In merge mode a shorter description is shown since the user is
    already familiar with the stack.

    Note: users upgrading a stack that already has Headroom enabled will see
    this prompt on every merge run.  This is intentional — it lets them toggle
    Headroom on or off during any upgrade without storing extra state in .env.
    """
    section("Step 7 of 9 — Headroom token compression (optional)")

    if existing_secrets is not None:
        print("  Headroom is optional token compression (15–95% savings).")
        print("  The compose file will include Headroom if you enable it here.")
        print()
    else:
        print(
            textwrap.dedent("""\
          Headroom is a local token compression service that can reduce input token
          costs by 15-95% depending on content type (code, JSON, logs, etc.).

          It runs as a sidecar container alongside LiteLLM. When enabled, two extra
          routing groups are added — "build-compressed" and "smart-compressed" — that
          apply Headroom compression before sending requests to the LLM.

          Existing groups ("build", "smart") are unchanged; compression is opt-in
          by selecting the -compressed variant.

          Port 8787 will be exposed on the host.
        """)
        )

    use_headroom = prompt_yes_no("Enable Headroom token compression?", default=False)
    if not use_headroom:
        return None

    return {"enabled": True}


# ---------------------------------------------------------------------------
# Step 8 — Secret generation / merge
# ---------------------------------------------------------------------------


def generate_secrets(
    custom_endpoint,
    qwen3_endpoint,
    existing_secrets: Optional[Dict] = None,
) -> Dict[str, str]:
    """
    Generate (fresh install) or merge (upgrade) all .env secrets.

    In merge mode every secret that already exists in existing_secrets is
    reused verbatim.  Only keys that are absent from the existing file are
    newly generated.  A per-key log line is printed showing ✓ Preserved or
    + Generated so the user can see exactly what changed.

    The LITELLM_MASTER_KEY interactive override prompt is suppressed in merge
    mode (the existing key is always preserved).  The Langfuse admin password
    override is likewise suppressed — it was already set at first install.

    Endpoint URLs/keys follow the values returned by get_qwen3_endpoint() and
    get_custom_endpoint(), which in merge mode already contain the preserved or
    updated values chosen by the user.
    """
    section("Step 8 of 9 — Secrets")
    merge = existing_secrets is not None

    if merge:
        print(green("  Merge mode: existing secrets will be preserved."))
        print(green("  Only missing secrets will be generated."))
        print()
    else:
        print(
            textwrap.dedent("""\
          Generating random values for all secrets.
          For LITELLM_MASTER_KEY and the Langfuse admin password you can press
          Enter to accept the generated value or type your own.

          Save the values shown at the end of this script — they will not be
          displayed again.
        """)
        )

    def _get(key: str, generator, *, silent: bool = False) -> str:
        """Return existing value (merge) or call generator (fresh)."""
        if merge and key in existing_secrets:
            if not silent:
                print(f"  {green('✓')} Preserved: {key}")
            return existing_secrets[key]
        value = generator()
        if merge:
            print(f"  {cyan('+')} Generated: {key}")
        return value

    # --- Critical secrets — always preserved in merge mode, never prompted ---
    salt_key = _get("LITELLM_SALT_KEY", lambda: gen_hex(32))
    master_key = _get("LITELLM_MASTER_KEY", gen_master_key)
    postgres_user = _get("POSTGRES_USER", lambda: "litellm", silent=True)
    postgres_password = _get("POSTGRES_PASSWORD", gen_password)
    postgres_db = _get("POSTGRES_DB", lambda: "litellm", silent=True)
    valkey_password = _get("VALKEY_PASSWORD", gen_password)
    langfuse_secret_key = _get("LANGFUSE_SECRET_KEY", gen_password)
    langfuse_public_key = _get("LANGFUSE_PUBLIC_KEY", gen_langfuse_public_key)
    nextauth_secret = _get("NEXTAUTH_SECRET", gen_password)
    langfuse_salt = _get("SALT", lambda: gen_hex(32))
    langfuse_init_password = _get("LANGFUSE_INIT_USER_PASSWORD", gen_password)

    # --- Fresh-install interactive overrides (skipped in merge mode) ---
    if not merge:
        print(f"\n  Generated LITELLM_MASTER_KEY: {cyan(master_key)}")
        overridden = prompt(
            "  LITELLM_MASTER_KEY (Enter to accept)", default=master_key, secret=False
        )
        if overridden:
            master_key = overridden
        if not master_key.startswith("sk-"):
            master_key = "sk-" + master_key
            print(f"  Prefixed with 'sk-': {cyan(master_key)}")

        generated_lf_pass = langfuse_init_password
        print()
        print(f"  Generated Langfuse admin password: {cyan(generated_lf_pass)}")
        overridden_lf = prompt(
            "  Langfuse admin password (Enter to accept)", default=generated_lf_pass, secret=False
        )
        if overridden_lf:
            langfuse_init_password = overridden_lf

    # --- Endpoint config: use values from prompt steps (already merged there) ---
    custom_url = custom_endpoint["url"] if custom_endpoint else ""
    custom_key = custom_endpoint["key"] if custom_endpoint else ""
    qwen3_url = qwen3_endpoint["url"] if qwen3_endpoint else ""
    qwen3_key = qwen3_endpoint["key"] if qwen3_endpoint else ""

    return {
        "LITELLM_MASTER_KEY": master_key,
        "LITELLM_SALT_KEY": salt_key,
        "POSTGRES_USER": postgres_user,
        "POSTGRES_PASSWORD": postgres_password,
        "POSTGRES_DB": postgres_db,
        "VALKEY_PASSWORD": valkey_password,
        "LANGFUSE_SECRET_KEY": langfuse_secret_key,
        "LANGFUSE_PUBLIC_KEY": langfuse_public_key,
        "NEXTAUTH_SECRET": nextauth_secret,
        "SALT": langfuse_salt,
        "LANGFUSE_INIT_USER_PASSWORD": langfuse_init_password,
        "CUSTOM_ENDPOINT_URL": custom_url,
        "CUSTOM_ENDPOINT_KEY": custom_key,
        "QWEN3_API_BASE": qwen3_url,
        "QWEN3_API_KEY": qwen3_key,
    }


# ---------------------------------------------------------------------------
# Step 9 — Write files
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
        "",
        "# ── Qwen3-14B (external OpenAI-compatible / vLLM endpoint) ────────────────────",
        f"QWEN3_API_BASE={sec['QWEN3_API_BASE']}",
        f"QWEN3_API_KEY={sec['QWEN3_API_KEY']}",
    ]
    env_path = out_dir / ".env"
    env_path.write_text("\n".join(lines) + "\n")
    print(f"  {green('✓')} Written: {env_path}")


def build_litellm_config(custom_endpoint, headroom=None):
    """
    Build litellm_config.yaml content based on whether a custom endpoint
    and/or Headroom compression are configured. Constructs the file from
    fixed blocks.
    """
    vertex_model_block = """\
  # ── Vertex AI: Gemini models ───────────────────────────────────────────────
  # input_cost_per_token / output_cost_per_token are set explicitly here
  # because LiteLLM's pricing DB does not have a direct key for these
  # vertex_ai/ model strings, causing $0 cost to be logged in Langfuse.
  # Prices are per-token (USD). Source: cloud.google.com/vertex-ai/pricing
  - model_name: gemini-2-5-pro
    litellm_params:
      model: vertex_ai/gemini-2.5-pro
      vertex_project: os.environ/GOOGLE_CLOUD_PROJECT
      vertex_location: os.environ/VERTEX_LOCATION
      vertex_credentials: /secrets/gcp-credentials.json
      input_cost_per_token: 0.00000125   # $1.25 / 1M tokens
      output_cost_per_token: 0.00001     # $10.00 / 1M tokens

  - model_name: gemini-2-5-flash
    litellm_params:
      model: vertex_ai/gemini-2.5-flash-preview-04-17
      vertex_project: os.environ/GOOGLE_CLOUD_PROJECT
      vertex_location: os.environ/VERTEX_LOCATION
      vertex_credentials: /secrets/gcp-credentials.json
      input_cost_per_token: 0.0000003    # $0.30 / 1M tokens
      output_cost_per_token: 0.0000025   # $2.50 / 1M tokens

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

  # ── Qwen3-14B (external OpenAI-compatible / vLLM endpoint) ─────────────────
  # max_input_tokens reflects the actual deployed limit (original_max_position_embeddings).
  # Requests exceeding this will be routed to the fallback before being sent.
  # input/output_cost_per_token: LiteLLM has no entry for openai/Qwen/Qwen3-14B;
  # set to 0 explicitly so Langfuse shows $0 (free internal endpoint) rather
  # than a missing/null cost. Update if your endpoint charges a rate.
  - model_name: qwen3-14b
    max_input_tokens: 40960
    litellm_params:
      model: openai/Qwen/Qwen3-14B
      api_base: os.environ/QWEN3_API_BASE
      api_key: os.environ/QWEN3_API_KEY
      input_cost_per_token: 0
      output_cost_per_token: 0
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
  # Cost-based routing: qwen3-14b first (free), then local Ollama model,
  # then Gemini Flash, with a final fallback to Gemini Pro.
  - model_name: smart
    max_input_tokens: 40960
    litellm_params:
      model: openai/Qwen/Qwen3-14B
      api_base: os.environ/QWEN3_API_BASE
      api_key: os.environ/QWEN3_API_KEY
      input_cost_per_token: 0
      output_cost_per_token: 0

  - model_name: smart
    litellm_params:
      model: openai/qwen2.5-coder:32b
      api_base: os.environ/CUSTOM_ENDPOINT_URL
      api_key: os.environ/CUSTOM_ENDPOINT_KEY
      input_cost_per_token: 0
      output_cost_per_token: 0

  - model_name: smart
    litellm_params:
      model: vertex_ai/gemini-2.5-flash-preview-04-17
      vertex_project: os.environ/GOOGLE_CLOUD_PROJECT
      vertex_location: os.environ/VERTEX_LOCATION
      vertex_credentials: /secrets/gcp-credentials.json
      input_cost_per_token: 0.0000003    # $0.30 / 1M tokens
      output_cost_per_token: 0.0000025   # $2.50 / 1M tokens
"""

    smart_block_without_custom = """\

  # ── Routing group: "smart" ─────────────────────────────────────────────────
  # Cost-based routing: qwen3-14b first (free), falls back to Gemini Flash,
  # then to Gemini Pro via router_settings.fallbacks.
  - model_name: smart
    max_input_tokens: 40960
    litellm_params:
      model: openai/Qwen/Qwen3-14B
      api_base: os.environ/QWEN3_API_BASE
      api_key: os.environ/QWEN3_API_KEY
      input_cost_per_token: 0
      output_cost_per_token: 0

  - model_name: smart
    litellm_params:
      model: vertex_ai/gemini-2.5-flash-preview-04-17
      vertex_project: os.environ/GOOGLE_CLOUD_PROJECT
      vertex_location: os.environ/VERTEX_LOCATION
      vertex_credentials: /secrets/gcp-credentials.json
      input_cost_per_token: 0.0000003    # $0.30 / 1M tokens
      output_cost_per_token: 0.0000025   # $2.50 / 1M tokens
"""

    build_routing_block = """\

  # ── Routing group: "build" ─────────────────────────────────────────────────
  # Used by the OpenCode build agent: tries Qwen3-14B first (free), falls back
  # to Claude Sonnet 4.6 via router_settings.fallbacks.
  - model_name: build
    max_input_tokens: 40960
    litellm_params:
      model: openai/Qwen/Qwen3-14B
      api_base: os.environ/QWEN3_API_BASE
      api_key: os.environ/QWEN3_API_KEY
      input_cost_per_token: 0
      output_cost_per_token: 0

  - model_name: build
    litellm_params:
      model: vertex_ai/claude-sonnet-4-6
      vertex_project: os.environ/GOOGLE_CLOUD_PROJECT
      vertex_location: os.environ/VERTEX_LOCATION
      vertex_credentials: /secrets/gcp-credentials.json
"""

    build_compressed_block = """\

  # ── Routing group: "build-compressed" ─────────────────────────────────────
  # Same models as "build" but with Headroom token compression applied as a
  # pre_call guardrail. Requires the Headroom service to be running.
  - model_name: build-compressed
    max_input_tokens: 40960
    litellm_params:
      model: openai/Qwen/Qwen3-14B
      api_base: os.environ/QWEN3_API_BASE
      api_key: os.environ/QWEN3_API_KEY
      input_cost_per_token: 0
      output_cost_per_token: 0

  - model_name: build-compressed
    litellm_params:
      model: vertex_ai/claude-sonnet-4-6
      vertex_project: os.environ/GOOGLE_CLOUD_PROJECT
      vertex_location: os.environ/VERTEX_LOCATION
      vertex_credentials: /secrets/gcp-credentials.json
"""

    smart_compressed_with_custom = """\

  # ── Routing group: "smart-compressed" ─────────────────────────────────────
  # Same models as "smart" but with Headroom token compression applied.
  - model_name: smart-compressed
    max_input_tokens: 40960
    litellm_params:
      model: openai/Qwen/Qwen3-14B
      api_base: os.environ/QWEN3_API_BASE
      api_key: os.environ/QWEN3_API_KEY
      input_cost_per_token: 0
      output_cost_per_token: 0

  - model_name: smart-compressed
    litellm_params:
      model: openai/qwen2.5-coder:32b
      api_base: os.environ/CUSTOM_ENDPOINT_URL
      api_key: os.environ/CUSTOM_ENDPOINT_KEY
      input_cost_per_token: 0
      output_cost_per_token: 0

  - model_name: smart-compressed
    litellm_params:
      model: vertex_ai/gemini-2.5-flash-preview-04-17
      vertex_project: os.environ/GOOGLE_CLOUD_PROJECT
      vertex_location: os.environ/VERTEX_LOCATION
      vertex_credentials: /secrets/gcp-credentials.json
      input_cost_per_token: 0.0000003    # $0.30 / 1M tokens
      output_cost_per_token: 0.0000025   # $2.50 / 1M tokens
"""

    smart_compressed_without_custom = """\

  # ── Routing group: "smart-compressed" ─────────────────────────────────────
  # Same models as "smart" but with Headroom token compression applied.
  - model_name: smart-compressed
    max_input_tokens: 40960
    litellm_params:
      model: openai/Qwen/Qwen3-14B
      api_base: os.environ/QWEN3_API_BASE
      api_key: os.environ/QWEN3_API_KEY
      input_cost_per_token: 0
      output_cost_per_token: 0

  - model_name: smart-compressed
    litellm_params:
      model: vertex_ai/gemini-2.5-flash-preview-04-17
      vertex_project: os.environ/GOOGLE_CLOUD_PROJECT
      vertex_location: os.environ/VERTEX_LOCATION
      vertex_credentials: /secrets/gcp-credentials.json
      input_cost_per_token: 0.0000003    # $0.30 / 1M tokens
      output_cost_per_token: 0.0000025   # $2.50 / 1M tokens
"""

    headroom_guardrails_block = """\

# =============================================================================
# Guardrails
# =============================================================================
# Headroom runs as a sidecar service (port 8787) and compresses prompts before
# they reach the LLM. Use routing groups "build-compressed" or "smart-compressed"
# to opt in, or attach this guardrail to a virtual key via the LiteLLM Admin UI.
guardrails:
  - guardrail_name: headroom-compression
    litellm_params:
      guardrail: headroom
      mode: pre_call
      api_base: http://headroom:8787
      default_on: false  # opt-in only; set true to compress every request
"""

    router_settings_header = """\

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
"""

    router_settings_footer = """\
  context_window_fallbacks:
    - {"qwen3-14b": ["claude-sonnet-4-6"]}
    - {"build": ["claude-sonnet-4-6"]}
"""

    router_settings_end = """\
    - {"smart": ["gemini-2-5-pro"]}

  # Valkey for shared rate-limit state across restarts
  redis_host: valkey
  redis_port: 6379
  redis_password: os.environ/VALKEY_PASSWORD
"""

    general_settings = """\

# =============================================================================
# General proxy settings
# =============================================================================
general_settings:
  master_key: os.environ/LITELLM_MASTER_KEY
  # database_url is passed via DATABASE_URL environment variable in compose

# =============================================================================
# Caching and observability
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

    extra_fallbacks = ""
    extra_cwfallbacks = ""
    if headroom:
        extra_fallbacks = (
            '    - {"smart-compressed": ["gemini-2-5-pro"]}\n'
            '    - {"build-compressed": ["claude-sonnet-4-6"]}\n'
        )
        extra_cwfallbacks = (
            '    - {"build-compressed": ["claude-sonnet-4-6"]}\n'
            '    - {"smart-compressed": ["gemini-2-5-pro"]}\n'
        )

    # The router block is split into three string literals so that conditional
    # fallback lines (extra_fallbacks, extra_cwfallbacks) can be injected in
    # the correct positions without format-string brace escaping:
    #   router_settings_header  — routing_strategy … fallbacks (base entries)
    #   extra_fallbacks         — compressed-group fallbacks (headroom only)
    #   router_settings_footer  — context_window_fallbacks (base entries)
    #   extra_cwfallbacks       — compressed-group cwfallbacks (headroom only)
    #   router_settings_end     — smart cwfallback + redis config
    router_and_settings = (
        router_settings_header
        + extra_fallbacks
        + router_settings_footer
        + extra_cwfallbacks
        + router_settings_end
        + general_settings
    )

    parts = [header, vertex_model_block]
    if custom_endpoint:
        parts.append(custom_model_block)
    parts.append(build_routing_block)
    if headroom:
        parts.append(build_compressed_block)
    if custom_endpoint:
        parts.append(smart_block_with_custom)
    else:
        parts.append(smart_block_without_custom)
    if headroom:
        if custom_endpoint:
            parts.append(smart_compressed_with_custom)
        else:
            parts.append(smart_compressed_without_custom)
    if headroom:
        parts.append(headroom_guardrails_block)
    parts.append(router_and_settings)

    return "".join(parts)


def write_litellm_config(out_dir, custom_endpoint, headroom=None):
    config_dir = out_dir / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    dest = config_dir / "litellm_config.yaml"
    content = build_litellm_config(custom_endpoint, headroom=headroom)
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


def print_summary(
    out_dir,
    sec,
    gcp_project,
    vertex_location,
    custom_endpoint,
    qwen3_endpoint,
    headroom=None,
    merge_mode: bool = False,
    backup_files: Optional[List[str]] = None,
):
    section("Setup complete — save these values")

    if backup_files is None:
        backup_files = []

    if merge_mode:
        print(green("  ✓ Merge completed successfully"))
        print(green("  ✓ Existing secrets preserved — no data loss"))
        print(green("  ✓ Configuration files updated from latest templates"))
        print()
        print(yellow("  The following critical secrets were PRESERVED from your existing .env:"))
        print(yellow("    • LITELLM_SALT_KEY (database encryption — must never change)"))
        print(yellow("    • LITELLM_MASTER_KEY"))
        print(yellow("    • POSTGRES_PASSWORD"))
        print(yellow("    • LANGFUSE_SECRET_KEY / LANGFUSE_PUBLIC_KEY"))
        print(yellow("    • NEXTAUTH_SECRET, SALT, VALKEY_PASSWORD"))
        print()
    else:
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

    if qwen3_endpoint:
        row("QWEN3_API_BASE", qwen3_endpoint["url"])
    if custom_endpoint:
        row("CUSTOM_ENDPOINT_URL", custom_endpoint["url"])
    if headroom:
        print(
            f"\n  {green('Headroom:')} token compression enabled"
            " (build-compressed, smart-compressed)"
        )
    if not qwen3_endpoint and not custom_endpoint:
        print(
            f"\n  {yellow('smart model:')} routes Gemini Flash → Gemini Pro"
            " (no local endpoint configured)"
        )

    if backup_files:
        print()
        print(cyan("  Backups created:"))
        for f in backup_files:
            print(cyan(f"    • {f}"))

    print()
    hr()
    print(bold("  Next steps"))
    hr()

    headroom_step = (
        textwrap.dedent("""\

      6. Check Headroom is running:
           curl http://localhost:8787/health
           # Use model "build-compressed" or "smart-compressed" to compress prompts.
    """)
        if headroom
        else ""
    )

    restart_num = "7" if headroom else "6"
    update_num = "8" if headroom else "7"

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
    """)
        + headroom_step
        + textwrap.dedent(f"""\

      {restart_num}. If LiteLLM fails to start because Postgres wasn't ready:
           podman compose restart litellm

      {update_num}. To update all images later:
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

    # Step 2: existing .env — returns None (fresh/overwrite) or dict (merge)
    existing_secrets = check_existing_env(out_dir)

    gcp_creds = setup_gcp_credentials(out_dir, existing_secrets)
    gcp_project, vertex_location = get_gcp_config(existing_secrets)
    qwen3_endpoint = get_qwen3_endpoint(existing_secrets)
    custom_endpoint = get_custom_endpoint(existing_secrets)
    headroom = get_headroom_config(existing_secrets)
    sec = generate_secrets(custom_endpoint, qwen3_endpoint, existing_secrets)

    # Confirm before writing
    section("Step 9 of 9 — Writing files")
    print(f"  Output directory: {cyan(str(out_dir))}")
    if existing_secrets is not None:
        print(green("  Mode: MERGE (existing secrets preserved)"))
    else:
        print(yellow("  Mode: FRESH INSTALL (new secrets generated)"))
    print()
    if not prompt_yes_no("Proceed and write all files?", default=True):
        print(red("\n  Aborted. No files were written."))
        sys.exit(0)

    # Optional backups — prompt only if files already exist
    backup_files = prompt_and_create_backups(out_dir)
    print()

    # Create directory structure
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "secrets").mkdir(exist_ok=True)

    # Write files
    apply_gcp_credentials(gcp_creds, out_dir)
    write_env(out_dir, gcp_project, vertex_location, sec, custom_endpoint)
    write_litellm_config(out_dir, custom_endpoint, headroom=headroom)
    write_compose(out_dir)
    write_gitignore(out_dir)

    print_summary(
        out_dir,
        sec,
        gcp_project,
        vertex_location,
        custom_endpoint,
        qwen3_endpoint,
        headroom=headroom,
        merge_mode=existing_secrets is not None,
        backup_files=backup_files,
    )


if __name__ == "__main__":
    main()
