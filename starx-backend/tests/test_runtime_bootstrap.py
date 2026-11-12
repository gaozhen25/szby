from pathlib import Path

from app.core.config import ENV_FILE, ENV_FILES, Settings


def test_settings_uses_project_root_env_file():
    assert ENV_FILE.name == ".env"
    assert "starx-backend" in str(ENV_FILE.parent)

    config = Settings()
    env_files = config.model_config["env_file"]
    assert any(str(env_file).endswith(".env") for env_file in env_files)


def test_settings_can_read_parent_checkout_env_file_from_worktree():
    assert str(ENV_FILE) in [str(env_file) for env_file in ENV_FILES]
    if ".worktrees" in str(ENV_FILE):
        assert any(str(env_file).endswith("starx-backend/.env") for env_file in ENV_FILES)


def test_env_example_documents_autophone_credentials():
    env_example = (Path(__file__).resolve().parents[1] / ".env.example").read_text(encoding="utf-8")

    assert "STARX_AUTOPHONE_CLIENT_ID=" in env_example
    assert "STARX_AUTOPHONE_CLIENT_SECRET=" in env_example


def test_env_example_documents_doubao_search_config():
    env_example = (Path(__file__).resolve().parents[1] / ".env.example").read_text(encoding="utf-8")

    assert "STARX_DOUBAO_SEARCH_API_URL=" in env_example
    assert "STARX_DOUBAO_SEARCH_API_KEY=" in env_example
    assert "STARX_DOUBAO_SEARCH_TIMEOUT=" in env_example


def test_env_example_documents_tikhub_config():
    env_example = (Path(__file__).resolve().parents[1] / ".env.example").read_text(encoding="utf-8")

    assert "STARX_TIKHUB_BASE_URL=" in env_example
    assert "STARX_TIKHUB_API_KEY=" in env_example
    assert "STARX_TIKHUB_TIMEOUT=" in env_example
    assert "STARX_TIKHUB_MAX_RETRIES=" in env_example
    assert "STARX_SOCIAL_RETRIEVAL_PROVIDER=hybrid" in env_example
    assert "STARX_TIKHUB_MAX_IN_FLIGHT=" in env_example
    assert "STARX_TIKHUB_QPS=8" in env_example


def test_settings_accepts_common_ai_env_aliases(monkeypatch):
    monkeypatch.delenv("STARX_DEFAULT_TOKEN", raising=False)
    monkeypatch.delenv("STARX_DEFAULT_BASE_URL", raising=False)
    monkeypatch.delenv("STARX_DEFAULT_TIMEOUT", raising=False)
    monkeypatch.setenv("AI_API_TOKEN", "alias-token")
    monkeypatch.setenv("AI_BASE_URL", "https://alias.example.test")
    monkeypatch.setenv("DEFAULT_TIMEOUT", "90")
    monkeypatch.setenv("DEFAULT_LLM_MODEL", "qwen-plus-character")

    config = Settings()

    assert config.DEFAULT_TOKEN == "alias-token"
    assert config.DEFAULT_BASE_URL == "https://alias.example.test"
    assert config.DEFAULT_TIMEOUT == 90
    assert config.DEFAULT_LLM_MODEL == "qwen-plus-character"


def test_main_contains_direct_script_bootstrap_support():
    main_source = (Path(__file__).resolve().parents[1] / "app" / "main.py").read_text(encoding="utf-8")

    assert "if __package__ in (None, \"\"):" in main_source
    assert "sys.path.append" in main_source
