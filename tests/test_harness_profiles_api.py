import os
import shutil
import subprocess
import tempfile
from unittest import mock
import pytest
from fastapi.testclient import TestClient

import main
import profile_manager


@pytest.fixture
def client_with_temp_profiles():
    temp_dir = tempfile.mkdtemp(prefix="kookai_api_profiles_")
    with (
        mock.patch.object(profile_manager, "DEFAULT_DATA_DIR", temp_dir),
        mock.patch.dict(os.environ, {"KOOKAI_DATA_DIR": temp_dir}, clear=False),
        mock.patch("main.verify_authorization", return_value=True),
        mock.patch("main.can_manage_cli_connections", return_value=True),
    ):
        test_client = TestClient(main.app)
        yield test_client
    shutil.rmtree(temp_dir, ignore_errors=True)


def test_harness_profiles_api_lifecycle(client_with_temp_profiles):
    client = client_with_temp_profiles

    # 1. Initially empty
    resp = client.get("/api/harness/profiles")
    assert resp.status_code == 200
    assert resp.json() == {"profiles": []}

    # 2. Create Profile 1 (Work)
    resp = client.post(
        "/api/harness/profiles",
        json={"cli_id": "codex", "label": "a@gmail.com (Work)", "profile_id": "prof_work"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["id"] == "prof_work"
    assert data["cli_id"] == "codex"
    assert data["is_default"] is True

    # 3. Create Profile 2 (Personal)
    resp = client.post(
        "/api/harness/profiles",
        json={"cli_id": "codex", "label": "b@gmail.com (Personal)", "profile_id": "prof_personal"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["id"] == "prof_personal"
    assert data["is_default"] is False

    # 4. List profiles
    resp = client.get("/api/harness/profiles")
    assert resp.status_code == 200
    profiles = resp.json()["profiles"]
    assert len(profiles) == 2
    ids = [p["id"] for p in profiles]
    assert "prof_work" in ids
    assert "prof_personal" in ids

    # 5. Switch default profile
    resp = client.post("/api/harness/profiles/prof_personal/default")
    assert resp.status_code == 200
    assert resp.json()["success"] is True

    # Check updated default
    resp = client.get("/api/harness/profiles?cli_id=codex")
    profiles = resp.json()["profiles"]
    p_personal = next(p for p in profiles if p["id"] == "prof_personal")
    assert p_personal["is_default"] is True

    # 6. Connect profile launches login with scoped env
    with mock.patch("main.launch_cli_login") as mock_launch:
        mock_launch.return_value = {"launched": True, "message": "Login opened"}
        with mock.patch("main.get_cli_statuses", return_value=[{"id": "codex", "installed": True}]):
            resp = client.post("/api/harness/profiles/prof_work/connect")
            assert resp.status_code == 200
            assert mock_launch.called
            call_kwargs = mock_launch.call_args.kwargs
            env_override = call_kwargs.get("env_override") or mock_launch.call_args.args[2]
            assert os.path.normpath(env_override["CODEX_HOME"]).endswith(os.path.normpath("prof_work/.codex"))

    # 7. Delete profile
    resp = client.delete("/api/harness/profiles/prof_work")
    assert resp.status_code == 200
    assert resp.json()["deleted"] == "prof_work"

    # List again
    resp = client.get("/api/harness/profiles")
    profiles = resp.json()["profiles"]
    assert len(profiles) == 1
    assert profiles[0]["id"] == "prof_personal"


def test_harness_profiles_admin_permission_check(client_with_temp_profiles):
    client = client_with_temp_profiles
    with mock.patch("main.can_manage_cli_connections", return_value=False):
        resp = client.post(
            "/api/harness/profiles",
            json={"cli_id": "codex", "label": "Unauthorized Attempt"},
        )
        assert resp.status_code == 403
        assert "Local access is required" in resp.json()["detail"]


def test_run_agy_cli_forwards_profile_id():
    with mock.patch("main.run_agent_command") as mock_agent_cmd, \
         mock.patch("main.get_existing_db_ids", return_value=set()):
        mock_agent_cmd.return_value = subprocess.CompletedProcess(
            args=["agy"], returncode=0, stdout="Success response", stderr=""
        )
        reply, cid = main.run_agy_cli(
            message="hello",
            model_ui_name="Google Ultra 5x",
            conversation_id="conv_123",
            profile_id="prof_google_ultra_5x_66a188",
        )
        assert reply == "Success response"
        assert mock_agent_cmd.called
        kwargs = mock_agent_cmd.call_args.kwargs
        assert kwargs.get("profile_id") == "prof_google_ultra_5x_66a188"


def test_invoke_provider_backend_resolves_default_profile():
    with mock.patch("main.get_default_profile") as mock_get_def, \
         mock.patch("main.run_agy_cli") as mock_run_agy:
        mock_get_def.return_value = {"id": "prof_google_ultra_5x_66a188"}
        mock_run_agy.return_value = ("hello reply", "cid_1")

        reply, cid = main._invoke_provider_backend(
            prov="agy",
            message="hi",
            prov_model="gemini-3.8-flash",
            conversation_id="cid_1",
            target="Sandbox",
            workspace="agy",
            effort="Medium",
            speed="Standard",
            thinking=True,
            image_paths=None,
            progress_callback=None,
            profile_id=None,
        )
        assert mock_get_def.called
        assert mock_run_agy.called
        kwargs = mock_run_agy.call_args.kwargs
        assert kwargs.get("profile_id") == "prof_google_ultra_5x_66a188"
