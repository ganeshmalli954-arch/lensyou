from flask import Blueprint, request, jsonify, session, render_template, redirect
import psutil
import os
import time
import urllib.parse
from services.storage_service import (
    get_stats, get_all_users, get_all_videos, get_logs,
    get_api_key_stats, get_all_codes, log_event,
    get_user_history, get_user_activity_summary,
    get_content_analytics, get_search_analytics,
    get_all_payments, get_payment_stats, get_user,
    get_system_setting, set_system_setting
)
from services.code_service import generate_codes_batch
from services.auth_service import is_admin, is_owner
from services.totp_service import (
    get_admin_totp_secret, is_admin_2fa_enabled, setup_admin_totp,
    disable_admin_totp, generate_totp_secret, format_secret_readable,
    get_totp_uri, verify_totp_code
)
from config import get_bmc_url

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
    two_fa_active = is_admin_2fa_enabled()
    
    if request.method == 'POST':
        pwd = request.form.get('password', '')
        import re
        totp_code = re.sub(r'\D', '', request.form.get('totp_code', ''))
        
        if not is_admin(pwd):
            log_event('WARNING', "Failed admin authentication attempt: invalid password", source='admin')
            error = "Invalid administrator password"
        elif two_fa_active:
            if not totp_code or len(totp_code) != 6:
                error = "Google Authenticator 6-digit code is required"
            else:
                secret = get_admin_totp_secret()
                if not secret or not verify_totp_code(secret, totp_code):
                    log_event('WARNING', "Failed admin 2FA verification attempt: invalid TOTP code", source='admin')
                    error = "Invalid 6-digit Google Authenticator code. Check device time sync."
                else:
                    session['is_admin'] = True
                    log_event('INFO', "Admin successfully authenticated with 2FA TOTP", source='admin')
                    return redirect('/admin/')
        else:
            session['is_admin'] = True
            log_event('INFO', "Admin successfully authenticated (password only)", source='admin')
            return redirect('/admin/')

    totp_input_html = ''
    if two_fa_active:
        totp_input_html = '''
            <div style="margin-bottom:16px; text-align:left;">
                <label style="display:block; font-size:12px; font-weight:600; color:#A1A1AA; margin-bottom:6px; letter-spacing:0.5px; text-transform:uppercase;">
                    Google Authenticator (2FA)
                </label>
                <input type="text" name="totp_code" placeholder="000 000" maxlength="8" inputmode="numeric" required autocomplete="one-time-code" autofocus
                       oninput="this.value = this.value.replace(/[^0-9]/g, '').slice(0, 6);"
                       style="width:100%; box-sizing:border-box; background:#141416; border:1px solid #222226; border-radius:8px; padding:12px 14px; color:#F5F5F5; font-size:18px; font-family:'JetBrains Mono', monospace; letter-spacing:4px; text-align:center; outline:none;">
            </div>
        '''
    else:
        totp_input_html = '''
            <div style="margin-top:16px; padding:10px 12px; background:rgba(255,255,255,0.02); border:1px solid #222226; border-radius:8px; font-size:12px; color:#71717A; text-align:center;">
                🔒 2FA is currently optional. <a href="/admin/setup-2fa" style="color:#F5F5F5; text-decoration:underline;">Set up Google Authenticator →</a>
            </div>
        '''

    return f'''
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <title>LensYou — Admin Portal Login</title>
        <link rel="icon" type="image/svg+xml" href="/static/logo.svg">
        <link rel="stylesheet" href="/static/style.css">
        <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;600&display=swap" rel="stylesheet">
        <style>
            body {{ background: #050505; color: #F5F5F5; font-family: 'Inter', sans-serif; display: flex; align-items: center; justify-content: center; min-height: 100vh; margin: 0; }}
            .login-card {{ background: #0C0C0D; border: 1px solid #222226; border-radius: 14px; padding: 36px; width: 360px; box-shadow: inset 0 1px 0 rgba(255,255,255,0.04), 0 16px 40px rgba(0,0,0,0.7); text-align: center; }}
            h2 {{ margin: 0 0 6px 0; font-size: 20px; font-weight: 700; color: #F5F5F5; }}
            p.sub {{ font-size: 13px; color: #71717A; margin: 0 0 24px 0; }}
            .form-group {{ margin-bottom: 16px; text-align: left; }}
            label {{ display: block; font-size: 11px; font-weight: 600; color: #A1A1AA; margin-bottom: 6px; letter-spacing: 0.5px; text-transform: uppercase; }}
            input[type="password"] {{ width: 100%; box-sizing: border-box; background: #141416; border: 1px solid #222226; border-radius: 8px; padding: 12px 14px; color: #F5F5F5; font-size: 14px; outline: none; transition: border-color 0.2s; }}
            input[type="password"]:focus, input[type="text"]:focus {{ border-color: #FFFFFF; }}
            button.submit-btn {{ width: 100%; background: #F5F5F5; border: 1px solid #FFFFFF; border-radius: 8px; padding: 12px; color: #09090B; font-weight: 600; font-size: 14px; cursor: pointer; transition: opacity 0.2s; margin-top: 8px; }}
            button.submit-btn:hover {{ opacity: 0.92; }}
            .error {{ background: rgba(239, 68, 68, 0.15); border: 1px solid #EF4444; color: #EF4444; padding: 10px; border-radius: 8px; font-size: 13px; margin-bottom: 16px; text-align: center; }}
            .badge-2fa {{ display: inline-flex; align-items: center; gap: 5px; padding: 3px 8px; border-radius: 4px; font-size: 11px; font-weight: 600; margin-bottom: 14px; }}
            .badge-active {{ background: rgba(34, 197, 94, 0.15); color: #22C55E; border: 1px solid rgba(34, 197, 94, 0.3); }}
            .badge-inactive {{ background: rgba(255, 255, 255, 0.05); color: #71717A; border: 1px solid #222226; }}
        </style>
    </head>
    <body>
        <div class="login-card">
            <img src="/static/logo.svg" alt="LensYou" width="40" height="40" style="margin-bottom: 12px;">
            <h2>Admin Portal</h2>
            <p class="sub">Owner authentication &amp; system management</p>
            
            <div style="margin-bottom: 16px;">
                {"<span class='badge-2fa badge-active'>● 2FA Protected (Google Authenticator)</span>" if two_fa_active else "<span class='badge-2fa badge-inactive'>○ Password Only (2FA Optional)</span>"}
            </div>

            {"<div class='error'>" + error + "</div>" if error else ""}

            <form method="POST" novalidate>
                <div class="form-group">
                    <label>Master Password</label>
                    <input type="password" name="password" placeholder="Enter admin password..." required autofocus autocomplete="current-password">
                </div>
                {totp_input_html}
                <button type="submit" class="submit-btn">Unlock Dashboard →</button>
            </form>
            
            <div style="margin-top: 24px; font-size: 11px; color: #52525B;">
                LensYou Intelligence Platform • <a href="/" style="color: #71717A; text-decoration: none;">Public Website</a>
            </div>
        </div>
    </body>
    </html>
    '''

