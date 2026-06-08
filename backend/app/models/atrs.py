"""
ATRS — Audit Trace + Replay System (Pydantic schemas + enums).

The schema is *closed*: `event_type` is a typed Enum (Union of all valid event
types across the system), and `entity_ref` is validated against a strict
`<type>:<id>` pattern. The metadata dict is scrubbed by the service layer to
ensure raw credentials are never logged — see `app.core.atrs`.
"""

from __future__ import annotations

import re
import time
import uuid
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


# ── Enums (typed — never freeform) ───────────────────────────────────────────


class ATRSStatus(str, Enum):
    """Outcome of the operation being audited."""
    SUCCESS = "success"
    FAILURE = "failure"
    BLOCKED = "blocked"
    PARTIAL = "partial"


class ATRSEngine(str, Enum):
    """Logical engine / subsystem that produced the event."""
    ATRS        = "atrs"
    VAULT       = "vault"
    ROUTER      = "router"
    FALLBACK    = "fallback"
    FREE_TIER   = "free_tier"
    LANGFUSE    = "langfuse"
    INFISICAL   = "infisical"
    API         = "api"
    CHAT        = "chat"
    SESSION     = "session"
    MEMORY      = "memory"
    PERSONA     = "persona"
    KNOWLEDGE   = "knowledge"
    INPUT       = "input"
    CONTEXT     = "context"
    SAFETY      = "safety"
    OUTPUT      = "output"
    GATE        = "gate"
    ORCHESTRATOR = "orchestrator"
    NOTIFICATION = "notification"
    RECOMMENDER = "recommender"


# ── Event types (one per logical action). All inherit from str so the
#    union type is JSON-serialisable and human-readable in ClickHouse.
#    Adding a new event type = adding a new enum value. ──────────────────────


class ATRSOrchestratorEvent(str, Enum):
    ORCHESTRATOR_COMPLETED = "orchestrator.completed"


class ATRSVaultEvent(str, Enum):
    VAULT_CREATED       = "vault.created"
    VAULT_READ          = "vault.read"
    VAULT_RESOLVED      = "vault.resolved"
    VAULT_ROTATED       = "vault.rotated"
    VAULT_REVOKED       = "vault.revoked"
    VAULT_LISTED        = "vault.listed"
    VAULT_ACCESS_DENIED = "vault.access_denied"
    VAULT_DECRYPT_FAIL  = "vault.decrypt_fail"


class ATRSRouterEvent(str, Enum):
    ROUTER_ROUTE_SELECTED     = "router.route_selected"
    ROUTER_FALLBACK_TRIGGERED = "router.fallback_triggered"
    ROUTER_ALL_FAILED         = "router.all_failed"
    ROUTER_COOLDOWN_SET       = "router.cooldown_set"


class ATRSFreeTierEvent(str, Enum):
    FREE_TIER_QUOTA_CHECK    = "free_tier.quota_check"
    FREE_TIER_QUOTA_EXHAUSTED = "free_tier.quota_exhausted"
    FREE_TIER_USAGE_RECORDED = "free_tier.usage_recorded"


class ATRSSessionEvent(str, Enum):
    SESSION_STARTED = "session.started"
    SESSION_ENDED   = "session.ended"
    SESSION_ERROR   = "session.error"


class ATRSModelEvent(str, Enum):
    MODEL_CALL_START       = "model.call.start"
    MODEL_CALL_SUCCESS     = "model.call.success"
    MODEL_CALL_FAILURE     = "model.call.failure"
    MODEL_FALLBACK_TRIGGERED = "model.fallback.triggered"


class ATRSAPIEvent(str, Enum):
    API_REQUEST      = "api.request"
    API_RESPONSE     = "api.response"
    API_ERROR        = "api.error"
    API_RATE_LIMITED = "api.rate_limited"


class ATRSChatEvent(str, Enum):
    CHAT_MESSAGE_SENT     = "chat.message_sent"
    CHAT_MESSAGE_RECEIVED = "chat.message_received"
    CHAT_STREAM_STARTED   = "chat.stream_started"
    CHAT_STREAM_ENDED     = "chat.stream_ended"


