# Product

<!-- impeccable:product-schema 1 -->

## Platform

adaptive

## Users

Developers, AI engineers, and power users who need an orchestrator bridging their local desktop coding workspace with remote mobile devices and web consoles. They run multimodal workflows (code, terminal, video analysis, transcription) across diverse AI model providers (Antigravity/Gemini, Codex, Claude Code, Grok, Kimi, Muse, Z.ai GLM).

## Product Purpose

KookAI provides a unified, cross-platform workspace hub that manages multi-provider AI CLI execution, real-time token streaming, multimodal video/audio extraction, and seamless device pairing (LAN QR / Cloudflare Quick Tunnel) with resilient failover.

## Positioning

Unlike single-vendor AI chat interfaces, KookAI is an open-ended multi-provider orchestration runtime with local execution fidelity, automated quota/latency health tracking, resilient failover mechanisms, and cross-device session synchronization.

## Operating Context

- **Desktop Host:** FastAPI Python backend running local CLI tools and WebSocket streams.
- **Web Console (`/static`):** High-density workspace dashboard for prompt execution, multi-server switching, and configuration.
- **Mobile Companion (`/mobile`):** React Native / Expo companion app for on-the-go chat, pairing, inline media viewing, and live streaming.
- **Network Modes:** Local LAN (mDNS, QR code) and remote zero-config tunnels (Cloudflare Tunnel).

## Capabilities and Constraints

- **Multi-Provider Failover:** Dynamic provider failover based on health, quota availability, and latency tracked by `cli_manager.py`.
- **Multimodal Video Processing:** Keyframe extraction, Whisper STT chunking, and transcript synthesis with rate-limit key rotation.
- **Session Continuity:** WebSocket pub/sub token stream mirroring, ring-buffer reconnection recovery, and master session locking.
- **Design Constraint:** UI must maintain clear state indicators (active provider, failover alerts, pairing status) without unnecessary clutter or deceptive animations.

## Brand Commitments

- **Name:** KookAI
- **Voice:** Direct, technical, transparent, responsive, and calm.
- **Aesthetic:** Crisp workspace client, purposeful dark/light modes, clear typography hierarchy, and zero AI slop (no gimmicky glows, no card-nesting overkill, no unreadable micro-text).

## Product Principles

1. **State Over Decoration:** Every visual indicator (chip, badge, pulse) must correspond to real connection, quota, or execution state.
2. **Speed and Scanability:** Dense developer interfaces must remain legible on high-DPI screens and mobile viewports with at least 12px body typography.
3. **Resilient Transparency:** When a provider fails or degrades, show an honest, actionable toast and status transition instead of silent masking.
