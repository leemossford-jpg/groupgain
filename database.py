"""
GroupGain — Database Models
Clean structure with multi-day trade group support
"""

from datetime import datetime
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin

db = SQLAlchemy()


class User(UserMixin, db.Model):
    """User account — profile, permissions & relationships"""
    __tablename__ = "user"
    
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    
    bio = db.Column(db.Text, default="No bio yet...")
    profile_pic = db.Column(db.String(200), default="default.png")
    
    is_approved = db.Column(db.Boolean, default=False)
    is_admin = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    posts = db.relationship(
        "FeedPost", backref="author",
        cascade="all, delete-orphan", lazy=True
    )
    entries = db.relationship(
        "DailyEntry", backref="user",
        cascade="all, delete-orphan", lazy=True
    )
    targets = db.relationship(
        "UserTarget", backref="user",
        cascade="all, delete-orphan", lazy=True
    )
    reset_requests = db.relationship(
        "PasswordResetRequest", backref="user",
        cascade="all, delete-orphan", lazy=True
    )
    chat_messages = db.relationship(
        "ChatMessage", backref="author",
        cascade="all, delete-orphan", lazy=True
    )
    
    def __repr__(self):
        return f"<User: {self.username}>"


class DailyEntry(db.Model):
    """Daily profit/loss entry — supports multi-day trade groups"""
    __tablename__ = "daily_entry"
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    date = db.Column(db.Date, nullable=False)
    profit_loss = db.Column(db.Float, nullable=False)
    notes = db.Column(db.Text, default="")
    
    # Multi-day trade grouping
    group_id = db.Column(db.String(100), nullable=True)
    group_total = db.Column(db.Float, nullable=True)
    
    def __repr__(self):
        return f"<Entry: {self.date} | £{self.profit_loss:.2f}>"


class UserTarget(db.Model):
    """Admin-set daily & monthly profit targets"""
    __tablename__ = "user_target"
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    daily_target = db.Column(db.Float, default=0.0)
    monthly_target = db.Column(db.Float, default=0.0)


class FeedPost(db.Model):
    """Social feed post — status updates from users"""
    __tablename__ = "feed_post"
    
    id = db.Column(db.Integer, primary_key=True)
    author_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    content = db.Column(db.Text, nullable=False)
    post_type = db.Column(db.String(30), default="status")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    comments = db.relationship(
        "Comment", backref="post",
        cascade="all, delete-orphan", lazy=True
    )
    
    def __repr__(self):
        return f"<Post by {self.author.username}>"


class Comment(db.Model):
    """Comment on a feed post"""
    __tablename__ = "comment"
    
    id = db.Column(db.Integer, primary_key=True)
    post_id = db.Column(db.Integer, db.ForeignKey("feed_post.id"), nullable=False)
    author_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class PasswordResetRequest(db.Model):
    """Admin-approved password reset request"""
    __tablename__ = "password_reset"
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    is_resolved = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class ChatMessage(db.Model):
    """Live group chat message"""
    __tablename__ = "chat_message"
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
