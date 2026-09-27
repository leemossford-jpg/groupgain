from flask import Flask, render_template, request, redirect, url_for, flash, abort, session
from flask_bcrypt import Bcrypt
from flask_login import LoginManager, login_user, login_required, logout_user, current_user
from datetime import datetime, date
import calendar
import os
from io import BytesIO
import base64
import qrcode

app = Flask(__name__)

# === DATABASE CONFIG — Works on Render + Local ===
basedir = os.path.abspath(os.path.dirname(__file__))
if 'RENDER' in os.environ or 'DATABASE_URL' in os.environ:
    db_url = os.environ.get('DATABASE_URL', '').replace('postgres://', 'postgresql://')
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

with app.app_context():
    db.create_all()
    if not User.query.filter_by(username='admin').first():
        admin_pass = bcrypt.generate_password_hash('Admin123!').decode('utf-8')
        admin = User(username='admin', password_hash=admin_pass, is_approved=True, is_admin=True, bio="GroupGain Founder 👑")
        db.session.add(admin)
        db.session.commit()
        db.session.add(UserTarget(user_id=admin.id, daily_target=500.0, monthly_target=10000.0))
        db.session.commit()
        print("✅ Admin created: admin / Admin123! — CHANGE THIS AFTER FIRST LOGIN!")

# === AUTH ROUTES ===
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
        db.session.add(UserTarget(user_id=new_user.id, daily_target=0.0, monthly_target=0.0))
        db.session.commit()
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
    flash('You have been logged out', 'success')
    return redirect(url_for('login'))

# === FORGOT PASSWORD SYSTEM ===
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
            flash('Request sent to admin — you will be notified when approved', 'success')
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
    requests = PasswordResetRequest.query.filter_by(is_resolved=False).order_by(PasswordResetRequest.created_at.desc()).all()
    return render_template('reset_requests.html', requests=requests)

@app.route('/admin/approve-reset/<int:req_id>', methods=['POST'])
@login_required
def approve_reset(req_id):
    if not current_user.is_admin: abort(403)
    req = PasswordResetRequest.query.get_or_404(req_id)
    req.is_resolved = True
    db.session.commit()
    flash(f'✅ Password reset approved for {req.user.username}', 'success')
    return redirect(url_for('list_reset_requests'))

@app.route('/admin/reject-reset/<int:req_id>', methods=['POST'])
@login_required
def reject_reset(req_id):
    if not current_user.is_admin: abort(403)
    req = PasswordResetRequest.query.get_or_404(req_id)
    db.session.delete(req)
    db.session.commit()
    flash('Reset request rejected', 'success')
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
            flash('Current password is incorrect', 'error')
            return redirect(url_for('change_password'))
        if new_pw != confirm_pw:
            flash('New passwords do not match', 'error')
            return redirect(url_for('change_password'))
        if len(new_pw) < 6:
            flash('Password must be at least 6 characters', 'error')
            return redirect(url_for('change_password'))
        current_user.password_hash = bcrypt.generate_password_hash(new_pw).decode('utf-8')
        db.session.commit()
        flash('✅ Password updated successfully!', 'success')
        return redirect(url_for('dashboard'))
    return render_template('change_password.html')

# === SHARE / QR CODE ===
@app.route('/share')
@login_required
def share_page():
    base_url = request.host_url.rstrip('/')
    signup_url = f"{base_url}/signup"
    qr_data = None
    try:
        qr_img = qrcode.make(signup_url)
        buf = BytesIO()
        qr_img.save(buf, format='PNG')
        qr_data = base64.b64encode(buf.getvalue()).decode()
    except Exception as e:
        flash(f'Could not generate QR: {e}', 'error')
    return render_template('share.html', signup_url=signup_url, qr_data=qr_data)

# === FEED & COMMENTS ===
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
        flash('Posted! ✅', 'success')
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
    flash('Post deleted', 'success')
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

