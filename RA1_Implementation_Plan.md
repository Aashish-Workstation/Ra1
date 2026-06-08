# RA1 Chat — Implementation Plan & Progress

> **Project:** RA1 Chat (first app on the RA1 AI OS).
> **Phase 1 scope:** ATRS (Audit Trace + Replay System) and Credential Vault only.
> **Out of scope:** autonomous agents, workflows, canvas, FastAPI route wiring (next phase).

---

## 1. Discovered Tech Stack

| Layer | Choice | Evidence |
|---|---|---|
| Language | Python 3.11 | `backend/pyproject.toml` |
| Web framework | FastAPI 0.111+ | `backend/pyproject.toml` |
| ASGI server | uvicorn[standard] | `backend/pyproject.toml` |
| Package manager | uv | `backend/pyproject.toml` |
| Validation / typing | Pydantic v2.7+ | `backend/pyproject.toml` |
| Settings | pydantic-settings | `backend/pyproject.toml` |
| Primary DB | PostgreSQL 16 (driver: `asyncpg`) | `backend/pyproject.toml`, `services/infra/postgres-init.sql` |
| Observability DB | ClickHouse 24.6 | `services/infra/clickhouse-init.sql` |
| Cache / cooldown | Redis 5.0.4 | `backend/pyproject.toml` |
| Async HTTP | httpx | `backend/pyproject.toml` |
| Encryption | cryptography 42.0+ (AES-256-GCM with HKDF) | `backend/app/core/crypto.py` |
| Tests | pytest + pytest-asyncio | `backend/pyproject.toml` |

### Conventions to match
- `app/services/<name>.py` — service modules
- `app/models/<name>.py` — Pydantic models
- `app/core/<name>.py` — cross-cutting utilities
- `services/infra/postgres-init.sql` — DB bootstrap
- `services/infra/clickhouse-init.sql` — observability tables

### Architectural decisions applied
- **ATRS** lives in **ClickHouse** (append-only observability)
- **Vault** lives in **PostgreSQL** (transactional, encrypted, with a UNIQUE(owner_id, label) constraint)
- **Replay**: ATRS writes to a Postgres `atrs_outbox` table when ClickHouse is unavailable, so logs are never dropped.

---

## 2. Implementation Checklists

### Component A — ATRS (Audit Trace + Replay System)

- [x] Create `backend/app/models/atrs.py` (Pydantic schemas + strict enums)
- [x] Create `backend/app/core/atrs.py` (append-only service with scrubber)
- [x] Append `audit_trace` table to `services/infra/clickhouse-init.sql`
- [x] Append `atrs_outbox` table to `services/infra/postgres-init.sql`
- [x] Implement `entity_ref` validator (pattern: `<type>:<id>`, no raw values)
- [x] Implement metadata scrubber (blocks `credential_value`, `api_key`, `token`, etc.)
- [x] Enforce `event_type` is a typed enum (no freeform strings)
- [x] Expose `timed()` context manager for `duration_ms`
- [x] Postgres outbox fallback for replay when ClickHouse is unreachable
- [x] Unit tests: enum enforcement, scrubber, append-only surface, entity_ref pattern
- [x] Unit tests: outbox fallback when CH raises

### Component B — Credential Vault

- [x] Create `backend/app/models/vault.py` (Pydantic schemas + enums for CredentialType/VaultStatus/RefreshStatus)
- [x] Create `backend/app/core/crypto.py` (AES-256-GCM with HKDF key derivation)
- [x] Create `backend/app/services/vault.py` (no-cache, owner-isolated, ATRS-integrated)
- [x] Append `vault_entries` table to `services/infra/postgres-init.sql` (UNIQUE(owner_id, label))
- [x] Encrypt `value` AND `refresh_token` before any DB write
- [x] `resolve()` decrypts at call time only — no caching of any kind
- [x] Strict owner isolation: every query `WHERE owner_id = $1 AND vault_id = $2`
- [x] ATRS events emitted on every `create`/`rotate`/`revoke`/`resolve` (never plaintext)
- [x] Existing ClickHouse `credential_access_events` table also written on resolve
- [x] Unit tests: encryption round-trip, no-plaintext-in-DB, unique nonce, no cache, owner isolation, rotate, revoke, ATRS integration
- [x] Unit tests: `refresh_status` correctly mapped in `_to_read()` (bug fix)
- [x] Unit tests: `refresh_token` encryption verified

