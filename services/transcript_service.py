import os
import re
import json
import uuid
import subprocess
from youtube_transcript_api import YouTubeTranscriptApi
from utils.time_utils import format_seconds

def get_transcript_tier1(video_id: str) -> dict:
    try:
        ytt_api = YouTubeTranscriptApi()
        fetched = None

        try:
            fetched = ytt_api.fetch(video_id)
        except Exception:
            pass

        if not fetched:
            try:
                t_list = ytt_api.list(video_id)
                target = None
                for t in t_list:
                    if not t.is_generated and t.language_code.startswith("en"):
                        target = t
                        break
                if not target:
                    for t in t_list:
                        if t.is_generated and t.language_code.startswith("en"):
                            target = t
                            break
                if not target:
                    for t in t_list:
                        if t.is_translatable:
                            try:
                                fetched = t.translate('en').fetch()
                                break
                            except Exception:
                                pass
                if not target and not fetched:
                    for t in t_list:
                        if not t.is_generated:
                            target = t
                            break
                if not target and not fetched:
                    target = next(iter(t_list), None)

                if target and not fetched:
                    fetched = target.fetch()
            except Exception as e_list:
                print(f"  [Transcript Tier 1] List notice: {e_list}", flush=True)

        if not fetched:
            return {"error": "Tier 1: No subtitles found"}

        snippets_raw = fetched.snippets if hasattr(fetched, "snippets") else fetched
        segments = []
        for s in snippets_raw:
            text = getattr(s, "text", "") if not isinstance(s, dict) else s.get("text", "")
            start = getattr(s, "start", 0) if not isinstance(s, dict) else s.get("start", 0)
            duration = getattr(s, "duration", 0) if not isinstance(s, dict) else s.get("duration", 0)
            if text and text.strip():
                segments.append({
                    "text": text.strip(),
                    "start": float(start),
                    "duration": float(duration),
                    "timestamp": format_seconds(float(start))
                })

        if not segments:
            return {"error": "Tier 1: Transcript empty"}

        full_text = " ".join([s["text"] for s in segments])
        duration_seconds = max((s["start"] + s["duration"] for s in segments), default=0)

        return {
            "text": full_text,
            "segments": segments,
            "duration_seconds": duration_seconds,
            "formatted_duration": format_seconds(duration_seconds),
            "segment_count": len(segments)
        }
    except Exception as e:
        return {"error": f"Tier 1 error: {e}"}

def parse_vtt(vtt_text: str) -> list:
    segments = []
    lines = vtt_text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if '-->' in line:
            parts = line.split('-->')
            if len(parts) == 2:
                start_str = parts[0].strip()
                end_str = parts[1].strip().split(' ')[0]
                
                # Parse start time
                start_parts = start_str.replace(',', '.').split(':')
                start_secs = 0
                if len(start_parts) == 3:
                    start_secs = float(start_parts[0])*3600 + float(start_parts[1])*60 + float(start_parts[2])
                elif len(start_parts) == 2:
                    start_secs = float(start_parts[0])*60 + float(start_parts[1])
                
                # Parse end time
                end_parts = end_str.replace(',', '.').split(':')
                end_secs = 0
                if len(end_parts) == 3:
                    end_secs = float(end_parts[0])*3600 + float(end_parts[1])*60 + float(end_parts[2])
                elif len(end_parts) == 2:
                    end_secs = float(end_parts[0])*60 + float(end_parts[1])
                
                text_lines = []
                i += 1
                while i < len(lines) and lines[i].strip() and '-->' not in lines[i]:
                    clean_line = re.sub(r'<[^>]+>', '', lines[i].strip())
                    if clean_line:
                        text_lines.append(clean_line)
                    i += 1
                
                if text_lines:
                    text = ' '.join(text_lines)
                    # deduplicate lines that are often repeated in auto-subs
                    if not segments or segments[-1]['text'] != text:
                        segments.append({
                            "text": text,
                            "start": start_secs,
                            "duration": max(0, end_secs - start_secs),
                            "timestamp": format_seconds(start_secs)
                        })
                continue
        i += 1
    return segments

