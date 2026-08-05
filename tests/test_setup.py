"""
Unit tests for samples/setup.py

Tests cover all pure functions (no I/O, no user input):
  - Secret generators
  - build_litellm_config (both variants)
  - write_env content
  - write_gitignore logic (new file and append)
  - apply_gcp_credentials (symlink and copy)
  - parse_env
  - confirm_overwrite_data_loss
  - prompt_and_create_backups
  - generate_secrets (merge mode)
"""

import importlib.util
import json
from pathlib import Path
from unittest.mock import patch

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


# ---------------------------------------------------------------------------
# build_litellm_config — Headroom variants
# ---------------------------------------------------------------------------


HEADROOM = {"enabled": True}
CUSTOM = {"url": "http://host.containers.internal:11434/v1", "key": "unused"}


class TestBuildLitellmConfigHeadroom:
    def test_headroom_adds_build_compressed(self, setup):
        config = setup.build_litellm_config(None, headroom=HEADROOM)
        assert "build-compressed" in config

    def test_headroom_adds_smart_compressed(self, setup):
        config = setup.build_litellm_config(None, headroom=HEADROOM)
        assert "smart-compressed" in config

    def test_headroom_adds_guardrails_section(self, setup):
        config = setup.build_litellm_config(None, headroom=HEADROOM)
        assert "guardrails:" in config
        assert "headroom-compression" in config
        assert "guardrail: headroom" in config
        assert "http://headroom:8787" in config

    def test_headroom_adds_compressed_fallbacks(self, setup):
        config = setup.build_litellm_config(None, headroom=HEADROOM)
        assert '"build-compressed": ["claude-sonnet-4-6"]' in config
        assert '"smart-compressed": ["gemini-2-5-pro"]' in config

    def test_headroom_adds_compressed_cwfallbacks(self, setup):
        yaml = pytest.importorskip("yaml")
        config = setup.build_litellm_config(None, headroom=HEADROOM)
        assert '"build-compressed": ["claude-sonnet-4-6"]' in config
        assert '"smart-compressed": ["gemini-2-5-pro"]' in config
        parsed = yaml.safe_load(config)
        cwf = parsed["router_settings"]["context_window_fallbacks"]
        keys = [list(entry.keys())[0] for entry in cwf]
        assert "build-compressed" in keys
        assert "smart-compressed" in keys

    def test_headroom_with_custom_smart_compressed_has_local_entry(self, setup):
        config = setup.build_litellm_config(CUSTOM, headroom=HEADROOM)
        # smart-compressed should include the custom endpoint entry
        lines = config.splitlines()
        in_smart_compressed = False
        found_custom = False
        for line in lines:
            if "model_name: smart-compressed" in line:
                in_smart_compressed = True
            if in_smart_compressed and "CUSTOM_ENDPOINT_URL" in line:
                found_custom = True
                break
        assert found_custom, "smart-compressed should reference CUSTOM_ENDPOINT_URL"

    def test_headroom_without_custom_smart_compressed_no_local_entry(self, setup):
        config = setup.build_litellm_config(None, headroom=HEADROOM)
        # smart-compressed should NOT include a custom endpoint block
        # (but CUSTOM_ENDPOINT_URL may appear in standalone llama-local — it's absent too)
        assert "CUSTOM_ENDPOINT_URL" not in config

    def test_no_headroom_no_compressed_groups(self, setup):
        config = setup.build_litellm_config(None, headroom=None)
        assert "build-compressed" not in config
        assert "smart-compressed" not in config
        assert "guardrails:" not in config

    def test_headroom_config_is_valid_yaml(self, setup):
        yaml = pytest.importorskip("yaml")
        for custom in [CUSTOM, None]:
            config = setup.build_litellm_config(custom, headroom=HEADROOM)
            parsed = yaml.safe_load(config)
            assert isinstance(parsed, dict)
            assert "model_list" in parsed
            assert "guardrails" in parsed
            assert "router_settings" in parsed

    def test_headroom_default_on_is_false(self, setup):
        config = setup.build_litellm_config(None, headroom=HEADROOM)
        assert "default_on: false" in config


