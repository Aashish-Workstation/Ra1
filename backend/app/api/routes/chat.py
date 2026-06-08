from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from typing import Optional
import uuid

from app.services.orchestrator import OrchestratorService
from app.core.atrs import ATRSService
from app.services.input_engine import InputEngineService
from app.services/context_assembler import ContextAssemblerService
from app.services/model_engine import ModelEngineService
from app.services/safety_engine import SafetyEngineService
from app.services/output_engine import OutputEngineService
from app.services/memory_engine import MemoryEngineService
from app.services.quality_gate import QualityGateService

router = APIRouter()

def get_atrs() -> ATRSService:
    return ATRSService()

def get_input_service(atrs: ATRSService = Depends(get_atrs)) -> InputEngineService:
    return InputEngineService()

def get_context_service(atrs: ATRSService = Depends(get_atrs)) -> ContextAssemblerService:
    return ContextAssemblerService(atrs)

def get_model_service(atrs: ATRSService = Depends(get_atrs)) -> ModelEngineService:
    return ModelEngineService(atrs)

def get_safety_service(atrs: ATRSService = Depends(get_atrs)) -> SafetyEngineService:
    return SafetyEngineService(atrs)

def get_output_service(atrs: ATRSService = Depends(get_atrs)) -> OutputEngineService:
    return OutputEngineService(atrs)

def get_memory_service(atrs: ATRSService = Depends(get_atrs)) -> MemoryEngineService:
    return MemoryEngineService(atrs)

def get_gate_service(atrs: ATRSService = Depends(get_atrs)) -> QualityGateService:
    return QualityGateService(atrs)

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
        input_normalizer=input_service.normalize_input,
        context_assembler=context_service.assemble,
        model_executor=model_service.execute,
        safety_evaluator=safety_service.evaluate,
        output_synthesizer=output_service.synthesize,
        memory_committer=memory_service.commit,
        gate_evaluator=gate_service.evaluate,
    )

def get_current_user_id() -> str:
    return "default-user"

@router.post("/process")
async def process_message(
    message: str,
    user_id: str = Depends(get_current_user_id),
    thread_id: Optional[str] = None,
    habitat_id: Optional[str] = None,
    orchestrator: OrchestratorService = Depends(get_orchestrator),
):
    result = await orchestrator.process(
        user_id=uuid.UUID(user_id),
        text=message,
        session_id=uuid.UUID(thread_id) if thread_id else None,
        habitat_id=uuid.UUID(habitat_id) if habitat_id else None,
    )
    return result.model_dump()

@router.get("/stream")
async def stream_response(
    request: Request,
    thread_id: str,
    user_id: str = Depends(get_current_user_id),
):
    async def generate():
        yield "data: {\"type\": \"start\", \"thread_id\": \"" + thread_id + "\"}\n\n"
        yield "data: {\"type\": \"chunk\", \"content\": \"Hello\"}\n\n"
        yield "data: {\"type\": \"end\"}\n\n"
    
    return StreamingResponse(generate(), media_type="text/event-stream")

@router.get("/health")
async def health():
    return {"status": "ok"}