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

# ==============================================
# ONE-TIME FULL DATABASE RESET — REMOVE AFTER FIRST DEPLOY
# ==============================================
with app.app_context():
    # Drop ALL tables and recreate fresh
    db.drop_all()
    db.create_all()
    print("✅ Database fully reset & rebuilt!")
    
    # Create fresh admin account
    if not User.query.filter_by(username='admin').first():
        admin_pass = bcrypt.generate_password_hash('Admin123!').decode('utf-8')
        admin = User(username='admin', password_hash=admin_pass, is_approved=True, is_admin=True, bio="GroupGain Founder 👑")
        db.session.add(admin)
        db.session.commit()
        # Create targets for admin
        db.session.add(UserTarget(user_id=admin.id, daily_target=0.0, monthly_target=0.0))
        db.session.commit()
        print("✅ Admin created: admin / Admin123! — CHANGE THIS PASSWORD!")

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def get_base_url():
    if 'RENDER' in os.environ:
        host = request.headers.get('X-Forwarded-Host', '')
        if host:
            return f"https://{host}"
    return request.host_url.rstrip('/')

def get_targets_safe(user):
    try:
        t = UserTarget.query.filter_by(user_id=user.id).first()
        if not t:
            t = UserTarget(user_id=user.id, daily_target=0.0, monthly_target=0.0)
            db.session.add(t)
            db.session.commit()
        return t
    except Exception:
        db.session.rollback()
        class Fallback:
            daily_target = 0.0
            monthly_target = 0.0
        return Fallback()

# === AUTH ROUTES ===
@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    if request.method == 'POST':
        un = request.form.get('username', '').strip()
        pw = request.form.get('password', '')
        if User.query.filter_by(username=un).first():
            flash('Username taken', 'error')
            return redirect(url_for('signup'))
        new_user = User(username=un, password_hash=bcrypt.generate_password_hash(pw).decode('utf-8'), is_approved=False)
        db.session.add(new_user)
        db.session.commit()
        get_targets_safe(new_user)
        flash('Account created — waiting for admin approval', 'success')
        return redirect(url_for('login'))
    return render_template('signup.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    if request.method == 'POST':
        un = request.form.get('username', '').strip()
        pw = request.form.get('password', '')
        user = User.query.filter_by(username=un).first()
        if not user:
            flash('Username not found', 'error')
            return redirect(url_for('login'))
        if not bcrypt.check_password_hash(user.password_hash, pw):
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

# === SHARE / QR CODE ===
@app.route('/share')
@login_required
def share_page():
    signup_url = f"{get_base_url()}/signup"
    qr_data = None
    try:
        buf = BytesIO()
        qrcode.make(signup_url).save(buf, format='PNG')
        qr_data = base64.b64encode(buf.getvalue()).decode()
    except Exception as e:
        flash(f'QR note: {e}', 'info')
    return render_template('share.html', signup_url=signup_url, qr_data=qr_data)

# === DASHBOARD — FIXED ===
@app.route('/')
@login_required
def dashboard():
    today = date.today()
    month_start = date(today.year, today.month, 1)
    t = get_targets_safe(current_user)
    
    try:
        today_entries = DailyEntry.query.filter_by(user_id=current_user.id, entry_date=today).all()
        today_total = round(sum((e.profit_loss or 0) for e in today_entries), 2)
    except Exception:
        today_total = 0.0
        
    try:
        month_entries = DailyEntry.query.filter(
            DailyEntry.user_id == current_user.id,
            DailyEntry.entry_date >= month_start
        ).all()
        month_total = round(sum((e.profit_loss or 0) for e in month_entries), 2)
    except Exception:
        month_total = 0.0

    try:
        all_users = User.query.filter_by(is_approved=True).all()
    except Exception:
        all_users = []
        
    try:
        messages = ChatMessage.query.order_by(ChatMessage.created_at.asc()).limit(50).all()
    except Exception:
        messages = []

    return render_template('dashboard.html',
        today=today,
        today_total=today_total,
        month_total=month_total,
        daily_target=getattr(t, 'daily_target', 0.0),
        monthly_target=getattr(t, 'monthly_target', 0.0),
        all_users=all_users,
        messages=messages
    )

# === CALENDAR ===
@app.route('/calendar')
@app.route('/calendar/<int:year>/<int:month>')
@login_required
def calendar_view(year=None, month=None):
    today = date.today()
    try:
        y = year or today.year
        m = month or today.month
        y = max(2020, min(2100, int(y)))
        m = max(1, min(12, int(m)))
    except (ValueError, TypeError):
        y, m = today.year, today.month

    prev_m, prev_y = (m-1, y) if m > 1 else (12, y-1)
    next_m, next_y = (m+1, y) if m < 12 else (1, y+1)
    month_start = date(y, m, 1)
    month_end = date(y, m, calendar.monthrange(y, m)[1])

    try:
        entries = DailyEntry.query.filter(
            DailyEntry.user_id == current_user.id,
            DailyEntry.entry_date >= month_start,
            DailyEntry.entry_date <= month_end
        ).all()
    except Exception:
        entries = []

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
        today=today, year=y, month=m,
        month_name=calendar.month_name[m],
        calendar_weeks=calendar.monthcalendar(y, m),
        daily_totals=daily_totals,
        entry_map=entry_map,
        prev_year=prev_y, prev_month=prev_m,
        next_year=next_y, next_month=next_m,
        daily_target=getattr(t, 'daily_target', 0.0)
    )

