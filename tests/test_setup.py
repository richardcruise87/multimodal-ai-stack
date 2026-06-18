"""
Unit tests for samples/setup.py

Tests cover all pure functions (no I/O, no user input):
  - Secret generators
  - build_litellm_config (both variants)
  - write_env content
  - write_gitignore logic (new file and append)
  - apply_gcp_credentials (symlink and copy)
"""

import importlib.util
import json
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Load the module without executing main()
# ---------------------------------------------------------------------------

SETUP_PATH = Path(__file__).resolve().parents[1] / "setup.py"


def load_setup():
    spec = importlib.util.spec_from_file_location("setup", SETUP_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def setup():
    return load_setup()


@pytest.fixture()
def tmp(tmp_path):
    """Provide a clean temporary directory for each test."""
    return tmp_path


# ---------------------------------------------------------------------------
# Secret generators
# ---------------------------------------------------------------------------


class TestGenerators:
    def test_gen_password_length(self, setup):
        pw = setup.gen_password()
        # token_urlsafe(24) → 32 base64 chars
        assert len(pw) >= 24

    def test_gen_password_uniqueness(self, setup):
        assert setup.gen_password() != setup.gen_password()

    def test_gen_hex_default_length(self, setup):
        h = setup.gen_hex()
        assert len(h) == 32
        assert all(c in "0123456789abcdef" for c in h)

    def test_gen_hex_custom_length(self, setup):
        h = setup.gen_hex(16)
        assert len(h) == 16

    def test_gen_master_key_prefix(self, setup):
        key = setup.gen_master_key()
        assert key.startswith("sk-")
        assert len(key) > 5

    def test_gen_master_key_uniqueness(self, setup):
        assert setup.gen_master_key() != setup.gen_master_key()

    def test_gen_langfuse_public_key_prefix(self, setup):
        key = setup.gen_langfuse_public_key()
        assert key.startswith("lf-pk-")
        assert len(key) > 10

    def test_gen_langfuse_public_key_uniqueness(self, setup):
        assert setup.gen_langfuse_public_key() != setup.gen_langfuse_public_key()


# ---------------------------------------------------------------------------
# build_litellm_config
# ---------------------------------------------------------------------------


class TestBuildLitellmConfig:
    CUSTOM = {"url": "http://host.containers.internal:11434/v1", "key": "unused"}

    def test_with_custom_contains_vertex_models(self, setup):
        config = setup.build_litellm_config(self.CUSTOM)
        assert "gemini-2-5-pro" in config
        assert "gemini-2-5-flash" in config
        assert "vertex_ai/gemini-2.5-pro" in config

    def test_with_custom_contains_local_models(self, setup):
        config = setup.build_litellm_config(self.CUSTOM)
        assert "llama-local" in config
        assert "qwen-coder" in config
        assert "openai/llama3.3:70b" in config
        assert "openai/qwen2.5-coder:32b" in config

    def test_with_custom_smart_includes_local_entry(self, setup):
        config = setup.build_litellm_config(self.CUSTOM)
        # smart group should have the qwen local entry
        assert "CUSTOM_ENDPOINT_URL" in config

    def test_with_custom_router_settings_present(self, setup):
        config = setup.build_litellm_config(self.CUSTOM)
        assert "router_settings:" in config
        assert "cost-based-routing" in config
        assert '"smart": ["gemini-2-5-pro"]' in config

    def test_with_custom_caching_present(self, setup):
        config = setup.build_litellm_config(self.CUSTOM)
        assert "litellm_settings:" in config
        assert "ttl: 600" in config
        assert "langfuse" in config

    def test_without_custom_no_local_models(self, setup):
        config = setup.build_litellm_config(None)
        assert "llama-local" not in config
        assert "qwen-coder" not in config
        assert "llama3.3" not in config

    def test_without_custom_contains_vertex_models(self, setup):
        config = setup.build_litellm_config(None)
        assert "gemini-2-5-pro" in config
        assert "gemini-2-5-flash" in config

    def test_without_custom_smart_uses_flash(self, setup):
        config = setup.build_litellm_config(None)
        # smart group should reference flash
        assert "gemini-2.5-flash" in config

    def test_without_custom_router_fallback_to_pro(self, setup):
        config = setup.build_litellm_config(None)
        assert '"smart": ["gemini-2-5-pro"]' in config

    def test_without_custom_no_custom_endpoint_vars(self, setup):
        config = setup.build_litellm_config(None)
        assert "CUSTOM_ENDPOINT_URL" not in config
        assert "CUSTOM_ENDPOINT_KEY" not in config

    def test_config_is_valid_yaml(self, setup):
        """Generated config must parse as valid YAML."""
        yaml = pytest.importorskip("yaml")
        for endpoint in [self.CUSTOM, None]:
            config = setup.build_litellm_config(endpoint)
            # Should not raise
            parsed = yaml.safe_load(config)
            assert isinstance(parsed, dict)
            assert "model_list" in parsed
            assert "router_settings" in parsed
            assert "litellm_settings" in parsed


# ---------------------------------------------------------------------------
# write_env
# ---------------------------------------------------------------------------


SAMPLE_SECRETS = {
    "LITELLM_MASTER_KEY": "sk-testkey123",
    "LITELLM_SALT_KEY": "a" * 32,
    "POSTGRES_USER": "litellm",
    "POSTGRES_PASSWORD": "pg-pass",
    "POSTGRES_DB": "litellm",
    "VALKEY_PASSWORD": "valkey-pass",
    "LANGFUSE_SECRET_KEY": "lf-secret",
    "LANGFUSE_PUBLIC_KEY": "lf-pk-abc123",
    "NEXTAUTH_SECRET": "nextauth-secret",
    "SALT": "b" * 32,
    "LANGFUSE_INIT_USER_PASSWORD": "lf-admin-pass",
    "CUSTOM_ENDPOINT_URL": "http://host.containers.internal:11434/v1",
    "CUSTOM_ENDPOINT_KEY": "unused",
    "QWEN3_API_BASE": "https://qwen3.example.com",
    "QWEN3_API_KEY": "test-qwen3-key",
}


class TestWriteEnv:
    def test_all_keys_present(self, setup, tmp):
        setup.write_env(tmp, "my-project", "us-central1", SAMPLE_SECRETS, {"url": "x", "key": "y"})
        content = (tmp / ".env").read_text()
        for key in SAMPLE_SECRETS:
            assert key in content

    def test_gcp_vars_written(self, setup, tmp):
        setup.write_env(tmp, "test-project-id", "europe-west4", SAMPLE_SECRETS, None)
        content = (tmp / ".env").read_text()
        assert "GOOGLE_CLOUD_PROJECT=test-project-id" in content
        assert "VERTEX_LOCATION=europe-west4" in content

    def test_salt_key_warning_comment(self, setup, tmp):
        setup.write_env(tmp, "p", "us-central1", SAMPLE_SECRETS, None)
        content = (tmp / ".env").read_text()
        assert "NEVER change after first use" in content

    def test_master_key_value(self, setup, tmp):
        setup.write_env(tmp, "p", "us-central1", SAMPLE_SECRETS, None)
        content = (tmp / ".env").read_text()
        assert "LITELLM_MASTER_KEY=sk-testkey123" in content

    def test_qwen3_vars_written(self, setup, tmp):
        setup.write_env(tmp, "p", "us-central1", SAMPLE_SECRETS, None)
        content = (tmp / ".env").read_text()
        assert "QWEN3_API_BASE=" in content
        assert "QWEN3_API_KEY=test-qwen3-key" in content

    def test_env_ends_with_newline(self, setup, tmp):
        setup.write_env(tmp, "p", "us-central1", SAMPLE_SECRETS, None)
        content = (tmp / ".env").read_text()
        assert content.endswith("\n")

    def test_no_secrets_in_gitignore_scope(self, setup, tmp):
        """Ensure .env file is a flat KEY=VALUE file with no YAML/JSON structure."""
        setup.write_env(tmp, "p", "us-central1", SAMPLE_SECRETS, None)
        content = (tmp / ".env").read_text()
        # Should not contain YAML/JSON structural characters at line start
        lines = [ln for ln in content.splitlines() if ln and not ln.startswith("#")]
        for line in lines:
            assert "=" in line, f"Expected KEY=VALUE line, got: {line!r}"


# ---------------------------------------------------------------------------
# write_gitignore
# ---------------------------------------------------------------------------


class TestWriteGitignore:
    def test_creates_new_gitignore(self, setup, tmp):
        setup.write_gitignore(tmp)
        content = (tmp / ".gitignore").read_text()
        assert ".env" in content
        assert "secrets/" in content

    def test_appends_to_existing_without_entries(self, setup, tmp):
        (tmp / ".gitignore").write_text("*.pyc\n__pycache__/\n")
        setup.write_gitignore(tmp)
        content = (tmp / ".gitignore").read_text()
        assert ".env" in content
        assert "secrets/" in content
        assert "*.pyc" in content  # original entry preserved

    def test_does_not_duplicate_existing_entries(self, setup, tmp):
        (tmp / ".gitignore").write_text(".env\nsecrets/\n")
        setup.write_gitignore(tmp)
        content = (tmp / ".gitignore").read_text()
        assert content.count(".env") == 1
        assert content.count("secrets/") == 1

    def test_partially_missing_entries_appended(self, setup, tmp):
        (tmp / ".gitignore").write_text(".env\n")
        setup.write_gitignore(tmp)
        content = (tmp / ".gitignore").read_text()
        assert "secrets/" in content
        assert content.count(".env") == 1


# ---------------------------------------------------------------------------
# apply_gcp_credentials
# ---------------------------------------------------------------------------


class TestApplyGcpCredentials:
    def _fake_creds(self, src_dir, dest_dir):
        src = src_dir / "service-account.json"
        src.write_text(json.dumps({"type": "service_account", "project_id": "test"}))
        dest = dest_dir / "secrets" / "gcp-credentials.json"
        return src, dest

    def test_symlink_action(self, setup, tmp):
        src_dir = tmp / "src"
        src_dir.mkdir()
        dest_dir = tmp / "stack"
        dest_dir.mkdir()
        src, dest = self._fake_creds(src_dir, dest_dir)

        gcp_creds = {"action": "s", "src": src, "dest": dest}
        setup.apply_gcp_credentials(gcp_creds, dest_dir)

        assert dest.is_symlink()
        assert dest.resolve() == src.resolve()

    def test_copy_action(self, setup, tmp):
        src_dir = tmp / "src"
        src_dir.mkdir()
        dest_dir = tmp / "stack"
        dest_dir.mkdir()
        src, dest = self._fake_creds(src_dir, dest_dir)

        gcp_creds = {"action": "c", "src": src, "dest": dest}
        setup.apply_gcp_credentials(gcp_creds, dest_dir)

        assert dest.is_file()
        assert not dest.is_symlink()
        assert dest.read_text() == src.read_text()
        assert oct(dest.stat().st_mode)[-3:] == "600"

    def test_copy_replaces_existing_symlink(self, setup, tmp):
        src_dir = tmp / "src"
        src_dir.mkdir()
        dest_dir = tmp / "stack"
        (dest_dir / "secrets").mkdir(parents=True)
        src, dest = self._fake_creds(src_dir, dest_dir)

        # Pre-create a symlink at dest
        dummy = src_dir / "dummy.json"
        dummy.write_text("{}")
        dest.symlink_to(dummy)
        assert dest.is_symlink()

        gcp_creds = {"action": "c", "src": src, "dest": dest}
        setup.apply_gcp_credentials(gcp_creds, dest_dir)

        assert dest.is_file()
        assert not dest.is_symlink()

    def test_skip_action_does_nothing(self, setup, tmp):
        dest_dir = tmp / "stack"
        dest_dir.mkdir()
        setup.apply_gcp_credentials(False, dest_dir)
        assert not (dest_dir / "secrets" / "gcp-credentials.json").exists()

    def test_secrets_dir_created_if_missing(self, setup, tmp):
        src_dir = tmp / "src"
        src_dir.mkdir()
        dest_dir = tmp / "stack"
        dest_dir.mkdir()
        # Do NOT pre-create dest_dir/secrets
        src, dest = self._fake_creds(src_dir, dest_dir)

        gcp_creds = {"action": "s", "src": src, "dest": dest}
        setup.apply_gcp_credentials(gcp_creds, dest_dir)

        assert (dest_dir / "secrets").is_dir()
        assert dest.is_symlink()


# ---------------------------------------------------------------------------
# write_litellm_config (integration: writes file and checks content)
# ---------------------------------------------------------------------------


class TestWriteLitellmConfig:
    def test_writes_file_with_custom(self, setup, tmp):
        setup.write_litellm_config(tmp, {"url": "http://ollama/v1", "key": "unused"})
        dest = tmp / "config" / "litellm_config.yaml"
        assert dest.exists()
        assert "llama-local" in dest.read_text()

    def test_writes_file_without_custom(self, setup, tmp):
        setup.write_litellm_config(tmp, None)
        dest = tmp / "config" / "litellm_config.yaml"
        assert dest.exists()
        assert "llama-local" not in dest.read_text()

    def test_creates_config_subdir(self, setup, tmp):
        setup.write_litellm_config(tmp, None)
        assert (tmp / "config").is_dir()