# ---------------------------------------------------------------------------
# write_litellm_config — Headroom variants
# ---------------------------------------------------------------------------


class TestWriteLitellmConfigHeadroom:
    def test_writes_file_with_headroom(self, setup, tmp):
        setup.write_litellm_config(tmp, None, headroom=HEADROOM)
        dest = tmp / "config" / "litellm_config.yaml"
        assert dest.exists()
        content = dest.read_text()
        assert "build-compressed" in content
        assert "headroom-compression" in content

    def test_writes_file_without_headroom(self, setup, tmp):
        setup.write_litellm_config(tmp, None, headroom=None)
        dest = tmp / "config" / "litellm_config.yaml"
        assert dest.exists()
        assert "headroom-compression" not in dest.read_text()

    def test_writes_file_with_custom_and_headroom(self, setup, tmp):
        setup.write_litellm_config(tmp, CUSTOM, headroom=HEADROOM)
        dest = tmp / "config" / "litellm_config.yaml"
        assert dest.exists()
        content = dest.read_text()
        assert "llama-local" in content
        assert "smart-compressed" in content
        assert "headroom-compression" in content


# ---------------------------------------------------------------------------
# parse_env
# ---------------------------------------------------------------------------


class TestParseEnv:
    def test_parses_simple_key_value_pairs(self, setup, tmp):
        (tmp / ".env").write_text("KEY1=value1\nKEY2=value2\n")
        result = setup.parse_env(tmp / ".env")
        assert result == {"KEY1": "value1", "KEY2": "value2"}

    def test_ignores_comment_lines(self, setup, tmp):
        (tmp / ".env").write_text("# this is a comment\nKEY=value\n")
        result = setup.parse_env(tmp / ".env")
        assert result == {"KEY": "value"}
        assert "# this is a comment" not in result

    def test_ignores_blank_lines(self, setup, tmp):
        (tmp / ".env").write_text("\nKEY=value\n\n")
        result = setup.parse_env(tmp / ".env")
        assert result == {"KEY": "value"}

    def test_handles_equals_in_value(self, setup, tmp):
        # Values such as DATABASE_URL that contain '=' must be preserved in full
        (tmp / ".env").write_text("DB=postgresql://user:pass@host/db?sslmode=disable\n")
        result = setup.parse_env(tmp / ".env")
        assert result == {"DB": "postgresql://user:pass@host/db?sslmode=disable"}

    def test_strips_whitespace_around_key_and_value(self, setup, tmp):
        (tmp / ".env").write_text("  KEY  =  value  \n")
        result = setup.parse_env(tmp / ".env")
        assert result == {"KEY": "value"}

    def test_empty_value_is_preserved(self, setup, tmp):
        (tmp / ".env").write_text("KEY=\n")
        result = setup.parse_env(tmp / ".env")
        assert result == {"KEY": ""}

    def test_inline_comment_not_stripped(self, setup, tmp):
        # Only full-line comments are ignored; inline comments are part of the value
        (tmp / ".env").write_text("KEY=value # not a comment\n")
        result = setup.parse_env(tmp / ".env")
        assert result["KEY"] == "value # not a comment"

    def test_roundtrip_with_write_env(self, setup, tmp):
        """parse_env must be able to read back everything write_env writes."""
        setup.write_env(tmp, "my-project", "us-east1", SAMPLE_SECRETS, None)
        parsed = setup.parse_env(tmp / ".env")
        for key, val in SAMPLE_SECRETS.items():
            assert parsed[key] == val, f"Mismatch for {key}"
        assert parsed["GOOGLE_CLOUD_PROJECT"] == "my-project"
        assert parsed["VERTEX_LOCATION"] == "us-east1"


# ---------------------------------------------------------------------------
# confirm_overwrite_data_loss
# ---------------------------------------------------------------------------


