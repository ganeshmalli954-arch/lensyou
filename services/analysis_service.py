import os
import time
from google import genai
from google.genai import types
from utils.time_utils import prepare_transcript_for_analysis
from utils.json_utils import safe_json_parse, sanitize_data_strings
from services.storage_service import update_api_key_stat

PRIORITY_MODELS = [
    "gemini-3.5-flash-lite",
    "gemini-flash-lite-latest",
    "gemini-3.1-flash-lite",
    "gemini-3.7-flash",
    "gemini-flash-latest",
    "gemini-3.8-flash",
    "gemini-3.6-flash",
]

STANDARD_MODELS = [
    "gemini-3.5-flash-lite",
    "gemini-flash-lite-latest",
    "gemini-3.1-flash-lite",
    "gemini-flash-latest",
    "gemini-3.7-flash",
    "gemini-3.6-flash",
]

MODELS = PRIORITY_MODELS
MAX_RETRIES = 3
RETRY_DELAY = 1.5

VIDEOLENS_PROMPT = """You are LensYou, an elite video intelligence platform analyst. Analyze this entire video thoroughly across all dimensions.

VIDEO TITLE: {title}
CHANNEL: {author}
TOTAL DURATION: {duration}

TRANSCRIPT:
\"\"\"
{transcript_sample}
\"\"\"

You must produce a rich, ultra-structured JSON response with EXACTLY this structure (no markdown fences, just pure valid JSON):
{{
    "video_overview": {{
        "title": "{title}",
        "channel": "{author}",
        "estimated_duration": "{duration}",
        "content_type": "Podcast | Lecture | Tutorial | Review | Debate | Documentary | Essay",
        "content_type_confidence": 94,
        "category": "Technology | Business | Science | Education | Entertainment",
        "visual_style": "In-person interview | Presentation slides | Screen recording | Talking head",
        "overall_tone": "Informative | Inspiring | Critical | Persuasive | Analytical",
        "sentiment_label": "Positive | Neutral | Analytical | Mixed",
        "target_audience": "Target audience description",
        "summary": "High-level 2-3 paragraph executive synthesis of what the entire video covers, main arguments, and conclusions."
    }},
    "metrics": {{
        "duration": "{duration}",
        "topics_count": 8,
        "chapters_count": 6,
        "key_points_count": 10,
        "claims_count": 12,
        "sentiment": "Positive (78%)",
        "quality_score": 8.8,
        "information_density": 8.5,
        "clarity_score": 9.0,
        "depth_score": 8.4,
        "engagement_score": 8.7
    }},
    "quality_scorecard": {{
        "overall_score": 88,
        "density_score": 90,
        "clarity_score": 92,
        "structure_score": 94,
        "engagement_score": 87,
        "depth_score": 85,
        "pacing_score": 80,
        "strengths": [
            "Clear logical progression from foundational concepts to advanced applications",
            "Rich concrete examples and empirical data points",
            "High actionable clarity for practitioners"
        ],
        "weaknesses": [
            "Dense middle section with rapid topic shifts",
            "Minor repetition regarding core thesis"
        ],
        "verdict": "A high-leverage watch for anyone looking to understand practical implications."
    }},
    "engagement_curve": [
        {{"time": "00:00", "seconds": 0, "score": 65, "highlight": "Introduction & Hook"}},
        {{"time": "08:15", "seconds": 495, "score": 82, "highlight": "First major paradigm shift"}},
        {{"time": "18:40", "seconds": 1120, "score": 96, "highlight": "Peak insight & turning point"}},
        {{"time": "29:10", "seconds": 1750, "score": 78, "highlight": "Technical deep-dive"}},
        {{"time": "41:30", "seconds": 2490, "score": 89, "highlight": "Strategic implications & wrap-up"}}
    ],
    "key_takeaways": [
        {{
            "id": "01",
            "title": "Short punchy headline",
            "description": "2-3 sentences explaining this takeaway and its strategic significance",
            "timestamp": "03:42",
            "seconds": 222,
            "importance": "CRITICAL",
            "confidence": "Directly stated"
        }},
        {{
            "id": "02",
            "title": "Another key takeaway",
            "description": "2-3 sentences explaining this takeaway",
            "timestamp": "18:20",
            "seconds": 1100,
            "importance": "HIGH",
            "confidence": "AI interpretation"
        }}
    ],
    "timeline": [
        {{
            "time": "00:00",
            "seconds": 0,
            "title": "Introduction & Setup",
            "description": "Overview of topics to be covered and background context",
            "type": "key_moment"
        }},
        {{
            "time": "12:30",
            "seconds": 750,
            "title": "Core Problem Definition",
            "description": "Explains foundational challenge discussed",
            "type": "topic_shift"
        }}
    ],
    "chapters": [
        {{
            "number": "01",
            "title": "Introduction & Overview",
            "start_time": "00:00",
            "end_time": "05:20",
            "start_seconds": 0,
            "summary": "Brief 1-2 sentence chapter summary",
            "key_points": ["First point", "Second point"]
        }}
    ],
    "topics": [
        {{
            "name": "Topic Name",
            "percentage": 35,
            "subtopics": ["Subtopic A", "Subtopic B"]
        }}
    ],
    "speakers": [
        {{
            "speaker": "Speaker 1 Name",
            "percentage": 60,
            "words_estimate": "4,500",
            "questions_count": 8,
            "role": "Host / Presenter"
        }},
        {{
            "speaker": "Speaker 2 Name",
            "percentage": 40,
            "words_estimate": "3,100",
            "questions_count": 2,
            "role": "Guest / Expert"
        }}
    ],
    "insights": [
        {{
            "category": "KEY INSIGHT",
            "text": "Core transformative insight",
            "explanation": "Why this insight matters",
            "timestamp": "12:42",
            "seconds": 762,
            "confidence": "Directly stated"
        }}
    ],
    "quotes": [
        {{
            "quote": "Memorable direct quote from video",
            "speaker": "{author}",
            "timestamp": "02:14",
            "seconds": 134,
            "context": "Context of statement"
        }}
    ],
    "claims": [
        {{
            "claim": "Statement or statistic made in the video",
            "type": "Fact | Opinion | Prediction | Statistic | Speculation",
            "confidence": "High | Medium | Low",
            "timestamp": "12:42",
            "seconds": 762,
            "context": "Source or reasoning referenced",
            "verification_note": "Direct claim stated in transcript"
        }}
    ],
    "entities": {{
        "people": [
            {{"name": "Person Name", "role": "Role / Affiliation", "timestamp": "04:12", "seconds": 252, "context": "How they were referenced"}}
        ],
        "companies": [
            {{"name": "Company / Organization", "industry": "Sector", "context": "Why discussed"}}
        ],
        "tools_software": [
            {{"name": "Tool / Framework / Book", "category": "Type", "context": "How it was recommended or used"}}
        ]
    }},
    "repetitions": [
        {{
            "idea": "Core recurring concept or argument",
            "occurrences_count": 3,
            "timestamps": ["04:10", "18:25", "35:10"],
            "seconds": [250, 1105, 2110],
            "context": "Why this point is reinforced repeatedly across the video"
        }}
    ],
    "contradictions": [
        {{
            "topic": "Subject of contrast or tension",
            "statement_a": {{"text": "First statement or perspective", "timestamp": "10:15", "seconds": 615}},
            "statement_b": {{"text": "Nuanced opposing statement or counter-weight", "timestamp": "28:40", "seconds": 1720}},
            "nuance": "Nuanced explanation of whether this is a shift in context, evolving argument, or direct tension"
        }}
    ],
    "learning": {{
        "key_definitions": [
            {{"term": "Key Concept Term", "definition": "Clear concise explanation of concept", "timestamp": "06:30", "seconds": 390}}
        ],
        "study_notes": [
            {{
                "heading": "Core Theme or Section",
                "bullets": [
                    "Concise synthesis of primary learning point",
                    "Second critical takeaway or framework"
                ]
            }}
        ],
        "flashcards": [
            {{
                "front": "Question testing knowledge of core concept discussed in video?",
                "back": "Clear, precise answer grounded directly in the video content.",
                "concept": "Topic Category",
                "timestamp": "14:20",
                "seconds": 860
            }}
        ],
        "quiz": [
            {{
                "question": "Multiple choice question testing understanding of key argument?",
                "options": ["Option A", "Option B", "Option C", "Option D"],
                "correct_index": 0,
                "explanation": "Explanation linking directly to what was stated around timestamp."
            }}
        ]
    }},
    "creator_repurposing": {{
        "viral_clips": [
            {{
                "clip_id": "01",
                "title": "Punchy Catchy Hook Title",
                "hook": "Compelling opening hook sentence for Shorts/Reels...",
                "start_time": "08:15",
                "end_time": "09:00",
                "start_seconds": 495,
                "end_seconds": 540,
                "viral_score": 92,
                "rationale": "High emotional or counter-intuitive punchline"
            }}
        ],
        "social_posts": {{
            "twitter_thread": [
                "1/4 🧵 Breakdown of key insights from {title} by {author}:",
                "2/4 Key takeaway & data: ...",
                "3/4 Most surprising finding: ...",
                "4/4 Final verdict & practical action item."
            ],
            "linkedin_post": "Comprehensive professional takeaway post formatted for LinkedIn with bullets and discussion CTA...",
            "newsletter_edition": {{
                "subject": "Executive briefing: {title}",
                "intro": "High level context and why this matters now...",
                "key_bullets": ["Core finding 1", "Core finding 2", "Core finding 3"],
                "action_item": "One thing to implement or think about today."
            }}
        }},
        "youtube_chapters_raw": "00:00 Introduction\\n05:15 Foundations\\n14:30 Breakthrough Concept\\n28:00 Case Study & Application\\n40:15 Strategic Outlook"
    }},
    "visual_moments": [
        {{
            "timestamp": "03:45",
            "seconds": 225,
            "scene_type": "Slide",
            "title": "Core Conceptual Architecture",
            "ocr_text": "Key terms and labels visible on screen",
            "takeaway": "Visual explanation of system components"
        }},
        {{
            "timestamp": "16:20",
            "seconds": 980,
            "scene_type": "Chart",
            "title": "Data Distribution Benchmark",
            "ocr_text": "X-axis metrics and benchmark comparison",
            "takeaway": "Highlights significant empirical delta"
        }}
    ],
    "knowledge_graph": {{
        "nodes": [
            {{"id": "n1", "label": "Core Subject", "type": "main", "occurrences": 8, "timestamp": "00:00"}},
            {{"id": "n2", "label": "Primary Concept", "type": "topic", "occurrences": 5, "timestamp": "08:15"}},
            {{"id": "n3", "label": "Secondary Framework", "type": "topic", "occurrences": 4, "timestamp": "16:20"}},
            {{"id": "n4", "label": "Key Entity/Tool", "type": "entity", "occurrences": 3, "timestamp": "24:00"}}
        ],
        "links": [
            {{"source": "n1", "target": "n2", "relation": "explores"}},
            {{"source": "n2", "target": "n3", "relation": "implemented via"}},
            {{"source": "n3", "target": "n4", "relation": "relies on"}}
        ]
    }},
    "executive_assessment": {{
        "best_for": ["Students", "Entrepreneurs", "Researchers", "Practitioners"],
        "recommendation": "A concise 2-sentence verdict on whether and why someone should watch this video."
    }}
}}

CRITICAL INSTRUCTIONS:
1. Divide the video into realistic chapters (5 to 12 for standard, 8 to 20 for long university lectures) and key timeline moments that span across the ENTIRE duration ({duration}) from 00:00 to the very end.
2. In key_takeaways, mark the most important points as 'CRITICAL' and others as 'HIGH' or 'MEDIUM'.
3. In claims, classify each as 'Fact', 'Opinion', 'Prediction', 'Statistic', or 'Speculation' with confidence 'High', 'Medium', or 'Low'.
4. In repetitions, identify concepts or phrases reiterated across multiple timestamps.
5. In learning, provide at least 4-8 key definitions, 4-8 in-depth study note sections (structured with key concepts, mechanisms, and exam-grade explanations ideal for university students), 6-12 flashcards, and 4-6 multiple-choice quiz questions with correct_index (0-3).
6. In creator_repurposing, provide 3-6 high-potential viral clip segments with exact timestamps, titles, and viral hooks, plus complete social posts and raw YouTube chapters.
7. In visual_moments, provide 3-8 key visual moments with scene_type ('Slide', 'Chart', 'Demo', 'Screen', 'Speaker', 'Diagram') and what on-screen content or OCR text was displayed.
8. In knowledge_graph, provide 6-12 interconnected concept nodes and directional links.
9. Make every timestamp accurate and realistic based on transcript progression spanning the whole duration up to {duration}.
10. Return ONLY valid JSON, with no wrapping markdown fences.
11. Return clean text values in all JSON fields. NEVER include raw markdown bold asterisks (**) inside JSON string values."""


