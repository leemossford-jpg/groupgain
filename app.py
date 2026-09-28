from flask import Flask, render_template, request, redirect, url_for, flash
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, current_user, login_user, logout_user, login_required
from datetime import datetime

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your-secret-key-here-keep-safe'
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
    password_hash = db.Column(db.String(200), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    trades = db.relationship('Trade', backref='user', lazy=True)


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


# ========== EXISTING ROUTES ==========
@app.route('/')
def home():
    if current_user.is_authenticated:
        return redirect(url_for('calendar'))
    return redirect(url_for('login'))


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user = User.query.filter_by(username=request.form.get('username')).first()
        if user and user.password_hash == request.form.get('password'):
            login_user(user)
            return redirect(url_for('calendar'))
        flash('Invalid login')
    return render_template('login.html')


@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        existing = User.query.filter_by(username=request.form.get('username')).first()
        if existing:
            flash('Username taken')
            return redirect(url_for('register'))
        new_user = User(
            username=request.form.get('username'),
            email=request.form.get('email'),
            password_hash=request.form.get('password')
        )
        db.session.add(new_user)
        db.session.commit()
        flash('Registered! Please log in.')
        return redirect(url_for('login'))
    return render_template('register.html')


@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))


# ========== BATCH 1 — CALENDAR & ADD ENTRY ROUTES ==========
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
    # Get form data
    result_type = request.form.get('kind', 'win')
    symbol = request.form.get('sym', '').strip().upper()
    amount = float(request.form.get('amt', 0) or 0)
    category = request.form.get('cat')
    fees = float(request.form.get('fees', 0) or 0)
    notes = request.form.get('notes', '')

    # Apply result type to P&L
    if result_type == 'loss':
        pnl_value = -abs(amount)
    elif result_type == 'even':
        pnl_value = 0
    else:  # win
        pnl_value = abs(amount)

    # Save to database
    new_trade = Trade(
        user_id=current_user.id,
        symbol=symbol,
        pnl_amount=pnl_value,
        fees=fees,
        category=category,
        notes=notes,
        date=datetime.today().date()
    )
    db.session.add(new_trade)
    db.session.commit()

    flash('✅ Entry saved!')
    return redirect(url_for('calendar'))


@app.route('/analyze')
@login_required
def analyze():
    return "<h1>Analyze page coming next — Batch 2</h1>"

@app.route('/feed')
@login_required
def feed():
    return "<h1>Feed page coming next — Batch 3</h1>"

@app.route('/chat')
@login_required
def chat():
    return "<h1>Chat page coming next — Batch 3</h1>"

@app.route('/profile')
@login_required
def profile():
    return "<h1>Profile page coming next — Batch 4</h1>"


# ========== RUN ==========
with app.app_context():
    db.create_all()

if __name__ == '__main__':
    app.run(debug=True)