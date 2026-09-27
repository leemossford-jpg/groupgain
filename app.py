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

# Database config
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
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

bcrypt = Bcrypt(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

from database import db, User, DailyEntry, UserTarget, FeedPost, Comment, ChatMessage, PasswordResetRequest
db.init_app(app)

# ==============================================
# ONE-TIME RESET — REMOVE AFTER FIRST SUCCESS
# ==============================================
with app.app_context():
    db.drop_all()
    db.create_all()
    print("✅ All tables created fresh")
    
    if not User.query.filter_by(username='admin').first():
        admin = User(
            username='admin',
            password_hash=bcrypt.generate_password_hash('Admin123!').decode('utf-8'),
            is_approved=True,
            is_admin=True,
            bio="GroupGain Founder 👑"
        )
        db.session.add(admin)
        db.session.commit()
        db.session.add(UserTarget(user_id=admin.id, daily_target=0.0, monthly_target=0.0))
        db.session.commit()
        print("✅ Admin created: admin / Admin123! — CHANGE THIS PASSWORD!")


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

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


# === AUTH ===
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
        u = User(username=un, password_hash=bcrypt.generate_password_hash(pw).decode('utf-8'))
        db.session.add(u)
        db.session.commit()
        flash('Account created — waiting admin approval', 'success')
        return redirect(url_for('login'))
    return render_template('signup.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    if request.method == 'POST':
        u = User.query.filter_by(username=request.form.get('username', '').strip()).first()
        if not u or not bcrypt.check_password_hash(u.password_hash, request.form.get('password', '')):
            flash('Invalid login', 'error')
            return redirect(url_for('login'))
        if not u.is_approved:
            flash('⏳ Pending approval', 'error')
            return redirect(url_for('login'))
        login_user(u, remember=True)
        return redirect(url_for('dashboard'))
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))


# === DASHBOARD ===
@app.route('/')
@login_required
def dashboard():
    today = date.today()
    month_start = date(today.year, today.month, 1)
    t = get_targets_safe(current_user)
    
    try:
        today_total = round(sum((e.profit_loss or 0) for e in
            DailyEntry.query.filter_by(user_id=current_user.id, entry_date=today).all()), 2)
    except:
        today_total = 0.0
    
    try:
        month_total = round(sum((e.profit_loss or 0) for e in
            DailyEntry.query.filter(DailyEntry.user_id==current_user.id,
            DailyEntry.entry_date >= month_start).all()), 2)
    except:
        month_total = 0.0
    
    try:
        messages = ChatMessage.query.order_by(ChatMessage.created_at.asc()).limit(50).all()
    except:
        messages = []
    
    try:
        all_users = User.query.filter_by(is_approved=True).all()
    except:
        all_users = []
    
    return render_template('dashboard.html',
        today=today,
        today_total=today_total,
        month_total=month_total,
        daily_target=getattr(t, 'daily_target', 0.0),
        monthly_target=getattr(t, 'monthly_target', 0.0),
        messages=messages,
        all_users=all_users
    )


# === CALENDAR ===
@app.route('/calendar')
@app.route('/calendar/<int:y>/<int:m>')
@login_required
def calendar_view(y=None, m=None):
    today = date.today()
    try:
        y = y or today.year
        m = m or today.month
        y = max(2020, min(2100, int(y)))
        m = max(1, min(12, int(m)))
    except:
        y, m = today.year, today.month
    
    prev_m, prev_y = (m-1, y) if m > 1 else (12, y-1)
    next_m, next_y = (m+1, y) if m < 12 else (1, y+1)
    start = date(y, m, 1)
    end = date(y, m, calendar.monthrange(y, m)[1])
    
    try:
        entries = DailyEntry.query.filter(DailyEntry.user_id==current_user.id,
            DailyEntry.entry_date >= start, DailyEntry.entry_date <= end).all()
    except:
        entries = []
    
    day_totals = {}
    for e in entries:
        day_totals[e.entry_date] = day_totals.get(e.entry_date, 0) + (e.profit_loss or 0)
    
    t = get_targets_safe(current_user)
    
    return render_template('calendar.html',
        today=today, year=y, month=m,
        month_name=calendar.month_name[m],
        calendar_weeks=calendar.monthcalendar(y, m),
        daily_totals=day_totals,
        prev_year=prev_y, prev_month=prev_m,
        next_year=next_y, next_month=next_m,
        daily_target=getattr(t, 'daily_target', 0.0)
    )


