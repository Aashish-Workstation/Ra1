from fastapi import APIRouter, Depends, HTTPException
from typing import Optional
import uuid
import os

from app.core import db
from app.core.atrs import ATRSService
from app.services.vault import VaultService, make_vault_row_writer, make_vault_row_reader, make_vault_lister, make_vault_updater, make_credential_access_writer
from app.models.vault import VaultEntryCreate, VaultEntryRead, CredentialType
from app.services.memory_engine import MemoryEngineService
from app.services.persona_engine import PersonaEngineService
from app.services.search_engine import SearchEngineService
from app.services.context_assembler import ContextAssemblerService
from app.services.model_engine import ModelEngineService, make_model_reader
from app.services.safety_engine import SafetyEngineService
from app.services.output_engine import OutputEngineService
from app.services.quality_gate import QualityGateService
from app.services.notification_engine import NotificationEngineService
from app.services.orchestrator import OrchestratorService
from app.services.input_engine import InputEngineService
from app.services import litellm_service

router = APIRouter()

RA1_OWNER_ID = os.environ.get("RA1_OWNER_ID", "")


def get_pool():
    return db.get_pool()


def get_atrs(pool=Depends(get_pool)) -> ATRSService:
    async def _outbox_writer(row: dict) -> None:
        async with pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO atrs_outbox (payload, created_at) VALUES ($1, NOW())",
                row,
            )
    return ATRSService(outbox_writer=_outbox_writer)


def get_vault_service(pool=Depends(get_pool), atrs: ATRSService = Depends(get_atrs)) -> VaultService:
    row_writer = make_vault_row_writer(pool, atrs)
    row_reader = make_vault_row_reader(pool)
    lister = make_vault_lister(pool)
    updater = make_vault_updater(pool)
    cred_log = make_credential_access_writer()
    return VaultService(
        row_writer=row_writer,
        row_reader=row_reader,
        lister=lister,
        updater=updater,
        atrs=atrs,
        credential_access_writer=cred_log,
    )


def get_memory_service(pool=Depends(get_pool), atrs: ATRSService = Depends(get_atrs)) -> MemoryEngineService:
    return MemoryEngineService(
        row_writer=None,
        row_reader=None,
        lister=None,
        updater=None,
        atrs=atrs,
    )


def get_persona_service(pool=Depends(get_pool), atrs: ATRSService = Depends(get_atrs)) -> PersonaEngineService:
    return PersonaEngineService(
        row_reader=None,
        row_writer=None,
        updater=None,
        lister=None,
        atrs=atrs,
    )


def get_search_service(memory_service: MemoryEngineService = Depends(get_memory_service), atrs: ATRSService = Depends(get_atrs)) -> SearchEngineService:
    return SearchEngineService(
        memory_lister=None,
        knowledge_lister=None,
        atrs=atrs,
    )


def get_context_service(
    atrs: ATRSService = Depends(get_atrs),
    memory_service: MemoryEngineService = Depends(get_memory_service),
    search_service: SearchEngineService = Depends(get_search_service),
    persona_service: PersonaEngineService = Depends(get_persona_service),
) -> ContextAssemblerService:
    return ContextAssemblerService(
        atrs=atrs,
        memory_lister=memory_service.list_for_scope,
        search_engine=search_service.search,
        persona_reader=persona_service.load_persona,
    )


def get_model_service(
    pool=Depends(get_pool),
    atrs: ATRSService = Depends(get_atrs),
    vault_service: VaultService = Depends(get_vault_service),
) -> ModelEngineService:
    return ModelEngineService(
        atrs=atrs,
        vault_resolve=vault_service.resolve,
        model_reader=make_model_reader(pool),
        execute_fn=litellm_service.execute_chat_completion,
        owner_id=RA1_OWNER_ID,
    )


def get_safety_service(atrs: ATRSService = Depends(get_atrs)) -> SafetyEngineService:
    return SafetyEngineService(atrs=atrs)


def get_output_service(atrs: ATRSService = Depends(get_atrs)) -> OutputEngineService:
    return OutputEngineService(atrs=atrs)


def get_gate_service(atrs: ATRSService = Depends(get_atrs)) -> QualityGateService:
    return QualityGateService(atrs=atrs)


def get_notification_service(pool=Depends(get_pool), atrs: ATRSService = Depends(get_atrs)) -> NotificationEngineService:
    return NotificationEngineService(
        row_writer=None,
        row_reader=None,
        updater=None,
        atrs=atrs,
    )


def get_input_service(atrs: ATRSService = Depends(get_atrs)) -> InputEngineService:
    return InputEngineService(atrs=atrs)


async def _noop_memory_committer(ctx: dict) -> None:
    pass


def get_orchestrator(
    atrs: ATRSService = Depends(get_atrs),
    input_service: InputEngineService = Depends(get_input_service),
    context_service: ContextAssemblerService = Depends(get_context_service),
    model_service: ModelEngineService = Depends(get_model_service),
    safety_service: SafetyEngineService = Depends(get_safety_service),
    output_service: OutputEngineService = Depends(get_output_service),
    memory_service: MemoryEngineService = Depends(get_memory_service),
    gate_service: QualityGateService = Depends(get_gate_service),
) -> OrchestratorService:
    return OrchestratorService(
        atrs=atrs,
        input_normalizer=input_service.normalize,
        context_assembler=context_service.assemble,
        model_executor=model_service.execute,
        safety_evaluator=safety_service.evaluate_output,
        output_synthesizer=output_service.synthesize,
        memory_committer=_noop_memory_committer,
        gate_evaluator=gate_service.evaluate,
    )


@router.post("/process")
async def process_message(
    message: str,
    orchestrator: OrchestratorService = Depends(get_orchestrator),
):
    result = await orchestrator.process(
        user_id=uuid.UUID(RA1_OWNER_ID) if RA1_OWNER_ID else uuid.uuid4(),
        text=message,
        session_id=None,
        habitat_id=None,
    )
    return result.model_dump()


@router.get("/health")
async def health():
    return {"status": "ok"}