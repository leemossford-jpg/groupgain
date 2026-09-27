from flask import Flask, render_template, request, redirect, url_for, flash, abort
from flask_bcrypt import Bcrypt
from flask_login import LoginManager, login_user, login_required, logout_user, current_user
from datetime import datetime, date
import calendar
import os
from io import BytesIO
import base64
import qrcode

app = Flask(__name__)

# === DATABASE CONFIG — Works on Render + Local ✅ ===
basedir = os.path.abspath(os.path.dirname(__file__))

if 'DATABASE_URL' in os.environ:
    db_url = os.environ['DATABASE_URL']
    if db_url.startswith('postgres://'):
        db_url = db_url.replace('postgres://', 'postgresql://', 1)
    app.config['SQLALCHEMY_DATABASE_URI'] = db_url
else:
    app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{os.path.join(basedir, "groupgain.db")}'

app.config['SECRET_KEY'] = 'groupgain_secret_key_2026_secure!'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = os.path.join('static', 'profile_pics')
app.config['MAX_CONTENT_LENGTH'] = 2 * 1024 * 1024
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}

bcrypt = Bcrypt(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'
login_manager.login_message = 'Please log in to access GroupGain.'

from database import db, User, DailyEntry, UserTarget, FeedPost, Comment, PasswordResetRequest, ChatMessage
db.init_app(app)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# === HELPER: Correct URL on Render ===
def get_base_url():
    if 'RENDER' in os.environ:
        host = request.headers.get('X-Forwarded-Host', '')
        if host:
            return f"https://{host}"
    return request.host_url.rstrip('/')

# === HELPER: Safe targets get ===
def get_targets_safe(user):
    if not hasattr(user, 'targets') or not user.targets:
        try:
            t = UserTarget(user_id=user.id, daily_target=0.0, monthly_target=0.0)
            db.session.add(t)
            db.session.commit()
            return t
        except Exception:
            db.session.rollback()
            class FallbackTargets:
                daily_target = 0.0
                monthly_target = 0.0
            return FallbackTargets()
    return user.targets

with app.app_context():
    db.create_all()
    if not User.query.filter_by(username='admin').first():
        admin_pass = bcrypt.generate_password_hash('Admin123!').decode('utf-8')
        admin = User(username='admin', password_hash=admin_pass, is_approved=True, is_admin=True, bio="GroupGain Founder 👑")
        db.session.add(admin)
        db.session.commit()
        get_targets_safe(admin)
        print("✅ Admin created: admin / Admin123! — CHANGE THIS AFTER FIRST LOGIN!")

# === AUTH ===
@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        if User.query.filter_by(username=username).first():
            flash('Username already taken!', 'error')
            return redirect(url_for('signup'))
        hashed_pw = bcrypt.generate_password_hash(password).decode('utf-8')
        new_user = User(username=username, password_hash=hashed_pw, is_approved=False, bio="New to GroupGain! 🎉")
        db.session.add(new_user)
        db.session.commit()
        get_targets_safe(new_user)
        flash('Account created! Waiting for admin approval.', 'success')
        return redirect(url_for('login'))
    return render_template('signup.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        user = User.query.filter_by(username=username).first()
        if not user:
            flash('Username not found', 'error')
            return redirect(url_for('login'))
        if not bcrypt.check_password_hash(user.password_hash, password):
            flash('Incorrect password', 'error')
            return redirect(url_for('login'))
        if not user.is_approved:
            flash('⏳ Your account is pending admin approval', 'error')
            return redirect(url_for('login'))
        login_user(user, remember=True)
        return redirect(url_for('dashboard'))
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('Logged out', 'success')
    return redirect(url_for('login'))

# === FORGOT PASSWORD ===
@app.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        user = User.query.filter_by(username=username).first()
        if user:
            existing = PasswordResetRequest.query.filter_by(user_id=user.id, is_resolved=False).first()
            if not existing:
                db.session.add(PasswordResetRequest(user_id=user.id))
                db.session.commit()
            flash('Request sent to admin', 'success')
        else:
            flash('Username not found', 'error')
        return redirect(url_for('forgot_password'))
    return render_template('forgot_password.html')

@app.route('/admin/reset-requests')
@login_required
def list_reset_requests():
    if not current_user.is_admin:
        flash('Admin only!', 'error')
        return redirect(url_for('dashboard'))
    reqs = PasswordResetRequest.query.filter_by(is_resolved=False).order_by(PasswordResetRequest.created_at.desc()).all()
    return render_template('reset_requests.html', requests=reqs)

@app.route('/admin/approve-reset/<int:req_id>', methods=['POST'])
@login_required
def approve_reset(req_id):
    if not current_user.is_admin: abort(403)
    req = PasswordResetRequest.query.get_or_404(req_id)
    req.is_resolved = True
    db.session.commit()
    flash(f'✅ Approved for {req.user.username}', 'success')
    return redirect(url_for('list_reset_requests'))

@app.route('/admin/reject-reset/<int:req_id>', methods=['POST'])
@login_required
def reject_reset(req_id):
    if not current_user.is_admin: abort(403)
    req = PasswordResetRequest.query.get_or_404(req_id)
    db.session.delete(req)
    db.session.commit()
    flash('Rejected', 'success')
    return redirect(url_for('list_reset_requests'))

# === CHANGE PASSWORD ===
@app.route('/change-password', methods=['GET', 'POST'])
@login_required
def change_password():
    if request.method == 'POST':
        old_pw = request.form.get('old_password', '')
        new_pw = request.form.get('new_password', '')
        confirm_pw = request.form.get('confirm_password', '')
        if not bcrypt.check_password_hash(current_user.password_hash, old_pw):
            flash('Current password incorrect', 'error')
            return redirect(url_for('change_password'))
        if new_pw != confirm_pw:
            flash('Passwords do not match', 'error')
            return redirect(url_for('change_password'))
        if len(new_pw) < 6:
            flash('Min 6 characters', 'error')
            return redirect(url_for('change_password'))
        current_user.password_hash = bcrypt.generate_password_hash(new_pw).decode('utf-8')
        db.session.commit()
        flash('✅ Password updated', 'success')
        return redirect(url_for('dashboard'))
    return render_template('change_password.html')

# === SHARE / QR ===
@app.route('/share')
@login_required
def share_page():
    base_url = get_base_url()
    signup_url = f"{base_url}/signup"
    qr_data = None
    try:
        qr_img = qrcode.make(signup_url)
        buf = BytesIO()
        qr_img.save(buf, format='PNG')
        qr_data = base64.b64encode(buf.getvalue()).decode()
    except Exception as e:
        flash(f'QR note: {e}', 'info')
    return render_template('share.html', signup_url=signup_url, qr_data=qr_data)

# === FEED ===
@app.route('/feed')
@login_required
def feed():
    posts = FeedPost.query.order_by(FeedPost.created_at.desc()).all()
    return render_template('feed.html', posts=posts)

@app.route('/post/status', methods=['POST'])
@login_required
def post_status():
    content = request.form.get('content', '').strip()
    if content:
        db.session.add(FeedPost(user_id=current_user.id, content=content, post_type='status'))
        db.session.commit()
        flash('Posted ✅', 'success')
    return redirect(url_for('feed'))

@app.route('/post/<int:post_id>/comment', methods=['POST'])
@login_required
def add_comment(post_id):
    post = FeedPost.query.get_or_404(post_id)
    content = request.form.get('content', '').strip()
    if content:
        db.session.add(Comment(post_id=post_id, user_id=current_user.id, content=content))
        db.session.commit()
    return redirect(url_for('feed'))

@app.route('/post/<int:post_id>/delete', methods=['POST'])
@login_required
def delete_post(post_id):
    post = FeedPost.query.get_or_404(post_id)
    if post.author_id != current_user.id and not current_user.is_admin:
        abort(403)
    db.session.delete(post)
    db.session.commit()
    flash('Deleted', 'success')
    return redirect(url_for('feed'))

# === CHAT ===
@app.route('/chat/send', methods=['POST'])
@login_required
def send_chat():
    msg = request.form.get('chat_message', '').strip()
    if msg:
        db.session.add(ChatMessage(user_id=current_user.id, content=msg))
        db.session.commit()
    return redirect(url_for('dashboard'))

# === PROFILE ===
@app.route('/profile/<username>')
@login_required
def view_profile(username):
    user = User.query.filter_by(username=username).first_or_404()
    if not user.is_approved and not current_user.is_admin:
        flash('Not approved yet', 'error')
        return redirect(url_for('dashboard'))

    today = date.today()
    try:
        year = request.args.get('year', today.year, type=int)
        month = request.args.get('month', today.month, type=int)
        year = max(2020, min(2100, year))
        month = max(1, min(12, month))
    except (ValueError, TypeError):
        year, month = today.year, today.month

    prev_m, prev_y = (month-1, year) if month > 1 else (12, year-1)
    next_m, next_y = (month+1, year) if month < 12 else (1, year+1)
    month_start = date(year, month, 1)
    month_end = date(year, month, calendar.monthrange(year, month)[1])
    first_day_current = date(today.year, today.month, 1)

    month_entries_current = DailyEntry.query.filter(
        DailyEntry.user_id == user.id,
        DailyEntry.entry_date >= first_day_current
    ).all()
    month_total = round(sum((e.profit_loss or 0) for e in month_entries_current), 2)

    cal_entries = DailyEntry.query.filter(
        DailyEntry.user_id == user.id,
        DailyEntry.entry_date >= month_start,
        DailyEntry.entry_date <= month_end
    ).all()
    daily_totals = {}
    for e in cal_entries:
        ed = e.entry_date
        if ed not in daily_totals:
            daily_totals[ed] = 0
        daily_totals[ed] += e.profit_loss or 0

    winning_days = [v for v in daily_totals.values() if v > 0]
    losing_days = [v for v in daily_totals.values() if v < 0]
    avg_win = round(sum(winning_days) / len(winning_days), 2) if winning_days else 0.00
    avg_loss = round(sum(losing_days) / len(losing_days), 2) if losing_days else 0.00
    total_days = len(winning_days) + len(losing_days)
    win_rate = round((len(winning_days) / total_days * 100), 1) if total_days > 0 else 0.0

    cal = calendar.monthcalendar(year, month)
    streak = max_streak = 0
    for week in cal:
        for day in week:
            if day == 0: continue
            t = daily_totals.get(date(year, month, day), 0)
            if t > 0:
                streak += 1
                max_streak = max(max_streak, streak)
            else:
                streak = 0

    posts = FeedPost.query.filter_by(user_id=user.id).order_by(FeedPost.created_at.desc()).all()

    return render_template('profile_view.html',
        profile_user=user,
        year=year, month=month,
        month_name=calendar.month_name[month],
        calendar_weeks=cal,
        daily_totals=daily_totals,
        prev_year=prev_y, prev_month=prev_m,
        next_year=next_y, next_month=next_m,
        month_total=month_total,
        avg_win=avg_win, avg_loss=avg_loss,
        win_rate=win_rate, streak=max_streak,
        total_entries=DailyEntry.query.filter_by(user_id=user.id).count(),
        posts=posts
    )

@app.route('/my-profile', methods=['GET', 'POST'])
@login_required
def my_profile():
    if request.method == 'POST':
        current_user.bio = request.form.get('bio', '').strip()
        if 'avatar' in request.files:
            f = request.files['avatar']
            if f and allowed_file(f.filename):
                ext = f.filename.rsplit('.', 1)[1].lower()
                fn = f"user_{current_user.id}_{int(datetime.utcnow().timestamp())}.{ext}"
                f.save(os.path.join(app.config['UPLOAD_FOLDER'], fn))
                current_user.profile_pic = fn
        db.session.commit()
        flash('Profile updated ✅', 'success')
        return redirect(url_for('view_profile', username=current_user.username))
    return render_template('my_profile.html')

# === TARGETS ===
@app.route('/targets', methods=['GET', 'POST'])
@login_required
def my_targets():
    t = get_targets_safe(current_user)
    if request.method == 'POST' and current_user.is_admin:
        try:
            dt = float(request.form.get('daily_target', 0))
            mt = float(request.form.get('monthly_target', 0))
            for u in User.query.filter_by(is_approved=True).all():
                ut = get_targets_safe(u)
                ut.daily_target = dt
                ut.monthly_target = mt
            db.session.commit()
            flash(f'✅ Updated: Daily £{dt:.2f} | Monthly £{mt:.2f}', 'success')
        except Exception as e:
            db.session.rollback()
            flash(f'Error: {e}', 'error')
    return render_template('targets.html',
        daily_target=getattr(t, 'daily_target', 0.0),
        monthly_target=getattr(t, 'monthly_target', 0.0)
    )

# === CALENDAR ===
@app.route('/calendar')
@app.route('/calendar/<int:year>/<int:month>')
@login_required
def calendar_view(year=None, month=None):
    today = date.today()
    try:
        if year is None: year = today.year
        if month is None: month = today.month
        year = max(2020, min(2100, int(year)))
        month = max(1, min(12, int(month)))
    except (ValueError, TypeError):
        year, month = today.year, today.month

    show_weekends = request.args.get('show_weekends', 'on') == 'on'
    prev_m, prev_y = (month-1, year) if month > 1 else (12, year-1)
    next_m, next_y = (month+1, year) if month < 12 else (1, year+1)
    month_start = date(year, month, 1)
    month_end = date(year, month, calendar.monthrange(year, month)[1])

    entries = DailyEntry.query.filter(
        DailyEntry.user_id == current_user.id,
        DailyEntry.entry_date >= month_start,
        DailyEntry.entry_date <= month_end
    ).all()

    daily_totals = {}
    entry_map = {}
    for e in entries:
        ed = e.entry_date
        if ed not in daily_totals:
            daily_totals[ed] = 0
            entry_map[ed] = []
        daily_totals[ed] += e.profit_loss or 0
        entry_map[ed].append(e)

    t = get_targets_safe(current_user)

    return render_template('calendar.html',
        today=today, year=year, month=month,
        month_name=calendar.month_name[month],
        calendar_weeks=calendar.monthcalendar(year, month),
        daily_totals=daily_totals,
        entry_map=entry_map,
        prev_year=prev_y, prev_month=prev_m,
        next_year=next_y, next_month=next_m,
        daily_target=getattr(t, 'daily_target', 0.0),
        show_weekends=show_weekends
    )

# === ENTRY ADD/EDIT/DELETE ===
@app.route('/entry/add', methods=['POST'])
@login_required
def add_entry():
    try:
        ed = datetime.strptime(request.form.get('entry_date'), '%Y-%m-%d').date()
        pl = float(request.form.get('profit_loss', 0))
        notes = request.form.get('notes', '').strip()
        db.session.add(DailyEntry(user_id=current_user.id, entry_date=ed, profit_loss=pl, notes=notes))
        sign = '+' if pl >= 0 else ''
        content = f"📊 Posted: {sign}£{pl:.2f} on {ed}"
        if notes: content += f"\n💬 {notes}"
        db.session.add(FeedPost(user_id=current_user.id, content=content, post_type='result'))
        db.session.commit()
        flash(f'Added: {sign}£{pl:.2f} ✅', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error: {e}', 'error')
    return redirect(url_for('calendar_view'))

@app.route('/entry/<int:entry_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_entry(entry_id):
    entry = DailyEntry.query.get_or_404(entry_id)
    if entry.user_id != current_user.id and not current_user.is_admin:
        abort(403)
    if request.method == 'POST':
        try:
            entry.profit_loss = float(request.form.get('profit_loss', 0))
            entry.notes = request.form.get('notes', '').strip()
            db.session.commit()
            flash('Updated ✅', 'success')
        except Exception as e:
            db.session.rollback()
            flash(f'Error: {e}', 'error')
        return redirect(url_for('calendar_view', year=entry.entry_date.year, month=entry.entry_date.month))
    return render_template('edit_entry.html', entry=entry)

@app.route('/entry/<int:entry_id>/delete', methods=['POST'])
@login_required
def delete_entry(entry_id):
    entry = DailyEntry.query.get_or_404(entry_id)
    if entry.user_id != current_user.id and not current_user.is_admin:
        abort(403)
    try:
        y, m = entry.entry_date.year, entry.entry_date.month
        db.session.delete(entry)
        db.session.commit()
        flash('Deleted', 'success')
    except Exception:
        y, m = date.today().year, date.today().month
    return redirect(url_for('calendar_view', year=y, month=m))

# === ADMIN SETTINGS — FIXED ✅ ===
@app.route('/admin/settings')
@login_required
def admin_settings():
    if not current_user.is_admin:
        flash('Admin only!', 'error')
        return redirect(url_for('dashboard'))
    try:
        return render_template('admin_settings.html',
            total_users=User.query.count(),
            approved_users=User.query.filter_by(is_approved=True).count(),
            pending_users=User.query.filter_by(is_approved=False).count(),
            total_entries=DailyEntry.query.count(),
            admin_count=User.query.filter_by(is_admin=True).count()
        )
    except Exception as e:
        flash(f'Error loading admin panel: {e}', 'error')
        return redirect(url_for('dashboard'))

@app.route('/admin/approve/<int:user_id>', methods=['POST'])
@login_required
def approve_user(user_id):
    if not current_user.is_admin: abort(403)
    user = User.query.get_or_404(user_id)
    user.is_approved = True
    get_targets_safe(user)
    db.session.commit()
    flash(f'✅ {user.username} approved', 'success')
    return redirect(url_for('admin_settings'))

@app.route('/admin/reject/<int:user_id>', methods=['POST'])
@login_required
def reject_user(user_id):
    if not current_user.is_admin: abort(403)
    user = User.query.get_or_404(user_id)
    db.session.delete(user)
    db.session.commit()
    flash(f'{user.username} rejected ❌', 'success')
    return redirect(url_for('admin_settings'))

@app.route('/admin/remove/<int:user_id>', methods=['POST'])
@login_required
def remove_user(user_id):
    if not current_user.is_admin: abort(403)
    user = User.query.get_or_404(user_id)
    if user.id == current_user.id:
        flash('Cannot remove yourself!', 'error')
        return redirect(url_for('admin_settings'))
    db.session.delete(user)
    db.session.commit()
    flash(f'{user.username} removed', 'success')
    return redirect(url_for('admin_settings'))

@app.route('/admin/toggle-admin/<int:user_id>', methods=['POST'])
@login_required
def toggle_admin(user_id):
    if not current_user.is_admin: abort(403)
    user = User.query.get_or_404(user_id)
    if user.id == current_user.id:
        flash('Cannot change your own status', 'error')
        return redirect(url_for('admin_settings'))
    user.is_admin = not user.is_admin
    db.session.commit()
    flash(f"{user.username} is {'admin' if user.is_admin else 'user'}", 'success')
    return redirect(url_for('admin_settings'))

# === DASHBOARD ===
@app.route('/')
@login_required
def dashboard():
    today = date.today()
    month_start = date(today.year, today.month, 1)
    t = get_targets_safe(current_user)

    today_total = round(sum((e.profit_loss or 0) for e in DailyEntry.query.filter_by(
        user_id=current_user.id, entry_date=today).all()), 2)
    month_total = round(sum((e.profit_loss or 0) for e in DailyEntry.query.filter(
        user_id=current_user.id).filter(DailyEntry.entry_date >= month_start).all()), 2)

    return render_template('dashboard.html',
        today=today,
        today_total=today_total,
        month_total=month_total,
        daily_target=getattr(t, 'daily_target', 0.0),
        monthly_target=getattr(t, 'monthly_target', 0.0),
        all_users=User.query.filter_by(is_approved=True).all(),
        messages=ChatMessage.query.order_by(ChatMessage.created_at.asc()).limit(50).all()
    )

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)
