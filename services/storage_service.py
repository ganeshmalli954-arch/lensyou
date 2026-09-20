import os
import sqlite3
import json
import uuid
import secrets
import string
from collections import OrderedDict
from datetime import datetime, date

def resolve_database_path() -> str:
    env_path = os.getenv('DATABASE_PATH')
    if env_path:
        return env_path
    if os.path.exists('/var/data'):
        if os.path.exists('/var/data/lensyou.db'):
            return '/var/data/lensyou.db'
        if os.path.exists('/var/data/videolens.db'):
            return '/var/data/videolens.db'
        return '/var/data/lensyou.db'
    return os.path.join(os.path.dirname(__file__), '..', 'data', 'videolens.db')

DB_PATH = resolve_database_path()

class BoundedCache(OrderedDict):
    def __init__(self, maxsize=20, *args, **kwargs):
        self.maxsize = maxsize
        super().__init__(*args, **kwargs)

    def __getitem__(self, key):
        value = super().__getitem__(key)
        self.move_to_end(key)
        return value

    def __setitem__(self, key, value):
        super().__setitem__(key, value)
        if len(self) > self.maxsize:
            oldest = next(iter(self))
            del self[oldest]

CACHE = BoundedCache(20)

def get_db():
    db_path = resolve_database_path()
    parent_dir = os.path.dirname(db_path)
    if parent_dir:
        os.makedirs(parent_dir, exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=10.0)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    with get_db() as conn:
        c = conn.cursor()
        c.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                provider TEXT,
                provider_id TEXT,
                email TEXT,
                name TEXT,
                avatar_url TEXT,
                plan TEXT,
                quota_used INTEGER DEFAULT 0,
                quota_limit INTEGER DEFAULT 5,
                created_at TEXT,
                last_active TEXT,
                UNIQUE(provider, provider_id)
            )
        ''')
        c.execute('''
            CREATE TABLE IF NOT EXISTS anon_sessions (
                session_key TEXT PRIMARY KEY,
                quota_used INTEGER DEFAULT 0,
                created_at TEXT
            )
        ''')
        c.execute('''
            CREATE TABLE IF NOT EXISTS videos (
                id TEXT PRIMARY KEY,
                video_id TEXT,
                title TEXT,
                author TEXT,
                duration TEXT,
                analysis_json TEXT,
                user_id TEXT,
                session_key TEXT,
                created_at TEXT
            )
        ''')
        c.execute('''
            CREATE TABLE IF NOT EXISTS redemption_codes (
                code TEXT PRIMARY KEY,
                plan TEXT,
                quota_grant INTEGER,
                used BOOLEAN DEFAULT 0,
                used_by TEXT,
                used_at TEXT,
                created_at TEXT
            )
        ''')
        c.execute('''
            CREATE TABLE IF NOT EXISTS api_key_stats (
                key_index INTEGER PRIMARY KEY,
                key_prefix TEXT,
                requests_today INTEGER DEFAULT 0,
                tokens_used_today INTEGER DEFAULT 0,
                last_error TEXT,
                last_used TEXT,
                status TEXT
            )
        ''')
        c.execute('''
            CREATE TABLE IF NOT EXISTS app_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                level TEXT,
                message TEXT,
                source TEXT,
                created_at TEXT
            )
        ''')
        c.execute('''
            CREATE TABLE IF NOT EXISTS user_activity_history (
                id TEXT PRIMARY KEY,
                user_id TEXT,
                session_key TEXT,
                content_id TEXT,
                content_title TEXT,
                content_type TEXT DEFAULT 'YouTube Video',
                action TEXT,
                status TEXT,
                query TEXT,
                plan_at_time TEXT,
                usage_amount INTEGER DEFAULT 1,
                duration TEXT,
                model_used TEXT,
                error_info TEXT,
                created_at TEXT
            )
        ''')
        c.execute('CREATE INDEX IF NOT EXISTS idx_uah_user ON user_activity_history(user_id)')
        c.execute('CREATE INDEX IF NOT EXISTS idx_uah_content ON user_activity_history(content_id)')
        c.execute('CREATE INDEX IF NOT EXISTS idx_uah_action ON user_activity_history(action)')
        c.execute('CREATE INDEX IF NOT EXISTS idx_uah_created ON user_activity_history(created_at)')
        c.execute('CREATE INDEX IF NOT EXISTS idx_videos_video_id ON videos(video_id)')

        c.execute('''
            CREATE TABLE IF NOT EXISTS payments (
                id TEXT PRIMARY KEY,
                user_id TEXT,
                payment_id TEXT,
                order_id TEXT,
                amount INTEGER,
                currency TEXT DEFAULT 'INR',
                plan TEXT,
                status TEXT,
                provider TEXT,
                created_at TEXT
            )
        ''')
        c.execute('CREATE INDEX IF NOT EXISTS idx_payments_user ON payments(user_id)')
        c.execute('CREATE INDEX IF NOT EXISTS idx_payments_created ON payments(created_at)')

        c.execute('''
            CREATE TABLE IF NOT EXISTS system_settings (
                key TEXT PRIMARY KEY,
                value TEXT,
                updated_at TEXT
            )
        ''')

        c.execute('''
            CREATE TABLE IF NOT EXISTS notifications (
                id TEXT PRIMARY KEY,
                user_id TEXT,
                title TEXT,
                message TEXT,
                link TEXT,
                type TEXT,
                created_at TEXT,
                is_read INTEGER DEFAULT 0
            )
        ''')
        c.execute('CREATE INDEX IF NOT EXISTS idx_notif_user ON notifications(user_id)')
        c.execute('CREATE INDEX IF NOT EXISTS idx_notif_created ON notifications(created_at)')

        conn.commit()
        # Migrations: add columns if missing
        try:
            c.execute('ALTER TABLE users ADD COLUMN login_count INTEGER DEFAULT 0')
            conn.commit()
        except Exception:
            pass  # Column already exists
        try:
            c.execute("ALTER TABLE users ADD COLUMN role TEXT DEFAULT 'user'")
            conn.commit()
        except Exception:
            pass  # Column already exists

        # Backfill user_activity_history from videos if empty
        try:
            c.execute('SELECT COUNT(*) as count FROM user_activity_history')
            if c.fetchone()['count'] == 0:
                c.execute('SELECT id, video_id, title, duration, user_id, session_key, created_at FROM videos')
                rows = c.fetchall()
                for r in rows:
                    act_id = str(uuid.uuid4())
                    c.execute('''
                        INSERT INTO user_activity_history (id, user_id, session_key, content_id, content_title, content_type, action, status, query, plan_at_time, duration, created_at)
                        VALUES (?, ?, ?, ?, ?, 'YouTube Video', 'process', 'success', ?, 'free', ?, ?)
                    ''', (act_id, r['user_id'], r['session_key'], r['video_id'], r['title'] or r['video_id'], r['video_id'], r['duration'], r['created_at']))
                conn.commit()
        except Exception as e:
            print(f"Backfill notice: {e}")

def log_event(level, message, source='app'):
    with get_db() as conn:
        c = conn.cursor()
        c.execute('INSERT INTO app_logs (level, message, source, created_at) VALUES (?, ?, ?, ?)',
                  (level, message, source, datetime.utcnow().isoformat()))
        conn.commit()

def get_logs(limit=200) -> list:
    with get_db() as conn:
        c = conn.cursor()
        c.execute('SELECT * FROM app_logs ORDER BY created_at DESC LIMIT ?', (limit,))
        return [dict(row) for row in c.fetchall()]

def save_cached_analysis(video_id: str, title: str, author: str, duration: str, analysis: dict, user_id: str = None, session_key: str = None) -> str:
    """Save completed video analysis to SQLite database for instant caching and public sharing."""
    if not video_id or not analysis:
        return ""
    CACHE[video_id] = analysis
    record_id = str(uuid.uuid4())
    now_str = datetime.utcnow().isoformat()
    try:
        raw_json = json.dumps(analysis)
        with get_db() as conn:
            c = conn.cursor()
            c.execute('SELECT id FROM videos WHERE video_id = ?', (video_id,))
            existing = c.fetchone()
            if existing:
                c.execute('''
                    UPDATE videos 
                    SET title = ?, author = ?, duration = ?, analysis_json = ?, 
                        user_id = COALESCE(?, user_id), session_key = COALESCE(?, session_key), created_at = ?
                    WHERE video_id = ?
                ''', (title, author, duration, raw_json, user_id, session_key, now_str, video_id))
            else:
                c.execute('''
                    INSERT INTO videos (id, video_id, title, author, duration, analysis_json, user_id, session_key, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (record_id, video_id, title, author, duration, raw_json, user_id, session_key, now_str))
            conn.commit()
            return existing['id'] if existing else record_id
    except Exception as e:
        print(f"  [Cache Save Error]: {e}", flush=True)
        return ""

