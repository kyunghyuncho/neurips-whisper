"""
Database Models for NeurIPS Whisper Application

This module defines the SQLAlchemy ORM models for the application:
- User: Conference participants who can post and star messages
- Message: Posts in the town square with threading support

The models demonstrate several important ORM patterns:
- Many-to-many relationships (users starring messages)
- Self-referential foreign keys (threaded message replies)
- Bidirectional relationships (backrefs)
"""

from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Table
from sqlalchemy.orm import declarative_base, relationship, backref
from datetime import datetime


# Base class for all ORM models
# All models must inherit from Base to be recognized by SQLAlchemy
Base = declarative_base()


# Association table for many-to-many relationship between Users and Messages
# This allows users to "star" multiple messages, and messages to be starred by multiple users
# Note: This is a pure association table (no additional columns), so it's defined as a Table
# rather than a full ORM class. If we needed to store when a star was added, we'd use a class.
star_association = Table(
    'stars',
    Base.metadata,
    Column('user_id', Integer, ForeignKey('users.id')),
    Column('message_id', Integer, ForeignKey('messages.id'))
)


class User(Base):
    """
    User model representing conference participants.
    
    Authentication is email-based with magic links (passwordless).
    Users must accept terms of service before posting messages.
    """
    __tablename__ = "users"
    
    # Primary key - automatically incremented
    id = Column(Integer, primary_key=True, index=True)
    
    # Email is unique and indexed for fast lookups during authentication
    # unique=True prevents duplicate accounts
    # index=True speeds up queries filtering by email
    email = Column(String, unique=True, index=True)
    
    # Timestamp when user accepted terms of service
    # Defaults to current UTC time when user is created
    terms_accepted_at = Column(DateTime, default=datetime.utcnow)
    
    # Account creation timestamp
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Many-to-many relationship: users can star multiple messages
    # - secondary: Points to the association table
    # - backref: Creates reverse relationship (Message.starred_by)
    # This allows: user.starred_messages and message.starred_by
    starred_messages = relationship(
        "Message",
        secondary=star_association,
        backref="starred_by"
    )


class Message(Base):
    """
    Message model representing posts in the town square.
    
    Supports threaded conversations through self-referential foreign keys.
    A message can be either a top-level post (parent_id=None) or a reply.
    """
    __tablename__ = "messages"
    
    # Primary key
    id = Column(Integer, primary_key=True, index=True)
    
    # Foreign key to User - who wrote this message
    user_id = Column(Integer, ForeignKey("users.id"), index=True)
    
    # Message content (text, may contain hashtags and URLs)
    content = Column(String)
    
    # When the message was posted
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    
    # Self-referential foreign key for threaded conversations
    # - nullable=True: Top-level messages have no parent (parent_id=None)
    # - For replies, this points to the parent message's ID
    parent_id = Column(Integer, ForeignKey("messages.id"), nullable=True, index=True)
    
    # Self-referential relationship for replies
    # - backref="parent": Creates Message.parent to access the parent message
    # - remote_side=[id]: Tells SQLAlchemy which side is the "parent" in the self-join
    # - cascade="all, delete-orphan": If a parent message is deleted, all replies are too
    # This allows: message.replies (list of child messages) and reply.parent (parent message)
    replies = relationship(
        "Message",
        backref=backref("parent", remote_side=[id]),
        cascade="all, delete-orphan"
    )
    
    # Many-to-one relationship with User
    # - backref="messages": Creates User.messages (all messages by a user)
    # This allows: message.user (get the author) and user.messages (get all their posts)
    # Many-to-one relationship with User
    # - backref="messages": Creates User.messages (all messages by a user)
    # This allows: message.user (get the author) and user.messages (get all their posts)
    # cascade="all, delete-orphan": If a user is deleted, all their messages are too
    user = relationship("User", backref=backref("messages", cascade="all, delete-orphan"))


class BlacklistedEmail(Base):
    """
    Model for blacklisted email addresses.
    
    Users with these emails are blocked from signing up or logging in.
    This is used when a superuser bans a user.
    """
    __tablename__ = "blacklisted_emails"
    
    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True)
    reason = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class AuditLog(Base):
    """
    Model for audit logs.
    
    Records important actions taken by users and superusers for auditing purposes.
    """
    __tablename__ = "audit_logs"
    
    id = Column(Integer, primary_key=True, index=True)
    action = Column(String, index=True)  # e.g., "user_created", "message_deleted"
    user_email = Column(String, index=True)  # Email of the actor
    details = Column(String, nullable=True)  # JSON or text description
    created_at = Column(DateTime, default=datetime.utcnow)



