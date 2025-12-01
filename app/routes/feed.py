from fastapi import APIRouter, Depends, HTTPException, Form, Request
from sse_starlette.sse import EventSourceResponse
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.models import Message, User
from app.services.feed import publish_message, subscribe_channel
from app.utils.validators import is_valid_url
from datetime import datetime
import json

router = APIRouter(prefix="/feed", tags=["feed"])
CHANNEL = "neurips_feed"

@router.post("/post")
async def post_message(
    content: str = Form(...),
    user_id: int = Form(...), # In real app, get from session/token
    db: AsyncSession = Depends(get_db)
):
    if len(content) > 140:
        raise HTTPException(status_code=400, detail="Message too long")
    
    # Check for URLs
    words = content.split()
    for word in words:
        if word.startswith("http") and not is_valid_url(word):
             raise HTTPException(status_code=400, detail="URL not allowed")

    # Save to DB
    message = Message(user_id=user_id, content=content)
    db.add(message)
    await db.commit()
    await db.refresh(message)

    # Publish to Redis
    data = {
        "id": message.id,
        "content": message.content,
        "created_at": message.created_at.isoformat()
    }
    await publish_message(CHANNEL, data)
    
    return {"message": "Message posted"}

@router.get("/stream")
async def stream_messages(request: Request):
    async def event_generator():
        async for message in subscribe_channel(CHANNEL):
            if await request.is_disconnected():
                break
            yield {"data": message}

    return EventSourceResponse(event_generator())
