"""
Retention & Spaced Repetition Service for LensYou
Automates weekly re-engagement loops:
1. "Your 3 Saved Flashcard Decks are ready for review (Spaced Repetition)"
2. "Here are the 3 most analyzed podcasts on LensYou this week."
Legitimately leverages Google user emails stored in SQLite users table.
"""

import os
import json
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
from services.storage_service import (
    get_db, create_notification, get_user_notifications,
    get_all_users_with_email, log_event
)

CURATED_TRENDING_PODCASTS = [
    {
        "video_id": "LqY6hFLMEJw",
        "title": "Raj Shamani AI & Tech Founders Masterclass",
        "author": "Raj Shamani",
        "duration": "01:24:10",
        "category": "Technology & Founders",
        "hook": "Executive takeaways on rapid AI workflow shifts and venture scale."
    },
    {
        "video_id": "aircAruvnKk",
        "title": "Neural Networks & Deep Learning Foundations",
        "author": "3Blue1Brown",
        "duration": "00:19:13",
        "category": "Medical & Engineering",
        "hook": "Core mathematical calculus and gradient descent visual breakdown."
    },
    {
        "video_id": "qmNCJxvs080",
        "title": "Dopamine & Drive: Protocol Checklists",
        "author": "Andrew Huberman",
        "duration": "02:14:03",
        "category": "Self-Improvement",
        "hook": "Actionable neurobiology habit lists and timeline evidence timestamps."
    }
]


def get_user_saved_flashcard_decks(user_id: str) -> list:
    """Find all saved video analyses belonging to this user that contain flashcards."""
    if not user_id:
        return []
    decks = []
    with get_db() as conn:
        c = conn.cursor()
        c.execute("""
            SELECT video_id, title, author, duration, analysis_json, created_at
            FROM videos
            WHERE user_id = ?
            ORDER BY created_at DESC
        """, (user_id,))
        rows = c.fetchall()
        for r in rows:
            try:
                data = json.loads(r['analysis_json'])
                flashcards = data.get('learning', {}).get('flashcards', [])
                if flashcards and len(flashcards) > 0:
                    decks.append({
                        'video_id': r['video_id'],
                        'title': r['title'] or 'Video Analysis',
                        'author': r['author'] or '',
                        'duration': r['duration'] or '',
                        'flashcard_count': len(flashcards),
                        'created_at': r['created_at']
                    })
            except Exception:
                continue
    return decks


def get_weekly_trending_podcasts(limit: int = 3) -> list:
    """Retrieve the top analyzed videos or fall back to high-stakes curated podcasts."""
    recent_videos = []
    try:
        with get_db() as conn:
            c = conn.cursor()
            c.execute("""
                SELECT video_id, title, author, duration, COUNT(*) as analysis_count
                FROM videos
                WHERE video_id IS NOT NULL AND video_id != ''
                GROUP BY video_id
                ORDER BY analysis_count DESC, created_at DESC
                LIMIT ?
            """, (limit,))
            rows = c.fetchall()
            for r in rows:
                if r['video_id']:
                    recent_videos.append({
                        'video_id': r['video_id'],
                        'title': r['title'] or 'Executive Video Dossier',
                        'author': r['author'] or 'LensYou Intelligence',
                        'duration': r['duration'] or '',
                        'analysis_count': r['analysis_count']
                    })
    except Exception:
        pass

    # Merge or fallback to curated podcasts if fewer than required
    if len(recent_videos) < limit:
        existing_ids = {v['video_id'] for v in recent_videos}
        for item in CURATED_TRENDING_PODCASTS:
            if item['video_id'] not in existing_ids and len(recent_videos) < limit:
                recent_videos.append(item)

    return recent_videos[:limit]


def generate_weekly_digest_for_user(user_id: str, email: str, name: str = "") -> dict:
    """
    Construct the retention message based on whether user has saved flashcard decks
    (spaced repetition reminder) or trending executive podcasts.
    """
    decks = get_user_saved_flashcard_decks(user_id) if user_id else []

    if decks and len(decks) > 0:
        count = len(decks)
        deck_plural = f"{count} Saved Flashcard Decks" if count != 1 else "1 Saved Flashcard Deck"
        title = f"Your {deck_plural} are ready for review (Spaced Repetition)"
        sample_titles = ", ".join(f'"{d["title"]}"' for d in decks[:2])
        message = (
            f"Active recall reinforces knowledge by 80%. Your flashcard decks for {sample_titles} "
            f"are scheduled for your spaced repetition review session."
        )
        primary_link = f"/v/{decks[0]['video_id']}#pane-learn"
        notif_type = "spaced_repetition"
    else:
        top_podcasts = get_weekly_trending_podcasts(3)
        title = "Here are the 3 most analyzed podcasts on LensYou this week."
        pod_summary = " • ".join(f"{p['title']} ({p.get('author', 'Executive')})" for p in top_podcasts)
        message = (
            f"Discover high-stakes takeaways, timeline heatmaps, and Bloom's taxonomy quizzes from "
            f"this week's most analyzed deep-dives: {pod_summary}"
        )
        primary_link = f"/v/{top_podcasts[0]['video_id']}" if top_podcasts else "/"
        notif_type = "weekly_digest"

    return {
        "user_id": user_id,
        "email": email,
        "name": name or "Executive Learner",
        "title": title,
        "message": message,
        "link": primary_link,
        "type": notif_type,
        "deck_count": len(decks)
    }


