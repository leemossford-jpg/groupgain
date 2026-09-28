from flask import Flask, render_template, request, redirect, url_for, flash, abort
from flask_bcrypt import Bcrypt
from flask_login import LoginManager, login_user, login_required, logout_user, current_user
from datetime import datetime, date, timedelta
import calendar
import os
from io import BytesIO
import base64
import qrcode
from database import db, User, DailyEntry, UserTarget, FeedPost, Comment, PasswordResetRequest, ChatMessage

app = Flask(__name__)

# ===== DATABASE CONFIG — Works on Render + Local =====
basedir = os.path.abspath(os.path.dirname(__file__))
if "DATABASE_URL" in os.environ:
    app.config["SQLALCHEMY_DATABASE_URI"] = os.environ["DATABASE_URL"]
    if app.config["SQLALCHEMY_DATABASE_URI"].startswith("postgres://"):
        app.config["SQLALCHEMY_DATABASE_URI"] = app.config["SQLALCHEMY_DATABASE_URI"].replace("postgres://", "postgresql://", 1)
else:
    app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{os.path.join(basedir, 'groupgain.db')}"

app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "groupgain_secret_secure_2026!")
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["UPLOAD_FOLDER"] = os.path.join("static", "profile_pics")
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024

os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)

db.init_app(app)
bcrypt = Bcrypt(app)
login_manager = LoginManager(app)
login_manager.login_view = "login"
login_manager.login_message_category = "info"

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# ===== CREATE TABLES & ADMIN (run once) =====
with app.app_context():
    db.create_all()
    if not User.query.filter_by(username="admin").first():
        admin_pass = bcrypt.generate_password_hash("Admin123!").decode("utf-8")
        admin = User(username="admin", password_hash=admin_pass, is_approved=True, is_admin=True, bio="GroupGain Founder 👑")
        db.session.add(admin)
        db.session.commit()
        print("✅ Admin created: admin / Admin123!")

# ===== UTILITY — Get Public URL =====
def get_public_url():
    if 'RENDER' in os.environ:
        return os.environ.get('RENDER_EXTERNAL_URL', None)
    try:
        import requests
        r = requests.get("http://127.0.0.1:4040/api/tunnels", timeout=2)
        if r.status_code == 200:
            tunnels = r.json()["tunnels"]
            for t in tunnels:
                if t["proto"] == "https":
                    return t["public_url"]
    except Exception:
        pass
    return None

# ===== AUTH ROUTES =====
@app.route("/signup", methods=["GET", "POST"])
def signup():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))
    if request.method == "POST":
        u = request.form.get("username", "").strip()
        p = request.form.get("password")
        if User.query.filter_by(username=u).first():
            flash("Username taken", "error")
            return redirect(url_for("signup"))
        ph = bcrypt.generate_password_hash(p).decode("utf-8")
        user = User(username=u, password_hash=ph)
        db.session.add(user)
        db.session.commit()
        flash("Account created — waiting admin approval", "success")
        return redirect(url_for("login"))
    return render_template("signup.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))
    if request.method == "POST":
        u = request.form.get("username", "").strip()
        p = request.form.get("password")
        user = User.query.filter_by(username=u).first()
        if not user or not bcrypt.check_password_hash(user.password_hash, p):
            flash("Invalid username or password", "error")
            return redirect(url_for("login"))
        if not user.is_approved:
            flash("Account not approved yet — contact admin", "error")
            return redirect(url_for("login"))
        login_user(user, remember=True)
        return redirect(url_for("dashboard"))
    return render_template("login.html")

@app.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("login"))

@app.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    if request.method == "POST":
        u = request.form.get("username", "").strip()
        user = User.query.filter_by(username=u).first()
        if user:
            if not PasswordResetRequest.query.filter_by(user_id=user.id, is_resolved=False).first():
                pr = PasswordResetRequest(user_id=user.id)
                db.session.add(pr)
                db.session.commit()
        flash("Request sent to admin", "success")
    return render_template("forgot.html")