save_analysis = save_cached_analysis

def get_cached_analysis(video_id: str) -> dict | None:
    """Retrieve cached analysis JSON from memory or SQLite database. Zero network calls or Gemini API tokens needed."""
    if not video_id:
        return None
    if video_id in CACHE:
        return CACHE[video_id]
    try:
        with get_db() as conn:
            c = conn.cursor()
            c.execute('SELECT analysis_json FROM videos WHERE video_id = ? ORDER BY created_at DESC LIMIT 1', (video_id,))
            row = c.fetchone()
            if row and row['analysis_json']:
                data = json.loads(row['analysis_json'])
                CACHE[video_id] = data
                return data
    except Exception as e:
        print(f"  [Cache Retrieval Error]: {e}", flush=True)
    return None

get_analysis = get_cached_analysis

def get_recent_videos(limit=100) -> list:
    """Retrieve list of recently analyzed videos for admin portal and caching overview."""
    with get_db() as conn:
        c = conn.cursor()
        c.execute('SELECT id, video_id, title, author, duration, user_id, created_at FROM videos ORDER BY created_at DESC LIMIT ?', (limit,))
        return [dict(row) for row in c.fetchall()]

def get_all_videos(limit=100) -> list:
    return get_recent_videos(limit)

def get_user(user_id) -> dict:
    with get_db() as conn:
        c = conn.cursor()
        c.execute('SELECT * FROM users WHERE id = ?', (user_id,))
        row = c.fetchone()
        return dict(row) if row else None

