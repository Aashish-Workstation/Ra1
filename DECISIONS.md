# RA1 Decision Log

## DEC-001 — Backend language: Python + FastAPI
**Date:** 2026-06-08
**Decision:** Python with FastAPI for the RA1 backend.
**Reason:** AI/ML ecosystem is Python-first. All downstream components (memory scoring, vector operations, embeddings, agent frameworks) have best-in-class Python libraries. FastAPI is async-native, handles streaming cleanly, and produces OpenAI-compatible endpoints easily.
**Alternatives considered:** Node.js/TypeScript (same ecosystem as LibreChat, but advantage disappears since we don't touch LibreChat source).

## DEC-002 — Package manager: uv
**Date:** 2026-06-08
**Decision:** uv as the Python package manager.
**Reason:** Significantly faster than pip, clean virtual environment handling, modern standard for Python projects.

## DEC-003 — No source modification of third-party services
**Date:** 2026-06-08
**Decision:** All third-party services (LibreChat, LiteLLM, Infisical, Langfuse, etc.) run from official Docker images only. No forks, no source modification.
**Reason:** Upstream updates become a single image tag change. No merge conflicts. All customization via config files, environment variables, and RA1's own backend services.

## DEC-004 — Volumes: bind mounts over named volumes
**Date:** 2026-06-08
**Decision:** All data volumes use bind mounts under ./data/ rather than named Docker volumes.
**Reason:** Easier to inspect, backup, and manage. Data location is explicit and visible.

## DEC-005 — Single Valkey instance for all Redis-compatible services
**Date:** 2026-06-08
**Decision:** One Valkey container serves as Redis-compatible cache for LibreChat sessions, Infisical, Langfuse, and RA1 backend. No separate Redis container.
**Reason:** Reduces container count, all services support Redis-compatible protocol, Valkey is the OSS-locked choice per RA1 spec.

## DEC-006 — Old TypeScript codebase as reference only
**Date:** 2026-06-08
**Decision:** The existing TypeScript codebase is used as logic and pattern reference only. No code is copied directly. Everything is rewritten in Python.
**Reason:** Language mismatch (TypeScript vs Python). Architecture has evolved. Clean rewrite avoids hidden debt.

## DEC-007 — Canvas parked
**Date:** 2026-06-08
**Decision:** Canvas (React Flow) is parked. RA1 Chat (LibreChat + RA1 backend) is the sole focus until beta.
**Reason:** Scope control. Chat must be stable before canvas work resumes.