def get_transcript_tier2(video_id: str) -> dict:
    try:
        tmp_id = str(uuid.uuid4())
        cmd = [
            'yt-dlp',
            '--write-sub',
            '--write-auto-sub',
            '--skip-download',
            '--sub-format', 'vtt',
            '--sub-lang', 'en,en-orig,en-US,en-GB,hi',
            '--no-playlist',
            '--extractor-args', 'youtube:player_client=android,web',
            '-o', f'{tmp_id}.%(ext)s',
            f'https://www.youtube.com/watch?v={video_id}'
        ]
        subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        
        vtt_file = None
        for f in os.listdir('.'):
            if f.startswith(tmp_id) and f.endswith('.vtt'):
                vtt_file = f
                break
                
        if not vtt_file:
            # cleanup any left over files
            for f in os.listdir('.'):
                if f.startswith(tmp_id):
                    os.remove(f)
            return {"error": "Tier 2: yt-dlp failed to download subtitles"}
            
        with open(vtt_file, 'r', encoding='utf-8') as f:
            vtt_content = f.read()
            
        os.remove(vtt_file)
        
        segments = parse_vtt(vtt_content)
        if not segments:
            return {"error": "Tier 2: Failed to parse VTT"}
            
        full_text = " ".join([s["text"] for s in segments])
        duration_seconds = max((s["start"] + s["duration"] for s in segments), default=0)

        return {
            "text": full_text,
            "segments": segments,
            "duration_seconds": duration_seconds,
            "formatted_duration": format_seconds(duration_seconds),
            "segment_count": len(segments)
        }
    except Exception as e:
        return {"error": f"Tier 2 error: {e}"}

def get_transcript_tier3(video_id: str) -> dict:
    groq_api_key = os.getenv('GROQ_API_KEY')
    if not groq_api_key:
        return {"error": "Tier 3: GROQ_API_KEY not set"}
        
    try:
        from groq import Groq
        client = Groq(api_key=groq_api_key)
        
        tmp_id = str(uuid.uuid4())
        # download lowest quality audio
        cmd = [
            'yt-dlp',
            '-f', 'worstaudio[ext=m4a]/worstaudio',
            '-o', f'{tmp_id}.%(ext)s',
            f'https://www.youtube.com/watch?v={video_id}'
        ]
        subprocess.run(cmd, capture_output=True, text=True)
        
        audio_file = None
        for f in os.listdir('.'):
            if f.startswith(tmp_id):
                audio_file = f
                break
                
        if not audio_file:
            return {"error": "Tier 3: Failed to download audio"}
            
        with open(audio_file, "rb") as file:
            transcription = client.audio.transcriptions.create(
              file=(audio_file, file.read()),
              model="whisper-large-v3-turbo",
              response_format="verbose_json",
            )
            
        os.remove(audio_file)
        
        segments = []
        if hasattr(transcription, 'segments') and transcription.segments:
            for s in transcription.segments:
                segments.append({
                    "text": s.text.strip(),
                    "start": float(s.start),
                    "duration": max(0, float(s.end) - float(s.start)),
                    "timestamp": format_seconds(float(s.start))
                })
        
        if not segments:
             return {"error": "Tier 3: Whisper transcription empty"}
             
        full_text = " ".join([s["text"] for s in segments])
        duration_seconds = max((s["start"] + s["duration"] for s in segments), default=0)

        return {
            "text": full_text,
            "segments": segments,
            "duration_seconds": duration_seconds,
            "formatted_duration": format_seconds(duration_seconds),
            "segment_count": len(segments)
        }
    except Exception as e:
        # cleanup
        for f in os.listdir('.'):
            if f.startswith(tmp_id):
                try: os.remove(f)
                except: pass
        return {"error": f"Tier 3 error: {e}"}