### Component C — Model Engine

- [x] Create `backend/app/models/model.py` (ModelStatus enum, ModelNode schema)
- [x] Extend `backend/app/models/atrs.py` with model event types (`model.call.start/success/failure`, `model.fallback.triggered`)
- [x] Append `model_catalog` table to `services/infra/postgres-init.sql`
- [x] Create `backend/app/services/model_engine.py` (ModelEngineService with BYOK, fallback, guard layer)
- [x] Unit tests: dynamic fallback selection when primary model fails
- [x] Unit tests: call-time key resolution from Credential Vault
- [x] Unit tests: ATRS logging on call events
- [x] Unit tests: owner isolation on model access
- [x] Fixed: Added uuid import, credential resolution error handling
- [x] Fixed: Added user_id parameter for budget checks
- [x] Fixed: Provider availability now checks credential_ref

### Component D — Memory Engine & Node

- [x] Create `backend/app/models/memory.py` (Pydantic schemas + enums for KnowledgeType/MemorySource/KnowledgeLane)
- [x] Create `backend/app/services/memory_engine.py` (MemoryEngineService with stateless KAC pipeline)
- [x] Append `memory_records` table to `services/infra/postgres-init.sql`
- [x] Extend `backend/app/models/atrs.py` with `ATRSMemoryEvent` enum
- [x] Unit tests: KAC blocks edits to locked records
- [x] Unit tests: Confidence score changes promote records across lanes
- [x] Unit tests: Conflicting facts trigger conflict detection and ATRS logging
- [x] Extend `conftest.py` with memory fixtures

### Cross-cutting

- [x] Add `cryptography` runtime dep to `pyproject.toml` + `requirements.txt`
- [x] Add `pytest` + `pytest-asyncio` dev deps
- [x] Create `backend/tests/__init__.py` + `conftest.py` (`FakePool` fixture)

---

### Component E — Persona Engine & Node

- [x] Create `backend/app/models/persona.py` (Persona, PersonaCreate, PersonaRead schemas + Archetype enum + PersonaScope enum)
- [x] Create `backend/app/services/persona_engine.py` (stateless service with blend shifts and major switch detection)
- [x] Add `ATRSPersonaEvent` enum to `backend/app/models/atrs.py` (PERSONA_LOADED, PERSONA_BLEND_UPDATED, PERSONA_SWITCH_MANual)
- [x] Append `personas` table to `services/infra/postgres-init.sql`
- [x] Implement `load_persona()` with scope precedence (private > habitat > global)
- [x] Implement `update_blend()` with context-driven weight adjustments
- [x] Implement `propose_major_switch()` for threshold-crossing detection
- [x] ATRS logging on persona.load, persona.blend.update, persona.switch.manual
- [x] Unit tests: archetype blend validation (sum = 1.0), invalid archetypes rejected
- [x] Unit tests: persona lifecycle operations

---

### Component F — Knowledge Base & Search Engine

- [x] Create `backend/app/models/knowledge.py` (KnowledgeItem, KnowledgeItemCreate, KnowledgeItemRead, SearchResult schemas + ContentType enum)
- [x] Create `backend/app/services/search_engine.py` (unified search across Memory and Knowledge domains)
- [x] Add `ATRSKnowledgeEvent` enum to `backend/app/models/atrs.py` (SEARCH_RECEIVED, SEARCH_RESULTS_RETURNED)
- [x] Append `knowledge_items` table to `services/infra/postgres-init.sql`
- [x] Implement `search()` with relevance threshold filtering
- [x] Integrate MemoryEngineService for memory domain queries
- [x] Integrate KnowledgeItem repository for knowledge domain queries
- [x] ATRS logging on search.received and search.results_returned
- [x] Unit tests: cross-domain search execution
- [x] Unit tests: threshold filtering excludes low-relevance results

---

### Component G — Input Engine

