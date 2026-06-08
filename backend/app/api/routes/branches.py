from fastapi import APIRouter
import uuid

router = APIRouter()

@router.post("/")
async def create_branch(parent_id: str, thread_id: str, user_id: str):
    new_node_id = str(uuid.uuid4())
    return {
        "node_id": new_node_id,
        "parent_id": parent_id,
        "children_ids": [],
        "provisional": True
    }

@router.get("/{node_id}/tree")
async def get_tree(node_id: str, thread_id: str, user_id: str):
    return {"nodes": {}, "branch_points": []}