class TestConfirmOverwriteDataLoss:
    def _run(self, setup, responses):
        """Patch prompt_explicit_yes to return successive values from responses."""
        calls = iter(responses)
        with patch.object(setup, "prompt_explicit_yes", side_effect=lambda _: next(calls)):
            return setup.confirm_overwrite_data_loss()

    def test_returns_true_on_double_yes(self, setup):
        assert self._run(setup, [True, True]) is True

    def test_returns_false_if_first_prompt_declined(self, setup):
        assert self._run(setup, [False]) is False

    def test_returns_false_if_second_prompt_declined(self, setup):
        assert self._run(setup, [True, False]) is False

    def test_first_no_does_not_call_second_prompt(self, setup):
        """If the first confirmation fails, the second must never be shown."""
        call_count = 0

        def side_effect(_):
            nonlocal call_count
            call_count += 1
            return False  # Always decline

        with patch.object(setup, "prompt_explicit_yes", side_effect=side_effect):
            setup.confirm_overwrite_data_loss()

        assert call_count == 1


# ---------------------------------------------------------------------------
# prompt_explicit_yes
# ---------------------------------------------------------------------------


class TestPromptExplicitYes:
    def test_returns_true_for_exact_Yes(self, setup):
        with patch("builtins.input", return_value="Yes"):
            assert setup.prompt_explicit_yes("Confirm?") is True

    def test_returns_false_for_lowercase_yes(self, setup):
        with patch("builtins.input", return_value="yes"):
            assert setup.prompt_explicit_yes("Confirm?") is False

    def test_returns_false_for_y(self, setup):
        with patch("builtins.input", return_value="y"):
            assert setup.prompt_explicit_yes("Confirm?") is False

    def test_returns_false_for_YES_uppercase(self, setup):
        with patch("builtins.input", return_value="YES"):
            assert setup.prompt_explicit_yes("Confirm?") is False

    def test_returns_false_for_empty_input(self, setup):
        with patch("builtins.input", return_value=""):
            assert setup.prompt_explicit_yes("Confirm?") is False

    def test_returns_false_for_arbitrary_string(self, setup):
        with patch("builtins.input", return_value="I UNDERSTAND DATA WILL BE LOST"):
            assert setup.prompt_explicit_yes("Confirm?") is False


# ---------------------------------------------------------------------------
# prompt_and_create_backups
# ---------------------------------------------------------------------------


