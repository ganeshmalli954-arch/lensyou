import os
from dotenv import load_dotenv

load_dotenv()

PLANS = {
    'anonymous': {'label': 'Guest', 'quota': 3, 'price': 0, 'price_display': 'Free'},
    'free': {'label': 'Free', 'quota': 5, 'price': 0, 'price_display': 'Free'},
    'pack10': {'label': '10-Video Pack', 'quota_grant': 10, 'price': 50, 'price_display': '₹50'},
    'pack50': {'label': '50-Video Pack', 'quota_grant': 50, 'price': 70, 'price_display': '₹70'},
    'unlimited': {'label': 'Unlimited', 'quota_grant': -1, 'price': 99, 'price_display': '₹99/mo'},
}

def get_bmc_url() -> str:
    try:
        from services.storage_service import get_system_setting
        val = get_system_setting('bmc_url')
        if val and val.strip():
            return val.strip()
    except Exception:
        pass
    return os.getenv('BMC_URL', 'https://www.buymeacoffee.com/videolens')

class _DynamicBMCUrl(str):
    def __str__(self):
        return get_bmc_url()
    def __repr__(self):
        return get_bmc_url()

BMC_URL = _DynamicBMCUrl('https://www.buymeacoffee.com/videolens')
ADMIN_PASSWORD = os.getenv('ADMIN_PASSWORD', '')
SECRET_KEY = os.getenv('FLASK_SECRET_KEY', '')

FEATURES = {
    'google_login': bool(os.getenv('GOOGLE_CLIENT_ID')),
    'twitter_login': bool(os.getenv('TWITTER_CLIENT_ID')),
    'facebook_login': bool(os.getenv('FACEBOOK_CLIENT_ID')),
    'tier3_whisper': bool(os.getenv('GROQ_API_KEY')),
    'payments_enabled': True,
}
