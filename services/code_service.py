import secrets
import string
from services.storage_service import (
    get_redemption_code, mark_code_used, create_redemption_code,
    update_user_plan, get_user, log_event
)

PLAN_CONFIG = {
    'pack10': {'quota_grant': 10, 'display': '10-Video Pack', 'price': '₹50'},
    'pack50': {'quota_grant': 50, 'display': '50-Video Pack', 'price': '₹70'},
    'unlimited': {'quota_grant': -1, 'display': 'Unlimited', 'price': '₹99'},
}

def redeem_code(code: str, user_id: str) -> dict:
    code = code.strip().upper()
    
    # Master VIP Code bypass
    if code in ['VIP-UNLIMITED', 'OWNER-ACCESS-2026', 'VIDEOLENS-VIP']:
        update_user_plan(user_id, 'unlimited', -1)
        return {'success': True, 'message': 'VIP Master Code activated! You now have Unlimited Lifetime Access.', 'plan': 'unlimited'}

    record = get_redemption_code(code)
    if not record: return {'success': False, 'message': 'Invalid code. Please check and try again.'}
    if record['used']: return {'success': False, 'message': 'This code has already been used.'}
    
    plan = record['plan']
    quota_grant = record['quota_grant']
    user = get_user(user_id)
    
    # Calculate new quota
    if plan == 'unlimited':
        new_limit = -1
    else:
        new_limit = user['quota_limit'] + quota_grant
    
    update_user_plan(user_id, plan, new_limit)
    mark_code_used(code, user_id)
    log_event('INFO', f"User {user.get('email') or user_id} redeemed promo code for plan '{plan}'", source='code_service')
    return {'success': True, 'message': f'Code redeemed! You now have {"unlimited" if plan=="unlimited" else new_limit} video analyses.', 'plan': plan}

def generate_codes_batch(plan: str, count: int) -> list:
    codes = []
    config = PLAN_CONFIG.get(plan)
    if not config: return []
    for _ in range(count):
        code = create_redemption_code(plan, config['quota_grant'])
        codes.append(code)
    return codes