@admin_bp.route('/setup-2fa', methods=['GET', 'POST'])
def setup_2fa():
    error = None
    is_authenticated = bool(session.get('is_admin'))

    if request.method == 'POST':
        pwd = request.form.get('password', '')
        import re
        totp_code = re.sub(r'\D', '', request.form.get('totp_code', ''))

        # If not authenticated, require valid master password
        if not is_authenticated:
            if not is_admin(pwd):
                error = "Invalid administrator password. (Default is admin123)"

        secret = request.form.get('setup_secret') or session.get('pending_totp_secret')
        if not error:
            if not secret:
                error = "Setup session expired. Please refresh the page."
            elif not totp_code or len(totp_code) != 6:
                error = "Please enter the complete 6-digit code shown in your Google Authenticator app."
            elif not verify_totp_code(secret, totp_code, window=2):
                error = "Invalid 6-digit code. Ensure your device time is synchronized and enter the code currently displayed."
            else:
                setup_admin_totp(secret, enable=True)
                session['is_admin'] = True
                session.pop('pending_totp_secret', None)
                log_event('INFO', "Google Authenticator 2FA configured and activated successfully", source='admin')
                return redirect('/admin/?msg=2fa_enabled')

    # GET or failed POST: Ensure a fresh pending secret exists
    if request.args.get('reset') or 'pending_totp_secret' not in session:
        session['pending_totp_secret'] = generate_totp_secret()

    secret = session['pending_totp_secret']
    formatted_secret = format_secret_readable(secret)
    totp_uri = get_totp_uri(secret, account="Admin", issuer="LensYou")
    encoded_uri = urllib.parse.quote(totp_uri)
    qr_url = f"https://api.qrserver.com/v1/create-qr-code/?size=220x220&margin=8&data={encoded_uri}"
    qr_fallback = f"https://chart.googleapis.com/chart?chs=220x220&cht=qr&chl={encoded_uri}"

    pwd_input_html = ''
    if not is_authenticated:
        pwd_input_html = '''
            <div style="margin-bottom:16px; text-align:left;">
                <label style="display:block; font-size:11px; font-weight:600; color:#A1A1AA; margin-bottom:6px; letter-spacing:0.5px; text-transform:uppercase;">
                    Master Admin Password
                </label>
                <input type="password" name="password" placeholder="Enter admin password (default: admin123)..." value="admin123" required
                       style="width:100%; box-sizing:border-box; background:#141416; border:1px solid #222226; border-radius:8px; padding:12px 14px; color:#F5F5F5; font-size:14px; outline:none;">
                <div style="font-size:11px; color:#71717A; margin-top:4px;">Default is <code>admin123</code> unless configured differently in environment.</div>
            </div>
        '''

    return f'''
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <title>Setup Google Authenticator — LensYou</title>
        <link rel="icon" type="image/svg+xml" href="/static/logo.svg">
        <link rel="stylesheet" href="/static/style.css">
        <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;600&display=swap" rel="stylesheet">
        <style>
            body {{ background: #050505; color: #F5F5F5; font-family: 'Inter', sans-serif; display: flex; align-items: center; justify-content: center; min-height: 100vh; margin: 0; padding: 24px 0; }}
            .setup-card {{ background: #0C0C0D; border: 1px solid #222226; border-radius: 16px; padding: 32px; width: 440px; box-shadow: inset 0 1px 0 rgba(255,255,255,0.04), 0 20px 50px rgba(0,0,0,0.8); text-align: center; }}
            h2 {{ margin: 0 0 6px 0; font-size: 20px; font-weight: 700; color: #F5F5F5; }}
            p.sub {{ font-size: 13px; color: #71717A; margin: 0 0 20px 0; line-height: 1.4; }}
            .qr-box {{ background: #FFFFFF; border-radius: 12px; padding: 12px; width: 220px; height: 220px; margin: 0 auto 20px auto; box-shadow: 0 4px 20px rgba(0,0,0,0.5); }}
            .qr-box img {{ display: block; width: 100%; height: 100%; }}
            .step-box {{ background: #141416; border: 1px solid #222226; border-radius: 10px; padding: 14px; margin-bottom: 20px; text-align: left; font-size: 12px; color: #A1A1AA; line-height: 1.5; }}
            .step-box strong {{ color: #F5F5F5; }}
            .code-box {{ font-family: 'JetBrains Mono', monospace; font-size: 15px; font-weight: 600; color: #F5F5F5; background: #080808; border: 1px dashed #333338; border-radius: 6px; padding: 8px 12px; margin-top: 6px; display: flex; align-items: center; justify-content: space-between; }}
            .copy-btn {{ background: #222226; border: none; color: #F5F5F5; padding: 4px 10px; border-radius: 4px; font-size: 11px; cursor: pointer; }}
            .copy-btn:hover {{ background: #333338; }}
            button.submit-btn {{ width: 100%; background: #F5F5F5; border: 1px solid #FFFFFF; border-radius: 8px; padding: 12px; color: #09090B; font-weight: 600; font-size: 14px; cursor: pointer; transition: opacity 0.2s; margin-top: 8px; }}
            button.submit-btn:hover {{ opacity: 0.92; }}
            .error {{ background: rgba(239, 68, 68, 0.15); border: 1px solid #EF4444; color: #EF4444; padding: 10px; border-radius: 8px; font-size: 13px; margin-bottom: 16px; text-align: center; }}
        </style>
    </head>
    <body>
        <div class="setup-card">
            <img src="/static/logo.svg" alt="LensYou" width="36" height="36" style="margin-bottom: 10px;">
            <h2>Google Authenticator 2FA</h2>
            <p class="sub">Add two-factor authentication (TOTP) to protect your private Owner and Admin Portal.</p>

            {"<div class='error'>" + error + "</div>" if error else ""}

            <!-- Step 1: QR Code -->
            <div class="qr-box">
                <img src="{qr_url}" onerror="this.onerror=null; this.src='{qr_fallback}';" alt="2FA QR Code">
            </div>

            <!-- Step 2: Manual Key -->
            <div class="step-box">
                <div><strong>Option 1 (Scan):</strong> Open <strong>Google Authenticator</strong> on your phone, tap <strong>+</strong> &rarr; <strong>Scan a QR code</strong>.</div>
                <div style="margin-top: 10px;"><strong>Option 2 (Manual Setup Key):</strong> If you cannot scan:</div>
                <div style="font-size: 11px; color: #71717A; margin-top: 4px;">In app, tap <strong>+</strong> &rarr; <strong>Enter a setup key</strong> &rarr; Account: <code>LensYou:Admin</code> &rarr; Key:</div>
                <div class="code-box">
                    <span id="secretKeyText" style="letter-spacing: 2px;">{secret}</span>
                    <button type="button" class="copy-btn" onclick="navigator.clipboard.writeText('{secret}'); this.textContent='Copied!';">Copy Key</button>
                </div>
                <div style="font-size: 11px; color: #71717A; margin-top: 6px;">Readable chunks: <code>{formatted_secret}</code> (Type: <strong>Time based</strong>)</div>
            </div>

            <!-- Step 3: Verification -->
            <form method="POST" novalidate>
                <input type="hidden" name="setup_secret" value="{secret}">
                {pwd_input_html}
                <div style="margin-bottom: 16px; text-align: left;">
                    <label style="display:block; font-size:11px; font-weight:600; color:#A1A1AA; margin-bottom:6px; letter-spacing:0.5px; text-transform:uppercase;">
                        Enter 6-Digit Code from Authenticator App
                    </label>
                    <input type="text" name="totp_code" id="setupTotpCode" placeholder="000 000" maxlength="8" inputmode="numeric" required autofocus autocomplete="one-time-code"
                           oninput="this.value = this.value.replace(/[^0-9]/g, '').slice(0, 6);"
                           style="width:100%; box-sizing:border-box; background:#141416; border:1px solid #222226; border-radius:8px; padding:12px 14px; color:#F5F5F5; font-size:20px; font-family:'JetBrains Mono', monospace; letter-spacing:4px; text-align:center; outline:none;">
                </div>
                <button type="submit" class="submit-btn">Verify & Activate 2FA →</button>
            </form>

            <div style="margin-top: 18px; display: flex; justify-content: space-between; font-size: 12px;">
                <a href="/admin/setup-2fa?reset=1" style="color: #71717A; text-decoration: none;">↻ Regenerate Key</a>
                <a href="/admin/login" style="color: #71717A; text-decoration: none;">Cancel & Return</a>
            </div>
        </div>
    </body>
    </html>
    '''