class ATRSAtrsEvent(str, Enum):
    ATRS_RECORDED   = "atrs.recorded"
    ATRS_REPLAYED   = "atrs.replayed"
    ATRS_DROPPED    = "atrs.dropped"
    ATRS_SCRUB_HIT  = "atrs.scrub_hit"  # metadata scrubber rejected a forbidden key


class ATRSMemoryEvent(str, Enum):
    MEMORY_WRITE_PROPOSED = "memory.write.proposed"
    MEMORY_WRITE_COMMITTED = "memory.write.committed"
    MEMORY_WRITE_REJECTED = "memory.write.rejected"
    MEMORY_READ = "memory.read"
    MEMORY_CONFLICT_DETECTED = "memory.conflict.detected"


class ATRSPersonaEvent(str, Enum):
    PERSONA_LOADED = "persona.loaded"
    PERSONA_BLEND_UPDATED = "persona.blend.updated"
    PERSONA_SWITCH_MANUAL = "persona.switch.manual"


class ATRSKnowledgeEvent(str, Enum):
    SEARCH_RECEIVED = "search.received"
    SEARCH_RESULTS_RETURNED = "search.results_returned"


class ATRSInputEvent(str, Enum):
    INPUT_RECEIVED = "input.received"
    INPUT_PAYLOAD_ASSEMBLED = "input.payload.assembled"


class ATRSContextEvent(str, Enum):
    CONTEXT_FETCH_SPEC_RECEIVED = "context.fetch_spec_received"
    CONTEXT_ASSEMBLED = "context.assembled"


class ATRSSafetyEvent(str, Enum):
    SAFETY_EVALUATED = "safety.evaluated"
    SAFETY_BLOCKED = "safety.blocked"


class ATRSEventEvent(str, Enum):
    EVENT_RECEIVED = "event.received"


class ATSROutputEvent(str, Enum):
    OUTPUT_RECEIVED = "output.received"
    OUTPUT_SYNTHESISED = "output.synthesised"


class ATRSGateEvent(str, Enum):
    GATE_EVALUATED = "gate.evaluated"
    GATE_REJECTED_RETRY = "gate.rejected_retry"


class ATRSNotificationEvent(str, Enum):
    NOTIFICATION_RECEIVED = "notification.received"
    NOTIFICATION_DELIVERED = "notification.delivered"


class ATRSRecommenderEvent(str, Enum):
    RECOMMENDATION_FIRED = "recommendation.fired"
    RECOMMENDATION_ACCEPTED = "recommendation.accepted"
    RECOMMENDATION_DISMISSED = "recommendation.dismissed"


# Public type alias: any event type the system can emit. ``record()`` validates
# against this union.
ATRSEventType = (
    ATRSVaultEvent
    | ATRSRouterEvent
    | ATRSFreeTierEvent
    | ATRSSessionEvent
    | ATRSModelEvent
    | ATRSAPIEvent
    | ATRSChatEvent
    | ATRSAtrsEvent
    | ATRSMemoryEvent
    | ATRSPersonaEvent
    | ATRSKnowledgeEvent
    | ATRSInputEvent
    | ATRSContextEvent
    | ATRSSafetyEvent
    | ATRSEventEvent
    | ATSROutputEvent
    | ATRSGateEvent
    | ATRSOrchestratorEvent
    | ATRSNotificationEvent
    | ATRSRecommenderEvent
)

# Compile a set of all valid event values for fast membership checks.
_VALID_EVENT_VALUES: frozenset[str] = frozenset(
    v.value for enum_cls in (
        ATRSVaultEvent,
        ATRSRouterEvent,
        ATRSFreeTierEvent,
        ATRSSessionEvent,
        ATRSModelEvent,
        ATRSAPIEvent,
        ATRSChatEvent,
        ATRSAtrsEvent,
        ATRSMemoryEvent,
        ATRSPersonaEvent,
        ATRSKnowledgeEvent,
        ATRSInputEvent,
        ATRSContextEvent,
        ATRSSafetyEvent,
        ATRSEventEvent,
        ATSROutputEvent,
        ATRSGateEvent,
        ATRSOrchestratorEvent,
        ATRSNotificationEvent,
        ATRSRecommenderEvent,
    ) for v in enum_cls
)


