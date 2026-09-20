"""
Automated Daily Database Export & Cloud Syncing Service for LensYou
Addresses Render SQLite persistence options:
1. Attach Render Persistent Disk mounted to /var/data (set DATABASE_PATH=/var/data/lensyou.db)
2. Automated daily exports/syncing of videolens.db / lensyou.db to Cloudflare R2 / Supabase / S3 bucket
"""

import os
import shutil
import sqlite3
from datetime import datetime
from services.storage_service import resolve_database_path, log_event

def export_database_snapshot(dest_dir: str = None) -> str:
    """
    Creates a consistent SQLite backup snapshot using SQLite online backup API.
    Prevents corruptions during live concurrent transactions.
    """
    src_path = resolve_database_path()
    if not os.path.exists(src_path):
        raise FileNotFoundError(f"Source database not found at {src_path}")

    if not dest_dir:
        dest_dir = os.path.join(os.path.dirname(src_path), 'backups')
    os.makedirs(dest_dir, exist_ok=True)

    timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
    filename = f"lensyou_backup_{timestamp}.db"
    dest_path = os.path.join(dest_dir, filename)

    # Safe online SQLite backup
    src_conn = sqlite3.connect(src_path)
    dest_conn = sqlite3.connect(dest_path)
    with dest_conn:
        src_conn.backup(dest_conn)
    dest_conn.close()
    src_conn.close()

    log_event('INFO', f"Database snapshot created at {dest_path}", source='backup')
    return dest_path


def sync_snapshot_to_cloud_bucket(snapshot_path: str) -> bool:
    """
    Uploads a snapshot to Cloudflare R2, AWS S3, or Supabase Storage if configured.
    Falls back gracefully if cloud bucket credentials are not provided.
    """
    s3_bucket = os.getenv('CLOUD_BACKUP_BUCKET') or os.getenv('S3_BUCKET') or os.getenv('R2_BUCKET')
    s3_endpoint = os.getenv('S3_ENDPOINT_URL') or os.getenv('R2_ENDPOINT_URL')
    access_key = os.getenv('AWS_ACCESS_KEY_ID') or os.getenv('R2_ACCESS_KEY_ID')
    secret_key = os.getenv('AWS_SECRET_ACCESS_KEY') or os.getenv('R2_SECRET_ACCESS_KEY')

    if not s3_bucket or not access_key or not secret_key:
        log_event('INFO', f"Cloud bucket not configured; preserved local snapshot at {snapshot_path}", source='backup')
        return False

    try:
        import boto3
        s3 = boto3.client(
            's3',
            endpoint_url=s3_endpoint,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key
        )
        base_name = os.path.basename(snapshot_path)
        s3.upload_file(snapshot_path, s3_bucket, f"database_backups/{base_name}")
        log_event('INFO', f"Synced snapshot {base_name} to cloud bucket {s3_bucket}", source='backup')
        return True
    except Exception as e:
        log_event('WARNING', f"Failed to sync snapshot to cloud bucket: {e}", source='backup')
        return False


def run_daily_backup_cycle() -> dict:
    """Executes a full snapshot and cloud sync cycle."""
    try:
        snapshot = export_database_snapshot()
        synced = sync_snapshot_to_cloud_bucket(snapshot)
        return {
            "status": "success",
            "snapshot_path": snapshot,
            "cloud_synced": synced,
            "timestamp": datetime.utcnow().isoformat()
        }
    except Exception as e:
        log_event('ERROR', f"Daily backup cycle error: {e}", source='backup')
        return {
            "status": "error",
            "error": str(e),
            "timestamp": datetime.utcnow().isoformat()
        }


if __name__ == '__main__':
    result = run_daily_backup_cycle()
    print(f"Daily backup finished: {result}")
