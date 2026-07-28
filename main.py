import os
from dependency_bootstrap import ensure_python_requirements

ensure_python_requirements(os.path.dirname(os.path.abspath(__file__)))

import asyncio
import uvicorn
import subprocess
import logging
import glob
import re
import json
import base64
import uuid
import queue
import urllib.parse
import urllib.request
import datetime
from collections import deque
from fastapi import FastAPI, Request, HTTPException, UploadFile, File
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse, FileResponse, HTMLResponse
from pydantic import BaseModel
from typing import List, Optional
from codex_backend import (
    CODEX_CONVERSATION_PREFIX,
    build_codex_command,
    classify_codex_progress_line,
    codex_session_id,
    configure_codex_catalog,
    fetch_codex_rate_limits,
    hidden_subprocess_kwargs,
    is_codex_model,
    make_codex_conversation_id,
    normalize_codex_effort,
    normalize_codex_speed,
    parse_codex_jsonl,
    resolve_codex_executable,
    resolve_provider,
)
from claude_backend import (
    CLAUDE_CONVERSATION_PREFIX,
    build_claude_command,
    build_claude_environment,
    classify_claude_progress_line,
    claude_session_id,
    configure_claude_catalog,
    make_claude_conversation_id,
    normalize_claude_effort,
    parse_claude_stream_json,
    resolve_claude_executable,
)
from cli_manager import (
    auto_install_missing,
    get_cli_statuses,
    install_cli,
    launch_cli_login,
    resolve_cli_executable as resolve_managed_cli_executable,
)
from model_catalog import (
    ModelCatalogError,
    load_model_catalog,
    public_model_catalog,
    resolve_catalog_model,
    save_model_catalog,
)

# Configure logging
logging.basicConfig(level=logging.INFO)

import getpass
# Get system username and home directory dynamically
SYSTEM_USER = getpass.getuser()
HOME_DIR = os.path.expanduser("~")

# Base data directory for KookAI settings & pairing configs
GEMINI_DATA_DIR = os.path.join(HOME_DIR, ".gemini")
ANTIGRAVITY_DATA_DIR = os.path.join(GEMINI_DATA_DIR, "kookai")
ANTIGRAVITY_CLI_DIR = os.path.join(GEMINI_DATA_DIR, "kookai-cli")
LEGACY_ANTIGRAVITY_DATA_DIR = os.path.join(GEMINI_DATA_DIR, "antigravity")
LEGACY_ANTIGRAVITY_CLI_DIR = os.path.join(GEMINI_DATA_DIR, "antigravity-cli")
DESKTOP_DIR = os.path.join(HOME_DIR, "Desktop")
if os.name == "nt":
    try:
        import winreg
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders")
        path, _ = winreg.QueryValueEx(key, "Desktop")
        winreg.CloseKey(key)
        resolved_desktop = os.path.expandvars(path)
        if os.path.exists(resolved_desktop):
            DESKTOP_DIR = resolved_desktop
    except Exception as e:
        logging.error(f"Failed to resolve Windows Desktop user shell folder: {e}")
WORKSPACE_DIR = os.path.dirname(os.path.abspath(__file__))
BUILTIN_MODEL_CATALOG_PATH = os.path.join(
    WORKSPACE_DIR,
    "model_catalog.json",
)
MODEL_CATALOG_PATH = os.environ.get(
    "KOOKAI_MODEL_CATALOG_PATH",
    os.path.join(ANTIGRAVITY_DATA_DIR, "model_catalog.json"),
)


def load_runtime_model_catalog() -> dict:
    catalog_path = (
        MODEL_CATALOG_PATH
        if os.path.isfile(MODEL_CATALOG_PATH)
        else BUILTIN_MODEL_CATALOG_PATH
    )
    catalog = load_model_catalog(catalog_path)
    configure_codex_catalog(catalog["models"])
    configure_claude_catalog(catalog["models"])
    return catalog

def migrate_legacy_data_dir(old_path: str, new_path: str):
    if old_path == new_path or os.path.exists(new_path) or not os.path.exists(old_path):
        return
    try:
        import shutil
        shutil.copytree(old_path, new_path)
        logging.info(f"Migrated legacy data directory from {old_path} to {new_path}")
    except Exception as e:
        logging.error(f"Failed to migrate legacy data directory from {old_path} to {new_path}: {e}")

migrate_legacy_data_dir(LEGACY_ANTIGRAVITY_DATA_DIR, ANTIGRAVITY_DATA_DIR)
migrate_legacy_data_dir(LEGACY_ANTIGRAVITY_CLI_DIR, ANTIGRAVITY_CLI_DIR)

# Default execution timeout for the agy CLI (seconds)
AGY_CLI_TIMEOUT = int(os.environ.get("AGY_CLI_TIMEOUT", "600"))
AGY_CLI_MAX_CAPTURE_CHARS = int(os.environ.get("AGY_CLI_MAX_CAPTURE_CHARS", "200000"))
AGY_RELOAD = os.environ.get("AGY_RELOAD", "0").lower() in ("1", "true", "yes", "on")

app = FastAPI(title="KookAI Workspace Chat Client")


TUNNEL_ALLOWED_EXACT_PATHS = {
    "/api/pair",
    "/api/models",
    "/api/projects",
    "/api/chat-history",
    "/api/chat",
    "/api/chat-tasks",
    "/api/upload-media",
    "/api/usage-limits",
    "/api/media",
}

TUNNEL_ALLOWED_PREFIXES = (
    "/api/conversation/",
    "/api/chat-tasks/",
)


def is_tunnel_host(host: str) -> bool:
    return "trycloudflare.com" in (host or "").lower()


def is_tunnel_allowed_path(path: str) -> bool:
    if path in TUNNEL_ALLOWED_EXACT_PATHS:
        return True
    return any(path.startswith(prefix) for prefix in TUNNEL_ALLOWED_PREFIXES)


_tunnel_block_page_cache = None


def get_tunnel_block_page() -> str:
    """Return a silent branded page for blocked tunnel web requests."""
    global _tunnel_block_page_cache
    if _tunnel_block_page_cache is not None:
        return _tunnel_block_page_cache

    icon_data_uri = ""
    icon_path = os.path.join(WORKSPACE_DIR, "static", "kookai-icon.png")
    try:
        with open(icon_path, "rb") as f:
            icon_data_uri = "data:image/png;base64," + base64.b64encode(f.read()).decode("ascii")
    except Exception as e:
        logging.warning(f"Failed to load tunnel block icon: {e}")

    _tunnel_block_page_cache = f'''<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="robots" content="noindex,nofollow">
  <style>
    html, body {{
      width: 100%;
      height: 100%;
      margin: 0;
      background: #0f172a;
    }}
    body {{
      display: flex;
      align-items: center;
      justify-content: center;
    }}
    img {{
      width: 96px;
      height: 96px;
      object-fit: contain;
      opacity: 0.92;
    }}
  </style>
</head>
<body>{f'<img src="{icon_data_uri}" alt="">' if icon_data_uri else ''}</body>
</html>'''
    return _tunnel_block_page_cache


@app.middleware("http")
async def block_web_client_from_tunnel(request: Request, call_next):
    """Expose Cloudflare Quick Tunnel to paired mobile API calls only."""
    host = request.headers.get("host", "")
    if is_tunnel_host(host) and not is_tunnel_allowed_path(request.url.path):
        response = HTMLResponse(content=get_tunnel_block_page(), status_code=404)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Robots-Tag"] = "noindex, nofollow"
        return response
    return await call_next(request)

# Ensure static directory exists
os.makedirs("static", exist_ok=True)

import socket
import threading
import random

# Persistent Host ID retrieval
def get_or_create_host_id():
    path = os.path.join(ANTIGRAVITY_DATA_DIR, "host_id.txt")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if os.path.exists(path):
        with open(path, "r") as f:
            return f.read().strip()
    host_id = f"host_{SYSTEM_USER}_{uuid.uuid4().hex[:12]}"
    with open(path, "w") as f:
        f.write(host_id)
    return host_id

# Global state for dynamic URL
public_url = ""
local_ip_addr = ""

def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 1))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"

# Worker dynamic registry URL. Keep the deployed worker hostname stable unless
# that Cloudflare Worker is renamed/deployed separately.
REGISTRY_WORKER_URL = os.environ.get("REGISTRY_WORKER_URL", "https://antigravity-pairing-broker.rangsarn.workers.dev")

def start_localtunnel():
    global public_url, local_ip_addr
    local_ip_addr = get_local_ip()
    host_id = get_or_create_host_id()
    
    cmd = ["npx", "wrangler", "tunnel", "quick-start", "http://localhost:8080"]
    logging.info("Starting Cloudflare Tunnel...")
    
    def run_tunnel():
        global public_url
        import time
        while True:
            try:
                logging.info("Launching Cloudflare Tunnel subprocess...")
                proc = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1,
                    shell=(os.name == 'nt')
                )
                for line in iter(proc.stdout.readline, ''):
                    logging.info(f"[Tunnel] {line.strip()}")
                    if "trycloudflare.com" in line:
                        url_match = re.search(r'https?://[^\s|]+trycloudflare\.com[^\s|]*', line)
                        if url_match:
                            raw_url = url_match.group(0).strip()
                            parsed = urllib.parse.urlparse(raw_url)
                            public_url = f"{parsed.scheme}://{parsed.netloc}"
                            logging.info(f"Cloudflare Tunnel started successfully! Public URL: {public_url}")
                            # Update Worker Registry with current local IP dynamically
                            update_registry(host_id, public_url, get_local_ip())
                    elif "your url is:" in line.lower():
                        url_match = re.search(r'https?://[^\s]+', line)
                        if url_match:
                            raw_url = url_match.group(0).strip()
                            parsed = urllib.parse.urlparse(raw_url)
                            public_url = f"{parsed.scheme}://{parsed.netloc}"
                            logging.info(f"Localtunnel started successfully! Public URL: {public_url}")
                            # Update Worker Registry with current local IP dynamically
                            update_registry(host_id, public_url, get_local_ip())
                return_code = proc.wait()
                logging.warning(f"Tunnel subprocess exited with code {return_code}. Restarting in 5 seconds...")
            except Exception as e:
                logging.error(f"Error running tunnel: {e}. Retrying in 5 seconds...")
            time.sleep(5)
        
    threading.Thread(target=run_tunnel, daemon=True).start()


def update_registry(host_id, url, local_ip):
    import urllib.request
    import json
    data = {
        "host_id": host_id,
        "url": url,
        "local_ip": local_ip
    }
    req = urllib.request.Request(
        f"{REGISTRY_WORKER_URL}/update-host",
        data=json.dumps(data).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        },
        method="POST"
    )
    import ssl
    context = ssl._create_unverified_context()
    try:
        with urllib.request.urlopen(req, timeout=5, context=context) as res:
            logging.info(f"Updated host URL on Worker Registry: {res.read().decode().strip()}")
    except Exception as e:
        logging.error(f"Failed to update registry: {e}")

def periodic_registry_update():
    import time
    global public_url
    last_registered_ip = ""
    last_registered_url = ""
    last_update_time = 0.0
    while True:
        try:
            current_ip = get_local_ip()
            now = time.time()
            # Force update registry if URL/IP changed, or at least once every 10 minutes (600s) to refresh TTL
            if public_url and (current_ip != last_registered_ip or public_url != last_registered_url or (now - last_update_time) > 600):
                host_id = get_or_create_host_id()
                update_registry(host_id, public_url, current_ip)
                last_registered_ip = current_ip
                last_registered_url = public_url
                last_update_time = now
        except Exception as e:
            logging.error(f"Error in periodic registry update: {e}")
        time.sleep(30)