def _call_model(model: str, contents, client, response_mime_type=None, retries=MAX_RETRIES):
    config_params = {"temperature": 0.2}
    if response_mime_type:
        config_params["response_mime_type"] = response_mime_type

    for attempt in range(retries):
        try:
            response = client.models.generate_content(
                model=model, 
                contents=contents,
                config=types.GenerateContentConfig(**config_params)
            )
            return response
        except Exception as e:
            error_str = str(e)
            is_overload = any(code in error_str for code in ['503', 'UNAVAILABLE', '429', 'RESOURCE_EXHAUSTED', 'overloaded', 'deadline'])
            if is_overload and attempt < retries - 1:
                wait = RETRY_DELAY * (attempt + 1)
                print(f"  [Model Busy: {model}] Temporary spike, retrying in {wait}s ({attempt+1}/{retries})...", flush=True)
                time.sleep(wait)
            else:
                raise

class GeminiResponseWrapper:
    def __init__(self, raw_response, model: str):
        self._raw = raw_response
        self.text = getattr(raw_response, 'text', '')
        self.used_model = model

    def __getattr__(self, name):
        return getattr(self._raw, name)

def call_gemini_with_fallback(contents, response_mime_type=None, key_pool=None, is_paid=False):
    if not key_pool:
        key = os.getenv('GEMINI_API_KEY')
        if not key: raise ValueError("No API key configured")
        key_pool = [(0, key)]
        
    models_to_try = PRIORITY_MODELS if is_paid else STANDARD_MODELS
    last_error = None
    
    for idx, key in key_pool:
        client = genai.Client(api_key=key)
        key_prefix = key[:8]
        for model in models_to_try:
            try:
                tier_tag = "PREMIUM" if is_paid else "STANDARD"
                print(f"  [{tier_tag}] Running {model} with key {key_prefix}...", flush=True)
                response = _call_model(model, contents, client, response_mime_type=response_mime_type)
                update_api_key_stat(idx, key_prefix, increment_requests=1)
                print(f"  [{tier_tag}] Success with {model}!", flush=True)
                return GeminiResponseWrapper(response, model)
            except Exception as e:
                last_error = e
                update_api_key_stat(idx, key_prefix, increment_requests=1, error=str(e)[:100])
                print(f"  [Fallback] Model {model} unavailable ({str(e)[:70]}), trying next model...", flush=True)
                if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e):
                    print(f"  [Key Rate Limit] Key {key_prefix} rate limited, switching to next key...", flush=True)
                    break
                # otherwise try next model with same key
                continue
    raise last_error

