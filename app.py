import os
import sys
import secrets
import hashlib
from datetime import timedelta
from flask import Flask, render_template, request, jsonify, send_file, session, redirect, url_for, send_from_directory
from dotenv import load_dotenv
from authlib.integrations.flask_client import OAuth
from waitress import serve

# Import local modules
from config import FEATURES, SECRET_KEY, ADMIN_PASSWORD, BMC_URL
from services.storage_service import (
    init_db, get_stats, get_user, get_user_history,
    record_search_event, record_payment, update_user_plan,
    get_analysis, update_search_event_content
)
from services.metadata_service import extract_video_id, get_video_oembed, search_youtube
from services.job_service import create_job, get_job, start_job, JOBS
from services.auth_service import (
    get_session_key, check_quota, get_or_create_user,
    is_owner, PLAN_CONFIG, get_plan_history_limit
)
from services.code_service import redeem_code
from routes.admin_routes import admin_bp
from services.analysis_service import call_gemini_with_fallback
from utils.json_utils import safe_json_parse, sanitize_data_strings
from utils.time_utils import prepare_transcript_for_analysis
from pdf_generator import generate_detailed_pdf

# Fix Windows console encoding for unicode
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

load_dotenv()

# Only allow insecure transport in local development
if os.getenv('RENDER') or os.getenv('PRODUCTION'):
    os.environ.pop('OAUTHLIB_INSECURE_TRANSPORT', None)

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY") or secrets.token_hex(32)

# Secure application cookie settings & persistent sessions
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_SECURE'] = bool(os.getenv('RENDER') or os.getenv('PRODUCTION'))
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=30)

# Init DB
init_db()

# Register Admin blueprint
app.register_blueprint(admin_bp)

# OAuth setup
oauth = OAuth(app)
if FEATURES.get('google_login'):
    oauth.register('google',
        client_id=os.getenv('GOOGLE_CLIENT_ID'),
        client_secret=os.getenv('GOOGLE_CLIENT_SECRET'),
        server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
        client_kwargs={'scope': 'openid email profile'}
    )

if FEATURES.get('twitter_login'):
    pass # Add twitter setup if needed
if FEATURES.get('facebook_login'):
    pass # Add facebook setup if needed

def get_key_pool():
    keys = os.getenv('GEMINI_API_KEYS')
    if keys:
        pool = [(i, k.strip()) for i, k in enumerate(keys.split(',')) if k.strip()]
        if pool: return pool
    key = os.getenv('GEMINI_API_KEY')
    if key and key != "your_key_here":
        return [(0, key)]
    return []

@app.before_request
def assign_anon_session():
    if 'session_key' not in session and not session.get('user_id'):
        ip = request.headers.get("X-Forwarded-For", request.remote_addr or "").split(",")[0].strip()
        ua = request.headers.get("User-Agent", "")
        session['session_key'] = get_session_key(ip, ua)

@app.context_processor
def inject_global_vars():
    return {'bmc_url': BMC_URL}

# --- View Routes ---

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/history")
def history_page():
    return render_template("history.html")

@app.route("/owner")
def owner_redirect():
    return redirect("/admin/")

@app.route("/favicon.ico")
def favicon():
    return send_from_directory(app.static_folder, "logo.svg", mimetype="image/svg+xml")

@app.route("/manifest.json")
def manifest():
    return send_from_directory(app.static_folder, "manifest.json", mimetype="application/manifest+json")

# --- Auth Routes ---

@app.route('/auth/google')
def auth_google():
    if not FEATURES.get('google_login'):
        return "Google login not configured", 400
    redirect_uri = url_for('auth_google_callback', _external=True)
    return oauth.google.authorize_redirect(redirect_uri)

