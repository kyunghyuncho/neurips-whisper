from fastapi import APIRouter, Depends, HTTPException, Form, Request, Query
from app.dependencies import get_current_user, get_optional_user
from sse_starlette.sse import EventSourceResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import desc, or_
from sqlalchemy.orm import selectinload
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
from sqlalchemy import delete, text

router = APIRouter(prefix="/feed", tags=["feed"])
CHANNEL = "neurips_feed"

@router.post("/post")
async def post_message(
    content: str = Form(...),
    parent_id: int = Form(None),
    user: User = Depends(get_current_user),
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
    # Save to DB
    message = Message(user_id=user.id, content=content, parent_id=parent_id)
    db.add(message)
    await db.commit()
    await db.refresh(message)

    # Fetch user email (already have user)
    user_email = user.email

    # Extract and store hashtags
    hashtags = set(re.findall(r"#(\w+)", content))
    if hashtags:
        timestamp = time.time()
        for tag in hashtags:
            # Add to Redis sorted set: score=timestamp, member=tag:msg_id
            await redis_client.zadd("hashtag_activity", {f"{tag}:{message.id}": timestamp})
            # Add to Redis set of all hashtags
            await redis_client.sadd("all_hashtags", tag)
            # Increment total count
            await redis_client.hincrby("hashtag_counts", tag, 1)

    # Extract and store terms
    from app.utils.text import extract_terms
    terms = extract_terms(content)
    if terms:
        timestamp = time.time()
        for term in terms:
            # Add to Redis sorted set: score=timestamp, member=term:msg_id
            await redis_client.zadd("term_activity", {f"{term}:{message.id}": timestamp})
            # Add to Redis set of all terms
            await redis_client.sadd("all_terms", term)

    # Publish to Redis
    data = {
        "id": message.id,
        "content": message.content,
        "created_at": message.created_at.isoformat(),
        "user_email": user_email,
        "parent_id": message.parent_id
    }
    await publish_message(CHANNEL, data)
    

    from fastapi.responses import JSONResponse
    return JSONResponse(
        content={"message": "Message posted"},
        headers={"HX-Trigger": json.dumps({"updateHashtags": True, "updateMyMessages": True})}
    )


@router.post("/star/{message_id}")
async def star_message(
    message_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    # Fetch user with starred messages
    # We need to reload user with starred_messages or join
    # Since get_current_user returns a user, but maybe not with relationships loaded.
    # Let's re-fetch or use selectinload in dependency? 
    # Better to re-fetch to be safe and simple here.
    result = await db.execute(select(User).filter(User.id == user.id).options(selectinload(User.starred_messages)))
    user = result.scalars().first()
    
    msg_result = await db.execute(select(Message).filter(Message.id == message_id))
    message = msg_result.scalars().first()
    
    if not user or not message:
        raise HTTPException(status_code=404, detail="User or Message not found")
    
    # Check if already starred
    if message in user.starred_messages:
        user.starred_messages.remove(message)
        is_starred = False
    else:
        user.starred_messages.append(message)
        is_starred = True
        
    await db.commit()
    
    # Return the updated star button
    return templates.TemplateResponse("partials/star_button.html", {
        "request": {},
        "id": message.id,
        "is_starred": is_starred
    }, headers={"HX-Trigger": "updateMyMessages"})


@router.get("/my_messages")
async def get_my_messages(request: Request, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    user_id = user.id
    # Fetch user's posts
    user_posts_query = select(Message).filter(Message.user_id == user_id)
    
    # Fetch starred posts
    # We need to join with the association table
    # But simpler: fetch user with starred_messages loaded
    user_result = await db.execute(select(User).filter(User.id == user_id).options(selectinload(User.starred_messages).selectinload(Message.user)))
    user = user_result.scalars().first()
    
    starred_messages = user.starred_messages if user else []
    
    # Execute user posts query
    posts_result = await db.execute(user_posts_query.options(selectinload(Message.user)))
    user_posts = posts_result.scalars().all()
    
    # Combine and sort
    starred_ids = {m.id for m in starred_messages}
    all_messages = []
    seen_ids = set()
    
    for msg in user_posts + starred_messages:
        if msg.id not in seen_ids:
            all_messages.append(msg)
            seen_ids.add(msg.id)
            
    all_messages.sort(key=lambda x: x.created_at, reverse=True)
    
    # Format
    formatted_messages = []
    for msg in all_messages:
        try:
            formatted_time = msg.created_at.strftime("%H:%M")
        except:
            formatted_time = str(msg.created_at)
            
        formatted_messages.append({
            "id": msg.id,
            "content": linkify_content(msg.content),
            "created_at": formatted_time,
            "author": msg.user.email if msg.user else "Unknown",
            "is_starred": msg.id in starred_ids
        })
        
    return templates.TemplateResponse("partials/my_messages.html", {
        "request": request,
        "messages": formatted_messages
    })

@router.get("/thread/{message_id}")
async def get_thread(request: Request, message_id: int, db: AsyncSession = Depends(get_db)):
    # Find the root message
    current_id = message_id
    root_id = current_id
    
    # Traverse up to find root
    # Since we don't have recursive CTEs easily setup in async sqlalchemy without raw SQL, 
    # and depth is likely shallow, we can loop. 
    # But better: just fetch the message and check parent_id.
    
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
            
    # Now fetch the whole tree from root
    # We can reuse the recursive loader strategy from get_feed_container
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

    # Format recursively
    from sqlalchemy import inspect
    def format_message_recursive(msg):
        try:
            formatted_time = msg.created_at.strftime("%H:%M")
        except:
            formatted_time = str(msg.created_at)
            
        replies = []
        if "replies" not in inspect(msg).unloaded:
            replies = [format_message_recursive(reply) for reply in msg.replies]
            
        return {
            "id": msg.id,
            "content": linkify_content(msg.content),
            "created_at": formatted_time,
            "author": msg.user.email if msg.user else "Unknown",
            "replies": replies,
            "is_focused": msg.id == message_id
        }

    formatted_root = format_message_recursive(root_msg)
    
    return templates.TemplateResponse("partials/thread_view.html", {
        "request": request,
        "message": formatted_root
    })

@router.get("/hashtags")
async def get_hashtags(request: Request, tags: list[str] = Query(None)):
    # Clean old entries (older than 1 hour)
    now = time.time()
    cutoff = now - 3600
    await redis_client.zremrangebyscore("hashtag_activity", "-inf", cutoff)
    
    # Get all active hashtag events (for popularity/trending)
    activity = await redis_client.zrange("hashtag_activity", 0, -1)
    
    trending_counts = {}
    for item in activity:
        # Item format: tag:msg_id
        parts = item.split(":")
        if len(parts) >= 1:
            tag = parts[0]
            trending_counts[tag] = trending_counts.get(tag, 0) + 1
            
    # Get ALL hashtags ever seen
    all_tags = await redis_client.smembers("all_hashtags")
    
    # Get total counts
    total_counts = await redis_client.hgetall("hashtag_counts")
    
    # Combine
    final_list = []
    for tag in all_tags:
        # Use total count for display, but maybe sort by trending count?
        # User said "count is not correct", implying they want total count.
        # Let's use total count for display.
        count = int(total_counts.get(tag, 0))
        trending = trending_counts.get(tag, 0)
        final_list.append((tag, count, trending))
        
    # Sort by trending count (desc), then total count (desc), then alpha
    sorted_hashtags = sorted(final_list, key=lambda x: (-x[2], -x[1], x[0]))
    
    # Prioritize selected tags
    if tags:
        selected = []
        others = []
        for tag, count, trending in sorted_hashtags:
            if tag in tags:
                selected.append((tag, count))
            else:
                others.append((tag, count))
        
        # Ensure selected tags that might not be in "all_hashtags" are shown
        existing_selected = {t[0] for t in selected}
        for t in tags:
            if t not in existing_selected:
                selected.append((t, 0))
                
        sorted_hashtags = selected + others
    else:
        # Strip trending count for template
        sorted_hashtags = [(t, c) for t, c, tr in sorted_hashtags]
    
    return templates.TemplateResponse("partials/hashtag_list.html", {
        "request": request,
        "hashtags": sorted_hashtags,
        "selected_tags": tags or []
    })

@router.get("/container")
async def get_feed_container(request: Request, tags: list[str] = Query(None), search: str = Query(None), db: AsyncSession = Depends(get_db)):
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
            "replies": replies,
            "is_starred": is_starred
        }

    # Fetch user to check starred messages
    current_user = await get_optional_user(request, db)
    starred_ids = set()
    if current_user:
        # Re-fetch with relationship
        user_result = await db.execute(select(User).filter(User.id == current_user.id).options(selectinload(User.starred_messages)))
        current_user = user_result.scalars().first()
        starred_ids = {msg.id for msg in current_user.starred_messages}

    # We need to pass is_starred to the recursive function, but it's hard to pass down.
    # Instead, we can post-process or modify the function to check the set.
    
    def format_message_recursive_with_star(msg):
        try:
            formatted_time = msg.created_at.strftime("%H:%M")
        except:
            formatted_time = str(msg.created_at)
            
        replies = []
        if "replies" not in inspect(msg).unloaded:
            replies = [format_message_recursive_with_star(reply) for reply in msg.replies]
            
        return {
            "id": msg.id,
            "content": linkify_content(msg.content),
            "created_at": formatted_time,
            "author": msg.user.email if msg.user else "Unknown",
            "replies": replies,
            "is_starred": msg.id in starred_ids
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
        
    if search:
        query = query.filter(Message.content.ilike(f"%{search}%"))
        
    query = query.order_by(desc(Message.created_at)).limit(30)
        
    result = await db.execute(query)
    rows = result.scalars().all()
    
    messages = [format_message_recursive_with_star(msg) for msg in rows]
        
    tags_query = "&".join([f"tags={t}" for t in tags]) if tags else ""
    if search:
        tags_query += f"&search={search}"
        
    return templates.TemplateResponse("partials/feed_container.html", {
        "request": request,
        "messages": messages,
        "tags": tags,
        "search": search,
        "tags_query": tags_query
    })

@router.get("/stream")
async def stream_messages(request: Request, tags: list[str] = Query(None), search: str = Query(None)):
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
                    
            # Filter by search term if present
            if search:
                if search.lower() not in data["content"].lower():
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
                id=data["id"],
                replies=[]
            )
            
            # If it's a reply, use OOB swap to append to the parent's reply list
            parent_id = data.get("parent_id")
            if parent_id:
                # Wrap in a div that targets the parent's replies container
                # We use hx-swap-oob="beforeend:#replies-{parent_id}"
                # Note: HTMX OOB usually replaces by ID. To append, we might need a different approach or use the extended syntax.
                # Let's try the extended syntax: hx-swap-oob="beforeend:#replies-{parent_id}"
                # Also include a script to expand the replies and show the button
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
            
            yield {"data": rendered_html}

    return EventSourceResponse(event_generator())

@router.get("/history")
async def get_history(request: Request, cursor: int = None, tags: list[str] = Query(None), search: str = Query(None), db: AsyncSession = Depends(get_db)):
    if not cursor:
        return "" 
        
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
    ).filter(Message.parent_id == None).filter(Message.id < cursor)
    
    if tags:
        conditions = [Message.content.contains(f"#{tag}") for tag in tags]
        query = query.filter(or_(*conditions))
        
    if search:
        query = query.filter(Message.content.ilike(f"%{search}%"))
        
    query = query.order_by(desc(Message.created_at)).limit(30)
        
    result = await db.execute(query)
    rows = result.scalars().all()
    
    messages = [format_message_recursive(msg) for msg in rows]
        
    next_cursor = messages[-1]["id"] if messages else None
    
    tags_query = "&".join([f"tags={t}" for t in tags]) if tags else ""
    if search:
        tags_query += f"&search={search}"
    
    return templates.TemplateResponse("partials/feed_history.html", {
        "request": request,
        "messages": messages,
        "next_cursor": next_cursor,
        "tags": tags,
        "search": search,
        "tags_query": tags_query
    })