class TestPromptAndCreateBackups:
    def _with_yes(self, setup, out_dir):
        """Run prompt_and_create_backups with the backup prompt answered Yes."""
        with patch.object(setup, "prompt_yes_no", return_value=True):
            return setup.prompt_and_create_backups(out_dir)

    def _with_no(self, setup, out_dir):
        """Run prompt_and_create_backups with the backup prompt answered No."""
        with patch.object(setup, "prompt_yes_no", return_value=False):
            return setup.prompt_and_create_backups(out_dir)

    def test_returns_empty_list_when_no_files_exist(self, setup, tmp):
        result = self._with_yes(setup, tmp)
        assert result == []

    def test_returns_empty_list_when_user_declines(self, setup, tmp):
        (tmp / ".env").write_text("KEY=value")
        result = self._with_no(setup, tmp)
        assert result == []

    def test_creates_bak_1_for_env(self, setup, tmp):
        (tmp / ".env").write_text("KEY=value")
        self._with_yes(setup, tmp)
        assert (tmp / ".env.bak.1").exists()
        assert (tmp / ".env.bak.1").read_text() == "KEY=value"

    def test_increments_to_bak_2_when_bak_1_exists(self, setup, tmp):
        (tmp / ".env").write_text("current")
        (tmp / ".env.bak.1").write_text("old")
        self._with_yes(setup, tmp)
        assert (tmp / ".env.bak.2").exists()
        assert (tmp / ".env.bak.2").read_text() == "current"

    def test_increments_across_multiple_existing_backups(self, setup, tmp):
        (tmp / ".env").write_text("newest")
        for i in range(1, 4):
            (tmp / f".env.bak.{i}").write_text(f"backup {i}")
        self._with_yes(setup, tmp)
        assert (tmp / ".env.bak.4").exists()

    def test_original_file_unchanged_after_backup(self, setup, tmp):
        (tmp / ".env").write_text("original content")
        self._with_yes(setup, tmp)
        assert (tmp / ".env").read_text() == "original content"

    def test_preserves_directory_structure_for_config(self, setup, tmp):
        (tmp / "config").mkdir()
        (tmp / "config" / "litellm_config.yaml").write_text("yaml: true")
        self._with_yes(setup, tmp)
        assert (tmp / "config" / "litellm_config.yaml.bak.1").exists()

    def test_backs_up_all_three_files(self, setup, tmp):
        (tmp / ".env").write_text("env")
        (tmp / "podman-compose.yml").write_text("compose")
        (tmp / "config").mkdir()
        (tmp / "config" / "litellm_config.yaml").write_text("config")
        result = self._with_yes(setup, tmp)
        assert len(result) == 3

    def test_returns_relative_paths(self, setup, tmp):
        (tmp / ".env").write_text("env")
        result = self._with_yes(setup, tmp)
        assert all(not Path(r).is_absolute() for r in result)
        assert ".env.bak.1" in result

    def test_backs_up_only_existing_files(self, setup, tmp):
        # Only .env exists — compose and config are missing
        (tmp / ".env").write_text("env")
        result = self._with_yes(setup, tmp)
        assert len(result) == 1
        assert ".env.bak.1" in result


# ---------------------------------------------------------------------------
# generate_secrets — merge mode
# ---------------------------------------------------------------------------

_ALL_EXISTING = {
    "LITELLM_MASTER_KEY": "sk-existing-master",
    "LITELLM_SALT_KEY": "existing-salt-key-32chars!!!!!!!",
    "POSTGRES_USER": "litellm",
    "POSTGRES_PASSWORD": "existing-pg-pass",
    "POSTGRES_DB": "litellm",
    "VALKEY_PASSWORD": "existing-valkey-pass",
    "LANGFUSE_SECRET_KEY": "existing-lf-secret",
    "LANGFUSE_PUBLIC_KEY": "lf-pk-existingpubkey",
    "NEXTAUTH_SECRET": "existing-nextauth",
    "SALT": "existing-salt-32hexchars!!!!!!!",
    "LANGFUSE_INIT_USER_PASSWORD": "existing-lf-admin-pass",
    "CUSTOM_ENDPOINT_URL": "",
    "CUSTOM_ENDPOINT_KEY": "",
    "QWEN3_API_BASE": "",
    "QWEN3_API_KEY": "",
}