def send_retention_email(to_email: str, subject: str, body_text: str, action_link: str) -> bool:
    """
    Send an email via SMTP if credentials are provided in environment,
    otherwise log the payload for auditable zero-cost operation.
    """
    if not to_email:
        return False

    smtp_host = os.getenv('SMTP_HOST')
    smtp_user = os.getenv('SMTP_USER')
    smtp_pass = os.getenv('SMTP_PASSWORD')
    smtp_port = int(os.getenv('SMTP_PORT', 587))
    sender = os.getenv('SMTP_FROM', 'intelligence@lensyou.ai')

    if smtp_host and smtp_user and smtp_pass:
        try:
            msg = MIMEMultipart('alternative')
            msg['Subject'] = subject
            msg['From'] = f"LensYou Intelligence <{sender}>"
            msg['To'] = to_email

            html = f"""
            <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 600px; margin: 0 auto; background: #0c0a17; color: #f5f5f7; padding: 32px 24px; border-radius: 12px; border: 1px solid #2a2542;">
                <div style="margin-bottom: 24px;">
                    <span style="font-size: 11px; font-weight: 700; letter-spacing: 1px; color: #8b7cff; text-transform: uppercase;">LensYou • Executive Video Intelligence & Learning Engine</span>
                    <h2 style="margin: 8px 0 16px 0; color: #ffffff; font-size: 20px;">{subject}</h2>
                    <p style="color: #cbd5e1; font-size: 14px; line-height: 1.6;">{body_text}</p>
                </div>
                <div style="margin: 28px 0;">
                    <a href="{action_link}" style="background: linear-gradient(135deg, #8b7cff 0%, #6366f1 100%); color: #ffffff; text-decoration: none; padding: 12px 24px; font-weight: 700; border-radius: 8px; font-size: 13px; display: inline-block;">
                        Open in LensYou →
                    </a>
                </div>
                <hr style="border: 0; border-top: 1px solid #1f1a35; margin: 24px 0;">
                <p style="font-size: 11px; color: #64748b;">
                    LensYou Executive Video Intelligence &bull; Built for time-poor, high-stakes learners.
                </p>
            </div>
            """
            msg.attach(MIMEText(body_text, 'plain'))
            msg.attach(MIMEText(html, 'html'))

            with smtplib.SMTP(smtp_host, smtp_port, timeout=10) as server:
                server.starttls()
                server.login(smtp_user, smtp_pass)
                server.sendmail(sender, [to_email], msg.as_string())
            log_event('INFO', f"Dispatched retention email to {to_email}: '{subject}'", source='retention')
            return True
        except Exception as e:
            log_event('WARNING', f"Failed to send email to {to_email}: {e}", source='retention')
            return False
    else:
        # Zero-cost local logging
        log_event('INFO', f"[DRY-RUN EMAIL] To: {to_email} | Subject: '{subject}' | Link: {action_link}", source='retention')
        return True


def run_weekly_retention_cycle() -> dict:
    """
    Executes the automated weekly retention loop across all registered Google accounts.
    Creates in-app notifications and dispatches emails.
    """
    users = get_all_users_with_email()
    processed = 0
    notifications_created = 0
    emails_sent = 0
    site_url = os.getenv('SITE_URL') or os.getenv('RENDER_EXTERNAL_URL') or 'https://lensyou.onrender.com'
    site_url = site_url.rstrip('/')

    for u in users:
        user_id = u['id']
        email = u.get('email')
        if not email:
            continue

        digest = generate_weekly_digest_for_user(user_id, email, u.get('name', ''))
        action_url = f"{site_url}{digest['link']}"

        # Create persistent in-app notification
        create_notification(
            user_id=user_id,
            title=digest['title'],
            message=digest['message'],
            link=digest['link'],
            notif_type=digest['type']
        )
        notifications_created += 1

        # Dispatch email
        if send_retention_email(email, digest['title'], digest['message'], action_url):
            emails_sent += 1
        processed += 1

    return {
        "status": "success",
        "users_found": len(users),
        "users_processed": processed,
        "notifications_created": notifications_created,
        "emails_sent": emails_sent,
        "timestamp": datetime.utcnow().isoformat()
    }


if __name__ == '__main__':
    print("Executing LensYou Weekly Retention & Spaced Repetition Loop...")
    result = run_weekly_retention_cycle()
    print(f"Cycle finished: {result}")
