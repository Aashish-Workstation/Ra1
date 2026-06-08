from fastapi import APIRouter, UploadFile, File
import uuid

router = APIRouter()

@router.get("/")
async def list_knowledge(user_id: str):
    return []

@router.post("/")
async def upload_document(user_id: str, file: UploadFile = File(...)):
    content = await file.read()
    return {"item_id": str(uuid.uuid4()), "filename": file.filename}

@router.delete("/{item_id}")
async def delete_item(item_id: str, user_id: str):
    return {"deleted": True}