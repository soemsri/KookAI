import os
import shutil
import tempfile
import pytest

from profile_manager import (
    create_profile,
    delete_profile,
    get_default_profile,
    get_profile,
    get_profile_scoped_env,
    list_profiles,
    sanitize_profile_id,
    set_default_profile,
    update_profile_status,
)


@pytest.fixture
def temp_data_dir():
    d = tempfile.mkdtemp(prefix="kookai_test_profiles_")
    yield d
    shutil.rmtree(d, ignore_errors=True)


def test_sanitize_profile_id():
    assert sanitize_profile_id("user-work_01") == "user-work_01"
    assert sanitize_profile_id("a@gmail.com") == "a_gmail_com"
    with pytest.raises(ValueError):
        sanitize_profile_id("   ")
    with pytest.raises(ValueError):
        sanitize_profile_id("../escape")


def test_create_and_list_profiles(temp_data_dir):
    p1 = create_profile("codex", "a@gmail.com (Work)", profile_id="prof_work", data_dir=temp_data_dir)
    assert p1["id"] == "prof_work"
    assert p1["cli_id"] == "codex"
    assert p1["is_default"] is True
    assert os.path.isdir(p1["config_dir"])
    assert p1["config_dir"].endswith(".codex")

    p2 = create_profile("codex", "b@gmail.com (Personal)", profile_id="prof_personal", data_dir=temp_data_dir)
    assert p2["id"] == "prof_personal"
    assert p2["is_default"] is False

    profiles = list_profiles("codex", data_dir=temp_data_dir)
    assert len(profiles) == 2
    ids = [p["id"] for p in profiles]
    assert "prof_work" in ids
    assert "prof_personal" in ids


def test_default_profile_lifecycle(temp_data_dir):
    create_profile("codex", "Work", profile_id="p_work", data_dir=temp_data_dir)
    create_profile("codex", "Personal", profile_id="p_personal", data_dir=temp_data_dir)

    default_prof = get_default_profile("codex", data_dir=temp_data_dir)
    assert default_prof["id"] == "p_work"

    # Switch default
    ok = set_default_profile("codex", "p_personal", data_dir=temp_data_dir)
    assert ok is True

    default_prof = get_default_profile("codex", data_dir=temp_data_dir)
    assert default_prof["id"] == "p_personal"


def test_profile_scoped_env(temp_data_dir):
    p_codex = create_profile("codex", "Codex Profile", profile_id="p_codex", data_dir=temp_data_dir)
    env_codex = get_profile_scoped_env("p_codex", base_env={"EXISTING": "1"}, data_dir=temp_data_dir)
    assert env_codex["EXISTING"] == "1"
    assert env_codex["CODEX_HOME"] == os.path.abspath(p_codex["config_dir"])
    assert env_codex["KOOKAI_ACTIVE_PROFILE_ID"] == "p_codex"

    p_claude = create_profile("claude", "Claude Profile", profile_id="p_claude", data_dir=temp_data_dir)
    env_claude = get_profile_scoped_env("p_claude", data_dir=temp_data_dir)
    assert env_claude["CLAUDE_CONFIG_DIR"] == os.path.abspath(p_claude["config_dir"])
    assert env_claude["HOME"] == os.path.abspath(p_claude["profile_root"])


def test_delete_profile(temp_data_dir):
    p = create_profile("codex", "To Delete", profile_id="p_del", data_dir=temp_data_dir)
    cfg_dir = p["config_dir"]
    assert os.path.exists(cfg_dir)

    deleted = delete_profile("p_del", delete_files=True, data_dir=temp_data_dir)
    assert deleted is True

    assert get_profile("p_del", data_dir=temp_data_dir) is None
    assert not os.path.exists(cfg_dir)


def test_update_profile_status(temp_data_dir):
    create_profile("codex", "Status Test", profile_id="p_status", data_dir=temp_data_dir)
    ok = update_profile_status("p_status", "authenticated", data_dir=temp_data_dir)
    assert ok is True
    p = get_profile("p_status", data_dir=temp_data_dir)
    assert p["status"] == "authenticated"
    assert p["last_used_at"] is not None