@app.route('/auth/google/callback')
def auth_google_callback():
    if not FEATURES.get('google_login'):
        return "Google login not configured", 400
    try:
        token = oauth.google.authorize_access_token()
        userinfo = token.get('userinfo')
        if userinfo:
            user = get_or_create_user(
                provider='google',
                provider_id=userinfo['sub'],
                email=userinfo.get('email', ''),
                name=userinfo.get('name', ''),
                avatar_url=userinfo.get('picture', '')
            )
            session.permanent = True
            session['user_id'] = user['id']
            if is_owner(user.get('email', '')):
                session['is_admin'] = True
    except Exception as e:
        print(f'OAuth callback error: {e}')
        return redirect('/?auth_error=1')
    return redirect('/')

@app.route('/auth/dev-login', methods=['GET', 'POST'])
def dev_login():
    """Development/Testing simulated Google OAuth login for multi-account testing."""
    if os.getenv('RENDER') or os.getenv('PRODUCTION'):
        return jsonify({'error': 'Dev login disabled in strict production'}), 403
    email = (request.args.get('email') or (request.get_json(silent=True) or {}).get('email') or 'user_alpha@example.com').strip().lower()
    name = request.args.get('name') or (request.get_json(silent=True) or {}).get('name') or 'User Alpha'
    sub = f"dev_google_{hashlib.sha256(email.encode()).hexdigest()[:16]}"
    user = get_or_create_user(
        provider='google',
        provider_id=sub,
        email=email,
        name=name,
        avatar_url=''
    )
    session.permanent = True
    session['user_id'] = user['id']
    if is_owner(email):
        session['is_admin'] = True
    return redirect(request.args.get('redirect', '/'))

@app.route('/auth/logout', methods=['POST', 'GET'])
def logout():
    session.pop('user_id', None)
    session.pop('is_admin', None)
    return redirect('/')

# --- API Routes ---

@app.route('/api/config')
def get_config():
    return jsonify({'features': FEATURES, 'bmc_url': BMC_URL})

@app.route('/api/me')
def api_me():
    user_id = session.get('user_id')
    session_key = session.get('session_key')
    
    quota = check_quota(user_id=user_id, session_key=session_key)
    if user_id:
        user = get_user(user_id)
        if user:
            # hide sensitive
            safe_user = {k: v for k, v in user.items() if k not in ['provider_id']}
            safe_user['is_owner'] = is_owner(user.get('email', ''))
            safe_user['history_limit'] = get_plan_history_limit(user.get('plan', 'free'))
            safe_user['quota_info'] = quota
            return jsonify({'logged_in': True, 'user': safe_user})
            
    return jsonify({
        'logged_in': False,
        'quota_info': quota,
        'history_limit': get_plan_history_limit('anonymous')
    })

@app.route('/api/search', methods=['GET', 'POST'])
def api_search():
    """Unified search endpoint: records account-level search event and returns matching videos."""
    if request.method == 'POST':
        data = request.get_json(silent=True) or {}
        raw_query = data.get('query', '').strip()
    else:
        raw_query = request.args.get('q', '').strip()

    if not raw_query:
        return jsonify({'error': 'No search query provided'}), 400

    user_id = session.get('user_id')
    session_key = session.get('session_key')
    user = get_user(user_id) if user_id else None
    user_plan = user.get('plan', 'free') if user else 'anonymous'

    # Check if direct YouTube video URL or ID
    vid_id = extract_video_id(raw_query)
    if vid_id:
        meta = get_video_oembed(vid_id)
        video_title = meta.get('title') or f"YouTube Video ({vid_id})"
        event_id = record_search_event(
            user_id=user_id,
            session_key=session_key,
            query=raw_query,
            content_id=vid_id,
            content_title=video_title,
            content_type="YouTube Video",
            plan=user_plan
        )
        return jsonify({
            'is_direct_video': True,
            'video_id': vid_id,
            'title': video_title,
            'event_id': event_id,
            'results': [{
                'video_id': vid_id,
                'title': video_title,
                'author': meta.get('author_name', 'YouTube Creator'),
                'thumbnail_url': meta.get('thumbnail_url') or f"https://img.youtube.com/vi/{vid_id}/mqdefault.jpg"
            }]
        })

    # Record search event for keyword/topic query
    event_id = record_search_event(
        user_id=user_id,
        session_key=session_key,
        query=raw_query,
        content_id=raw_query,
        content_title=raw_query.title(),
        content_type="Topic Search",
        plan=user_plan
    )

    # Scrape top YouTube video candidates for this query
    results = search_youtube(raw_query, limit=6)
    return jsonify({
        'is_direct_video': False,
        'query': raw_query,
        'event_id': event_id,
        'results': results
    })