def get_user_by_provider(provider, provider_id, email=None, name=None, avatar_url=None) -> dict:
    owner_emails = [e.strip().lower() for e in os.getenv('OWNER_EMAIL', 'ganeshmalli954@gmail.com').split(',') if e.strip()]
    is_admin_owner = bool(email and email.strip().lower() in owner_emails)
    with get_db() as conn:
        c = conn.cursor()
        c.execute('SELECT * FROM users WHERE provider = ? AND provider_id = ?', (provider, provider_id))
        row = c.fetchone()
        if row:
            user_id = dict(row)['id']
            now = datetime.utcnow().isoformat()
            plan_clause = ", plan = 'unlimited', quota_limit = -1, role = 'admin'" if is_admin_owner else ""
            c.execute(f'''
                UPDATE users 
                SET last_active = ?, 
                    login_count = COALESCE(login_count, 0) + 1,
                    email = COALESCE(NULLIF(?, ''), email),
                    name = COALESCE(NULLIF(?, ''), name),
                    avatar_url = COALESCE(NULLIF(?, ''), avatar_url)
                    {plan_clause}
                WHERE id = ?
            ''', (now, email, name, avatar_url, user_id))
            conn.commit()
            c.execute('SELECT * FROM users WHERE id = ?', (user_id,))
            updated_row = c.fetchone()
            return dict(updated_row) if updated_row else dict(row)
        return None

def create_user(provider, provider_id, email, name, avatar_url) -> str:
    user_id = str(uuid.uuid4())
    now = datetime.utcnow().isoformat()
    owner_emails = [e.strip().lower() for e in os.getenv('OWNER_EMAIL', 'ganeshmalli954@gmail.com').split(',') if e.strip()]
    is_admin_owner = bool(email and email.strip().lower() in owner_emails)
    plan = 'unlimited' if is_admin_owner else 'free'
    quota_limit = -1 if is_admin_owner else 5
    role = 'admin' if is_admin_owner else 'user'
    with get_db() as conn:
        c = conn.cursor()
        c.execute('''
            INSERT INTO users (id, provider, provider_id, email, name, avatar_url, plan, quota_used, quota_limit, role, created_at, last_active, login_count)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
        ''', (user_id, provider, provider_id, email, name, avatar_url, plan, 0, quota_limit, role, now, now))
        conn.commit()
    return user_id

def update_user_quota(user_id, increment=1):
    with get_db() as conn:
        c = conn.cursor()
        c.execute('UPDATE users SET quota_used = quota_used + ? WHERE id = ?', (increment, user_id))
        conn.commit()

def update_user_plan(user_id, plan, quota_limit):
    with get_db() as conn:
        c = conn.cursor()
        c.execute('UPDATE users SET plan = ?, quota_limit = ? WHERE id = ?', (plan, quota_limit, user_id))
        conn.commit()

def get_anon_session(session_key) -> dict:
    with get_db() as conn:
        c = conn.cursor()
        c.execute('SELECT * FROM anon_sessions WHERE session_key = ?', (session_key,))
        row = c.fetchone()
        if row:
            return dict(row)
        c.execute('INSERT INTO anon_sessions (session_key, quota_used, created_at) VALUES (?, 0, ?)', (session_key, datetime.utcnow().isoformat()))
        conn.commit()
        return {'session_key': session_key, 'quota_used': 0, 'created_at': datetime.utcnow().isoformat()}

def increment_anon_quota(session_key):
    with get_db() as conn:
        c = conn.cursor()
        c.execute('UPDATE anon_sessions SET quota_used = quota_used + 1 WHERE session_key = ?', (session_key,))
        conn.commit()

def get_redemption_code(code) -> dict:
    with get_db() as conn:
        c = conn.cursor()
        c.execute('SELECT * FROM redemption_codes WHERE code = ?', (code,))
        row = c.fetchone()
        return dict(row) if row else None

def mark_code_used(code, user_id):
    with get_db() as conn:
        c = conn.cursor()
        c.execute('UPDATE redemption_codes SET used = 1, used_by = ?, used_at = ? WHERE code = ?',
                  (user_id, datetime.utcnow().isoformat(), code))
        conn.commit()

def create_redemption_code(plan, quota_grant) -> str:
    code = ''.join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(12))
    with get_db() as conn:
        c = conn.cursor()
        c.execute('''
            INSERT INTO redemption_codes (code, plan, quota_grant, created_at)
            VALUES (?, ?, ?, ?)
        ''', (code, plan, quota_grant, datetime.utcnow().isoformat()))
        conn.commit()
    return code