# ── entity_ref pattern: <type>:<id> — IDs only, no raw values. ──────────────

# Examples:  vault:550e8400-e29b-41d4-a716-446655440000
#            record:abc-123
#            session:xyz
_ENTITY_REF_RE = re.compile(r"^[a-z][a-z0-9_]{0,31}:[A-Za-z0-9_\-:.]{1,128}$")


def is_valid_entity_ref(value: str) -> bool:
    """True iff ``value`` matches the strict ``<type>:<id>`` pattern."""
    return bool(_ENTITY_REF_RE.match(value))


# ── The single Pydantic model that goes through ``record()``. ──────────────


class ATRSLogEntry(BaseModel):
    """One row in the ATRS append-only log.

    Field names match the spec EXACTLY. Use ``metadata`` for any extra
    context — but the service layer will scrub it for forbidden keys.
    """

    model_config = ConfigDict(extra="forbid", use_enum_values=False)

    log_id:      uuid.UUID = Field(default_factory=uuid.uuid4)
    timestamp:   int       = Field(default_factory=lambda: int(time.time() * 1000))
    session_id:  Optional[str] = None
    habitat_id:  Optional[str] = None
    engine:      ATRSEngine
    event_type:  ATRSEventType
    entity_ref:  Optional[str] = None
    status:      ATRSStatus
    duration_ms: Optional[int] = None
    error_code:  Optional[str] = None
    metadata:    dict[str, Any] = Field(default_factory=dict)

    # ── Validators ────────────────────────────────────────────────────────

    @field_validator("event_type", mode="before")
    @classmethod
    def _coerce_event_type(cls, value: Any) -> Any:
        """Accept either an enum member or a string value, but ONLY strings
        that match one of the registered enum values. Freeform strings are
        rejected."""
        if isinstance(value, str):
            if value not in _VALID_EVENT_VALUES:
                raise ValueError(
                    f"event_type '{value}' is not a registered ATRS event type. "
                    f"Add a new enum value to models.atrs instead of using "
                    f"freeform strings."
                )
            # Find the matching enum class and return the member.
            for enum_cls in (
                ATRSVaultEvent,
                ATRSRouterEvent,
                ATRSFreeTierEvent,
                ATRSSessionEvent,
                ATRSModelEvent,
                ATRSAPIEvent,
                ATRSChatEvent,
                ATRSAtrsEvent,
                ATRSMemoryEvent,
                ATRSPersonaEvent,
                ATRSKnowledgeEvent,
                ATRSInputEvent,
                ATRSContextEvent,
                ATRSSafetyEvent,
                ATRSEventEvent,
                ATSROutputEvent,
                ATRSGateEvent,
                ATRSOrchestratorEvent,
                ATRSNotificationEvent,
                ATRSRecommenderEvent,
            ):
                member = enum_cls.__members__.get(value.replace(".", "_").upper())
                # Try by value lookup too
                for m in enum_cls:
                    if m.value == value:
                        return m
        return value

    @field_validator("entity_ref")
    @classmethod
    def _validate_entity_ref(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        if not is_valid_entity_ref(value):
            raise ValueError(
                f"entity_ref '{value}' does not match required pattern "
                f"'<type>:<id>'. Raw values are never permitted in ATRS — "
                f"log IDs (e.g. 'vault:<uuid>') only."
            )
        return value

    @field_validator("duration_ms")
    @classmethod
    def _validate_duration(cls, value: Optional[int]) -> Optional[int]:
        if value is not None and value < 0:
            raise ValueError("duration_ms must be >= 0")
        return value
