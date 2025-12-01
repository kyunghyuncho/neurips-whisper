from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Table
from sqlalchemy.orm import declarative_base, relationship, backref
from datetime import datetime

Base = declarative_base()

star_association = Table('stars', Base.metadata,
    Column('user_id', Integer, ForeignKey('users.id')),
    Column('message_id', Integer, ForeignKey('messages.id'))
)

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True)
    terms_accepted_at = Column(DateTime, default=datetime.utcnow)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    starred_messages = relationship("Message", secondary=star_association, backref="starred_by")

class Message(Base):
    __tablename__ = "messages"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    content = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)
    parent_id = Column(Integer, ForeignKey("messages.id"), nullable=True)
    
    replies = relationship("Message", backref=backref("parent", remote_side=[id]), cascade="all, delete-orphan")
    user = relationship("User", backref="messages")


