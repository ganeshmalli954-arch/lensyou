import hashlib
import os
from services.storage_service import (
    get_user, get_user_by_provider, create_user,
    get_anon_session, increment_anon_quota, update_user_quota, update_user_plan,
    log_event
)

QUOTA_ANONYMOUS = 3
QUOTA_FREE = 5
PLAN_QUOTAS = {'free': 5, 'pack10': 15, 'pack50': 55, 'unlimited': -1}

def get_session_key(ip: str, fingerprint: str = '') -> str:
    raw = f'{ip}:{fingerprint}'
    return hashlib.sha256(raw.encode()).hexdigest()[:32]

def get_owner_emails() -> list:
    raw = os.getenv('OWNER_EMAIL', 'ganeshmalli954@gmail.com')
    return [e.strip().lower() for e in raw.split(',') if e.strip()]

def is_owner(email: str) -> bool:
    if not email: return False
    return email.strip().lower() in get_owner_emails()

def check_quota(user_id=None, session_key=None) -> dict:
    if user_id:
        user = get_user(user_id)
        if not user: return {'allowed': False, 'reason': 'User not found'}
        
        # Check if owner email
        user_email = (user.get('email') or '').lower()
        if user_email and is_owner(user_email):
            if user.get('plan') != 'unlimited' or user.get('quota_limit') != -1:
                update_user_plan(user_id, 'unlimited', -1)
            return {'allowed': True, 'used': user.get('quota_used', 0), 'limit': -1, 'plan': 'unlimited (owner)'}

        if user['plan'] == 'unlimited': 
            return {'allowed': True, 'used': user['quota_used'], 'limit': -1, 'plan': 'unlimited'}
        allowed = user['quota_used'] < user['quota_limit']
        return {'allowed': allowed, 'used': user['quota_used'], 'limit': user['quota_limit'], 'plan': user['plan']}
    else:
        session = get_anon_session(session_key)
        allowed = session['quota_used'] < QUOTA_ANONYMOUS
        return {'allowed': allowed, 'used': session['quota_used'], 'limit': QUOTA_ANONYMOUS, 'plan': 'anonymous'}

def increment_quota(user_id=None, session_key=None):
    if user_id:
        update_user_quota(user_id)
    elif session_key:
        increment_anon_quota(session_key)

def get_or_create_user(provider, provider_id, email, name, avatar_url) -> dict:
    existing = get_user_by_provider(provider, provider_id, email=email, name=name, avatar_url=avatar_url)
    if existing:
        if email and is_owner(email) and existing.get('plan') != 'unlimited':
            update_user_plan(existing['id'], 'unlimited', -1)
            existing = get_user(existing['id'])
        log_event('INFO', f"User {email or existing.get('name', 'Anonymous')} signed in via {provider}", source='auth')
        return existing

    user_id = create_user(provider, provider_id, email, name, avatar_url)
    if email and is_owner(email):
        update_user_plan(user_id, 'unlimited', -1)
    new_user = get_user(user_id)
    log_event('INFO', f"New user registered: {email or name} via {provider}", source='auth')
    return new_user

PLAN_CONFIG = {
    'anonymous': {
        'name': 'Guest',
        'quota': 3,
        'history_limit': 5,
        'price': 0,
        'price_display': 'Free',
        'features': ['Standard 9-stage analysis', '3 free analyses', '5 history items', 'Unlimited video length (lectures & podcasts)']
    },
    'free': {
        'name': 'Free Tier',
        'quota': 5,
        'history_limit': 10,
        'price': 0,
        'price_display': 'Free',
        'features': ['Google Account Sync', '5 video analyses', '10 history items', 'PDF dossier export', 'Unlimited video length (1-4+ hr lectures)']
    },
    'pack10': {
        'name': '10-Video Pack',
        'quota': 15,
        'history_limit': 50,
        'price': 50,
        'price_display': '₹50',
        'price_usd': 2.99,
        'price_display_usd': '$2.99',
        'features': ['15 video analyses (+10 extra)', '50 history items', 'Priority model inference', 'Full PDF dossier export', 'Unlimited video length (1-4+ hr lectures)']
    },
    'pack50': {
        'name': '50-Video Pack',
        'quota': 55,
        'history_limit': 100,
        'price': 70,
        'price_display': '₹70',
        'price_usd': 3.99,
        'price_display_usd': '$3.99',
        'features': ['55 video analyses (+50 extra)', '100 history items', 'Priority model inference', 'Deep Copilot evidence mode', 'Unlimited video length (1-4+ hr lectures)']
    },
    'unlimited': {
        'name': 'Unlimited Pro',
        'quota': -1,
        'history_limit': 500,
        'price': 99,
        'price_display': '₹99/mo',
        'price_usd': 4.99,
        'price_display_usd': '$4.99/mo',
        'features': ['Unlimited analyses', 'Full 500-item history retention', 'Priority Model Intelligence', 'Unlimited PDF dossiers', 'Grounded Copilot Evidence Mode', 'Unlimited video length (1-4+ hr lectures)']
    }
}

def get_plan_history_limit(plan: str) -> int:
    cfg = PLAN_CONFIG.get(plan, PLAN_CONFIG['free'])
    return cfg.get('history_limit', 10)

def is_admin(password: str = None, user_id: str = None) -> bool:
    if user_id:
        user = get_user(user_id)
        if user and is_owner(user.get('email', '')):
            return True
    admin_pass = os.getenv('ADMIN_PASSWORD', '')
    if not admin_pass or not password:
        return False
    return password == admin_pass
