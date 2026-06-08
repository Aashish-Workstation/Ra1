# Memory Engine & Node — Implementation Plan

## Component D: Memory Engine & Node (Knowledge Palace)

### Overview
The Memory Engine functions as a living, confidence-scored knowledge palace with:
- **Memory Node**: Database schema for atomic knowledge records
- **Memory Engine**: Stateless execution layer managed via Knowledge Arbitration Core (KAC)
- **Knowledge Tiers & Lanes**: Logical categorization with confidence-based decay

---

## 1. Atomic Record Schema (Memory Node)

### Database Table: `memory_records`

| Field | Type | Description |
|-------|------|-------------|
| `entity_id` | UUID | Primary Key |
| `habitat_id` | UUID | Isolates chat workspaces |
| `user_id` | UUID | Owner/member context |
| `entity_type` | TEXT | What the fact is about (e.g., "user_preference", "fact") |
| `attribute` | TEXT | Specific attribute (e.g., "name", "timezone") |
| `value` | JSONB | Typed knowledge value |
| `knowledge_type` | TEXT | Enum: `FACT`, `DERIVED_FACT`, `HYPOTHESIS`, `OPINION`, `RECOMMENDATION`, `PROCEDURE`, `TRACE` |
| `confidence` | REAL | Float 0.0 - 1.0 |
| `source` | TEXT | Enum: `user`, `connector`, `agent`, `flow`, `inference` |
| `provenance` | TEXT | Reference to session/interaction |
| `ttl` | TIMESTAMPTZ | Nullable expiration |
| `lock_status` | BOOLEAN | User-locked (immutable to engines) |
| `links` | JSONB | Connections to other entity IDs |

### Knowledge Tiers
- **T1 (Working)**: Current thread state
- **T2 (Episodic)**: Session history
- **T3 (Semantic)**: Vector data (text search index if PGVector unavailable)
- **T4 (External)**: External data sources

### Knowledge Lanes (Confidence Thresholds)
- **TEMP**: Session-scoped, dissolves on session end
- **SHORT**: Confidence ≥ 0.5, eligible for time-based decay
- **LONG**: Confidence ≥ 0.7, slower decay
- **SUPER**: Confidence ≥ 0.95, permanent, never decays

---

## 2. Knowledge Arbitration Core (KAC) & Service Rules

### MemoryEngineService (Stateless)
All state persists in the database Node. The engine is stateless.

### KAC Pipeline (Every Write)
1. Evaluate incoming payload
2. Update confidence if fact is reinforced
3. Handle conflict detection (opposing assertions)
4. Commit or reject write

### Rules
- User-locked records (`lock_status=true`) cannot be modified by engines
- Read operations return scoped view matching `user_id` and `habitat_id`

### ATRS Logging
- `memory.write.proposed`
- `memory.write.committed`
- `memory.write.rejected`
- `memory.read`
- `memory.conflict.detected`

---

## 3. Implementation Steps

### Step 1: Database Schema
**File**: `services/infra/postgres-init.sql`
```sql
CREATE TABLE IF NOT EXISTS memory_records (
    entity_id       UUID         PRIMARY KEY,
    habitat_id      UUID         NOT NULL,
    user_id         UUID         NOT NULL,
    entity_type     TEXT         NOT NULL,
    attribute       TEXT         NOT NULL,
    value           JSONB        NOT NULL,
    knowledge_type  TEXT         NOT NULL,
    confidence      REAL         NOT NULL DEFAULT 0.5,
    source          TEXT         NOT NULL,
    provenance      TEXT         NOT NULL,
    ttl             TIMESTAMPTZ  NULL,
    lock_status     BOOLEAN      NOT NULL DEFAULT FALSE,
    links           JSONB        NOT NULL DEFAULT '{}',
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
    CONSTRAINT memory_records_knowledge_type_chk 
        CHECK (knowledge_type IN ('FACT','DERIVED_FACT','HYPOTHESIS','OPINION','RECOMMENDATION','PROCEDURE','TRACE')),
    CONSTRAINT memory_records_source_chk 
        CHECK (source IN ('user','connector','agent','flow','inference')),
    CONSTRAINT memory_records_confidence_range 
        CHECK (confidence >= 0.0 AND confidence <= 1.0)
);

CREATE INDEX IF NOT EXISTS memory_records_habitat_idx ON memory_records (habitat_id);
CREATE INDEX IF NOT EXISTS memory_records_user_idx ON memory_records (user_id);
CREATE INDEX IF NOT EXISTS memory_records_entity_type_idx ON memory_records (entity_type);
CREATE INDEX IF NOT EXISTS memory_records_confidence_idx ON memory_records (confidence);
```

### Step 2: Pydantic Models
**File**: `backend/app/models/memory.py`

- `KnowledgeType` enum
- `MemorySource` enum  
- `KnowledgeLane` enum (TEMP, SHORT, LONG, SUPER)
- `MemoryRecord` (storage model)
- `MemoryRecordCreate` (input)
- `MemoryRecordRead` (output)
- `MemoryConflict` (conflict detection)

### Step 3: Memory Engine Service
**File**: `backend/app/services/memory_engine.py`

- `MemoryEngineService` class (stateless)
- `KAC` (Knowledge Arbitration Core) pipeline
- Methods: `propose()`, `commit()`, `read()`, `list_for_scope()`
- Lock status enforcement
- Confidence promotion logic
- Conflict detection

### Step 4: ATRS Event Types
**File**: `backend/app/models/atrs.py`

Add to `ATRSMemoryEvent` enum:
- `MEMORY_WRITE_PROPOSED = "memory.write.proposed"`
- `MEMORY_WRITE_COMMITTED = "memory.write.committed"`
- `MEMORY_WRITE_REJECTED = "memory.write.rejected"`
- `MEMORY_READ = "memory.read"`
- `MEMORY_CONFLICT_DETECTED = "memory.conflict.detected"`

### Step 5: Unit Tests
**File**: `backend/tests/test_memory_engine.py`

1. Test KAC blocks edits to locked records
2. Test confidence score changes promote records across lanes
3. Test conflicting facts trigger conflict detection and ATRS logging

### Step 6: Fixtures
**File**: `backend/tests/conftest.py`

- Add `memory_records` table to `FakePool`
- Add `make_memory` fixture
- Add memory-specific adapters

---

## 4. File Deliverables

| File | Status |
|------|--------|
| `backend/app/models/memory.py` | ⬜ |
| `backend/app/services/memory_engine.py` | ⬜ |
| `backend/tests/test_memory_engine.py` | ⬜ |
| `services/infra/postgres-init.sql` | ⬜ (append) |
| `backend/app/models/atrs.py` | ⬜ (extend) |
| `backend/tests/conftest.py` | ⬜ (extend) |

---

## 5. Execution Order

1. Extend `atrs.py` with `ATRSMemoryEvent` enum
2. Create `models/memory.py` with all schemas
3. Update `postgres-init.sql` with `memory_records` table
4. Create `services/memory_engine.py` with KAC pipeline
5. Extend `conftest.py` with memory fixtures
6. Create `tests/test_memory_engine.py` with unit tests
7. Update implementation plan checklist

---

## 6. Key Design Decisions

- **UUID primary key**: Globally unique, supports distributed creation
- **JSONB for value/links**: Flexible schema for varied knowledge types
- **Separate enums**: Clear boundaries for knowledge classification
- **Lock status as boolean**: Simple but effective immutability flag
- **Confidence as REAL**: Native PostgreSQL float, range-checked
- **TTL nullable**: Optional expiration for temporary knowledge