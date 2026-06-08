# Notification Engine & Recommender Engine — Implementation Plan

## Overview
This plan covers the final two components for the RA1 backend proactive intelligence layer:
- **Component M: Notification Engine** — System-level state flags, exceptions, and blocks routing
- **Component N: Recommender Engine** — Non-blocking architectural optimization suggestions

---

## Component M: Notification Engine

### 1. Data Model (`backend/app/models/notification.py`)

```python
class NotificationPriority(str, Enum):
    P0_BLOCK = "P0_BLOCK"
    P1_URGENT = "P1_URGENT"
    P2_INFORM = "P2_INFORM"
    P3_NOTICE = "P3_NOTICE"
    P_SILENT = "P_SILENT"

class NotificationStatus(str, Enum):
    QUEUED = "queued"
    DELIVERED = "delivered"
    RESOLVED = "resolved"

class Notification(BaseModel):
    notification_id: uuid.UUID
    user_id: uuid.UUID
    habitat_id: uuid.UUID
    priority: NotificationPriority
    source_engine: str
    title: str
    message: str
    status: NotificationStatus
    created_at: datetime
```

### 2. Service (`backend/app/services/notification_engine.py`)

**Core Responsibilities:**
- Priority routing logic
- Quiet hours window mechanism
- ATRS integration

**Priority Routing Rules:**
| Priority | Behavior |
|----------|----------|
| P0_BLOCK | Immediate delivery, bypass all controls |
| P1_URGENT | Immediate delivery |
| P2_INFORM | Respect quiet hours (queued if active) |
| P3_NOTICE | Respect quiet hours (queued if active) |
| P_SILENT | Never deliver, metadata only |

**Quiet Hours Mechanism:**
- Default window: 22:00 - 08:00 local time (configurable)
- Lower priority (P2, P3, P_SILENT) notifications queued during quiet hours
- Bundled delivery on quiet hours exit

### 3. ATRS Events
- `notification.received` — When notification is created
- `notification.delivered` — When notification is delivered (after quiet hours check)

### 4. Database Schema (`services/infra/postgres-init.sql`)
```sql
CREATE TABLE IF NOT EXISTS notifications (
    notification_id UUID PRIMARY KEY,
    user_id UUID NOT NULL,
    habitat_id UUID,
    priority TEXT NOT NULL CHECK (priority IN ('P0_BLOCK','P1_URGENT','P2_INFORM','P3_NOTICE','P_SILENT')),
    source_engine TEXT NOT NULL,
    title TEXT NOT NULL,
    message TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'queued' CHECK (status IN ('queued','delivered','resolved')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS notifications_user_idx ON notifications (user_id);
CREATE INDEX IF NOT EXISTS notifications_status_idx ON notifications (status);
```

---

## Component N: Recommender Engine

### 1. Data Model (`backend/app/models/recommender.py`)

```python
class RecommendationDomain(str, Enum):
    MODEL = "MODEL"
    PERSONA = "PERSONA"
    SKILLS = "SKILLS"
    ENVIRONMENT = "ENVIRONMENT"

class RecommendationStatus(str, Enum):
    ACTIVE = "active"
    ACCEPTED = "accepted"
    DISMISSED = "dismissed"

class Recommendation(BaseModel):
    recommendation_id: uuid.UUID
    user_id: uuid.UUID
    habitat_id: uuid.UUID
    domain: RecommendationDomain
    suggestion_text: str
    trigger_context: dict[str, Any]
    status: RecommendationStatus
    created_at: datetime
```

### 2. Service (`backend/app/services/recommender_engine.py`)

**Observer-Style Suggestion Routines:**

#### Model Domain
- Analyze recent ATRS logs for `model.call.failure` events
- Calculate failure rate per model over last N calls
- If failure rate > 10% threshold, suggest:
  - Cost/reliability switch optimization
  - Explicit fallback model change