@app.route('/api/record-search', methods=['POST'])
def api_record_search():
    data = request.get_json() or {}
    raw_query = data.get('query', '').strip()
    content_id = data.get('content_id', '').strip()
    content_title = data.get('content_title', '').strip()
    content_type = data.get('content_type', 'YouTube Video')

    if not raw_query and not content_id:
        return jsonify({'error': 'No search query or content ID provided'}), 400

    user_id = session.get('user_id')
    session_key = session.get('session_key')

    user = get_user(user_id) if user_id else None
    plan = user.get('plan', 'free') if user else 'anonymous'

    # If YouTube video ID, try fetching real title
    if content_id and (not content_title or content_title == content_id):
        meta = get_video_oembed(content_id)
        if meta and meta.get('title'):
            content_title = meta['title']

    event_id = record_search_event(
        user_id=user_id,
        session_key=session_key,
        query=raw_query or content_id,
        content_id=content_id or raw_query,
        content_title=content_title or raw_query,
        content_type=content_type,
        plan=plan
    )
    return jsonify({'success': True, 'event_id': event_id})

@app.route('/api/history', methods=['GET'])
def api_history():
    user_id = session.get('user_id')
    session_key = session.get('session_key')

    if not user_id and not session_key:
        return jsonify({'total': 0, 'items': [], 'plan_limit': 5, 'summary': {}})

    action = request.args.get('action')
    status = request.args.get('status')
    search_query = request.args.get('q')
    sort_by = request.args.get('sort', 'newest')

    if user_id:
        user = get_user(user_id)
        user_plan = user.get('plan', 'free') if user else 'free'
    else:
        user_plan = 'anonymous'

    plan_limit = get_plan_history_limit(user_plan)
    req_limit = int(request.args.get('limit', plan_limit if plan_limit > 0 else 50))
    limit = min(req_limit, plan_limit) if plan_limit > 0 else req_limit
    offset = int(request.args.get('offset', 0))

    history = get_user_history(
        user_id=user_id,
        session_key=session_key,
        action=action,
        status=status,
        search_query=search_query,
        sort_by=sort_by,
        limit=limit,
        offset=offset,
        plan_limit=plan_limit
    )
    history['plan'] = user_plan
    history['plan_limit'] = plan_limit
    return jsonify(history)

@app.route('/api/payment/plans')
def api_payment_plans():
    return jsonify({'plans': PLAN_CONFIG})

@app.route('/api/payment/verify', methods=['POST'])
def api_payment_verify():
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({'success': False, 'error': 'You must be logged in to upgrade.'}), 401

    data = request.get_json() or {}
    plan = data.get('plan')
    payment_id = data.get('payment_id') or f"PAY-{secrets.token_hex(6).upper()}"
    order_id = data.get('order_id') or f"ORD-{secrets.token_hex(4).upper()}"
    provider = data.get('provider', 'razorpay')

    if plan not in PLAN_CONFIG or plan in ['anonymous', 'free']:
        return jsonify({'success': False, 'error': 'Invalid plan selected'}), 400

    cfg = PLAN_CONFIG[plan]
    amount = cfg['price']
    quota_limit = cfg['quota']

    # Record in payments table
    record_payment(
        user_id=user_id,
        payment_id=payment_id,
        order_id=order_id,
        amount=amount,
        currency='INR',
        plan=plan,
        status='verified',
        provider=provider
    )

    # Update user's plan and quota
    update_user_plan(user_id, plan, quota_limit)

    return jsonify({
        'success': True,
        'message': f"Successfully upgraded to {cfg['name']}!",
        'plan': plan,
        'amount': amount,
        'payment_id': payment_id
    })