# === ADD TRADE ENTRY ===
@app.route('/entry/add', methods=['POST'])
@login_required
def add_entry():
    try:
        ed = datetime.strptime(request.form.get('entry_date'), '%Y-%m-%d').date()
        pl = float(request.form.get('profit_loss', 0))
        notes = request.form.get('notes', '').strip()
        db.session.add(DailyEntry(user_id=current_user.id, entry_date=ed, profit_loss=pl, notes=notes))
        sign = '+' if pl >= 0 else ''
        db.session.add(FeedPost(user_id=current_user.id, content=f"📊 Posted result: {sign}£{pl:.2f} on {ed}", post_type='result'))
        db.session.commit()
        flash(f'✅ Added: {sign}£{pl:.2f}', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error: {e}', 'error')
    return redirect(url_for('calendar_view'))

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
            flash(f'✅ Group targets updated: Daily £{dt:.2f} | Monthly £{mt:.2f}', 'success')
        except Exception as e:
            db.session.rollback()
            flash(f'Error saving: {e}', 'error')
    return render_template('targets.html',
        daily_target=getattr(t, 'daily_target', 0.0),
        monthly_target=getattr(t, 'monthly_target', 0.0)
    )

# === ADMIN PANEL ===
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
            total_entries=DailyEntry.query.count()
        )
    except Exception as e:
        flash(f'Error: {e}', 'error')
        return redirect(url_for('dashboard'))

@app.route('/admin/approve/<int:uid>', methods=['POST'])
@login_required
def approve(uid):
    if not current_user.is_admin: abort(403)
    u = User.query.get_or_404(uid)
    u.is_approved = True
    get_targets_safe(u)
    db.session.commit()
    flash(f'✅ {u.username} approved', 'success')
    return redirect(url_for('admin_settings'))

@app.route('/admin/remove/<int:uid>', methods=['POST'])
@login_required
def remove(uid):
    if not current_user.is_admin: abort(403)
    u = User.query.get_or_404(uid)
    if u.id == current_user.id:
        flash('Cannot remove yourself!', 'error')
        return redirect(url_for('admin_settings'))
    db.session.delete(u)
    db.session.commit()
    flash(f'✅ {u.username} removed from app', 'success')
    return redirect(url_for('admin_settings'))

# === PROFILE ===
@app.route('/profile/<username>')
@login_required
def profile(username):
    u = User.query.filter_by(username=username).first_or_404()
    if not u.is_approved and not current_user.is_admin:
        flash('Not approved yet', 'error')
        return redirect(url_for('dashboard'))
    return render_template('profile_view.html', profile_user=u)

# === FEED & CHAT ===
@app.route('/feed')
@login_required
def feed():
    try:
        posts = FeedPost.query.order_by(FeedPost.created_at.desc()).all()
    except Exception:
        posts = []
    return render_template('feed.html', posts=posts)

@app.route('/post/status', methods=['POST'])
@login_required
def post_status():
    c = request.form.get('content', '').strip()
    if c:
        db.session.add(FeedPost(user_id=current_user.id, content=c, post_type='status'))
        db.session.commit()
        flash('Posted ✅', 'success')
    return redirect(url_for('feed'))

@app.route('/chat/send', methods=['POST'])
@login_required
def send_chat():
    m = request.form.get('chat_message', '').strip()
    if m:
        db.session.add(ChatMessage(user_id=current_user.id, content=m))
        db.session.commit()
    return redirect(url_for('dashboard'))

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)
