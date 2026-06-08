from fastapi import APIRouter

router = APIRouter()

@router.get("/")
async def list_memory(user_id: str):
    return []

@router.delete("/{record_id}")
async def delete_record(record_id: str, user_id: str):
    return {"deleted": True}

@router.patch("/{record_id}/lock")
async def toggle_lock(record_id: str, user_id: str, locked: bool):
    return {"locked": locked}