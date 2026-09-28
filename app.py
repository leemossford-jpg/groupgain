@app.route('/profile/<username>')
@login_required
def profile(username):
    profile_user = User.query.filter_by(username=username).first_or_404()
    
    # Date ranges
    today = date.today()
    month_start = date(today.year, today.month, 1)
    
    # All entries for this user
    all_entries = DailyEntry.query.filter_by(user_id=profile_user.id).order_by(DailyEntry.date.desc()).all()
    month_entries = DailyEntry.query.filter(
        DailyEntry.user_id == profile_user.id,
        DailyEntry.date >= month_start
    ).all()
    today_entries = [e for e in all_entries if e.date == today]
    
    # ===== CALCULATIONS =====
    # Today's P&L
    today_pnl = sum(e.profit_loss for e in today_entries)
    
    # Monthly P&L
    month_total = sum(e.profit_loss for e in month_entries)
    
    # Total Trades (days with at least one entry)
    unique_days = {}
    for e in all_entries:
        unique_days[e.date] = True
    total_trades = len(unique_days)
    
    # Win Rate
    winning_days = 0
    for day in unique_days:
        day_sum = sum(e.profit_loss for e in all_entries if e.date == day)
        if day_sum > 0:
            winning_days += 1
    win_rate = (winning_days / total_trades * 100) if total_trades > 0 else 0
    
    # Win Streak
    win_streak = 0
    sorted_dates = sorted(unique_days.keys(), reverse=True)
    for d in sorted_dates:
        day_sum = sum(e.profit_loss for e in all_entries if e.date == d)
        if day_sum > 0:
            win_streak += 1
        else:
            break
    
    # Avg Daily Profit
    days_in_month = today.day
    avg_daily_profit = month_total / days_in_month if days_in_month > 0 else 0
    
    # Daily P&L Chart (last 7 days)
    daily_pnl_chart = []
    for i in range(6, -1, -1):
        chart_date = today - timedelta(days=i)
        day_sum = sum(e.profit_loss for e in all_entries if e.date == chart_date)
        daily_pnl_chart.append(day_sum)
    max_pnl = max(abs(v) if v != 0 else 1 for v in daily_pnl_chart) if daily_pnl_chart else 1
    
    # Monthly P&L Chart (last 6 months)
    monthly_pnl_chart = []
    for i in range(5, -1, -1):
        chart_year = today.year
        chart_month = today.month - i
        while chart_month <= 0:
            chart_month += 12
            chart_year -= 1
        month_start_dt = date(chart_year, chart_month, 1)
        if chart_month == 12:
            month_end_dt = date(chart_year + 1, 1, 1) - timedelta(days=1)
        else:
            month_end_dt = date(chart_year, chart_month + 1, 1) - timedelta(days=1)
        month_sum = sum(e.profit_loss for e in all_entries 
                        if month_start_dt <= e.date <= month_end_dt)
        monthly_pnl_chart.append(month_sum)
    max_monthly_pnl = max(abs(v) if v != 0 else 1 for v in monthly_pnl_chart) if monthly_pnl_chart else 1
    
    # Posts
    posts = FeedPost.query.filter_by(author_id=profile_user.id).order_by(FeedPost.created_at.desc()).all()
    
    return render_template('profile.html',
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