# ===== DASHBOARD =====
@app.route("/")
@login_required
def dashboard():
    today = date.today()
    month_start = date(today.year, today.month, 1)
    
    today_entries = DailyEntry.query.filter_by(user_id=current_user.id, date=today).all()
    today_total = sum(e.profit_loss for e in today_entries)
    
    month_entries = DailyEntry.query.filter(
        DailyEntry.user_id == current_user.id,
        DailyEntry.date >= month_start
    ).all()
    month_total = sum(e.profit_loss for e in month_entries)
    
    tgt = UserTarget.query.filter_by(user_id=current_user.id).first()
    daily_target = tgt.daily_target if tgt else 0
    monthly_target = tgt.monthly_target if tgt else 0
    
    recent_entries = DailyEntry.query.filter_by(user_id=current_user.id)\
        .order_by(DailyEntry.date.desc()).limit(7).all()
    
    messages = ChatMessage.query.order_by(ChatMessage.created_at.asc()).limit(30).all()
    
    return render_template("dashboard.html",
        today=today,
        today_total=today_total,
        month_total=month_total,
        daily_target=daily_target,
        monthly_target=monthly_target,
        recent_entries=recent_entries,
        messages=messages
    )

# ===== ADD ENTRY =====
@app.route("/add-entry", methods=["POST"])
@login_required
def add_entry():
    d = datetime.strptime(request.form["entry_date"], "%Y-%m-%d").date()
    pl = float(request.form["profit_loss"])
    notes = request.form.get("notes", "")
    db.session.add(DailyEntry(user_id=current_user.id, date=d, profit_loss=pl, notes=notes))
    db.session.commit()
    flash("Entry added", "success")
    return redirect(url_for("dashboard"))

# ===== CALENDAR =====
@app.route("/calendar")
@login_required
def calendar_view():
    today = date.today()
    y, m = today.year, today.month
    cal = calendar.monthcalendar(y, m)
    month_name = calendar.month_name[m]
    
    entries = {}
    for e in DailyEntry.query.filter_by(user_id=current_user.id).all():
        entries[e.date] = e
    
    return render_template("calendar.html",
        year=y, month=m, month_name=month_name,
        calendar_weeks=cal, entries=entries, today=today
    )

@app.route("/edit-entry/<int:eid>", methods=["POST"])
@login_required
def edit_entry(eid):
    entry = DailyEntry.query.get_or_404(eid)
    if entry.user_id != current_user.id and not current_user.is_admin:
        abort(403)
    entry.profit_loss = float(request.form["profit_loss"])
    entry.notes = request.form.get("notes", "")
    db.session.commit()
    flash("Updated", "success")
    return redirect(url_for("calendar_view"))

@app.route("/delete-entry/<int:eid>", methods=["POST"])
@login_required
def delete_entry(eid):
    entry = DailyEntry.query.get_or_404(eid)
    if entry.user_id != current_user.id and not current_user.is_admin:
        abort(403)
    db.session.delete(entry)
    db.session.commit()
    flash("Deleted", "success")
    return redirect(url_for("calendar_view"))

# ===== TARGETS =====
@app.route("/targets", methods=["GET", "POST"])
@login_required
def targets():
    tgt = UserTarget.query.filter_by(user_id=current_user.id).first()
    if not tgt:
        tgt = UserTarget(user_id=current_user.id)
        db.session.add(tgt)
    if request.method == "POST" and current_user.is_admin:
        tgt.daily_target = float(request.form.get("daily_target", 0))
        tgt.monthly_target = float(request.form.get("monthly_target", 0))
        db.session.commit()
        flash("Targets updated", "success")
    return render_template("targets.html", tgt=tgt)

# ===== FEED =====
@app.route("/feed")
@login_required
def feed():
    posts = FeedPost.query.order_by(FeedPost.created_at.desc()).all()
    return render_template("feed.html", posts=posts)

