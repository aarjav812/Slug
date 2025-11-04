import os
from dotenv import load_dotenv

# Load .env file FIRST, before any other imports that might use environment variables
# This ensures Config and other modules can read environment variables correctly
# On Vercel, .env doesn't exist (uses environment variables from dashboard)
basedir = os.path.abspath(os.path.dirname(__file__))
env_path = os.path.join(basedir, '.env')
if os.path.exists(env_path):
    load_dotenv(env_path)
else:
    # Running on serverless platform - environment variables are already set
    load_dotenv()  # This will load from system environment

from flask import Flask, request, jsonify
from flask_cors import CORS
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from sqlalchemy import text

from config import Config
from database import db
from models import Report, Message, User, Post, Comment, Like, Save, ReportLike, ReportComment
from schemas import (
    ReportCreateSchema, MessageCreateSchema, ReportPublicSchema,
    RegisterSchema, LoginSchema, UserPublicSchema, CommentPublicSchema
)
from security import (
    gen_ticket_id, gen_access_code, hash_code, verify_code,
    issue_token, verify_token
)


def create_app() -> Flask:
    app = Flask(__name__)
    app.config.from_object(Config)

    # CORS configuration - handle both wildcard and specific origins
    cors_origins = app.config.get("CORS_ORIGINS", "*")
    
    # Parse comma-separated origins
    if isinstance(cors_origins, str):
        if cors_origins == "*":
            # Allow all origins
            cors_origins = "*"
        elif "," in cors_origins:
            # Parse comma-separated list
            cors_origins = [o.strip() for o in cors_origins.split(",") if o.strip()]
        else:
            # Single origin
            cors_origins = cors_origins.strip()
    
    # Configure CORS
    CORS(app, 
         resources={r"/*": {"origins": cors_origins}},  # Changed from /api/* to /* to catch all routes
         allow_headers=["Content-Type", "Authorization", "X-Access-Code"],
         methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
         supports_credentials=False)

    db.init_app(app)

    # NOTE: Database initialization moved out to avoid import-time side effects
    # that crash serverless platforms. Call init_db() explicitly when needed.

    def get_current_user():
        auth = request.headers.get("Authorization", "")
        parts = auth.split()
        if len(parts) == 2 and parts[0].lower() == "bearer":
            data = verify_token(parts[1])
            if data and (uid := data.get("uid")):
                user = User.query.get(uid)
                if user:
                    return user
        return None

    def get_report_or_404(ticket: str):
        return Report.query.filter_by(ticket=ticket).first()

    def require_code_and_report(ticket: str):
        code = request.args.get("code", "") or request.headers.get("X-Access-Code", "")
        rpt = get_report_or_404(ticket)
        if not rpt:
            return None, jsonify({"error": "Not found"}), 404
        if not code or not verify_code(code, rpt.code_hash):
            return None, jsonify({"error": "Forbidden"}), 403
        return rpt, None, None

    # -----------------------
    # Root & Health Check
    # -----------------------
    @app.get("/")
    def root():
        """Root endpoint - helps verify the app is running"""
        db_uri = app.config.get('SQLALCHEMY_DATABASE_URI', 'NOT SET')
        # Mask sensitive info but show structure
        if db_uri and db_uri != 'NOT SET':
            # Show protocol and host but hide credentials
            if '@' in db_uri:
                protocol = db_uri.split('://')[0] if '://' in db_uri else 'unknown'
                host_part = db_uri.split('@')[1] if '@' in db_uri else 'unknown'
                db_uri_safe = f"{protocol}://***:***@{host_part}"
            else:
                db_uri_safe = "sqlite (local)"
        else:
            db_uri_safe = "NOT CONFIGURED"
            
        return jsonify({
            "message": "SlugLime API",
            "version": "1.0.0",
            "database": db_uri_safe,
            "endpoints": {
                "health": "/api/v1/health",
                "auth": {
                    "register": "/api/v1/auth/register",
                    "login": "/api/v1/auth/login"
                },
                "reports": "/api/v1/reports",
                "feed": "/api/v1/feed"
            }
        }), 200
    
    @app.get("/api/v1/health")
    def health_check():
        """Health check endpoint to verify server is running"""
        # Lazy initialization: ensure tables exist on first health check
        try:
            db.create_all()
        except Exception as init_error:
            print(f"⚠ Lazy DB init warning: {init_error}")
        
        # Check database connection
        db_status = "unknown"
        db_error = None
        try:
            with app.app_context():
                # Try a simple query
                db.session.execute(text("SELECT 1"))
                db_status = "connected"
        except Exception as e:
            db_status = "disconnected"
            db_error = str(e)[:200]  # First 200 chars of error
        
        return jsonify({
            "status": "healthy" if db_status == "connected" else "degraded",
            "message": "SlugLime backend is running",
            "version": "1.0.0",
            "database": {
                "status": db_status,
                "type": "postgresql" if "postgresql" in app.config.get('SQLALCHEMY_DATABASE_URI', '') else "sqlite",
                "error": db_error
            }
        }), 200

    # -----------------------
    # Auth Routes
    # -----------------------
    @app.post("/api/v1/auth/register")
    def register():
        payload = request.get_json(silent=True) or {}
        errors = RegisterSchema().validate(payload)
        if errors:
            return jsonify({"errors": errors}), 400

        if User.query.filter_by(email=payload["email"].lower()).first():
            return jsonify({"error": "Email already registered"}), 400

        user = User(
            email=payload["email"].lower(),
            name=payload["name"],
            password_hash=generate_password_hash(payload["password"]),
            avatar_url=None,
            verified=False,
        )
        db.session.add(user)
        db.session.commit()

        token = issue_token({"uid": user.id})
        return jsonify({"token": token, "user": UserPublicSchema().dump(user)}), 201

    @app.post("/api/v1/auth/login")
    def login():
        payload = request.get_json(silent=True) or {}
        errors = LoginSchema().validate(payload)
        if errors:
            return jsonify({"errors": errors}), 400

        user = User.query.filter_by(email=payload["email"].lower()).first()
        if not user or not check_password_hash(user.password_hash, payload["password"]):
            return jsonify({"error": "Invalid credentials"}), 401

        token = issue_token({"uid": user.id})
        return jsonify({"token": token, "user": UserPublicSchema().dump(user)}), 200

    @app.get("/api/v1/feed")
    def get_feed():
        user = get_current_user()
        posts = Post.query.order_by(Post.created_at.desc()).limit(20).all()
        items = []
        for p in posts:
            like_count = len(p.likes)
            comment_count = len(p.comments)
            liked = False
            saved = False
            if user:
                liked = any(l.user_id == user.id for l in p.likes)
                saved = any(s.user_id == user.id for s in p.saves)
            items.append({
                "id": p.id,
                "caption": p.caption,
                "image_url": p.image_url,
                "created_at": p.created_at.isoformat(),
                "author": {
                    "id": p.author.id,
                    "email": p.author.email,
                    "name": p.author.name,
                    "avatar_url": p.author.avatar_url,
                    "verified": p.author.verified,
                },
                "like_count": like_count,
                "comment_count": comment_count,
                "liked": liked,
                "saved": saved,
            })
        return jsonify({"posts": items}), 200

    @app.post("/api/v1/posts")
    def create_post():
        user = get_current_user()
        if not user:
            return jsonify({"error": "Unauthorized"}), 401
        payload = request.get_json(silent=True) or {}
        image_url = (payload.get("image_url") or "").strip()
        caption = (payload.get("caption") or "").strip()
        if not image_url:
            return jsonify({"error": "image_url required"}), 400
        p = Post(user_id=user.id, image_url=image_url, caption=caption)
        db.session.add(p)
        db.session.commit()
        return jsonify({"id": p.id}), 201

    @app.post("/api/v1/posts/<int:post_id>/like")
    def like_post(post_id: int):
        user = get_current_user()
        if not user:
            return jsonify({"error": "Unauthorized"}), 401

        post = Post.query.get_or_404(post_id)
        existing = Like.query.filter_by(post_id=post.id, user_id=user.id).first()
        if existing:
            db.session.delete(existing)
            db.session.commit()
            liked = False
        else:
            like = Like(post_id=post.id, user_id=user.id)
            db.session.add(like)
            db.session.commit()
            liked = True

        return jsonify({"liked": liked, "like_count": len(post.likes)}), 200

    @app.post("/api/v1/posts/<int:post_id>/save")
    def save_post(post_id: int):
        user = get_current_user()
        if not user:
            return jsonify({"error": "Unauthorized"}), 401

        post = Post.query.get_or_404(post_id)
        existing = Save.query.filter_by(post_id=post.id, user_id=user.id).first()
        if existing:
            db.session.delete(existing)
            db.session.commit()
            saved = False
        else:
            s = Save(post_id=post.id, user_id=user.id)
            db.session.add(s)
            db.session.commit()
            saved = True

        return jsonify({"saved": saved}), 200

    @app.post("/api/v1/posts/<int:post_id>/comments")
    def add_comment(post_id: int):
        user = get_current_user()
        if not user:
            return jsonify({"error": "Unauthorized"}), 401
        body = (request.get_json(silent=True) or {}).get("body", "").strip()
        if not body:
            return jsonify({"error": "Body required"}), 400

        post = Post.query.get_or_404(post_id)
        c = Comment(post_id=post.id, user_id=user.id, body=body)
        db.session.add(c)
        db.session.commit()
        return jsonify({
            "comment": CommentPublicSchema().dump(c),
            "comment_count": len(post.comments)
        }), 201

    @app.get("/api/v1/reports/public")
    def get_public_reports():
        """Get public whistleblower reports for the main feed with pagination"""
        # Lazy initialization: ensure tables exist on first request
        try:
            db.create_all()
        except Exception as init_error:
            print(f"⚠ Lazy DB init warning in get_public_reports: {init_error}")
        
        # Pagination parameters
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 20, type=int)
        
        # Limit per_page to prevent abuse
        per_page = min(per_page, 100)
        
        try:
            # Use pagination
            pagination = Report.query.filter_by(status="open").order_by(Report.created_at.desc()).paginate(
                page=page, 
                per_page=per_page, 
                error_out=False
            )
            reports = pagination.items
            
        except Exception as e:
            # Database connection error
            app.logger.error(f"Database error in get_public_reports: {e}")
            return jsonify({
                "error": "Database connection failed",
                "message": "Could not fetch reports. Please check database configuration.",
                "details": str(e)[:200] if app.debug else None
            }), 500

        items = []
        for rpt in reports:
            # Get actual like and comment counts
            like_count = ReportLike.query.filter_by(report_id=rpt.id).count()
            comment_count = ReportComment.query.filter_by(report_id=rpt.id).count()
            
            items.append({
                "id": rpt.id,  # Use actual report ID for frontend operations
                "type": "report",
                "ticket": rpt.ticket,
                "title": rpt.title,
                "category": rpt.category,
                "body": rpt.body[:200] + "..." if len(rpt.body) > 200 else rpt.body,
                "created_at": rpt.created_at.isoformat(),
                "author": {
                    "id": None,
                    "email": None,
                    "name": "Anonymous Whistleblower",
                    "avatar_url": "https://via.placeholder.com/40x40/ffd700/000000?text=W",
                    "verified": True,
                },
                "like_count": like_count,
                "comment_count": comment_count,
                "liked": False,
                "saved": False,
                "status": rpt.status,
            })

        return jsonify({
            "reports": items,
            "pagination": {
                "page": pagination.page,
                "per_page": pagination.per_page,
                "total": pagination.total,
                "pages": pagination.pages,
                "has_next": pagination.has_next,
                "has_prev": pagination.has_prev
            }
        }), 200

    @app.post("/api/v1/reports")
    def create_report():
        payload = request.get_json(silent=True)
        if payload is None:
            payload = {k: v for k, v in request.form.items()}

        errors = ReportCreateSchema().validate(payload)
        if errors:
            return jsonify({"errors": errors}), 400

        ticket = gen_ticket_id()
        code = gen_access_code()

        rpt = Report(
            ticket=ticket,
            title=payload["title"].strip(),
            category=payload.get("category", "").strip() or None,
            body=payload["body"].strip(),
            code_hash=hash_code(code),
        )
        db.session.add(rpt)
        db.session.commit()

        upload_folder = app.config.get("UPLOAD_FOLDER")
        for fkey in request.files:
            f = request.files.get(fkey)
            if f and getattr(f, 'filename', None):
                filename = secure_filename(f.filename)
                dest = os.path.join(upload_folder, f"{ticket}_{filename}")
                try:
                    f.save(dest)
                except Exception:
                    pass

        return jsonify({"ticket": ticket, "access_code": code}), 201

    @app.get("/api/v1/reports/<ticket>")
    def get_report(ticket: str):
        rpt, err_resp, err_code = require_code_and_report(ticket)
        if err_resp:
            return err_resp, err_code
        return jsonify(ReportPublicSchema().dump(rpt)), 200

    @app.post("/api/v1/reports/<ticket>/messages")
    def post_report_message(ticket: str):
        rpt, err_resp, err_code = require_code_and_report(ticket)
        if err_resp:
            return err_resp, err_code
        
        payload = request.get_json(silent=True) or {}
        errors = MessageCreateSchema().validate(payload)
        if errors:
            return jsonify({"errors": errors}), 400

        msg = Message(
            report_id=rpt.id,
            body=payload["body"].strip(),
            author="user"
        )
        db.session.add(msg)
        db.session.commit()

        return jsonify({"message": "Message posted", "id": msg.id}), 201

    @app.post("/api/v1/reports/<int:report_id>/like")
    def like_report(report_id: int):
        """Like or unlike a report. Anonymous users can like using email."""
        # Ensure tables exist
        try:
            db.create_all()
        except Exception as e:
            print(f"⚠ Table creation warning: {e}")
        
        payload = request.get_json(silent=True) or {}
        user_email = payload.get("email", "anonymous@example.com")
        
        if not user_email or "@" not in user_email:
            return jsonify({"error": "Valid email required"}), 400
        
        try:
            report = Report.query.get_or_404(report_id)
            existing = ReportLike.query.filter_by(report_id=report.id, user_email=user_email).first()
            
            if existing:
                db.session.delete(existing)
                db.session.commit()
                liked = False
            else:
                like = ReportLike(report_id=report.id, user_email=user_email)
                db.session.add(like)
                db.session.commit()
                liked = True

            like_count = ReportLike.query.filter_by(report_id=report.id).count()
            return jsonify({"liked": liked, "like_count": like_count}), 200
        except Exception as e:
            app.logger.error(f"Error in like_report: {e}")
            return jsonify({"error": "Failed to like report", "details": str(e)}), 500

    @app.post("/api/v1/reports/<int:report_id>/comments")
    def add_report_comment(report_id: int):
        """Add a comment to a report. Anonymous users can comment."""
        # Ensure tables exist
        try:
            db.create_all()
        except Exception as e:
            print(f"⚠ Table creation warning: {e}")
        
        payload = request.get_json(silent=True) or {}
        
        body = payload.get("body", "").strip()
        user_email = payload.get("email", "anonymous@example.com")  # Default email if not provided
        user_name = payload.get("name", "Anonymous").strip()
        
        if not body:
            return jsonify({"error": "Comment body required"}), 400

        try:
            report = Report.query.get_or_404(report_id)
            comment = ReportComment(
                report_id=report.id,
                user_email=user_email,
                user_name=user_name,
                body=body
            )
            db.session.add(comment)
            db.session.commit()
            
            comment_count = ReportComment.query.filter_by(report_id=report.id).count()
            return jsonify({
                "comment": {
                    "id": comment.id,
                    "user_name": comment.user_name,
                    "body": comment.body,
                    "created_at": comment.created_at.isoformat()
                },
                "comment_count": comment_count
            }), 201
        except Exception as e:
            app.logger.error(f"Error in add_report_comment: {e}")
            return jsonify({"error": "Failed to add comment", "details": str(e)}), 500

    @app.get("/api/v1/reports/<int:report_id>/comments")
    def get_report_comments(report_id: int):
        """Get all comments for a report."""
        report = Report.query.get_or_404(report_id)
        comments = ReportComment.query.filter_by(report_id=report.id).order_by(ReportComment.created_at.desc()).all()
        
        return jsonify({
            "comments": [{
                "id": c.id,
                "user_name": c.user_name,
                "body": c.body,
                "created_at": c.created_at.isoformat()
            } for c in comments]
        }), 200

    # -----------------------
    # Error Handlers
    # -----------------------
    @app.errorhandler(500)
    def internal_error(error):
        """Handle internal server errors"""
        app.logger.error(f'Server Error: {error}')
        return jsonify({
            "error": "Internal server error",
            "message": "The server encountered an internal error. Please check the server logs."
        }), 500

    @app.errorhandler(404)
    def not_found(error):
        """Handle 404 errors"""
        return jsonify({
            "error": "Not found",
            "message": f"The requested URL {request.url} was not found on the server.",
            "available_endpoints": [rule.rule for rule in app.url_map.iter_rules() if rule.rule.startswith('/api')]
        }), 404

    @app.errorhandler(Exception)
    def handle_exception(e):
        """Handle uncaught exceptions"""
        app.logger.error(f'Unhandled Exception: {e}', exc_info=True)
        return jsonify({
            "error": "An unexpected error occurred",
            "message": str(e) if app.debug else "Please contact support"
        }), 500

    return app


