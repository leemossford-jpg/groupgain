from flask import Flask, render_template, request, redirect, url_for, flash
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, current_user, login_user, logout_user, login_required
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, date

app = Flask(__name__)
app.config['SECRET_KEY'] = 'groupgain-fixed-key-2026'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///groupgain.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'


# ========== DATABASE MODELS ==========
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    trades = db.relationship('Trade', backref='user', lazy=True)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


class Trade(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    symbol = db.Column(db.String(20))
    pnl_amount = db.Column(db.Float, default=0.0)
    fees = db.Column(db.Float, default=0.0)
    category = db.Column(db.String(50))
    notes = db.Column(db.Text)
    date = db.Column(db.Date, nullable=False, default=datetime.utcnow().date)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


# ========== STATS HELPER ==========
def get_user_stats(uid):
    trades = Trade.query.filter_by(user_id=uid).all()
    if not trades:
        return {
            'total_pnl': 0, 'win_rate': 0, 'wins': 0, 'losses': 0, 'trade_count': 0,
            'profit_factor': 0, 'avg_win': 0, 'avg_loss': 0, 'largest_win': 0,
            'largest_loss': 0, 'total_fees': 0, 'net_after_fees': 0
        }
    total_pnl = sum(t.pnl_amount for t in trades)
    wins = [t for t in trades if t.pnl_amount > 0]
    losses = [t for t in trades if t.pnl_amount < 0]
    wc, lc = len(wins), len(losses)
    wr = round(wc / len(trades) * 100, 1) if trades else 0
    gw = sum(t.pnl_amount for t in wins) or 0
    gl = abs(sum(t.pnl_amount for t in losses)) or 0
    pf = round(gw / gl, 2) if gl > 0 else round(gw, 2)
    aw = round(gw / wc, 2) if wc else 0
    al = round(gl / lc, 2) if lc else 0
    lw = round(max([t.pnl_amount for t in wins]) if wins else 0, 2)
    ll = round(max([abs(t.pnl_amount) for t in losses]) if losses else 0, 2)
    tf = round(sum(t.fees or 0 for t in trades), 2)
    naf = round(total_pnl - tf, 2)
    return {
        'total_pnl': round(total_pnl, 2), 'win_rate': wr, 'wins': wc, 'losses': lc,
        'trade_count': len(trades), 'profit_factor': pf, 'avg_win': aw,
        'avg_loss': al, 'largest_win': lw, 'largest_loss': ll,
        'total_fees': tf, 'net_after_fees': naf
    }


# ========== ROUTES ==========
@app.route('/')
def home():
    return redirect(url_for('calendar') if current_user.is_authenticated else url_for('login'))


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user = User.query.filter_by(username=request.form.get('username')).first()
        if user and user.check_password(request.form.get('password')):
            login_user(user)
            return redirect(url_for('calendar'))
        flash('❌ Invalid username or password — try again')
    return render_template('login.html')


@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        if User.query.filter_by(username=request.form.get('username')).first():
            flash('Username already taken')
            return redirect(url_for('register'))
        new_user = User(
            username=request.form.get('username'),
            email=request.form.get('email')
        )
        new_user.set_password(request.form.get('password'))
        db.session.add(new_user)
        db.session.commit()
        flash('✅ Account created! Please log in')
        return redirect(url_for('login'))
    return render_template('register.html')


@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))


@app.route('/calendar')
@login_required
def calendar():
    return render_template('calendar_home.html')


@app.route('/add-entry')
@login_required
def add_entry_form():
    return render_template('add_entry.html')


@app.route('/save-entry', methods=['POST'])
@login_required
def save_entry():
    k = request.form.get('kind', 'win')
    sym = (request.form.get('sym', '') or '').strip().upper() or '—'
    amt = float(request.form.get('amt', 0) or 0)
    cat = request.form.get('cat') or None
    fees = float(request.form.get('fees', 0) or 0)
    notes = request.form.get('notes', '')

    if k == 'loss':
        pnl = -abs(amt)
    elif k == 'even':
        pnl = 0
    else:
        pnl = abs(amt)

    db.session.add(Trade(
        user_id=current_user.id, symbol=sym, pnl_amount=pnl,
        fees=fees, category=cat, notes=notes, date=date.today()
    ))
    db.session.commit()
    flash('✅ Entry saved!')
    return redirect(url_for('calendar'))


@app.route('/analyze')
@login_required
def analyze():
    s = get_user_stats(current_user.id)
    t = Trade.query.filter_by(user_id=current_user.id).order_by(Trade.date.desc()).all()
    return render_template('analyze.html', trades=t, **s)


@app.route('/feed')
@login_required
def feed():
    return "<h1 style='padding:2rem;color:#fff'>📡 Feed — Batch 3 coming!</h1>"


@app.route('/chat')
@login_required
def chat():
    return "<h1 style='padding:2rem;color:#fff'>💬 Chat — Batch 3 coming!</h1>"


@app.route('/profile')
@login_required
def profile():
    return "<h1 style='padding:2rem;color:#fff'>👤 Profile — Batch 4 coming!</h1>"


# ========== DATABASE SETUP ==========
with app.app_context():
    db.create_all()

if __name__ == '__main__':
    app.run(debug=True)