def get_all_codes(limit=100) -> list:
    with get_db() as conn:
        c = conn.cursor()
        c.execute('SELECT * FROM redemption_codes ORDER BY created_at DESC LIMIT ?', (limit,))
        return [dict(row) for row in c.fetchall()]

def get_all_users(limit=100) -> list:
    with get_db() as conn:
        c = conn.cursor()
        c.execute('SELECT * FROM users ORDER BY created_at DESC LIMIT ?', (limit,))
        return [dict(row) for row in c.fetchall()]

def get_stats() -> dict:
    from datetime import timedelta
    with get_db() as conn:
        c = conn.cursor()
        c.execute('SELECT COUNT(*) as count FROM users')
        total_users = c.fetchone()['count']
        
        c.execute('SELECT COUNT(*) as count FROM videos')
        total_videos = c.fetchone()['count']
        
        today_utc = datetime.utcnow().strftime('%Y-%m-%d')
        c.execute("SELECT COUNT(*) as count FROM videos WHERE created_at LIKE ?", (f"{today_utc}%",))
        today_videos = c.fetchone()['count']
        
        c.execute("SELECT COUNT(*) as count FROM users WHERE created_at LIKE ?", (f"{today_utc}%",))
        today_users = c.fetchone()['count']
        
        # Weekly (last 7 days)
        week_start = (datetime.utcnow() - timedelta(days=7)).strftime('%Y-%m-%d')
        c.execute("SELECT COUNT(*) as count FROM users WHERE created_at >= ?", (week_start,))
        week_users = c.fetchone()['count']
        c.execute("SELECT COUNT(*) as count FROM videos WHERE created_at >= ?", (week_start,))
        week_videos = c.fetchone()['count']
        
        # Monthly (last 30 days)
        month_start = (datetime.utcnow() - timedelta(days=30)).strftime('%Y-%m-%d')
        c.execute("SELECT COUNT(*) as count FROM users WHERE created_at >= ?", (month_start,))
        month_users = c.fetchone()['count']
        c.execute("SELECT COUNT(*) as count FROM videos WHERE created_at >= ?", (month_start,))
        month_videos = c.fetchone()['count']
        
        # Plan breakdown
        c.execute("SELECT plan, COUNT(*) as count FROM users GROUP BY plan")
        plan_rows = c.fetchall()
        plan_breakdown = {row['plan']: row['count'] for row in plan_rows}
        
        # Active users (last_active in last 7 days)
        c.execute("SELECT COUNT(*) as count FROM users WHERE last_active >= ?", (week_start,))
        active_users_week = c.fetchone()['count']
        
        # Code redemptions
        c.execute("SELECT COUNT(*) as count FROM redemption_codes WHERE used = 1")
        total_redemptions = c.fetchone()['count']
        
        # Total logins
        c.execute('SELECT COALESCE(SUM(login_count), 0) as total_logins FROM users')
        total_logins = c.fetchone()['total_logins']
        
        # Search & Processing stats
        c.execute("SELECT COUNT(*) as count FROM user_activity_history WHERE action = 'search'")
        total_searches = c.fetchone()['count']
        
        c.execute("SELECT COUNT(DISTINCT content_id) as count FROM user_activity_history WHERE action = 'search'")
        unique_search_content = c.fetchone()['count']

        c.execute("SELECT COUNT(DISTINCT COALESCE(user_id, session_key)) as count FROM user_activity_history WHERE action = 'search'")
        unique_searchers = c.fetchone()['count']

        c.execute("SELECT COUNT(*) as count FROM user_activity_history WHERE action = 'process'")
        total_processing = c.fetchone()['count']

        c.execute("SELECT COUNT(*) as count FROM user_activity_history WHERE action = 'process' AND status = 'success'")
        processing_success = c.fetchone()['count']

        c.execute("SELECT COUNT(*) as count FROM user_activity_history WHERE action = 'process' AND status = 'failed'")
        processing_failed = c.fetchone()['count']

        c.execute("SELECT COUNT(*) as count FROM users WHERE provider = 'google'")
        google_users = c.fetchone()['count']

        c.execute("SELECT COALESCE(SUM(amount), 0) as revenue FROM payments WHERE status = 'verified'")
        verified_revenue = c.fetchone()['revenue']

        c.execute("SELECT COUNT(DISTINCT user_id) as count FROM payments WHERE status = 'verified'")
        paying_users = c.fetchone()['count']
        
        return {
            'total_users': total_users,
            'google_users': google_users,
            'total_videos': total_videos,
            'today_videos': today_videos,
            'today_users': today_users,
            'week_users': week_users,
            'week_videos': week_videos,
            'month_users': month_users,
            'month_videos': month_videos,
            'plan_breakdown': plan_breakdown,
            'active_users_week': active_users_week,
            'total_redemptions': total_redemptions,
            'total_logins': total_logins,
            'total_searches': total_searches,
            'unique_search_content': unique_search_content,
            'unique_searchers': unique_searchers,
            'total_processing': total_processing,
            'processing_success': processing_success,
            'processing_failed': processing_failed,
            'verified_revenue': verified_revenue,
            'paying_users': paying_users
        }

