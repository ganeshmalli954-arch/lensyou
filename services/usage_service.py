"""
services/usage_service.py
Usage management, tier duration limit enforcement, rate limiting middleware,
and granular usage logging for LensYou platform.
"""

import time
import json
import re
import os
import functools
import threading
from datetime import datetime, timedelta
from flask import request, jsonify, session

from services.storage_service import (
    log_usage_entry, get_usage_logs, get_user, get_db
)
from services.auth_service import is_owner

# Duration limits in seconds per plan tier
# guest/anonymous: 30 min (1,800s), free: 90 min (5,400s), paid/unlimited: unlimited
TIER_DURATION_LIMITS = {
    'anonymous': 30 * 60,   # 1,800 seconds (30 mins)
    'guest': 30 * 60,       # 1,800 seconds (30 mins)
    'free': 90 * 60,        # 5,400 seconds (90 mins)
    'pack10': None,         # Unlimited
    'pack50': None,         # Unlimited
    'unlimited': None       # Unlimited
}

# Requests per minute (RPM) limits per plan tier
TIER_RATE_LIMITS = {
    'anonymous': 30,        # 30 req/min
    'guest': 30,            # 30 req/min
    'free': 60,             # 60 req/min
    'pack10': 120,          # 120 req/min
    'pack50': 180,          # 180 req/min
    'unlimited': 300        # 300 req/min
}

def parse_duration_seconds(duration) -> int:
    """Parses integer, float, or formatted duration string (e.g. '14:20', '01:30:15') into integer seconds."""
    if duration is None:
        return 0
    if isinstance(duration, (int, float)):
        return max(0, int(duration))
    dur_str = str(duration).strip()
    if dur_str.isdigit():
        return int(dur_str)
    
    # ISO 8601 like PT1H30M
    iso_match = re.match(r'PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?', dur_str)
    if iso_match:
        h = int(iso_match.group(1) or 0)
        m = int(iso_match.group(2) or 0)
        s = int(iso_match.group(3) or 0)
        return h * 3600 + m * 60 + s

    parts = dur_str.split(':')
    try:
        if len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
        elif len(parts) == 2:
            return int(parts[0]) * 60 + int(parts[1])
        elif len(parts) == 1 and parts[0].isdigit():
            return int(parts[0])
    except Exception:
        pass
    return 0

def get_tier_duration_limit(plan: str = 'anonymous') -> int | None:
    """Returns the maximum video duration in seconds allowed for a plan tier, or None if unlimited."""
    clean_plan = str(plan).lower().strip() if plan else 'anonymous'
    return TIER_DURATION_LIMITS.get(clean_plan, TIER_DURATION_LIMITS['anonymous'])

def get_tier_rate_limit(plan: str = 'anonymous') -> int:
    """Returns the maximum requests per minute allowed for a plan tier."""
    clean_plan = str(plan).lower().strip() if plan else 'anonymous'
    return TIER_RATE_LIMITS.get(clean_plan, TIER_RATE_LIMITS['anonymous'])