- [x] Create `backend/app/services/input_engine.py` (normalizing function for raw inputs)
- [x] Create `NormalizedInputPayload` and `AttachmentMeta` schemas
- [x] Create `InputSettings` with max_file_upload_size and max_file_count
- [x] Add `ATRSInputEvent` enum to `backend/app/models/atrs.py` (INPUT_RECEIVED, INPUT_PAYLOAD_ASSEMBLED)
- [x] Implement input normalization for text, files, and attachments
- [x] Enforce file size and file count safety limits
- [x] ATRS logging on input.received and input.payload.assembled
- [x] Unit tests: input normalization flattens combined text and file payload
- [x] Unit tests: file size limit enforcement
- [x] Unit tests: file count limit enforcement

---

### Component H — Context Assembler

- [x] Create `backend/app/models/context.py` (ContextPayload, WorkingContext, EpisodicContext, SemanticContext, PersonaState)
- [x] Create `backend/app/services/context_assembler.py` (parallel fetch, token budget enforcement, pruning sequence)
- [x] Add `ATRSContextEvent` enum to `backend/app/models/atrs.py` (context.fetch_spec_received, context.assembled)
- [x] Add `CONTEXT` to `ATRSEngine` enum
- [x] Unit tests: context trimming under token budget stress
- [x] Unit tests: priority-based pruning verification

### Component I — Safety + Guardrails

- [x] Create `backend/app/models/safety.py` (SafetyOutcome, SafetyEvaluation, SafetyConfig)
- [x] Create `backend/app/services/safety_engine.py` (evaluation layer, Sacred Interceptor)
- [x] Add `ATRSSafetyEvent` enum to `backend/app/models/atrs.py` (safety.evaluated, safety.blocked)
- [x] Add `SAFETY` to `ATRSEngine` enum
- [x] Unit tests: credential leak blocking
- [x] Unit tests: safety outcome evaluation

### Component J — Output Engine

- [x] Create `backend/app/models/output.py` (OutputFormat, OutputChunk, OutputSynthesis)
- [x] Create `backend/app/services/output_engine.py` (format determination, composite delivery)
- [x] Add `ATSROutputEvent` enum to `backend/app/models/atrs.py` (output.received, output.synthesised)
- [x] Add `OUTPUT` to `ATRSEngine` enum
- [x] Unit tests: format determination
- [x] Unit tests: composite structure packaging

### Component K — Quality Gate

- [x] Create `backend/app/models/gate.py` (GateOutcome, QualityMetrics, GateConfig)
- [x] Create `backend/app/services/quality_gate.py` (dimension evaluation, retry logic)
- [x] Add `ATRSGateEvent` enum to `backend/app/models/atrs.py` (gate.evaluated, gate.rejected_retry)
- [x] Add `GATE` to `ATRSEngine` enum
- [x] Unit tests: coherence check failure triggering retry
- [x] Unit tests: hallucination detection

### Component L — Central Orchestrator

- [x] Create `backend/app/models/orchestrator.py` (MessageIntent, PipelinePhase, OrchestratorResult)
- [x] Create `backend/app/services/orchestrator.py` (10-phase pipeline, dependency injection)
- [x] Add `ATRSOrchestratorEvent` enum to `backend/app/models/atrs.py` (orchestrator.completed)
- [x] Add `ORCHESTRATOR` to `ATRSEngine` enum
- [x] Unit tests: end-to-end pipeline flow
- [x] Unit tests: service integration

---

### Component M — Notification Engine

- [x] Create `backend/app/models/notification.py` (Notification schema with Priority enum: P0_BLOCK, P1_URGENT, P2_INFORM, P3_NOTICE, P_SILENT)
- [x] Create `backend/app/services/notification_engine.py` (NotificationEngineService with priority routing and quiet hours)
- [x] Add `ATRSNotificationEvent` enum to `backend/app/models/atrs.py` (notification.received, notification.delivered)
- [x] Add `NOTIFICATION` to `ATRSEngine` enum
- [x] Append `notifications` table to `services/infra/postgres-init.sql`
- [x] Implement priority routing: P0/P1 break through immediately; P2/P3 respect quiet hours
- [x] Implement quiet hours window mechanism for lower priority signals
- [x] ATRS logging on notification.received and notification.delivered
- [x] Unit tests: P0_BLOCK bypasses quiet hours; P2_INFORM is held/queued during quiet hours
- [x] Unit tests: notifications correctly transition status (queued → delivered)

### Component N — Recommender Engine