def _ensure_complete_schema(data: dict, duration_str: str, video_title: str, author_name: str) -> dict:
    if not isinstance(data, dict):
        data = {}
    ov = data.setdefault("video_overview", {})
    ov.setdefault("title", video_title or "YouTube Video")
    ov.setdefault("channel", author_name or "Content Creator")
    ov.setdefault("estimated_duration", duration_str or "N/A")
    ov.setdefault("content_type", "Podcast")
    ov.setdefault("content_type_confidence", 92)
    ov.setdefault("category", "Technology")
    ov.setdefault("visual_style", "Presentation")
    ov.setdefault("overall_tone", "Informative")
    ov.setdefault("sentiment_label", "Positive")
    ov.setdefault("target_audience", "General audience")
    ov.setdefault("summary", "Executive summary unavailable.")

    m = data.setdefault("metrics", {})
    m.setdefault("duration", duration_str or "N/A")
    m.setdefault("topics_count", len(data.get("topics", [])) or 6)
    m.setdefault("chapters_count", len(data.get("chapters", [])) or 5)
    m.setdefault("key_points_count", len(data.get("key_takeaways", [])) or 8)
    m.setdefault("claims_count", len(data.get("claims", [])) or 10)
    m.setdefault("sentiment", "Positive (82%)")
    m.setdefault("quality_score", 8.8)
    m.setdefault("information_density", 8.5)
    m.setdefault("clarity_score", 9.0)
    m.setdefault("depth_score", 8.4)
    m.setdefault("engagement_score", 8.7)
    
    if not data.get("engagement_curve"):
        data["engagement_curve"] = [
            {"time": "00:00", "seconds": 0, "score": 68, "highlight": "Intro"},
            {"time": "05:00", "seconds": 300, "score": 82, "highlight": "Core"}
        ]
    return data

