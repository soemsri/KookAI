# ADR 0003: Universal Video Processing Pipeline, Multimodal Failover & Cache Lifecycle

* **Status**: Accepted
* **Date**: 2026-08-10

## Context
KookAI supports `/watch` video understanding across multiple AI backends (Gemini, Claude, Grok, Kimi, Codex, Muse). Processing online or local videos involves frame extraction (ffmpeg), subtitle parsing (VTT), audio transcription (Whisper), and LLM vision prompt construction. Unhandled rate limits, heavy video files, and remote STT failures require robust fallback, status updates, and storage cleanup.

## Decision
1. **Multimodal Failover & Downsampling**: If the primary vision provider fails or exceeds vision token limits, KookAI automatically downsamples frame density (e.g., from 2.0 FPS to 0.5 FPS) and attempts execution on the next vision-capable backend. If vision backends are unavailable, it falls back to transcript-only mode with an inline UI notification badge.
2. **Audio Transcription Fallback**: Subtitles prioritize native VTT captions. If unavailable, requests route to Groq (`whisper-large-v3`) or OpenAI (`whisper-1`). If remote APIs fail or lack API keys, KookAI falls back to local `whisper` CLI / `whisper.cpp` execution before dropping back to vision-only keyframe analysis.
3. **Granular Progress Event Dispatch**: Long-running video pipeline stages (`downloading`, `extracting_frames`, `transcribing`, `generating`) stream real-time step events over WebSockets and SSE to mobile and web UI clients.
4. **Cache & Storage Lifecycle**: Raw video files are purged immediately post-extraction. Keyframes and transcripts are stored in `.data/video_cache` governed by an LRU policy (1GB max size, 24-hour TTL).

## Consequences
- Guarantees seamless video processing across high/low resource environments and network dropouts.
- Prevents disk bloat on host computers while maintaining instant keyframe reuse for repeat queries within 24 hours.
- Requires backend event emitters in `video_processor.py` and `main.py` connected to UI progress components.
