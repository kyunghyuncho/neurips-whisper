from fastapi import APIRouter, Depends, HTTPException, Form, Request, Query
from sse_starlette.sse import EventSourceResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import desc, or_
from app.database import get_db
from app.models import Message, User
from app.services.feed import publish_message, subscribe_channel, redis_client
from app.utils.validators import is_valid_url
from app.utils.text import linkify_content
from app.templating import templates
from datetime import datetime
import json
import re
import time

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

    # Fetch user email
    result = await db.execute(select(User).filter(User.id == user_id))
    user = result.scalars().first()
    user_email = user.email if user else "Unknown"

    # Extract and store hashtags
    hashtags = set(re.findall(r"#(\w+)", content))
    if hashtags:
        timestamp = time.time()
        for tag in hashtags:
            # Add to Redis sorted set: score=timestamp, member=tag:msg_id
            await redis_client.zadd("hashtag_activity", {f"{tag}:{message.id}": timestamp})

    # Publish to Redis
    data = {
        "id": message.id,
        "content": message.content,
        "created_at": message.created_at.isoformat(),
        "user_email": user_email
    }
    await publish_message(CHANNEL, data)
    
    from fastapi.responses import JSONResponse
    return JSONResponse(
        content={"message": "Message posted"},
        headers={"HX-Trigger": "updateHashtags"}
    )


@router.get("/hashtags")
async def get_hashtags(request: Request, tags: list[str] = Query(None)):
    # Clean old entries (older than 1 hour)
    now = time.time()
    cutoff = now - 3600
    await redis_client.zremrangebyscore("hashtag_activity", "-inf", cutoff)
    
    # Get all active hashtag events
    activity = await redis_client.zrange("hashtag_activity", 0, -1)
    
    counts = {}
    for item in activity:
        # Item format: tag:msg_id
        parts = item.split(":")
        if len(parts) >= 1:
            tag = parts[0]
            counts[tag] = counts.get(tag, 0) + 1
        
    sorted_hashtags = sorted(counts.items(), key=lambda x: x[1], reverse=True)
    
    return templates.TemplateResponse("partials/hashtag_list.html", {
        "request": request,
        "hashtags": sorted_hashtags,
        "selected_tags": tags or []
    })

@router.get("/container")
async def get_feed_container(request: Request, tags: list[str] = Query(None), db: AsyncSession = Depends(get_db)):
    query = select(Message, User).join(User)
    
    if tags:
        conditions = [Message.content.contains(f"#{tag}") for tag in tags]
        query = query.filter(or_(*conditions))
        
    query = query.order_by(desc(Message.created_at)).limit(30)
        
    result = await db.execute(query)
    rows = result.all()
    
    messages = []
    for message, msg_user in rows:
        try:
            formatted_time = message.created_at.strftime("%H:%M")
        except:
            formatted_time = str(message.created_at)
            
        messages.append({
            "id": message.id,
            "content": linkify_content(message.content),
            "created_at": formatted_time,
            "author": msg_user.email if msg_user else "Unknown"
        })
        
    tags_query = "&".join([f"tags={t}" for t in tags]) if tags else ""
        
    return templates.TemplateResponse("partials/feed_container.html", {
        "request": request,
        "messages": messages,
        "tags": tags,
        "tags_query": tags_query
    })

@router.get("/stream")
async def stream_messages(request: Request, tags: list[str] = Query(None)):
    async def event_generator():
        # Stream new messages
        async for message in subscribe_channel(CHANNEL):
            if await request.is_disconnected():
                break
            
            # Message is a JSON string from Redis
            data = json.loads(message)
            
            # Filter by tags if present
            if tags:
                # Show message if it contains ANY of the selected tags
                if not any(f"#{t}" in data["content"] for t in tags):
                    continue
            
            # Render template
            try:
                dt = datetime.fromisoformat(data["created_at"])
                formatted_time = dt.strftime("%H:%M")
            except:
                formatted_time = data["created_at"]

            rendered_html = templates.get_template("partials/feed_item.html").render(
                content=linkify_content(data["content"]),
                created_at=formatted_time,
                author=data.get("user_email", "Anonymous User"),
                id=data["id"]
            )
            
            yield {"data": rendered_html}

    return EventSourceResponse(event_generator())

@router.get("/history")
async def get_history(request: Request, cursor: int = None, tags: list[str] = Query(None), db: AsyncSession = Depends(get_db)):
    if not cursor:
        return "" 
        
    query = select(Message, User).join(User).filter(Message.id < cursor)
    
    if tags:
        conditions = [Message.content.contains(f"#{tag}") for tag in tags]
        query = query.filter(or_(*conditions))
        
    query = query.order_by(desc(Message.created_at)).limit(30)
        
    result = await db.execute(query)
    rows = result.all()
    
    messages = []
    for message, msg_user in rows:
        try:
            formatted_time = message.created_at.strftime("%H:%M")
        except:
            formatted_time = str(message.created_at)
            
        messages.append({
            "id": message.id,
            "content": linkify_content(message.content),
            "created_at": formatted_time,
            "author": msg_user.email if msg_user else "Unknown"
        })
        
    next_cursor = messages[-1]["id"] if messages else None
    
    tags_query = "&".join([f"tags={t}" for t in tags]) if tags else ""
    
    return templates.TemplateResponse("partials/feed_history.html", {
        "request": request,
        "messages": messages,
        "next_cursor": next_cursor,
        "tags": tags,
        "tags_query": tags_query
    })

