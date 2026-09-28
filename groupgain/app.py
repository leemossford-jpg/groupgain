from flask import Flask, render_template, request, redirect, url_for, flash, Response
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin, LoginManager, login_user, login_required, logout_user, current_user
from datetime import datetime
from collections import defaultdict
import csv
from io import StringIO

app = Flask(__name__)
app.config['SECRET_KEY'] = 'gg-2026-full-prod-key-keep-safe'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///groupgain.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password = db.Column(db.String(120), nullable=False)
    dark_mode = db.Column(db.Boolean, default=True)
    group_id = db.Column(db.Integer, db.ForeignKey('group.id'), nullable=True)
    is_admin = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Group(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    goal_amount = db.Column(db.Float, default=0.0)
    join_code = db.Column(db.String(20), default='')
    creator_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Trade(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    symbol = db.Column(db.String(20), nullable=False)
    asset_type = db.Column(db.String(50), default='Stock')
    entry_price = db.Column(db.Float, nullable=False)
    exit_price = db.Column(db.Float, nullable=True)
    quantity = db.Column(db.Float, nullable=False)
    notes = db.Column(db.Text, default='')
    tags = db.Column(db.String(200), default='')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    @property
    def pnl(self):
        if self.exit_price is None:
            return None
        return (self.exit_price - self.entry_price) * self.quantity

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

def get_group_leaderboard(group_id):
    members = User.query.filter_by(group_id=group_id).all()
    board = []
    for m in members:
        trades = Trade.query.filter_by(user_id=m.id).all()
        closed = [t for t in trades if t.pnl is not None]
        total = sum(t.pnl for t in closed)
        wins = len([t for t in closed if t.pnl > 0])
        board.append({
            'id': m.id, 'username': m.username,
            'trade_count': len(closed), 'win_count': wins,
            'total_pnl': total,
            'win_rate': (wins/len(closed)*100) if closed else 0
        })
    return sorted(board, key=lambda x: x['total_pnl'], reverse=True)

@app.route('/register', methods=['GET','POST'])
def register():
    if current_user.is_authenticated: return redirect(url_for('dashboard'))
    if request.method == 'POST':
        un = request.form['username'].strip()
        pw = request.form['password']
        if User.query.filter_by(username=un).first():
            flash('Username taken')
            return redirect(url_for('register'))
        db.session.add(User(username=un, password=pw))
        db.session.commit()
        flash('Account created — please log in')
        return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/login', methods=['GET','POST'])
def login():
    if current_user.is_authenticated: return redirect(url_for('dashboard'))
    if request.method == 'POST':
        u = User.query.filter_by(username=request.form['username'].strip()).first()
        if u and u.password == request.form['password']:
            login_user(u)
            return redirect(url_for('dashboard'))
        flash('Invalid credentials')
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

@app.route('/toggle-theme')
@login_required
def toggle_theme():
    current_user.dark_mode = not current_user.dark_mode
    db.session.commit()
    return redirect(request.referrer or url_for('dashboard'))

@app.route('/create-group', methods=['GET','POST'])
@login_required
def create_group():
    if current_user.group_id:
        flash('Already in a group')
        return redirect(url_for('dashboard'))
    if request.method == 'POST':
        name = request.form['name'].strip()
        goal = float(request.form.get('goal_amount') or 0)
        code = request.form.get('join_code', '').strip()
        if Group.query.filter_by(name=name).first():
            flash('Group name exists')
            return redirect(url_for('create_group'))
        g = Group(name=name, goal_amount=goal, join_code=code, creator_id=current_user.id)
        db.session.add(g)
        db.session.commit()
        current_user.group_id = g.id
        current_user.is_admin = True
        db.session.commit()
        flash(f'Group "{name}" created')
        return redirect(url_for('dashboard'))
    return render_template('create_group.html')

@app.route('/join-group', methods=['POST'])
@login_required
def join_group():
    if current_user.group_id:
        flash('Already in a group')
        return redirect(url_for('dashboard'))
    code = request.form.get('join_code', '').strip()
    g = Group.query.filter_by(join_code=code).first()
    if not g: flash('Invalid join code')
    else:
        current_user.group_id = g.id
        db.session.commit()
        flash(f'Joined "{g.name}"')
    return redirect(url_for('dashboard'))

@app.route('/leave-group')
@login_required
def leave_group():
    if current_user.group_id:
        current_user.group_id = None
        current_user.is_admin = False
        db.session.commit()
        flash('Left group')
    return redirect(url_for('dashboard'))

@app.route('/add-trade', methods=['GET','POST'])
@login_required
def add_trade():
    if request.method == 'POST':
        Trade(
            user_id=current_user.id,
            symbol=request.form['symbol'].strip().upper(),
            asset_type=request.form.get('asset_type','Stock'),
            entry_price=float(request.form['entry_price']),
            exit_price=float(request.form['exit_price']) if request.form.get('exit_price') else None,
            quantity=float(request.form['quantity']),
            notes=request.form.get('notes',''),
            tags=request.form.get('tags','')
        )
        db.session.commit()
        flash('Trade added')
        return redirect(url_for('dashboard'))
    return render_template('add_trade.html')

@app.route('/edit-trade/<int:tid>', methods=['GET','POST'])
@login_required
def edit_trade(tid):
    t = Trade.query.filter_by(id=tid, user_id=current_user.id).first_or_404()
    if request.method == 'POST':
        t.symbol = request.form['symbol'].strip().upper()
        t.asset_type = request.form.get('asset_type','Stock')
        t.entry_price = float(request.form['entry_price'])
        t.exit_price = float(request.form['exit_price']) if request.form.get('exit_price') else None
        t.quantity = float(request.form['quantity'])
        t.notes = request.form.get('notes','')
        t.tags = request.form.get('tags','')
        db.session.commit()
        flash('Trade updated')
        return redirect(url_for('dashboard'))
    return render_template('edit_trade.html', trade=t)

@app.route('/delete-trade/<int:tid>', methods=['POST'])
@login_required
def delete_trade(tid):
    t = Trade.query.filter_by(id=tid, user_id=current_user.id).first_or_404()
    db.session.delete(t)
    db.session.commit()
    flash('Trade deleted')
    return redirect(url_for('dashboard'))

@app.route('/export/csv')
@login_required
def export_csv():
    trades = Trade.query.filter_by(user_id=current_user.id).order_by(Trade.created_at.desc()).all()
    out = StringIO()
    w = csv.writer(out)
    w.writerow(['Symbol','Asset Type','Entry','Exit','Qty','P&L','Tags','Notes','Date'])
    for t in trades:
        w.writerow([t.symbol, t.asset_type, t.entry_price, t.exit_price or '',
            t.quantity, t.pnl or '', t.tags, t.notes, t.created_at.strftime('%Y-%m-%d %H:%M')])
    return Response(out.getvalue(), mimetype='text/csv',
        headers={'Content-Disposition':'attachment; filename=trades.csv'})

@app.route('/import/csv', methods=['POST'])
@login_required
def import_csv():
    f = request.files.get('csv_file')
    if not f: flash('No file selected'); return redirect(url_for('dashboard'))
    try:
        count = 0
        for row in csv.DictReader(StringIO(f.read().decode('utf-8'))):
            Trade(
                user_id=current_user.id,
                symbol=row.get('Symbol','').strip().upper(),
                asset_type=row.get('Asset Type','Stock'),
                entry_price=float(row.get('Entry Price',0)),
                exit_price=float(row.get('Exit Price')) if row.get('Exit Price') else None,
                quantity=float(row.get('Quantity',0)),
                notes=row.get('Notes',''),
                tags=row.get('Tags','')
            )
            count += 1
        db.session.commit()
        flash(f'Imported {count} trades')
    except Exception as e: flash(f'Import failed: {e}')
    return redirect(url_for('dashboard'))

@app.route('/')
@login_required
def dashboard():
    user_trades = Trade.query.filter_by(user_id=current_user.id).order_by(Trade.created_at.desc()).all()
    closed = [t for t in user_trades if t.pnl is not None]
    total_pnl = sum(t.pnl for t in closed)
    wins = [t for t in closed if t.pnl > 0]
    win_rate = len(wins)/len(closed)*100 if closed else 0

    group = Group.query.get(current_user.group_id) if current_user.group_id else None
    leaderboard = get_group_leaderboard(current_user.group_id) if current_user.group_id else []
    group_total = sum(m['total_pnl'] for m in leaderboard)
    goal_progress = min(100, (group_total/group.goal_amount*100)) if group and group.goal_amount>0 else 0

    sorted_closed = sorted(closed, key=lambda x:x.created_at)
    running = 0
    cumulative = []
    for t in sorted_closed:
        running += t.pnl
        cumulative.append({'date': t.created_at.strftime('%d/%m'), 'val': running})

    return render_template('dashboard.html',
        user_trades=user_trades, total_pnl=total_pnl,
        win_rate=win_rate, win_count=len(wins), closed_count=len(closed),
        group=group, leaderboard=leaderboard,
        group_total=group_total, goal_progress=goal_progress,
        cumulative_data=cumulative
    )

with app.app_context(): db.create_all()
if __name__ == '__main__': app.run(debug=True, port=5000)
