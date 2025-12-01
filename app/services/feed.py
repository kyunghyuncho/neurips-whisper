"""
Feed Service - Real-time Messaging and Caching

This module provides Redis-based services for the message feed:
1. Pub/Sub for real-time message broadcasting
2. Hashtag and term caching for quick lookups
3. Activity tracking using sorted sets

Redis data structures used:
- Pub/Sub channels: Real-time message streaming
- Sorted Sets (ZSET): Time-ordered hashtag/term activity
- Sets: All-time hashtag/term collections
- Hashes: Hashtag usage counts
"""

import redis.asyncio as redis
from app.config import settings
import json


# Create async Redis client
# - encoding="utf-8": Decode bytes to strings automatically
# - decode_responses=True: Return strings instead of bytes for easier handling
redis_client = redis.from_url(
    settings.REDIS_URL,
    encoding="utf-8",
    decode_responses=True
)


async def publish_message(channel: str, message: dict):
    """
    Publish a message to a Redis pub/sub channel.
    
    This broadcasts the message to all subscribers listening on the channel.
    Used for real-time updates when new messages are posted.
    
    Args:
        channel: Redis channel name (e.g., "neurips_feed")
        message: Dict containing message data (will be JSON-serialized)
                 Typically includes: id, content, created_at, user_email, parent_id
    """
    # Redis pub/sub only handles string data, so we serialize to JSON
    await redis_client.publish(channel, json.dumps(message))


async def subscribe_channel(channel: str):
    """
    Subscribe to a Redis pub/sub channel and yield messages as they arrive.
    
    This is an async generator that continuously listens for new messages.
    Used for Server-Sent Events (SSE) to push updates to connected clients.
    
    Args:
        channel: Redis channel name to subscribe to
        
    Yields:
        JSON string for each message published to the channel
        
    Example usage:
        async for message in subscribe_channel("neurips_feed"):
            # Process real-time message
            data = json.loads(message)
    """
    # Create a pubsub instance for this subscription
    pubsub = redis_client.pubsub()
    
    # Subscribe to the channel
    await pubsub.subscribe(channel)
    
    # Listen for messages indefinitely
    async for message in pubsub.listen():
        # Filter for actual messages (ignore subscription confirmations, etc.)
        # message["type"] can be: "subscribe", "message", "unsubscribe", etc.
        if message["type"] == "message":
            # Yield just the data payload
            yield message["data"]


async def rebuild_cache(db_session):
    """
    Rebuild the hashtag and term cache in Redis from the database.
    
    This is called on application startup to populate Redis with data
    from all existing messages. It's idempotent - safe to run multiple times.
    
    Data populated:
    - all_hashtags (SET): Every hashtag ever used
    - all_terms (SET): Every term (non-stop-word) ever used
    - hashtag_counts (HASH): Total usage count for each hashtag
    - hashtag_activity (ZSET): Recent hashtag usage (last hour)
    - term_activity (ZSET): Recent term usage (last hour)
    
    The activity sorted sets use timestamp as the score, allowing:
    - Time-based queries (messages from last hour)
    - Trending detection (most active in recent time window)
    - Expiration by removing old scores
    
    Args:
        db_session: SQLAlchemy async session for database queries
    """
    from app.models import Message
    from sqlalchemy import select
    from datetime import datetime, timedelta
    from app.utils.text import extract_terms
    import re
    import time
    
    # Clear existing cache to start fresh
    # This ensures we don't have stale data from previous runs
    await redis_client.delete("hashtag_activity")
    await redis_client.delete("all_hashtags")
    await redis_client.delete("hashtag_counts")
    await redis_client.delete("term_activity")
    await redis_client.delete("all_terms")
    
    # Get ALL messages from the database
    query = select(Message)
    result = await db_session.execute(query)
    messages = result.scalars().all()
    
    # Define "recent" as last hour for activity tracking
    one_hour_ago = datetime.utcnow() - timedelta(hours=1)
    
    # Track counts in memory first, then bulk insert to Redis
    # This is more efficient than incrementing for each message
    counts = {}
    
    for message in messages:
        # === HASHTAG PROCESSING ===
        # Find all hashtags in message content (e.g., #machinelearning)
        hashtags = set(re.findall(r"#(\w+)", message.content))
        
        if hashtags:
            for tag in hashtags:
                # Add to set of all hashtags ever seen
                await redis_client.sadd("all_hashtags", tag)
                
                # Increment total count
                counts[tag] = counts.get(tag, 0) + 1
                
            # If message is recent (within last hour), add to activity tracker
            if message.created_at >= one_hour_ago:
                timestamp = message.created_at.timestamp()
                for tag in hashtags:
                    # ZADD adds to sorted set with score=timestamp
                    # Key format: "tag:message_id" allows finding which messages used each tag
                    await redis_client.zadd(
                        "hashtag_activity",
                        {f"{tag}:{message.id}": timestamp}
                    )

        # === TERM PROCESSING ===
        # Extract significant terms (excluding stop words, URLs, hashtags)
        terms = extract_terms(message.content)
        
        if terms:
            for term in terms:
                # Add to set of all terms ever seen
                await redis_client.sadd("all_terms", term)
                
            # If message is recent, add to activity tracker
            if message.created_at >= one_hour_ago:
                timestamp = message.created_at.timestamp()
                for term in terms:
                    # Same pattern as hashtags
                    await redis_client.zadd(
                        "term_activity",
                        {f"{term}:{message.id}": timestamp}
                    )
    
    # Bulk insert hashtag counts into Redis hash
    # HSET with mapping is more efficient than individual HINCRBY calls
    if counts:
        await redis_client.hset("hashtag_counts", mapping=counts)
