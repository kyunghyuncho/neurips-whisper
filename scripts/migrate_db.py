"""
Database Migration Script

This script adds the parent_id column to the messages table for threaded conversations.
It's a one-time migration that should be run when adding the threading feature.

Usage:
    python scripts/migrate_db.py

Note: This is a simple ad-hoc migration. For production applications,
consider using a migration tool like Alembic for version-controlled schema changes.
"""

import asyncio
import os
import sys

# Add parent directory to Python path so we can import app modules
# This allows running the script from any directory
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import engine
from sqlalchemy import text


async def migrate():
    """
    Add parent_id column to messages table for threaded replies.
    
    This migration enables messages to reference a parent message,
    creating threaded conversations in the feed.
    
    The column is nullable because top-level messages have no parent.
    """
    # Begin a database transaction
    async with engine.begin() as conn:
        try:
            # Execute raw SQL to alter table
            # - parent_id: Foreign key to another message
            # - INTEGER: Matches the id column type
            # - REFERENCES messages(id): Creates foreign key constraint
            await conn.execute(
                text("ALTER TABLE messages ADD COLUMN parent_id INTEGER REFERENCES messages(id)")
            )
            print("Successfully added parent_id column")
            
        except Exception as e:
            # Migration might fail if column already exists
            # This is okay - it means migration was already run
            print(f"Migration failed (maybe column exists?): {e}")


if __name__ == "__main__":
    # Run the async migration function
    asyncio.run(migrate())