@app.route('/api/payment/webhook', methods=['POST'])
def api_payment_webhook():
    """Server-to-server webhook endpoint for payment confirmation from Razorpay/Stripe."""
    payload = request.get_json(silent=True) or {}
    payment_entity = payload.get('payload', {}).get('payment', {}).get('entity', {}) or payload.get('data', {}).get('object', {})
    user_id = payment_entity.get('notes', {}).get('user_id') or payment_entity.get('metadata', {}).get('user_id') or session.get('user_id')
    plan = payment_entity.get('notes', {}).get('plan') or payment_entity.get('metadata', {}).get('plan') or 'pack10'
    payment_id = payment_entity.get('id', f"PAY-WH-{secrets.token_hex(4).upper()}")
    provider = payload.get('provider') or ('stripe' if 'data' in payload else 'razorpay')

    if user_id and plan in PLAN_CONFIG:
        cfg = PLAN_CONFIG[plan]
        record_payment(
            user_id=user_id,
            payment_id=payment_id,
            order_id=f"ORD-WH-{secrets.token_hex(4).upper()}",
            amount=cfg['price'],
            currency='INR',
            plan=plan,
            status='verified',
            provider=provider
        )
        update_user_plan(user_id, plan, cfg['quota'])
        return jsonify({'success': True, 'user_id': user_id, 'plan': plan})

    return jsonify({'success': False, 'message': 'Webhook acknowledged without plan update'}), 200

@app.route('/api/analyze', methods=['POST'])
def api_analyze():
    data = request.get_json()
    if not data or "url" not in data:
        return jsonify({"error": "No URL provided"}), 400

    raw_url = data.get("url", "").strip()
    video_id = extract_video_id(raw_url)
    if not video_id:
        return jsonify({"error": "Invalid YouTube URL"}), 400
        
    user_id = session.get('user_id')
    session_key = session.get('session_key')
    
    quota = check_quota(user_id=user_id, session_key=session_key)
    if not quota['allowed']:
        return jsonify({"error": "Quota exceeded", "quota_info": quota}), 402
        
    key_pool = get_key_pool()
    if not key_pool:
         return jsonify({"error": "Gemini API keys not configured"}), 500

    user = get_user(user_id) if user_id else None
    user_plan = user.get('plan', 'free') if user else 'anonymous'

    # Fetch official video title so search event has the real title immediately
    meta = get_video_oembed(video_id)
    video_title = meta.get('title') or f"YouTube Video ({video_id})"

    # Record search event immediately
    record_search_event(
        user_id=user_id,
        session_key=session_key,
        query=raw_url,
        content_id=video_id,
        content_title=video_title,
        content_type="YouTube Video",
        plan=user_plan
    )

    job_id = create_job()
    start_job(job_id, video_id=video_id, user_id=user_id, session_key=session_key, key_pool=key_pool)
    
    return jsonify({"job_id": job_id})

