from datetime import datetime
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin

db = SQLAlchemy()

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    bio = db.Column(db.Text, default="")
    profile_pic = db.Column(db.String(200), default="default.png")
    is_approved = db.Column(db.Boolean, default=False)
    is_admin = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    posts = db.relationship('FeedPost', backref='author', cascade="all, delete-orphan", lazy=True)
    entries = db.relationship('DailyEntry', backref='user', cascade="all, delete-orphan", lazy=True)
    targets = db.relationship('UserTarget', backref='user', cascade="all, delete-orphan", lazy=True)
    chat_messages = db.relationship('ChatMessage', backref='author', cascade="all, delete-orphan", lazy=True)

class DailyEntry(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    entry_date = db.Column(db.Date, nullable=False)
    profit_loss = db.Column(db.Float, default=0.0)
    notes = db.Column(db.Text, default="")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class UserTarget(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, unique=True)
    daily_target = db.Column(db.Float, default=0.0)
    monthly_target = db.Column(db.Float, default=0.0)

class FeedPost(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    content = db.Column(db.Text, nullable=False)
    post_type = db.Column(db.String(20), default="status")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class ChatMessage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
