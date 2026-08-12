import pytest
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from main import (
    clean_project_name,
    sanitize_conversation_id,
    resolve_workspace_dir_safely,
    get_conversation_project,
    kill_processes_locking_db,
    get_workspace_alignment_context,
    build_chat_response,
    ChatRequest,
)

LONG_THAI_OPTION_1 = "(Recommended) บันทึกการเลือกธีมใน LocalStorage และซิงค์กับ OS Preference เป็นค่าเริ่มต้นเมื่อยังไม่มีการตั้งค่าไว้"
LONG_THAI_OPTION_2 = "(Recommended) Hybrid WebGPU Compute + Server Fallback: ประมวลผลบน WebGPU WGSL Compute Shaders เป็นหลักเพื่อ Zero-latency และรองรับ Python FastAPI Fallback บน Server สำหรับเครื่องที่ไม่มี WebGPU"


def test_clean_project_name_sanitizes_long_inputs():
    res1 = clean_project_name(LONG_THAI_OPTION_1)
    res2 = clean_project_name(LONG_THAI_OPTION_2)
    assert res1 == "agy"
    assert res2 == "agy"
    assert len(clean_project_name("KookAI")) == 6


def test_sanitize_conversation_id():
    safe1 = sanitize_conversation_id(LONG_THAI_OPTION_1)
    safe2 = sanitize_conversation_id(LONG_THAI_OPTION_2)
    assert len(safe1.encode("utf-8")) <= 100
    assert len(safe2.encode("utf-8")) <= 100
    assert "\n" not in safe1
    assert "\n" not in safe2
    assert "/" not in safe1
    assert "\\" not in safe1


def test_sanitize_conversation_id_strips_path_traversal_and_nulls():
    unsafe = "../../../etc/passwd\x00\n\rtest"
    safe = sanitize_conversation_id(unsafe)
    assert ".." not in safe
    assert "/" not in safe
    assert "\x00" not in safe
    assert "\n" not in safe


def test_resolve_workspace_dir_safely_prevents_errno_36():
    # Calling with a >255 byte string must return standard working directory safely without throwing OSError(36)
    dir_path = resolve_workspace_dir_safely(LONG_THAI_OPTION_1)
    assert os.path.isdir(dir_path)

    # Calling with a 500-char string component
    dir_path2 = resolve_workspace_dir_safely("a" * 500)
    assert os.path.isdir(dir_path2)

    # Valid existing absolute directory
    cwd = os.getcwd()
    assert resolve_workspace_dir_safely(cwd) == cwd


def test_get_conversation_project_prevents_errno_36():
    proj = get_conversation_project(LONG_THAI_OPTION_1)
    assert proj is None or isinstance(proj, str)


def test_kill_processes_locking_db_prevents_errno_36():
    # Must run cleanly without raising OSError [Errno 36]
    kill_processes_locking_db(LONG_THAI_OPTION_1)
    kill_processes_locking_db("a" * 500)


def test_get_workspace_alignment_context_prevents_errno_36():
    assert get_workspace_alignment_context(LONG_THAI_OPTION_1) == ""
    assert get_workspace_alignment_context("a" * 500) == ""
    assert get_workspace_alignment_context("") == ""