@app.route('/api/job/<job_id>')
def api_job(job_id):
    job = get_job(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404
    return jsonify(job)

@app.route('/api/analysis/<video_id>')
def api_get_analysis(video_id):
    analysis = get_analysis(video_id)
    if not analysis:
        return jsonify({"error": "Analysis not found for this video"}), 404
    return jsonify(analysis)

@app.route('/api/redeem', methods=['POST'])
def api_redeem():
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({"success": False, "message": "You must be logged in to redeem a code."}), 401
        
    data = request.get_json()
    code = data.get('code', '')
    if not code:
         return jsonify({"success": False, "message": "No code provided"}), 400
         
    res = redeem_code(code, user_id)
    return jsonify(res)

@app.route("/api/chat", methods=["POST"])
def chat():
    user_id = session.get('user_id')
    session_key = session.get('session_key')
    quota = check_quota(user_id=user_id, session_key=session_key)
    if not quota['allowed']:
        return jsonify({"error": "Quota limit reached. Please sign in or upgrade your plan."}), 402

    data = request.get_json()
    if not data or "question" not in data:
        return jsonify({"error": "No question provided"}), 400

    question = data["question"].strip()
    client_summary = data.get("summary", "")
    client_title = data.get("title", "")
    client_snippets = data.get("snippets", [])
    
    transcript_sample = prepare_transcript_for_analysis(client_snippets, max_chars=120000) if client_snippets else client_summary
    
    copilot_prompt = f"""You are VideoLens Copilot, a world-class AI video researcher and investigative analyst with photographic recall of this entire video.
VIDEO TITLE: {client_title}
FULL TIMESTAMPED TRANSCRIPT:
\"\"\"
{transcript_sample}
\"\"\"
USER QUESTION:
{question}
CRITICAL INSTRUCTIONS: Answer based strictly on the transcript. Quote exact timestamps [MM:SS]."""

    try:
        key_pool = get_key_pool()
        res = call_gemini_with_fallback(copilot_prompt, key_pool=key_pool)
        return jsonify({"answer": res.text.strip()})
    except Exception as e:
        return jsonify({"error": f"Copilot error: {str(e)}"}), 500

@app.route("/api/compare", methods=["POST"])
def compare():
    data = request.get_json()
    if not data or "video_a" not in data or "video_b" not in data:
        return jsonify({"error": "No comparison data provided"}), 400

    title_a = data["video_a"].get("title", "Video A")
    title_b = data["video_b"].get("title", "Video B")
    summary_a = data["video_a"].get("video_overview", {}).get("summary", "")
    summary_b = data["video_b"].get("video_overview", {}).get("summary", "")
    
    prompt = f"""Compare these two videos: A: {title_a}, Summary A: {summary_a}, B: {title_b}, Summary B: {summary_b}. Return JSON with "title_a", "title_b", "comparison_matrix", "common_themes", "key_disagreements", "synthesis_verdict"."""
    try:
        key_pool = get_key_pool()
        res = call_gemini_with_fallback(prompt, response_mime_type="application/json", key_pool=key_pool)
        result = safe_json_parse(res.text)
        return jsonify(sanitize_data_strings(result))
    except Exception as e:
        return jsonify({"error": f"Comparison error: {str(e)}"}), 500

@app.route("/api/export-pdf", methods=["POST"])
def export_pdf():
    try:
        user_id = session.get('user_id')
        session_key = session.get('session_key')
        quota = check_quota(user_id=user_id, session_key=session_key)
        if not quota['allowed'] and not user_id:
            return jsonify({"error": "Export requires active quota or an authenticated account. Please sign in or upgrade."}), 402

        data = request.get_json()
        if not data:
            return jsonify({"error": "No data provided"}), 400

        pdf_buf = generate_detailed_pdf(data)
        meta = data.get("_meta", {})
        video_id = meta.get("video_id", "analysis")
        import re
        title_slug = re.sub(r'[^a-zA-Z0-9_-]', '_', meta.get("title", video_id))[:30]
        filename = f"VideoLens_{title_slug}_Report.pdf"

        return send_file(
            pdf_buf,
            mimetype="application/pdf",
            as_attachment=True,
            download_name=filename
        )
    except Exception as e:
        return jsonify({"error": f"Failed to generate PDF: {str(e)}"}), 500

@app.route("/api/usage-stats", methods=["GET"])
def usage_stats():
    # Return simple stats from DB
    return jsonify(get_stats())

def find_available_port(preferred_port=5000):
    import socket
    for port in [preferred_port, 5500, 5050, 8080]:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(('0.0.0.0', port))
                return port
            except OSError:
                continue
    return preferred_port

if __name__ == '__main__':
    port = int(os.getenv('PORT', find_available_port(5000)))
    print(f"\n==========================================================")
    print(f" VideoLens v2 — AI YouTube Video Intelligence Platform")
    print(f" Local: http://localhost:{port}")
    print(f"==========================================================")
    serve(app, host='0.0.0.0', port=port, threads=4)
