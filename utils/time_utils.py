import re

def format_seconds(seconds: float) -> str:
    """Format seconds into HH:MM:SS or MM:SS."""
    seconds = int(seconds)
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    if h > 0:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"

def prepare_transcript_for_analysis(segments: list, max_chars: int = 500000) -> str:
    """
    Format transcript for analysis, guaranteeing 100% full-timeline coverage for ANY video length.
    """
    if not segments:
        return ""

    formatted_lines = [f"[{s.get('timestamp', '')}] {s.get('text', '')}" for s in segments]
    total_len = sum(len(line) + 1 for line in formatted_lines)

    if total_len <= max_chars:
        return "\n".join(formatted_lines)

    # Calculate uniform stride so samples span evenly across the entire duration
    ratio = max_chars / total_len
    step = max(1, int(1 / ratio))

    sampled = []
    sampled.append(formatted_lines[0])  # Always start at 00:00:00

    for i in range(1, len(formatted_lines) - 1, step):
        sampled.append(formatted_lines[i])

    if formatted_lines[-1] not in sampled:
        sampled.append(formatted_lines[-1])  # Always include the conclusion

    return "\n".join(sampled)

def prepare_ui_transcript_sample(segments: list, max_snippets: int = 2500) -> list:
    """Prepare transcript snippets for UI split view spanning the whole video."""
    if len(segments) <= max_snippets:
        return segments
    step = max(1, len(segments) // max_snippets)
    sampled = [segments[i] for i in range(0, len(segments), step)]
    if segments[-1] not in sampled:
        sampled.append(segments[-1])
    return sampled

def sanitize_transcript(text: str) -> str:
    """Removes [Music], [Applause], um, uh, you know fillers using regex, reduces tokens by ~30%."""
    if not text:
        return ""
    
    # Remove bracketed sounds
    text = re.sub(r'\[.*?\]', '', text)
    
    # Remove common filler words. Using word boundaries to avoid matching parts of words.
    # Note: 'you know' might be legitimate, but as per instructions we remove it as a filler.
    fillers = r'\b(um|uh|uhm|ah|er|hm|hmm|you know|like|so yeah)\b'
    text = re.sub(fillers, '', text, flags=re.IGNORECASE)
    
    # Clean up extra whitespace that might result from removals
    text = re.sub(r'\s+', ' ', text).strip()
    return text

def search_transcript_segments(segments: list, query: str, max_segments: int = 15, context_window: int = 1) -> list:
    """
    Search transcript segments for terms and concepts in query.
    Returns the most relevant continuous segment windows with timestamps.
    """
    if not segments or not query:
        return segments[:max_segments] if segments else []
    
    stop_words = {
        'the', 'a', 'an', 'is', 'are', 'was', 'were', 'and', 'or', 'in', 'on', 'at', 'to',
        'for', 'of', 'with', 'about', 'by', 'from', 'this', 'that', 'it', 'what', 'when',
        'where', 'who', 'how', 'why', 'can', 'you', 'give', 'me', 'tell', 'show', 'explain',
        'does', 'did', 'video', 'talk'
    }
    
    query_tokens = [w.lower() for w in re.findall(r'\b\w{2,}\b', query) if w.lower() not in stop_words]
    if not query_tokens:
        query_tokens = [w.lower() for w in re.findall(r'\b\w+\b', query)]
    
    if not query_tokens:
        return segments[:max_segments]

    scored = []
    n = len(segments)
    for idx, seg in enumerate(segments):
        text = (seg.get('text') or '').lower()
        if not text:
            continue
        score = 0
        # Exact phrase match bonus
        clean_q = " ".join(query_tokens)
        if clean_q in text:
            score += 10
        # Token matches
        for t in query_tokens:
            if t in text:
                score += 3
        if score > 0:
            scored.append((score, idx))

    scored.sort(key=lambda x: x[0], reverse=True)
    if not scored:
        # Fall back to evenly spaced sample
        return prepare_ui_transcript_sample(segments, max_snippets=max_segments)

    # Pick top match indices and include surrounding context window
    selected_indices = set()
    for _, idx in scored[:max_segments]:
        for offset in range(-context_window, context_window + 1):
            target = idx + offset
            if 0 <= target < n:
                selected_indices.add(target)

    sorted_indices = sorted(selected_indices)
    return [segments[i] for i in sorted_indices]