def run_videolens_analysis(segments: list, duration_str: str, video_title: str, author_name: str, key_pool=None, is_paid=False) -> dict:
    max_chars = 600000 if is_paid else 500000
    transcript_sample = prepare_transcript_for_analysis(segments, max_chars=max_chars)
    
    extra_instructions = ""
    if is_paid:
        extra_instructions = "\n\nPREMIUM DIRECTIVE: Provide deep analytical granularity, comprehensive timestamps, rich takeaways with 'CRITICAL' ratings, detailed claims verification, and thorough study notes."

    prompt = VIDEOLENS_PROMPT.format(
        title=video_title or "YouTube Video",
        author=author_name or "Content Creator",
        duration=duration_str or "Full Length",
        transcript_sample=transcript_sample
    ) + extra_instructions

    response = call_gemini_with_fallback(prompt, response_mime_type="application/json", key_pool=key_pool, is_paid=is_paid)
    data = safe_json_parse(response.text)
    data = sanitize_data_strings(data)
    data = _ensure_complete_schema(data, duration_str, video_title, author_name)
    data["_is_premium"] = is_paid
    data["_model_used"] = getattr(response, "used_model", "Gemini 3.6 Flash")

    # Safety: check if generated chapters or engagement curve points show a longer lecture
    last_known_sec = 0
    from services.metadata_service import parse_duration_string
    for ch in data.get("chapters", []):
        t_str = ch.get("timestamp") or ch.get("time") or ""
        s = parse_duration_string(t_str)
        if s > last_known_sec:
            last_known_sec = s
    for pt in data.get("engagement_curve", []):
        s = pt.get("seconds", 0)
        if s > last_known_sec:
            last_known_sec = s

    if last_known_sec > 600 and (not duration_str or duration_str in ["N/A", "10:00", "00:00"]):
        from utils.time_utils import format_seconds
        duration_str = format_seconds(last_known_sec + 120)

    if "metrics" in data and duration_str:
        data["metrics"]["duration"] = duration_str
    if "video_overview" in data and duration_str:
        data["video_overview"]["estimated_duration"] = duration_str
    return data
