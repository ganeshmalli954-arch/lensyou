import re
import requests

def extract_video_id(url: str) -> str | None:
    """Extract YouTube video ID from various URL formats including query parameters, share links, and embeds."""
    if not url:
        return None
    url = url.strip()
    # Strip wrapping markdown brackets or angle brackets <https://...>
    url = re.sub(r'^[<\[(]|([>\])])$', '', url).strip()

    # Raw 11-character video ID
    if re.match(r'^[a-zA-Z0-9_-]{11}$', url):
        return url

    patterns = [
        r'(?:v=|\/embed\/|\/shorts\/|\/live\/|youtu\.be\/|\/v\/)([a-zA-Z0-9_-]{11})',
        r'(?:youtube\.com\/watch\?.*[&?]v=)([a-zA-Z0-9_-]{11})',
        r'(?:youtu\.be\/)([a-zA-Z0-9_-]{11})',
        r'(?:youtube\.com\/shorts\/)([a-zA-Z0-9_-]{11})',
        r'(?:youtube\.com\/live\/)([a-zA-Z0-9_-]{11})',
    ]
    for pattern in patterns:
        m = re.search(pattern, url)
        if m:
            return m.group(1)

    try:
        from urllib.parse import urlparse, parse_qs
        parsed = urlparse(url)
        if 'youtube' in parsed.netloc or 'youtu.be' in parsed.netloc:
            qs = parse_qs(parsed.query)
            if 'v' in qs and len(qs['v'][0]) == 11:
                return qs['v'][0]
    except Exception:
        pass

    return None

def get_video_oembed(video_id: str) -> dict:
    """Fetch official video metadata (title, author, thumbnail) via YouTube oEmbed."""
    try:
        url = f"https://www.youtube.com/oembed?url=https://www.youtube.com/watch?v={video_id}&format=json"
        res = requests.get(url, timeout=5)
        if res.status_code == 200:
            return res.json()
    except Exception as e:
        print(f"  [Warning] oEmbed lookup failed: {e}", flush=True)
    return {}

def parse_duration_string(dur_str: str) -> int:
    """Convert '02:44:05', '1:21:12', '14:20', or '0:45' to total integer seconds."""
    if not dur_str:
        return 0
    parts = str(dur_str).strip().split(':')
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

def get_video_duration_seconds(video_id: str) -> int:
    """Fetch exact video duration in seconds via YouTube Search data, yt-dlp, and HTML fallback."""
    if not video_id:
        return 0

    # 1. Fast, highly reliable YouTube Search query (works seamlessly in cloud/Render environments)
    try:
        results = search_youtube(f'"{video_id}"', limit=3)
        for it in results:
            if it.get('video_id') == video_id and it.get('duration'):
                secs = parse_duration_string(it['duration'])
                if secs > 0:
                    return secs
        if results and results[0].get('duration'):
            secs = parse_duration_string(results[0]['duration'])
            if secs > 0:
                return secs
    except Exception as e_search:
        print(f"  [Warning] Search duration lookup note: {e_search}", flush=True)

    # 2. yt-dlp duration extractor
    import subprocess
    try:
        cmd = [
            'yt-dlp',
            '--print', '%(duration)s',
            '--no-playlist',
            '--extractor-args', 'youtube:player_client=android,web',
            f'https://www.youtube.com/watch?v={video_id}'
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        for line in res.stdout.strip().split('\n'):
            line = line.strip()
            if line.isdigit() and int(line) > 0:
                return int(line)
    except Exception as e:
        print(f"  [Warning] yt-dlp duration lookup note: {e}", flush=True)

    # 3. Fallback to watch page lengthSeconds
    try:
        import urllib.request
        url = f"https://www.youtube.com/watch?v={video_id}"
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'})
        with urllib.request.urlopen(req, timeout=6) as resp:
            html = resp.read().decode('utf-8', errors='ignore')
            m = re.search(r'"lengthSeconds":\s*"(\d+)"', html)
            if m and int(m.group(1)) > 0:
                return int(m.group(1))
            m_ms = re.search(r'"approxDurationMs":\s*"(\d+)"', html)
            if m_ms and int(m_ms.group(1)) > 0:
                return int(int(m_ms.group(1)) / 1000)
    except Exception:
        pass

    return 0

def search_youtube(query: str, limit: int = 6) -> list:
    """Search YouTube for a query string and return top matching video records."""
    if not query:
        return []
    import urllib.request
    import urllib.parse
    import json

    encoded = urllib.parse.quote(query.strip())
    url = f"https://www.youtube.com/results?search_query={encoded}"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept-Language': 'en-US,en;q=0.9'
    }
    req = urllib.request.Request(url, headers=headers)
    results = []
    try:
        with urllib.request.urlopen(req, timeout=6) as response:
            html_text = response.read().decode('utf-8', errors='ignore')
            match = re.search(r'var ytInitialData = ({.*?});</script>', html_text)
            if match:
                try:
                    data = json.loads(match.group(1))
                    sections = data.get('contents', {}).get('twoColumnSearchResultsRenderer', {}).get('primaryContents', {}).get('sectionListRenderer', {}).get('contents', [])
                    for sec in sections:
                        items = sec.get('itemSectionRenderer', {}).get('contents', [])
                        for it in items:
                            v = it.get('videoRenderer')
                            if v and 'videoId' in v:
                                vid_id = v['videoId']
                                title = v.get('title', {}).get('runs', [{}])[0].get('text', '')
                                author = v.get('ownerText', {}).get('runs', [{}])[0].get('text', 'YouTube Creator')
                                duration = v.get('lengthText', {}).get('simpleText', '')
                                if vid_id and title:
                                    results.append({
                                        'video_id': vid_id,
                                        'title': title,
                                        'author': author,
                                        'duration': duration,
                                        'thumbnail_url': f"https://img.youtube.com/vi/{vid_id}/mqdefault.jpg"
                                    })
                                if len(results) >= limit:
                                    break
                        if len(results) >= limit:
                            break
                except Exception as je:
                    print(f"  [Warning] ytInitialData parse failed: {je}", flush=True)

            if not results:
                # Fallback: regex search on watch?v= links
                raw_ids = list(dict.fromkeys(re.findall(r'watch\?v=([a-zA-Z0-9_-]{11})', html_text)))[:limit]
                for vid in raw_ids:
                    oembed = get_video_oembed(vid)
                    results.append({
                        'video_id': vid,
                        'title': oembed.get('title') or f"{query.title()} Video",
                        'author': oembed.get('author_name') or 'YouTube Creator',
                        'duration': '',
                        'thumbnail_url': f"https://img.youtube.com/vi/{vid}/mqdefault.jpg"
                    })
    except Exception as e:
        print(f"  [Warning] search_youtube error for '{query}': {e}", flush=True)
    return results