class TestGenerateSecretsMergeMode:
    def test_preserves_salt_key(self, setup):
        result = setup.generate_secrets(None, None, _ALL_EXISTING)
        assert result["LITELLM_SALT_KEY"] == _ALL_EXISTING["LITELLM_SALT_KEY"]

    def test_preserves_master_key(self, setup):
        result = setup.generate_secrets(None, None, _ALL_EXISTING)
        assert result["LITELLM_MASTER_KEY"] == _ALL_EXISTING["LITELLM_MASTER_KEY"]

    def test_preserves_postgres_password(self, setup):
        result = setup.generate_secrets(None, None, _ALL_EXISTING)
        assert result["POSTGRES_PASSWORD"] == _ALL_EXISTING["POSTGRES_PASSWORD"]

    def test_preserves_valkey_password(self, setup):
        result = setup.generate_secrets(None, None, _ALL_EXISTING)
        assert result["VALKEY_PASSWORD"] == _ALL_EXISTING["VALKEY_PASSWORD"]

    def test_preserves_langfuse_secret_key(self, setup):
        result = setup.generate_secrets(None, None, _ALL_EXISTING)
        assert result["LANGFUSE_SECRET_KEY"] == _ALL_EXISTING["LANGFUSE_SECRET_KEY"]

    def test_preserves_langfuse_public_key(self, setup):
        result = setup.generate_secrets(None, None, _ALL_EXISTING)
        assert result["LANGFUSE_PUBLIC_KEY"] == _ALL_EXISTING["LANGFUSE_PUBLIC_KEY"]

    def test_preserves_nextauth_secret(self, setup):
        result = setup.generate_secrets(None, None, _ALL_EXISTING)
        assert result["NEXTAUTH_SECRET"] == _ALL_EXISTING["NEXTAUTH_SECRET"]

    def test_preserves_salt(self, setup):
        result = setup.generate_secrets(None, None, _ALL_EXISTING)
        assert result["SALT"] == _ALL_EXISTING["SALT"]

    def test_preserves_langfuse_init_password(self, setup):
        result = setup.generate_secrets(None, None, _ALL_EXISTING)
        assert result["LANGFUSE_INIT_USER_PASSWORD"] == _ALL_EXISTING["LANGFUSE_INIT_USER_PASSWORD"]

    def test_generates_missing_secret_when_absent(self, setup):
        # Existing file has no VALKEY_PASSWORD — merge must generate one
        partial = {k: v for k, v in _ALL_EXISTING.items() if k != "VALKEY_PASSWORD"}
        result = setup.generate_secrets(None, None, partial)
        assert "VALKEY_PASSWORD" in result
        assert result["VALKEY_PASSWORD"] != ""

    def test_endpoint_values_come_from_prompt_args(self, setup):
        # Even in merge mode, if the user provided a new endpoint via prompt
        # steps, its values should appear in the output.
        qwen = {"url": "https://new-qwen.example.com/v1", "key": "new-key"}
        result = setup.generate_secrets(None, qwen, _ALL_EXISTING)
        assert result["QWEN3_API_BASE"] == "https://new-qwen.example.com/v1"
        assert result["QWEN3_API_KEY"] == "new-key"

    def test_fresh_install_generates_all_secrets(self, setup):
        # Fresh-install mode prompts for master key / Langfuse password override;
        # patch input() to press Enter (accept generated values) for both prompts.
        with patch("builtins.input", return_value=""):
            result = setup.generate_secrets(None, None, None)
        for key in [
            "LITELLM_MASTER_KEY",
            "LITELLM_SALT_KEY",
            "POSTGRES_PASSWORD",
            "VALKEY_PASSWORD",
            "LANGFUSE_SECRET_KEY",
            "LANGFUSE_PUBLIC_KEY",
            "NEXTAUTH_SECRET",
            "SALT",
            "LANGFUSE_INIT_USER_PASSWORD",
        ]:
            assert key in result
            assert result[key] != ""

    def test_fresh_install_master_key_has_sk_prefix(self, setup):
        with patch("builtins.input", return_value=""):
            result = setup.generate_secrets(None, None, None)
        assert result["LITELLM_MASTER_KEY"].startswith("sk-")

    def test_merge_result_contains_all_required_keys(self, setup):
        result = setup.generate_secrets(None, None, _ALL_EXISTING)
        required = [
            "LITELLM_MASTER_KEY",
            "LITELLM_SALT_KEY",
            "POSTGRES_USER",
            "POSTGRES_PASSWORD",
            "POSTGRES_DB",
            "VALKEY_PASSWORD",
            "LANGFUSE_SECRET_KEY",
            "LANGFUSE_PUBLIC_KEY",
            "NEXTAUTH_SECRET",
            "SALT",
            "LANGFUSE_INIT_USER_PASSWORD",
            "CUSTOM_ENDPOINT_URL",
            "CUSTOM_ENDPOINT_KEY",
            "QWEN3_API_BASE",
            "QWEN3_API_KEY",
        ]
        for key in required:
            assert key in result, f"Missing key: {key}"


# ---------------------------------------------------------------------------
# AI harness configuration
# ---------------------------------------------------------------------------

