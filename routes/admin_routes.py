from flask import Blueprint, request, jsonify, session, render_template, redirect
import psutil
import os
import time
from services.storage_service import (
    get_stats, get_all_users, get_all_videos, get_logs,
    get_api_key_stats, get_all_codes, log_event,
    get_user_history, get_user_activity_summary,
    get_content_analytics, get_search_analytics,
    get_all_payments, get_payment_stats, get_user
)
from services.code_service import generate_codes_batch
from services.auth_service import is_admin, is_owner

admin_bp = Blueprint('admin', __name__, url_prefix='/admin')

def require_admin(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        user_id = session.get('user_id')
        if session.get('is_admin'):
            return f(*args, **kwargs)
        if user_id:
            user = get_user(user_id)
            if user and is_owner(user.get('email', '')):
                session['is_admin'] = True
                return f(*args, **kwargs)
        if request.path.startswith('/admin/api/'):
            return jsonify({'error': 'Unauthorized: Owner or Administrator authentication required'}), 401
        return redirect('/admin/login')
    return decorated

@admin_bp.route('/login', methods=['GET', 'POST'])
def admin_login():
    error = None
    if request.method == 'POST':
        pwd = request.form.get('password', '')
        if is_admin(pwd):
            session['is_admin'] = True
            log_event('INFO', "Admin successfully authenticated", source='admin')
            return redirect('/admin/')
        else:
            log_event('WARNING', "Failed admin authentication attempt", source='admin')
            error = "Invalid administrator password"
    
    return f'''
    <!DOCTYPE html>
    <html>
    <head>
        <title>VideoLens Admin Login</title>
        <link rel="stylesheet" href="/static/style.css">
        <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
        <style>
            body {{ background: #080A12; color: #F8FAFC; font-family: 'Inter', sans-serif; display: flex; align-items: center; justify-content: center; min-height: 100vh; margin: 0; }}
            .login-card {{ background: #101522; border: 1px solid #242B42; border-radius: 16px; padding: 36px; width: 340px; box-shadow: 0 10px 40px rgba(0,0,0,0.6); }}
            h2 {{ margin-top: 0; font-size: 20px; font-weight: 700; color: #F8FAFC; text-align: center; margin-bottom: 8px; }}
            p.sub {{ font-size: 13px; color: #8E9AAF; text-align: center; margin-bottom: 24px; }}
            input[type="password"] {{ width: 100%; box-sizing: border-box; background: #151C2B; border: 1px solid #242B42; border-radius: 10px; padding: 12px 14px; color: #F8FAFC; font-size: 14px; margin-bottom: 16px; outline: none; }}
            input[type="password"]:focus {{ border-color: #7C5CFC; }}
            button {{ width: 100%; background: linear-gradient(135deg, #7C3AED 0%, #5B5FEF 45%, #22D3EE 100%); border: none; border-radius: 10px; padding: 12px; color: #fff; font-weight: 600; font-size: 14px; cursor: pointer; transition: opacity 0.2s; }}
            button:hover {{ opacity: 0.95; }}
            .error {{ background: rgba(239, 68, 68, 0.15); border: 1px solid #EF4444; color: #EF4444; padding: 10px; border-radius: 8px; font-size: 13px; margin-bottom: 16px; text-align: center; }}
        </style>
    </head>
    <body>
        <div class="login-card">
            <h2>Admin Portal</h2>
            <p class="sub">Enter master password to access system controls</p>
            {"<div class='error'>" + error + "</div>" if error else ""}
            <form method="POST">
                <input type="password" name="password" placeholder="Enter admin password..." required autofocus autocomplete="current-password">
                <button type="submit">Unlock Dashboard →</button>
            </form>
        </div>
    </body>
    </html>
    '''

@admin_bp.route('/logout')
def admin_logout():
    session.pop('is_admin', None)
    return redirect('/admin/login')

@admin_bp.route('/')
@require_admin
def admin_dashboard():
    return render_template('admin.html')

@admin_bp.route('/api/health')
@require_admin
def system_health():
    cpu = psutil.cpu_percent(interval=1)
    ram = psutil.virtual_memory()
    disk = psutil.disk_usage('/')
    return jsonify({
        'cpu_percent': cpu,
        'ram_used_mb': round(ram.used / 1024 / 1024),
        'ram_total_mb': round(ram.total / 1024 / 1024),
        'ram_percent': ram.percent,
        'disk_used_gb': round(disk.used / 1024**3, 1),
        'disk_total_gb': round(disk.total / 1024**3, 1),
        'disk_percent': round(disk.percent, 1),
    })

@admin_bp.route('/api/stats')
@require_admin  
def admin_stats():
    return jsonify(get_stats())

@admin_bp.route('/api/users')
@require_admin
def admin_users():
    return jsonify(get_all_users())

@admin_bp.route('/api/videos')
@require_admin
def admin_videos():
    return jsonify(get_all_videos())

@admin_bp.route('/api/logs')
@require_admin
def admin_logs():
    return jsonify(get_logs())

@admin_bp.route('/api/api-keys')
@require_admin
def admin_api_keys():
    return jsonify(get_api_key_stats())

@admin_bp.route('/api/codes')
@require_admin
def admin_codes():
    return jsonify(get_all_codes())

@admin_bp.route('/api/generate-codes', methods=['POST'])
@require_admin
def admin_generate_codes():
    data = request.get_json() or {}
    plan = data.get('plan')
    count = min(int(data.get('count', 1)), 50)  # max 50 at once
    codes = generate_codes_batch(plan, count)
    log_event('INFO', f"Generated {len(codes)} promo codes for plan '{plan}'", source='admin')
    return jsonify({'codes': codes, 'plan': plan, 'count': len(codes)})

@admin_bp.route('/api/user/<user_id>/history')
@require_admin
def admin_user_history(user_id):
    action = request.args.get('action')
    status = request.args.get('status')
    q = request.args.get('q')
    sort_by = request.args.get('sort', 'newest')
    limit = int(request.args.get('limit', 100))
    history = get_user_history(user_id=user_id, action=action, status=status, search_query=q, sort_by=sort_by, limit=limit)
    summary = get_user_activity_summary(user_id)
    return jsonify({'history': history, 'summary': summary})

@admin_bp.route('/api/user/<user_id>/summary')
@require_admin
def admin_user_summary(user_id):
    return jsonify(get_user_activity_summary(user_id))

@admin_bp.route('/api/content-analytics')
@require_admin
def admin_content_analytics():
    limit = int(request.args.get('limit', 50))
    return jsonify(get_content_analytics(limit=limit))

@admin_bp.route('/api/content/<path:content_id>')
@require_admin
def admin_content_detail(content_id):
    data = get_content_analytics(content_id=content_id)
    if not data:
        return jsonify({'error': 'Content not found'}), 404
    return jsonify(data)

@admin_bp.route('/api/search-stats')
@require_admin
def admin_search_stats():
    return jsonify(get_search_analytics())

@admin_bp.route('/api/payments')
@require_admin
def admin_payments():
    payments = get_all_payments()
    stats = get_payment_stats()
    return jsonify({'payments': payments, 'stats': stats})

