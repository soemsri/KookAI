"""Chat with a running Exo or OpenAI-compatible local inference server.

Discovery is a runtime overlay: it never downloads or starts a model, and never
writes machine-specific model IDs into the shared catalog.
"""
from __future__ import annotations

import copy
import hashlib
import http.client
import json
import os
import socket
import threading
import time
import urllib.parse

_cache_lock = threading.Lock()
_cache = {}


class LocalRequestCancelled(Exception):
    pass


def base_url():
    url = os.environ.get("KOOKAI_LOCAL_LLM_URL", "http://127.0.0.1:52415/v1").rstrip("/")
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("KOOKAI_LOCAL_LLM_URL must be an http(s) API URL without credentials or query parameters")
    return url if parsed.path.endswith("/v1") else url + "/v1"


def _request(path, payload=None, cancel_event=None):
    """Yield decoded SSE events or one JSON response; close on cancellation."""
    url = urllib.parse.urlsplit(base_url())
    cls = http.client.HTTPSConnection if url.scheme == "https" else http.client.HTTPConnection
    conn = cls(url.hostname, url.port, timeout=5)
    finished = threading.Event()

    def check_cancel():
        if cancel_event and cancel_event.is_set():
            raise LocalRequestCancelled("Local generation cancelled")

    def watch_cancel():
        while not finished.wait(0.1):
            if cancel_event.is_set():
                if conn.sock:
                    try:
                        conn.sock.shutdown(socket.SHUT_RDWR)
                    except OSError:
                        pass
                return

    watcher = None
    try:
        check_cancel()
        conn.connect()
        conn.sock.settimeout(120 if payload is not None else 5)
        if cancel_event:
            watcher = threading.Thread(target=watch_cancel, daemon=True)
            watcher.start()
        headers = {"Content-Type": "application/json"}
        key = os.environ.get("KOOKAI_LOCAL_LLM_API_KEY", "").strip()
        if key:
            headers["Authorization"] = "Bearer " + key
        request_path = path if path.startswith("/") else url.path + "/" + path
        conn.request("POST" if payload is not None else "GET", request_path,
                     json.dumps(payload).encode() if payload is not None else None, headers)
        response = conn.getresponse()
        check_cancel()
        if response.status >= 400:
            # Do not forward arbitrary server bodies (which may contain secrets).
            raise RuntimeError(f"Local LLM returned HTTP {response.status}; check the model is running")
        if "text/event-stream" not in response.getheader("Content-Type", ""):
            yield json.loads(response.read())
            check_cancel()
            return
        data = []
        while True:
            check_cancel()
            raw = response.readline()
            if not raw:
                if data:
                    raise RuntimeError("Local LLM stream ended mid-event")
                break
            line = raw.decode("utf-8").rstrip("\r\n")
            if line.startswith("data:"):
                data.append(line[5:].lstrip())
            elif not line and data:
                event = "\n".join(data)
                data = []
                if event == "[DONE]":
                    return
                yield json.loads(event)
    except Exception:
        check_cancel()
        raise
    finally:
        finished.set()
        conn.close()
        if watcher:
            watcher.join(timeout=0.2)


def _local_model_description():
    try:
        from qwen_backend import should_use_qwen_harness

        if should_use_qwen_harness():
            return "Local LLM • Qwen Code harness • workspace tools"
    except Exception:
        pass
    return "Local LLM chat • running server • no workspace tools"


def discover_local_models(force=False):
    url = base_url()
    with _cache_lock:
        cached = _cache.get(url)
        if not force and cached and time.monotonic() - cached[0] < 10:
            result = copy.deepcopy(cached[1])
            desc = _local_model_description()
            for model in result:
                model["description"] = desc
            return result
        models = []
        try:
            payload = next(_request("models"))
            entries = payload.get("data", []) if isinstance(payload, dict) else payload
            if not isinstance(entries, list):
                raise ValueError("Invalid local model list")
            if any(m.get("owned_by") == "exo" for m in entries if isinstance(m, dict)):
                state = next(_request("/state"))
                running = set()
                instances = state.get("instances", {}) if isinstance(state, dict) else {}
                if not isinstance(instances, dict):
                    instances = {}
                for wrapper in instances.values():
                    if not isinstance(wrapper, dict):
                        continue
                    for instance in wrapper.values():
                        if isinstance(instance, dict):
                            assignments = instance.get("shardAssignments", {})
                            model_id = assignments.get("modelId") if isinstance(assignments, dict) else None
                            if isinstance(model_id, str):
                                running.add(model_id)
                entries = [m for m in entries if isinstance(m, dict) and m.get("id") in running]
            seen = set()
            desc = _local_model_description()
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                raw_id = entry.get("id")
                if not isinstance(raw_id, str) or not raw_id or len(raw_id) > 150 or any(ord(c) < 32 for c in raw_id) or raw_id in seen:
                    continue
                seen.add(raw_id)
                digest = hashlib.sha256(raw_id.encode()).hexdigest()[:12]
                caps = entry.get("capabilities") or []
                models.append({
                    "id": "local-" + digest,
                    "label": (raw_id[:100] + " (Local)"),
                    "description": desc,
                    "provider": "local", "cli_model": "local/" + raw_id,
                    "badge": "Local", "usage_bucket": "local", "enabled": True,
                    "capabilities": {"effort": [], "speed": [],
                                     "thinking": entry.get("owned_by") == "exo" and "thinking_toggle" in caps,
                                     "thinking_required": False},
                })
        except (OSError, ValueError, RuntimeError, http.client.HTTPException):
            models = []
        _cache[url] = (time.monotonic(), models)
        result = copy.deepcopy(models)
        desc = _local_model_description()
        for model in result:
            model["description"] = desc
        return result


def complete_local(model, messages, *, thinking=False, progress_callback=None, cancel_event=None, max_tokens=4096):
    payload = {"model": model["cli_model"].removeprefix("local/"),
               "messages": messages, "stream": True, "max_tokens": max_tokens}
    if model["capabilities"]["thinking"]:
        payload["enable_thinking"] = thinking
    parts = []
    finished = False
    for event in _request("chat/completions", payload, cancel_event):
        if event.get("error"):
            raise RuntimeError("Local LLM generation failed; check the inference server")
        choices = event.get("choices") or []
        if not choices:
            continue
        choice = choices[0]
        delta = choice.get("delta") or choice.get("message") or {}
        content = delta.get("content")
        if isinstance(content, str) and content:
            parts.append(content)
            if progress_callback:
                progress_callback("progress", content)
        if choice.get("finish_reason"):
            finished = True
    if not finished or not parts:
        raise RuntimeError("Local LLM returned an incomplete or empty response")
    return "".join(parts)
