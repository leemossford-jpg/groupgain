from flask import Flask, render_template, request, redirect, url_for, flash, abort
from flask_bcrypt import Bcrypt
from flask_login import LoginManager, login_user, login_required, logout_user, current_user
from datetime import datetime, date
import calendar
import socket
import os
from io import BytesIO
import base64
import requests
from werkzeug.utils import secure_filename
import qrcode

from database import db, User, DailyEntry, UserTarget, FeedPost, Comment, PasswordResetRequest

app = Flask(__name__)
app.config['SECRET_KEY'] = 'groupgain_secret_key_2026_secure!'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///groupgain.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = os.path.join('static', 'profile_pics')
app.config['MAX_CONTENT_LENGTH'] = 2 * 1024 * 1024

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}

bcrypt = Bcrypt(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'
login_manager.login_message = 'Please log in first!'

db.init_app(app)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def get_ngrok_url():
    try:
        resp = requests.get("http://127.0.0.1:4040/api/tunnels", timeout=2)
        if resp.ok:
            data = resp.json()
            for t in data.get("tunnels", []):
                if t.get("proto") == "https":
                    return t.get("public_url")
    except Exception:
        pass
    return None

with app.app_context():
    db.create_all()
    if not User.query.filter_by(username='admin').first():
        admin_pass = bcrypt.generate_password_hash('Admin123!').decode('utf-8')
        admin = User(username='admin', password_hash=admin_pass, is_approved=True, is_admin=True, bio="I run GroupGain 🚀")
        db.session.add(admin)
        db.session.commit()
        db.session.add(UserTarget(user_id=admin.id, daily_target=500.0, monthly_target=10000.0))
        db.session.commit()
        print("✅ Admin created: admin / Admin123!")

# === AUTH ===
@app.route('/signup', methods=['GET','POST'])
def signup():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    if request.method == 'POST':
        un = request.form['username'].strip()
        pw = request.form['password']
        if User.query.filter_by(username=un).first():
            flash('Username taken!','error')
            return redirect(url_for('signup'))
        hashed = bcrypt.generate_password_hash(pw).decode('utf-8')
        new_user = User(username=un, password_hash=hashed, is_approved=False, bio="Just joined GroupGain! 🎉")
        db.session.add(new_user)
        db.session.commit()
        db.session.add(UserTarget(user_id=new_user.id))
        db.session.commit()
        flash('✅ Account created! Waiting for admin approval.','success')
        return redirect(url_for('login'))
    return render_template('signup.html')

@app.route('/login', methods=['GET','POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        
        db.session.expire_all()
        user = User.query.filter_by(username=username).first()
        
        if not user:
            flash('Username not found', 'error')
            return redirect(url_for('login'))
        
        if bcrypt.check_password_hash(user.password_hash, password):
            if not user.is_approved:
                flash('⏳ Account pending approval', 'error')
                return redirect(url_for('login'))
            login_user(user)
            return redirect(url_for('dashboard'))
        else:
            flash('Invalid username or password', 'error')
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

# === FORGOT PASSWORD ===
@app.route('/forgot-password', methods=['GET','POST'])
def forgot_password():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    if request.method == 'POST':
        username = request.form['username'].strip()
        message = request.form.get('message', '').strip()
        user = User.query.filter_by(username=username).first()
        if user:
            existing = PasswordResetRequest.query.filter_by(user_id=user.id, is_resolved=False).first()
            if existing:
                flash('⚠️ You already have a pending request','error')
                return redirect(url_for('forgot_password'))
            db.session.add(PasswordResetRequest(user_id=user.id, message=message))
            db.session.commit()
            flash('✅ Request sent — admin will reset your password soon','success')
            return redirect(url_for('login'))
        flash('Username not found','error')
    return render_template('forgot_password.html')

# === ADMIN PASSWORD RESET — FINAL FIXED ===
@app.route('/admin/reset-requests')
@login_required
def list_reset_requests():
    if not current_user.is_admin:
        flash('Admin only!','error')
        return redirect(url_for('dashboard'))
    requests = PasswordResetRequest.query.order_by(PasswordResetRequest.created_at.desc()).all()
    return render_template('reset_requests.html', requests=requests)

@app.route('/admin/reset-password/<int:req_id>', methods=['GET','POST'])
@login_required
def admin_reset_password(req_id):
    if not current_user.is_admin:
        flash('Admin only!', 'error')
        return redirect(url_for('dashboard'))
    
    req = PasswordResetRequest.query.get_or_404(req_id)
    
    if req.is_resolved:
        flash('Already handled!', 'info')
        return redirect(url_for('list_reset_requests'))
    
    if request.method == 'POST':
        new_pass = request.form.get('new_password', '').strip()
        confirm_pass = request.form.get('confirm_password', '').strip()
        
        if len(new_pass) < 6:
            flash('Password must be at least 6 characters!', 'error')
            return redirect(url_for('admin_reset_password', req_id=req_id))
        if new_pass != confirm_pass:
            flash('Passwords do not match!', 'error')
            return redirect(url_for('admin_reset_password', req_id=req_id))
        
        db.session.expire_all()
        user = User.query.get(req.user.id)
        if not user:
            flash('User not found!', 'error')
            return redirect(url_for('list_reset_requests'))
        
        new_hash = bcrypt.generate_password_hash(new_pass).decode('utf-8')
        user.password_hash = new_hash
        req.is_resolved = True
        
        db.session.commit()
        db.session.remove()
        fresh_user = User.query.filter_by(id=user.id).first()
        
        if bcrypt.check_password_hash(fresh_user.password_hash, new_pass):
            flash(f'✅ Password saved & confirmed for {user.username}!', 'success')
        else:
            flash('❌ FAILED — delete groupgain.db and restart', 'error')
        
        return redirect(url_for('list_reset_requests'))
    
    return render_template('admin_reset.html', req=req)

# === SHARE / QR — FIXED REAL IP ===
@app.route('/share')
@login_required
def share_page():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
        s.close()
        base = f"http://{local_ip}:5000"
    except Exception:
        base = request.host_url.rstrip('/')

    signup_url = f"{base}/signup"

    qr_img = qrcode.make(signup_url)
    buffered = BytesIO()
    qr_img.save(buffered, format="PNG")
    qr_base64 = base64.b64encode(buffered.getvalue()).decode()

    return render_template('share.html',
        profile_url=signup_url,
        qr_code_data=qr_base64
    )

# === FEED ===
@app.route('/feed')
@login_required
def feed():
    posts = FeedPost.query.order_by(FeedPost.created_at.desc()).all()
    return render_template('feed.html', posts=posts)

@app.route('/post-status', methods=['POST'])
@login_required
def post_status():
    content = request.form.get('content', '').strip()
    if content:
        db.session.add(FeedPost(user_id=current_user.id, content=content, post_type="status"))
        db.session.commit()
        flash('Posted to feed! ✅','success')
    return redirect(url_for('feed'))

@app.route('/post/<int:post_id>/comment', methods=['POST'])
@login_required
def add_comment(post_id):
    post = FeedPost.query.get_or_404(post_id)
    content = request.form.get('comment_content', '').strip()
    if content:
        db.session.add(Comment(post_id=post.id, user_id=current_user.id, content=content))
        db.session.commit()
        flash('💬 Comment added! ✅', 'success')
    return redirect(url_for('feed'))

@app.route('/comment/<int:comment_id>/delete', methods=['POST'])
@login_required
def delete_comment(comment_id):
    comment = Comment.query.get_or_404(comment_id)
    if comment.author.id != current_user.id and not current_user.is_admin:
        flash('You cannot delete this comment!', 'error')
        return redirect(url_for('feed'))
    db.session.delete(comment)
    db.session.commit()
    flash('Comment deleted ✅', 'success')
    return redirect(url_for('feed'))

# === PROFILE ===
@app.route('/profile/<username>')
@login_required
def view_profile(username):
    user = User.query.filter_by(username=username).first_or_404()
    if not user.is_approved and not current_user.is_admin and user.id != current_user.id:
        abort(403)
    today = date.today()
    month_start = date(today.year, today.month, 1)
    today_total = round(sum(e.profit_loss for e in DailyEntry.query.filter_by(user_id=user.id, entry_date=today).all()), 2)
    month_total = round(sum(e.profit_loss for e in DailyEntry.query.filter(DailyEntry.user_id==user.id, DailyEntry.entry_date>=month_start).all()), 2)
    if not user.targets:
        db.session.add(UserTarget(user_id=user.id))
        db.session.commit()
    posts = FeedPost.query.filter_by(user_id=user.id).order_by(FeedPost.created_at.desc()).all()
    return render_template('profile_view.html', profile_user=user, today_total=today_total, month_total=month_total, targets=user.targets, posts=posts)

@app.route('/my-profile', methods=['GET','POST'])
@login_required
def my_profile():
    if request.method == 'POST':
        current_user.bio = request.form.get('bio', '').strip()
        db.session.commit()
        flash('Profile updated! ✅','success')
        return redirect(url_for('view_profile', username=current_user.username))
    return render_template('my_profile.html', user=current_user)

@app.route('/upload-avatar', methods=['POST'])
@login_required
def upload_avatar():
    if 'avatar' not in request.files:
        flash('No file selected','error')
        return redirect(url_for('my_profile'))
    file = request.files['avatar']
    if file.filename == '':
        flash('No file selected','error')
        return redirect(url_for('my_profile'))
    if file and allowed_file(file.filename):
        ext = secure_filename(file.filename).rsplit('.', 1)[1].lower()
        filename = f"user_{current_user.id}_{datetime.utcnow().timestamp()}.{ext}"
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(filepath)
        current_user.profile_pic = filename
        db.session.commit()
        flash('Profile picture updated! ✅','success')
    return redirect(url_for('view_profile', username=current_user.username))

# === TARGETS ===
@app.route('/my-targets', methods=['GET','POST'])
@login_required
def my_targets():
    if not current_user.targets:
        db.session.add(UserTarget(user_id=current_user.id))
        db.session.commit()
    if request.method == 'POST':
        current_user.targets.daily_target = float(request.form['daily_target'])
        current_user.targets.monthly_target = float(request.form['monthly_target'])
        db.session.commit()
        flash('Targets updated! ✅','success')
        return redirect(url_for('dashboard'))
    return render_template('my_targets.html', targets=current_user.targets)

# === CALENDAR ===
@app.route('/calendar')
@app.route('/calendar/<int:year>/<int:month>')
@login_required
def calendar_view(year=None, month=None):
    today = date.today()
    if year is None: year = today.year
    if month is None: month = today.month
    prev_month_date = month - 1
    prev_year_date = year
    if prev_month_date < 1: prev_month_date, prev_year_date = 12, year-1
    next_month_date = month + 1
    next_year_date = year
    if next_month_date > 12: next_month_date, next_year_date = 1, year+1
    cal = calendar.monthcalendar(year, month)
    month_start = date(year, month, 1)
    month_end = date(year, month, calendar.monthrange(year, month)[1])
    entries = DailyEntry.query.filter(DailyEntry.user_id == current_user.id, DailyEntry.entry_date >= month_start, DailyEntry.entry_date <= month_end).order_by(DailyEntry.entry_date.asc()).all()
    entry_map = {}
    for e in entries:
        d = e.entry_date
        if d not in entry_map: entry_map[d] = []
        entry_map[d].append(e)
    daily_totals = {d: sum(e.profit_loss for e in entry_map[d]) for d in entry_map}
    if not current_user.targets:
        db.session.add(UserTarget(user_id=current_user.id))
        db.session.commit()
    return render_template('calendar.html', today_date=today, year=year, month=month, month_name=calendar.month_name[month], calendar_weeks=cal, entry_map=entry_map, daily_totals=daily_totals, prev_year=prev_year_date, prev_month=prev_month_date, next_year=next_year_date, next_month=next_month_date, daily_target=current_user.targets.daily_target, date=date)

# === ADD ENTRY ===
@app.route('/add-entry', methods=['POST'])
@login_required
def add_entry():
    entry_date_str = request.form.get('entry_date')
    entry_date = datetime.strptime(entry_date_str, '%Y-%m-%d').date() if entry_date_str else date.today()
    pl = float(request.form['profit_loss'])
    notes = request.form.get('notes', '')
    entry = DailyEntry(user_id=current_user.id, entry_date=entry_date, profit_loss=pl, notes=notes)
    db.session.add(entry)
    db.session.flush()
    sign = "+" if pl >= 0 else ""
    content = f"📊 Posted result: {sign}£{pl:.2f} on {entry_date}"
    if notes: content += f"\n💬 {notes}"
    db.session.add(FeedPost(user_id=current_user.id, content=content, post_type="result", linked_entry_id=entry.id))
    db.session.commit()
    flash(f'Added: {sign}£{pl:.2f} ✅','success')
    return redirect(url_for('calendar_view'))

@app.route('/edit/<int:entry_id>', methods=['GET','POST'])
@login_required
def edit_entry(entry_id):
    entry = DailyEntry.query.get_or_404(entry_id)
    if entry.user_id != current_user.id and not current_user.is_admin:
        abort(403)
    if request.method == 'POST':
        entry.profit_loss = float(request.form['profit_loss'])
        entry.notes = request.form.get('notes', '')
        db.session.commit()
        flash('Updated! ✅','success')
        return redirect(url_for('calendar_view', year=entry.entry_date.year, month=entry.entry_date.month))
    return render_template('edit_entry.html', entry=entry)

# === ADMIN TOOLS ===
@app.route('/admin/approve', methods=['GET','POST'])
@login_required
def approve_users():
    if not current_user.is_admin:
        flash('Admin only!','error')
        return redirect(url_for('dashboard'))
    if request.method == 'POST':
        user = User.query.get(int(request.form['user_id']))
        if user:
            user.is_approved = True
            db.session.commit()
            flash(f'✅ Approved {user.username}!','success')
    pending = User.query.filter_by(is_approved=False).all()
    return render_template('approve.html', pending=pending)

@app.route('/admin/users')
@login_required
def all_users():
    if not current_user.is_admin:
        flash('Admin only!', 'error')
        return redirect(url_for('dashboard'))
    users = User.query.order_by(User.created_at.desc()).all()
    return render_template('all_users.html', users=users)

@app.route('/admin/delete-user/<int:user_id>', methods=['POST'])
@login_required
def delete_user(user_id):
    if not current_user.is_admin:
        flash('Admin only!', 'error')
        return redirect(url_for('dashboard'))
    if user_id == current_user.id:
        flash('⚠️ Cannot delete yourself!', 'error')
        return redirect(url_for('all_users'))
    user = User.query.get_or_404(user_id)
    db.session.delete(user)
    db.session.commit()
    flash(f'✅ {user.username} removed!', 'success')
    return redirect(url_for('all_users'))

@app.route('/admin/admins')
@login_required
def list_admins():
    if not current_user.is_admin:
        flash('Admin only!', 'error')
        return redirect(url_for('dashboard'))
    return render_template('admins_list.html', all_admins=User.query.filter_by(is_admin=True).all())

@app.route('/admin/remove-admin/<int:user_id>', methods=['POST'])
@login_required
def remove_admin(user_id):
    if not current_user.is_admin:
        flash('Admin only!', 'error')
        return redirect(url_for('dashboard'))
    if user_id == current_user.id:
        flash('⚠️ Cannot remove yourself!', 'error')
        return redirect(url_for('list_admins'))
    user = User.query.get_or_404(user_id)
    if user.is_admin:
        user.is_admin = False
        db.session.commit()
        flash(f'Removed admin from {user.username}! ✅', 'success')
    return redirect(url_for('list_admins'))

@app.route('/admin/make-admin/<int:user_id>', methods=['POST'])
@login_required
def make_admin(user_id):
    if not current_user.is_admin:
        flash('Admin only!', 'error')
        return redirect(url_for('dashboard'))
    user = User.query.get_or_404(user_id)
    if not user.is_admin:
        user.is_admin = True
        db.session.commit()
        flash(f'{user.username} is now an admin! 👑', 'success')
    return redirect(url_for('all_users'))

# === CHANGE PASSWORD ===
@app.route('/change-password', methods=['GET','POST'])
@login_required
def change_password():
    if request.method == 'POST':
        if not bcrypt.check_password_hash(current_user.password_hash, request.form['old_password']):
            flash('Wrong current password','error')
            return redirect(url_for('change_password'))
        if request.form['new_password'] != request.form['confirm_password']:
            flash('Passwords do not match','error')
            return redirect(url_for('change_password'))
        if len(request.form['new_password']) < 6:
            flash('Min 6 characters','error')
            return redirect(url_for('change_password'))
        current_user.password_hash = bcrypt.generate_password_hash(request.form['new_password']).decode('utf-8')
        db.session.commit()
        flash('Password changed! ✅','success')
        return redirect(url_for('dashboard'))
    return render_template('change_password.html')

# === DASHBOARD ===
@app.route('/')
@login_required
def dashboard():
    today = date.today()
    month_start = date(today.year, today.month, 1)
    if not current_user.targets:
        db.session.add(UserTarget(user_id=current_user.id))
        db.session.commit()
    today_total = round(sum(e.profit_loss for e in DailyEntry.query.filter_by(user_id=current_user.id, entry_date=today).all()), 2)
    month_total = round(sum(e.profit_loss for e in DailyEntry.query.filter(DailyEntry.user_id==current_user.id, DailyEntry.entry_date>=month_start).all()), 2)
    all_users = User.query.filter_by(is_approved=True).all()
    return render_template('dashboard.html', today=today, today_total=today_total, daily_target=current_user.targets.daily_target, month_total=month_total, monthly_target=current_user.targets.monthly_target, username=current_user.username, all_users=all_users)

if __name__ == '__main__':
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
        s.close()
        print(f"\n✅ Running at http://{local_ip}:5000")
        print(f"✅ QR uses REAL IP — Password Reset FIXED 🔑\n")
    except Exception:
        print("\n✅ Running at http://localhost:5000\n")
    app.run(debug=True, host='0.0.0.0', port=5000)