import redis.asyncio as redis
from app.config import settings
import json

redis_client = redis.from_url(settings.REDIS_URL, encoding="utf-8", decode_responses=True)

async def publish_message(channel: str, message: dict):
    await redis_client.publish(channel, json.dumps(message))

async def subscribe_channel(channel: str):
    pubsub = redis_client.pubsub()
    await pubsub.subscribe(channel)
    async for message in pubsub.listen():
        if message["type"] == "message":
            yield message["data"]

async def rebuild_cache(db_session):
    """
    Rebuilds the hashtag and term cache in Redis from the database.
    Populates 'all_hashtags' and 'all_terms' with every tag/term ever seen.
    Populates 'hashtag_activity' and 'term_activity' with items from the last hour.
    Populates 'hashtag_counts' with total counts.
    """
    from app.models import Message
    from sqlalchemy import select
    from datetime import datetime, timedelta
    from app.utils.text import extract_terms
    import re
    import time
    
    # Clear existing cache
    await redis_client.delete("hashtag_activity")
    await redis_client.delete("all_hashtags")
    await redis_client.delete("hashtag_counts")
    await redis_client.delete("term_activity")
    await redis_client.delete("all_terms")
    
    # Get ALL messages
    query = select(Message)
    result = await db_session.execute(query)
    messages = result.scalars().all()
    
    one_hour_ago = datetime.utcnow() - timedelta(hours=1)
    
    counts = {}
    
    for message in messages:
        # Hashtags
        hashtags = set(re.findall(r"#(\w+)", message.content))
        if hashtags:
            for tag in hashtags:
                await redis_client.sadd("all_hashtags", tag)
                counts[tag] = counts.get(tag, 0) + 1
                
            if message.created_at >= one_hour_ago:
                timestamp = message.created_at.timestamp()
                for tag in hashtags:
                    await redis_client.zadd("hashtag_activity", {f"{tag}:{message.id}": timestamp})

        # Terms
        terms = extract_terms(message.content)
        if terms:
            for term in terms:
                await redis_client.sadd("all_terms", term)
                
            if message.created_at >= one_hour_ago:
                timestamp = message.created_at.timestamp()
                for term in terms:
                    await redis_client.zadd("term_activity", {f"{term}:{message.id}": timestamp})
                    
    # Store counts in Redis
    if counts:
        await redis_client.hset("hashtag_counts", mapping=counts)
