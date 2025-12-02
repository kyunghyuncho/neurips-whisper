"""
Audit Logging Service

This module provides functionality to record audit logs for important system actions.

Audit logs track administrative actions like:
- User account creation
- Message deletion by superusers
- User bans
- Data downloads

The logs can be downloaded by superusers for compliance and security monitoring.
"""

from sqlalchemy.ext.asyncio import AsyncSession
from app.models import AuditLog
import json


async def log_action(
    db: AsyncSession,
    action: str,
    user_email: str,
    details: dict | str | None = None
):
    """
    Record an action in the audit log.
    
    This function creates an audit log entry but does not commit it to the database.
    The caller is responsible for committing the transaction, which ensures that
    audit logs are only saved when the main action succeeds (transactional integrity).
    
    For example, if a message deletion fails, we don't want to log that it was deleted.
    By leaving commit to the caller, the audit log and main action succeed or fail together.
    
    Args:
        db: Database session (transaction will be committed by caller)
        action: Name of the action (e.g., "user_created", "message_deleted", "user_banned")
        user_email: Email of the user performing the action (actor, not target)
        details: Optional additional context about the action
                 - Dict: Will be JSON-serialized for structured data
                 - String: Will be stored as-is
                 - None: No additional details
                 
    Example:
        await log_action(
            db, 
            "message_deleted", 
            "admin@university.edu",
            {"message_id": 123, "reason": "spam"}
        )
        await db.commit()  # Caller commits the transaction
    """
    # Convert details to string for storage
    # Dicts are JSON-serialized to preserve structure
    details_str = None
    if details:
        if isinstance(details, dict):
            details_str = json.dumps(details)
        else:
            details_str = str(details)
    
    # Create audit log entry
    log_entry = AuditLog(
        action=action,
        user_email=user_email,
        details=details_str
    )
    
    # Add to session but don't commit
    # The caller will commit this along with the main action
    # This ensures transactional consistency
    db.add(log_entry)
