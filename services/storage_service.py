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

def init_relational_db(conn=None):
    """Initializes the 12 normalized relational tables in SQLite for LensYou architecture."""
    close_conn = False
    if conn is None:
        conn = get_db()
        close_conn = True
    try:
        c = conn.cursor()
        # 1. users
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
                role TEXT DEFAULT 'user',
                login_count INTEGER DEFAULT 0,
                created_at TEXT,
                last_active TEXT,
                UNIQUE(provider, provider_id)
            )
        ''')
        c.execute('CREATE INDEX IF NOT EXISTS idx_users_email ON users(email)')

        # 2. videos (MUST include idx_videos_video_id and analysis_json)
        c.execute('''
            CREATE TABLE IF NOT EXISTS videos (
                id TEXT PRIMARY KEY,
                video_id TEXT NOT NULL,
                title TEXT,
                author TEXT,
                duration TEXT,
                analysis_json TEXT,
                user_id TEXT,
                session_key TEXT,
                created_at TEXT
            )
        ''')
        c.execute('CREATE INDEX IF NOT EXISTS idx_videos_video_id ON videos(video_id)')
        c.execute('CREATE INDEX IF NOT EXISTS idx_videos_user ON videos(user_id)')

        # 3. analysis_jobs
        c.execute('''
            CREATE TABLE IF NOT EXISTS analysis_jobs (
                id TEXT PRIMARY KEY,
                video_id TEXT NOT NULL,
                user_id TEXT,
                session_key TEXT,
                status TEXT NOT NULL DEFAULT 'QUEUED',
                stage INTEGER DEFAULT 0,
                stage_name TEXT DEFAULT 'queued',
                progress INTEGER DEFAULT 0,
                error TEXT,
                result_summary TEXT,
                modules_completed TEXT DEFAULT '[]',
                retry_count INTEGER DEFAULT 0,
                created_at TEXT,
                updated_at TEXT,
                completed_at TEXT
            )
        ''')
        c.execute('CREATE INDEX IF NOT EXISTS idx_analysis_jobs_video_id ON analysis_jobs(video_id)')
        c.execute('CREATE INDEX IF NOT EXISTS idx_analysis_jobs_status ON analysis_jobs(status)')
        c.execute('CREATE INDEX IF NOT EXISTS idx_analysis_jobs_user ON analysis_jobs(user_id)')

        # 4. transcript_segments
        c.execute('''
            CREATE TABLE IF NOT EXISTS transcript_segments (
                id TEXT PRIMARY KEY,
                video_id TEXT NOT NULL,
                segment_index INTEGER NOT NULL,
                start_seconds REAL NOT NULL,
                duration REAL NOT NULL,
                end_seconds REAL,
                text TEXT NOT NULL,
                speaker TEXT,
                is_synthesized INTEGER DEFAULT 0,
                created_at TEXT
            )
        ''')
        c.execute('CREATE INDEX IF NOT EXISTS idx_transcript_segments_vid ON transcript_segments(video_id)')
        c.execute('CREATE INDEX IF NOT EXISTS idx_transcript_segments_time ON transcript_segments(video_id, start_seconds)')

        # 5. summaries
        c.execute('''
            CREATE TABLE IF NOT EXISTS summaries (
                id TEXT PRIMARY KEY,
                video_id TEXT NOT NULL,
                summary_type TEXT DEFAULT 'overview',
                content TEXT NOT NULL,
                key_takeaways TEXT,
                target_audience TEXT,
                sentiment TEXT,
                model_used TEXT,
                created_at TEXT
            )
        ''')
        c.execute('CREATE INDEX IF NOT EXISTS idx_summaries_video_id ON summaries(video_id)')

        # 6. chapters
        c.execute('''
            CREATE TABLE IF NOT EXISTS chapters (
                id TEXT PRIMARY KEY,
                video_id TEXT NOT NULL,
                chapter_index INTEGER NOT NULL,
                title TEXT NOT NULL,
                start_seconds REAL NOT NULL,
                end_seconds REAL,
                timestamp_label TEXT,
                summary TEXT,
                key_points TEXT,
                created_at TEXT
            )
        ''')
        c.execute('CREATE INDEX IF NOT EXISTS idx_chapters_video_id ON chapters(video_id)')

        # 7. claims
        c.execute('''
            CREATE TABLE IF NOT EXISTS claims (
                id TEXT PRIMARY KEY,
                video_id TEXT NOT NULL,
                claim_text TEXT NOT NULL,
                category TEXT DEFAULT 'factual',
                timestamp_label TEXT,
                start_seconds REAL,
                end_seconds REAL,
                confidence_score REAL DEFAULT 1.0,
                verified INTEGER DEFAULT 1,
                verification_note TEXT,
                transcript_segment_id TEXT,
                speaker TEXT,
                created_at TEXT
            )
        ''')
        c.execute('CREATE INDEX IF NOT EXISTS idx_claims_video_id ON claims(video_id)')

        # 8. entities
        c.execute('''
            CREATE TABLE IF NOT EXISTS entities (
                id TEXT PRIMARY KEY,
                video_id TEXT NOT NULL,
                name TEXT NOT NULL,
                entity_type TEXT DEFAULT 'Concept',
                description TEXT,
                relevance_score REAL DEFAULT 1.0,
                mention_count INTEGER DEFAULT 1,
                first_seen_seconds REAL,
                metadata_json TEXT,
                created_at TEXT
            )
        ''')
        c.execute('CREATE INDEX IF NOT EXISTS idx_entities_video_id ON entities(video_id)')

        # 9. flashcards
        c.execute('''
            CREATE TABLE IF NOT EXISTS flashcards (
                id TEXT PRIMARY KEY,
                video_id TEXT NOT NULL,
                card_index INTEGER,
                front TEXT NOT NULL,
                back TEXT NOT NULL,
                topic TEXT,
                difficulty TEXT DEFAULT 'medium',
                bloom_level TEXT,
                review_interval INTEGER DEFAULT 1,
                ease_factor REAL DEFAULT 2.5,
                created_at TEXT
            )
        ''')
        c.execute('CREATE INDEX IF NOT EXISTS idx_flashcards_video_id ON flashcards(video_id)')

        # 10. quizzes
        c.execute('''
            CREATE TABLE IF NOT EXISTS quizzes (
                id TEXT PRIMARY KEY,
                video_id TEXT NOT NULL,
                question_index INTEGER,
                bloom_level TEXT DEFAULT 'Understand',
                question TEXT NOT NULL,
                options_json TEXT NOT NULL,
                correct_index INTEGER NOT NULL,
                explanation TEXT,
                timestamp_label TEXT,
                created_at TEXT
            )
        ''')
        c.execute('CREATE INDEX IF NOT EXISTS idx_quizzes_video_id ON quizzes(video_id)')

        # 11. exports
        c.execute('''
            CREATE TABLE IF NOT EXISTS exports (
                id TEXT PRIMARY KEY,
                video_id TEXT NOT NULL,
                user_id TEXT,
                session_key TEXT,
                export_type TEXT NOT NULL,
                file_path TEXT,
                file_size INTEGER,
                status TEXT DEFAULT 'completed',
                created_at TEXT
            )
        ''')
        c.execute('CREATE INDEX IF NOT EXISTS idx_exports_video_id ON exports(video_id)')

        # 12. usage_logs
        c.execute('''
            CREATE TABLE IF NOT EXISTS usage_logs (
                id TEXT PRIMARY KEY,
                user_id TEXT,
                session_key TEXT,
                ip_address TEXT,
                action TEXT NOT NULL,
                video_id TEXT,
                video_duration_seconds INTEGER,
                tokens_used INTEGER DEFAULT 0,
                plan TEXT,
                status TEXT DEFAULT 'allowed',
                details TEXT,
                created_at TEXT
            )
        ''')
        c.execute('CREATE INDEX IF NOT EXISTS idx_usage_logs_user ON usage_logs(user_id)')
        c.execute('CREATE INDEX IF NOT EXISTS idx_usage_logs_ip ON usage_logs(ip_address)')
        c.execute('CREATE INDEX IF NOT EXISTS idx_usage_logs_created ON usage_logs(created_at)')

        conn.commit()
    finally:
        if close_conn:
            conn.close()

def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    with get_db() as conn:
        init_relational_db(conn)
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

def save_analysis_modular(video_id: str, modules: dict, user_id: str = None, session_key: str = None) -> bool:
    """Persists modular analysis records into relational tables in SQLite."""
    if not video_id or not isinstance(modules, dict):
        return False
    now = datetime.utcnow().isoformat()
    try:
        with get_db() as conn:
            c = conn.cursor()
            
            # 1. Summaries
            overview = modules.get('video_overview') or {}
            summary_content = overview.get('summary') if isinstance(overview, dict) else (modules.get('summary') or "")
            takeaways = modules.get('key_takeaways') or []
            target_aud = overview.get('target_audience', '') if isinstance(overview, dict) else ""
            sentiment = overview.get('sentiment_label', '') if isinstance(overview, dict) else ""
            model_used = modules.get('_meta', {}).get('model_used', '') if isinstance(modules.get('_meta'), dict) else ""
            
            if summary_content or takeaways:
                c.execute('DELETE FROM summaries WHERE video_id = ?', (video_id,))
                sum_id = f"sum_{video_id}_{uuid.uuid4().hex[:8]}"
                c.execute('''
                    INSERT INTO summaries (id, video_id, summary_type, content, key_takeaways, target_audience, sentiment, model_used, created_at)
                    VALUES (?, ?, 'overview', ?, ?, ?, ?, ?, ?)
                ''', (sum_id, video_id, str(summary_content), json.dumps(takeaways), target_aud, sentiment, model_used, now))

            # 2. Chapters
            raw_chapters = modules.get('chapters') or modules.get('timeline') or modules.get('timestamped_chapters') or []
            if isinstance(raw_chapters, list) and raw_chapters:
                c.execute('DELETE FROM chapters WHERE video_id = ?', (video_id,))
                for idx, chap in enumerate(raw_chapters):
                    chap_id = f"chap_{video_id}_{idx}"
                    title = chap.get('title') or chap.get('highlight') or f"Chapter {idx+1}"
                    sec = chap.get('seconds') or 0.0
                    end_sec = chap.get('end_seconds')
                    ts_label = chap.get('time') or chap.get('timestamp') or ""
                    summary = chap.get('summary') or ""
                    kp = json.dumps(chap.get('key_points', []))
                    c.execute('''
                        INSERT INTO chapters (id, video_id, chapter_index, title, start_seconds, end_seconds, timestamp_label, summary, key_points, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ''', (chap_id, video_id, idx, title, float(sec), float(end_sec) if end_sec is not None else None, str(ts_label), summary, kp, now))

            # 3. Claims
            raw_claims = modules.get('factual_claims') or modules.get('claims') or []
            if isinstance(raw_claims, list) and raw_claims:
                c.execute('DELETE FROM claims WHERE video_id = ?', (video_id,))
                for idx, clm in enumerate(raw_claims):
                    claim_id = f"claim_{video_id}_{idx}"
                    text = clm.get('claim') or clm.get('claim_text') or str(clm)
                    cat = clm.get('category', 'factual')
                    ts_label = clm.get('timestamp') or clm.get('time') or ""
                    sec = clm.get('seconds') or 0.0
                    end_sec = clm.get('end_seconds')
                    conf = clm.get('confidence_score', 1.0)
                    if isinstance(conf, str):
                        try:
                            conf = float(conf.replace('%', '')) / 100.0 if '%' in conf else float(conf)
                        except Exception:
                            conf = 1.0
                    verified = 1 if clm.get('verified', True) else 0
                    note = clm.get('verification_note', '')
                    seg_id = clm.get('transcript_segment_id')
                    speaker = clm.get('speaker', '')
                    c.execute('''
                        INSERT INTO claims (id, video_id, claim_text, category, timestamp_label, start_seconds, end_seconds, confidence_score, verified, verification_note, transcript_segment_id, speaker, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ''', (claim_id, video_id, text, cat, str(ts_label), float(sec), float(end_sec) if end_sec is not None else None, float(conf), verified, note, seg_id, speaker, now))

            # 4. Entities
            raw_entities = modules.get('key_concepts') or modules.get('entities') or []
            if isinstance(raw_entities, dict) and 'nodes' in raw_entities:
                raw_entities = raw_entities['nodes']
            if isinstance(raw_entities, list) and raw_entities:
                c.execute('DELETE FROM entities WHERE video_id = ?', (video_id,))
                for idx, ent in enumerate(raw_entities):
                    ent_id = f"ent_{video_id}_{idx}"
                    name = ent.get('concept') or ent.get('name') or ent.get('id') or f"Entity {idx+1}"
                    etype = ent.get('type') or ent.get('entity_type', 'Concept')
                    desc = ent.get('explanation') or ent.get('description', '')
                    rel = ent.get('relevance_score', 1.0)
                    mcount = ent.get('mention_count', 1)
                    first_sec = ent.get('first_seen_seconds')
                    c.execute('''
                        INSERT INTO entities (id, video_id, name, entity_type, description, relevance_score, mention_count, first_seen_seconds, metadata_json, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ''', (ent_id, video_id, name, etype, desc, float(rel), int(mcount), float(first_sec) if first_sec is not None else None, json.dumps(ent), now))

            # 5. Flashcards
            raw_learning = modules.get('learning') or {}
            raw_cards = raw_learning.get('flashcards') or modules.get('flashcards') or []
            if isinstance(raw_cards, list) and raw_cards:
                c.execute('DELETE FROM flashcards WHERE video_id = ?', (video_id,))
                for idx, fc in enumerate(raw_cards):
                    fc_id = f"fc_{video_id}_{idx}"
                    front = fc.get('front') or fc.get('question') or ""
                    back = fc.get('back') or fc.get('answer') or ""
                    topic = fc.get('topic', '')
                    diff = fc.get('difficulty', 'medium')
                    bloom = fc.get('bloom_level', '')
                    c.execute('''
                        INSERT INTO flashcards (id, video_id, card_index, front, back, topic, difficulty, bloom_level, review_interval, ease_factor, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, 2.5, ?)
                    ''', (fc_id, video_id, idx, front, back, topic, diff, bloom, now))

            # 6. Quizzes
            raw_quiz = raw_learning.get('quiz') or modules.get('quizzes') or []
            if isinstance(raw_quiz, list) and raw_quiz:
                c.execute('DELETE FROM quizzes WHERE video_id = ?', (video_id,))
                for idx, qz in enumerate(raw_quiz):
                    qz_id = f"quiz_{video_id}_{idx}"
                    q_text = qz.get('question') or ""
                    opts = qz.get('options') or []
                    corr = qz.get('correct_index', 0)
                    exp = qz.get('explanation', '')
                    bloom = qz.get('bloom_level', 'Understand')
                    ts = qz.get('timestamp', '')
                    c.execute('''
                        INSERT INTO quizzes (id, video_id, question_index, bloom_level, question, options_json, correct_index, explanation, timestamp_label, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ''', (qz_id, video_id, idx, bloom, q_text, json.dumps(opts), int(corr), exp, str(ts), now))

            # 7. Transcript segments
            raw_segments = modules.get('transcript_segments') or modules.get('transcript') or []
            if isinstance(raw_segments, dict) and 'segments' in raw_segments:
                raw_segments = raw_segments['segments']
            if isinstance(raw_segments, list) and raw_segments:
                c.execute('DELETE FROM transcript_segments WHERE video_id = ?', (video_id,))
                for idx, seg in enumerate(raw_segments):
                    seg_id = f"seg_{video_id}_{idx}"
                    start = float(seg.get('start', 0.0))
                    dur = float(seg.get('duration', 0.0))
                    end = float(start + dur)
                    txt = seg.get('text', '')
                    spk = seg.get('speaker', '')
                    synth = 1 if seg.get('is_synthesized') else 0
                    c.execute('''
                        INSERT INTO transcript_segments (id, video_id, segment_index, start_seconds, duration, end_seconds, text, speaker, is_synthesized, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ''', (seg_id, video_id, idx, start, dur, end, txt, spk, synth, now))

            conn.commit()
            return True
    except Exception as e:
        print(f"  [Modular Save Error]: {e}", flush=True)
        return False

def get_modular_analysis(video_id: str) -> dict | None:
    """Reconstructs complete analysis dictionary from 12 normalized relational tables."""
    if not video_id:
        return None
    try:
        with get_db() as conn:
            c = conn.cursor()
            c.execute('SELECT * FROM videos WHERE video_id = ? ORDER BY created_at DESC LIMIT 1', (video_id,))
            v_row = c.fetchone()
            
            # Base data from videos table if analysis_json exists
            base_data = {}
            if v_row and v_row['analysis_json']:
                try:
                    base_data = json.loads(v_row['analysis_json'])
                except Exception:
                    base_data = {}

            # Fetch summaries
            c.execute('SELECT * FROM summaries WHERE video_id = ? ORDER BY created_at DESC LIMIT 1', (video_id,))
            s_row = c.fetchone()
            if s_row:
                if 'video_overview' not in base_data:
                    base_data['video_overview'] = {}
                base_data['video_overview']['summary'] = s_row['content']
                base_data['video_overview']['target_audience'] = s_row['target_audience']
                base_data['video_overview']['sentiment_label'] = s_row['sentiment']
                if s_row['key_takeaways']:
                    try:
                        base_data['key_takeaways'] = json.loads(s_row['key_takeaways'])
                    except Exception:
                        pass

            # Fetch chapters
            c.execute('SELECT * FROM chapters WHERE video_id = ? ORDER BY chapter_index ASC, start_seconds ASC', (video_id,))
            c_rows = c.fetchall()
            if c_rows:
                timeline = []
                for cr in c_rows:
                    kp = []
                    if cr['key_points']:
                        try:
                            kp = json.loads(cr['key_points'])
                        except Exception:
                            pass
                    timeline.append({
                        'title': cr['title'],
                        'time': cr['timestamp_label'],
                        'seconds': cr['start_seconds'],
                        'end_seconds': cr['end_seconds'],
                        'summary': cr['summary'],
                        'key_points': kp
                    })
                base_data['timeline'] = timeline
                base_data['chapters'] = timeline

            # Fetch claims
            c.execute('SELECT * FROM claims WHERE video_id = ? ORDER BY start_seconds ASC', (video_id,))
            cl_rows = c.fetchall()
            if cl_rows:
                claims = []
                for cl in cl_rows:
                    claims.append({
                        'id': cl['id'],
                        'claim': cl['claim_text'],
                        'claim_text': cl['claim_text'],
                        'category': cl['category'],
                        'timestamp': cl['timestamp_label'],
                        'seconds': cl['start_seconds'],
                        'end_seconds': cl['end_seconds'],
                        'confidence_score': cl['confidence_score'],
                        'verified': bool(cl['verified']),
                        'verification_note': cl['verification_note'],
                        'transcript_segment_id': cl['transcript_segment_id'],
                        'speaker': cl['speaker']
                    })
                base_data['factual_claims'] = claims

            # Fetch entities
            c.execute('SELECT * FROM entities WHERE video_id = ? ORDER BY relevance_score DESC', (video_id,))
            e_rows = c.fetchall()
            if e_rows:
                entities = []
                for er in e_rows:
                    entities.append({
                        'concept': er['name'],
                        'name': er['name'],
                        'type': er['entity_type'],
                        'explanation': er['description'],
                        'relevance_score': er['relevance_score'],
                        'mention_count': er['mention_count'],
                        'first_seen_seconds': er['first_seen_seconds']
                    })
                base_data['key_concepts'] = entities

            # Fetch flashcards and quizzes
            c.execute('SELECT * FROM flashcards WHERE video_id = ? ORDER BY card_index ASC', (video_id,))
            fc_rows = c.fetchall()
            c.execute('SELECT * FROM quizzes WHERE video_id = ? ORDER BY question_index ASC', (video_id,))
            qz_rows = c.fetchall()

            if fc_rows or qz_rows:
                if 'learning' not in base_data:
                    base_data['learning'] = {}
                if fc_rows:
                    cards = []
                    for fcr in fc_rows:
                        cards.append({
                            'front': fcr['front'],
                            'back': fcr['back'],
                            'topic': fcr['topic'],
                            'difficulty': fcr['difficulty'],
                            'bloom_level': fcr['bloom_level']
                        })
                    base_data['learning']['flashcards'] = cards
                    base_data['flashcards'] = cards
                if qz_rows:
                    quizzes = []
                    for qzr in qz_rows:
                        opts = []
                        if qzr['options_json']:
                            try:
                                opts = json.loads(qzr['options_json'])
                            except Exception:
                                pass
                        quizzes.append({
                            'question': qzr['question'],
                            'options': opts,
                            'correct_index': qzr['correct_index'],
                            'explanation': qzr['explanation'],
                            'bloom_level': qzr['bloom_level'],
                            'timestamp': qzr['timestamp_label']
                        })
                    base_data['learning']['quiz'] = quizzes
                    base_data['quizzes'] = quizzes

            # Fetch transcript segments
            c.execute('SELECT * FROM transcript_segments WHERE video_id = ? ORDER BY segment_index ASC, start_seconds ASC', (video_id,))
            seg_rows = c.fetchall()
            if seg_rows:
                segments = []
                for sr in seg_rows:
                    segments.append({
                        'text': sr['text'],
                        'start': sr['start_seconds'],
                        'duration': sr['duration'],
                        'end': sr['end_seconds'],
                        'speaker': sr['speaker'],
                        'is_synthesized': bool(sr['is_synthesized'])
                    })
                base_data['transcript_segments'] = segments

            if not base_data and not v_row:
                return None

            # Ensure _meta is set
            if '_meta' not in base_data and v_row:
                base_data['_meta'] = {
                    'video_id': v_row['video_id'],
                    'title': v_row['title'],
                    'author': v_row['author'],
                    'duration': v_row['duration']
                }

            return base_data if base_data else None
    except Exception as e:
        print(f"  [Modular Retrieval Error]: {e}", flush=True)
        return None

def save_cached_analysis(video_id: str, title: str = "", author: str = "", duration: str = "", analysis: dict = None, user_id: str = None, session_key: str = None, **kwargs) -> str:
    """Save completed video analysis to SQLite database for instant caching and public sharing.
    Saves both the relational records and videos.analysis_json for 100% backward compatibility."""
    if not video_id:
        return ""
    if isinstance(title, dict) and analysis is None:
        analysis = title
        title = analysis.get('_meta', {}).get('title', '')
        author = analysis.get('_meta', {}).get('author', '')
        duration = analysis.get('_meta', {}).get('duration', '')
    if not analysis:
        return ""
    if not title and isinstance(analysis, dict):
        title = analysis.get('_meta', {}).get('title') or analysis.get('video_overview', {}).get('title', '')
    if not author and isinstance(analysis, dict):
        author = analysis.get('_meta', {}).get('author') or analysis.get('video_overview', {}).get('channel', '')
    if not duration and isinstance(analysis, dict):
        duration = analysis.get('_meta', {}).get('duration') or analysis.get('video_overview', {}).get('estimated_duration', '')

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
                ret_id = existing['id']
            else:
                c.execute('''
                    INSERT INTO videos (id, video_id, title, author, duration, analysis_json, user_id, session_key, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (record_id, video_id, title, author, duration, raw_json, user_id, session_key, now_str))
                ret_id = record_id
            conn.commit()

        # Save into normalized relational tables
        save_analysis_modular(video_id, analysis, user_id=user_id, session_key=session_key)
        return ret_id
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
        # Fallback to modular reconstruction if analysis_json missing
        modular_data = get_modular_analysis(video_id)
        if modular_data:
            CACHE[video_id] = modular_data
            return modular_data
    except Exception as e:
        print(f"  [Cache Retrieval Error]: {e}", flush=True)
    return None

get_analysis = get_cached_analysis

# --- Persistent Analysis Jobs State Machine ---

def create_analysis_job(job_id: str = None, video_id: str = "", user_id: str = None, session_key: str = None) -> dict:
    """Creates a persistent job record in SQLite table analysis_jobs."""
    if not job_id:
        job_id = f"job_{uuid.uuid4().hex[:12]}"
    now = datetime.utcnow().isoformat()
    with get_db() as conn:
        c = conn.cursor()
        c.execute('''
            INSERT INTO analysis_jobs (id, video_id, user_id, session_key, status, stage, stage_name, progress, retry_count, created_at, updated_at)
            VALUES (?, ?, ?, ?, 'QUEUED', 0, 'queued', 0, 0, ?, ?)
        ''', (job_id, video_id, user_id, session_key, now, now))
        conn.commit()
    return {
        'id': job_id,
        'video_id': video_id,
        'user_id': user_id,
        'session_key': session_key,
        'status': 'QUEUED',
        'stage': 0,
        'stage_name': 'queued',
        'progress': 0,
        'error': None,
        'result_summary': {},
        'modules_completed': [],
        'retry_count': 0,
        'created_at': now,
        'updated_at': now,
        'completed_at': None
    }

def update_job_status(job_id: str, status: str, stage: int = None, stage_name: str = None, error: str = None, result_summary: dict = None, modules_completed: list = None, progress: int = None, retry_count: int = None) -> bool:
    """Updates persistent job status in table analysis_jobs."""
    now = datetime.utcnow().isoformat()
    is_terminal = str(status).upper() in ('COMPLETED', 'PARTIAL', 'FAILED') or str(status).lower() in ('completed', 'partial', 'failed', 'error')
    completed_at = now if is_terminal else None

    with get_db() as conn:
        c = conn.cursor()
        updates = ["status = ?", "updated_at = ?"]
        params = [status, now]

        if stage is not None:
            updates.append("stage = ?")
            params.append(stage)
        if stage_name is not None:
            updates.append("stage_name = ?")
            params.append(stage_name)
        if progress is not None:
            updates.append("progress = ?")
            params.append(progress)
        if error is not None:
            updates.append("error = ?")
            params.append(str(error))
        if result_summary is not None:
            updates.append("result_summary = ?")
            params.append(json.dumps(result_summary) if isinstance(result_summary, (dict, list)) else str(result_summary))
        if modules_completed is not None:
            updates.append("modules_completed = ?")
            params.append(json.dumps(modules_completed) if isinstance(modules_completed, list) else str(modules_completed))
        if retry_count is not None:
            updates.append("retry_count = ?")
            params.append(retry_count)
        if completed_at is not None:
            updates.append("completed_at = COALESCE(completed_at, ?)")
            params.append(completed_at)

        params.append(job_id)
        sql = f"UPDATE analysis_jobs SET {', '.join(updates)} WHERE id = ?"
        c.execute(sql, params)
        conn.commit()
        return c.rowcount > 0

def get_analysis_job(job_id: str) -> dict | None:
    """Retrieves persistent analysis job record by id."""
    with get_db() as conn:
        c = conn.cursor()
        c.execute("SELECT * FROM analysis_jobs WHERE id = ?", (job_id,))
        row = c.fetchone()
        if not row:
            return None
        job = dict(row)
        if job.get('result_summary'):
            try:
                job['result_summary'] = json.loads(job['result_summary'])
            except Exception:
                pass
        else:
            job['result_summary'] = {}

        if job.get('modules_completed'):
            try:
                job['modules_completed'] = json.loads(job['modules_completed'])
            except Exception:
                job['modules_completed'] = []
        else:
            job['modules_completed'] = []
        return job

def list_analysis_jobs(limit: int = 50, status: str = None, user_id: str = None) -> list:
    """Lists recent persistent analysis jobs."""
    with get_db() as conn:
        c = conn.cursor()
        clauses = []
        params = []
        if status:
            clauses.append("status = ?")
            params.append(status)
        if user_id:
            clauses.append("user_id = ?")
            params.append(user_id)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(limit)
        c.execute(f"SELECT * FROM analysis_jobs{where} ORDER BY created_at DESC LIMIT ?", params)
        jobs = []
        for row in c.fetchall():
            j = dict(row)
            if j.get('result_summary'):
                try:
                    j['result_summary'] = json.loads(j['result_summary'])
                except Exception:
                    pass
            if j.get('modules_completed'):
                try:
                    j['modules_completed'] = json.loads(j['modules_completed'])
                except Exception:
                    pass
            jobs.append(j)
        return jobs

# --- Usage Logs & Export Management ---

def log_usage_entry(user_id=None, session_key=None, ip_address=None, action="", video_id=None, video_duration_seconds=0, tokens_used=0, plan="free", status="allowed", details=None) -> str:
    """Records granular usage events in table usage_logs to track resource consumption."""
    log_id = f"usg_{uuid.uuid4().hex[:12]}"
    now = datetime.utcnow().isoformat()
    det_str = json.dumps(details) if isinstance(details, (dict, list)) else (str(details) if details else None)
    with get_db() as conn:
        c = conn.cursor()
        c.execute('''
            INSERT INTO usage_logs (id, user_id, session_key, ip_address, action, video_id, video_duration_seconds, tokens_used, plan, status, details, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (log_id, user_id, session_key, ip_address, action, video_id, video_duration_seconds, tokens_used, plan, status, det_str, now))
        conn.commit()
    return log_id

def get_usage_logs(user_id=None, ip_address=None, action=None, limit=50) -> list:
    """Retrieves usage logs from table usage_logs."""
    with get_db() as conn:
        c = conn.cursor()
        clauses = []
        params = []
        if user_id:
            clauses.append("user_id = ?")
            params.append(user_id)
        if ip_address:
            clauses.append("ip_address = ?")
            params.append(ip_address)
        if action:
            clauses.append("action = ?")
            params.append(action)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(limit)
        c.execute(f"SELECT * FROM usage_logs{where} ORDER BY created_at DESC LIMIT ?", params)
        return [dict(r) for r in c.fetchall()]

def record_export(video_id: str, export_type: str, file_path: str = None, file_size: int = 0, user_id: str = None, session_key: str = None, status: str = 'completed') -> str:
    """Stores record of generated export file in table exports."""
    exp_id = f"exp_{uuid.uuid4().hex[:12]}"
    now = datetime.utcnow().isoformat()
    with get_db() as conn:
        c = conn.cursor()
        c.execute('''
            INSERT INTO exports (id, video_id, user_id, session_key, export_type, file_path, file_size, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (exp_id, video_id, user_id, session_key, export_type, file_path, file_size, status, now))
        conn.commit()
    return exp_id

def get_exports_for_video(video_id: str) -> list:
    """Retrieves all export records for a given video."""
    with get_db() as conn:
        c = conn.cursor()
        c.execute('SELECT * FROM exports WHERE video_id = ? ORDER BY created_at DESC', (video_id,))
        return [dict(r) for r in c.fetchall()]

# --- Relational Entity Select Queries ---

def get_transcript_segments(video_id: str) -> list:
    with get_db() as conn:
        c = conn.cursor()
        c.execute('SELECT * FROM transcript_segments WHERE video_id = ? ORDER BY segment_index ASC, start_seconds ASC', (video_id,))
        return [dict(r) for r in c.fetchall()]

def get_chapters(video_id: str) -> list:
    with get_db() as conn:
        c = conn.cursor()
        c.execute('SELECT * FROM chapters WHERE video_id = ? ORDER BY chapter_index ASC, start_seconds ASC', (video_id,))
        return [dict(r) for r in c.fetchall()]

def get_claims(video_id: str) -> list:
    with get_db() as conn:
        c = conn.cursor()
        c.execute('SELECT * FROM claims WHERE video_id = ? ORDER BY start_seconds ASC', (video_id,))
        return [dict(r) for r in c.fetchall()]

def get_entities(video_id: str) -> list:
    with get_db() as conn:
        c = conn.cursor()
        c.execute('SELECT * FROM entities WHERE video_id = ? ORDER BY relevance_score DESC', (video_id,))
        return [dict(r) for r in c.fetchall()]

def get_flashcards(video_id: str) -> list:
    with get_db() as conn:
        c = conn.cursor()
        c.execute('SELECT * FROM flashcards WHERE video_id = ? ORDER BY card_index ASC', (video_id,))
        return [dict(r) for r in c.fetchall()]

def get_quizzes(video_id: str) -> list:
    with get_db() as conn:
        c = conn.cursor()
        c.execute('SELECT * FROM quizzes WHERE video_id = ? ORDER BY question_index ASC', (video_id,))
        return [dict(r) for r in c.fetchall()]

def get_summaries(video_id: str) -> list:
    with get_db() as conn:
        c = conn.cursor()
        c.execute('SELECT * FROM summaries WHERE video_id = ? ORDER BY created_at DESC', (video_id,))
        return [dict(r) for r in c.fetchall()]

def record_export(video_id: str, export_type: str, user_id: str = None, session_key: str = None, file_path: str = None, file_size: int = 0, status: str = 'completed') -> str:
    export_id = f"exp_{uuid.uuid4().hex[:12]}"
    now = datetime.utcnow().isoformat()
    with get_db() as conn:
        c = conn.cursor()
        c.execute('''
            INSERT INTO exports (id, video_id, user_id, session_key, export_type, file_path, file_size, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (export_id, video_id, user_id, session_key, export_type, file_path, file_size, status, now))
        conn.commit()
    return export_id

def get_exports(video_id: str) -> list:
    with get_db() as conn:
        c = conn.cursor()
        c.execute('SELECT * FROM exports WHERE video_id = ? ORDER BY created_at DESC', (video_id,))
        return [dict(r) for r in c.fetchall()]


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



