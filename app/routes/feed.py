"""
Feed Routes - Message Posting, Real-time Streaming, and Filtering

This module handles all feed-related endpoints:
- POST /feed/post: Create new messages (top-level or replies)
- POST /feed/star/{id}: Star/unstar messages
- GET /feed/my_messages: User's posts and starred messages
- GET /feed/thread/{id}: Thread view for conversations
- GET /feed/hashtags: List trending hashtags
- GET /feed/container: Feed content with filters
- GET /feed/stream: Real-time message streaming (SSE)
- GET /feed/history: Load older messages (infinite scroll)

Key patterns demonstrated:
- Server-Sent Events (SSE) for real-time updates
- Redis pub/sub for message broadcasting
- HTMX partial templates for dynamic UI updates
- Hashtag and term caching for performance
"""

from fastapi import APIRouter, Depends, HTTPException, Form, Request, Query
from app.dependencies import get_current_user, get_optional_user
from sse_starlette.sse import EventSourceResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import desc, or_, inspect
from sqlalchemy.orm import selectinload
from app.database import get_db
from app.models import Message, User
from app.services.feed import publish_message, subscribe_channel, redis_client
from app.utils.validators import is_valid_url
from app.utils.text import linkify_content, extract_terms
from app.templating import templates
from datetime import datetime
import json
import re
import time
from app.limiter import limiter
from app.services.audit import log_action
from app.limiter import limiter
from app.services.audit import log_action
from app.models import AuditLog
from app.services.security import check_url_safety


# Router with /feed prefix
router = APIRouter(prefix="/feed", tags=["feed"])

# Redis pub/sub channel for broadcasting new messages
CHANNEL = "neurips_feed"


def format_message_recursive(msg, starred_ids=None):
    """
    Recursively format a message and its replies for template rendering.
    
    This helper function is reused across multiple endpoints to ensure
    consistent message formatting. It handles nested replies and optional
    star status tracking.
    
    Args:
        msg: Message ORM object with relationships loaded
        starred_ids: Optional set of message IDs that are starred by current user
        
    Returns:
        Dict with formatted message data including nested replies
    """
    # Format timestamp consistently across the app
    try:
        formatted_time = msg.created_at.strftime("%H:%M")
    except:
        # Fallback if datetime formatting fails
        formatted_time = str(msg.created_at)
    
    replies = []
    # Check if replies relationship is loaded to avoid lazy-loading errors
    # In async SQLAlchemy, lazy loading would cause "MissingGreenlet" errors
    if "replies" not in inspect(msg).unloaded:
        # Recursively format each reply
        replies = [format_message_recursive(reply, starred_ids) for reply in msg.replies]
    
    # Build message dictionary
    result = {
        "id": msg.id,
        "content": linkify_content(msg.content),  # Convert URLs and hashtags to links
        "created_at": formatted_time,
        "created_at_iso": msg.created_at.isoformat(),
        "author": msg.user.email if msg.user else "Unknown",
        "user_id": msg.user_id if msg.user else None,
        "replies": replies  # Nested list of formatted reply dictionaries
    }
    
    # Add star status if starred_ids set is provided
    if starred_ids is not None:
        result["is_starred"] = msg.id in starred_ids
        
    # Add parent info if available (for unrolled view)
    if msg.parent_id:
        # Check if parent relationship is loaded
        if "parent" not in inspect(msg).unloaded and msg.parent:
            if "user" not in inspect(msg.parent).unloaded and msg.parent.user:
                result["parent_author"] = msg.parent.user.email
    
    return result