def check_video_duration_limit(duration, user_id: str = None, session_key: str = None, plan: str = None, video_id: str = None, ip_address: str = None) -> dict:
    """
    Enforces video duration ceilings per user tier:
    - anonymous/guest: max 30 min (1,800s)
    - free: max 90 min (5,400s)
    - paid (pack10, pack50, unlimited): unlimited
    Logs the outcome in SQLite table usage_logs.
    """
    duration_seconds = parse_duration_seconds(duration)
    
    # Determine effective plan
    effective_plan = plan
    if not effective_plan:
        if user_id:
            user = get_user(user_id)
            if user:
                user_email = (user.get('email') or '').lower()
                if user_email and is_owner(user_email):
                    effective_plan = 'unlimited'
                else:
                    effective_plan = user.get('plan') or 'free'
            else:
                effective_plan = 'free'
        else:
            effective_plan = 'anonymous'

    effective_plan = str(effective_plan).lower().strip()
    limit_seconds = get_tier_duration_limit(effective_plan)

    if limit_seconds is not None and duration_seconds > limit_seconds:
        limit_mins = limit_seconds // 60
        dur_mins = round(duration_seconds / 60, 1)
        reason = f"Video duration ({dur_mins} mins) exceeds the {effective_plan} plan limit of {limit_mins} minutes."
        
        # Log duration exceeded event
        log_usage_entry(
            user_id=user_id,
            session_key=session_key,
            ip_address=ip_address,
            action='check_duration_limit',
            video_id=video_id,
            video_duration_seconds=duration_seconds,
            tokens_used=0,
            plan=effective_plan,
            status='duration_exceeded',
            details={'limit_seconds': limit_seconds, 'limit_minutes': limit_mins, 'reason': reason}
        )

        return {
            'allowed': False,
            'reason': reason,
            'duration_seconds': duration_seconds,
            'limit_seconds': limit_seconds,
            'limit_minutes': limit_mins,
            'plan': effective_plan
        }

    # Allowed duration
    log_usage_entry(
        user_id=user_id,
        session_key=session_key,
        ip_address=ip_address,
        action='check_duration_limit',
        video_id=video_id,
        video_duration_seconds=duration_seconds,
        tokens_used=0,
        plan=effective_plan,
        status='allowed',
        details={'limit_seconds': limit_seconds}
    )

    return {
        'allowed': True,
        'reason': None,
        'duration_seconds': duration_seconds,
        'limit_seconds': limit_seconds,
        'limit_minutes': (limit_seconds // 60) if limit_seconds else None,
        'plan': effective_plan
    }

class SlidingWindowRateLimiter:
    """Thread-safe sliding window rate limiter tracking request timestamps."""
    def __init__(self):
        self._requests = {}
        self._lock = threading.Lock()

    def check(self, key: str, limit: int = 60, window_seconds: int = 60) -> tuple[bool, dict]:
        now = time.time()
        cutoff = now - window_seconds
        with self._lock:
            timestamps = self._requests.get(key, [])
            valid_timestamps = [t for t in timestamps if t > cutoff]
            count = len(valid_timestamps)

            if count >= limit:
                reset_seconds = max(1, int(valid_timestamps[0] + window_seconds - now))
                self._requests[key] = valid_timestamps
                return False, {
                    'allowed': False,
                    'count': count,
                    'limit': limit,
                    'reset_seconds': reset_seconds
                }

            valid_timestamps.append(now)
            self._requests[key] = valid_timestamps
            return True, {
                'allowed': True,
                'count': count + 1,
                'limit': limit,
                'reset_seconds': window_seconds
            }

    def reset(self, key: str = None):
        with self._lock:
            if key:
                self._requests.pop(key, None)
            else:
                self._requests.clear()

    def get_count(self, key: str, window_seconds: int = 60) -> int:
        now = time.time()
        cutoff = now - window_seconds
        with self._lock:
            timestamps = self._requests.get(key, [])
            return len([t for t in timestamps if t > cutoff])

RATE_LIMITER = SlidingWindowRateLimiter()

def check_rate_limit(key: str = None, user_id: str = None, session_key: str = None, ip_address: str = None, plan: str = None, limit: int = None, window_seconds: int = 60, action: str = 'api_request') -> dict:
    """
    Checks if a user/IP has exceeded rate limits.
    Logs violations to SQLite table usage_logs.
    """
    effective_plan = plan
    if not effective_plan:
        if user_id:
            user = get_user(user_id)
            if user:
                user_email = (user.get('email') or '').lower()
                if user_email and is_owner(user_email):
                    effective_plan = 'unlimited'
                else:
                    effective_plan = user.get('plan') or 'free'
            else:
                effective_plan = 'free'
        else:
            effective_plan = 'anonymous'

    effective_plan = str(effective_plan).lower().strip()

    if limit is None:
        limit = get_tier_rate_limit(effective_plan)

    rate_key = key or user_id or session_key or ip_address or 'anonymous'
    allowed, meta = RATE_LIMITER.check(rate_key, limit=limit, window_seconds=window_seconds)

    if not allowed:
        log_usage_entry(
            user_id=user_id,
            session_key=session_key,
            ip_address=ip_address,
            action=action,
            tokens_used=0,
            plan=effective_plan,
            status='rate_limited',
            details=meta
        )
        return {
            'allowed': False,
            'status': 'rate_limited',
            'count': meta['count'],
            'limit': limit,
            'reset_seconds': meta['reset_seconds'],
            'retry_after': meta['reset_seconds'],
            'plan': effective_plan
        }

    return {
        'allowed': True,
        'status': 'allowed',
        'count': meta['count'],
        'limit': limit,
        'reset_seconds': meta['reset_seconds'],
        'plan': effective_plan
    }

def rate_limit(limit=None, window_seconds=60, action='api_request'):
    """Flask route decorator enforcing rate limits per IP/user."""
    def decorator(f):
        @functools.wraps(f)
        def decorated_function(*args, **kwargs):
            ip = None
            try:
                ip = request.headers.get('X-Forwarded-For', request.remote_addr)
                if ip and ',' in ip:
                    ip = ip.split(',')[0].strip()
            except Exception:
                pass

            user_id = None
            session_key = None
            try:
                if hasattr(session, 'get'):
                    user_id = session.get('user_id')
                    session_key = session.get('session_key')
            except Exception:
                pass

            res = check_rate_limit(
                user_id=user_id,
                session_key=session_key,
                ip_address=ip,
                limit=limit,
                window_seconds=window_seconds,
                action=action
            )
            if not res['allowed']:
                return jsonify({
                    'error': 'Too Many Requests',
                    'message': f"Rate limit exceeded. Tier '{res['plan']}' limit is {res['limit']} requests per minute.",
                    'retry_after': res.get('reset_seconds', 60)
                }), 429

            return f(*args, **kwargs)
        return decorated_function
    return decorator

def log_action_usage(action: str, video_id: str = None, duration_seconds: int = 0, tokens_used: int = 0, user_id: str = None, session_key: str = None, ip_address: str = None, plan: str = 'free', status: str = 'allowed', details: dict = None) -> str:
    """Convenience function to log application activity in table usage_logs."""
    return log_usage_entry(
        user_id=user_id,
        session_key=session_key,
        ip_address=ip_address,
        action=action,
        video_id=video_id,
        video_duration_seconds=duration_seconds,
        tokens_used=tokens_used,
        plan=plan,
        status=status,
        details=details
    )

def get_user_usage_summary(user_id: str = None, session_key: str = None, days: int = 30) -> dict:
    """Aggregates user usage metrics over recent days from table usage_logs."""
    since_date = (datetime.utcnow() - timedelta(days=days)).isoformat()
    with get_db() as conn:
        c = conn.cursor()
        clauses = ["created_at >= ?"]
        params = [since_date]
        if user_id:
            clauses.append("user_id = ?")
            params.append(user_id)
        elif session_key:
            clauses.append("session_key = ?")
            params.append(session_key)

        where = f" WHERE {' AND '.join(clauses)}"
        
        # Total events
        c.execute(f"SELECT COUNT(*) as total_events, COALESCE(SUM(tokens_used), 0) as total_tokens, COALESCE(SUM(video_duration_seconds), 0) as total_duration FROM usage_logs{where}", params)
        row = c.fetchone()
        total_events = row['total_events'] if row else 0
        total_tokens = row['total_tokens'] if row else 0
        total_duration = row['total_duration'] if row else 0

        # Rate limits & duration exceeded
        c.execute(f"SELECT COUNT(*) as rate_limited FROM usage_logs{where} AND status = 'rate_limited'", params)
        rate_limited_count = c.fetchone()['rate_limited']

        c.execute(f"SELECT COUNT(*) as duration_exceeded FROM usage_logs{where} AND status = 'duration_exceeded'", params)
        duration_exceeded_count = c.fetchone()['duration_exceeded']

        return {
            'total_events': total_events,
            'total_tokens': total_tokens,
            'total_duration_seconds': total_duration,
            'total_duration_minutes': round(total_duration / 60, 2),
            'rate_limited_count': rate_limited_count,
            'duration_exceeded_count': duration_exceeded_count,
            'window_days': days
        }
