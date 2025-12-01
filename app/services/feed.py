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

async def rebuild_hashtag_cache(db_session):
    """
    Rebuilds the hashtag cache in Redis from the database.
    Populates 'all_hashtags' with every hashtag ever seen.
    Populates 'hashtag_activity' with hashtags from the last hour.
    """
    from app.models import Message
    from sqlalchemy import select
    from datetime import datetime, timedelta
    import re
    import time
    
    # Clear existing cache
    await redis_client.delete("hashtag_activity")
    await redis_client.delete("all_hashtags")
    await redis_client.delete("hashtag_counts")
    
    # Get ALL messages
    query = select(Message)
    result = await db_session.execute(query)
    messages = result.scalars().all()
    
    one_hour_ago = datetime.utcnow() - timedelta(hours=1)
    
    counts = {}
    
    for message in messages:
        hashtags = set(re.findall(r"#(\w+)", message.content))
        if hashtags:
            # Add to all_hashtags and count
            for tag in hashtags:
                await redis_client.sadd("all_hashtags", tag)
                counts[tag] = counts.get(tag, 0) + 1
                
            # If within last hour, add to activity
            if message.created_at >= one_hour_ago:
                timestamp = message.created_at.timestamp()
                for tag in hashtags:
                    await redis_client.zadd("hashtag_activity", {f"{tag}:{message.id}": timestamp})
                    
    # Store counts in Redis
    if counts:
        await redis_client.hset("hashtag_counts", mapping=counts)
