from flask import Flask, render_template, request, redirect, url_for, flash
from flask_bcrypt import Bcrypt
from flask_login import LoginManager, login_user, login_required, logout_user, current_user
from datetime import datetime, date
import calendar
import os
from io import BytesIO
import base64
import qrcode

app = Flask(__name__)
basedir = os.path.abspath(os.path.dirname(__file__))

if "DATABASE_URL" in os.environ:
    app.config["SQLALCHEMY_DATABASE_URI"] = os.environ["DATABASE_URL"]
else:
    app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{os.path.join(basedir, 'groupgain.db')}"

app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "groupgain_secure_2026")
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

bcrypt = Bcrypt(app)
login_manager = LoginManager(app)
login_manager.login_view = "login"

from database import db, User, DailyEntry, UserTarget, FeedPost, ChatMessage
db.init_app(app)

with app.app_context():
    db.create_all()
    if not User.query.filter_by(username="admin").first():
        admin = User(
            username="admin",
            password_hash=bcrypt.generate_password_hash("Admin123!").decode("utf-8"),
            is_approved=True,
            is_admin=True
        )
        db.session.add(admin)
        db.session.commit()

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# Helper functions — defined BEFORE routes
def get_base_url():
    return os.environ.get("RENDER_EXTERNAL_URL", request.host_url.rstrip("/"))

def get_targets_safe(user):
    t = UserTarget.query.filter_by(user_id=user.id).first()
    if not t:
        t = UserTarget(user_id=user.id)
        db.session.add(t)
        db.session.commit()
    return t

# Routes
@app.route("/signup", methods=["GET", "POST"])
def signup():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))
    if request.method == "POST":
        un = request.form.get("username", "").strip()
        if User.query.filter_by(username=un).first():
            flash("Username taken", "error")
            return redirect(url_for("signup"))
        pw = request.form.get("password")
        u = User(username=un, password_hash=bcrypt.generate_password_hash(pw).decode("utf-8"))
        db.session.add(u)
        db.session.commit()
        flash("Account created — waiting admin approval", "success")
        return redirect(url_for("login"))
    return render_template("signup.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))
    if request.method == "POST":
        un = request.form.get("username", "").strip()
        u = User.query.filter_by(username=un).first()
        pw = request.form.get("password")
        if not u or not bcrypt.check_password_hash(u.password_hash, pw):
            flash("Invalid login", "error")
            return redirect(url_for("login"))
        if not u.is_approved:
            flash("Waiting approval", "error")
            return redirect(url_for("login"))
        login_user(u, remember=True)
        return redirect(url_for("dashboard"))
    return render_template("login.html")

@app.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("login"))

@app.route("/")
@login_required
def dashboard():
    today = date.today()
    month_start = date(today.year, today.month, 1)
    t = get_targets_safe(current_user)
    
    today_entries = DailyEntry.query.filter_by(user_id=current_user.id, entry_date=today).all()
    today_total = round(sum((e.profit_loss or 0) for e in today_entries), 2)
    
    month_entries = DailyEntry.query.filter(DailyEntry.user_id==current_user.id, DailyEntry.entry_date >= month_start).all()
    month_total = round(sum((e.profit_loss or 0) for e in month_entries), 2)
    
    messages = ChatMessage.query.order_by(ChatMessage.created_at.asc()).limit(50).all()
    return render_template("dashboard.html", today=today, today_total=today_total, 
                           month_total=month_total, daily_target=t.daily_target, 
                           monthly_target=t.monthly_target, messages=messages)

@app.route("/calendar")
@app.route("/calendar/<int:y>/<int:m>")
@login_required
def calendar_view(y=None, m=None):
    today = date.today()
    y = y or today.year
    m = m or today.month
    
    prev_m, prev_y = (m-1, y) if m > 1 else (12, y-1)
    next_m, next_y = (m+1, y) if m < 12 else (1, y+1)
    
    start = date(y, m, 1)
    end_day = calendar.monthrange(y, m)[1]
    end = date(y, m, end_day)
    
    entries = DailyEntry.query.filter(DailyEntry.user_id==current_user.id, 
                                       DailyEntry.entry_date >= start, 
                                       DailyEntry.entry_date <= end).all()
    day_totals = {}
    for e in entries:
        day_totals[e.entry_date] = day_totals.get(e.entry_date, 0) + (e.profit_loss or 0)
    
    t = get_targets_safe(current_user)
    return render_template("calendar.html", today=today, year=y, month=m, 
                           month_name=calendar.month_name[m], 
                           calendar_weeks=calendar.monthcalendar(y, m),
                           daily_totals=day_totals, prev_year=prev_y, 
                           prev_month=prev_m, next_year=next_y, 
                           next_month=next_m, daily_target=t.daily_target)

