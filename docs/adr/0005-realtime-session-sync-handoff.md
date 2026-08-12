# ADR 0005: Real-time Cross-Device Session Handoff & WebSocket State Synchronization Protocol

* **Status**: Accepted
* **Date**: 2026-08-10

## Context
KookAI connects multiple client devices (e.g., Mobile App and Web Dashboard) to server backends running AI model generation (Claude, Codex, Grok, Kimi, Meta Muse) and video processing pipelines. When multiple devices interact with the backend simultaneously or experience intermittent network disconnections (such as switching from Wi-Fi to 5G), the platform requires predictable state synchronization, stream recovery, concurrent command resolution, and multi-server presence management.

## Decision
1. **WebSocket Pub/Sub Broadcast & Master Session Locking**:
   - Broadcast live token streams and execution progress events to all authenticated socket connections subscribed to the active session.
   - The client device initiating an action acquires a soft write lock (with a 10-second heartbeat timeout). Other connected devices display an "In Use by [Device Alias]" indicator and mirror streamed tokens in real-time.
2. **Background Detached Execution & Resumable Stream Buffer**:
   - Backend tasks continue execution to completion during client network disconnections, buffering generated output in an in-memory ring buffer (up to 500 tokens / 5MB per active session).
   - Reconnecting clients supply `last_seq_id` to receive buffered token flushes and resume live WebSocket streaming.
   - Outputs are auto-committed to the canonical transcript store (`.data/conversations.json` / `conversations.db`) after a 60-second disconnection timeout.
3. **First-Write-Wins Atomic Mutex & Conflict Resolution**:
   - `cli_manager.py` enforces an atomic mutex lock per session.
   - Concurrent actions during active execution are rejected with HTTP 409 Conflict and trigger a WebSocket notification toast ("Session currently busy processing command from [Device Alias]").
4. **Per-Server Heartbeat Presence & Subscription Lifecycle**:
   - Clients maintain 15-second ping/pong heartbeats with active server hosts.
   - Server backends track connected devices (`device_id`, `device_alias`, `client_type`, `last_seen`). Switching active servers cleanly unsubscribes socket channels and updates host presence.

## Consequences
- Enables smooth token stream mirroring across mobile and web UI interfaces.
- Prevents generation loss from temporary mobile signal drops or app backgrounding.
- Resolves race conditions during concurrent multi-device user inputs.
- Keeps server host presence accurate across multi-server network setups.
