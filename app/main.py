from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, Depends, Query
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from app.config import settings
from app.routes import auth, feed
from app.database import engine
from app.models import Base, Message, User
from app.services.auth import verify_token
from app.database import get_db
from app.utils.text import linkify_content
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import desc, or_
from sqlalchemy.orm import selectinload

@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    # Rebuild hashtag cache
    from app.services.feed import rebuild_cache
    from app.database import AsyncSessionLocal
    
    async with AsyncSessionLocal() as session:
        await rebuild_cache(session)
        
    yield

app = FastAPI(title="NeurIPS Whisper", lifespan=lifespan)
app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")

app.include_router(auth.router)
app.include_router(feed.router)

@app.get("/")
async def root(request: Request, tags: list[str] = Query(None), msg: int = None, db: AsyncSession = Depends(get_db)):
    user = None
    token = request.cookies.get("access_token")
    if token:
        # Token format is "Bearer <token>"
        try:
            scheme, _, param = token.partition(" ")
            if scheme.lower() == "bearer":
                payload = verify_token(param)
                if payload:
                    user = payload.get("sub")
        except Exception:
            pass
    
    # Fetch focused message if msg id is provided
    focused_message = None
    if msg:
        result = await db.execute(select(Message, User).join(User).filter(Message.id == msg))
        row = result.first()
        if row:
            message, msg_user = row
            try:
                formatted_time = message.created_at.strftime("%H:%M")
            except:
                formatted_time = str(message.created_at)
            
            focused_message = {
                "id": message.id,
                "content": linkify_content(message.content),
                "created_at": formatted_time,
                "author": msg_user.email if msg_user else "Unknown"
            }

    # Fetch latest messages
    # Recursive function to format messages
    from sqlalchemy import inspect
    def format_message_recursive(msg):
        try:
            formatted_time = msg.created_at.strftime("%H:%M")
        except:
            formatted_time = str(msg.created_at)
            
        replies = []
        # Check if 'replies' is loaded to avoid MissingGreenlet error
        if "replies" not in inspect(msg).unloaded:
            replies = [format_message_recursive(reply) for reply in msg.replies]
            
        return {
            "id": msg.id,
            "content": linkify_content(msg.content),
            "created_at": formatted_time,
            "author": msg.user.email if msg.user else "Unknown",
            "replies": replies
        }

    query = select(Message).options(
        selectinload(Message.user),
        selectinload(Message.replies).selectinload(Message.user),
        selectinload(Message.replies).selectinload(Message.replies).selectinload(Message.user),
        selectinload(Message.replies).selectinload(Message.replies).selectinload(Message.replies).selectinload(Message.user),
        selectinload(Message.replies).selectinload(Message.replies).selectinload(Message.replies).selectinload(Message.replies).selectinload(Message.user)
    ).filter(Message.parent_id == None)
    
    if tags:
        conditions = [Message.content.contains(f"#{tag}") for tag in tags]
        query = query.filter(or_(*conditions))
        
    query = query.order_by(desc(Message.created_at)).limit(30)
        
    result = await db.execute(query)
    rows = result.scalars().all()
    
    messages = [format_message_recursive(msg) for msg in rows]
            
    tags_query = "&".join([f"tags={t}" for t in tags]) if tags else ""
    
    return templates.TemplateResponse("index.html", {
        "request": request, 
        "user": user, 
        "tags": tags,
        "tags_query": tags_query,
        "messages": messages,
        "focused_message": focused_message
    })