- [x] Create `backend/app/models/recommender.py` (Recommendation schema with Domain enum: MODEL, PERSONA, SKILLS, ENVIRONMENT)
- [x] Create `backend/app/services/recommender_engine.py` (RecommenderEngineService with observer-style suggestions)
- [x] Add `ATRSRecommenderEvent` enum to `backend/app/models/atrs.py` (recommendation.fired, recommendation.accepted, recommendation.dismissed)
- [x] Add `RECOMMENDER` to `ATRSEngine` enum
- [x] Append `recommendations` table to `services/infra/postgres-init.sql`
- [x] Implement Model Domain recommendations: analyze ATRS logs for model.call.failure patterns
- [x] Implement Persona Domain recommendations: check archetype balances for blend modifications
- [x] Enforce dismissed recommendations cannot be surfaced again in same execution context
- [x] ATRS logging on recommendation.fired, recommendation.accepted, recommendation.dismissed
- [x] Unit tests: dismissed recommendations are blocked from re-display
- [x] Unit tests: model switch recommendations trigger on simulated ATRS error rate thresholds

---

### File Deliverables

| File | Status |
|---|---|
| `RA1_Implementation_Plan.md` | ✅ created (this file) |
| `backend/app/models/atrs.py` | ✅ created |
| `backend/app/models/vault.py` | ✅ created |
| `backend/app/models/model.py` | ✅ created |
| `backend/app/core/atrs.py` | ✅ created |
| `backend/app/core/crypto.py` | ✅ created |
| `backend/app/services/vault.py` | ✅ created |
| `backend/app/services/model_engine.py` | ✅ created |
| `backend/tests/__init__.py` | ✅ created |
| `backend/tests/conftest.py` | ✅ created |
| `backend/tests/test_atrs.py` | ✅ created |
| `backend/tests/test_vault.py` | ✅ updated (new tests for refresh_status and refresh_token) |
| `backend/tests/test_model_engine.py` | ✅ created |
| `backend/tests/test_memory_engine.py` | ✅ created |
| `backend/app/models/memory.py` | ✅ created |
| `backend/app/services/memory_engine.py` | ✅ created |
| `services/infra/postgres-init.sql` | ✅ updated (vault_entries, atrs_outbox, model_catalog, memory_records, notifications, recommendations) |
| `backend/app/models/atrs.py` | ✅ updated (ATRSPersonaEvent, ATRSKnowledgeEvent, ATRSInputEvent, ATRSNotificationEvent, ATRSRecommenderEvent enums) |
| `backend/app/models/persona.py` | ✅ created |
| `backend/app/models/knowledge.py` | ✅ created |
| `backend/app/services/persona_engine.py` | ✅ created |
| `backend/app/services/search_engine.py` | ✅ created |
| `backend/app/services/input_engine.py` | ✅ created |
| `backend/tests/test_persona_engine.py` | ✅ created |
| `backend/tests/test_search_engine.py` | ✅ created |
| `backend/tests/test_input_engine.py` | ✅ created |
| `backend/tests/test_context_assembler.py` | ✅ created |
| `backend/tests/test_safety_engine.py` | ✅ created |
| `backend/tests/test_output_engine.py` | ✅ created |
| `backend/tests/test_quality_gate.py` | ✅ created |
| `backend/tests/test_orchestrator.py` | ✅ created |
| `services/infra/postgres-init.sql` | ✅ updated (personas, knowledge_items tables) |
| `backend/app/models/context.py` | ✅ created |
| `backend/app/models/safety.py` | ✅ created |
| `backend/app/models/output.py` | ✅ created |
| `backend/app/models/gate.py` | ✅ created |
| `backend/app/models/orchestrator.py` | ✅ created |
| `backend/app/services/context_assembler.py` | ✅ created |
| `backend/app/services/safety_engine.py` | ✅ created |
| `backend/app/services/output_engine.py` | ✅ created |
| `backend/app/services/quality_gate.py` | ✅ created |
| `backend/app/services/orchestrator.py` | ✅ created |
| `backend/tests/conftest.py` | ✅ updated (personas, knowledge_items, notifications, recommendations in FakePool) |
| `services/infra/clickhouse-init.sql` | ✅ updated (audit_trace) |
| `backend/pyproject.toml` | ✅ updated (cryptography, pytest, pytest-asyncio) |
| `backend/requirements.txt` | ✅ updated |
| `backend/app/models/notification.py` | ✅ created |
| `backend/app/models/recommender.py` | ✅ created |
| `backend/app/services/notification_engine.py` | ✅ created |
| `backend/app/services/recommender_engine.py` | ✅ created |
| `backend/tests/test_notification_engine.py` | ✅ created |
| `backend/tests/test_recommender_engine.py` | ✅ created |