# Global active pairing pins mapping: pin -> expiry
ACTIVE_PINS_FILE = os.path.join(ANTIGRAVITY_DATA_DIR, "active_pins.json")

def load_active_pins() -> dict:
    if os.path.exists(ACTIVE_PINS_FILE):
        try:
            with open(ACTIVE_PINS_FILE, "r") as f:
                return json.load(f)
        except:
            pass
    return {}

def save_active_pins(pins: dict):
    try:
        with open(ACTIVE_PINS_FILE, "w") as f:
            json.dump(pins, f)
    except Exception as e:
        logging.error(f"Failed to save active pins: {e}")

# Authorized devices (device_uuid -> device_name)
AUTHORIZED_DEVICES_FILE = os.path.join(ANTIGRAVITY_DATA_DIR, "authorized_devices.json")
authorized_devices = {}

if os.path.exists(AUTHORIZED_DEVICES_FILE):
    try:
        with open(AUTHORIZED_DEVICES_FILE, "r") as f:
            authorized_devices = json.load(f)
    except:
        pass

def save_authorized_devices():
    with open(AUTHORIZED_DEVICES_FILE, "w") as f:
        json.dump(authorized_devices, f)

# Helper to verify device authorization
def verify_authorization(request: Request):
    auth_header = request.headers.get("Authorization")
    token = None
    if auth_header and auth_header.startswith("Bearer "):
        token = auth_header.split(" ")[1]
    else:
        token = request.query_params.get("token")
        
    if token:
        for dev_uuid, dev_info in authorized_devices.items():
            if dev_info.get("token") == token:
                return True
        raise HTTPException(status_code=401, detail="Unauthorized device token")
    
    # Allow localhost requests without token
    client_host = request.client.host if request.client else ""
    if client_host in ["127.0.0.1", "localhost", "::1"]:
        return True

    
    raise HTTPException(status_code=401, detail="Missing or invalid authorization header")

class PairRequest(BaseModel):
    device_name: str
    pin: str
    device_uuid: str

@app.on_event("startup")
async def startup_event():
    catalog = load_runtime_model_catalog()
    logging.info(
        "Loaded model catalog %s with %s enabled models",
        catalog["catalog_version"],
        sum(1 for model in catalog["models"] if model["enabled"]),
    )
    requirements_path = os.path.join(WORKSPACE_DIR, "requirements.txt")
    cli_statuses = await asyncio.to_thread(
        auto_install_missing,
        requirements_path,
    )
    for cli_status in cli_statuses:
        log_method = logging.info if cli_status["installed"] else logging.warning
        log_method(
            "CLI requirement %s: %s%s",
            cli_status["id"],
            cli_status["status"],
            f" ({cli_status['message']})" if cli_status["message"] else "",
        )
    start_localtunnel()
    threading.Thread(target=periodic_registry_update, daemon=True).start()

@app.get("/api/pairing-code")
async def get_pairing_code():
    host_id = get_or_create_host_id()
    pin = f"{random.randint(100000, 999999)}"
    expiry = int(datetime.datetime.now().timestamp()) + 120
    active_pins = load_active_pins()
    active_pins[pin] = expiry
    save_active_pins(active_pins)
    
    # Register pin on worker KV
    import urllib.request
    import json
    host_url = public_url or f"http://{local_ip_addr}:8080"
    data = {
        "pin": pin,
        "host_id": host_id,
        "url": host_url,
        "local_ip": local_ip_addr
    }
    req = urllib.request.Request(
        f"{REGISTRY_WORKER_URL}/register-pin",
        data=json.dumps(data).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        },
        method="POST"
    )
    import ssl
    context = ssl._create_unverified_context()
    try:
        with urllib.request.urlopen(req, timeout=5, context=context) as res:
            logging.info(f"Registered pairing PIN {pin} on Worker Registry.")
    except Exception as e:
        logging.error(f"Failed to register pairing PIN: {e}")
        
    return JSONResponse(content={"pin": pin, "host_id": host_id, "pairing_url": host_url, "pairing_deep_link": f"kookai://pair?pin={pin}"})

@app.post("/api/pair")
async def pair_device(req: PairRequest):
    pin = req.pin.strip()
    now = int(datetime.datetime.now().timestamp())
    active_pins = load_active_pins()
    if pin not in active_pins or active_pins[pin] < now:
        raise HTTPException(status_code=403, detail="PIN expired or invalid")
        
    device_uuid = req.device_uuid
    token = uuid.uuid4().hex
    authorized_devices[device_uuid] = {
        "name": req.device_name,
        "paired_at": now,
        "token": token
    }
    save_authorized_devices()
    if pin in active_pins:
        del active_pins[pin]
    save_active_pins(active_pins)
    
    return JSONResponse(content={
        "status": "success",
        "token": token,
        "host_id": get_or_create_host_id()
    })


def can_manage_cli_connections(request: Request) -> bool:
    client_host = request.client.host if request.client else ""
    return client_host in {"127.0.0.1", "localhost", "::1"}


def verify_cli_admin(request: Request):
    if not can_manage_cli_connections(request):
        raise HTTPException(
            status_code=403,
            detail="Local access is required to manage CLI connections",
        )


@app.get("/api/cli/status")
async def get_cli_status(request: Request):
    verify_cli_admin(request)
    requirements_path = os.path.join(WORKSPACE_DIR, "requirements.txt")
    statuses = await asyncio.to_thread(
        get_cli_statuses,
        requirements_path,
    )
    return JSONResponse(
        content={
            "clis": statuses,
            "can_manage": True,
            "auto_install": os.environ.get(
                "KOOKAI_AUTO_INSTALL_CLIS",
                "1",
            ).lower()
            in {"1", "true", "yes", "on"},
        }
    )


@app.post("/api/cli/{cli_id}/install")
async def install_cli_requirement(cli_id: str, request: Request):
    verify_cli_admin(request)
    if cli_id not in {"agy", "claude", "codex"}:
        raise HTTPException(status_code=404, detail="Unknown CLI")
    status = await asyncio.to_thread(install_cli, cli_id)
    resolve_codex_executable.cache_clear()
    resolve_claude_executable.cache_clear()
    return JSONResponse(
        status_code=200 if status["installed"] else 500,
        content={"cli": status},
    )


@app.post("/api/cli/{cli_id}/connect")
async def connect_cli_account(cli_id: str, request: Request):
    verify_cli_admin(request)
    if cli_id not in {"agy", "claude", "codex"}:
        raise HTTPException(status_code=404, detail="Unknown CLI")

    statuses = {
        status["id"]: status
        for status in await asyncio.to_thread(
            get_cli_statuses,
            os.path.join(WORKSPACE_DIR, "requirements.txt"),
        )
    }
    status = statuses.get(cli_id)
    if not status or not status["installed"]:
        raise HTTPException(
            status_code=409,
            detail=f"{cli_id} is not installed. Install it before connecting.",
        )

    result = await asyncio.to_thread(
        launch_cli_login,
        cli_id,
        WORKSPACE_DIR,
    )
    return JSONResponse(
        status_code=200 if result["launched"] else 503,
        content=result,
    )


@app.get("/api/models")
async def get_models(request: Request, include_disabled: bool = False):
    verify_authorization(request)
    if include_disabled and not can_manage_cli_connections(request):
        raise HTTPException(
            status_code=403,
            detail="Local access is required to view disabled models",
        )
    try:
        catalog = load_runtime_model_catalog()
    except ModelCatalogError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return JSONResponse(
        content=public_model_catalog(
            catalog,
            include_disabled=include_disabled,
        )
    )