# === ADD ENTRY ===
@app.route('/entry/add', methods=['POST'])
@login_required
def add_entry():
    try:
        ed = datetime.strptime(request.form.get('entry_date'), '%Y-%m-%d').date()
        pl = float(request.form.get('profit_loss', 0))
        notes = request.form.get('notes', '').strip()
        db.session.add(DailyEntry(user_id=current_user.id, entry_date=ed, profit_loss=pl, notes=notes))
        sign = '+' if pl >= 0 else ''
        db.session.add(FeedPost(user_id=current_user.id,
            content=f"📊 Posted result: {sign}£{pl:.2f} on {ed}", post_type='result'))
        db.session.commit()
        flash(f'✅ Added: {sign}£{pl:.2f}', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error: {e}', 'error')
    return redirect(url_for('calendar_view'))


# === TARGETS ===
@app.route('/targets', methods=['GET', 'POST'])
@login_required
def targets():
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
            flash(f'✅ Targets updated', 'success')
        except Exception as e:
            db.session.rollback()
            flash(f'Error: {e}', 'error')
    return render_template('targets.html',
        daily_target=getattr(t, 'daily_target', 0.0),
        monthly_target=getattr(t, 'monthly_target', 0.0)
    )


# === SHARE/QR ===
@app.route('/share')
@login_required
def share():
    url = f"{get_base_url()}/signup"
    qr = None
    try:
        buf = BytesIO()
        qrcode.make(url).save(buf, 'PNG')
        qr = base64.b64encode(buf.getvalue()).decode()
    except:
        pass
    return render_template('share.html', signup_url=url, qr_data=qr)


# === FEED ===
@app.route('/feed')
@login_required
def feed():
    try:
        posts = FeedPost.query.order_by(FeedPost.created_at.desc()).all()
    except:
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


# === CHAT ===
@app.route('/chat/send', methods=['POST'])
@login_required
def send_chat():
    m = request.form.get('chat_message', '').strip()
    if m:
        db.session.add(ChatMessage(user_id=current_user.id, content=m))
        db.session.commit()
    return redirect(url_for('dashboard'))


# === ADMIN ===
@app.route('/admin')
@login_required
def admin_panel():
    if not current_user.is_admin:
        flash('Admin only', 'error')
        return redirect(url_for('dashboard'))
    try:
        users = User.query.all()
    except:
        users = []
    return render_template('admin.html', users=users)

@app.route('/admin/approve/<int:uid>', methods=['POST'])
@login_required
def approve(uid):
    if not current_user.is_admin:
        return redirect(url_for('dashboard'))
    u = User.query.get_or_404(uid)
    u.is_approved = True
    get_targets_safe(u)
    db.session.commit()
    flash(f'✅ {u.username} approved', 'success')
    return redirect(url_for('admin_panel'))

@app.route('/admin/remove/<int:uid>', methods=['POST'])
@login_required
def remove(uid):
    if not current_user.is_admin:
        return redirect(url_for('dashboard'))
    u = User.query.get_or_404(uid)
    if u.id == current_user.id:
        flash('Cannot remove yourself', 'error')
        return redirect(url_for('admin_panel'))
    db.session.delete(u)
    db.session.commit()
    flash(f'✅ {u.username} removed', 'success')
    return redirect(url_for('admin_panel'))


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)
