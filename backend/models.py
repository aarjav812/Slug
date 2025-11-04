from datetime import datetime
from database import db


class Report(db.Model):
    __tablename__ = "reports"
    id = db.Column(db.Integer, primary_key=True)
    ticket = db.Column(db.String(24), unique=True, index=True, nullable=False)
    title = db.Column(db.String(200), nullable=False)
    category = db.Column(db.String(120), nullable=True)
    body = db.Column(db.Text, nullable=False)
    code_hash = db.Column(db.String(255), nullable=False)
    status = db.Column(db.String(20), default="open", nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    messages = db.relationship("Message", backref="report", cascade="all, delete-orphan", order_by="Message.created_at")

class Message(db.Model):
    __tablename__ = "messages"
    id = db.Column(db.Integer, primary_key=True)
    report_id = db.Column(db.Integer, db.ForeignKey("reports.id", ondelete="CASCADE"), nullable=False)
    body = db.Column(db.Text, nullable=False)
    author = db.Column(db.String(32), default="user", nullable=False)  # "user" | "staff"
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


# ---- Social feed models to support frontend Main page ----

class User(db.Model):
    __tablename__ = "users"
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, index=True, nullable=False)
    name = db.Column(db.String(120), nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    avatar_url = db.Column(db.String(512), nullable=True)
    verified = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    posts = db.relationship("Post", backref="author", cascade="all, delete-orphan")


class Post(db.Model):
    __tablename__ = "posts"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    image_url = db.Column(db.String(1024), nullable=False)
    caption = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    comments = db.relationship("Comment", backref="post", cascade="all, delete-orphan")
    likes = db.relationship("Like", backref="post", cascade="all, delete-orphan")
    saves = db.relationship("Save", backref="post", cascade="all, delete-orphan")


class Comment(db.Model):
    __tablename__ = "comments"
    id = db.Column(db.Integer, primary_key=True)
    post_id = db.Column(db.Integer, db.ForeignKey("posts.id", ondelete="CASCADE"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    body = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    user = db.relationship("User")


class Like(db.Model):
    __tablename__ = "likes"
    id = db.Column(db.Integer, primary_key=True)
    post_id = db.Column(db.Integer, db.ForeignKey("posts.id", ondelete="CASCADE"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        db.UniqueConstraint("post_id", "user_id", name="uq_like_post_user"),
    )


class Save(db.Model):
    __tablename__ = "saves"
    id = db.Column(db.Integer, primary_key=True)
    post_id = db.Column(db.Integer, db.ForeignKey("posts.id", ondelete="CASCADE"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        db.UniqueConstraint("post_id", "user_id", name="uq_save_post_user"),
    )


class ReportLike(db.Model):
    __tablename__ = "report_likes"
    id = db.Column(db.Integer, primary_key=True)
    report_id = db.Column(db.Integer, db.ForeignKey("reports.id", ondelete="CASCADE"), nullable=False)
    user_email = db.Column(db.String(255), nullable=False)  # Anonymous users can like
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        db.UniqueConstraint("report_id", "user_email", name="uq_report_like_user"),
    )


class ReportComment(db.Model):
    __tablename__ = "report_comments"
    id = db.Column(db.Integer, primary_key=True)
    report_id = db.Column(db.Integer, db.ForeignKey("reports.id", ondelete="CASCADE"), nullable=False)
    user_email = db.Column(db.String(255), nullable=False)  # Anonymous users can comment
    user_name = db.Column(db.String(120), nullable=False, default="Anonymous")
    body = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    report = db.relationship("Report", backref="public_comments")