@app.route("/entry/add", methods=["POST"])
@login_required
def add_entry():
    try:
        ed = datetime.strptime(request.form.get("entry_date"), "%Y-%m-%d").date()
        pl = float(request.form.get("profit_loss", 0))
        notes = request.form.get("notes", "")
        
        db.session.add(DailyEntry(user_id=current_user.id, entry_date=ed, 
                                   profit_loss=pl, notes=notes))
        
        sign = "+" if pl >= 0 else ""
        db.session.add(FeedPost(user_id=current_user.id, 
                                content=f"📊 Posted: {sign}£{pl:.2f} on {ed}", 
                                post_type="result"))
        db.session.commit()
        flash(f"Added: {sign}£{pl:.2f}", "success")
    except Exception as e:
        flash(f"Error: {e}", "error")
    return redirect(url_for("calendar_view"))

@app.route("/targets", methods=["GET", "POST"])
@login_required
def targets():
    t = get_targets_safe(current_user)
    if request.method == "POST" and current_user.is_admin:
        dt = float(request.form.get("daily_target", 0))
        mt = float(request.form.get("monthly_target", 0))
        for u in User.query.filter_by(is_approved=True).all():
            ut = get_targets_safe(u)
            ut.daily_target = dt
            ut.monthly_target = mt
        db.session.commit()
        flash("Targets updated for all users", "success")
    return render_template("targets.html", daily_target=t.daily_target, 
                           monthly_target=t.monthly_target)

@app.route("/share")
@login_required
def share():
    url = get_base_url() + url_for("signup")
    qr = None
    try:
        buf = BytesIO()
        qrcode.make(url).save(buf, "PNG")
        qr = base64.b64encode(buf.getvalue()).decode()
    except Exception as e:
        flash(f"QR generation skipped: {e}", "info")
    return render_template("share.html", signup_url=url, qr_data=qr)

@app.route("/feed")
@login_required
def feed():
    posts = FeedPost.query.order_by(FeedPost.created_at.desc()).all()
    return render_template("feed.html", posts=posts)

@app.route("/post/status", methods=["POST"])
@login_required
def post_status():
    c = request.form.get("content", "").strip()
    if c:
        db.session.add(FeedPost(user_id=current_user.id, content=c, post_type="status"))
        db.session.commit()
        flash("Posted to feed", "success")
    return redirect(url_for("feed"))

@app.route("/chat/send", methods=["POST"])
@login_required
def send_chat():
    m = request.form.get("chat_message", "").strip()
    if m:
        db.session.add(ChatMessage(user_id=current_user.id, content=m))
        db.session.commit()
    return redirect(url_for("dashboard"))

@app.route("/admin")
@login_required
def admin_panel():
    if not current_user.is_admin:
        flash("Admin access only", "error")
        return redirect(url_for("dashboard"))
    return render_template("admin.html", users=User.query.all())

@app.route("/admin/approve/<int:uid>", methods=["POST"])
@login_required
def approve(uid):
    if not current_user.is_admin:
        return redirect(url_for("dashboard"))
    u = User.query.get_or_404(uid)
    u.is_approved = True
    get_targets_safe(u)
    db.session.commit()
    flash(f"Approved: {u.username}", "success")
    return redirect(url_for("admin_panel"))

@app.route("/admin/remove/<int:uid>", methods=["POST"])
@login_required
def remove(uid):
    if not current_user.is_admin:
        return redirect(url_for("dashboard"))
    u = User.query.get_or_404(uid)
    if u.id == current_user.id:
        flash("Cannot remove yourself", "error")
        return redirect(url_for("admin_panel"))
    db.session.delete(u)
    db.session.commit()
    flash(f"Removed: {u.username}", "success")
    return redirect(url_for("admin_panel"))

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
