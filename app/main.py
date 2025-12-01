"""
Main Application Entry Point

This module sets up the FastAPI application with:
- Database initialization on startup
- Static file serving
- Template rendering
- Route registration
- Homepage with message feed and filtering

Key concepts demonstrated:
- Async context managers for application lifecycle
- SQLAlchemy eager loading to avoid N+1 queries
- Recursive data formatting for threaded conversations
"""

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
from app.dependencies import get_optional_user
from app.utils.text import linkify_content
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import desc, or_
from sqlalchemy.orm import selectinload


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan manager - runs on startup and shutdown.
    
    This async context manager:
    1. Runs startup code before 'yield'
    2. Keeps the application running
    3. Runs cleanup code after 'yield' (when app shuts down)
    
    Startup tasks:
    - Create database tables if they don't exist
    - Rebuild hashtag cache from existing messages
    
    Args:
        app: The FastAPI application instance
    """
    # STARTUP: Create database tables
    async with engine.begin() as conn:
        # run_sync() executes synchronous SQLAlchemy code in async context
        # create_all() creates tables for all models that inherit from Base
        await conn.run_sync(Base.metadata.create_all)
    
    # STARTUP: Rebuild hashtag cache for quick hashtag lookups
    from app.services.feed import rebuild_cache
    from app.database import AsyncSessionLocal
    
    async with AsyncSessionLocal() as session:
        # Scan all messages and extract hashtags into Redis cache
        await rebuild_cache(session)
        
    # Application runs here (between yield and context exit)
    yield
    
    # SHUTDOWN: Add any cleanup code here if needed
    # (Currently no cleanup required)


# Create FastAPI application instance
app = FastAPI(title="NeurIPS Whisper", lifespan=lifespan)

# Mount static files (CSS, JS, images) at /static URL
# Files in app/static/ will be accessible at /static/...
app.mount("/static", StaticFiles(directory="app/static"), name="static")

# Template engine for rendering HTML responses
templates = Jinja2Templates(directory="app/templates")

# Register route modules
# All routes in auth.router will be prefixed with /auth
# All routes in feed.router will be prefixed with /feed
app.include_router(auth.router)
app.include_router(feed.router)


@app.get("/")
async def root(
    request: Request,
    tags: list[str] = Query(None),  # Optional hashtag filter: ?tags=ml&tags=neurips
    msg: int = None,  # Optional message ID to focus/highlight: ?msg=123
    user: User | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Homepage route - displays the main message feed.
    
    Features:
    - Shows latest messages with threading (replies to replies)
    - Filters by hashtags if provided in query parameters
    - Highlights a specific message if msg parameter is provided
    - Detects logged-in user from cookie
    
    Args:
        request: FastAPI request object (needed for templates)
        tags: List of hashtags to filter by (optional)
        msg: Message ID to highlight in a modal (optional)
        user: Authenticated user (optional)
        db: Database session (injected by FastAPI)
        
    Returns:
        Rendered HTML template with message data
    """
    starred_ids = set()
    if user:
        # Fetch user with starred messages relationship
        # We need to re-fetch because get_optional_user might not have loaded relationships
        # or we want to be sure we have the latest data
        user_result = await db.execute(
            select(User)
            .filter(User.id == user.id)
            .options(selectinload(User.starred_messages))
        )
        user_obj = user_result.scalars().first()
        if user_obj:
            user = user_obj # Update user object with loaded relationships
            starred_ids = {m.id for m in user.starred_messages}

    # Fetch focused message if msg parameter is provided
    # This is used to show a specific message in a modal/popup
    focused_message = None
    if msg:
        # Fetch the complete thread with all relationships loaded
        # This is similar to what /feed/thread/ does but for server-side rendering
        query = select(Message).options(
            selectinload(Message.user),
            selectinload(Message.replies).selectinload(Message.user),
            selectinload(Message.replies).selectinload(Message.replies).selectinload(Message.user),
            selectinload(Message.replies).selectinload(Message.replies).selectinload(Message.replies).selectinload(Message.user),
            selectinload(Message.replies).selectinload(Message.replies).selectinload(Message.replies).selectinload(Message.replies).selectinload(Message.user)
        ).filter(Message.id == msg)
        
        result = await db.execute(query)
        message = result.scalars().first()
        
        if message:
            # Inline formatting for focused message
            try:
                formatted_time = message.created_at.strftime("%H:%M")
            except:
                formatted_time = str(message.created_at)
            
            # Build focused message dictionary with all necessary fields
            focused_message = {
                "id": message.id,
                "content": linkify_content(message.content),
                "created_at": formatted_time,
                "author": message.user.email if message.user else "Unknown",
                "user_id": message.user_id if message.user else None,
                "is_starred": message.id in starred_ids
            }

    # Recursive helper function to format messages with their reply threads
    from sqlalchemy import inspect
    
    def format_message_recursive(msg):
        """
        Recursively format a message and all its replies.
        
        This handles nested conversations of arbitrary depth.
        For example: Message -> Reply -> Reply to Reply -> etc.
        
        Args:
            msg: Message ORM object with relationships loaded
            
        Returns:
            Dictionary with formatted message data and nested replies
        """
        # Format timestamp
        try:
            formatted_time = msg.created_at.strftime("%H:%M")
        except:
            formatted_time = str(msg.created_at)
        
        replies = []
        # Check if 'replies' relationship is loaded to avoid lazy-loading errors
        # In async context, lazy loading would cause "MissingGreenlet" errors
        if "replies" not in inspect(msg).unloaded:
            # Recursively format each reply
            replies = [format_message_recursive(reply) for reply in msg.replies]
        
        return {
            "id": msg.id,
            "content": linkify_content(msg.content),  # Make URLs clickable
            "created_at": formatted_time,
            "author": msg.user.email if msg.user else "Unknown",
            "replies": replies,  # Nested list of reply dictionaries
            "is_starred": msg.id in starred_ids,
            "user_id": msg.user_id if msg.user else None
        }

    # Build query for main feed messages
    # selectinload() eagerly loads relationships to avoid N+1 query problem
    # We load up to 4 levels deep of nested replies
    query = select(Message).options(
        # Load the message author
        selectinload(Message.user),
        # Load first-level replies and their authors
        selectinload(Message.replies).selectinload(Message.user),
        # Load second-level replies and their authors
        selectinload(Message.replies).selectinload(Message.replies).selectinload(Message.user),
        # Load third-level replies and their authors
        selectinload(Message.replies).selectinload(Message.replies).selectinload(Message.replies).selectinload(Message.user),
        # Load fourth-level replies and their authors
        selectinload(Message.replies).selectinload(Message.replies).selectinload(Message.replies).selectinload(Message.replies).selectinload(Message.user)
    ).filter(Message.parent_id == None)  # Only get top-level messages (not replies)
    
    # Apply hashtag filtering if tags are provided
    if tags:
        # Build OR conditions: message contains #tag1 OR #tag2 OR ...
        conditions = [Message.content.contains(f"#{tag}") for tag in tags]
        query = query.filter(or_(*conditions))
    
    # Order by newest first and limit to 30 messages
    query = query.order_by(desc(Message.created_at)).limit(30)
    
    # Execute query and get all results
    result = await db.execute(query)
    rows = result.scalars().all()
    
    # Format all messages recursively (including their reply threads)
    messages = [format_message_recursive(msg) for msg in rows]
    
    # Build query string for hashtag links (e.g., "tags=ml&tags=neurips")
    tags_query = "&".join([f"tags={t}" for t in tags]) if tags else ""
    
    # Render template with all the data
    return templates.TemplateResponse("index.html", {
        "request": request,  # Required by Jinja2Templates
        "user": user,  # Logged-in user object or None
        "tags": tags,  # List of active hashtag filters
        "tags_query": tags_query,  # Query string for hashtag links
        "messages": messages,  # Formatted message list with nested replies
        "focused_message": focused_message  # Message to show in modal, if any
    })