- ATRS logging: `recommendation.fired`

#### Persona Domain
- Check current archetype balances
- Detect significant intent signal drift
- Suggest blend modifications when:
  - Any archetype weight crosses 15% threshold
  - New intent patterns detected

**Dismissal Enforcement:**
- Once `dismissed`, recommendation tracked in session context
- Dismissed IDs stored in-memory per execution context
- Query filter excludes dismissed recommendations from queries

### 3. ATRS Events
- `recommendation.fired` — New suggestion generated
- `recommendation.accepted` — User accepted suggestion
- `recommendation.dismissed` — User dismissed suggestion

### 4. Database Schema (`services/infra/postgres-init.sql`)
```sql
CREATE TABLE IF NOT EXISTS recommendations (
    recommendation_id UUID PRIMARY KEY,
    user_id UUID NOT NULL,
    habitat_id UUID,
    domain TEXT NOT NULL CHECK (domain IN ('MODEL','PERSONA','SKILLS','ENVIRONMENT')),
    suggestion_text TEXT NOT NULL,
    trigger_context JSONB NOT NULL,
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','accepted','dismissed')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS recommendations_user_idx ON recommendations (user_id);
CREATE INDEX IF NOT EXISTS recommendations_status_idx ON recommendations (status);
```

---

## 5. Integration Points

### System Error Hooks
- Model Engine failures → Notification Engine (P1_URGENT)
- Vault access failures → Notification Engine (P1_URGENT)
- Memory conflicts → Notification Engine (P2_INFORM)

### ATRS Integration
Both engines integrate with existing `ATRSService` in `app/core/atrs.py`.

---

## 6. Unit Test Requirements

### Notification Engine Tests
| Test | Description |
|------|-------------|
| `test_p0_bypasses_quiet_hours` | P0_BLOCK notification is immediately delivered even during quiet hours |
| `test_p2_held_during_quiet_hours` | P2_INFORM notification is queued during quiet hours window |
| `test_p1_delivered_immediately` | P1_URGENT notification bypasses quiet hours |
| `test_notification_status_transitions` | Verify queued → delivered transitions |
| `test_atrs_logging` | Verify notification.received and notification.delivered events |

### Recommender Engine Tests
| Test | Description |
|------|-------------|
| `test_dismissed_recommendations_blocked` | Dismissed recommendations never resurface |
| `test_model_failure_triggers_recommendation` | Simulated ATRS error rate > 10% triggers model recommendation |
| `test_persona_blend_suggestion` | Archetype drift triggers persona suggestion |
| `test_atrs_logging` | Verify recommendation.fired/accepted/dismissed events |

---

## 7. File Deliverables Checklist

### Models
- [ ] `backend/app/models/notification.py`
- [ ] `backend/app/models/recommender.py`

### Services
- [ ] `backend/app/services/notification_engine.py`
- [ ] `backend/app/services/recommender_engine.py`

### Database
- [ ] `services/infra/postgres-init.sql` (append notifications and recommendations tables)

### ATRS Updates
- [ ] `backend/app/models/atrs.py` (add new event enums and ATRSEngine entries)

### Tests
- [ ] `backend/tests/test_notification_engine.py`
- [ ] `backend/tests/test_recommender_engine.py`
- [ ] `backend/tests/conftest.py` (extend with notification and recommendation fixtures)

---

## 8. Implementation Order

1. Extend `atrs.py` with `ATRSNotificationEvent`, `ATRSRecommenderEvent`, and engine enums
2. Create `models/notification.py` with Priority and Status enums
3. Create `models/recommender.py` with Domain and Status enums
4. Update `postgres-init.sql` with notifications and recommendations tables
5. Create `services/notification_engine.py` with priority routing and quiet hours
6. Create `services/recommender_engine.py` with observer-style suggestions
7. Extend `conftest.py` with fixtures for both services
8. Create unit tests for both engines
9. Update this plan with completion status