def init_app_resources(app: Flask) -> None:
    """
    Initialize filesystem resources (folders, database tables).
    Call this explicitly when running locally or during deployment setup.
    DO NOT call during module import - serverless platforms have read-only filesystems.
    """
    with app.app_context():
        try:
            # Try to create instance folder for SQLite database
            os.makedirs(app.instance_path, exist_ok=True)
        except (OSError, PermissionError) as e:
            # Read-only filesystem (e.g., Vercel) - skip folder creation
            print(f"⚠ Cannot create instance folder (read-only filesystem): {e}")
        
        try:
            # Try to create upload folder
            upload_folder = app.config.get("UPLOAD_FOLDER", os.path.join(app.instance_path, "uploads"))
            os.makedirs(upload_folder, exist_ok=True)
        except (OSError, PermissionError) as e:
            print(f"⚠ Cannot create upload folder (read-only filesystem): {e}")
        
        try:
            # Create database tables
            db.create_all()
            print(f"✓ Database initialized at: {app.config.get('SQLALCHEMY_DATABASE_URI')}")
        except Exception as e:
            print(f"⚠ Database initialization warning: {e}")


# Create the Flask app instance (safe for serverless import)
app = create_app()


def init_db():
    """
    Initialize database tables. Safe to call on serverless platforms.
    Only creates tables if they don't exist - idempotent operation.
    Call this AFTER app is created (import time is safe).
    """
    with app.app_context():
        try:
            db.create_all()
            print("✓ Database tables initialized")
        except Exception as e:
            print(f"⚠ Database init warning: {e}")