---

## 4. Bug Fixes Applied

### Critical Fix
- **File:** `backend/app/services/vault.py:350`
- **Issue:** `_to_read()` incorrectly mapped `row.refresh_token` to `refresh_status` field
- **Fix:** Changed to `refresh_status=row.refresh_status`

### Clarity Fix
- **File:** `backend/app/services/vault.py:121-124`
- **Issue:** Truthiness check for `refresh_token` could be unclear
- **Fix:** Changed to explicit `if entry.refresh_token is not None and entry.refresh_token != ""`

---

## 5. Test Results

Run manually:
```bash
cd backend && python3 -m pytest tests/ -v
```

## 6. Implementation Summary

### Component E: Persona Engine
- **Models:** `Persona`, `PersonaCreate`, `PersonaRead`, `Archetype`, `PersonaScope`
- **Service:** Stateless `PersonaEngineService` with scope precedence loading, blend updates, and major switch detection
- **Database:** `personas` table with JSONB for archetype_blend, tone_rules, rules
- **ATRS Events:** `persona.loaded`, `persona.blend.updated`, `persona.switch.manual`

### Component F: Knowledge Base & Search Engine
- **Models:** `KnowledgeItem`, `KnowledgeItemCreate`, `KnowledgeItemRead`, `SearchResult`, `ContentType`
- **Service:** `SearchEngineService` with unified cross-domain search and threshold filtering
- **Database:** `knowledge_items` table with GIN indexes for tags and content search
- **ATRS Events:** `search.received`, `search.results_returned`

### Component G: Input Engine
- **Models:** `NormalizedInputPayload`, `AttachmentMeta`, `InputSettings`
- **Service:** `InputEngineService` with file size/count limits and language detection
- **ATRS Events:** `input.received`, `input.payload.assembled`

### Component H: Context Assembler
- **Models:** `ContextPayload`, `WorkingContext`, `EpisodicContext`, `SemanticContext`, `PersonaState`, `ContextFetchSpec`
- **Service:** `ContextAssemblerService` with parallel fetch and priority-based pruning
- **ATRS Events:** `context.fetch_spec_received`, `context.assembled`

### Component I: Safety + Guardrails
- **Models:** `SafetyOutcome`, `SafetyEvaluation`, `SafetyConfig`
- **Service:** `SafetyEngineService` with credential leak detection
- **ATRS Events:** `safety.evaluated`, `safety.blocked`

### Component J: Output Engine
- **Models:** `OutputFormat`, `OutputChunk`, `OutputSynthesis`, `OutputSpec`
- **Service:** `OutputEngineService` with format determination
- **ATRS Events:** `output.received`, `output.synthesised`

### Component K: Quality Gate
- **Models:** `GateOutcome`, `QualityMetrics`, `GateEvaluation`, `GateConfig`
- **Service:** `QualityGateService` with dimension evaluation
- **ATRS Events:** `gate.evaluated`, `gate.rejected_retry`

### Component L: Central Orchestrator
- **Models:** `MessageIntent`, `PipelinePhase`, `ExecutionContext`, `OrchestratorResult`
- **Service:** `OrchestratorService` with 10-phase pipeline
- **ATRS Events:** `orchestrator.completed`

### Component M: Notification Engine
- **Models:** `Notification`, `NotificationPriority`, `NotificationStatus`
- **Service:** `NotificationEngineService` with priority routing and quiet hours
- **Database:** `notifications` table with priority/status indexes
- **ATRS Events:** `notification.received`, `notification.delivered`

### Component N: Recommender Engine
- **Models:** `Recommendation`, `RecommendationDomain`, `RecommendationStatus`
- **Service:** `RecommenderEngineService` with observer-style suggestions
- **Database:** `recommendations` table with status index
- **ATRS Events:** `recommendation.fired`, `recommendation.accepted`, `recommendation.dismissed`