def get_login_stats() -> dict:
    with get_db() as conn:
        c = conn.cursor()
        c.execute('SELECT SUM(COALESCE(login_count, 0)) as total_logins FROM users')
        row = c.fetchone()
        total_logins = row['total_logins'] or 0
        return {'total_logins': total_logins}

def update_api_key_stat(key_index, key_prefix, increment_requests=1, increment_tokens=0, error=None):
    with get_db() as conn:
        c = conn.cursor()
        c.execute('SELECT * FROM api_key_stats WHERE key_index = ?', (key_index,))
        row = c.fetchone()
        now = datetime.utcnow().isoformat()
        status = 'error' if error else 'active'
        
        # Reset if it's a new day
        reset = False
        if row:
            last_used = row['last_used']
            if last_used and last_used[:10] != now[:10]:
                reset = True
                
        if not row:
            c.execute('''
                INSERT INTO api_key_stats (key_index, key_prefix, requests_today, tokens_used_today, last_error, last_used, status)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (key_index, key_prefix, increment_requests, increment_tokens, error, now, status))
        else:
            reqs = increment_requests if reset else row['requests_today'] + increment_requests
            toks = increment_tokens if reset else row['tokens_used_today'] + increment_tokens
            c.execute('''
                UPDATE api_key_stats 
                SET requests_today = ?, tokens_used_today = ?, last_error = ?, last_used = ?, status = ?
                WHERE key_index = ?
            ''', (reqs, toks, error, now, status, key_index))
        conn.commit()

def get_api_key_stats() -> list:
    with get_db() as conn:
        c = conn.cursor()
        c.execute('SELECT * FROM api_key_stats ORDER BY key_index ASC')
        return [dict(row) for row in c.fetchall()]

# --- User Activity History (Searches & Processing) ---

def record_search_event(user_id=None, session_key=None, query="", content_id="", content_title="", content_type="YouTube Video", plan="free") -> str:
    event_id = str(uuid.uuid4())
    now = datetime.utcnow().isoformat()
    with get_db() as conn:
        c = conn.cursor()
        c.execute('''
            INSERT INTO user_activity_history (id, user_id, session_key, content_id, content_title, content_type, action, status, query, plan_at_time, created_at)
            VALUES (?, ?, ?, ?, ?, ?, 'search', 'completed', ?, ?, ?)
        ''', (event_id, user_id, session_key, content_id, content_title or content_id or query, content_type, query, plan, now))
        conn.commit()
    return event_id

def update_search_event_content(event_id: str, content_id=None, content_title=None):
    with get_db() as conn:
        c = conn.cursor()
        c.execute('''
            UPDATE user_activity_history
            SET content_id = COALESCE(?, content_id),
                content_title = COALESCE(?, content_title)
            WHERE id = ?
        ''', (content_id, content_title, event_id))
        conn.commit()

def update_search_events_for_content(content_id: str, content_title: str):
    if not content_id or not content_title:
        return
    with get_db() as conn:
        c = conn.cursor()
        c.execute('''
            UPDATE user_activity_history
            SET content_title = ?
            WHERE content_id = ? AND (content_title LIKE 'YouTube Video (%' OR content_title = ? OR content_title = '')
        ''', (content_title, content_id, content_id))
        conn.commit()

def record_processing_event(user_id=None, session_key=None, content_id="", content_title="", content_type="YouTube Video", status="pending", duration=None, model_used=None, plan="free", error_info=None) -> str:
    event_id = str(uuid.uuid4())
    now = datetime.utcnow().isoformat()
    with get_db() as conn:
        c = conn.cursor()
        c.execute('''
            INSERT INTO user_activity_history (id, user_id, session_key, content_id, content_title, content_type, action, status, query, plan_at_time, duration, model_used, error_info, created_at)
            VALUES (?, ?, ?, ?, ?, ?, 'process', ?, ?, ?, ?, ?, ?, ?)
        ''', (event_id, user_id, session_key, content_id, content_title or content_id, content_type, status, content_id, plan, duration, model_used, error_info, now))
        conn.commit()
    return event_id

def update_processing_event(event_id: str, status: str, error_info=None, duration=None, model_used=None):
    with get_db() as conn:
        c = conn.cursor()
        c.execute('''
            UPDATE user_activity_history
            SET status = ?,
                error_info = COALESCE(?, error_info),
                duration = COALESCE(?, duration),
                model_used = COALESCE(?, model_used)
            WHERE id = ?
        ''', (status, error_info, duration, model_used, event_id))
        conn.commit()

def get_user_history(user_id=None, session_key=None, action=None, status=None, search_query=None, sort_by='newest', limit=50, offset=0, plan_limit=None) -> dict:
    if not user_id and not session_key:
        return {'total': 0, 'items': [], 'limit': limit, 'offset': offset, 'summary': {}}

    with get_db() as conn:
        c = conn.cursor()
        query_parts = []
        params = []

        if user_id:
            query_parts.append("user_id = ?")
            params.append(user_id)
        else:
            query_parts.append("session_key = ? AND (user_id IS NULL OR user_id = '')")
            params.append(session_key)

        if action and action != 'all':
            query_parts.append("action = ?")
            params.append(action)

        if status and status != 'all':
            query_parts.append("status = ?")
            params.append(status)

        if search_query:
            query_parts.append("(content_title LIKE ? OR content_id LIKE ? OR query LIKE ?)")
            wildcard = f"%{search_query}%"
            params.extend([wildcard, wildcard, wildcard])

        where_clause = " WHERE " + " AND ".join(query_parts) if query_parts else ""

        # Order by - strictly scoped to this user/session to avoid leaking global search patterns
        if sort_by == 'oldest':
            order_clause = " ORDER BY created_at ASC"
        elif sort_by == 'most_searched':
            order_clause = " ORDER BY (SELECT COUNT(*) FROM user_activity_history h2 WHERE h2.content_id = user_activity_history.content_id AND COALESCE(h2.user_id, h2.session_key) = COALESCE(user_activity_history.user_id, user_activity_history.session_key) AND h2.action = 'search') DESC, created_at DESC"
        elif sort_by == 'most_processed':
            order_clause = " ORDER BY (SELECT COUNT(*) FROM user_activity_history h2 WHERE h2.content_id = user_activity_history.content_id AND COALESCE(h2.user_id, h2.session_key) = COALESCE(user_activity_history.user_id, user_activity_history.session_key) AND h2.action = 'process') DESC, created_at DESC"
        else:
            order_clause = " ORDER BY created_at DESC"

        # Count total in DB
        count_sql = f"SELECT COUNT(*) as total FROM user_activity_history{where_clause}"
        c.execute(count_sql, params)
        db_total = c.fetchone()['total']

        # Enforce plan limits strictly on pagination: user cannot bypass history retention
        effective_total = db_total
        if plan_limit is not None and plan_limit > 0:
            effective_total = min(db_total, plan_limit)
            if offset >= plan_limit:
                summary = get_user_activity_summary(user_id=user_id, session_key=session_key)
                return {'total': effective_total, 'unlimited_total': db_total, 'items': [], 'limit': limit, 'offset': offset, 'summary': summary}
            if offset + limit > plan_limit:
                limit = max(0, plan_limit - offset)

        # Fetch items
        data_sql = f"SELECT * FROM user_activity_history{where_clause}{order_clause} LIMIT ? OFFSET ?"
        data_params = list(params) + [limit, offset]
        c.execute(data_sql, data_params)
        items = [dict(row) for row in c.fetchall()]

        summary = get_user_activity_summary(user_id=user_id, session_key=session_key)

        return {
            'total': effective_total,
            'unlimited_total': db_total,
            'items': items,
            'limit': limit,
            'offset': offset,
            'summary': summary
        }

def get_user_activity_summary(user_id: str = None, session_key: str = None) -> dict:
    if not user_id and not session_key:
        return {
            'total_searches': 0, 'unique_content': 0, 'total_processing': 0,
            'successful_processing': 0, 'failed_processing': 0, 'last_activity': None
        }

    with get_db() as conn:
        c = conn.cursor()
        if user_id:
            where_user = "user_id = ?"
            param = (user_id,)
        else:
            where_user = "session_key = ? AND (user_id IS NULL OR user_id = '')"
            param = (session_key,)

        c.execute(f"SELECT COUNT(*) as total_searches FROM user_activity_history WHERE {where_user} AND action = 'search'", param)
        total_searches = c.fetchone()['total_searches']

        c.execute(f"SELECT COUNT(DISTINCT content_id) as unique_content FROM user_activity_history WHERE {where_user}", param)
        unique_content = c.fetchone()['unique_content']

        c.execute(f"SELECT COUNT(*) as total_processing FROM user_activity_history WHERE {where_user} AND action = 'process'", param)
        total_processing = c.fetchone()['total_processing']

        c.execute(f"SELECT COUNT(*) as successful_processing FROM user_activity_history WHERE {where_user} AND action = 'process' AND status = 'success'", param)
        successful_processing = c.fetchone()['successful_processing']

        c.execute(f"SELECT COUNT(*) as failed_processing FROM user_activity_history WHERE {where_user} AND action = 'process' AND status = 'failed'", param)
        failed_processing = c.fetchone()['failed_processing']

        c.execute(f"SELECT MAX(created_at) as last_activity FROM user_activity_history WHERE {where_user}", param)
        row = c.fetchone()
        last_activity = row['last_activity'] if row else None

        return {
            'total_searches': total_searches,
            'unique_content': unique_content,
            'total_processing': total_processing,
            'successful_processing': successful_processing,
            'failed_processing': failed_processing,
            'last_activity': last_activity
        }

def get_content_analytics(content_id=None, limit=50):
    with get_db() as conn:
        c = conn.cursor()
        if content_id:
            c.execute('''
                SELECT 
                    content_id,
                    content_title,
                    content_type,
                    COUNT(CASE WHEN action = 'search' THEN 1 END) as total_searches,
                    COUNT(DISTINCT COALESCE(user_id, session_key)) as unique_users,
                    COUNT(DISTINCT CASE WHEN action = 'search' THEN COALESCE(user_id, session_key) END) as unique_searchers,
                    COUNT(CASE WHEN action = 'process' THEN 1 END) as total_processing,
                    COUNT(CASE WHEN action = 'process' AND status = 'success' THEN 1 END) as successful_processing,
                    COUNT(CASE WHEN action = 'process' AND status = 'failed' THEN 1 END) as failed_processing,
                    MIN(created_at) as first_seen,
                    MAX(created_at) as last_seen
                FROM user_activity_history
                WHERE content_id = ?
                GROUP BY content_id
            ''', (content_id,))
            row = c.fetchone()
            if not row:
                return None
            res = dict(row)

            # Get user interactions breakdown
            c.execute('''
                SELECT 
                    COALESCE(u.name, 'Guest') as user_name,
                    COALESCE(u.email, 'Anonymous') as user_email,
                    COALESCE(h.user_id, h.session_key) as account_id,
                    COUNT(CASE WHEN h.action = 'search' THEN 1 END) as search_count,
                    COUNT(CASE WHEN h.action = 'process' THEN 1 END) as process_count,
                    MAX(h.created_at) as last_interacted
                FROM user_activity_history h
                LEFT JOIN users u ON h.user_id = u.id
                WHERE h.content_id = ?
                GROUP BY account_id
                ORDER BY last_interacted DESC
                LIMIT 50
            ''', (content_id,))
            res['users_breakdown'] = [dict(r) for r in c.fetchall()]
            return res
        else:
            c.execute('''
                SELECT 
                    content_id,
                    MAX(content_title) as content_title,
                    MAX(content_type) as content_type,
                    COUNT(CASE WHEN action = 'search' THEN 1 END) as total_searches,
                    COUNT(DISTINCT COALESCE(user_id, session_key)) as unique_users,
                    COUNT(DISTINCT CASE WHEN action = 'search' THEN COALESCE(user_id, session_key) END) as unique_searchers,
                    COUNT(CASE WHEN action = 'process' THEN 1 END) as total_processing,
                    COUNT(CASE WHEN action = 'process' AND status = 'success' THEN 1 END) as successful_processing,
                    COUNT(CASE WHEN action = 'process' AND status = 'failed' THEN 1 END) as failed_processing,
                    MAX(created_at) as last_activity
                FROM user_activity_history
                GROUP BY content_id
                ORDER BY (total_searches + total_processing) DESC
                LIMIT ?
            ''', (limit,))
            return [dict(row) for row in c.fetchall()]

def get_search_analytics(limit=20) -> dict:
    from datetime import date, timedelta
    with get_db() as conn:
        c = conn.cursor()
        c.execute("SELECT COUNT(*) as total FROM user_activity_history WHERE action = 'search'")
        total_searches = c.fetchone()['total']

        c.execute("SELECT COUNT(DISTINCT COALESCE(user_id, session_key)) as unique_searchers FROM user_activity_history WHERE action = 'search'")
        unique_searchers = c.fetchone()['unique_searchers']

        today = date.today().isoformat()
        c.execute("SELECT COUNT(*) as today FROM user_activity_history WHERE action = 'search' AND created_at LIKE ?", (f"{today}%",))
        searches_today = c.fetchone()['today']

        week_start = (date.today() - timedelta(days=7)).isoformat()
        c.execute("SELECT COUNT(*) as week FROM user_activity_history WHERE action = 'search' AND created_at >= ?", (week_start,))
        searches_week = c.fetchone()['week']

        month_start = (date.today() - timedelta(days=30)).isoformat()
        c.execute("SELECT COUNT(*) as month FROM user_activity_history WHERE action = 'search' AND created_at >= ?", (month_start,))
        searches_month = c.fetchone()['month']

        # Most searched content
        c.execute('''
            SELECT 
                content_id,
                MAX(content_title) as content_title,
                COUNT(*) as search_count,
                COUNT(DISTINCT COALESCE(user_id, session_key)) as unique_searchers,
                MAX(created_at) as last_searched
            FROM user_activity_history
            WHERE action = 'search'
            GROUP BY content_id
            ORDER BY search_count DESC
            LIMIT ?
        ''', (limit,))
        most_searched = [dict(r) for r in c.fetchall()]

        # Recent searches
        c.execute('''
            SELECT 
                h.id,
                h.content_id,
                h.content_title,
                h.query,
                h.created_at,
                COALESCE(u.name, 'Guest') as user_name,
                COALESCE(u.email, 'Anonymous') as user_email
            FROM user_activity_history h
            LEFT JOIN users u ON h.user_id = u.id
            WHERE h.action = 'search'
            ORDER BY h.created_at DESC
            LIMIT 25
        ''')
        recent_searches = [dict(r) for r in c.fetchall()]

        return {
            'total_searches': total_searches,
            'unique_searchers': unique_searchers,
            'searches_today': searches_today,
            'searches_week': searches_week,
            'searches_month': searches_month,
            'most_searched': most_searched,
            'recent_searches': recent_searches
        }

# --- Payments & Subscriptions ---

def record_payment(user_id, payment_id, order_id, amount, currency='INR', plan='pack10', status='verified', provider='razorpay') -> str:
    pay_id = str(uuid.uuid4())
    now = datetime.utcnow().isoformat()
    with get_db() as conn:
        c = conn.cursor()
        c.execute('''
            INSERT INTO payments (id, user_id, payment_id, order_id, amount, currency, plan, status, provider, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (pay_id, user_id, payment_id, order_id, amount, currency, plan, status, provider, now))
        conn.commit()
    log_event('INFO', f"Payment recorded: {currency} {amount} for plan {plan} by user {user_id}", source='payment')
    return pay_id

def get_all_payments(limit=100) -> list:
    with get_db() as conn:
        c = conn.cursor()
        c.execute('''
            SELECT p.*, COALESCE(u.name, 'Unknown') as user_name, COALESCE(u.email, 'Unknown') as user_email
            FROM payments p
            LEFT JOIN users u ON p.user_id = u.id
            ORDER BY p.created_at DESC
            LIMIT ?
        ''', (limit,))
        return [dict(row) for row in c.fetchall()]

def get_payment_stats() -> dict:
    with get_db() as conn:
        c = conn.cursor()
        c.execute("SELECT COUNT(*) as count, COALESCE(SUM(amount), 0) as total_rev FROM payments WHERE status = 'verified'")
        row = c.fetchone()
        verified_count = row['count']
        total_revenue = row['total_rev']

        c.execute("SELECT COUNT(DISTINCT user_id) as count FROM payments WHERE status = 'verified'")
        paying_users = c.fetchone()['count']

        c.execute("SELECT plan, COUNT(*) as count, SUM(amount) as revenue FROM payments WHERE status = 'verified' GROUP BY plan")
        plan_rows = [dict(r) for r in c.fetchall()]

        return {
            'verified_count': verified_count,
            'total_revenue': total_revenue,
            'paying_users': paying_users,
            'plans': plan_rows
        }

def get_system_setting(key: str, default=None) -> str:
    """Retrieve a persistent system configuration setting from SQLite."""
    try:
        with get_db() as conn:
            c = conn.cursor()
            c.execute("SELECT value FROM system_settings WHERE key = ?", (key,))
            row = c.fetchone()
            return row['value'] if row else default
    except Exception:
        return default

def set_system_setting(key: str, value: str):
    """Store or update a persistent system configuration setting in SQLite."""
    now = datetime.utcnow().isoformat()
    with get_db() as conn:
        c = conn.cursor()
        c.execute("""
            INSERT INTO system_settings (key, value, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
        """, (key, str(value), now))
        conn.commit()


def create_notification(user_id: str, title: str, message: str, link: str = None, notif_type: str = 'retention') -> str:
    """Create a persistent in-app notification for a user."""
    notif_id = f"notif_{uuid.uuid4().hex[:12]}"
    now = datetime.utcnow().isoformat()
    with get_db() as conn:
        c = conn.cursor()
        c.execute("""
            INSERT INTO notifications (id, user_id, title, message, link, type, created_at, is_read)
            VALUES (?, ?, ?, ?, ?, ?, ?, 0)
        """, (notif_id, user_id, title, message, link, notif_type, now))
        conn.commit()
    return notif_id


def get_user_notifications(user_id: str, unread_only: bool = True, limit: int = 5) -> list:
    """Retrieve notifications for a given user."""
    with get_db() as conn:
        c = conn.cursor()
        if unread_only:
            c.execute("""
                SELECT id, user_id, title, message, link, type, created_at, is_read
                FROM notifications
                WHERE user_id = ? AND is_read = 0
                ORDER BY created_at DESC
                LIMIT ?
            """, (user_id, limit))
        else:
            c.execute("""
                SELECT id, user_id, title, message, link, type, created_at, is_read
                FROM notifications
                WHERE user_id = ?
                ORDER BY created_at DESC
                LIMIT ?
            """, (user_id, limit))
        return [dict(r) for r in c.fetchall()]


def mark_notification_read(notification_id: str, user_id: str = None) -> bool:
    """Mark a notification as read."""
    with get_db() as conn:
        c = conn.cursor()
        if user_id:
            c.execute("UPDATE notifications SET is_read = 1 WHERE id = ? AND user_id = ?", (notification_id, user_id))
        else:
            c.execute("UPDATE notifications SET is_read = 1 WHERE id = ?", (notification_id,))
        conn.commit()
        return c.rowcount > 0


def get_all_users_with_email() -> list:
    """Retrieve all users with legitimate email stored in SQLite."""
    with get_db() as conn:
        c = conn.cursor()
        c.execute("SELECT id, provider, provider_id, email, name, plan, created_at, last_active FROM users WHERE email IS NOT NULL AND email != ''")
        return [dict(r) for r in c.fetchall()]



