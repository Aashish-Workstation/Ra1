from fastapi import APIRouter
import uuid

router = APIRouter()

@router.get("/")
async def list_threads(user_id: str):
    return []

@router.post("/")
async def create_thread(user_id: str):
    thread_id = str(uuid.uuid4())
    return {"thread_id": thread_id, "active_node_id": thread_id, "nodes": {}}

@router.get("/{thread_id}")
async def get_thread(thread_id: str, user_id: str):
    return {
        "thread_id": thread_id,
        "root_node_id": thread_id,
        "active_node_id": thread_id,
        "nodes": {},
        "branch_points": []
    }

@router.delete("/{thread_id}")
async def delete_thread(thread_id: str, user_id: str):
    return {"deleted": True}