@admin_bp.route('/disable-2fa', methods=['POST'])
@require_admin
def disable_2fa_route():
    disable_admin_totp()
    log_event('WARNING', "Google Authenticator 2FA disabled by administrator", source='admin')
    if request.is_json:
        return jsonify({'success': True, 'message': 'Google Authenticator 2FA has been disabled'})
    return redirect('/admin/?msg=2fa_disabled')

@admin_bp.route('/api/settings', methods=['GET', 'POST'])
@require_admin
def admin_settings_api():
    if request.method == 'POST':
        data = request.get_json() or {}
        if 'bmc_url' in data:
            new_url = str(data['bmc_url']).strip()
            if new_url:
                set_system_setting('bmc_url', new_url)
                log_event('INFO', f"Updated Buy Me a Coffee URL to: {new_url}", source='admin')
        if 'admin_2fa_enabled' in data:
            enable = bool(data['admin_2fa_enabled'])
            set_system_setting('admin_2fa_enabled', 'true' if enable else 'false')
            log_event('INFO', f"Updated admin 2FA status: {'enabled' if enable else 'disabled'}", source='admin')

        return jsonify({
            'success': True,
            'bmc_url': get_bmc_url(),
            'admin_2fa_enabled': is_admin_2fa_enabled()
        })

    return jsonify({
        'bmc_url': get_bmc_url(),
        'admin_2fa_enabled': is_admin_2fa_enabled(),
        'has_secret': bool(get_admin_totp_secret())
    })

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
