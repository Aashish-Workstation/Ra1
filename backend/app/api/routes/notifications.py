from fastapi import APIRouter

router = APIRouter()

@router.get("/")
async def list_notifications(user_id: str):
    return [
        {
            "id": "1",
            "priority": "P2_INFORM",
            "title": "Model switched",
            "message": "Switched to gpt-4o for better coherence",
            "read": False,
            "created_at": "2024-01-01T00:00:00Z"
        }
    ]

@router.patch("/{notification_id}")
async def update_notification(notification_id: str, user_id: str, read: bool = True):
    return {"updated": True}