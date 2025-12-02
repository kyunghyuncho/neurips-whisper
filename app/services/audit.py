"""
Audit Logging Service

This module provides functionality to record audit logs for important system actions.
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
    
    Args:
        db: Database session
        action: Name of the action (e.g., "user_created", "message_deleted")
        user_email: Email of the user performing the action
        details: Optional details about the action (dict will be JSON encoded)
    """
    details_str = None
    if details:
        if isinstance(details, dict):
            details_str = json.dumps(details)
        else:
            details_str = str(details)
            
    log_entry = AuditLog(
        action=action,
        user_email=user_email,
        details=details_str
    )
    
    db.add(log_entry)
    # We don't commit here to allow the caller to group this with other transaction changes
    # or commit explicitly.
    # However, for logging, we often want to ensure it's saved even if the main action fails?
    # But usually we want it to be part of the transaction.
    # Let's assume the caller handles commit, or we can flush.
    # Actually, for "audit", we might want it to persist even if the main action fails, 
    # but usually we log *successful* actions.
    # If we want to log attempts, we should commit immediately.
    # For now, let's leave commit to the caller to keep it simple and transactional.