_HARNESS_SEC = {
    "LANGFUSE_PUBLIC_KEY": "lf-pk-testpublic",
    "LANGFUSE_SECRET_KEY": "sk-testlangfusesecret",
    "LITELLM_MASTER_KEY": "sk-testmaster123",
}


class TestAIHarnessConfig:
    """Tests for write_opencode_langfuse_config, write_opencode_config,
    write_claude_config, and backup_ai_harness_configs."""

    # ── write_opencode_langfuse_config ───────────────────────────────────────

    def test_langfuse_config_json_structure(self, setup, tmp):
        """JSON file contains all expected keys with values from sec."""
        with patch("pathlib.Path.home", return_value=tmp):
            setup.write_opencode_langfuse_config(_HARNESS_SEC, "alice")

        dest = tmp / ".config" / "opencode" / "opencode-langfuse.json"
        assert dest.exists()

        data = json.loads(dest.read_text())
        assert data["publicKey"] == "lf-pk-testpublic"
        assert data["secretKey"] == "sk-testlangfusesecret"
        assert data["baseUrl"] == "http://localhost:3000"
        assert data["environment"] == "development"
        assert data["userId"] == "alice"

    def test_langfuse_config_missing_keys_writes_placeholders(self, setup, tmp):
        """Missing Langfuse keys produce placeholder strings, not KeyError."""
        sec = {"LITELLM_MASTER_KEY": "sk-master"}
        with patch("pathlib.Path.home", return_value=tmp):
            setup.write_opencode_langfuse_config(sec, "bob")

        dest = tmp / ".config" / "opencode" / "opencode-langfuse.json"
        data = json.loads(dest.read_text())
        assert "missing-from-env" in data["publicKey"]
        assert "missing-from-env" in data["secretKey"]

    def test_langfuse_config_chmod_600(self, setup, tmp):
        """File permissions must be 0o600 (owner read/write only)."""
        with patch("pathlib.Path.home", return_value=tmp):
            setup.write_opencode_langfuse_config(_HARNESS_SEC, "alice")

        dest = tmp / ".config" / "opencode" / "opencode-langfuse.json"
        mode = dest.stat().st_mode & 0o777
        assert mode == 0o600

    def test_langfuse_config_creates_parent_dirs(self, setup, tmp):
        """Parent directory ~/.config/opencode/ is created if absent."""
        assert not (tmp / ".config").exists()
        with patch("pathlib.Path.home", return_value=tmp):
            setup.write_opencode_langfuse_config(_HARNESS_SEC, "alice")
        assert (tmp / ".config" / "opencode").is_dir()

    # ── write_opencode_config ────────────────────────────────────────────────

    def test_opencode_config_copies_template(self, setup, tmp):
        """opencode.jsonc is copied verbatim from samples/."""
        with patch("pathlib.Path.home", return_value=tmp):
            setup.write_opencode_config()

        dest = tmp / ".config" / "opencode" / "opencode.jsonc"
        assert dest.exists()
        # The real sample file is referenced by the module constant
        expected = setup.SAMPLE_OPENCODE.read_text()
        assert dest.read_text() == expected

    def test_opencode_config_creates_parent_dirs(self, setup, tmp):
        """Parent directory is created if absent."""
        assert not (tmp / ".config").exists()
        with patch("pathlib.Path.home", return_value=tmp):
            setup.write_opencode_config()
        assert (tmp / ".config" / "opencode").is_dir()

    # ── write_claude_config ──────────────────────────────────────────────────

    def test_claude_config_substitutes_master_key(self, setup, tmp):
        """LITELLM_MASTER_KEY placeholder is replaced with the real key."""
        with patch("pathlib.Path.home", return_value=tmp):
            setup.write_claude_config(_HARNESS_SEC)

        dest = tmp / ".claude" / "settings.json"
        assert dest.exists()

        content = dest.read_text()
        assert '"sk-testmaster123"' in content
        assert "<your-litellm-master-key>" not in content

    def test_claude_config_is_valid_json(self, setup, tmp):
        """Written file must parse as valid JSON."""
        with patch("pathlib.Path.home", return_value=tmp):
            setup.write_claude_config(_HARNESS_SEC)

        dest = tmp / ".claude" / "settings.json"
        data = json.loads(dest.read_text())
        assert data["env"]["ANTHROPIC_API_KEY"] == "sk-testmaster123"
        assert data["env"]["ANTHROPIC_BASE_URL"] == "http://localhost:4000"

    def test_claude_config_creates_parent_dirs(self, setup, tmp):
        """~/.claude/ directory is created if absent."""
        assert not (tmp / ".claude").exists()
        with patch("pathlib.Path.home", return_value=tmp):
            setup.write_claude_config(_HARNESS_SEC)
        assert (tmp / ".claude").is_dir()

    # ── backup_ai_harness_configs ────────────────────────────────────────────

    def test_backup_opencode_incremental_numbering(self, setup, tmp):
        """Backup suffix increments past existing .bak.N files."""
        cfg_dir = tmp / ".config" / "opencode"
        cfg_dir.mkdir(parents=True)
        cfg = cfg_dir / "opencode.jsonc"
        cfg.write_text("original")
        # Pre-create .bak.1 and .bak.2
        (cfg_dir / "opencode.jsonc.bak.1").write_text("b1")
        (cfg_dir / "opencode.jsonc.bak.2").write_text("b2")

        harness = {"opencode": {"enabled": True, "backup": True}}
        with patch("pathlib.Path.home", return_value=tmp):
            backed = setup.backup_ai_harness_configs(harness)

        assert len(backed) == 1
        assert backed[0].endswith("opencode.jsonc.bak.3")
        assert (cfg_dir / "opencode.jsonc.bak.3").read_text() == "original"

    def test_backup_skipped_when_flag_false(self, setup, tmp):
        """No backup files are created when backup=False."""
        cfg_dir = tmp / ".config" / "opencode"
        cfg_dir.mkdir(parents=True)
        (cfg_dir / "opencode.jsonc").write_text("content")

        harness = {"opencode": {"enabled": True, "backup": False}}
        with patch("pathlib.Path.home", return_value=tmp):
            backed = setup.backup_ai_harness_configs(harness)

        assert backed == []
        assert not (cfg_dir / "opencode.jsonc.bak.1").exists()

    def test_backup_both_harnesses(self, setup, tmp):
        """All three candidate files are backed up when both harnesses request it."""
        oc_dir = tmp / ".config" / "opencode"
        oc_dir.mkdir(parents=True)
        (oc_dir / "opencode.jsonc").write_text("oc")
        (oc_dir / "opencode-langfuse.json").write_text("lf")

        cl_dir = tmp / ".claude"
        cl_dir.mkdir(parents=True)
        (cl_dir / "settings.json").write_text("cl")

        harness = {
            "opencode": {"enabled": True, "backup": True},
            "claude": {"enabled": True, "backup": True},
        }
        with patch("pathlib.Path.home", return_value=tmp):
            backed = setup.backup_ai_harness_configs(harness)

        assert len(backed) == 3
        names = [Path(b).name for b in backed]
        assert "opencode.jsonc.bak.1" in names
        assert "opencode-langfuse.json.bak.1" in names
        assert "settings.json.bak.1" in names

    def test_backup_returns_empty_when_no_files_exist(self, setup, tmp):
        """Empty list is returned when candidate files don't exist yet."""
        harness = {
            "opencode": {"enabled": True, "backup": True},
            "claude": {"enabled": True, "backup": True},
        }
        with patch("pathlib.Path.home", return_value=tmp):
            backed = setup.backup_ai_harness_configs(harness)

        assert backed == []

    def test_backup_none_harness_config_returns_empty(self, setup, tmp):
        """Passing None returns an empty list without error."""
        assert setup.backup_ai_harness_configs(None) == []