@router.post("/post")
@limiter.limit("10/minute")
async def post_message(
    request: Request,
    content: str = Form(...),
    parent_id: int = Form(None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Create a new message (top-level post or reply).
    
    This endpoint:
    1. Validates message length and URLs
    2. Saves message to database
    3. Extracts and caches hashtags and terms in Redis
    4. Broadcasts message to real-time subscribers
    5. Triggers UI updates via HTMX
    
    Args:
        content: Message text (max 140 characters)
        parent_id: ID of parent message if this is a reply, None for top-level
        user: Authenticated user (injected by dependency)
        db: Database session
        
    Returns:
        JSON response with HTMX triggers for UI updates
        
    Raises:
        HTTPException: If message is too long or contains disallowed URLs
    """
    # Validate message length (Twitter-style limit)
    # Use weighted length where URLs count as 1 character
    from app.utils.text import calculate_weighted_length
    if calculate_weighted_length(content) > 140:
        raise HTTPException(status_code=400, detail="Message too long")
    
    # Validate URLs against whitelist
    # Validate URLs and check safety
    words = content.split()
    for word in words:
        if word.startswith("http"):
            if not is_valid_url(word):
                raise HTTPException(status_code=400, detail="Invalid URL format")
            
            # Check safety using VirusTotal
            if not await check_url_safety(word):
                # Redact suspicious URL in the content
                content = content.replace(word, "[SUSPICIOUS LINK]")

    # Save message to database
    message = Message(user_id=user.id, content=content, parent_id=parent_id)
    db.add(message)
    await db.commit()
    await db.refresh(message)  # Refresh to get auto-generated fields

    # Extract and cache hashtags in Redis
    hashtags = set(re.findall(r"#(\w+)", content))
    if hashtags:
        timestamp = time.time()
        for tag in hashtags:
            # Add to sorted set for temporal queries (trending, recent activity)
            await redis_client.zadd("hashtag_activity", {f"{tag}:{message.id}": timestamp})
            # Add to set of all hashtags ever seen
            await redis_client.sadd("all_hashtags", tag)
            # Increment usage counter
            await redis_client.hincrby("hashtag_counts", tag, 1)

    # Extract and cache significant terms (excluding stop words)
    terms = extract_terms(content)
    if terms:
        timestamp = time.time()
        for term in terms:
            # Add to sorted set for search functionality
            await redis_client.zadd("term_activity", {f"{term}:{message.id}": timestamp})
            # Add to set of all terms
            await redis_client.sadd("all_terms", term)
            
    # Cleanup old term activity (keep last 24 hours)
    # This prevents Redis from filling up with old search data
    cutoff = time.time() - 86400  # 24 hours
    await redis_client.zremrangebyscore("term_activity", "-inf", cutoff)


    # Get parent author ID if this is a reply
    parent_author_id = None
    if parent_id:
        parent_msg = await db.execute(select(Message).filter(Message.id == parent_id))
        parent = parent_msg.scalars().first()
        if parent:
            parent_author_id = parent.user_id
            
            # Create notification if replying to someone else
            if parent.user_id != user.id:
                from app.models import Notification
                notification = Notification(
                    user_id=parent.user_id,
                    message_id=message.id
                )
                db.add(notification)
                await db.commit()

    # Broadcast message to real-time subscribers via Redis pub/sub
    data = {
        "id": message.id,
        "content": message.content,
        "created_at": message.created_at.isoformat(),
        "user_email": user.email,
        "user_id": user.id,
        "parent_id": message.parent_id,
        "parent_author_id": parent_author_id
    }
    await publish_message(CHANNEL, data)

    # Return success with HTMX triggers
    # These trigger client-side events to update hashtag list and user's messages
    from fastapi.responses import JSONResponse
    return JSONResponse(
        content={"message": "Message posted"},
        headers={"HX-Trigger": json.dumps({"updateHashtags": True, "updateMyMessages": True, "updateNotifications": True})}
    )


@router.post("/star/{message_id}")
@limiter.limit("60/minute")
async def star_message(
    request: Request,
    message_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Toggle star status for a message.
    
    Users can star messages to save them for later.
    This implements a many-to-many relationship via the star_association table.
    
    Args:
        message_id: ID of message to star/unstar
        user: Authenticated user
        db: Database session
        
    Returns:
        Rendered star button HTML partial with updated state
        
    Raises:
        HTTPException: If user or message not found
    """
    # Re-fetch user with starred_messages relationship loaded
    # The user from get_current_user dependency doesn't have relationships loaded
    result = await db.execute(
        select(User)
        .filter(User.id == user.id)
        .options(selectinload(User.starred_messages))
    )
    user = result.scalars().first()
    
    # Fetch the message
    msg_result = await db.execute(select(Message).filter(Message.id == message_id))
    message = msg_result.scalars().first()
    
    if not user or not message:
        raise HTTPException(status_code=404, detail="User or Message not found")
    
    # Toggle star status
    if message in user.starred_messages:
        # Already starred - remove it
        user.starred_messages.remove(message)
        is_starred = False
    else:
        # Not starred - add it
        user.starred_messages.append(message)
        is_starred = True
    
    await db.commit()
    
    # Return updated star button HTML
    # HTMX will swap this into the page
    return templates.TemplateResponse("partials/star_button.html", {
        "request": {},
        "id": message.id,
        "is_starred": is_starred
    }, headers={"HX-Trigger": "updateMyMessages"})  # Trigger update of "My Messages" panel


@router.delete("/message/{message_id}")
async def delete_message(
    message_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Delete a message (Super User only).
    """
    if not getattr(user, "is_superuser", False):
        raise HTTPException(status_code=403, detail="Not authorized")

    result = await db.execute(select(Message).filter(Message.id == message_id))
    message = result.scalars().first()
    
    if message:
        await db.delete(message)
        await log_action(db, "message_deleted", user.email, {"message_id": message_id, "content_snippet": message.content[:50]})
        await db.commit()
        
    return ""


@router.post("/ban/{user_id}")
async def ban_user(
    user_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Ban a user and delete their account (Super User only).
    """
    if not getattr(user, "is_superuser", False):
        raise HTTPException(status_code=403, detail="Not authorized")

    # Get target user
    result = await db.execute(select(User).filter(User.id == user_id))
    target_user = result.scalars().first()
    
    if target_user:
        # Add to blacklist
        from app.models import BlacklistedEmail
        blacklist_entry = BlacklistedEmail(email=target_user.email, reason="Banned by superuser")
        db.add(blacklist_entry)
        
        # Delete user (cascades to messages)
        await db.delete(target_user)
        await log_action(db, "user_banned", user.email, {"banned_user_id": user_id, "banned_user_email": target_user.email})
        await db.commit()
        
    return "User banned"


@router.get("/my_messages")
@limiter.limit("60/minute")
async def get_my_messages(
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Get messages posted or starred by the current user.
    
    This powers the "My Messages" sidebar panel, showing:
    - Messages the user has posted
    - Messages the user has starred
    
    Results are merged, deduplicated, and sorted by creation time.
    
    Args:
        request: FastAPI request (needed for template)
        user: Authenticated user
        db: Database session
        
    Returns:
        Rendered HTML partial with user's messages
    """
    user_id = user.id
    
    # Query for user's own posts
    user_posts_query = select(Message).filter(Message.user_id == user_id)
    
    # Fetch user with starred messages relationship loaded
    user_result = await db.execute(
        select(User)
        .filter(User.id == user_id)
        .options(
            selectinload(User.starred_messages).selectinload(Message.user)
        )
    )
    user = user_result.scalars().first()
    starred_messages = user.starred_messages if user else []
    
    # Execute user posts query with user relationship loaded
    posts_result = await db.execute(
        user_posts_query.options(selectinload(Message.user))
    )
    user_posts = posts_result.scalars().all()
    
    # Convert to list to avoid side effects and ensure sortability
    starred_messages = list(starred_messages)
    
    # Sort both lists by creation time (newest first)
    user_posts.sort(key=lambda x: x.created_at, reverse=True)
    starred_messages.sort(key=lambda x: x.created_at, reverse=True)
    
    # Helper to format a list of messages
    def format_list(msgs, starred_set):
        formatted = []
        for msg in msgs:
            try:
                formatted_time = msg.created_at.strftime("%H:%M")
            except:
                formatted_time = str(msg.created_at)
            
            formatted.append({
                "id": msg.id,
                "content": linkify_content(msg.content),
                "created_at": formatted_time,
                "created_at_iso": msg.created_at.isoformat(),
                "author": msg.user.email if msg.user else "Unknown",
                "is_starred": msg.id in starred_set
            })
        return formatted

    starred_ids = {m.id for m in starred_messages}
    
    return templates.TemplateResponse("partials/my_messages.html", {
        "request": request,
        "my_messages": format_list(user_posts, starred_ids),
        "starred_messages": format_list(starred_messages, starred_ids),
        "user": user
    })


@router.get("/download")
async def download_data(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Download user data as JSON.
    
    Regular users: Download their own posts and starred messages.
    Superusers: Download all messages in the system.
    """
    data = {}
    
    # Helper to serialize message list
    def serialize_messages(msgs):
        serialized = []
        for msg in msgs:
            serialized.append({
                "id": msg.id,
                "content": msg.content,
                "created_at": msg.created_at.isoformat(),
                "author_email": msg.user.email if msg.user else "Unknown",
                "parent_id": msg.parent_id
            })
        return serialized

    if getattr(user, "is_superuser", False):
        # Superuser: Download everything
        query = select(Message).options(selectinload(Message.user)).order_by(Message.created_at)
        result = await db.execute(query)
        all_messages = result.scalars().all()
        data["all_messages"] = serialize_messages(all_messages)
        await log_action(db, "data_downloaded", user.email, "Full system download by superuser")
        await db.commit()
    else:
        # Regular user: My posts + Starred
        # 1. My posts
        my_posts_query = select(Message).filter(Message.user_id == user.id).options(selectinload(Message.user)).order_by(Message.created_at)
        result = await db.execute(my_posts_query)
        my_posts = result.scalars().all()
        data["my_messages"] = serialize_messages(my_posts)
        
        # 2. Starred messages
        # Need to fetch user with starred_messages loaded
        user_result = await db.execute(
            select(User)
            .filter(User.id == user.id)
            .options(selectinload(User.starred_messages).selectinload(Message.user))
        )
        user_with_stars = user_result.scalars().first()
        starred = user_with_stars.starred_messages if user_with_stars else []
        # Sort starred by created_at
        starred = sorted(starred, key=lambda x: x.created_at)
        data["starred_messages"] = serialize_messages(starred)
        await log_action(db, "data_downloaded", user.email, "User data download")
        await db.commit()

    # Return as JSON file download
    from fastapi.responses import Response
    json_content = json.dumps(data, indent=2)
    
    return Response(
        content=json_content,
        media_type="application/json",
        headers={"Content-Disposition": "attachment; filename=neurips_whisper_data.json"}
    )



@router.get("/audit_logs")
async def get_audit_logs(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Download audit logs as JSONL (Super User only).
    """
    if not getattr(user, "is_superuser", False):
        raise HTTPException(status_code=403, detail="Not authorized")

    # Fetch all logs
    result = await db.execute(select(AuditLog).order_by(desc(AuditLog.created_at)))
    logs = result.scalars().all()
    
    # Serialize to JSONL
    output = ""
    for log in logs:
        entry = {
            "id": log.id,
            "action": log.action,
            "user_email": log.user_email,
            "details": log.details,
            "created_at": log.created_at.isoformat()
        }
        output += json.dumps(entry) + "\n"
        
    # Log this action too
    await log_action(db, "audit_logs_downloaded", user.email, "Audit logs downloaded")
    await db.commit()

    from fastapi.responses import Response
    return Response(
        content=output,
        media_type="application/x-jsonlines",
        headers={"Content-Disposition": "attachment; filename=audit_logs.jsonl"}
    )


@router.get("/thread/{message_id}")

@limiter.limit("60/minute")
async def get_thread(
    request: Request,
    message_id: int,
    db: AsyncSession = Depends(get_db)
):
    """
    Get a complete conversation thread for a message.
    
    This finds the root message of a thread and returns the entire
    conversation tree. Used when clicking a reply to see context.
    
    Args:
        request: FastAPI request
        message_id: ID of any message in the thread
        db: Database session
        
    Returns:
        Rendered thread view HTML with the full conversation
    """
    # Get current user for admin controls
    current_user = await get_optional_user(request, db)
    
    # Find the root message by traversing up the parent chain
    current_id = message_id
    root_id = current_id
    
    # Traverse up to find root (parent_id == None)
    while True:
        res = await db.execute(select(Message).filter(Message.id == current_id))
        msg = res.scalars().first()
        if not msg:
            break
        if msg.parent_id:
            current_id = msg.parent_id
        else:
            root_id = msg.id
            break
    
    # Fetch the entire thread from root with eager loading
    query = select(Message).options(
        selectinload(Message.user),
        selectinload(Message.replies).selectinload(Message.user),
        selectinload(Message.replies).selectinload(Message.replies).selectinload(Message.user),
        selectinload(Message.replies).selectinload(Message.replies).selectinload(Message.replies).selectinload(Message.user),
        selectinload(Message.replies).selectinload(Message.replies).selectinload(Message.replies).selectinload(Message.replies).selectinload(Message.user)
    ).filter(Message.id == root_id)
    
    result = await db.execute(query)
    root_msg = result.scalars().first()
    
    if not root_msg:
        return "Message not found"

    # Format recursively with focus marker for the requested message
    def format_with_focus(msg):
        """Helper to mark the focused message in the thread."""
        formatted = format_message_recursive(msg)
        formatted["is_focused"] = msg.id == message_id
        return formatted
    
    # Override format_message_recursive locally to add focus marker
    from sqlalchemy import inspect as sqlalchemy_inspect
    
    def format_recursive_with_focus(msg):
        try:
            formatted_time = msg.created_at.strftime("%H:%M")
        except:
            formatted_time = str(msg.created_at)
        
        replies = []
        if "replies" not in sqlalchemy_inspect(msg).unloaded:
            replies = [format_recursive_with_focus(reply) for reply in msg.replies]
        
        return {
            "id": msg.id,
            "content": linkify_content(msg.content),
            "created_at": formatted_time,
            "created_at_iso": msg.created_at.isoformat(),
            "author": msg.user.email if msg.user else "Unknown",
            "user_id": msg.user_id if msg.user else None,
            "replies": replies,
            "is_focused": msg.id == message_id  # Mark the requested message
        }
    
    formatted_root = format_recursive_with_focus(root_msg)
    
    return templates.TemplateResponse("partials/thread_view.html", {
        "request": request,
        "message": formatted_root,
        "user": current_user
    })


@router.get("/messages/{message_id}/replies")
async def get_replies(
    request: Request,
    message_id: int,
    db: AsyncSession = Depends(get_db)
):
    """
    Get replies for a specific message.
    Used for dynamically updating the replies list after posting.
    """
    # Get current user for admin controls
    current_user = await get_optional_user(request, db)
    
    # Fetch the message with replies loaded
    query = select(Message).options(
        selectinload(Message.replies).selectinload(Message.user),
        selectinload(Message.replies).selectinload(Message.replies).selectinload(Message.user),
        selectinload(Message.replies).selectinload(Message.replies).selectinload(Message.replies).selectinload(Message.user)
    ).filter(Message.id == message_id)
    
    result = await db.execute(query)
    message = result.scalars().first()
    
    if not message:
        return ""

    # Format replies
    formatted_replies = []
    if message.replies:
        # Sort replies by creation time
        sorted_replies = sorted(message.replies, key=lambda x: x.created_at)
        formatted_replies = [format_message_recursive(reply) for reply in sorted_replies]
    
    return templates.TemplateResponse("partials/reply_list.html", {
        "request": request,
        "replies": formatted_replies,
        "user": current_user,
        "expanded": True  # Always expand when fetching explicitly
    })


@router.get("/hashtags")
async def get_hashtags(
    request: Request,
    tags: list[str] = Query(None)
):
    """
    Get list of hashtags with usage counts and trending status.
    
    This endpoint powers the hashtag sidebar, showing:
    - All hashtags ever used (with total counts)
    - Trending hashtags (most active in last hour)
    - Selected tags highlighted at top
    
    Args:
        request: FastAPI request
        tags: Currently selected hashtags (to highlight)
        
    Returns:
        Rendered HTML partial with hashtag list
    """
    # Clean old activity entries (older than 1 hour)
    now = time.time()
    cutoff = now - 3600  # 1 hour in seconds
    await redis_client.zremrangebyscore("hashtag_activity", "-inf", cutoff)
    
    # Get recent activity for trending calculation
    activity = await redis_client.zrange("hashtag_activity", 0, -1)
    
    # Count trending occurrences (activity in last hour)
    trending_counts = {}
    for item in activity:
        # Item format: "tag:msg_id"
        parts = item.split(":")
        if len(parts) >= 1:
            tag = parts[0]
            trending_counts[tag] = trending_counts.get(tag, 0) + 1
    
    # Get all hashtags ever seen
    all_tags = await redis_client.smembers("all_hashtags")
    
    # Get total usage counts
    total_counts = await redis_client.hgetall("hashtag_counts")
    
    # Combine data for each tag
    final_list = []
    for tag in all_tags:
        count = int(total_counts.get(tag, 0))
        trending = trending_counts.get(tag, 0)
        final_list.append((tag, count, trending))
    
    # Sort by: trending count (desc), then total count (desc), then alphabetically
    sorted_hashtags = sorted(final_list, key=lambda x: (-x[2], -x[1], x[0]))
    
    # Prioritize selected tags at the top
    if tags:
        selected = []
        others = []
        for tag, count, trending in sorted_hashtags:
            if tag in tags:
                selected.append((tag, count))
            else:
                others.append((tag, count))
        
        # Ensure selected tags that might not be in cache are shown
        existing_selected = {t[0] for t in selected}
        for t in tags:
            if t not in existing_selected:
                selected.append((t, 0))
        
        sorted_hashtags = selected + others
    else:
        # Strip trending count for template (only need tag and total count)
        sorted_hashtags = [(t, c) for t, c, tr in sorted_hashtags]
    
    return templates.TemplateResponse("partials/hashtag_list.html", {
        "request": request,
        "hashtags": sorted_hashtags,
        "selected_tags": tags or []
    })


@router.get("/container")
async def get_feed_container(
    request: Request,
    tags: list[str] = Query(None),
    search: str = Query(None),
    view: str = Query("unrolled"),
    db: AsyncSession = Depends(get_db)
):
    """
    Get main feed container with filtered messages.
    
    This powers the main feed display with support for:
    - Hashtag filtering (show messages with specific tags)
    - Search filtering (text search in messages)
    - Star status for authenticated users
    
    Args:
        request: FastAPI request
        tags: List of hashtags to filter by
        search: Search term to filter by
        db: Database session
        
    Returns:
        Rendered HTML partial with feed messages
    """
    # Get current user to check starred messages (optional)
    current_user = await get_optional_user(request, db)
    starred_ids = set()
    
    if current_user:
        # Fetch user with starred messages relationship
        user_result = await db.execute(
            select(User)
            .filter(User.id == current_user.id)
            .options(selectinload(User.starred_messages))
        )
        current_user = user_result.scalars().first()
        starred_ids = {msg.id for msg in current_user.starred_messages}

    # Build query with eager loading (avoid N+1 queries)
    query = select(Message).options(
        selectinload(Message.user),
        selectinload(Message.replies).selectinload(Message.user),
        selectinload(Message.replies).selectinload(Message.replies).selectinload(Message.user),
        selectinload(Message.replies).selectinload(Message.replies).selectinload(Message.replies).selectinload(Message.user),
        selectinload(Message.replies).selectinload(Message.replies).selectinload(Message.replies).selectinload(Message.replies).selectinload(Message.user),
        selectinload(Message.parent).selectinload(Message.user)  # Load parent for reply context
    )
    
    # Filter by parent_id based on view mode
    if view == "threaded":
        query = query.filter(Message.parent_id == None)  # Only top-level messages
    # If view == "unrolled", we show all messages (no parent_id filter)

    
    # Apply filters
    if tags:
        # Show messages containing ANY of the selected tags
        conditions = [Message.content.contains(f"#{tag}") for tag in tags]
        query = query.filter(or_(*conditions))
    
    if search:
        # Case-insensitive search in content
        query = query.filter(Message.content.ilike(f"%{search}%"))
    
    # Order and limit
    query = query.order_by(desc(Message.created_at)).limit(30)
    
    # Execute query
    result = await db.execute(query)
    rows = result.scalars().all()
    
    # Format messages with star status
    messages = [format_message_recursive(msg, starred_ids) for msg in rows]
    
    # Build query string for links
    tags_query = "&".join([f"tags={t}" for t in tags]) if tags else ""
    if search:
        tags_query += f"&search={search}"
    
    return templates.TemplateResponse("partials/feed_container.html", {
        "request": request,
        "messages": messages,
        "tags": tags,
        "search": search,
        "view": view,
        "tags_query": tags_query,
        "user": current_user
    })


@router.get("/notifications")
async def get_notifications(
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Get notifications for the current user.
    """
    from app.models import Notification
    
    # Fetch notifications with message loaded
    query = select(Notification).options(
        selectinload(Notification.message).selectinload(Message.user)
    ).filter(
        Notification.user_id == user.id
    ).order_by(desc(Notification.created_at))
    
    result = await db.execute(query)
    notifications = result.scalars().all()
    
    # Format notifications
    formatted_notifications = []
    for notif in notifications:
        if not notif.message:
            continue
            
        try:
            formatted_time = notif.created_at.strftime("%H:%M")
        except:
            formatted_time = str(notif.created_at)
            
        formatted_notifications.append({
            "id": notif.id,
            "message_id": notif.message_id,
            "content": notif.message.content[:50] + "..." if len(notif.message.content) > 50 else notif.message.content,
            "author": notif.message.user.email if notif.message.user else "Unknown",
            "created_at": formatted_time,
            "is_read": notif.is_read
        })
    
    return templates.TemplateResponse("partials/notifications.html", {
        "request": request,
        "notifications": formatted_notifications
    })


@router.post("/notifications/{notification_id}/read")
async def mark_notification_read(
    notification_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Mark a notification as read.
    """
    from app.models import Notification
    
    result = await db.execute(
        select(Notification).filter(
            Notification.id == notification_id,
            Notification.user_id == user.id
        )
    )
    notification = result.scalars().first()
    
    if notification:
        notification.is_read = True
        await db.commit()
        
    return "OK"


@router.get("/stream")
async def stream_messages(
    request: Request,
    tags: list[str] = Query(None),
    search: str = Query(None),
    db: AsyncSession = Depends(get_db)
):
    """
    Server-Sent Events stream for real-time message updates.
    
    This creates a persistent connection that pushes new messages to the
    client as they are posted. Uses Redis pub/sub for scalability.
    
    Filters are applied client-side for efficiency - all messages are
    sent, but only matching ones are displayed.
    
    Args:
        request: FastAPI request (used to detect disconnection)
        tags: List of hashtags to filter by
        search: Search term to filter by
        db: Database session
        
    Yields:
        Server-sent events with HTML for new messages
    """
    # Get current user for admin controls
    current_user = await get_optional_user(request, db)

    async def event_generator():
        """
        Async generator that yields SSE events for new messages.
        
        Subscribes to Redis channel and formats/filters messages as they arrive.
        """
        # Subscribe to Redis pub/sub channel
        async for message in subscribe_channel(CHANNEL):
            # Check if client disconnected
            if await request.is_disconnected():
                break
            
            # Parse message data from JSON
            data = json.loads(message)
            
            # Handle Notifications
            # Don't notify the author of their own post
            if data.get("user_id") != current_user.id if current_user else True:
                notification_type = None
                notification_data = {}
                
                # Check if this is a reply to the current user
                parent_author_id = data.get("parent_author_id")
                
                if parent_author_id and current_user and parent_author_id == current_user.id:
                    # High-level notification: Reply to my message
                    notification_type = "new_reply"
                    notification_data = {
                        "title": "New Reply",
                        "body": f"New reply from {data.get('user_email', 'Someone')}: {data['content'][:50]}...",
                        "tag": "reply"
                    }
                elif not parent_author_id:
                     # Low-level notification: New top-level message
                    notification_type = "new_message"
                    notification_data = {
                        "title": "New Message",
                        "body": f"New message from {data.get('user_email', 'Someone')}",
                        "tag": "message"
                    }
                
                if notification_type:
                    yield {
                        "event": "notification",
                        "data": json.dumps(notification_data)
                    }
                    
                    # Also trigger notification panel refresh for replies
                    if notification_type == "new_reply":
                        # Send empty refresh event that HTMX will use to update the panel
                        yield {
                            "event": "refreshNotifications",
                            "data": ""
                        }

            # Apply filters
            if tags:
                # Show only if message contains ANY selected tag
                if not any(f"#{t}" in data["content"] for t in tags):
                    continue
            
            if search:
                # Show only if message contains search term
                if search.lower() not in data["content"].lower():
                    continue
            
            # Format timestamp
            try:
                dt = datetime.fromisoformat(data["created_at"])
                formatted_time = dt.strftime("%H:%M")
                created_at_iso = data["created_at"]  # Keep the ISO format for frontend
            except:
                formatted_time = data["created_at"]
                created_at_iso = data["created_at"]

            # Render message HTML from template
            rendered_html = templates.get_template("partials/feed_item.html").render(
                content=linkify_content(data["content"]),
                created_at=formatted_time,
                created_at_iso=created_at_iso,  # Add ISO timestamp for timezone conversion
                author=data.get("user_email", "Anonymous User"),
                id=data["id"],
                user_id=data.get("user_id"),
                replies=[],
                user=current_user
            )
            
            # Handle replies with out-of-band (OOB) swapping
            parent_id = data.get("parent_id")
            
            # In threaded view, replies are swapped into the parent's reply list
            # In unrolled view, replies are treated as top-level items in the stream
            if parent_id and view == "threaded":
                # For replies, wrap HTML with HTMX OOB swap directive
                # This appends the reply to the parent's reply list
                script = f"""
                <script>
                    (function() {{
                        const replies = document.getElementById('replies-{parent_id}');
                        const btn = document.getElementById('reply-toggle-{parent_id}');
                        if (replies) {{
                            replies.style.display = 'block';
                        }}
                        if (btn) {{
                            btn.style.display = 'inline-flex';
                            btn.textContent = 'Hide replies';
                        }}
                    }})();
                </script>
                """
                rendered_html = f'<div hx-swap-oob="beforeend:#replies-{parent_id}">{rendered_html}</div>{script}'
            
            # Yield SSE event with HTML data
            yield {"data": rendered_html}

    # Return EventSourceResponse for SSE
    return EventSourceResponse(event_generator())


@router.get("/history")
async def get_history(
    request: Request,
    cursor: int = None,
    tags: list[str] = Query(None),
    search: str = Query(None),
    view: str = Query("threaded"),
    db: AsyncSession = Depends(get_db)
):
    """
    Get older messages for infinite scroll pagination.
    
    This loads messages older than the cursor ID, allowing users
    to scroll back through message history.
    
    Args:
        request: FastAPI request
        cursor: ID of oldest message currently displayed (pagination cursor)
        tags: List of hashtags to filter by
        search: Search term to filter by
        db: Database session
        
    Returns:
        Rendered HTML partial with older messages
    """
    if not cursor:
        # No cursor = no more messages to load
        return ""
    
    # Get current user to check starred messages (optional)
    current_user = await get_optional_user(request, db)
    starred_ids = set()
    
    if current_user:
        # Fetch user with starred messages relationship
        user_result = await db.execute(
            select(User)
            .filter(User.id == current_user.id)
            .options(selectinload(User.starred_messages))
        )
        current_user = user_result.scalars().first()
        starred_ids = {msg.id for msg in current_user.starred_messages}
    
    # Build query similar to container, but filter by ID < cursor
    query = select(Message).options(
        selectinload(Message.user),
        selectinload(Message.replies).selectinload(Message.user),
        selectinload(Message.replies).selectinload(Message.replies).selectinload(Message.user),
        selectinload(Message.replies).selectinload(Message.replies).selectinload(Message.replies).selectinload(Message.user),
        selectinload(Message.replies).selectinload(Message.replies).selectinload(Message.replies).selectinload(Message.replies).selectinload(Message.user),
        selectinload(Message.parent).selectinload(Message.user)  # Load parent for reply context
    ).filter(Message.id < cursor)
    
    if view == "threaded":
        query = query.filter(Message.parent_id == None)
    
    # Apply same filters as container
    if tags:
        conditions = [Message.content.contains(f"#{tag}") for tag in tags]
        query = query.filter(or_(*conditions))
    
    if search:
        query = query.filter(Message.content.ilike(f"%{search}%"))
    
    # Order and limit
    query = query.order_by(desc(Message.created_at)).limit(30)
    
    # Execute query
    result = await db.execute(query)
    rows = result.scalars().all()
    
    # Format messages
    messages = [format_message_recursive(msg, starred_ids) for msg in rows]
    
    # Calculate next cursor (ID of last message)
    next_cursor = messages[-1]["id"] if messages else None
    
    # Build query string
    tags_query = "&".join([f"tags={t}" for t in tags]) if tags else ""
    if search:
        tags_query += f"&search={search}"
    
    return templates.TemplateResponse("partials/feed_history.html", {
        "request": request,
        "messages": messages,
        "next_cursor": next_cursor,
        "tags": tags,
        "search": search,
        "view": view,
        "tags_query": tags_query,
        "user": current_user
    })