def main():
    """Main entry point with environment checks"""
    import sys
    
    # Check Python version
    if sys.version_info < (3, 10):
        print("ERROR: Python 3.10 or higher is required")
        print(f"Current version: {sys.version}")
        sys.exit(1)
    
    # Check if SECRET_KEY is set
    if not os.getenv("SECRET_KEY"):
        print("WARNING: SECRET_KEY not set in environment")
        print("Using a randomly generated key (tokens will be invalidated on restart)")
    
    # Get host and port from config
    from config import Config
    host = Config.FLASK_HOST
    port = Config.FLASK_PORT
    
    print("="*60)
    print("Starting SlugLime Backend Server")
    print("="*60)
    print(f"Python version: {sys.version.split()[0]}")
    try:
        from importlib.metadata import version
        print(f"Flask version: {version('flask')}")
    except:
        print("Flask version: 3.0.3")
    print(f"Server: http://{host}:{port}")
    print("="*60)
    
    try:
        # Use the module-level app instance
        global app
        
        # Initialize filesystem resources for local development
        init_app_resources(app)
        
        upload_folder = app.config.get("UPLOAD_FOLDER", os.path.join(app.instance_path, "uploads"))
        print(f"✓ Upload folder: {upload_folder}")
        
        # Use debug=False to avoid reloader path issues on Windows
        app.run(host=host, port=port, debug=False)
    except Exception as e:
        print(f"\nERROR: Failed to start server: {e}")
        print("\nTroubleshooting:")
        print("1. Check if port 5000 is already in use")
        print("2. Verify .env file exists and has SECRET_KEY set")
        print("3. Run: python check_setup.py")
        sys.exit(1)


if __name__ == "__main__":
    main()