@app.route("/post/create", methods=["POST"])
@login_required
def create_post():
    content = request.form.get("content", "").strip()
    if content:
        db.session.add(FeedPost(author_id=current_user.id, content=content))
        db.session.commit()
    return redirect(url_for("feed"))

@app.route("/post/<int:pid>/comment", methods=["POST"])
@login_required
def add_comment(pid):
    FeedPost.query.get_or_404(pid)
    c = Comment(post_id=pid, author_id=current_user.id, content=request.form.get("content", ""))
    db.session.add(c)
    db.session.commit()
    return redirect(url_for("feed"))

@app.route("/post/<int:pid>/delete", methods=["POST"])
@login_required
def delete_post(pid):
    p = FeedPost.query.get_or_404(pid)
    if p.author_id != current_user.id and not current_user.is_admin:
        abort(403)
    db.session.delete(p)
    db.session.commit()
    return redirect(url_for("feed"))

# ===== PROFILE =====
@app.route("/profile/<username>")
@login_required
def profile(username):
    profile_user = User.query.filter_by(username=username).first_or_404()
    today = date.today()
    month_start = date(today.year, today.month, 1)
    
    all_entries = DailyEntry.query.filter_by(user_id=profile_user.id).order_by(DailyEntry.date.desc()).all()
    month_entries = DailyEntry.query.filter(DailyEntry.user_id==profile_user.id, DailyEntry.date>=month_start).all()
    today_entries = [e for e in all_entries if e.date == today]
    
    today_pnl = sum(e.profit_loss for e in today_entries)
    month_total = sum(e.profit_loss for e in month_entries)
    
    unique_days = {}
    for e in all_entries:
        unique_days[e.date] = True
    total_trades = len(unique_days)
    
    winning_days = 0
    for d in unique_days:
        day_sum = sum(e.profit_loss for e in all_entries if e.date == d)
        if day_sum > 0:
            winning_days += 1
    win_rate = (winning_days / total_trades * 100) if total_trades > 0 else 0
    
    win_streak = 0
    for d in sorted(unique_days.keys(), reverse=True):
        day_sum = sum(e.profit_loss for e in all_entries if e.date == d)
        if day_sum > 0:
            win_streak += 1
        else:
            break
    
    avg_daily_profit = month_total / today.day if today.day > 0 else 0
    
    daily_pnl_chart = []
    for i in range(6, -1, -1):
        d = today - timedelta(days=i)
        daily_pnl_chart.append(sum(e.profit_loss for e in all_entries if e.date == d))
    max_pnl = max((abs(v) if v != 0 else 1 for v in daily_pnl_chart), default=1)
    
    monthly_pnl_chart = []
    for i in range(5, -1, -1):
        y, m = today.year, today.month - i
        while m <= 0:
            m += 12
            y -= 1
        m_start = date(y, m, 1)
        if m == 12:
            m_end = date(y + 1, 1, 1) - timedelta(days=1)
        else:
            m_end = date(y, m + 1, 1) - timedelta(days=1)
        monthly_pnl_chart.append(sum(e.profit_loss for e in all_entries if m_start <= e.date <= m_end))
    max_monthly_pnl = max((abs(v) if v != 0 else 1 for v in monthly_pnl_chart), default=1)
    
    posts = FeedPost.query.filter_by(author_id=profile_user.id).order_by(FeedPost.created_at.desc()).all()
    
    return render_template("profile.html",
        profile_user=profile_user,
        today_pnl=today_pnl,
        month_total=month_total,
        total_trades=total_trades,
        win_rate=win_rate,
        win_streak=win_streak,
        avg_daily_profit=avg_daily_profit,
        daily_pnl_chart=daily_pnl_chart,
        max_pnl=max_pnl,
        monthly_pnl_chart=monthly_pnl_chart,
        max_monthly_pnl=max_monthly_pnl,
        posts=posts
    )