def get_transcript_tier4_metadata(video_id: str) -> dict:
    """Fallback tier when a video has no subtitles or YouTube restricts cloud IP:
    Extracts video metadata, full description, and chapter timestamps to synthesize
    accurate timeline segments so Gemini can perform full deep analysis.
    """
    try:
        import urllib.request
        from services.metadata_service import get_video_oembed, get_video_duration_seconds
        
        oembed = get_video_oembed(video_id)
        title = oembed.get("title", f"YouTube Video ({video_id})")
        author = oembed.get("author_name", "YouTube Creator")

        desc = ""
        duration_secs = get_video_duration_seconds(video_id) or 600

        # Scrape YouTube watch page for description, length, and chapters
        try:
            url = f"https://www.youtube.com/watch?v={video_id}"
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept-Language': 'en-US,en;q=0.9'
            }
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=6) as resp:
                html = resp.read().decode('utf-8', errors='ignore')
                m = re.search(r'"description":\s*\{"simpleText":\s*"(.*?)"\}', html)
                if m:
                    desc = m.group(1).encode().decode('unicode-escape')
                else:
                    m2 = re.search(r'"shortDescription":\s*"(.*?)"', html)
                    if m2:
                        desc = m2.group(1).encode().decode('unicode-escape')
                
                m_len = re.search(r'"lengthSeconds":\s*"(\d+)"', html)
                if m_len:
                    duration_secs = int(m_len.group(1))
        except Exception as e_page:
            print(f"  [Transcript Tier 4] Metadata fetch note: {e_page}", flush=True)

        # Look for chapter timestamps in description e.g. "01:23 Intro" or "0:00 - Chapter 1"
        chapter_matches = re.findall(r'(?:(\d{1,2}):)?(\d{1,2}):(\d{2})\s+[-–—]?\s*([^\n\r]+)', desc)
        segments = []
        if chapter_matches:
            for match in chapter_matches:
                hrs, mins, secs, chap_title = match
                total_s = (int(hrs) * 3600 if hrs else 0) + int(mins) * 60 + int(secs)
                clean_title = chap_title.strip()
                if clean_title:
                    segments.append({
                        "text": f"Chapter: {clean_title}",
                        "start": float(total_s),
                        "duration": 60.0,
                        "timestamp": format_seconds(float(total_s))
                    })

        if not segments:
            # Construct segments from description paragraphs
            paragraphs = [p.strip() for p in desc.split('\n') if len(p.strip()) > 20]
            if paragraphs:
                step = max(30.0, duration_secs / max(len(paragraphs[:10]), 1))
                curr = 0.0
                for p in paragraphs[:10]:
                    segments.append({
                        "text": p,
                        "start": curr,
                        "duration": step,
                        "timestamp": format_seconds(curr)
                    })
                    curr += step
            else:
                # Minimum baseline segments
                segments = [
                    {"text": f"Video Overview: {title} by {author}.", "start": 0.0, "duration": float(duration_secs), "timestamp": "00:00"},
                    {"text": f"Core topics, discussion, and analysis of {title}.", "start": min(60.0, float(duration_secs)), "duration": float(max(60, duration_secs - 60)), "timestamp": "01:00"}
                ]

        full_text = " ".join([s["text"] for s in segments])
        if desc:
            full_text += f"\n\nVideo Overview & Description:\n{desc[:3000]}"

        return {
            "text": full_text,
            "segments": segments,
            "duration_seconds": duration_secs,
            "formatted_duration": format_seconds(duration_secs),
            "segment_count": len(segments),
            "is_synthesized": True
        }
    except Exception as e:
        return {"error": f"Tier 4 error: {e}"}

def get_transcript_data(video_id: str) -> dict:
    print(f"  [Transcript] Trying Tier 1 (YouTube API)...", flush=True)
    res1 = get_transcript_tier1(video_id)
    if "error" not in res1:
        print("  [Transcript] Tier 1 Success!", flush=True)
        return res1
    print(f"  [Transcript] Tier 1 Failed: {res1['error']}", flush=True)
    
    print(f"  [Transcript] Trying Tier 2 (yt-dlp VTT)...", flush=True)
    res2 = get_transcript_tier2(video_id)
    if "error" not in res2:
        print("  [Transcript] Tier 2 Success!", flush=True)
        return res2
    print(f"  [Transcript] Tier 2 Failed: {res2['error']}", flush=True)
    
    print(f"  [Transcript] Trying Tier 3 (Groq Whisper)...", flush=True)
    res3 = get_transcript_tier3(video_id)
    if "error" not in res3:
        print("  [Transcript] Tier 3 Success!", flush=True)
        return res3
    print(f"  [Transcript] Tier 3 Failed: {res3['error']}", flush=True)

    print(f"  [Transcript] Trying Tier 4 (AI Metadata & Chapter Synthesis)...", flush=True)
    res4 = get_transcript_tier4_metadata(video_id)
    if "error" not in res4 and res4.get("segments"):
        print("  [Transcript] Tier 4 Success (Synthesized Metadata)!", flush=True)
        return res4
    print(f"  [Transcript] Tier 4 Failed: {res4.get('error', 'No segments')}", flush=True)
    
    return {"error": "Could not extract transcript or metadata for this video. Please try another video."}