# === PROFILES ===
@app.route('/profile/<username>')
@login_required
def view_profile(username):
    user = User.query.filter_by(username=username).first_or_404()
    if not user.is_approved and not current_user.is_admin:
        flash('This profile is not yet approved', 'error')
        return redirect(url_for('dashboard'))

    today = date.today()
    year = request.args.get('year', today.year, type=int)
    month = request.args.get('month', today.month, type=int)

    prev_m, prev_y = (month-1, year) if month > 1 else (12, year-1)
    next_m, next_y = (month+1, year) if month < 12 else (1, year+1)

    month_start = date(year, month, 1)
    month_end = date(year, month, calendar.monthrange(year, month)[1])
    first_day_current = date(today.year, today.month, 1)

    all_entries = DailyEntry.query.filter_by(user_id=user.id).all()
    month_entries_current = DailyEntry.query.filter(
        DailyEntry.user_id == user.id,
        DailyEntry.entry_date >= first_day_current
    ).all()
    month_total = round(sum(e.profit_loss for e in month_entries_current), 2)
    total_entries = len(all_entries)

    cal_entries = DailyEntry.query.filter(
        DailyEntry.user_id == user.id,
        DailyEntry.entry_date >= month_start,
        DailyEntry.entry_date <= month_end
    ).all()
    daily_totals = {}
    for e in cal_entries:
        if e.entry_date not in daily_totals:
            daily_totals[e.entry_date] = 0
        daily_totals[e.entry_date] += e.profit_loss

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
            d = date(year, month, day)
            t = daily_totals.get(d, 0)
            if t > 0:
                streak += 1
                max_streak = max(max_streak, streak)
            else:
                streak = 0

    if not user.targets:
        db.session.add(UserTarget(user_id=user.id))
        db.session.commit()

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
        total_entries=total_entries,
        posts=posts
    )

@app.route('/my-profile', methods=['GET', 'POST'])
@login_required
def my_profile():
    if request.method == 'POST':
        bio = request.form.get('bio', '').strip()
        current_user.bio = bio
        if 'avatar' in request.files:
            file = request.files['avatar']
            if file and allowed_file(file.filename):
                ext = file.filename.rsplit('.', 1)[1].lower()
                fn = f"user_{current_user.id}_{int(datetime.utcnow().timestamp())}.{ext}"
                file.save(os.path.join(app.config['UPLOAD_FOLDER'], fn))
                current_user.profile_pic = fn
        db.session.commit()
        flash('Profile updated ✅', 'success')
        return redirect(url_for('view_profile', username=current_user.username))
    return render_template('my_profile.html')

# === TARGETS ===
@app.route('/targets', methods=['GET', 'POST'])
@login_required
def my_targets():
    if not current_user.targets:
        db.session.add(UserTarget(user_id=current_user.id))
        db.session.commit()
    if request.method == 'POST':
        if current_user.is_admin:
            dt = float(request.form.get('daily_target', 0))
            mt = float(request.form.get('monthly_target', 0))
            for user in User.query.filter_by(is_approved=True).all():
                if not user.targets:
                    db.session.add(UserTarget(user_id=user.id, daily_target=dt, monthly_target=mt))
                else:
                    user.targets.daily_target = dt
                    user.targets.monthly_target = mt
            db.session.commit()
            flash('✅ Group targets updated!', 'success')
        else:
            flash('Only admin can change targets', 'error')
    return render_template('targets.html', targets=current_user.targets)

# === CALENDAR WITH HIDE WEEKENDS TOGGLE ===
@app.route('/calendar')
@app.route('/calendar/<int:year>/<int:month>')
@login_required
def calendar_view(year=None, month=None):
    today = date.today()
    if year is None: year = today.year
    if month is None: month = today.month

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
        if e.entry_date not in daily_totals:
            daily_totals[e.entry_date] = 0
            entry_map[e.entry_date] = []
        daily_totals[e.entry_date] += e.profit_loss
        entry_map[e.entry_date].append(e)

    if not current_user.targets:
        db.session.add(UserTarget(user_id=current_user.id))
        db.session.commit()

    return render_template('calendar.html',
        today=today, year=year, month=month,
        month_name=calendar.month_name[month],
        calendar_weeks=calendar.monthcalendar(year, month),
        daily_totals=daily_totals,
        entry_map=entry_map,
        prev_year=prev_y, prev_month=prev_m,
        next_year=next_y, next_month=next_m,
        daily_target=current_user.targets.daily_target,
        show_weekends=show_weekends
    )

# === ADD / EDIT ENTRY ===
@app.route('/entry/add', methods=['POST'])
@login_required
def add_entry():
    ed_str = request.form.get('entry_date')
    ed = datetime.strptime(ed_str, '%Y-%m-%d').date()
    pl = float(request.form.get('profit_loss'))
    notes = request.form.get('notes', '').strip()
    entry = DailyEntry(user_id=current_user.id, entry_date=ed, profit_loss=pl, notes=notes)
    db.session.add(entry)
    db.session.flush()
    sign = '+' if pl >= 0 else ''
    post_content = f"📊 Posted result: {sign}£{pl:.2f} on {ed}"
    if notes: post_content += f"\n💬 {notes}"
    db.session.add(FeedPost(user_id=current_user.id, content=post_content, post_type='result'))
    db.session.commit()
    flash(f'Added: {sign}£{pl:.2f} ✅', 'success')
    return redirect(url_for('calendar_view'))

