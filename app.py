from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta
import uuid, os

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-only-replace-me-later-gg372')
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///grouptrade.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=7)

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

# ===== DATABASE MODELS =====
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    group_id = db.Column(db.Integer, db.ForeignKey('group.id'))
    is_admin = db.Column(db.Boolean, default=False)
    dark_mode = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def set_password(self, pw):
        self.password_hash = generate_password_hash(pw, method='pbkdf2:sha256')
    def check_password(self, pw):
        return check_password_hash(self.password_hash, pw)

class Group(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)
    invite_code = db.Column(db.String(20), unique=True)
    admin_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    goal_amount = db.Column(db.Float, default=0)

class Trade(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    symbol = db.Column(db.String(20), nullable=False)
    asset_type = db.Column(db.String(20), nullable=False)
    entry_price = db.Column(db.Float, nullable=False)
    exit_price = db.Column(db.Float)
    quantity = db.Column(db.Float, nullable=False)
    pnl = db.Column(db.Float)
    notes = db.Column(db.Text)
    tags = db.Column(db.String(200))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Comment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    trade_id = db.Column(db.Integer, db.ForeignKey('trade.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Like(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    trade_id = db.Column(db.Integer, db.ForeignKey('trade.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)

class Watchlist(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    group_id = db.Column(db.Integer, db.ForeignKey('group.id'), nullable=False)
    symbol = db.Column(db.String(20), nullable=False)
    note = db.Column(db.String(200))
    added_at = db.Column(db.DateTime, default=datetime.utcnow)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

def calc_pnl(entry, exit_p, qty):
    return (exit_p - entry) * qty if exit_p else None

def get_leaderboard(group_id):
    from sqlalchemy import func, desc
    return db.session.query(
        User.id, User.username,
        func.sum(Trade.pnl).label('total_pnl'),
        func.count(Trade.id).label('trade_count'),
        func.sum(db.case((Trade.pnl > 0, 1), else_=0)).label('win_count')
    ).outerjoin(Trade, Trade.user_id == User.id)\
     .filter(User.group_id == group_id).group_by(User.id)\
     .order_by(desc('total_pnl')).all()

# ===== ROUTES =====
@app.route('/')
@login_required
def dashboard():
    user_trades = Trade.query.filter_by(user_id=current_user.id).order_by(Trade.created_at.desc()).all()
    group_trades = []
    leaderboard = []
    watchlist = []
    group_total = 0
    goal_progress = 0
    group = None

    if current_user.group_id:
        group_trades = Trade.query.join(User).filter(User.group_id == current_user.group_id)\
                          .order_by(Trade.created_at.desc()).all()
        leaderboard = get_leaderboard(current_user.group_id)
        watchlist = Watchlist.query.filter_by(group_id=current_user.group_id).all()
        group = Group.query.get(current_user.group_id)
        if leaderboard:
            group_total = sum(u.total_pnl or 0 for u in leaderboard)
            if group and group.goal_amount:
                goal_progress = min(100, (group_total / group.goal_amount) * 100)

    return render_template('dashboard.html',
        user_trades=user_trades, group_trades=group_trades,
        leaderboard=leaderboard, watchlist=watchlist,
        group_total=group_total, goal_progress=goal_progress, group=group)

@app.route('/register', methods=['GET','POST'])
def register():
    if request.method == 'POST':
        if User.query.filter_by(username=request.form['username']).first():
            flash('Username taken')
            return redirect(url_for('register'))
        u = User(username=request.form['username'])
        u.set_password(request.form['password'])
        db.session.add(u)
        db.session.commit()
        flash('Account created — welcome!')
        return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/login', methods=['GET','POST'])
def login():
    if request.method == 'POST':
        u = User.query.filter_by(username=request.form['username']).first()
        if u and u.check_password(request.form['password']):
            login_user(u, remember=True)
            return redirect(url_for('dashboard'))
        flash('Invalid username or password')
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

@app.route('/trade/add', methods=['GET','POST'])
@login_required
def add_trade():
    if request.method == 'POST':
        exit_p = float(request.form['exit_price']) if request.form.get('exit_price') else None
        pnl = calc_pnl(float(request.form['entry_price']), exit_p, float(request.form['quantity']))
        t = Trade(
            user_id=current_user.id,
            symbol=request.form['symbol'].upper(),
            asset_type=request.form['asset_type'],
            entry_price=float(request.form['entry_price']),
            exit_price=exit_p,
            quantity=float(request.form['quantity']),
            pnl=pnl,
            notes=request.form['notes'],
            tags=request.form.get('tags','')
        )
        db.session.add(t)
        db.session.commit()
        flash('Trade logged!')
        return redirect(url_for('dashboard'))
    return render_template('add_trade.html')

@app.route('/trade/edit/<int:tid>', methods=['GET','POST'])
@login_required
def edit_trade(tid):
    t = Trade.query.get_or_404(tid)
    if t.user_id != current_user.id:
        flash('Not your trade')
        return redirect(url_for('dashboard'))
    if request.method == 'POST':
        t.symbol = request.form['symbol'].upper()
        t.asset_type = request.form['asset_type']
        t.entry_price = float(request.form['entry_price'])
        t.exit_price = float(request.form['exit_price']) if request.form.get('exit_price') else None
        t.quantity = float(request.form['quantity'])
        t.pnl = calc_pnl(t.entry_price, t.exit_price, t.quantity)
        t.notes = request.form['notes']
        t.tags = request.form.get('tags','')
        db.session.commit()
        flash('Trade updated')
        return redirect(url_for('dashboard'))
    return render_template('edit_trade.html', trade=t)

@app.route('/trade/delete/<int:tid>', methods=['POST'])
@login_required
def delete_trade(tid):
    t = Trade.query.get_or_404(tid)
    if t.user_id != current_user.id and not current_user.is_admin:
        flash('No permission')
        return redirect(url_for('dashboard'))
    Comment.query.filter_by(trade_id=tid).delete()
    Like.query.filter_by(trade_id=tid).delete()
    db.session.delete(t)
    db.session.commit()
    flash('Trade deleted')
    return redirect(url_for('dashboard'))

@app.route('/group/create', methods=['GET','POST'])
@login_required
def create_group():
    if request.method == 'POST':
        code = str(uuid.uuid4())[:8]
        g = Group(name=request.form['name'], invite_code=code, admin_id=current_user.id)
        g.goal_amount = float(request.form.get('goal_amount', 0)) if request.form.get('goal_amount') else 0
        db.session.add(g)
        current_user.group_id = g.id
        current_user.is_admin = True
        db.session.commit()
        flash(f'Group created! Invite code: {code}')
        return redirect(url_for('dashboard'))
    return render_template('create_group.html')

@app.route('/group/join', methods=['POST'])
@login_required
def join_group():
    code = request.form['invite_code'].strip()
    g = Group.query.filter_by(invite_code=code).first()
    if g:
        current_user.group_id = g.id
        db.session.commit()
        flash(f'Joined: {g.name}')
    else:
        flash('Invalid invite code')
    return redirect(url_for('dashboard'))

@app.route('/import/csv', methods=['POST'])
@login_required
def import_csv():
    f = request.files['csv_file']
    try:
        import pandas as pd
        df = pd.read_csv(f)
        count = 0
        for _, row in df.iterrows():
            exit_p = float(row['Exit Price']) if 'Exit Price' in df.columns and pd.notna(row['Exit Price']) else None
            t = Trade(user_id=current_user.id, symbol=str(row['Symbol']).upper(),
                asset_type=row.get('Asset Type','Stocks'),
                entry_price=float(row['Entry Price']), exit_price=exit_p,
                quantity=float(row['Quantity']), pnl=calc_pnl(float(row['Entry Price']), exit_p, float(row['Quantity'])),
                notes=row.get('Notes',''), tags=row.get('Tags',''))
            db.session.add(t); count += 1
        db.session.commit()
        flash(f'Imported {count} trades!')
    except Exception as e:
        flash(f'Import failed: {str(e)}')
    return redirect(url_for('dashboard'))

@app.route('/export/csv')
@login_required
def export_csv():
    trades = Trade.query.filter_by(user_id=current_user.id).order_by(Trade.created_at.desc()).all()
    import csv, io
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(['Symbol','Asset Type','Entry Price','Exit Price','Quantity','P&L','Notes','Tags','Date'])
    for t in trades:
        w.writerow([t.symbol, t.asset_type, t.entry_price, t.exit_price or '', t.quantity, t.pnl or '', t.notes, t.tags, t.created_at])
    return out.getvalue(), 200, {'Content-Disposition':'attachment; filename=trades.csv'}

@app.route('/toggle-theme')
@login_required
def toggle_theme():
    current_user.dark_mode = not current_user.dark_mode
    db.session.commit()
    return redirect(url_for('dashboard'))

with app.app_context():
    db.create_all()

if __name__ == '__main__':
    app.run(debug=True, port=5000)
