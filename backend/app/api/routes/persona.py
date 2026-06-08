from fastapi import APIRouter
from app.models.persona import Archetype

router = APIRouter()

@router.get("/active")
async def get_active_persona(user_id: str):
    return {
        "persona_id": "00000000-0000-0000-0000-000000000000",
        "user_id": user_id,
        "name": "Default Persona",
        "profession": "AI Assistant",
        "industry": "Technology",
        "archetype_blend": {a.value: 1.0/8 for a in Archetype},
        "tone_rules": [],
        "rules": [],
        "scope": "global"
    }

@router.put("/")
async def update_persona(user_id: str, blend: dict):
    return {"updated": True}

@router.post("/switch")
async def propose_switch(user_id: str, new_blend: dict):
    return {"should_switch": False, "confidence": 0.5}