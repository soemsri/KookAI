# KookAI Project Context & Domain Glossary

## Overview
KookAI is an AI orchestration platform supporting multi-provider model routing, automated model failover, video processing, and real-time status dispatch across mobile and web interfaces.

## Domain Terminology & Concepts
- **CLI Manager (`cli_manager.py`)**: Central orchestration component responsible for managing multi-provider model processes and state transitions.
- **Model Provider Failover**: The automated strategy that switches requests to secondary model backends (e.g. Claude, Grok, Kimi, Codex, Muse) upon primary provider errors or rate limits.
- **UI Fallback Notifications**: Real-time status updates dispatched from the backend orchestrator (`main.py` & `cli_manager.py`) to inform the UI of provider switching events.
- **Alignment Preferences (`alignment_preferences.json`)**: Persistent configuration tracking architecture choices and failover priorities aligned via `grill-me` or `grill-with-docs`.
- **Pairing & Token Lifecycle**: 6-digit PIN and QR-code pairing generating persistent device auth tokens, with heartbeat validation and local LAN QR fallback if worker registry is offline.
- **Multi-Server Management**: Mobile client background status pinging across saved server hosts with visual availability indicators and interactive switch suggestions.
- **Universal Video Processing Pipeline (`video_processor.py`)**: Scene-aware keyframe extraction, perceptual frame deduplication, VTT subtitle parsing, and remote/local Whisper STT fallback for multimodal LLMs.
- **Hybrid Multimodal Failover & Downsampling**: Automated reduction of frame sample density during vision model rate limits/failures before falling back to secondary vision backends or transcript-only analysis.
- **Granular Progress Event Dispatch**: WebSocket & SSE streaming of real-time video processing steps (download, frame extraction %, transcription, model generation) to UI clients.
- **Video Cache & Storage Lifecycle**: Immediate purge of raw video files post-extraction, with keyframes and transcripts managed in `.data/video_cache` capped at 1GB / 24-hour TTL.
- **Unified Canonical Transcript Store**: Provider-agnostic session store (`.data/conversations.json` / SQLite `conversations.db`) capturing roles, multi-turn messages, image attachments, and video analysis context across all CLI backends.
- **On-the-Fly CLI Adapter Synthesis**: Dynamic context re-hydration performed by model backends (`codex_backend.py`, `claude_backend.py`, `kimi_backend.py`, `grok_backend.py`, `muse_backend.py`) during provider switching or auto-failover.
- **Semantic Parameter Abstraction Matrix**: Unified parameter mapping (Reasoning Effort, Extended Thinking, Speed, Sandbox) ensuring model behavior consistency during failover with safe degradation notifications for unsupported knobs.
- **WebSocket Pub/Sub Broadcast & Session Master Locking**: Real-time token streaming and status mirroring across all connected client devices with a 10-second soft write lock timeout for active session input.
- **Resumable Stream Ring Buffer**: In-memory ring buffer (500 tokens / 5MB per session) storing active token generation during temporary network disconnects, flushed via `last_seq_id` upon client reconnection.
- **First-Write-Wins Session Mutex**: Mutex locking in `cli_manager.py` that rejects concurrent multi-device commands with HTTP 409 Conflict and WebSocket notification toasts.
- **Per-Server Heartbeat Presence Registry**: 15-second socket ping/pong tracking active device connections (`device_id`, `device_alias`, `client_type`, `last_seen`) across host servers.