@app.put("/api/models")
async def update_models(request: Request):
    verify_cli_admin(request)
    try:
        payload = await request.json()
        catalog = save_model_catalog(MODEL_CATALOG_PATH, payload)
        configure_codex_catalog(catalog["models"])
        configure_claude_catalog(catalog["models"])
    except (ModelCatalogError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return JSONResponse(
        content={
            "status": "success",
            **public_model_catalog(catalog, include_disabled=True),
        }
    )


class ChatRequest(BaseModel):
    message: str
    model: str
    workspace: str
    target: str
    conversation_id: str
    provider: Optional[str] = None
    effort: Optional[str] = "Medium"
    speed: Optional[str] = "Standard"
    thinking: Optional[bool] = True


def resolve_chat_model(request: ChatRequest) -> dict:
    catalog = load_runtime_model_catalog()
    model = resolve_catalog_model(catalog, request.model)
    if not model:
        raise ValueError(
            f"Unknown or disabled model: {request.model}. Refresh the model catalog."
        )
    requested_provider = (request.provider or "").strip().lower()
    if requested_provider and requested_provider != model["provider"]:
        raise ValueError(
            f"Model {model['id']} must use the {model['provider']} provider"
        )
    return model


def verify_chat_model_request(request: ChatRequest) -> None:
    try:
        resolve_chat_model(request)
    except (ModelCatalogError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

# Temp UUID to actual conversation ID mapping
convo_id_mapping = {}

# In-memory session message cache (stores active tab sessions)
in_memory_chats = {}

# Persistent metadata/history for conversations started through Codex CLI.
CODEX_CONVERSATIONS_FILE = os.path.join(ANTIGRAVITY_DATA_DIR, "codex_conversations.json")
codex_conversations_lock = threading.Lock()
CLAUDE_CONVERSATIONS_FILE = os.path.join(ANTIGRAVITY_DATA_DIR, "claude_conversations.json")
claude_conversations_lock = threading.Lock()
CONVERSATION_METADATA_FILE = os.path.join(ANTIGRAVITY_DATA_DIR, "conversation_metadata.json")
conversation_metadata_lock = threading.Lock()

def _load_conversation_metadata() -> dict:
    if not os.path.exists(CONVERSATION_METADATA_FILE):
        return {}
    try:
        with open(CONVERSATION_METADATA_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception as e:
        logging.error(f"Failed to load conversation metadata: {e}")
        return {}

def _save_conversation_metadata(records: dict):
    os.makedirs(os.path.dirname(CONVERSATION_METADATA_FILE), exist_ok=True)
    temp_path = f"{CONVERSATION_METADATA_FILE}.tmp"
    with open(temp_path, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)
    os.replace(temp_path, CONVERSATION_METADATA_FILE)

def persist_conversation_metadata(
    conversation_id: str,
    project: str,
    model: str,
    provider: str,
    effort: Optional[str] = None,
    speed: Optional[str] = None,
    thinking: Optional[bool] = None,
):
    if not conversation_id:
        return
    now = datetime.datetime.now().timestamp()
    with conversation_metadata_lock:
        records = _load_conversation_metadata()
        existing = records.get(conversation_id, {})
        records[conversation_id] = {
            "id": conversation_id,
            "project": project or existing.get("project"),
            "model": model or existing.get("model"),
            "provider": provider or existing.get("provider", "agy"),
            "effort": effort if effort is not None else existing.get("effort"),
            "speed": speed if speed is not None else existing.get("speed"),
            "thinking": thinking if thinking is not None else existing.get("thinking"),
            "timestamp": now,
        }
        _save_conversation_metadata(records)


# Background chat task state for polling progress while agy is still running.
chat_tasks = {}
chat_tasks_lock = threading.Lock()

# Multi-step interview logic for /grill-me
interview_states = {} # conversation_id -> current_question_index

# Pending media uploads for the next message (actual_cid -> list of absolute file paths)
pending_media = {}

DEFAULT_INTERVIEW_QUESTIONS = [
    {
        "type": "question",
        "question": "Should we add a manual Light/Dark mode toggle switch to the web app, or should it continue to strictly follow your macOS system settings?",
        "options": [
            "(Recommended) Add a manual Light/Dark mode toggle switch in the UI (e.g. next to Settings or Header) for full user control.",
            "Keep the current behavior where the theme strictly follows the macOS system settings."
        ],
        "allow_other": True
    },
    {
        "type": "question",
        "question": "What type of transition animations would you prefer when navigation panels are switched or loaded?",
        "options": [
            "(Recommended) Smooth, premium slide-and-fade animations.",
            "Instant switching (no animations) for maximum speed and simplicity."
        ],
        "allow_other": True
    },
    {
        "type": "question",
        "question": "How would you like the sidebar list to organize nested conversations under each project?",
        "options": [
            "(Recommended) Display only the 5 most recent conversations, with a \"See all\" button.",
            "Show all conversations in a single scrollable list under each project folder."
        ],
        "allow_other": True
    }
]

# Mock seed conversations to match user screenshot layout on startup
SEED_CONVERSATIONS = [
    {
        "id": "mock-vo-1",
        "title": "การใช้งาน Obsidian ร่วมกับโปรเจกต์",
        "project": "VirtualOffice",
        "timestamp": 1782631546.0,
        "messages": [
            {"role": "user", "content": "ขอตัวอย่างการใช้งาน Obsidian ในโปรเจกต์นี้หน่อย"},
            {"role": "assistant", "content": "การใช้งาน Obsidian ร่วมกับโปรเจกต์มีขั้นตอนดังนี้ครับ:\n\n1. **ติดตั้ง Obsidian** และเปิดโฟลเดอร์คู่มือ\n2. **ใช้หน้าเทมเพลต** สำหรับบันทึกความคืบหน้างาน\n3. **สร้างลิงก์เชื่อมโยง** ไปยังไฟล์โครงสร้างในโครงการเพื่อความสะดวกรวดเร็ว"}
        ]
    },
    {
        "id": "mock-vo-2",
        "title": "Fixing Camera Zoom Bug",
        "project": "VirtualOffice",
        "timestamp": 1782631536.0,
        "messages": [
            {"role": "user", "content": "Camera zoom is bugged on Android device."},
            {"role": "assistant", "content": "Let's inspect the camera controller to fix the zoom bounds on Android."}
        ]
    },
    {
        "id": "mock-vo-3",
        "title": "### เปรียบเทียบแนวทางลดต้นทุน AI Agent",
        "project": "VirtualOffice",
        "timestamp": 1782631526.0,
        "messages": [
            {"role": "user", "content": "เปรียบเทียบแนวทางประหยัดงบสำหรับรัน AI Agent"},
            {"role": "assistant", "content": "แนวทางการลดต้นทุนรัน AI Agent:\n- **Caching**: เก็บผลการเรียกซ้ำ\n- **Model Routing**: เลือกใช้โมเดลเล็กสำหรับงานง่าย\n- **Token Truncation**: ควบคุมประวัติแชท"}
        ]
    },
    {
        "id": "mock-vo-4",
        "title": "Analyzing Risk Agent DeepSeek Requests",
        "project": "VirtualOffice",
        "timestamp": 1782631516.0,
        "messages": [
            {"role": "user", "content": "Analyze risk parameters for DeepSeek API requests"},
            {"role": "assistant", "content": "Analysis of DeepSeek API usage shows no token leaks. Recommended rate limits are set."}
        ]
    },
    {
        "id": "mock-vo-5",
        "title": "Rebacktesting Failed Strategies",
        "project": "VirtualOffice",
        "timestamp": 1782631506.0,
        "messages": []
    },
    {
        "id": "mock-vo-6",
        "title": "กด connect แล้วก็เงียบไปเลย",
        "project": "VirtualOffice",
        "timestamp": 1782631496.0,
        "messages": []
    },
    {
        "id": "mock-vo-7",
        "title": "Debugging Production Remote Desktop",
        "project": "VirtualOffice",
        "timestamp": 1782631486.0,
        "messages": []
    }
]


def _load_codex_conversation_records() -> dict:
    if not os.path.exists(CODEX_CONVERSATIONS_FILE):
        return {}
    try:
        with open(CODEX_CONVERSATIONS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception as e:
        logging.error(f"Failed to load Codex conversation history: {e}")
        return {}


def _save_codex_conversation_records(records: dict):
    os.makedirs(os.path.dirname(CODEX_CONVERSATIONS_FILE), exist_ok=True)
    temp_path = f"{CODEX_CONVERSATIONS_FILE}.tmp"
    with open(temp_path, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)
    os.replace(temp_path, CODEX_CONVERSATIONS_FILE)


def persist_codex_exchange(
    conversation_id: str,
    project: str,
    model: str,
    effort: str,
    speed: str,
    user_message: str,
    assistant_message: str,
):
    if not conversation_id.startswith(CODEX_CONVERSATION_PREFIX):
        return

    now = datetime.datetime.now().timestamp()
    with codex_conversations_lock:
        records = _load_codex_conversation_records()
        record = records.get(conversation_id, {})
        messages = record.get("messages")
        if not isinstance(messages, list):
            messages = []
        messages.extend([
            {"role": "user", "content": user_message},
            {"role": "assistant", "content": assistant_message},
        ])

        clean_title = re.sub(r"!\[.*?\]\(.*?\)", "", user_message).strip()
        if not clean_title:
            clean_title = "Codex conversation"
        if len(clean_title) > 40:
            clean_title = clean_title[:40] + "..."

        records[conversation_id] = {
            "id": conversation_id,
            "session_id": codex_session_id(conversation_id),
            "title": record.get("title") or clean_title,
            "project": project,
            "provider": "codex",
            "model": model,
            "effort": effort,
            "speed": speed,
            "timestamp": now,
            "messages": messages,
        }
        _save_codex_conversation_records(records)


def get_codex_conversations() -> List[dict]:
    with codex_conversations_lock:
        records = _load_codex_conversation_records()
    conversations = [value for value in records.values() if isinstance(value, dict)]
    conversations.sort(key=lambda item: item.get("timestamp", 0), reverse=True)
    return conversations


def get_codex_conversation(conversation_id: str) -> Optional[dict]:
    with codex_conversations_lock:
        record = _load_codex_conversation_records().get(conversation_id)
    return record if isinstance(record, dict) else None


def _load_claude_conversation_records() -> dict:
    if not os.path.exists(CLAUDE_CONVERSATIONS_FILE):
        return {}
    try:
        with open(CLAUDE_CONVERSATIONS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception as e:
        logging.error(f"Failed to load Claude conversation history: {e}")
        return {}


def _save_claude_conversation_records(records: dict):
    os.makedirs(os.path.dirname(CLAUDE_CONVERSATIONS_FILE), exist_ok=True)
    temp_path = f"{CLAUDE_CONVERSATIONS_FILE}.tmp"
    with open(temp_path, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)
    os.replace(temp_path, CLAUDE_CONVERSATIONS_FILE)


def persist_claude_exchange(
    conversation_id: str,
    project: str,
    model: str,
    effort: str,
    thinking: bool,
    user_message: str,
    assistant_message: str,
):
    if not conversation_id.startswith(CLAUDE_CONVERSATION_PREFIX):
        return

    now = datetime.datetime.now().timestamp()
    with claude_conversations_lock:
        records = _load_claude_conversation_records()
        record = records.get(conversation_id, {})
        messages = record.get("messages")
        if not isinstance(messages, list):
            messages = []
        messages.extend([
            {"role": "user", "content": user_message},
            {"role": "assistant", "content": assistant_message},
        ])

        clean_title = re.sub(r"!\[.*?\]\(.*?\)", "", user_message).strip()
        if not clean_title:
            clean_title = "Claude conversation"
        if len(clean_title) > 40:
            clean_title = clean_title[:40] + "..."

        records[conversation_id] = {
            "id": conversation_id,
            "session_id": claude_session_id(conversation_id),
            "title": record.get("title") or clean_title,
            "project": project,
            "provider": "claude",
            "model": model,
            "effort": effort,
            "thinking": thinking,
            "timestamp": now,
            "messages": messages,
        }
        _save_claude_conversation_records(records)


def get_claude_conversations() -> List[dict]:
    with claude_conversations_lock:
        records = _load_claude_conversation_records()
    conversations = [value for value in records.values() if isinstance(value, dict)]
    conversations.sort(key=lambda item: item.get("timestamp", 0), reverse=True)
    return conversations


def get_claude_conversation(conversation_id: str) -> Optional[dict]:
    with claude_conversations_lock:
        record = _load_claude_conversation_records().get(conversation_id)
    return record if isinstance(record, dict) else None


# Helper: Get all database file names (conversation IDs) in kookai folders
def get_existing_db_ids():
    db_paths = [
        os.path.join(ANTIGRAVITY_CLI_DIR, "conversations/*.db"),
        os.path.join(ANTIGRAVITY_DATA_DIR, "conversations/*.db")
    ]
    ids = set()
    for pattern in db_paths:
        for f in glob.glob(pattern):
            ids.add(os.path.basename(f)[:-3])
    return ids

# Helper: Resolve display name for projects
def clean_project_name(path_name: str) -> str:
    if path_name == "GinRaiD":
        return "GinRaiDee"
    return path_name

# Helper: Get list of projects on Desktop & Parent Workspace directory (Dynamic list of folders)
def get_desktop_projects():
    projects = ["agy", "VirtualOffice", "GinRaiDee", "HumanRelation"] # Default minimum set
    
    # 1. Scan the sibling directory (parent of workspace_dir)
    parent_dir = os.path.dirname(WORKSPACE_DIR)
    if os.path.exists(parent_dir):
        try:
            for entry in os.listdir(parent_dir):
                full_path = os.path.join(parent_dir, entry)
                if os.path.isdir(full_path) and not entry.startswith('.'):
                    cleaned = clean_project_name(entry)
                    if cleaned not in projects:
                        projects.append(cleaned)
        except Exception as e:
            logging.error(f"Error scanning parent project dir {parent_dir}: {e}")
            
    # 2. Scan Desktop path
    desktop_path = DESKTOP_DIR
    if os.path.exists(desktop_path):
        try:
            for entry in os.listdir(desktop_path):
                full_path = os.path.join(desktop_path, entry)
                if os.path.isdir(full_path) and not entry.startswith('.'):
                    cleaned = clean_project_name(entry)
                    if cleaned not in projects:
                        projects.append(cleaned)
        except Exception as e:
            logging.error(f"Error scanning desktop dir {desktop_path}: {e}")
            
    return projects

def resolve_project_directory(project_id: str) -> str:
    # 1. Check parent workspace directory (sibling projects)
    parent_dir = os.path.dirname(WORKSPACE_DIR)
    direct_path = os.path.join(parent_dir, project_id)
    if os.path.exists(direct_path) and os.path.isdir(direct_path):
        return direct_path
    if os.path.exists(parent_dir):
        for entry in os.listdir(parent_dir):
            full_path = os.path.join(parent_dir, entry)
            if os.path.isdir(full_path) and clean_project_name(entry) == project_id:
                return full_path

    # 2. Check Desktop directory
    desktop_path = DESKTOP_DIR
    direct_path = os.path.join(desktop_path, project_id)
    if os.path.exists(direct_path) and os.path.isdir(direct_path):
        return direct_path
    if os.path.exists(desktop_path):
        for entry in os.listdir(desktop_path):
            full_path = os.path.join(desktop_path, entry)
            if os.path.isdir(full_path) and clean_project_name(entry) == project_id:
                return full_path
                
    return WORKSPACE_DIR

def get_conversation_project(conversation_id: str) -> Optional[str]:
    hist_paths = [
        os.path.join(ANTIGRAVITY_CLI_DIR, "history.jsonl"),
        os.path.join(ANTIGRAVITY_DATA_DIR, "history.jsonl")
    ]
    for hist_path in hist_paths:
        if not os.path.exists(hist_path):
            continue
        try:
            with open(hist_path, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    try:
                        data = json.loads(line.strip())
                        if data.get("conversationId") == conversation_id:
                            workspace_path = data.get("workspace", "")
                            if workspace_path:
                                return clean_project_name(os.path.basename(workspace_path))
                    except:
                        pass
        except:
            pass
    return None

def infer_project_from_conversation_artifacts(folder: str) -> Optional[str]:
    desktop_prefix = DESKTOP_DIR + os.sep
    candidates = {}
    artifact_patterns = [
        os.path.join(folder, ".system_generated/tasks/*.log"),
        os.path.join(folder, ".system_generated/messages/*.json"),
    ]

    for pattern in artifact_patterns:
        for artifact_path in glob.glob(pattern):
            try:
                with open(artifact_path, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read()
            except Exception:
                continue

            pattern = rf"(?:/Users/[^/]+/Desktop/|{re.escape(DESKTOP_DIR)}/)([A-Za-z0-9._ -]+)"
            for match in re.finditer(pattern, content):
                raw_name = match.group(1).split("/")[0].strip()
                if not raw_name or raw_name.startswith("."):
                    continue
                project = clean_project_name(raw_name)
                candidates[project] = candidates.get(project, 0) + 1

    if not candidates:
        return None
    return max(candidates.items(), key=lambda item: item[1])[0]

# Helper: Parse local conversation transcripts from brain folders
def get_real_conversations():
    brain_paths = [
        os.path.join(ANTIGRAVITY_CLI_DIR, "brain/*"),
        os.path.join(ANTIGRAVITY_DATA_DIR, "brain/*")
    ]
    
    # Map conversationId -> project using history.jsonl if possible
    cid_to_project = {}
    hist_paths = [
        os.path.join(ANTIGRAVITY_CLI_DIR, "history.jsonl"),
        os.path.join(ANTIGRAVITY_DATA_DIR, "history.jsonl")
    ]
    for hist_path in hist_paths:
        if os.path.exists(hist_path):
            with open(hist_path, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    try:
                        data = json.loads(line.strip())
                        cid = data.get("conversationId")
                        workspace = data.get("workspace", "")
                        if cid and workspace:
                            pname = os.path.basename(workspace)
                            cid_to_project[cid] = clean_project_name(pname)
                    except:
                        pass

    meta_records = _load_conversation_metadata()
    conversations = []
    
    for path_pattern in brain_paths:
        for folder in glob.glob(path_pattern):
            cid = os.path.basename(folder)
            transcript_path = os.path.join(folder, ".system_generated/logs/transcript_full.jsonl")
            if not os.path.exists(transcript_path):
                transcript_path = os.path.join(folder, ".system_generated/logs/transcript.jsonl")
            if not os.path.exists(transcript_path):
                continue
                
            # Scan media folder artifacts for this conversation
            media_files = []
            transcript_project = None
            for fpath in glob.glob(os.path.join(folder, "media__*")):
                try:
                    ts_part = os.path.basename(fpath).split("__")[1].split(".")[0]
                    media_files.append((fpath, float(ts_part) / 1000.0))
                except:
                    pass
            media_files.sort(key=lambda x: x[1])

            messages = []
            try:
                mtime = os.path.getmtime(transcript_path)
                prev_user_ts = 0.0
                with open(transcript_path, "r", encoding="utf-8") as f:
                    for line in f:
                        try:
                            step = json.loads(line.strip())
                            stype = step.get("type")
                            scontent = step.get("content", "")
                            
                            if stype == "USER_INPUT" and scontent:
                                created_str = step.get("created_at")
                                try:
                                    dt = datetime.datetime.strptime(created_str, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=datetime.timezone.utc)
                                    ts = dt.timestamp()
                                except:
                                    ts = mtime
                                
                                # Match media files by timestamp correlation
                                step_media = []
                                for mpath, mts in media_files:
                                    if prev_user_ts < mts <= (ts + 10.0):
                                        step_media.append(mpath)
                                
                                match = re.search(r"<USER_REQUEST>\s*(.*?)\s*</USER_REQUEST>", scontent, re.DOTALL)
                                prompt = match.group(1).strip() if match else scontent.strip()
                                context_match = re.match(
                                    r"Selected KookAI project/workspace:\s*(.*?)\n"
                                    r"Workspace directory:\s*(.*?)\n\n"
                                    r"User message:\n(.*)\Z",
                                    prompt,
                                    re.DOTALL
                                )
                                if context_match:
                                    transcript_project = clean_project_name(context_match.group(1).strip())
                                    prompt = context_match.group(3).strip()
                                
                                media_md = ""
                                if step_media:
                                    media_md = "\n".join([f"![Attached Image](file://{p})" for p in step_media]) + "\n\n"
                                    
                                messages.append({
                                    "role": "user", 
                                    "content": media_md + prompt
                                })
                                prev_user_ts = ts
                            elif stype == "PLANNER_RESPONSE" and scontent:
                                messages.append({"role": "assistant", "content": scontent.strip()})
                        except:
                            pass
                
                if messages:
                    # Strip markdown tags to form title if needed
                    raw_title = messages[0]["content"]
                    # If it starts with images, strip them for the sidebar title preview
                    clean_title = re.sub(r"!\[.*?\]\(.*?\)", "", raw_title).strip()
                    if not clean_title:
                        clean_title = "Image Attachment"
                    if len(clean_title) > 40:
                        clean_title = clean_title[:40] + "..."
                        
                    project = (
                        transcript_project
                        or infer_project_from_conversation_artifacts(folder)
                        or cid_to_project.get(cid, "agy")
                    )
                    
                    # Only show user-initiated conversations in the sidebar (filter out subagent runs)
                    is_user_convo = (transcript_project is not None) or (cid in cid_to_project)
                    if not is_user_convo:
                        continue
                    
                    meta = meta_records.get(cid, {})
                    conversations.append({
                        "id": cid,
                        "title": clean_title,
                        "project": project,
                        "timestamp": mtime,
                        "messages": messages,
                        "model": meta.get("model"),
                        "provider": meta.get("provider", "agy"),
                        "effort": meta.get("effort"),
                        "speed": meta.get("speed"),
                        "thinking": meta.get("thinking"),
                    })
            except Exception as e:
                logging.error(f"Error parsing conversation {cid}: {e}")
                
    conversations.sort(key=lambda x: x["timestamp"], reverse=True)
    return conversations

# Map model string to agy supported string
def map_model_name(model_ui_name: str) -> str:
    catalog = load_runtime_model_catalog()
    model = resolve_catalog_model(catalog, model_ui_name)
    if not model:
        raise ValueError(f"Unknown or disabled model: {model_ui_name}")
    return model["cli_model"]

# Helper: Kill processes locking the sqlite database or executing agy for this conversation
def kill_processes_locking_db(conversation_id: str):
    db_files = [
        os.path.join(ANTIGRAVITY_DATA_DIR, f"conversations/{conversation_id}.db"),
        os.path.join(ANTIGRAVITY_CLI_DIR, f"conversations/{conversation_id}.db")
    ]
    for db_path in db_files:
        if not os.path.exists(db_path):
            continue
        try:
            # 1. Kill via lsof
            res = subprocess.run(["lsof", "-t", db_path], capture_output=True, text=True, timeout=5)
            if res.returncode == 0:
                pids = res.stdout.strip().split()
                for pid_str in pids:
                    try:
                        pid = int(pid_str)
                        if pid != os.getpid():
                            logging.info(f"Killing process {pid} locking database {db_path}")
                            os.kill(pid, 9)
                    except Exception as e:
                        logging.error(f"Failed to kill locking process {pid_str}: {e}")
        except Exception as e:
            logging.error(f"Error running lsof for DB {db_path}: {e}")
            
    # 2. Kill via ps scan for agy CLI processes containing conversation ID
    try:
        ps_res = subprocess.run(["ps", "-ef"], capture_output=True, text=True, timeout=5)
        if ps_res.returncode == 0:
            for line in ps_res.stdout.splitlines():
                if "agy" in line and conversation_id in line:
                    parts = line.strip().split()
                    if len(parts) >= 2:
                        try:
                            pid = int(parts[1])
                            if pid != os.getpid():
                                logging.info(f"Killing matching agy process {pid} from ps output: {line}")
                                os.kill(pid, 9)
                        except Exception as e:
                            pass
    except Exception as e:
        logging.error(f"Error running ps to scan for agy processes: {e}")
# Helper: Run agy with conversation ID
def classify_cli_progress_line(source: str, line: str):
    # Strip ANSI escape sequences (like colors and cursor movements)
    ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
    clean = ansi_escape.sub('', line or "").strip()
    if not clean:
        return None

    # Limit line length to keep UI clean and prevent payload bloat
    if len(clean) > 150:
        clean = clean[:147] + "..."

    lower = clean.lower()
    error_terms = (
        "error", "failed", "failure", "exception", "traceback", "timeout",
        "denied", "unauthorized", "forbidden", "not found", "locked",
        "invalid", "cannot", "could not", "warning", "warn"
    )

    if any(term in lower for term in error_terms):
        return {"type": "error", "message": clean}
        
    return {"type": "progress", "message": clean}


def run_agent_command(
    cmd,
    cwd_path,
    timeout=AGY_CLI_TIMEOUT,
    progress_callback=None,
    progress_line_classifier=classify_cli_progress_line,
    raw_line_callback=None,
    stdin_text=None,
    env=None,
):
    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE if stdin_text is not None else subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
        cwd=cwd_path,
        env=env,
        **hidden_subprocess_kwargs(),
    )
    output_queue = queue.Queue()
    stdout_capture = {"chunks": deque(), "chars": 0, "total": 0, "truncated": False}
    stderr_capture = {"chunks": deque(), "chars": 0, "total": 0, "truncated": False}

    def append_capture(capture, line):
        original_len = len(line)
        if original_len > AGY_CLI_MAX_CAPTURE_CHARS:
            line = line[-AGY_CLI_MAX_CAPTURE_CHARS:]
            capture["truncated"] = True
        capture["chunks"].append(line)
        capture["chars"] += len(line)
        capture["total"] += original_len
        while capture["chars"] > AGY_CLI_MAX_CAPTURE_CHARS and capture["chunks"]:
            removed = capture["chunks"].popleft()
            capture["chars"] -= len(removed)
            capture["truncated"] = True

    def capture_text(capture):
        text = "".join(capture["chunks"])
        if capture["truncated"]:
            return (
                f"[... output truncated to last {AGY_CLI_MAX_CAPTURE_CHARS} chars "
                f"from {capture['total']} chars ...]\n{text}"
            )
        return text

    def reader(pipe, source, capture):
        try:
            for line in iter(pipe.readline, ""):
                append_capture(capture, line)
                if raw_line_callback:
                    try:
                        raw_line_callback(source, line.rstrip("\n"))
                    except Exception as e:
                        logging.debug(f"Raw CLI line callback failed: {e}")
                output_queue.put((source, line.rstrip("\n")))
        finally:
            pipe.close()

    stdout_thread = threading.Thread(target=reader, args=(proc.stdout, "stdout", stdout_capture), daemon=True)
    stderr_thread = threading.Thread(target=reader, args=(proc.stderr, "stderr", stderr_capture), daemon=True)
    stdout_thread.start()
    stderr_thread.start()

    if stdin_text is not None and proc.stdin:
        def write_stdin():
            try:
                proc.stdin.write(stdin_text)
            except (BrokenPipeError, OSError):
                pass
            finally:
                try:
                    proc.stdin.close()
                except OSError:
                    pass

        threading.Thread(target=write_stdin, daemon=True).start()

    start_time = datetime.datetime.now().timestamp()
    while proc.poll() is None or not output_queue.empty():
        try:
            source, line = output_queue.get(timeout=0.2)
            event = progress_line_classifier(source, line)
            if event and progress_callback:
                progress_callback(event["type"], event["message"])
        except queue.Empty:
            pass

        if proc.poll() is None and datetime.datetime.now().timestamp() - start_time > timeout:
            proc.kill()
            stdout_thread.join(timeout=1)
            stderr_thread.join(timeout=1)
            raise subprocess.TimeoutExpired(
                cmd,
                timeout,
                output=capture_text(stdout_capture),
                stderr=capture_text(stderr_capture)
            )

    stdout_thread.join(timeout=1)
    stderr_thread.join(timeout=1)

    while not output_queue.empty():
        source, line = output_queue.get()
        event = progress_line_classifier(source, line)
        if event and progress_callback:
            progress_callback(event["type"], event["message"])

    return subprocess.CompletedProcess(
        cmd,
        proc.returncode,
        stdout=capture_text(stdout_capture),
        stderr=capture_text(stderr_capture)
    )


def run_agy_command(cmd, cwd_path, timeout=AGY_CLI_TIMEOUT, progress_callback=None):
    return run_agent_command(
        cmd,
        cwd_path,
        timeout=timeout,
        progress_callback=progress_callback,
        progress_line_classifier=classify_cli_progress_line,
    )

def run_agy_cli(message: str, model_ui_name: str, conversation_id: str, target: str = "Sandbox", workspace: str = "agy", progress_callback=None):
    mapped_model = map_model_name(model_ui_name)
    project_id = clean_project_name(os.path.basename(workspace or "agy"))
    cwd_path = resolve_project_directory(project_id)
    message_with_context = (
        f"Selected KookAI project/workspace: {project_id}\n"
        f"Workspace directory: {cwd_path}\n\n"
        f"User message:\n{message}"
    )

    def command_output(result):
        return "\n".join(part for part in [
            (result.stderr or "").strip(),
            (result.stdout or "").strip()
        ] if part)

    def is_recoverable_conversation_error(result):
        output = command_output(result).lower()
        return (
            "trajectory not found" in output
            or "failed to send message" in output
            or "conversation not found" in output
            or "database is locked" in output
            or "locked" in output
        )
    
    # Resolve temporary frontend ID if mapped
    mapping_key = f"{project_id}:{conversation_id}"
    actual_cid = convo_id_mapping.get(mapping_key, conversation_id)
    
    # Get current DB list before running command
    before_dbs = get_existing_db_ids()
    
    # Decide if we continue an existing conversation
    use_continue = actual_cid in before_dbs
    if use_continue:
        existing_project = get_conversation_project(actual_cid)
        if existing_project and existing_project != project_id:
            logging.info(f"Conversation {actual_cid} belongs to {existing_project}; starting new conversation in {project_id}.")
            use_continue = False

    agy_path = (
        resolve_managed_cli_executable("agy")
        or os.path.expanduser("~/.local/bin/agy")
    )

    cmd = [
        agy_path, "--print", message_with_context,
        "--dangerously-skip-permissions",
        "--model", mapped_model,
        "--project", project_id,
        "--add-dir", cwd_path
    ]
    
    # Apply local sandbox constraint
    if target.lower() in ["local", "local sandbox", "sandbox"]:
        cmd.append("--sandbox")
        
    if use_continue:
        cmd += ["--conversation", actual_cid, "--continue"]
    else:
        # If frontend sent an ID but it is not in the db, let agy generate one
        pass
        
    logging.info(f"Executing agy CLI in {cwd_path}: {' '.join(cmd)}")
    
    try:
        result = run_agy_command(cmd, cwd_path, timeout=AGY_CLI_TIMEOUT, progress_callback=progress_callback)
        
        # Check stderr and stdout; agy can report conversation failures with exit code 0.
        if result.returncode != 0 or is_recoverable_conversation_error(result):
            err_msg = command_output(result) or "Unknown error"
            if is_recoverable_conversation_error(result):
                logging.info(f"Trajectory {actual_cid} locked or not found. Attempting to kill locking processes...")
                kill_processes_locking_db(actual_cid)
                
                # Wait 500ms for lock to clear
                import time
                time.sleep(0.5)
                
                logging.info(f"Retrying command after killing locking processes: {' '.join(cmd)}")
                if progress_callback:
                    progress_callback("progress", "Retrying after clearing conversation lock.")
                result = run_agy_command(cmd, cwd_path, timeout=AGY_CLI_TIMEOUT, progress_callback=progress_callback)

                # If it STILL fails after killing, do fallback to a new conversation
                if result.returncode != 0 or is_recoverable_conversation_error(result):
                    err_msg = command_output(result) or "Unknown error"
                    logging.info(f"Retry failed: {err_msg}. Falling back to a new conversation.")
                    fallback_cmd = []
                    skip_next = False
                    for token in cmd:
                        if skip_next:
                            skip_next = False
                            continue
                        if token == "--conversation":
                            skip_next = True
                            continue
                        if token == "--continue" or token == "-c":
                            continue
                        fallback_cmd.append(token)

                    logging.info(f"Executing fallback agy CLI in {cwd_path}: {' '.join(fallback_cmd)}")
                    if progress_callback:
                        progress_callback("progress", "Starting a fresh conversation after retry failed.")
                    result = run_agy_command(fallback_cmd, cwd_path, timeout=AGY_CLI_TIMEOUT, progress_callback=progress_callback)
                    use_continue = False # We've started a new conversation
        
        # Scan for new DB ID if we started a new conversation
        resolved_cid = actual_cid if use_continue else conversation_id
        if not use_continue:
            after_dbs = get_existing_db_ids()
            new_ids = after_dbs - before_dbs
            if new_ids:
                resolved_cid = list(new_ids)[0]
                convo_id_mapping[mapping_key] = resolved_cid
                logging.info(f"Resolved new conversation ID mapping: {mapping_key} -> {resolved_cid}")
        
        if result.returncode == 0 and not is_recoverable_conversation_error(result):
            return result.stdout.strip(), resolved_cid
        else:
            err_msg = command_output(result) or "Unknown error"
            return f"⚠️ **agy CLI Error (Exit Code {result.returncode})**\n\n```\n{err_msg}\n```", resolved_cid
            
    except subprocess.TimeoutExpired:
        return f"⏱️ **Timeout Error**: The request to `agy` CLI exceeded the {AGY_CLI_TIMEOUT}-second limit.", actual_cid
    except Exception as e:
        return f"❌ **Execution Error**: Failed to run `agy` CLI. Details: `{str(e)}`", actual_cid

def run_codex_cli(
    message: str,
    model_ui_name: str,
    conversation_id: str,
    target: str = "Sandbox",
    workspace: str = "agy",
    effort: str = "Medium",
    speed: str = "Standard",
    image_paths: Optional[List[str]] = None,
    progress_callback=None,
):
    project_id = clean_project_name(os.path.basename(workspace or "agy"))
    cwd_path = resolve_project_directory(project_id)
    mapping_key = f"codex:{project_id}:{conversation_id}"
    actual_cid = convo_id_mapping.get(mapping_key, conversation_id)
    effort_display, _ = normalize_codex_effort(effort, model_ui_name)
    speed_display, _ = normalize_codex_speed(speed, model_ui_name)

    message_with_context = (
        f"Selected project/workspace: {project_id}\n"
        f"Workspace directory: {cwd_path}\n\n"
        f"User message:\n{message}"
    )
    if effort_display == "Ultra":
        message_with_context = (
            "[EXECUTION MODE: ULTRA]\n"
            "Use subagents for independent work that can run in parallel, then integrate and verify "
            "their results before answering. Do not spawn subagents for trivial work.\n\n"
            + message_with_context
        )

    def execute(run_conversation_id: Optional[str]):
        stream_result = {"session_id": None, "final_message": "", "errors": []}

        def capture_codex_line(source: str, line: str):
            if source != "stdout":
                return
            parsed_line = parse_codex_jsonl(line)
            if parsed_line["session_id"]:
                stream_result["session_id"] = parsed_line["session_id"]
            if parsed_line["final_message"]:
                stream_result["final_message"] = parsed_line["final_message"]
            if parsed_line["errors"]:
                stream_result["errors"].extend(parsed_line["errors"])

        codex_path = resolve_codex_executable()
        cmd = build_codex_command(
            codex_path=codex_path,
            prompt=message_with_context,
            model_name=model_ui_name,
            effort=effort_display,
            speed=speed_display,
            target=target,
            conversation_id=run_conversation_id,
            image_paths=image_paths,
        )
        logging.info(
            "Executing Codex CLI in %s with model=%s effort=%s speed=%s target=%s resume=%s",
            cwd_path,
            model_ui_name,
            effort_display,
            speed_display,
            target,
            bool(codex_session_id(run_conversation_id)),
        )
        result = run_agent_command(
            cmd,
            cwd_path,
            timeout=AGY_CLI_TIMEOUT,
            progress_callback=progress_callback,
            progress_line_classifier=classify_codex_progress_line,
            raw_line_callback=capture_codex_line,
            stdin_text=message_with_context,
        )
        parsed = parse_codex_jsonl(result.stdout or "")
        return result, {
            "session_id": stream_result["session_id"] or parsed["session_id"],
            "final_message": stream_result["final_message"] or parsed["final_message"],
            "errors": stream_result["errors"] or parsed["errors"],
        }

    try:
        result, parsed = execute(actual_cid)
        combined_error = "\n".join(
            part
            for part in [
                (result.stderr or "").strip(),
                "\n".join(parsed["errors"]).strip(),
            ]
            if part
        )
        recoverable_resume_error = codex_session_id(actual_cid) and any(
            phrase in combined_error.lower()
            for phrase in (
                "session not found",
                "thread not found",
                "failed to resume",
                "unable to resume",
                "no rollout found",
            )
        )
        if result.returncode != 0 and recoverable_resume_error:
            if progress_callback:
                progress_callback("progress", "Codex session was unavailable; starting a fresh session.")
            result, parsed = execute(None)
            combined_error = "\n".join(
                part
                for part in [
                    (result.stderr or "").strip(),
                    "\n".join(parsed["errors"]).strip(),
                ]
                if part
            )

        session_id = parsed["session_id"]
        resolved_cid = make_codex_conversation_id(session_id) if session_id else actual_cid
        if resolved_cid != conversation_id:
            convo_id_mapping[mapping_key] = resolved_cid

        if result.returncode == 0 and parsed["final_message"]:
            return parsed["final_message"].strip(), resolved_cid

        error_message = combined_error or "Codex CLI did not return a final response."
        return (
            f"⚠️ **Codex CLI Error (Exit Code {result.returncode})**\n\n"
            f"```\n{error_message}\n```",
            resolved_cid,
        )
    except subprocess.TimeoutExpired:
        return (
            f"⏱️ **Timeout Error**: The request to `codex` CLI exceeded "
            f"the {AGY_CLI_TIMEOUT}-second limit.",
            actual_cid,
        )
    except Exception as e:
        return (
            "❌ **Execution Error**: Failed to run `codex` CLI. "
            f"Install/authenticate Codex or set `CODEX_CLI_PATH`. Details: `{str(e)}`",
            actual_cid,
        )


def run_claude_cli(
    message: str,
    model_ui_name: str,
    conversation_id: str,
    target: str = "Sandbox",
    workspace: str = "agy",
    effort: str = "Medium",
    thinking: bool = True,
    progress_callback=None,
):
    project_id = clean_project_name(os.path.basename(workspace or "agy"))
    cwd_path = resolve_project_directory(project_id)
    mapping_key = f"claude:{project_id}:{conversation_id}"
    actual_cid = convo_id_mapping.get(mapping_key, conversation_id)
    effort_display, _ = normalize_claude_effort(effort, model_ui_name)
    message_with_context = (
        f"Selected project/workspace: {project_id}\n"
        f"Workspace directory: {cwd_path}\n\n"
        f"User message:\n{message}"
    )

    def execute(run_conversation_id: Optional[str]):
        stream_result = {"session_id": None, "final_message": "", "errors": []}

        def capture_claude_line(source: str, line: str):
            if source != "stdout":
                return
            parsed_line = parse_claude_stream_json(line)
            if parsed_line["session_id"]:
                stream_result["session_id"] = parsed_line["session_id"]
            if parsed_line["final_message"]:
                stream_result["final_message"] = parsed_line["final_message"]
            if parsed_line["errors"]:
                stream_result["errors"].extend(parsed_line["errors"])

        cmd = build_claude_command(
            claude_path=resolve_claude_executable(),
            prompt=message_with_context,
            model_name=model_ui_name,
            effort=effort_display,
            target=target,
            conversation_id=run_conversation_id,
        )
        logging.info(
            "Executing Claude CLI in %s with model=%s effort=%s thinking=%s target=%s resume=%s",
            cwd_path,
            model_ui_name,
            effort_display,
            thinking,
            target,
            bool(claude_session_id(run_conversation_id)),
        )
        result = run_agent_command(
            cmd,
            cwd_path,
            timeout=AGY_CLI_TIMEOUT,
            progress_callback=progress_callback,
            progress_line_classifier=classify_claude_progress_line,
            raw_line_callback=capture_claude_line,
            stdin_text=message_with_context,
            env=build_claude_environment(thinking),
        )
        parsed = parse_claude_stream_json(result.stdout or "")
        return result, {
            "session_id": stream_result["session_id"] or parsed["session_id"],
            "final_message": stream_result["final_message"] or parsed["final_message"],
            "errors": stream_result["errors"] or parsed["errors"],
        }

    try:
        result, parsed = execute(actual_cid)
        combined_error = "\n".join(
            part
            for part in [
                (result.stderr or "").strip(),
                "\n".join(parsed["errors"]).strip(),
            ]
            if part
        )
        recoverable_resume_error = claude_session_id(actual_cid) and any(
            phrase in combined_error.lower()
            for phrase in (
                "session not found",
                "no conversation found",
                "failed to resume",
                "unable to resume",
            )
        )
        if result.returncode != 0 and recoverable_resume_error:
            if progress_callback:
                progress_callback("progress", "Claude session was unavailable; starting a fresh session.")
            result, parsed = execute(None)
            combined_error = "\n".join(
                part
                for part in [
                    (result.stderr or "").strip(),
                    "\n".join(parsed["errors"]).strip(),
                ]
                if part
            )

        session_id = parsed["session_id"]
        resolved_cid = make_claude_conversation_id(session_id) if session_id else actual_cid
        if resolved_cid != conversation_id:
            convo_id_mapping[mapping_key] = resolved_cid

        if result.returncode == 0 and parsed["final_message"] and not parsed["errors"]:
            return parsed["final_message"].strip(), resolved_cid

        error_message = combined_error or "Claude CLI did not return a final response."
        return (
            f"⚠️ **Claude CLI Error (Exit Code {result.returncode})**\n\n"
            f"```\n{error_message}\n```",
            resolved_cid,
        )
    except subprocess.TimeoutExpired:
        return (
            f"⏱️ **Timeout Error**: The request to `claude` CLI exceeded "
            f"the {AGY_CLI_TIMEOUT}-second limit.",
            actual_cid,
        )
    except Exception as e:
        return (
            "❌ **Execution Error**: Failed to run `claude` CLI. "
            f"Install/authenticate Claude Code or set `CLAUDE_CLI_PATH`. Details: `{str(e)}`",
            actual_cid,
        )


def run_selected_cli(
    message: str,
    model_ui_name: str,
    conversation_id: str,
    target: str,
    workspace: str,
    provider: Optional[str] = None,
    effort: str = "Medium",
    speed: str = "Standard",
    thinking: bool = True,
    image_paths: Optional[List[str]] = None,
    progress_callback=None,
):
    selected_provider = (provider or "").strip().lower()
    if not selected_provider:
        selected_provider = resolve_provider(None, model_ui_name)
    if selected_provider not in {"agy", "codex", "claude"}:
        raise ValueError(f"Unsupported agent provider: {provider}")
    if selected_provider == "codex":
        return run_codex_cli(
            message,
            model_ui_name,
            conversation_id,
            target,
            workspace,
            effort,
            speed,
            image_paths,
            progress_callback,
        )
    if selected_provider == "claude":
        return run_claude_cli(
            message,
            model_ui_name,
            conversation_id,
            target,
            workspace,
            effort,
            thinking,
            progress_callback,
        )
    return run_agy_cli(
        message,
        model_ui_name,
        conversation_id,
        target,
        workspace,
        progress_callback,
    )


# --- Endpoints ---

@app.get("/api/files")
async def get_files(request: Request):
    verify_authorization(request)
    files = []
    workspace_path = WORKSPACE_DIR
    if os.path.exists(workspace_path):
        for root, dirs, filenames in os.walk(workspace_path):
            dirs[:] = [d for d in dirs if not d.startswith('.')]
            for f in filenames:
                if f.startswith('.'):
                    continue
                full_path = os.path.join(root, f)
                rel_path = os.path.relpath(full_path, workspace_path)
                try:
                    size_bytes = os.path.getsize(full_path)
                    size_label = f"{size_bytes} B"
                    if size_bytes > 1024 * 1024:
                        size_label = f"{size_bytes / (1024*1024):.1f} MB"
                    elif size_bytes > 1024:
                        size_label = f"{size_bytes / 1024:.1f} KB"
                except:
                    size_label = "0 B"
                ext = os.path.splitext(f)[1]
                files.append({
                    "name": rel_path,
                    "type": ext.upper()[1:] if ext else "FILE",
                    "size": size_label
                })
    return JSONResponse(content={"files": files})

@app.get("/api/projects")
async def get_projects(request: Request):
    verify_authorization(request)
    projects = get_desktop_projects()
    return JSONResponse(content={"projects": projects, "workspace_dir": WORKSPACE_DIR})

@app.get("/api/conversations")
async def get_conversations(request: Request, project: Optional[str] = None):
    verify_authorization(request)
    real_convos = get_real_conversations()
    for convo in real_convos:
        convo.setdefault("provider", "agy")
    codex_convos = get_codex_conversations()
    claude_convos = get_claude_conversations()
    merged = list(real_convos) + codex_convos + claude_convos
    seen_ids = {c["id"] for c in merged}
    for c in SEED_CONVERSATIONS:
        if c["id"] not in seen_ids:
            merged.append({**c, "provider": "agy"})
            
    # Filter by project if supplied
    if project:
        merged = [c for c in merged if c["project"] == project]
        
    # Sort all by last modified time to match /api/chat-history
    merged.sort(key=lambda x: x.get("timestamp", 0), reverse=True)
    return JSONResponse(content={"conversations": merged})

@app.get("/api/chat-history")
async def get_chat_history(request: Request):
    verify_authorization(request)
    real_convos = get_real_conversations()
    for convo in real_convos:
        convo.setdefault("provider", "agy")
    codex_convos = get_codex_conversations()
    claude_convos = get_claude_conversations()
    merged = list(real_convos) + codex_convos + claude_convos
    seen_ids = {c["id"] for c in merged}
    for c in SEED_CONVERSATIONS:
        if c["id"] not in seen_ids:
            merged.append({**c, "provider": "agy"})
            
    # Sort all by last modified time
    merged.sort(key=lambda x: x.get("timestamp", 0), reverse=True)
    return JSONResponse(content={"conversations": merged})

@app.get("/api/conversation/{cid}")
async def get_conversation_details(cid: str, request: Request):
    verify_authorization(request)
    messages = []
    project = None
    provider = "agy"
    model = None
    effort = None
    speed = None
    thinking = None
    codex_record = get_codex_conversation(cid)
    claude_record = get_claude_conversation(cid)

    # First check memory cache
    if cid in in_memory_chats:
        messages = in_memory_chats[cid]
        if codex_record:
            project = codex_record.get("project")
            provider = "codex"
            model = codex_record.get("model")
            effort = codex_record.get("effort")
            speed = codex_record.get("speed")
        elif claude_record:
            project = claude_record.get("project")
            provider = "claude"
            model = claude_record.get("model")
            effort = claude_record.get("effort")
            thinking = claude_record.get("thinking", True)
    elif codex_record:
        messages = codex_record.get("messages", [])
        project = codex_record.get("project")
        provider = "codex"
        model = codex_record.get("model")
        effort = codex_record.get("effort")
        speed = codex_record.get("speed")
        in_memory_chats[cid] = messages
    elif claude_record:
        messages = claude_record.get("messages", [])
        project = claude_record.get("project")
        provider = "claude"
        model = claude_record.get("model")
        effort = claude_record.get("effort")
        thinking = claude_record.get("thinking", True)
        in_memory_chats[cid] = messages
    else:
        # Check seed conversations
        for c in SEED_CONVERSATIONS:
            if c["id"] == cid:
                messages = c["messages"]
                project = c.get("project")
                break
        else:
            # Parse actual transcript from folder
            real_convos = get_real_conversations()
            for c in real_convos:
                if c["id"] == cid:
                    in_memory_chats[cid] = c["messages"]
                    messages = c["messages"]
                    project = c.get("project")
                    model = c.get("model")
                    provider = c.get("provider", "agy")
                    effort = c.get("effort")
                    speed = c.get("speed")
                    thinking = c.get("thinking")
                    break

    meta = _load_conversation_metadata().get(cid, {})
    if meta:
        if not model:
            model = meta.get("model")
        if not provider or provider == "agy":
            provider = meta.get("provider", provider)
        if not effort:
            effort = meta.get("effort")
        if not speed:
            speed = meta.get("speed")
        if thinking is None:
            thinking = meta.get("thinking")

    if not project:
        for c in get_real_conversations():
            if c["id"] == cid:
                project = c.get("project")
                break

    auth_header = request.headers.get("Authorization")
    token = None
    if auth_header and auth_header.startswith("Bearer "):
        token = auth_header.split(" ")[1]
    else:
        token = request.query_params.get("token")

    processed_messages = []
    for m in messages:
        content = m["content"]
        if "file://" in content:
            if token:
                content = content.replace("file:///", f"/api/media?token={token}&path=/")
            else:
                content = content.replace("file:///", "/api/media?path=/")
        processed_messages.append({
            "role": m["role"],
            "content": content
        })

    # Add virtual messages for pending media that have been uploaded but not yet sent in a prompt
    actual_cid = convo_id_mapping.get(cid, cid)
    pending_list = pending_media.get(actual_cid, [])
    for p in pending_list:
        token_part = f"token={token}&" if token else ""
        processed_messages.append({
            "role": "user",
            "content": f"![Attached Image](/api/media?{token_part}path={urllib.parse.quote(p)})"
        })

    return JSONResponse(content={
        "messages": processed_messages,
        "project": project,
        "provider": provider,
        "model": model,
        "effort": effort,
        "speed": speed,
        "thinking": thinking,
    })

def build_chat_response(request: ChatRequest, progress_callback=None):
    message = request.message
    model_entry = resolve_chat_model(request)
    model = model_entry["id"]
    workspace = request.workspace
    target = request.target
    conversation_id = request.conversation_id
    provider = model_entry["provider"]
    capabilities = model_entry["capabilities"]
    effort = request.effort or "Medium"
    speed = request.speed or "Standard"
    thinking = request.thinking is not False and capabilities["thinking"]
    if capabilities["thinking_required"]:
        thinking = True
    if provider == "codex":
        if effort not in capabilities["effort"]:
            raise ValueError(
                f"Effort {effort} is not supported by model {model}"
            )
        if speed not in capabilities["speed"]:
            raise ValueError(
                f"Speed {speed} is not supported by model {model}"
            )
        effort, _ = normalize_codex_effort(effort, model)
        speed, _ = normalize_codex_speed(speed, model)
    elif provider == "claude":
        if capabilities["effort"]:
            if effort not in capabilities["effort"]:
                raise ValueError(
                    f"Effort {effort} is not supported by model {model}"
                )
            effort, _ = normalize_claude_effort(effort, model)

    project_id = clean_project_name(os.path.basename(workspace or "agy"))
    if provider == "codex":
        actual_cid = convo_id_mapping.get(
            f"codex:{project_id}:{conversation_id}",
            conversation_id,
        )
    elif provider == "claude":
        actual_cid = convo_id_mapping.get(
            f"claude:{project_id}:{conversation_id}",
            conversation_id,
        )
    else:
        actual_cid = convo_id_mapping.get(
            f"{project_id}:{conversation_id}",
            convo_id_mapping.get(conversation_id, conversation_id),
        )
    
    # Prepend any pending media files to the message
    attached_media = pending_media.pop(actual_cid, [])
    if attached_media:
        media_md = "\n".join([f"![Attached Image](file://{p})" for p in attached_media])
        # User visible message in the chat
        user_visible_message = media_md + "\n\n" + message
        # Message sent to the CLI with instructions for agy
        media_instrs = "\n".join([f"[Attached Media File: {p}]\nPlease use your view_file tool to view/analyze this media file if needed." for p in attached_media])
        message = user_visible_message + "\n\n" + media_instrs
    else:
        user_visible_message = message

    def execute_selected(prompt: str):
        codex_images = [
            path
            for path in attached_media
            if os.path.splitext(path)[1].lower()
            in {".png", ".jpg", ".jpeg", ".gif", ".webp"}
        ]
        return run_selected_cli(
            prompt,
            model,
            conversation_id,
            target,
            workspace,
            provider,
            effort,
            speed,
            thinking,
            codex_images,
            progress_callback,
        )

    msg_lower = message.strip().lower()

    if msg_lower.startswith("/grill-me"):
        # Initialize the dynamic grill interview state
        interview_states[actual_cid] = {
            "mode": "grill",
            "step": 0
        }
        
        grill_init_prompt = (
            "[SYSTEM: INTERACTIVE GRILL-ME MODE INITIATED]\n"
            "The user wants to align on design decisions and project requirements for this workspace. "
            "Please analyze the workspace files and codebase. "
            "Identify 2-3 important design choices, configuration options, or architectural trade-offs that need user alignment. "
            "Generate the FIRST clarifying question and choices in the following JSON format so the UI can render it. "
            "Output ONLY the JSON object, with no markdown code blocks or extra text outside the JSON.\n\n"
            "JSON Format:\n"
            "{\n"
            '  "type": "question",\n'
            '  "question": "The question text here?",\n'
            '  "options": [\n'
            '    "(Recommended) Choice A text",\n'
            '    "Choice B text"\n'
            "  ],\n"
            '  "allow_other": true\n'
            "}"
        )
        
        reply, resolved_cid = execute_selected(grill_init_prompt)
        
        # Ensure clean JSON format by stripping markdown formatting if present
        reply_clean = reply.strip()
        if reply_clean.startswith("```json"):
            reply_clean = reply_clean[7:]
        if reply_clean.startswith("```"):
            reply_clean = reply_clean[3:]
        if reply_clean.endswith("```"):
            reply_clean = reply_clean[:-3]
        reply_clean = reply_clean.strip()
        
        try:
            parsed = json.loads(reply_clean)
            if isinstance(parsed, dict) and "question" in parsed:
                reply = json.dumps(parsed)
        except Exception:
            pass

    elif actual_cid in interview_states:
        state = interview_states[actual_cid]
        state["step"] += 1
        
        grill_continue_prompt = (
            f"[SYSTEM: GRILL-ME INTERVIEW STEP {state['step']}]\n"
            f"The user selected/responded: \"{message.strip()}\"\n\n"
            "If you need to clarify more design decisions (limit to 3 questions max overall), "
            "please output the NEXT clarifying question in the exact same JSON format (ONLY the JSON object, no extra text, no markdown wrappers).\n\n"
            "If you have enough alignment or have reached 3 questions, please finish the interview by outputting "
            "a friendly markdown summary of all decisions, how you will save/apply them to the workspace, "
            "and state that the alignment is complete. Do NOT use the JSON format for the final summary response."
        )
        
        reply, resolved_cid = execute_selected(grill_continue_prompt)
        
        reply_clean = reply.strip()
        if reply_clean.startswith("```json"):
            reply_clean = reply_clean[7:]
        if reply_clean.startswith("```"):
            reply_clean = reply_clean[3:]
        if reply_clean.endswith("```"):
            reply_clean = reply_clean[:-3]
        reply_clean = reply_clean.strip()
        
        is_question = False
        try:
            parsed = json.loads(reply_clean)
            if isinstance(parsed, dict) and "question" in parsed:
                reply = json.dumps(parsed)
                is_question = True
        except Exception:
            pass
            
        if not is_question:
            # Interview completed! Close state and save report
            del interview_states[actual_cid]
            
            project_id = clean_project_name(os.path.basename(workspace or "agy"))
            cwd_path = resolve_project_directory(project_id)
            pref_file = os.path.join(cwd_path, "alignment_preferences.json")
            try:
                os.makedirs(os.path.dirname(pref_file), exist_ok=True)
                with open(pref_file, "w", encoding="utf-8") as f:
                    f.write(f"# Design Alignment Summary\n\nDate: {datetime.datetime.now().isoformat()}\n\n{reply}")
            except Exception as e:
                logging.error(f"Failed to save final alignment log: {e}")
    elif msg_lower.startswith("/goal"):
        goal_text = message[5:].strip()
        if not goal_text:
            reply = (
                "🎯 **Goal Mode**: Please specify a goal after the command.\n\n"
                "Example:\n"
                "`/goal build a login page with validation`"
            )
            resolved_cid = conversation_id
        else:
            wrapped_message = (
                "[SYSTEM: GOAL MODE INITIATED]\n"
                "The user has requested you to run in extra-thorough, goal-oriented mode to achieve the following objective. "
                "Do not stop until the objective is fully completed, verified, and all tests pass.\n\n"
                f"Objective:\n{goal_text}"
            )
            reply, resolved_cid = execute_selected(wrapped_message)
    elif msg_lower.startswith("/learn"):
        rule_text = message[6:].strip()
        if not rule_text:
            reply = (
                "💡 **Learn Mode**: Please specify a rule or instruction you want me to remember.\n\n"
                "Example:\n"
                "`/learn always use double quotes for React components`"
            )
            resolved_cid = conversation_id
        else:
            project_id = clean_project_name(os.path.basename(workspace or "agy"))
            cwd_path = resolve_project_directory(project_id)
            if provider == "codex":
                agents_file = os.path.join(cwd_path, "AGENTS.md")
            elif provider == "claude":
                agents_file = os.path.join(cwd_path, "CLAUDE.md")
            else:
                agents_file = os.path.join(cwd_path, ".agents", "AGENTS.md")
            agents_dir = os.path.dirname(agents_file)
            
            try:
                os.makedirs(agents_dir, exist_ok=True)
                file_existed = os.path.exists(agents_file)
                with open(agents_file, "a", encoding="utf-8") as f:
                    if not file_existed:
                        f.write("# Workspace Rules & Customizations\n\n")
                    f.write(f"- {rule_text}\n")
                
                reply = (
                    "💾 **Rule Learned & Persisted!**\n\n"
                    f"I have added the following rule to your workspace rules file:\n"
                    f"📁 `{agents_file}`\n\n"
                    f"**Learned Rule**:\n"
                    f"> {rule_text}\n\n"
                    "All future KookAI agent interactions in this workspace will now respect this rule."
                )
            except Exception as e:
                reply = f"❌ **Error saving rule**: {str(e)}"
            resolved_cid = conversation_id
    elif msg_lower.startswith("/browser") and not message[8:].strip():
        reply = (
            "🌐 **Browser Mode**: Please specify a web task or URL after the command.\n\n"
            "Example:\n"
            "`/browser search npm package info for lodash`"
        )
        resolved_cid = conversation_id
    elif msg_lower.startswith("/help"):
        reply = (
            "💡 **Available Commands & Help Guide**\n\n"
            "- `/goal <task>`: Start an extra-thorough, goal-oriented workflow on the workspace.\n"
            "- `/browser <task>`: Command browser subagent for web tasks.\n"
            "- `/grill-me`: Start an interactive design/requirement alignment session and save preferences.\n"
            "- `/learn <instruction>`: Instruct me to remember a specific rule or config for this workspace.\n"
            "- `@<filename>`: Reference file context in your message.\n\n"
            "Using model: **" + model + "** on target **" + target + "** inside workspace **" + workspace + "**."
        )
        resolved_cid = conversation_id
    else:
        reply, resolved_cid = execute_selected(message)

    if resolved_cid != actual_cid:
        if actual_cid in interview_states:
            interview_states[resolved_cid] = interview_states.pop(actual_cid)
        if actual_cid in in_memory_chats:
            existing_chats = in_memory_chats.pop(actual_cid)
            if resolved_cid not in in_memory_chats:
                in_memory_chats[resolved_cid] = existing_chats
            else:
                in_memory_chats[resolved_cid] = existing_chats + in_memory_chats[resolved_cid]

    if resolved_cid not in in_memory_chats:
        in_memory_chats[resolved_cid] = []

    in_memory_chats[resolved_cid].append({"role": "user", "content": user_visible_message})
    in_memory_chats[resolved_cid].append({"role": "assistant", "content": reply})

    persist_conversation_metadata(
        resolved_cid,
        project_id,
        model,
        provider,
        effort if provider in {"codex", "claude"} else None,
        speed if provider == "codex" else None,
        thinking if provider == "claude" else None,
    )

    if provider == "codex":
        persist_codex_exchange(
            resolved_cid,
            project_id,
            model,
            effort,
            speed,
            user_visible_message,
            reply,
        )
    elif provider == "claude":
        persist_claude_exchange(
            resolved_cid,
            project_id,
            model,
            effort,
            thinking,
            user_visible_message,
            reply,
        )

    processed_reply = reply.replace("file:///", "/api/media?path=/")
    return {
        "status": "success",
        "reply": processed_reply,
        "conversation_id": resolved_cid,
        "provider": provider,
        "model": model,
        "effort": effort if provider in {"codex", "claude"} else None,
        "speed": speed if provider == "codex" else None,
        "thinking": thinking if provider == "claude" else None,
    }


def append_chat_task_event(task_id: str, event_type: str, message: str):
    clean = (message or "").strip()
    if not clean:
        return
    if len(clean) > 500:
        clean = clean[:497] + "..."

    with chat_tasks_lock:
        task = chat_tasks.get(task_id)
        if not task:
            return
        events = task["events"]
        if events and events[-1]["type"] == event_type and events[-1]["message"] == clean:
            return
        seq = task["next_seq"]
        task["next_seq"] += 1
        events.append({
            "seq": seq,
            "type": event_type,
            "message": clean,
            "timestamp": datetime.datetime.now().timestamp()
        })
        if len(events) > 200:
            del events[:-200]


def finish_chat_task(task_id: str, status: str, result: dict):
    with chat_tasks_lock:
        task = chat_tasks.get(task_id)
        if not task:
            return
        task["status"] = status
        task["result"] = result
        task["completed_at"] = datetime.datetime.now().timestamp()


def run_chat_task(task_id: str, request_data: dict):
    try:
        chat_request = ChatRequest(**request_data)
        append_chat_task_event(task_id, "progress", "Thinking...")
        result = build_chat_response(
            chat_request,
            progress_callback=lambda event_type, message: append_chat_task_event(task_id, event_type, message)
        )
        finish_chat_task(task_id, "success", result)
    except Exception as e:
        logging.error(f"Chat task {task_id} failed: {e}")
        append_chat_task_event(task_id, "error", f"Task failed: {e}")
        finish_chat_task(task_id, "error", {
            "status": "error",
            "reply": f"❌ **Execution Error**: {str(e)}",
            "conversation_id": request_data.get("conversation_id")
        })


@app.post("/api/chat")
async def chat_endpoint(request: ChatRequest, req_raw: Request):
    verify_authorization(req_raw)
    verify_chat_model_request(request)
    return JSONResponse(content=build_chat_response(request))


@app.post("/api/chat-tasks")
async def start_chat_task_endpoint(request: ChatRequest, req_raw: Request):
    verify_authorization(req_raw)
    verify_chat_model_request(request)
    task_id = uuid.uuid4().hex
    with chat_tasks_lock:
        chat_tasks[task_id] = {
            "status": "running",
            "events": [],
            "next_seq": 0,
            "result": None,
            "created_at": datetime.datetime.now().timestamp(),
            "completed_at": None
        }
    thread = threading.Thread(target=run_chat_task, args=(task_id, request.dict()), daemon=True)
    thread.start()
    return JSONResponse(content={"status": "running", "task_id": task_id})


@app.get("/api/chat-tasks/{task_id}")
async def get_chat_task_endpoint(task_id: str, request: Request, after: int = -1):
    verify_authorization(request)
    with chat_tasks_lock:
        task = chat_tasks.get(task_id)
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        events = [event for event in task["events"] if event["seq"] > after]
        return JSONResponse(content={
            "status": task["status"],
            "events": events,
            "result": task["result"]
        })

@app.post("/api/upload-media")
async def upload_media_endpoint(conversation_id: str, filename: str, request: Request):
    actual_cid = convo_id_mapping.get(conversation_id, conversation_id)
    # Default to kookai brain folder, fallback to kookai-cli
    folder = os.path.join(ANTIGRAVITY_DATA_DIR, f"brain/{actual_cid}")
    if not os.path.exists(folder):
        folder = os.path.join(ANTIGRAVITY_CLI_DIR, f"brain/{actual_cid}")
        if not os.path.exists(folder):
            os.makedirs(folder, exist_ok=True)
            
    # Save the file as media__<current_timestamp_millis>.<ext>
    ext = os.path.splitext(filename)[1] or ".png"
    millis = int(datetime.datetime.now().timestamp() * 1000)
    target_filename = f"media__{millis}{ext}"
    target_path = os.path.join(folder, target_filename)
    
    try:
        content = await request.body()
        with open(target_path, "wb") as f:
            f.write(content)
        logging.info(f"Successfully uploaded media file: {target_path}")
        
        # Add to pending media list
        if actual_cid not in pending_media:
            pending_media[actual_cid] = []
        pending_media[actual_cid].append(target_path)
        
        return JSONResponse(content={"status": "success", "filename": target_filename, "path": target_path})
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to upload file: {str(e)}")

@app.get("/api/usage-limits")
async def get_usage_limits(request: Request):
    verify_authorization(request)
    result_data = {
        "geminiWeeklyPercent": 1.2,
        "geminiHourlyPercent": 0.5,
        "claudeWeeklyPercent": 2.5,
        "claudeHourlyPercent": 1.8,
        "gptWeeklyPercent": 0.0,
        "gptHourlyPercent": 0.0,
        
        "geminiWeeklyUsed": 120000,
        "geminiWeeklyLimit": 10000000,
        "geminiHourlyUsed": 5000,
        "geminiHourlyLimit": 1000000,
        
        "claudeWeeklyUsed": 2500000,
        "claudeWeeklyLimit": 100000000,
        "claudeHourlyUsed": 180000,
        "claudeHourlyLimit": 10000000,

        "gptWeeklyUsed": 0,
        "gptWeeklyLimit": 100000000,
        "gptHourlyUsed": 0,
        "gptHourlyLimit": 10000000,
        "codexRateLimits": None,
        "codexUsageNote": "Codex GPT models use your ChatGPT/Codex account rate limit. When available, this endpoint reports the same Codex app-server rate-limit percentage shown by Codex Desktop."
    }

    try:
        codex_rate_limits = fetch_codex_rate_limits(timeout_seconds=8)
        if codex_rate_limits:
            result_data["codexRateLimits"] = codex_rate_limits
            primary = codex_rate_limits.get("primary") or {}
            secondary = codex_rate_limits.get("secondary") or {}
            if isinstance(primary.get("usedPercent"), int):
                result_data["gptWeeklyPercent"] = primary["usedPercent"]
                result_data["gptWeeklyUsed"] = primary["usedPercent"]
                result_data["gptWeeklyLimit"] = 100
            if isinstance(secondary.get("usedPercent"), int):
                result_data["gptHourlyPercent"] = secondary["usedPercent"]
                result_data["gptHourlyUsed"] = secondary["usedPercent"]
                result_data["gptHourlyLimit"] = 100
    except Exception as e:
        logging.error(f"Failed to fetch Codex account rate limits: {e}")
    
    try:
        res = subprocess.run(
            ["npx", "ccusage", "session", "--json"],
            capture_output=True,
            text=True,
            timeout=5,
            shell=(os.name == 'nt'),
            **hidden_subprocess_kwargs(),
        )
        if res.returncode == 0:
            data = json.loads(res.stdout)
            now = datetime.datetime.now(datetime.timezone.utc)
            
            gemini_weekly = 0
            gemini_hourly = 0
            claude_weekly = 0
            claude_hourly = 0
            gpt_weekly = 0
            gpt_hourly = 0
            
            def parse_timestamp(la_str, period_str):
                if la_str:
                    try:
                        return datetime.datetime.fromisoformat(la_str.replace('Z', '+00:00'))
                    except:
                        pass
                match = re.search(r'(\d{4})-(\d{2})-(\d{2})T(\d{2})-(\d{2})-(\d{2})', period_str)
                if match:
                    try:
                        parts = [int(p) for p in match.groups()]
                        return datetime.datetime(parts[0], parts[1], parts[2], parts[3], parts[4], parts[5], tzinfo=datetime.timezone.utc)
                    except:
                        pass
                match_date = re.search(r'(\d{4})-(\d{2})-(\d{2})', period_str)
                if match_date:
                    try:
                        parts = [int(p) for p in match_date.groups()]
                        return datetime.datetime(parts[0], parts[1], parts[2], tzinfo=datetime.timezone.utc)
                    except:
                        pass
                return None
                
            for item in data.get('session', []):
                la = item.get('metadata', {}).get('lastActivity')
                period = item.get('period', '')
                dt = parse_timestamp(la, period)
                if not dt:
                    continue
                
                hours_ago = (now - dt).total_seconds() / 3600.0
                # Subtract cacheReadTokens (prompt cache read hits) as they do not count against rate limits
                tokens = item.get('totalTokens', 0) - item.get('cacheReadTokens', 0)
                
                models = item.get('modelsUsed', [])
                is_gemini = any('gemini' in m.lower() for m in models)
                is_claude = any('claude' in m.lower() for m in models)
                is_gpt = any(('gpt' in m.lower() or 'openai' in m.lower()) for m in models)
                
                if is_gemini:
                    if hours_ago <= 168:
                        gemini_weekly += tokens
                    if hours_ago <= 5:
                        gemini_hourly += tokens
                if is_claude:
                    if hours_ago <= 168:
                        claude_weekly += tokens
                    if hours_ago <= 5:
                        claude_hourly += tokens
                if is_gpt:
                    if hours_ago <= 168:
                        gpt_weekly += tokens
                    if hours_ago <= 5:
                        gpt_hourly += tokens
                        
            # Limits
            gw_limit = 10000000
            gh_limit = 1000000
            cw_limit = 100000000
            ch_limit = 10000000
            
            result_data["geminiWeeklyUsed"] = gemini_weekly
            result_data["geminiHourlyUsed"] = gemini_hourly
            result_data["claudeWeeklyUsed"] = claude_weekly
            result_data["claudeHourlyUsed"] = claude_hourly
            if not result_data.get("codexRateLimits"):
                result_data["gptWeeklyUsed"] = gpt_weekly
                result_data["gptHourlyUsed"] = gpt_hourly
            
            result_data["geminiWeeklyPercent"] = round((gemini_weekly / gw_limit) * 100, 1) if gemini_weekly > 0 else 1.2
            result_data["geminiHourlyPercent"] = round((gemini_hourly / gh_limit) * 100, 1) if gemini_hourly > 0 else 0.5
            result_data["claudeWeeklyPercent"] = round((claude_weekly / cw_limit) * 100, 1) if claude_weekly > 0 else 2.5
            result_data["claudeHourlyPercent"] = round((claude_hourly / ch_limit) * 100, 1) if claude_hourly > 0 else 1.8
            if not result_data.get("codexRateLimits"):
                result_data["gptWeeklyPercent"] = round((gpt_weekly / cw_limit) * 100, 1) if gpt_weekly > 0 else 0.0
                result_data["gptHourlyPercent"] = round((gpt_hourly / ch_limit) * 100, 1) if gpt_hourly > 0 else 0.0
            
    except Exception as e:
        logging.error(f"Failed to fetch usage limits from ccusage: {e}")
        
    return JSONResponse(content=result_data)

@app.get("/api/media")
async def get_media(path: str, request: Request):
    verify_authorization(request)
    decoded_path = urllib.parse.unquote(path)
    if decoded_path.startswith("file://"):
        decoded_path = decoded_path[7:]
    # Check if path exists and is absolute/relative resolved
    if not os.path.exists(decoded_path):
        raise HTTPException(status_code=404, detail="Media file not found")
    return FileResponse(decoded_path)

# Serve static files
app.mount("/", StaticFiles(directory="static", html=True), name="static")

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8080, reload=AGY_RELOAD)