@app.route('/entry/<int:entry_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_entry(entry_id):
    entry = DailyEntry.query.get_or_404(entry_id)
    if entry.user_id != current_user.id and not current_user.is_admin:
        abort(403)
    if request.method == 'POST':
        entry.profit_loss = float(request.form.get('profit_loss'))
        entry.notes = request.form.get('notes', '').strip()
        db.session.commit()
        flash('Entry updated ✅', 'success')
        return redirect(url_for('calendar_view', year=entry.entry_date.year, month=entry.entry_date.month))
    return render_template('edit_entry.html', entry=entry)

@app.route('/entry/<int:entry_id>/delete', methods=['POST'])
@login_required
def delete_entry(entry_id):
    entry = DailyEntry.query.get_or_404(entry_id)
    if entry.user_id != current_user.id and not current_user.is_admin:
        abort(403)
    y, m = entry.entry_date.year, entry.entry_date.month
    db.session.delete(entry)
    db.session.commit()
    flash('Entry deleted', 'success')
    return redirect(url_for('calendar_view', year=y, month=m))

# === ADMIN CONTROL PANEL ===
@app.route('/admin/settings')
@login_required
def admin_settings():
    if not current_user.is_admin:
        flash('Admin only!', 'error')
        return redirect(url_for('dashboard'))
    total_users = User.query.count()
    approved_users = User.query.filter_by(is_approved=True).count()
    pending_users = User.query.filter_by(is_approved=False).count()
    total_entries = DailyEntry.query.count()
    admin_count = User.query.filter_by(is_admin=True).count()
    return render_template('admin_settings.html',
        total_users=total_users,
        approved_users=approved_users,
        pending_users=pending_users,
        total_entries=total_entries,
        admin_count=admin_count
    )

@app.route('/admin/approve/<int:user_id>', methods=['POST'])
@login_required
def approve_user(user_id):
    if not current_user.is_admin: abort(403)
    user = User.query.get_or_404(user_id)
    user.is_approved = True
    if not user.targets:
        db.session.add(UserTarget(user_id=user.id, daily_target=500.0, monthly_target=10000.0))
    db.session.commit()
    flash(f'✅ {user.username} approved!', 'success')
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
    flash(f'{user.username} removed from app', 'success')
    return redirect(url_for('admin_settings'))

@app.route('/admin/toggle-admin/<int:user_id>', methods=['POST'])
@login_required
def toggle_admin(user_id):
    if not current_user.is_admin: abort(403)
    user = User.query.get_or_404(user_id)
    if user.id == current_user.id:
        flash('Cannot change your own admin status', 'error')
        return redirect(url_for('admin_settings'))
    user.is_admin = not user.is_admin
    db.session.commit()
    status = 'now an admin 👑' if user.is_admin else 'no longer an admin'
    flash(f'{user.username} is {status}', 'success')
    return redirect(url_for('admin_settings'))

# === DASHBOARD ===
@app.route('/')
@login_required
def dashboard():
    today = date.today()
    month_start = date(today.year, today.month, 1)

    if not current_user.targets:
        db.session.add(UserTarget(user_id=current_user.id))
        db.session.commit()

    today_entries = DailyEntry.query.filter(
        DailyEntry.user_id == current_user.id,
        DailyEntry.entry_date == today
    ).all()
    today_total = round(sum(e.profit_loss for e in today_entries), 2)

    month_entries = DailyEntry.query.filter(
        DailyEntry.user_id == current_user.id,
        DailyEntry.entry_date >= month_start
    ).all()
    month_total = round(sum(e.profit_loss for e in month_entries), 2)

    all_approved = User.query.filter_by(is_approved=True).all()
    messages = ChatMessage.query.order_by(ChatMessage.created_at.asc()).limit(50).all()

    return render_template('dashboard.html',
        today=today,
        today_total=today_total,
        month_total=month_total,
        daily_target=current_user.targets.daily_target,
        monthly_target=current_user.targets.monthly_target,
        all_users=all_approved,
        messages=messages
    )

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)