@app.route("/edit-profile", methods=["GET", "POST"])
@login_required
def edit_profile():
    if request.method == "POST":
        current_user.bio = request.form.get("bio", "")
        if "profile_pic" in request.files:
            f = request.files["profile_pic"]
            if f.filename:
                ext = f.filename.rsplit(".", 1)[-1].lower()
                fn = f"{current_user.id}_{datetime.utcnow().timestamp()}.{ext}"
                f.save(os.path.join(app.config["UPLOAD_FOLDER"], fn))
                current_user.profile_pic = fn
        db.session.commit()
        flash("Profile updated", "success")
        return redirect(url_for("profile", username=current_user.username))
    return render_template("edit_profile.html", user=current_user)

# ===== CHAT =====
@app.route("/send-chat", methods=["POST"])
@login_required
def send_chat():
    msg = request.form.get("chat_message", "").strip()
    if msg:
        db.session.add(ChatMessage(user_id=current_user.id, content=msg))
        db.session.commit()
    return redirect(url_for("dashboard"))

# ===== SHARE / QR =====
@app.route("/share")
@login_required
def share():
    url = get_public_url() or request.host_url
    signup_url = url.rstrip("/") + url_for("signup")
    img = qrcode.make(signup_url)
    buf = BytesIO()
    img.save(buf, format="PNG")
    qr_b64 = base64.b64encode(buf.getvalue()).decode()
    return render_template("share.html", signup_url=signup_url, qr_code=qr_b64)

# ===== ADMIN =====
@app.route("/admin")
@login_required
def admin_panel():
    if not current_user.is_admin:
        abort(403)
    users = User.query.all()
    reqs = PasswordResetRequest.query.filter_by(is_resolved=False).all()
    return render_template("admin.html", users=users, requests=reqs)

@app.route("/admin/approve/<int:uid>", methods=["POST"])
@login_required
def approve_user(uid):
    if not current_user.is_admin:
        abort(403)
    u = User.query.get_or_404(uid)
    u.is_approved = True
    db.session.commit()
    return redirect(url_for("admin_panel"))

@app.route("/admin/remove/<int:uid>", methods=["POST"])
@login_required
def remove_user(uid):
    if not current_user.is_admin:
        abort(403)
    if uid == current_user.id:
        flash("Cannot remove yourself", "error")
        return redirect(url_for("admin_panel"))
    u = User.query.get_or_404(uid)
    db.session.delete(u)
    db.session.commit()
    return redirect(url_for("admin_panel"))

@app.route("/admin/approve-reset/<int:rid>", methods=["POST"])
@login_required
def approve_reset(rid):
    if not current_user.is_admin:
        abort(403)
    r = PasswordResetRequest.query.get_or_404(rid)
    r.is_resolved = True
    u = User.query.get(r.user_id)
    if u:
        u.password_hash = bcrypt.generate_password_hash("NewPass123!").decode("utf-8")
    db.session.commit()
    flash("Password reset to: NewPass123!", "success")
    return redirect(url_for("admin_panel"))

@app.route("/admin/reject-reset/<int:rid>", methods=["POST"])
@login_required
def reject_reset(rid):
    if not current_user.is_admin:
        abort(403)
    db.session.delete(PasswordResetRequest.query.get_or_404(rid))
    db.session.commit()
    return redirect(url_for("admin_panel"))

@app.route("/admin/set-targets/<int:uid>", methods=["POST"])
@login_required
def set_user_targets(uid):
    if not current_user.is_admin:
        abort(403)
    tgt = UserTarget.query.filter_by(user_id=uid).first() or UserTarget(user_id=uid)
    tgt.daily_target = float(request.form.get("daily_target", 0))
    tgt.monthly_target = float(request.form.get("monthly_target", 0))
    db.session.add(tgt)
    db.session.commit()
    return redirect(url_for("admin_panel"))

if __name__ == "__main__":
    app.run(debug=False)
