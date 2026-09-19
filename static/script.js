// ===== LensYou Master Intelligence Platform Controller =====
// Direction: Quiet luxury + advanced AI interface (Bloomberg-density data platform)

let currentAnalysis = null;
let currentActiveSecond = 0;
let currentFlashcardIdx = 0;
let quizUserScore = 0;
let quizAnsweredCount = 0;
let isAnalyzing = false;
let lastAttemptedUrl = '';
let selectedConceptId = null;

// LocalStorage key for session history
const STORAGE_KEY = 'videolens_history_v1';

document.addEventListener('DOMContentLoaded', () => {
    initHistory();
    setupEventListeners();
    setupCommandPalette();
    updateUsageCounter();
    loadUserState();
    checkCookieConsent();
    setInterval(updateUsageCounter, 30000);

    const urlParams = new URLSearchParams(window.location.search);
    if (urlParams.get('support') === '1') {
        setTimeout(openSupportModal, 300);
    }

    // Mobile bottom navigation listener
    document.querySelectorAll('.bottom-nav-tab').forEach(tab => {
        tab.addEventListener('click', () => switchMainMode(tab.dataset.mode));
    });

    // Restore sidebar collapsed preference
    if (localStorage.getItem('sidebarCollapsed') === 'true') {
        const sb = document.getElementById('sidebar');
        if (sb) sb.classList.add('collapsed');
    }

    // Keyboard navigation for 3D Flashcards
    window.addEventListener('keydown', (e) => {
        const learnPane = document.getElementById('pane-learn');
        if (learnPane && learnPane.classList.contains('active')) {
            if (e.key === 'ArrowRight') {
                nextFlashcard();
            } else if (e.key === 'ArrowLeft') {
                prevFlashcard();
            } else if (e.key === ' ' && document.activeElement.tagName !== 'INPUT') {
                e.preventDefault();
                flipCurrentFlashcard();
            }
        }
    });
});

function setupEventListeners() {
    const form = document.getElementById('analyzeForm');
    if (form) {
        form.addEventListener('submit', (e) => {
            e.preventDefault();
            const input = document.getElementById('youtubeUrl');
            const url = input ? input.value.trim() : '';
            if (url) {
                handleAnalyzeOrSearch(url);
            }
        });
    }

    // Global Command Palette Shortcut: Ctrl+K or Cmd+K
    window.addEventListener('keydown', (e) => {
        if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
            e.preventDefault();
            toggleCommandPalette();
        } else if (e.key === 'Escape') {
            closeCommandPalette();
            const drawer = document.getElementById('historyDrawer');
            if (drawer && drawer.classList.contains('open')) toggleHistoryDrawer();
            closeAuthModal();
            closeUpgradeModal();
            closeSupportModal();
        }
    });
}

// ===== Unified Analyze or Keyword Search Handler =====
function isDirectYouTubeUrl(str) {
    if (!str) return false;
    str = str.trim();
    if (/^[a-zA-Z0-9_-]{11}$/.test(str)) return true;
    return str.includes('youtube.com') || str.includes('youtu.be') || str.includes('/watch') || str.includes('/embed');
}

async function handleAnalyzeOrSearch(query) {
    if (!query) return;
    query = query.trim();
    if (isDirectYouTubeUrl(query)) {
        startAnalysis(query);
    } else {
        await performContentSearch(query);
    }
}

async function performContentSearch(query) {
    hideErrors();
    setAnalyzeButtonLoading(true);
    const btnText = document.getElementById('analyzeBtnText');
    if (btnText) btnText.textContent = 'Searching...';

    try {
        const res = await fetch('/api/search', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ query })
        });
        const data = await res.json();
        setAnalyzeButtonLoading(false);

        if (data.is_direct_video && data.video_id) {
            startAnalysis(data.video_id);
            return;
        }

        renderSearchResults(query, data.results || []);
        renderHistoryDrawers();
    } catch (err) {
        setAnalyzeButtonLoading(false);
        showToast('Search error: ' + err.message, 'error');
    }
}

function renderSearchResults(query, results) {
    const zone = document.getElementById('searchResultsZone');
    const grid = document.getElementById('searchResultsGrid');
    const heading = document.getElementById('searchQueryHeading');

    if (!zone || !grid) return;

    heading.textContent = `Matching Content for "${query}" (${results.length} found)`;

    if (!results.length) {
        grid.innerHTML = `
            <div style="grid-column: 1 / -1; padding: 24px; text-align: center; color: var(--text-muted); background: var(--surface-card); border: 1px solid var(--border); border-radius: 12px;">
                No videos found matching "${escapeHtml(query)}". Try a direct YouTube link or different keywords.
            </div>
        `;
        zone.style.display = 'block';
        zone.scrollIntoView({ behavior: 'smooth', block: 'start' });
        return;
    }

    grid.innerHTML = results.map(r => `
        <div class="search-result-card" style="background:var(--surface-card); border:1px solid var(--border); border-radius:12px; overflow:hidden; display:flex; flex-direction:column; transition:transform 0.2s, border-color 0.2s;">
            <div style="position:relative; aspect-ratio:16/9; background:var(--bg-primary);">
                <img src="${escapeHtml(r.thumbnail_url)}" alt="Thumb" style="width:100%; height:100%; object-fit:cover;" onerror="this.src='/static/logo.svg'">
                ${r.duration ? `<span style="position:absolute; bottom:8px; right:8px; background:rgba(0,0,0,0.8); color:#fff; font-size:11px; padding:2px 6px; border-radius:4px; font-weight:600;">${escapeHtml(r.duration)}</span>` : ''}
            </div>
            <div style="padding:14px; display:flex; flex-direction:column; flex:1; justify-content:space-between; gap:10px;">
                <div>
                    <h4 style="margin:0 0 4px 0; font-size:14px; font-weight:600; color:var(--text-primary); display:-webkit-box; -webkit-line-clamp:2; -webkit-box-orient:vertical; overflow:hidden; line-height:1.3;">${escapeHtml(r.title)}</h4>
                    <p style="margin:0; font-size:12px; color:var(--text-muted);">${escapeHtml(r.author || 'YouTube Creator')}</p>
                </div>
                <button onclick="startAnalysis('${escapeHtml(r.video_id)}')" style="width:100%; padding:8px; background:#F5F5F5; border:1px solid #FFFFFF; border-radius:6px; color:#09090B; font-weight:600; font-size:12px; cursor:pointer; display:flex; align-items:center; justify-content:center; gap:6px;">
                    <span>⚡ Analyze Video</span>
                </button>
            </div>
        </div>
    `).join('');

    zone.style.display = 'block';
    zone.scrollIntoView({ behavior: 'smooth', block: 'start' });
    showToast(`Found ${results.length} videos matching "${query}"`, 'success');
}

function clearSearchResults() {
    const zone = document.getElementById('searchResultsZone');
    if (zone) zone.style.display = 'none';
}

// ===== Quick Header Analyze Handler =====
function handleQuickAnalyze() {
    const input = document.getElementById('quickYoutubeUrl');
    const url = input ? input.value.trim() : '';
    if (url) {
        handleAnalyzeOrSearch(url);
    }
}

// ===== Screen Routing =====
function showScreen(screenId) {
    const screens = ['landingScreen', 'loadingScreen', 'dashboardScreen'];
    screens.forEach(id => {
        const el = document.getElementById(id);
        if (el) el.style.display = (id === screenId + 'Screen') ? 'block' : 'none';
    });

    const sidebar = document.getElementById('sidebar');
    if (sidebar) {
        sidebar.style.display = (screenId === 'dashboard') ? 'flex' : 'none';
    }

    // Header Quick URL Bar toggle
    const navCenter = document.getElementById('navCenterZone');
    if (navCenter) {
        if (screenId === 'dashboard') {
            navCenter.classList.remove('hidden');
            navCenter.style.display = 'flex';
        } else {
            navCenter.classList.add('hidden');
            navCenter.style.display = 'none';
        }
    }

    window.scrollTo({ top: 0, behavior: 'smooth' });
}

function startNewAnalysis() {
    hideErrors();
    const input = document.getElementById('youtubeUrl');
    if (input) {
        input.value = '';
        setTimeout(() => input.focus(), 80);
    }
    showScreen('landing');
}

function promptNewAnalysis() {
    closeCommandPalette();
    startNewAnalysis();
}

function pasteQuickUrl(url) {
    const input = document.getElementById('youtubeUrl');
    if (input) {
        input.value = url;
        startAnalysis(url);
    }
}

function scrollToElement(elementId) {
    const el = document.getElementById(elementId);
    if (el) {
        switchMainMode('understand');
        setTimeout(() => {
            el.scrollIntoView({ behavior: 'smooth', block: 'start' });
        }, 80);
    }
}

// ===== Error & Loading State Management =====
function hideErrors() {
    const landingErr = document.getElementById('landingErrorBox');
    if (landingErr) {
        landingErr.textContent = '';
        landingErr.style.display = 'none';
    }
    const pipeErr = document.getElementById('pipelineErrorContainer');
    if (pipeErr) {
        pipeErr.style.display = 'none';
    }
}

function showPipelineError(msg) {
    let cleanMsg = msg || 'An error occurred during analysis.';
    if (typeof cleanMsg === 'string') {
        if (cleanMsg.includes('503') || cleanMsg.includes('UNAVAILABLE') || cleanMsg.toLowerCase().includes('high demand')) {
            cleanMsg = "Google AI is currently experiencing a temporary global demand spike. Please wait a few moments and click 'Try Again'.";
        } else if (cleanMsg.includes('429') || cleanMsg.includes('RESOURCE_EXHAUSTED')) {
            cleanMsg = "API quota or rate limit reached. Please wait a moment and click 'Try Again'.";
        } else if (cleanMsg.includes('TranscriptsDisabled') || cleanMsg.includes('No transcript')) {
            cleanMsg = "Could not retrieve captions for this video. Subtitles may be disabled by the creator.";
        }
    }
    const pipeErr = document.getElementById('pipelineErrorContainer');
    const pipeMsg = document.getElementById('pipelineErrorMessage');
    if (pipeErr && pipeMsg) {
        pipeMsg.textContent = cleanMsg;
        pipeErr.style.display = 'block';
    }
    const landingErr = document.getElementById('landingErrorBox');
    if (landingErr) {
        landingErr.textContent = '❌ ' + cleanMsg;
        landingErr.style.display = 'block';
    }
}

function retryLastAnalysis() {
    if (lastAttemptedUrl) {
        hideErrors();
        startAnalysis(lastAttemptedUrl);
    } else {
        returnToLanding();
    }
}

function returnToLanding() {
    hideErrors();
    const input = document.getElementById('youtubeUrl');
    if (input && lastAttemptedUrl) {
        input.value = lastAttemptedUrl;
    }
    showScreen('landing');
    if (input) setTimeout(() => input.focus(), 80);
}

function setAnalyzeButtonLoading(loading) {
    const btn = document.getElementById('analyzeSubmitBtn');
    const txt = document.getElementById('analyzeBtnText');
    if (btn) btn.disabled = loading;
    if (txt) txt.textContent = loading ? 'Analyzing...' : 'Analyze Video';
}

// ===== Clean Text & Inline Markdown Formatting Helpers =====
function formatCleanText(str) {
    if (!str) return '';
    return String(str)
        .replace(/\*\*([^*]+)\*\*/g, '$1')
        .replace(/\*\*/g, '')
        .trim();
}

function formatInlineMarkdown(str) {
    if (!str) return '';
    let s = escapeHtml(str);
    // Convert bold **text** to <strong>text</strong>
    s = s.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
    s = s.replace(/\*\*/g, '');
    return s;
}

// ===== 6-Mode Primary Navigation =====
function switchMainMode(modeKey) {
    // 1. Update Mode Tabs Bar
    document.querySelectorAll('.mode-tab-btn').forEach(btn => {
        btn.classList.toggle('active', btn.getAttribute('data-mode') === modeKey);
    });

    // 2. Update Sidebar Active Mode
    document.querySelectorAll('.sidebar-nav .side-nav-btn[data-mode]').forEach(btn => {
        btn.classList.toggle('active', btn.getAttribute('data-mode') === modeKey);
    });

    // 3. Update Mobile Bottom Nav
    document.querySelectorAll('.bottom-nav-tab[data-mode]').forEach(tab => {
        tab.classList.toggle('active', tab.getAttribute('data-mode') === modeKey);
    });

    // 4. Activate Pane
    document.querySelectorAll('.mode-pane').forEach(pane => {
        pane.classList.toggle('active', pane.id === 'pane-' + modeKey);
    });

    // 5. Special handling for compare mode dropdown
    if (modeKey === 'compare') {
        populateCompareDropdown();
    }

    window.scrollTo({ top: 380, behavior: 'smooth' });
}

function handleCapCardClick(mode) {
    if (currentAnalysis) {
        switchMainMode(mode);
        showScreen('dashboard');
    } else {
        const input = document.getElementById('youtubeUrl');
        if (input) {
            input.focus();
            input.scrollIntoView({ behavior: 'smooth', block: 'center' });
            showToast(`Paste a YouTube video link to explore ${mode} mode!`, 'info');
        }
    }
}

// ===== Analysis Pipeline Polling & Progress =====
let pollingInterval = null;
let elapsedTimer = null;
let elapsedSeconds = 0;

function startElapsedTimer() {
    elapsedSeconds = 0;
    const el = document.getElementById('elapsedTime');
    if (el) el.textContent = '00:00';
    if (elapsedTimer) clearInterval(elapsedTimer);
    elapsedTimer = setInterval(() => {
        elapsedSeconds++;
        const m = Math.floor(elapsedSeconds / 60).toString().padStart(2, '0');
        const s = (elapsedSeconds % 60).toString().padStart(2, '0');
        if (el) el.textContent = `${m}:${s}`;
    }, 1000);
}

function stopElapsedTimer() {
    if (elapsedTimer) {
        clearInterval(elapsedTimer);
        elapsedTimer = null;
    }
}

function updatePipelineStageUI(stageNum, stageName) {
    const fill = document.getElementById('progressBarFill');
    const taskEl = document.getElementById('loadingVideoTitle');
    if (taskEl && stageName) {
        taskEl.textContent = `Stage ${stageNum}/9: ${stageName}...`;
    }
    const pct = Math.min(100, Math.round((stageNum / 9) * 100));
    if (fill) fill.style.width = `${pct}%`;

    for (let i = 1; i <= 9; i++) {
        const sEl = document.getElementById('pStep' + i);
        if (sEl) {
            if (i < stageNum) {
                sEl.textContent = '✓';
                sEl.className = 'stage-indicator completed';
            } else if (i === stageNum) {
                sEl.textContent = '●';
                sEl.className = 'stage-indicator active';
            } else {
                sEl.textContent = '○';
                sEl.className = 'stage-indicator';
            }
        }
    }
}

async function startAnalysis(url) {
    if (!url || isAnalyzing) return;
    isAnalyzing = true;
    lastAttemptedUrl = url.trim();

    hideErrors();
    setAnalyzeButtonLoading(true);

    showScreen('loading');
    startElapsedTimer();
    updatePipelineStageUI(1, 'Submitting URL & allocating queue');

    try {
        const response = await fetch('/api/analyze', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ url: lastAttemptedUrl })
        });

        const data = await response.json();

        // Handle Quota Limit Reached
        if (response.status === 402 || (data.error && data.error.includes('Quota exceeded'))) {
            stopElapsedTimer();
            isAnalyzing = false;
            setAnalyzeButtonLoading(false);
            showScreen('landing');
            
            const quota = data.quota_info || {};
            if (quota.plan === 'anonymous') {
                openAuthModal('You have reached the 3 free video limit as a guest. Sign in with Google to get 5 free analyses!');
            } else {
                openUpgradeModal(quota);
            }
            return;
        }

        if (!response.ok || data.error) {
            throw new Error(data.error || 'Failed to start video analysis.');
        }

        const jobId = data.job_id;
        if (!jobId) {
            throw new Error('No job identifier returned by the server.');
        }

        // Begin Polling
        if (pollingInterval) clearInterval(pollingInterval);
        pollingInterval = setInterval(async () => {
            try {
                const jobRes = await fetch('/api/job/' + jobId);
                if (!jobRes.ok) return;
                const jobData = await jobRes.json();

                if (jobData.stage) {
                    updatePipelineStageUI(jobData.stage, jobData.stage_name);
                }

                if (jobData.status === 'completed' && jobData.result) {
                    clearInterval(pollingInterval);
                    stopElapsedTimer();
                    updatePipelineStageUI(9, 'Dossier ready');

                    setTimeout(() => {
                        currentAnalysis = jobData.result;
                        saveToHistory(jobData.result);
                        renderDashboard(jobData.result);
                        showScreen('dashboard');
                        updateUsageCounter();
                        loadUserState();
                        isAnalyzing = false;
                        setAnalyzeButtonLoading(false);
                    }, 350);

                } else if (jobData.status === 'error' || jobData.status === 'failed') {
                    clearInterval(pollingInterval);
                    stopElapsedTimer();
                    isAnalyzing = false;
                    setAnalyzeButtonLoading(false);
                    showPipelineError(jobData.error || 'An error occurred during analysis.');
                }
            } catch (pollErr) {
                console.warn('Poll retry:', pollErr);
            }
        }, 1200);

    } catch (err) {
        stopElapsedTimer();
        isAnalyzing = false;
        setAnalyzeButtonLoading(false);
        const isNetworkErr = err.message.includes('Failed to fetch') || err.message.includes('NetworkError');
        const friendlyMsg = isNetworkErr
            ? `Unable to connect to LensYou server (${window.location.origin}). Please ensure the backend is running.`
            : err.message;
        showPipelineError(friendlyMsg);
        showToast('❌ ' + friendlyMsg, 'error');
    }
}

// ===== Master Render Dashboard =====
function renderDashboard(data) {
    const meta = data._meta || {};
    const overview = data.video_overview || {};
    const metrics = data.metrics || {};

    // 1. Video Hero Header
    const thumbImg = document.getElementById('dashThumbnail');
    if (thumbImg) {
        thumbImg.src = meta.thumbnail_url || `https://img.youtube.com/vi/${meta.video_id}/hqdefault.jpg`;
    }
    document.getElementById('dashTitle').textContent = meta.title || overview.title || 'YouTube Video';
    document.getElementById('dashAuthor').textContent = meta.author || overview.channel || 'Content Creator';
    document.getElementById('dashDuration').textContent = meta.duration || metrics.duration || 'N/A';

    document.getElementById('dashCategory').textContent = overview.category || 'Technology';
    const conf = overview.content_type_confidence ? ` (${overview.content_type_confidence}% conf)` : '';
    document.getElementById('dashContentType').textContent = (overview.content_type || 'Podcast') + conf;
    document.getElementById('dashTone').textContent = overview.overall_tone || 'Informative';

    const watchBtn = document.getElementById('dashWatchBtn');
    if (watchBtn) watchBtn.href = meta.video_url || '#';

    // 2. Metrics Strip
    document.getElementById('metricDuration').textContent = meta.duration || metrics.duration || '--:--';
    document.getElementById('metricTopics').textContent = (data.topics || []).length || metrics.topics_count || '0';
    document.getElementById('metricChapters').textContent = (data.chapters || []).length || metrics.chapters_count || '0';
    document.getElementById('metricKeyPoints').textContent = (data.key_takeaways || []).length || metrics.key_points_count || '0';
    document.getElementById('metricQuality').textContent = `${data.quality_scorecard?.overall_score || 88}/100`;
    document.getElementById('metricSentiment').textContent = overview.sentiment_label || metrics.sentiment || 'Positive';

    // 3. Render Mode 1: UNDERSTAND
    const sumEl = document.getElementById('overviewSummaryText');
    if (sumEl) sumEl.innerHTML = formatInlineMarkdown(overview.summary || 'Summary unavailable.');
    renderQualityScorecard(data.quality_scorecard);
    renderEngagementCurve(data.engagement_curve || [], meta.duration_seconds || 1800);
    renderTakeaways(data.key_takeaways || []);
    renderMultiTrackTimeline(data);
    renderChapters(data.chapters || []);
    renderVideoMap(data.knowledge_graph || {});
    renderVisualMoments(data.visual_moments || [], meta.video_id);
    renderTranscript(data._transcript_sample || []);

    // 4. Render Mode 2: RESEARCH
    renderClaims(data.claims || []);
    renderEntities(data.entities || {});
    renderRepetitions(data.repetitions || []);
    renderContradictions(data.contradictions || []);
    renderSpeakers(data.speakers || []);

    // 5. Render Mode 3: LEARN
    renderDefinitions(data.learning?.key_definitions || []);
    renderStudyNotes(data.learning?.study_notes || []);
    setupFlashcards(data.learning?.flashcards || []);
    setupQuiz(data.learning?.quiz || []);

    // 6. Render Mode 4: CREATE / ACT
    renderViralClips(data.creator_repurposing?.viral_clips || []);
    renderSocialPosts(data.creator_repurposing?.social_posts || {}, data.creator_repurposing?.youtube_chapters_raw || '');

    // 7. Update Compare current video label
    const compareCur = document.getElementById('compareCurrentVideoName');
    if (compareCur) compareCur.textContent = meta.title || 'Current Video';

    // 8. Content-Type Adaptive Layout
    const cType = (overview.content_type || '').toLowerCase();
    if (cType.includes('lecture') || cType.includes('tutorial') || cType.includes('course')) {
        switchMainMode('learn');
        showToast('📚 Content detected as ' + overview.content_type + ' — Switched to Learn Mode');
    } else {
        switchMainMode('understand');
    }
}

// ===== Mode 1: Quality Scorecard & Engagement Curve =====
function renderQualityScorecard(scorecard) {
    if (!scorecard) return;
    const badge = document.getElementById('scorecardOverallBadge');
    if (badge) badge.textContent = `Overall: ${scorecard.overall_score || 88}/100`;

    const metrics = [
        { label: "Information Density", score: scorecard.density_score || 90 },
        { label: "Clarity & Articulation", score: scorecard.clarity_score || 92 },
        { label: "Narrative Structure", score: scorecard.structure_score || 94 },
        { label: "Audience Engagement", score: scorecard.engagement_score || 87 },
        { label: "Conceptual Depth", score: scorecard.depth_score || 85 },
        { label: "Pacing & Flow", score: scorecard.pacing_score || 80 }
    ];

    const container = document.getElementById('scorecardBars');
    if (container) {
        container.innerHTML = metrics.map(m => `
            <div class="scorecard-bar-row">
                <div class="scorecard-bar-meta">
                    <span>${m.label}</span>
                    <strong>${m.score}/100</strong>
                </div>
                <div class="scorecard-bar-track">
                    <div class="scorecard-bar-fill" style="width: ${m.score}%;"></div>
                </div>
            </div>
        `).join('');
    }

    const strengthsEl = document.getElementById('scorecardStrengths');
    if (strengthsEl && scorecard.strengths) {
        strengthsEl.innerHTML = scorecard.strengths.map(s => `<li>${escapeHtml(s)}</li>`).join('');
    }

    const weakEl = document.getElementById('scorecardWeaknesses');
    if (weakEl && scorecard.weaknesses) {
        weakEl.innerHTML = scorecard.weaknesses.map(w => `<li>${escapeHtml(w)}</li>`).join('');
    }
}

function renderEngagementCurve(points, totalSec) {
    const svg = document.getElementById('engagementSvg');
    if (!svg || !points || !points.length) return;

    const width = 500;
    const height = 140;
    const padding = 20;

    let peakPoint = points[0];
    points.forEach(p => {
        if ((p.score || 0) > (peakPoint?.score || 0)) peakPoint = p;
    });

    const peakCard = document.getElementById('peakMomentCard');
    const peakText = document.getElementById('peakMomentText');
    if (peakText && peakPoint) {
        peakText.innerHTML = `<span style="color:var(--text-primary); font-weight:700;">★ ${escapeHtml(peakPoint.time)}</span> — <strong>${escapeHtml(peakPoint.highlight || 'High engagement turning point')}</strong> (Score: ${peakPoint.score}/100)`;
        if (peakCard) {
            const peakSec = parseTimestampToSeconds(peakPoint.time);
            peakCard.onclick = () => jumpToSecond(peakSec);
            peakCard.title = "Click to jump to peak moment on YouTube";
        }
    }

    // Map points to coordinates
    const maxScore = 100;
    const minScore = 40;

    const coords = points.map((p, idx) => {
        const x = padding + (idx / Math.max(1, points.length - 1)) * (width - 2 * padding);
        const normScore = Math.max(0, Math.min(1, ((p.score || 50) - minScore) / (maxScore - minScore)));
        const y = height - padding - normScore * (height - 2 * padding);
        return { x, y, point: p };
    });

    let pathD = `M ${coords[0].x} ${coords[0].y}`;
    for (let i = 1; i < coords.length; i++) {
        const prev = coords[i - 1];
        const cur = coords[i];
        const cpX = (prev.x + cur.x) / 2;
        pathD += ` C ${cpX} ${prev.y}, ${cpX} ${cur.y}, ${cur.x} ${cur.y}`;
    }

    let areaD = `${pathD} L ${coords[coords.length - 1].x} ${height - 6} L ${coords[0].x} ${height - 6} Z`;

    let svgHtml = `
        <defs>
            <linearGradient id="engGrad" x1="0%" y1="0%" x2="0%" y2="100%">
                <stop offset="0%" stop-color="#FFFFFF" stop-opacity="0.12"/>
                <stop offset="100%" stop-color="#FFFFFF" stop-opacity="0.0"/>
            </linearGradient>
        </defs>
        <rect width="100%" height="100%" fill="transparent" style="cursor: crosshair;"/>
        <path d="${areaD}" fill="url(#engGrad)" style="cursor: pointer;"/>
        <path d="${pathD}" fill="none" stroke="#E4E4E7" stroke-width="2" stroke-linecap="round"/>
    `;

    coords.forEach(c => {
        const isPeak = c.point === peakPoint;
        const color = isPeak ? '#FFFFFF' : '#71717A';
        const r = isPeak ? 5.5 : 3.5;
        const sec = parseTimestampToSeconds(c.point.time);
        svgHtml += `
            <g class="eng-point" style="cursor: pointer;" onclick="event.stopPropagation(); jumpToSecond(${sec})" title="${escapeHtml(c.point.time)}: ${escapeHtml(c.point.highlight || '')} (${c.point.score}/100) — Click to seek">
                <circle cx="${c.x}" cy="${c.y}" r="${r + 5}" fill="transparent"/>
                <circle cx="${c.x}" cy="${c.y}" r="${r}" fill="${color}" stroke="#0C0C0D" stroke-width="2"/>
                <text x="${c.x}" y="${height - 4}" font-size="9" fill="#71717A" text-anchor="middle">${escapeHtml(c.point.time)}</text>
            </g>
        `;
    });

    svg.innerHTML = svgHtml;

    // Interactive canvas click-to-seek anywhere along the timeline curve
    svg.onclick = (e) => {
        const rect = svg.getBoundingClientRect();
        const clickX = e.clientX - rect.left;
        const ratio = Math.max(0, Math.min(1, (clickX - padding) / (rect.width - 2 * padding)));
        const targetSec = Math.round(ratio * (totalSec || 1800));
        jumpToSecond(targetSec);
    };
}

// ===== Mode 1: Key Strategic Takeaways =====
function renderTakeaways(takeaways) {
    const grid = document.getElementById('takeawaysGrid');
    if (!grid) return;

    grid.innerHTML = takeaways.map(t => {
        const imp = (t.importance || 'HIGH').toUpperCase();
        const badgeClass = imp === 'CRITICAL' ? 'importance-critical' : imp === 'HIGH' ? 'importance-high' : 'importance-medium';
        const seconds = t.seconds || parseTimestampToSeconds(t.timestamp);
        return `
            <div class="takeaway-card">
                <div>
                    <div class="takeaway-top-bar">
                        <span class="takeaway-id">${escapeHtml(t.id || '#')}</span>
                        <span class="importance-pill ${badgeClass}">● ${imp}</span>
                    </div>
                    <h4 class="takeaway-title">${formatInlineMarkdown(t.title)}</h4>
                    <p class="takeaway-desc">${formatInlineMarkdown(t.description)}</p>
                </div>
                <div class="takeaway-footer">
                    <button class="timestamp-pill" onclick="jumpToSecond(${seconds})">
                        <span>▶</span> ${escapeHtml(t.timestamp || '00:00')}
                    </button>
                    <span class="confidence-tag">${escapeHtml(t.confidence || 'Directly stated')}</span>
                </div>
            </div>
        `;
    }).join('');
}

// ===== Mode 1: Multi-Track Layered Timeline =====
function renderMultiTrackTimeline(data) {
    const meta = data._meta || {};
    const totalSec = meta.duration_seconds || 1800;

    document.getElementById('timelineStartLabel').textContent = '00:00';
    document.getElementById('timelineEndLabel').textContent = meta.duration || 'Full Video';
    document.getElementById('timelineMidLabel').textContent = formatSeconds(totalSec / 2);

    // Track 1: Topics Track
    const topicsCanvas = document.getElementById('track-topics-canvas');
    if (topicsCanvas) {
        const topics = data.topics || [];
        topicsCanvas.innerHTML = topics.map((t, idx) => {
            const widthPct = t.percentage || (100 / Math.max(1, topics.length));
            const leftPct = (idx * (100 / Math.max(1, topics.length)));
            return `
                <div class="track-pill-item" style="left: ${leftPct}%; width: ${Math.max(15, widthPct - 2)}%;" title="${escapeHtml(t.name)} (${widthPct}%)" onclick="selectTrackMoment('${escapeJsString(t.name)}', 'Topic Focus (${widthPct}% dialogue share)', 0)">
                    ${escapeHtml(t.name)}
                </div>
            `;
        }).join('');
    }

    // Track 2: Speakers Track
    const spCanvas = document.getElementById('track-speakers-canvas');
    if (spCanvas) {
        const speakers = data.speakers || [];
        spCanvas.innerHTML = speakers.map((sp, idx) => {
            const left = idx === 0 ? 0 : 55;
            const w = idx === 0 ? 53 : 45;
            return `
                <div class="track-pill-item" style="left: ${left}%; width: ${w}%; background: rgba(34, 197, 94, 0.18); border-color: rgba(34, 197, 94, 0.4); color: #4ade80;" onclick="selectTrackMoment('${escapeJsString(sp.speaker)}', 'Dialogue Share: ${sp.percentage}%', 0)">
                    🎙️ ${escapeHtml(sp.speaker)}
                </div>
            `;
        }).join('');
    }

    // Track 3: Claims Track
    const claimsCanvas = document.getElementById('track-claims-canvas');
    if (claimsCanvas) {
        const claims = data.claims || [];
        claimsCanvas.innerHTML = claims.map(c => {
            const sec = c.seconds || parseTimestampToSeconds(c.timestamp);
            const leftPct = Math.min(98, Math.max(1, (sec / totalSec) * 100));
            const typeColor = (c.type || '').toLowerCase().includes('fact') ? '#22C55E' : '#F59E0B';
            return `
                <div class="track-marker-dot" style="left: ${leftPct}%; background: ${typeColor};" title="${escapeHtml(c.claim)} [${c.timestamp}]" onclick="selectTrackMoment('${escapeJsString(c.claim)}', 'Claim Type: ${escapeJsString(c.type)}', ${sec}, '${c.timestamp}')"></div>
            `;
        }).join('');
    }

    // Track 4: Scenes Track
    const scenesCanvas = document.getElementById('track-scenes-canvas');
    if (scenesCanvas) {
        const moments = data.visual_moments || [];
        scenesCanvas.innerHTML = moments.map(vm => {
            const sec = vm.seconds || parseTimestampToSeconds(vm.timestamp);
            const leftPct = Math.min(98, Math.max(1, (sec / totalSec) * 100));
            return `
                <div class="track-marker-dot" style="left: ${leftPct}%; background: #8B7CFF;" title="${escapeHtml(vm.title)} (${vm.scene_type}) [${vm.timestamp}]" onclick="selectTrackMoment('${escapeJsString(vm.title)}', '${escapeJsString(vm.takeaway)}', ${sec}, '${vm.timestamp}')"></div>
            `;
        }).join('');
    }
}

function toggleTimelineTrack(trackName) {
    const row = document.getElementById('track-' + trackName + '-row');
    const checkbox = document.getElementById('toggle' + trackName.charAt(0).toUpperCase() + trackName.slice(1));
    if (row && checkbox) {
        row.style.display = checkbox.checked ? 'flex' : 'none';
    }
}

function selectTrackMoment(title, desc, sec, timeStr) {
    currentActiveSecond = sec;
    const timeBadge = document.getElementById('activeMomentTime');
    const titleEl = document.getElementById('activeMomentTitle');
    const descEl = document.getElementById('activeMomentDesc');

    if (timeBadge) timeBadge.textContent = timeStr || formatSeconds(sec);
    if (titleEl) titleEl.textContent = title;
    if (descEl) descEl.textContent = desc;

    const playBtn = document.getElementById('activeMomentPlayBtn');
    if (playBtn) playBtn.textContent = `▶ Play on YouTube from ${timeStr || formatSeconds(sec)}`;
}

function playCurrentMoment() {
    jumpToSecond(currentActiveSecond);
}

// ===== Mode 1: Chapters Breakdown =====
function renderChapters(chapters) {
    const list = document.getElementById('chaptersList');
    if (!list) return;

    const badge = document.getElementById('chaptersCountBadge');
    if (badge) badge.textContent = `${chapters.length} Chapters`;

    list.innerHTML = chapters.map(ch => {
        const startSec = ch.start_seconds || parseTimestampToSeconds(ch.start_time);
        return `
            <div class="chapter-card">
                <div class="chapter-top-line">
                    <div class="chapter-left-meta">
                        <span class="chapter-number">${escapeHtml(ch.number || '01')}</span>
                        <h4 class="chapter-title">${escapeHtml(ch.title)}</h4>
                    </div>
                    <button class="timestamp-pill" onclick="jumpToSecond(${startSec})">
                        <span>▶</span> ${escapeHtml(ch.start_time || '00:00')} - ${escapeHtml(ch.end_time || '')}
                    </button>
                </div>
                <p class="chapter-summary">${escapeHtml(ch.summary || '')}</p>
                <div class="chapter-bullets">
                    ${(ch.key_points || []).map(pt => `<div class="bullet-point"><span>•</span> ${escapeHtml(pt)}</div>`).join('')}
                </div>
            </div>
        `;
    }).join('');
}

// ===== Mode 1: Video Map / Knowledge Graph =====
function renderVideoMap(kg) {
    const svg = document.getElementById('videoMapSvg');
    if (!svg) return;

    const nodes = kg.nodes || [];
    const links = kg.links || [];

    if (!nodes.length) {
        svg.innerHTML = '<text x="350" y="175" fill="#71717A" text-anchor="middle" font-size="14">No concept graph generated</text>';
        return;
    }

    const width = 700;
    const height = 350;
    const cx = width / 2;
    const cy = height / 2;

    // Distribute nodes in a radial constellation layout
    const nodeCoords = {};
    nodes.forEach((n, idx) => {
        if (idx === 0) {
            nodeCoords[n.id] = { x: cx, y: cy, node: n };
        } else {
            const angle = ((idx - 1) / (nodes.length - 1)) * 2 * Math.PI;
            const radius = 125 + (idx % 2 === 0 ? 25 : -25);
            nodeCoords[n.id] = {
                x: cx + Math.cos(angle) * radius,
                y: cy + Math.sin(angle) * radius,
                node: n
            };
        }
    });

    let linksHtml = '';
    links.forEach((l, idx) => {
        const s = nodeCoords[l.source];
        const t = nodeCoords[l.target];
        if (s && t) {
            linksHtml += `
                <line id="kg-link-${idx}" data-source="${escapeHtml(l.source)}" data-target="${escapeHtml(l.target)}" x1="${s.x}" y1="${s.y}" x2="${t.x}" y2="${t.y}" stroke="rgba(255, 255, 255, 0.12)" stroke-width="1.5" class="kg-link" style="transition: opacity 0.25s, stroke 0.25s;"/>
            `;
        }
    });

    let nodesHtml = '';
    Object.values(nodeCoords).forEach((c, idx) => {
        const isCenter = idx === 0;
        const r = isCenter ? 24 : 18;
        const color = isCenter ? '#FFFFFF' : (c.node.type === 'entity' ? '#D4D4D8' : (c.node.type === 'theme' ? '#A1A1AA' : '#71717A'));
        const safeId = String(c.node.id).replace(/[^a-zA-Z0-9_-]/g, '_');
        nodesHtml += `
            <g id="kg-node-${safeId}" class="kg-node" data-id="${escapeHtml(c.node.id)}" onclick="selectConceptNode('${escapeJsString(c.node.id)}')" style="cursor: pointer; transition: opacity 0.25s, transform 0.25s;">
                <circle cx="${c.x}" cy="${c.y}" r="${r + 6}" fill="none" stroke="transparent" stroke-width="2.5" class="kg-node-ring" id="kg-ring-${safeId}"/>
                <circle cx="${c.x}" cy="${c.y}" r="${r}" fill="${color}" stroke="#0C0C0D" stroke-width="2.5" class="kg-node-circle"/>
                <text x="${c.x}" y="${c.y + r + 14}" class="kg-node-label" text-anchor="middle" fill="#E4E4E7" font-size="11" font-weight="600">${escapeHtml(c.node.label)}</text>
            </g>
        `;
    });

    svg.innerHTML = `
        <rect width="100%" height="100%" fill="transparent" onclick="deselectConceptNode()"/>
        <g id="kg-links-group">${linksHtml}</g>
        <g id="kg-nodes-group">${nodesHtml}</g>
    `;
}

function selectConceptNode(nodeId) {
    if (!currentAnalysis || !currentAnalysis.knowledge_graph) return;
    const kg = currentAnalysis.knowledge_graph;
    const nodes = kg.nodes || [];
    const links = kg.links || [];
    const node = nodes.find(n => n.id === nodeId);
    if (!node) return;

    selectedConceptId = nodeId;

    // Find connected node IDs
    const connectedNodeIds = new Set([nodeId]);
    links.forEach(l => {
        if (l.source === nodeId) connectedNodeIds.add(l.target);
        if (l.target === nodeId) connectedNodeIds.add(l.source);
    });

    // Dim unrelated nodes to 0.22 opacity, highlight selected & connected
    nodes.forEach(n => {
        const safeId = String(n.id).replace(/[^a-zA-Z0-9_-]/g, '_');
        const el = document.getElementById(`kg-node-${safeId}`);
        const ring = document.getElementById(`kg-ring-${safeId}`);
        if (el) {
            if (n.id === nodeId) {
                el.style.opacity = '1';
                if (ring) {
                    ring.setAttribute('stroke', '#8B7CFF');
                    ring.setAttribute('stroke-width', '2.5');
                }
            } else if (connectedNodeIds.has(n.id)) {
                el.style.opacity = '0.95';
                if (ring) {
                    ring.setAttribute('stroke', 'rgba(139, 124, 255, 0.45)');
                    ring.setAttribute('stroke-width', '1.5');
                }
            } else {
                el.style.opacity = '0.22';
                if (ring) ring.setAttribute('stroke', 'transparent');
            }
        }
    });

    // Dim unrelated links to 0.12 opacity
    const linkEls = document.querySelectorAll('.kg-link');
    linkEls.forEach(linkEl => {
        const s = linkEl.getAttribute('data-source');
        const t = linkEl.getAttribute('data-target');
        if (s === nodeId || t === nodeId) {
            linkEl.style.opacity = '1';
            linkEl.setAttribute('stroke', '#8B7CFF');
            linkEl.setAttribute('stroke-width', '2.5');
        } else {
            linkEl.style.opacity = '0.12';
            linkEl.setAttribute('stroke', 'rgba(255, 255, 255, 0.06)');
            linkEl.setAttribute('stroke-width', '1');
        }
    });

    const box = document.getElementById('conceptDetailBox');
    const titleEl = document.getElementById('selectedConceptTitle');
    const countEl = document.getElementById('selectedConceptCount');
    const stampsEl = document.getElementById('conceptTimestampsRow');

    if (box && titleEl && countEl && stampsEl) {
        box.style.display = 'block';
        titleEl.textContent = node.label;
        countEl.textContent = `Type: ${node.type || 'concept'} • Mentioned ${node.occurrences || 3} times`;

        const times = node.timestamps || [node.timestamp || '04:15', '12:30', '24:10'];
        stampsEl.innerHTML = times.map(t => {
            const sec = parseTimestampToSeconds(t);
            return `
                <button class="timestamp-pill" onclick="jumpToSecond(${sec})">
                    <span>▶</span> ${escapeHtml(t)} ↗
                </button>
            `;
        }).join('');
    }
}

function deselectConceptNode() {
    selectedConceptId = null;
    const kg = currentAnalysis?.knowledge_graph;
    if (!kg) return;
    (kg.nodes || []).forEach(n => {
        const safeId = String(n.id).replace(/[^a-zA-Z0-9_-]/g, '_');
        const el = document.getElementById(`kg-node-${safeId}`);
        const ring = document.getElementById(`kg-ring-${safeId}`);
        if (el) el.style.opacity = '1';
        if (ring) ring.setAttribute('stroke', 'transparent');
    });
    document.querySelectorAll('.kg-link').forEach(linkEl => {
        linkEl.style.opacity = '1';
        linkEl.setAttribute('stroke', 'rgba(255, 255, 255, 0.12)');
        linkEl.setAttribute('stroke-width', '1.5');
    });

    const box = document.getElementById('conceptDetailBox');
    if (box) box.style.display = 'none';
}

// ===== Mode 1: Visual & Scene Moments =====
function renderVisualMoments(moments, videoId) {
    const grid = document.getElementById('visualMomentsGrid');
    if (!grid) return;

    if (!moments.length) {
        grid.innerHTML = '<p class="text-muted">No visual slide or screen moments detected.</p>';
        return;
    }

    grid.innerHTML = moments.map((vm, idx) => {
        const sec = vm.seconds || parseTimestampToSeconds(vm.timestamp);
        const thumbNum = (idx % 3) + 1;
        const imgUrl = `https://img.youtube.com/vi/${videoId}/${thumbNum}.jpg`;

        return `
            <div class="visual-moment-card">
                <div class="visual-thumb-wrapper" onclick="jumpToSecond(${sec})">
                    <img src="${imgUrl}" alt="${escapeHtml(vm.title)}" onerror="this.src='https://img.youtube.com/vi/${videoId}/hqdefault.jpg'">
                    <span class="scene-type-badge">${escapeHtml(vm.scene_type || 'Scene')}</span>
                </div>
                <div class="visual-meta">
                    <div>
                        <div class="visual-title">${escapeHtml(vm.title)}</div>
                        ${vm.ocr_text ? `<div class="visual-ocr">OCR: ${escapeHtml(vm.ocr_text)}</div>` : ''}
                        <div class="visual-takeaway">${escapeHtml(vm.takeaway)}</div>
                    </div>
                    <div class="takeaway-footer mt-12">
                        <button class="timestamp-pill" onclick="jumpToSecond(${sec})">
                            <span>▶</span> ${escapeHtml(vm.timestamp || '00:00')}
                        </button>
                        <button class="btn-hero btn-secondary-hero btn-sm" onclick="askCopilot('Deeply analyze the visual shown at ${vm.timestamp}: ${escapeJsString(vm.title)}')">
                            Analyze ✦
                        </button>
                    </div>
                </div>
            </div>
        `;
    }).join('');
}

// ===== Mode 1: Split-Screen Transcript & Search Highlighting =====
let rawTranscriptSnippets = [];

function renderTranscript(snippets) {
    rawTranscriptSnippets = snippets || [];
    const scrollArea = document.getElementById('transcriptScrollArea');
    if (!scrollArea) return;

    scrollArea.innerHTML = rawTranscriptSnippets.map((s, idx) => `
        <div class="transcript-line-card" onclick="selectTranscriptLine(${idx})" id="tline-${idx}" data-text="${escapeHtml(s.text.toLowerCase())}">
            <span class="line-time">${s.timestamp}</span>
            <span class="line-text" id="tline-text-${idx}">${escapeHtml(s.text)}</span>
        </div>
    `).join('');
}

function filterTranscript(keyword) {
    const val = (keyword || '').toLowerCase().trim();
    rawTranscriptSnippets.forEach((s, idx) => {
        const card = document.getElementById(`tline-${idx}`);
        const textSpan = document.getElementById(`tline-text-${idx}`);
        if (!card || !textSpan) return;

        if (!val) {
            card.style.display = 'flex';
            textSpan.innerHTML = escapeHtml(s.text);
            return;
        }

        const lower = s.text.toLowerCase();
        if (lower.includes(val)) {
            card.style.display = 'flex';
            // Highlight matching occurrence
            const reg = new RegExp(`(${escapeRegex(val)})`, 'gi');
            textSpan.innerHTML = escapeHtml(s.text).replace(reg, '<mark class="transcript-match">$1</mark>');
        } else {
            card.style.display = 'none';
        }
    });
}

function selectTranscriptLine(idx) {
    if (!currentAnalysis || !currentAnalysis._transcript_sample) return;
    const item = currentAnalysis._transcript_sample[idx];
    if (!item) return;

    document.querySelectorAll('.transcript-line-card').forEach((card, i) => {
        card.classList.toggle('active', i === idx);
    });

    const body = document.getElementById('contextInsightBody');
    if (body) {
        body.innerHTML = `
            <div class="active-context-card">
                <span class="moment-badge">${item.timestamp}</span>
                <p class="mt-12"><strong>Spoken Statement:</strong></p>
                <p class="transcript-quote">"${escapeHtml(item.text)}"</p>
                <div class="mt-16 flex-row-gap">
                    <button class="btn-hero btn-primary-hero btn-sm" onclick="jumpToSecond(${item.start})">
                        ▶ Jump to ${item.timestamp} on YouTube
                    </button>
                    <button class="btn-hero btn-secondary-hero btn-sm" onclick="askCopilot('Analyze this statement spoken at ${item.timestamp}: &quot;${escapeJsString(item.text)}&quot;')">
                        Ask Copilot ✦
                    </button>
                </div>
            </div>
        `;
    }
}

// ===== Mode 2: RESEARCH MODE =====
function renderClaims(claims) {
    const list = document.getElementById('claimsList');
    if (!list) return;

    const totalBadge = document.getElementById('claimsTotalBadge');
    if (totalBadge) totalBadge.textContent = claims.length;

    const iconMap = {
        'fact': '✓',
        'opinion': '💬',
        'prediction': '🔮',
        'statistic': '📊',
        'speculation': '❓'
    };

    list.innerHTML = claims.map(c => {
        const typeKey = (c.type || 'Fact').toLowerCase();
        const icon = iconMap[typeKey] || '🔍';
        const sec = c.seconds || parseTimestampToSeconds(c.timestamp);
        return `
            <div class="claim-row" data-type="${typeKey}" onclick="selectClaim('${escapeJsString(c.claim)}', ${sec})">
                <span class="claim-type-icon">${icon}</span>
                <div class="claim-content">
                    <div class="claim-text">${formatInlineMarkdown(c.claim)}</div>
                    <div class="claim-context">${formatInlineMarkdown(c.context || '')}</div>
                    ${c.verification_note ? `<div class="claim-context text-muted mt-4"><em>Verification:</em> ${formatInlineMarkdown(c.verification_note)}</div>` : ''}
                </div>
                <div style="display:flex; flex-direction:column; align-items:flex-end; gap:6px; flex-shrink:0;">
                    <button class="timestamp-pill" onclick="jumpToSecond(${sec}); event.stopPropagation();">
                        <span>▶</span> ${escapeHtml(c.timestamp || '00:00')}
                    </button>
                    <span class="confidence-tag">${escapeHtml(c.confidence || 'High')}</span>
                </div>
            </div>
        `;
    }).join('');
}

function filterClaims(filterType) {
    document.querySelectorAll('.claim-filter-btn').forEach(btn => {
        btn.classList.toggle('active', btn.textContent.toLowerCase().includes(filterType));
    });

    document.querySelectorAll('#claimsList .claim-row').forEach(row => {
        if (filterType === 'all') {
            row.style.display = 'flex';
        } else {
            row.style.display = (row.getAttribute('data-type') || '').includes(filterType) ? 'flex' : 'none';
        }
    });
}

function selectClaim(claimText, timestampSeconds) {
    jumpToSecond(timestampSeconds);
}

function renderEntities(entities) {
    const pList = document.getElementById('entitiesPeopleList');
    const cList = document.getElementById('entitiesCompaniesList');
    const tList = document.getElementById('entitiesToolsList');

    if (pList) {
        const people = entities.people || [];
        pList.innerHTML = people.length ? people.map(p => `
            <div class="entity-item-card">
                <div class="entity-name">${escapeHtml(p.name)}</div>
                <div class="entity-context">${escapeHtml(p.role || p.context || '')}</div>
            </div>
        `).join('') : '<div class="text-muted font-sm">No specific individuals identified</div>';
    }

    if (cList) {
        const companies = entities.companies || [];
        cList.innerHTML = companies.length ? companies.map(c => `
            <div class="entity-item-card">
                <div class="entity-name">${escapeHtml(c.name)}</div>
                <div class="entity-context">${escapeHtml(c.industry || c.context || '')}</div>
            </div>
        `).join('') : '<div class="text-muted font-sm">No corporations mentioned</div>';
    }

    if (tList) {
        const tools = entities.tools_software || [];
        tList.innerHTML = tools.length ? tools.map(t => `
            <div class="entity-item-card">
                <div class="entity-name">${escapeHtml(t.name)}</div>
                <div class="entity-context">${escapeHtml(t.category || t.context || '')}</div>
            </div>
        `).join('') : '<div class="text-muted font-sm">No specific software or books detected</div>';
    }
}

function renderRepetitions(repetitions) {
    const list = document.getElementById('repetitionsList');
    if (!list) return;

    if (!repetitions.length) {
        list.innerHTML = '<p class="text-muted">No redundant or heavily repeated talking points identified.</p>';
        return;
    }

    list.innerHTML = repetitions.map(r => `
        <div class="repetition-card">
            <div class="repetition-header">
                <strong>"${escapeHtml(r.idea)}"</strong>
                <span class="pill-tag">Mentioned ${r.occurrences_count || r.timestamps?.length || 2} times</span>
            </div>
            <p class="text-muted font-sm">${escapeHtml(r.context || '')}</p>
            <div class="mt-8 flex-row-gap">
                ${(r.timestamps || []).map(t => {
                    const sec = parseTimestampToSeconds(t);
                    return `<button class="timestamp-pill" onclick="jumpToSecond(${sec})"><span>▶</span> ${t}</button>`;
                }).join(' ')}
            </div>
        </div>
    `).join('');
}

function renderContradictions(contradictions) {
    const list = document.getElementById('contradictionsList');
    if (!list) return;

    if (!contradictions.length) {
        list.innerHTML = '<p class="text-muted">No noticeable logical contradictions or conflicting assertions detected.</p>';
        return;
    }

    list.innerHTML = contradictions.map(c => {
        const secA = c.statement_a?.seconds || parseTimestampToSeconds(c.statement_a?.timestamp);
        const secB = c.statement_b?.seconds || parseTimestampToSeconds(c.statement_b?.timestamp);
        return `
            <div class="contradiction-card">
                <div class="contradiction-header">
                    <strong>Topic: ${escapeHtml(c.topic || 'Divergent Argument')}</strong>
                    <span class="pill-tag">Nuance Contrast</span>
                </div>
                <div class="contradiction-statements-grid">
                    <div class="statement-box">
                        <span class="moment-badge">${escapeHtml(c.statement_a?.timestamp || 'Point A')}</span>
                        <p class="mt-8">"${escapeHtml(c.statement_a?.text || '')}"</p>
                        <button class="timestamp-pill mt-8" onclick="jumpToSecond(${secA})">▶ Jump</button>
                    </div>
                    <div class="statement-box">
                        <span class="moment-badge">${escapeHtml(c.statement_b?.timestamp || 'Point B')}</span>
                        <p class="mt-8">"${escapeHtml(c.statement_b?.text || '')}"</p>
                        <button class="timestamp-pill mt-8" onclick="jumpToSecond(${secB})">▶ Jump</button>
                    </div>
                </div>
                <p class="text-muted font-sm mt-8"><em>Nuance explanation:</em> ${escapeHtml(c.nuance || '')}</p>
            </div>
        `;
    }).join('');
}

function renderSpeakers(speakers) {
    const grid = document.getElementById('speakersGrid');
    if (!grid) return;

    grid.innerHTML = speakers.map(sp => `
        <div class="speaker-card">
            <h3 class="speaker-name">🎙️ ${escapeHtml(sp.speaker)}</h3>
            <div class="speaker-role">${escapeHtml(sp.role || 'Contributor')}</div>
            <div class="speaker-stats">
                <div><strong>${sp.percentage || 50}%</strong> Speaking Share</div>
                <div><strong>~${sp.words_estimate || '3,000'}</strong> Words</div>
                <div><strong>${sp.questions_count || 0}</strong> Questions</div>
            </div>
        </div>
    `).join('');
}

// ===== Mode 3: LEARN MODE =====
function renderDefinitions(definitions) {
    const grid = document.getElementById('definitionsGrid');
    if (!grid) return;

    if (!definitions.length) {
        grid.innerHTML = '<p class="text-muted">No explicit conceptual definitions extracted.</p>';
        return;
    }

    grid.innerHTML = definitions.map(d => {
        const sec = d.seconds || parseTimestampToSeconds(d.timestamp);
        return `
            <div class="definition-card">
                <div>
                    <div class="definition-term"># ${formatCleanText(d.term)}</div>
                    <div class="definition-body">${formatInlineMarkdown(d.definition)}</div>
                </div>
                <div class="takeaway-footer mt-12">
                    <button class="timestamp-pill" onclick="jumpToSecond(${sec})">
                        <span>▶</span> ${escapeHtml(d.timestamp || '00:00')}
                    </button>
                </div>
            </div>
        `;
    }).join('');
}

function renderStudyNotes(notes) {
    const container = document.getElementById('studyNotesContainer');
    if (!container) return;

    if (!notes.length) {
        container.innerHTML = '<p class="text-muted">Study notes unavailable.</p>';
        return;
    }

    container.innerHTML = notes.map(n => `
        <div class="study-note-card">
            <div class="study-note-heading">📌 ${formatCleanText(n.heading || n.section_title || 'Key Module')}</div>
            <ul class="bullet-list-sm">
                ${(n.bullets || n.detailed_bullets || []).map(b => `<li>${formatInlineMarkdown(b)}</li>`).join('')}
            </ul>
        </div>
    `).join('');
}

function setupFlashcards(flashcards) {
    window.currentFlashcardsDeck = flashcards || [];
    currentFlashcardIdx = 0;
    renderCurrentFlashcard();
}

function renderCurrentFlashcard() {
    const deck = window.currentFlashcardsDeck || [];
    const cardEl = document.getElementById('activeFlashcard');
    const counter = document.getElementById('flashcardCounterBadge');
    if (!cardEl || !deck.length) return;

    if (cardEl.classList.contains('flipped')) cardEl.classList.remove('flipped');

    const card = deck[currentFlashcardIdx];
    document.getElementById('flashcardConceptTag').textContent = formatCleanText(card.concept || `Card ${currentFlashcardIdx + 1}`);
    document.getElementById('flashcardFrontText').textContent = formatCleanText(card.front || card.front_question || 'Question');
    document.getElementById('flashcardBackText').textContent = formatCleanText(card.back || card.back_answer || 'Answer');

    if (counter) counter.textContent = `Card ${currentFlashcardIdx + 1} of ${deck.length}`;
}

function flipCurrentFlashcard() {
    const card = document.getElementById('activeFlashcard');
    if (card) card.classList.toggle('flipped');
}

function nextFlashcard() {
    const deck = window.currentFlashcardsDeck || [];
    if (!deck.length) return;
    currentFlashcardIdx = (currentFlashcardIdx + 1) % deck.length;
    renderCurrentFlashcard();
}

function prevFlashcard() {
    const deck = window.currentFlashcardsDeck || [];
    if (!deck.length) return;
    currentFlashcardIdx = (currentFlashcardIdx - 1 + deck.length) % deck.length;
    renderCurrentFlashcard();
}

function setupQuiz(quiz) {
    const container = document.getElementById('quizContainer');
    if (!container) return;

    window.currentQuizQuestions = quiz || [];
    quizUserScore = 0;
    quizAnsweredCount = 0;
    const badge = document.getElementById('quizScoreBadge');
    if (badge) badge.textContent = `Score: 0/${window.currentQuizQuestions.length}`;

    if (!window.currentQuizQuestions.length) {
        container.innerHTML = '<p class="text-muted">No quiz generated for this video.</p>';
        return;
    }

    container.innerHTML = window.currentQuizQuestions.map((q, qIdx) => `
        <div class="quiz-card" id="quiz-card-${qIdx}">
            <div class="quiz-q-title">Q${qIdx + 1}: ${formatInlineMarkdown(q.question)}</div>
            <div class="quiz-options-list">
                ${(q.options || []).map((opt, optIdx) => `
                    <button class="quiz-opt-btn" onclick="selectQuizAnswer(${qIdx}, ${optIdx}, ${q.correct_index})" id="qopt-${qIdx}-${optIdx}">
                        ${String.fromCharCode(65 + optIdx)}. ${formatInlineMarkdown(opt)}
                    </button>
                `).join('')}
            </div>
            <div class="quiz-explanation-box" id="quiz-exp-${qIdx}">
                <strong>Explanation:</strong> ${escapeHtml(q.explanation || '')}
            </div>
        </div>
    `).join('');
}

function selectQuizAnswer(qIdx, selectedOptIdx, correctIdx) {
    const card = document.getElementById(`quiz-card-${qIdx}`);
    if (!card || card.getAttribute('data-answered')) return;

    card.setAttribute('data-answered', 'true');
    quizAnsweredCount++;

    const isCorrect = selectedOptIdx === correctIdx;
    if (isCorrect) {
        quizUserScore++;
    } else {
        card.classList.add('shake');
        setTimeout(() => card.classList.remove('shake'), 400);
    }

    const badge = document.getElementById('quizScoreBadge');
    if (badge) {
        badge.textContent = `Score: ${quizUserScore}/${window.currentQuizQuestions.length}`;
        badge.classList.add('score-bump');
        setTimeout(() => badge.classList.remove('score-bump'), 400);
    }

    // Color buttons
    card.querySelectorAll('.quiz-opt-btn').forEach((btn, idx) => {
        btn.disabled = true;
        if (idx === correctIdx) {
            btn.classList.add('correct');
        } else if (idx === selectedOptIdx) {
            btn.classList.add('incorrect');
        }
    });

    // Reveal explanation
    const exp = document.getElementById(`quiz-exp-${qIdx}`);
    if (exp) exp.style.display = 'block';
}

// ===== Mode 4: CREATE / ACT MODE =====
function renderViralClips(clips) {
    const grid = document.getElementById('viralClipsGrid');
    if (!grid) return;

    if (!clips.length) {
        grid.innerHTML = '<p class="text-muted">No viral clip segments generated.</p>';
        return;
    }

    grid.innerHTML = clips.map(c => {
        const startSec = c.start_seconds || parseTimestampToSeconds(c.start_time);
        return `
            <div class="viral-clip-card">
                <div>
                    <div style="display:flex; justify-content:space-between; align-items:center;">
                        <span class="viral-score-tag">⚡ ${c.viral_score || 90}/100 VIRAL SCORE</span>
                        <button class="timestamp-pill" onclick="jumpToSecond(${startSec})">
                            <span>▶</span> ${escapeHtml(c.start_time || '')} - ${escapeHtml(c.end_time || '')}
                        </button>
                    </div>
                    <h4 class="mt-8" style="color:var(--text-primary); font-size:14.5px;">${escapeHtml(c.title)}</h4>
                    <div class="viral-hook-text">"${escapeHtml(c.hook)}"</div>
                    <p class="text-muted font-sm">${escapeHtml(c.rationale || '')}</p>
                </div>
                <div class="mt-16 flex-row-gap">
                    <button class="btn-hero btn-primary-hero btn-sm" onclick="jumpToSecond(${startSec})">
                        ▶ Preview Clip
                    </button>
                    <button class="btn-hero btn-secondary-hero btn-sm" onclick="copyWithFeedback('${escapeJsString(c.hook)}', this, 'Hook copied!')">
                        Copy Hook
                    </button>
                </div>
            </div>
        `;
    }).join('');
}

function renderSocialPosts(social, rawChapters) {
    const threadBox = document.getElementById('twitterThreadBox');
    if (threadBox) {
        const tweets = social.twitter_thread || [];
        threadBox.textContent = tweets.join('\n\n---\n\n');
    }

    const linkedInBox = document.getElementById('linkedinPostBox');
    if (linkedInBox) {
        linkedInBox.textContent = social.linkedin_post || '';
    }

    const newsBox = document.getElementById('newsletterDraftBox');
    if (newsBox) {
        const ne = social.newsletter_edition || {};
        newsBox.textContent = `SUBJECT: ${ne.subject || 'Executive Briefing'}\n\n${ne.intro || ''}\n\nKey Takeaways:\n${(ne.key_bullets || []).map(b => '• ' + b).join('\n')}\n\nAction Item:\n${ne.action_item || ''}`;
    }

    const chaptersBox = document.getElementById('rawChaptersBox');
    if (chaptersBox) {
        chaptersBox.textContent = rawChapters || '00:00 Introduction';
    }
}

function copyTwitterThread(btn) {
    const t = document.getElementById('twitterThreadBox');
    if (t) copyWithFeedback(t.textContent, btn, 'Twitter thread copied!');
}
function copyLinkedInPost(btn) {
    const l = document.getElementById('linkedinPostBox');
    if (l) copyWithFeedback(l.textContent, btn, 'LinkedIn post copied!');
}
function copyNewsletterDraft(btn) {
    const n = document.getElementById('newsletterDraftBox');
    if (n) copyWithFeedback(n.textContent, btn, 'Newsletter draft copied!');
}
function copyYouTubeChapters(btn) {
    const c = document.getElementById('rawChaptersBox');
    if (c) copyWithFeedback(c.textContent, btn, 'YouTube chapters copied!');
}
function copyStudyNotes(btn) {
    const container = document.getElementById('studyNotesContainer');
    if (container) copyWithFeedback(container.innerText, btn, 'Study notes copied!');
}

// ===== Mode 5: COMPARE MODE =====
function openCompareModal() {
    switchMainMode('compare');
}

function populateCompareDropdown() {
    const select = document.getElementById('compareSelectVideoB');
    if (!select) return;

    try {
        const raw = localStorage.getItem(STORAGE_KEY);
        const list = raw ? JSON.parse(raw) : [];
        const curId = currentAnalysis?._meta?.video_id;

        const otherVideos = list.filter(v => v._meta?.video_id !== curId);
        if (!otherVideos.length) {
            select.innerHTML = '<option value="">-- No other videos in history. Analyze a 2nd video first! --</option>';
            return;
        }

        select.innerHTML = '<option value="">-- Select a video from your history --</option>' + 
            otherVideos.map(v => `<option value="${v._meta?.video_id}">${escapeHtml(v._meta?.title || 'Video')}</option>`).join('');
    } catch (e) {
        console.error(e);
    }
}

async function runVideoComparison() {
    const select = document.getElementById('compareSelectVideoB');
    const videoIdB = select?.value;

    if (!videoIdB || !currentAnalysis) {
        showToast('⚠️ Please select a second video from the dropdown first.', 'warning');
        return;
    }

    const raw = localStorage.getItem(STORAGE_KEY);
    const list = raw ? JSON.parse(raw) : [];
    const videoB = list.find(v => v._meta?.video_id === videoIdB);

    if (!videoB) {
        showToast('❌ Could not find selected video in history.', 'error');
        return;
    }

    showToast('⚖️ Synthesizing cross-video comparative intelligence...', 'info');

    try {
        const res = await fetch('/api/compare', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                video_id_a: currentAnalysis._meta?.video_id,
                video_id_b: videoIdB,
                video_a: currentAnalysis,
                video_b: videoB
            })
        });

        const data = await res.json();
        if (data.error) throw new Error(data.error);

        renderComparisonResults(data, currentAnalysis._meta?.title, videoB._meta?.title);
        showToast('✓ Comparison matrix ready!', 'success');
    } catch (err) {
        showToast('❌ Comparison failed: ' + err.message, 'error');
    }
}

function renderComparisonResults(comp, titleA, titleB) {
    const container = document.getElementById('compareResultsContainer');
    if (!container) return;

    container.style.display = 'block';
    document.getElementById('thVideoA').textContent = titleA || comp.title_a || 'Video A';
    document.getElementById('thVideoB').textContent = titleB || comp.title_b || 'Video B';

    const tbody = document.getElementById('compareMatrixBody');
    if (tbody && comp.comparison_matrix) {
        tbody.innerHTML = comp.comparison_matrix.map(row => `
            <tr>
                <td><strong>${escapeHtml(row.dimension)}</strong></td>
                <td>${escapeHtml(row.video_a)}</td>
                <td>${escapeHtml(row.video_b)}</td>
            </tr>
        `).join('');
    }

    const themesList = document.getElementById('compareCommonThemesList');
    if (themesList && comp.common_themes) {
        themesList.innerHTML = comp.common_themes.map(t => `<li>${escapeHtml(t)}</li>`).join('');
    }

    const disList = document.getElementById('compareDisagreementsList');
    if (disList && comp.key_disagreements) {
        disList.innerHTML = comp.key_disagreements.map(d => `
            <div class="disagreement-item">
                <strong>Topic: ${escapeHtml(d.topic)}</strong>
                <p class="mt-4"><strong>Video A:</strong> ${escapeHtml(d.video_a_view)}</p>
                <p><strong>Video B:</strong> ${escapeHtml(d.video_b_view)}</p>
                <p class="text-muted font-sm mt-4"><em>Synthesis verdict:</em> ${escapeHtml(d.verdict || '')}</p>
            </div>
        `).join('');
    }

    const verdictEl = document.getElementById('compareVerdictText');
    if (verdictEl) verdictEl.textContent = comp.synthesis_verdict || '';
}

// ===== Command Palette (Ctrl+K) =====
const COMMANDS = [
    { title: "Analyze New Video URL...", sub: "Paste another YouTube link to analyze", badge: "Action", action: () => promptNewAnalysis() },
    { title: "Understand Mode", sub: "View overview, chapters, and score", badge: "Navigation", action: () => switchMainMode('understand') },
    { title: "Research Mode", sub: "View claims, entities, and contradictions", badge: "Navigation", action: () => switchMainMode('research') },
    { title: "Learn Mode", sub: "View definitions, notes, and quiz", badge: "Navigation", action: () => switchMainMode('learn') },
    { title: "Create / Act Mode", sub: "Curated shorts and social threads", badge: "Navigation", action: () => switchMainMode('create') },
    { title: "Compare Mode", sub: "Side-by-side cross-video matrix", badge: "Navigation", action: () => switchMainMode('compare') },
    { title: "Ask Copilot with Evidence", sub: "Grounded Q&A with timestamps", badge: "Copilot", action: () => switchMainMode('copilot') },
    { title: "Video Map Knowledge Graph", sub: "Jump to interactive concept network", badge: "Feature", action: () => scrollToElement('section-videomap') },
    { title: "Multi-Track Timeline", sub: "Inspect topics, speakers, and claims tracks", badge: "Feature", action: () => scrollToElement('section-multitrack') },
    { title: "Interactive Quiz", sub: "Test your video comprehension", badge: "Learn", action: () => { switchMainMode('learn'); scrollToElement('quizContainer'); } },
    { title: "Practice Flashcards", sub: "Flip through video revision cards", badge: "Learn", action: () => { switchMainMode('learn'); scrollToElement('activeFlashcard'); } },
    { title: "Viral Shorts Clip Ideas", sub: "Review curated Shorts hooks and scores", badge: "Create", action: () => { switchMainMode('create'); } },
    { title: "Export Detailed PDF", sub: "Download publication-grade intelligence dossier", badge: "Export", action: () => exportDetailedPDF() },
    { title: "Copy Summary", sub: "Copy executive synthesis to clipboard", badge: "Share", action: () => copyShareableSummary() },
    { title: "Copy YouTube Chapters", sub: "Copy timestamp chapters description", badge: "Create", action: () => copyYouTubeChapters() }
];

let selectedCommandIdx = 0;

function setupCommandPalette() {
    renderCommandPaletteResults(COMMANDS);

    const input = document.getElementById('cmdPaletteInput');
    if (input) {
        input.addEventListener('keydown', (e) => {
            const list = window.currentFilteredCommands || COMMANDS;
            if (!list.length) return;

            if (e.key === 'ArrowDown') {
                e.preventDefault();
                selectedCommandIdx = (selectedCommandIdx + 1) % list.length;
                updateCommandSelection();
            } else if (e.key === 'ArrowUp') {
                e.preventDefault();
                selectedCommandIdx = (selectedCommandIdx - 1 + list.length) % list.length;
                updateCommandSelection();
            } else if (e.key === 'Enter') {
                e.preventDefault();
                executeCommand(selectedCommandIdx);
            }
        });
    }
}

function updateCommandSelection() {
    document.querySelectorAll('.cmd-item').forEach((item, idx) => {
        item.classList.toggle('active', idx === selectedCommandIdx);
        if (idx === selectedCommandIdx) {
            item.scrollIntoView({ block: 'nearest' });
        }
    });
}

function toggleCommandPalette() {
    const backdrop = document.getElementById('cmdPaletteBackdrop');
    if (backdrop) {
        if (backdrop.classList.contains('open')) {
            closeCommandPalette();
        } else {
            openCommandPalette();
        }
    }
}

function openCommandPalette() {
    const backdrop = document.getElementById('cmdPaletteBackdrop');
    const input = document.getElementById('cmdPaletteInput');
    if (backdrop && input) {
        backdrop.classList.add('open');
        input.value = '';
        selectedCommandIdx = 0;
        renderCommandPaletteResults(COMMANDS);
        setTimeout(() => input.focus(), 50);
    }
}

function closeCommandPalette(e) {
    if (e && e.target && e.target.id !== 'cmdPaletteBackdrop' && !e.target.classList.contains('cmd-esc-tag')) return;
    const backdrop = document.getElementById('cmdPaletteBackdrop');
    if (backdrop) backdrop.classList.remove('open');
}

function filterCommandPalette(query) {
    const q = (query || '').toLowerCase().trim();
    selectedCommandIdx = 0;
    if (!q) {
        renderCommandPaletteResults(COMMANDS);
        return;
    }
    const filtered = COMMANDS.filter(cmd => 
        cmd.title.toLowerCase().includes(q) || 
        cmd.sub.toLowerCase().includes(q) || 
        cmd.badge.toLowerCase().includes(q)
    );
    renderCommandPaletteResults(filtered);
}

function renderCommandPaletteResults(list) {
    const container = document.getElementById('cmdResultsList');
    if (!container) return;

    if (!list.length) {
        container.innerHTML = '<div style="padding: 16px 20px; color: var(--text-muted);">No matching commands found.</div>';
        return;
    }

    container.innerHTML = list.map((cmd, idx) => `
        <div class="cmd-item ${idx === selectedCommandIdx ? 'active' : ''}" onclick="executeCommand(${idx})">
            <div class="cmd-item-left">
                <span class="cmd-item-icon">✦</span>
                <div>
                    <div class="cmd-item-title">${escapeHtml(cmd.title)}</div>
                    <div class="cmd-item-sub">${escapeHtml(cmd.sub)}</div>
                </div>
            </div>
            <span class="cmd-item-badge">${escapeHtml(cmd.badge)}</span>
        </div>
    `).join('');

    window.currentFilteredCommands = list;
}

function executeCommand(idx) {
    const list = window.currentFilteredCommands || COMMANDS;
    const cmd = list[idx];
    if (cmd && typeof cmd.action === 'function') {
        const backdrop = document.getElementById('cmdPaletteBackdrop');
        if (backdrop) backdrop.classList.remove('open');
        cmd.action();
    }
}

// ===== Mode 6: AI Copilot & Evidence Grounding =====
function askCopilot(question) {
    switchMainMode('copilot');
    const input = document.getElementById('copilotQueryInput');
    if (input) {
        input.value = question;
        handleCopilotSubmit(new Event('submit'));
    }
}

async function handleCopilotSubmit(e) {
    if (e) e.preventDefault();
    const input = document.getElementById('copilotQueryInput');
    const query = input.value.trim();
    if (!query || !currentAnalysis) return;

    const evidenceMode = document.getElementById('evidenceModeToggle')?.checked !== false;

    // Append User Message
    appendCopilotMessage('user', query);
    input.value = '';

    // Append AI Loading Indicator
    const loaderId = appendCopilotMessage('ai', '<span class="copilot-thinking-pulse">✦ Deeply cross-referencing full transcript & grounded evidence...</span>', true);

    try {
        const res = await fetch('/api/chat', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                question: query,
                mode: evidenceMode ? "evidence" : "general",
                title: currentAnalysis._meta?.title || '',
                video_id: currentAnalysis._meta?.video_id || '',
                summary: currentAnalysis.video_overview?.summary || '',
                snippets: currentAnalysis._transcript_sample || []
            })
        });

        const data = await res.json();
        if (data.answer) {
            updateCopilotMessage(loaderId, formatCopilotAnswer(data.answer));
        } else {
            updateCopilotMessage(loaderId, '<p class="chat-p">I could not find a specific answer to that in the video.</p>');
        }
    } catch (err) {
        updateCopilotMessage(loaderId, '<p class="chat-p text-danger">Error connecting to AI Copilot: ' + escapeHtml(err.message) + '</p>');
    }
}

function appendCopilotMessage(role, content, isHtml = false) {
    const container = document.getElementById('copilotMessages');
    const msgId = 'msg-' + Date.now();
    const msg = document.createElement('div');
    msg.id = msgId;
    msg.className = `chat-msg ${role === 'user' ? 'user-msg' : 'ai-msg'}`;
    const bodyHtml = isHtml ? content : escapeHtml(content);
    msg.innerHTML = `
        <div class="msg-author">${role === 'user' ? '👤 You' : '✦ LensYou Grounded Copilot'}</div>
        <div class="msg-content">${bodyHtml}</div>
    `;
    container.appendChild(msg);
    container.scrollTop = container.scrollHeight;
    return msgId;
}

function updateCopilotMessage(msgId, formattedHtml) {
    const el = document.getElementById(msgId);
    if (el) {
        el.querySelector('.msg-content').innerHTML = formattedHtml;
    }
}

function formatCopilotAnswer(rawText) {
    if (!rawText) return '';
    let text = rawText.trim();

    // 1. Convert markdown headers
    text = text.replace(/^###\s+(.+)$/gm, '<h5 class="chat-h5">$1</h5>');
    text = text.replace(/^##\s+(.+)$/gm, '<h4 class="chat-h4">$1</h4>');
    text = text.replace(/^#\s+(.+)$/gm, '<h3 class="chat-h3">$1</h3>');

    // 2. Line-by-line list and paragraph processor
    const lines = text.split('\n');
    let inUl = false;
    let inOl = false;
    const processed = [];

    for (let rawLine of lines) {
        let line = rawLine.trim();
        if (!line) {
            if (inUl) { processed.push('</ul>'); inUl = false; }
            if (inOl) { processed.push('</ol>'); inOl = false; }
            continue;
        }

        const bulletMatch = line.match(/^[\*\-]\s+(.+)$/);
        const numMatch = line.match(/^(\d+)\.\s+(.+)$/);

        if (bulletMatch) {
            if (!inUl) {
                if (inOl) { processed.push('</ol>'); inOl = false; }
                processed.push('<ul class="chat-ul">');
                inUl = true;
            }
            processed.push('<li>' + bulletMatch[1] + '</li>');
        } else if (numMatch) {
            if (!inOl) {
                if (inUl) { processed.push('</ul>'); inUl = false; }
                processed.push('<ol class="chat-ol">');
                inOl = true;
            }
            processed.push('<li>' + numMatch[2] + '</li>');
        } else {
            if (inUl) { processed.push('</ul>'); inUl = false; }
            if (inOl) { processed.push('</ol>'); inOl = false; }
            if (line.startsWith('<h') || line.startsWith('<blockquote') || line.startsWith('<table')) {
                processed.push(line);
            } else {
                processed.push('<p class="chat-p">' + line + '</p>');
            }
        }
    }
    if (inUl) processed.push('</ul>');
    if (inOl) processed.push('</ol>');

    let html = processed.join('');

    // 3. Convert markdown bold **text** to <strong>text</strong>
    html = html.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');

    // 4. Convert inline code `code`
    html = html.replace(/`([^`]+)`/g, '<code class="chat-code">$1</code>');

    // 5. Convert [MM:SS] or [HH:MM:SS] timestamps to clickable pills
    html = html.replace(/\[(\d{1,2}:\d{2}(?::\d{2})?)\]/g, (match, timeStr) => {
        const sec = parseTimestampToSeconds(timeStr);
        return `<button class="timestamp-pill" onclick="jumpToSecond(${sec})" title="Jump to ${timeStr} in video">▶ ${timeStr} ↗</button>`;
    });

    // 6. Clean up any remaining stray asterisks
    html = html.replace(/\*\*/g, '');

    return html;
}

// ===== Video Jumper =====
function jumpToSecond(seconds) {
    if (!currentAnalysis || !currentAnalysis._meta) return;
    const videoId = currentAnalysis._meta.video_id;
    const url = `https://www.youtube.com/watch?v=${videoId}&t=${Math.floor(seconds)}s`;
    window.open(url, '_blank');
}

function openVideoPlayer() {
    if (currentAnalysis && currentAnalysis._meta) {
        window.open(currentAnalysis._meta.video_url, '_blank');
    }
}

// ===== LocalStorage History Manager =====
function initHistory() {
    renderHistoryDrawers();
}

function saveToHistory(analysis) {
    try {
        const raw = localStorage.getItem(STORAGE_KEY);
        let list = raw ? JSON.parse(raw) : [];

        const vid = analysis._meta?.video_id;
        list = list.filter(item => item._meta?.video_id !== vid);

        const compactItem = {
            _meta: analysis._meta,
            video_overview: analysis.video_overview,
            metrics: analysis.metrics,
            quality_scorecard: analysis.quality_scorecard,
            engagement_curve: analysis.engagement_curve,
            key_takeaways: analysis.key_takeaways,
            timeline: analysis.timeline,
            chapters: analysis.chapters,
            topics: analysis.topics,
            speakers: analysis.speakers,
            claims: analysis.claims,
            entities: analysis.entities,
            repetitions: analysis.repetitions,
            contradictions: analysis.contradictions,
            learning: analysis.learning,
            creator_repurposing: analysis.creator_repurposing,
            visual_moments: analysis.visual_moments,
            knowledge_graph: analysis.knowledge_graph,
            _transcript_sample: analysis._transcript_sample ? analysis._transcript_sample.slice(0, 100) : []
        };

        list.unshift(compactItem);
        if (list.length > 20) list = list.slice(0, 20);

        localStorage.setItem(STORAGE_KEY, JSON.stringify(list));
        renderHistoryDrawers();
    } catch (e) {
        console.warn('LocalStorage save failed:', e);
    }
}

async function renderHistoryDrawers() {
    let list = [];
    try {
        const res = await fetch('/api/history?action=process&limit=20');
        if (res.ok) {
            const data = await res.json();
            if (data.items && data.items.length) {
                list = data.items.map(item => ({
                    _meta: {
                        video_id: item.content_id,
                        title: item.content_title || item.query,
                        author: 'YouTube Creator',
                        duration: item.duration || 'N/A',
                        thumbnail_url: `https://img.youtube.com/vi/${item.content_id}/mqdefault.jpg`
                    }
                }));
                const badge = document.getElementById('historyBadge');
                if (badge) badge.textContent = data.total || list.length;
            }
        }
    } catch (e) {
        console.warn('API history fetch fallback to localStorage:', e);
    }

    if (!list.length) {
        try {
            const raw = localStorage.getItem(STORAGE_KEY);
            if (raw) list = JSON.parse(raw);
        } catch (e) {
            list = [];
        }
        const badge = document.getElementById('historyBadge');
        if (badge) badge.textContent = list.length;
    }

    const miniContainer = document.getElementById('sidebarHistoryList');
    if (miniContainer) {
        if (!list.length) {
            miniContainer.innerHTML = '<div class="empty-history-note">No recent analyses</div>';
        } else {
            miniContainer.innerHTML = list.slice(0, 5).map(item => `
                <div class="history-mini-item" onclick="loadFromHistory('${item._meta?.video_id}')">
                    <img src="${item._meta?.thumbnail_url || ''}" class="history-thumb-mini" alt="Thumb" onerror="this.src='/static/logo.svg'">
                    <div class="history-meta-mini">
                        <div class="history-title-mini">${escapeHtml(item._meta?.title || 'Video')}</div>
                        <div class="history-time-mini">${item._meta?.duration || ''}</div>
                    </div>
                </div>
            `).join('');
        }
    }

    const drawerContainer = document.getElementById('drawerHistoryList');
    if (drawerContainer) {
        if (!list.length) {
            drawerContainer.innerHTML = '<div class="empty-history-note">No saved analyses yet.</div>';
        } else {
            drawerContainer.innerHTML = list.map(item => `
                <div class="history-drawer-item" onclick="loadFromHistory('${item._meta?.video_id}'); toggleHistoryDrawer();">
                    <img src="${item._meta?.thumbnail_url || ''}" class="drawer-thumb" alt="Thumb" onerror="this.src='/static/logo.svg'">
                    <div class="drawer-meta">
                        <div class="drawer-title">${escapeHtml(item._meta?.title || 'Video')}</div>
                        <div class="drawer-sub">${escapeHtml(item._meta?.author || '')} • ${item._meta?.duration || ''}</div>
                    </div>
                </div>
            `).join('');
        }
    }
}

async function loadFromHistory(videoId) {
    if (!videoId) return;
    try {
        // 1. Try local memory / cache first
        const raw = localStorage.getItem(STORAGE_KEY);
        if (raw) {
            const list = JSON.parse(raw);
            const match = list.find(item => item._meta?.video_id === videoId);
            if (match && match.video_overview) {
                currentAnalysis = match;
                renderDashboard(match);
                showScreen('dashboard');
                showToast('✓ Loaded analysis from session history!', 'success');
                return;
            }
        }

        // 2. Fetch full dossier from server database
        showToast('⏳ Retrieving full video intelligence dossier...', 'info');
        const res = await fetch(`/api/analysis/${encodeURIComponent(videoId)}`);
        if (res.ok) {
            const fullData = await res.json();
            currentAnalysis = fullData;
            renderDashboard(fullData);
            showScreen('dashboard');
            showToast('✓ Restored analysis from database!', 'success');
            return;
        }

        // 3. If not cached, launch analysis
        showToast('Re-analyzing video...', 'info');
        startAnalysis(`https://www.youtube.com/watch?v=${videoId}`);

    } catch (e) {
        showToast('❌ Failed to load analysis: ' + e.message, 'error');
    }
}

function toggleHistoryDrawer() {
    const drawer = document.getElementById('historyDrawer');
    const overlay = document.getElementById('drawerOverlay');
    if (drawer && overlay) {
        drawer.classList.toggle('open');
        overlay.classList.toggle('open');
    }
}

// ===== Export PDF & Share =====
async function exportDetailedPDF() {
    if (!currentAnalysis) {
        showToast('⚠️ Please analyze a video first to export PDF.', 'warning');
        return;
    }

    showToast('⏳ Generating publication-grade PDF dossier...', 'info');

    try {
        const response = await fetch('/api/export-pdf', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(currentAnalysis)
        });

        if (!response.ok) {
            throw new Error('PDF generation failed on server.');
        }

        const blob = await response.blob();
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.style.display = 'none';
        a.href = url;

        const title = currentAnalysis._meta?.title || 'analysis';
        const cleanTitle = title.replace(/[^a-zA-Z0-9_-]/g, '_').substring(0, 30);
        a.download = `LensYou_${cleanTitle}_Report.pdf`;

        document.body.appendChild(a);
        a.click();
        window.URL.revokeObjectURL(url);
        document.body.removeChild(a);

        showToast('✓ Detailed PDF downloaded successfully!', 'success');
    } catch (err) {
        showToast('❌ PDF Export failed: ' + err.message, 'error');
    }
}

function printReportPreview() {
    window.print();
}

function copyShareableSummary(btn = null) {
    if (!currentAnalysis) return;
    const title = currentAnalysis._meta?.title || 'Video';
    const summary = currentAnalysis.video_overview?.summary || '';
    const text = `🎬 ${title}\n\n✦ AI Executive Summary:\n${summary}\n\nAnalyzed with LensYou Video Intelligence Platform.`;
    copyWithFeedback(text, btn, 'Executive summary copied to clipboard!');
}

function copyWithFeedback(text, btn, successMsg = 'Copied to clipboard!') {
    const onCopied = () => {
        showToast('✓ ' + successMsg, 'success');
        if (btn) {
            const originalHtml = btn.innerHTML;
            btn.innerHTML = '<span>✓</span> Copied!';
            btn.classList.add('copied');
            setTimeout(() => {
                btn.innerHTML = originalHtml;
                btn.classList.remove('copied');
            }, 1400);
        }
    };

    if (!navigator.clipboard) {
        fallbackCopyText(text);
        onCopied();
        return;
    }
    navigator.clipboard.writeText(text).then(onCopied).catch(() => {
        fallbackCopyText(text);
        onCopied();
    });
}

function fallbackCopyText(text) {
    const ta = document.createElement('textarea');
    ta.value = text;
    ta.style.position = 'fixed';
    ta.style.top = '0';
    ta.style.left = '0';
    document.body.appendChild(ta);
    ta.focus();
    ta.select();
    try { document.execCommand('copy'); } catch (e) {}
    document.body.removeChild(ta);
}

let toastTimer = null;
function showToast(msg, type = 'info') {
    const toast = document.getElementById('toastNotification');
    if (!toast) return;

    let icon = '✦';
    let borderColor = '#8B7CFF';
    if (type === 'success' || msg.includes('✓')) {
        icon = '✓';
        borderColor = '#22C55E';
    } else if (type === 'error' || msg.includes('❌')) {
        icon = '✕';
        borderColor = '#EF4444';
    } else if (type === 'warning' || msg.includes('⚠')) {
        icon = '⚠';
        borderColor = '#F59E0B';
    }

    const cleanMsg = msg.replace(/^[✓✕❌⚠✦]\s*/, '');
    toast.style.borderLeft = `3px solid ${borderColor}`;
    toast.innerHTML = `<span style="color:${borderColor}; font-weight:700;">${icon}</span> <span>${escapeHtml(cleanMsg)}</span>`;
    toast.style.display = 'flex';

    if (toastTimer) clearTimeout(toastTimer);
    toastTimer = setTimeout(() => {
        toast.style.display = 'none';
    }, 3200);
}

// ===== Utility Helpers =====
function escapeHtml(str) {
    if (!str) return '';
    return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

function escapeJsString(str) {
    if (!str) return '';
    return String(str)
        .replace(/\\/g, '\\\\')
        .replace(/'/g, "\\'")
        .replace(/"/g, '\\"')
        .replace(/\n/g, '\\n')
        .replace(/\r/g, '');
}

function escapeRegex(str) {
    return str.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

function parseTimestampToSeconds(timeStr) {
    if (!timeStr) return 0;
    const parts = timeStr.trim().split(':').map(Number);
    if (parts.some(isNaN)) return 0;
    if (parts.length === 3) {
        return parts[0] * 3600 + parts[1] * 60 + parts[2];
    } else if (parts.length === 2) {
        return parts[0] * 60 + parts[1];
    }
    return 0;
}

function formatSeconds(seconds) {
    seconds = Math.floor(seconds || 0);
    const h = Math.floor(seconds / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    const s = seconds % 60;
    if (h > 0) {
        return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
    }
    return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
}

// ===== Phase 3: Usage Counter & Supporter Banner =====
async function updateUsageCounter() {
    try {
        const res = await fetch('/api/usage-stats');
        if (res.ok) {
            const data = await res.json();
            const countEl = document.getElementById('usageCount');
            if (countEl && typeof data.total_analyses === 'number') {
                countEl.textContent = data.total_analyses;
            }
        }
    } catch (e) {
        // Silently ignore usage counter fetch failure
    }
}

function closeSupporterBanner() {
    const banner = document.getElementById('supporterSection');
    if (banner) banner.style.display = 'none';
    try {
        sessionStorage.setItem('supporter_dismissed', '1');
    } catch (e) {}
}

// ===== Auth & Quota State =====
let currentUser = null;
async function loadUserState() {
    try {
        const res = await fetch('/api/me');
        if (!res.ok) return;
        const data = await res.json();
        currentUser = data.user || null;
        const quota = data.quota || data.quota_info || (data.user && data.user.quota_info);
        updateAuthUI(currentUser);
        updateQuotaUI(quota);
    } catch (e) {
        console.warn('loadUserState fetch error:', e);
    }
}

function updateAuthUI(user) {
    const panel = document.getElementById('userInfoPanel');
    const navSlot = document.getElementById('navUserSlot');

    if (user && user.email) {
        const initial = (user.name || user.email || 'U')[0].toUpperCase();
        const planBadge = user.plan === 'unlimited' ? 'Pro' : (user.plan === 'pack10' ? '₹50' : 'Free');

        if (panel) {
            panel.innerHTML = `
                <div style="display:flex; align-items:center; gap:8px; width:100%; justify-content:space-between;">
                    <div style="display:flex; align-items:center; gap:8px; min-width:0;">
                        ${user.avatar_url 
                            ? `<img src="${escapeHtml(user.avatar_url)}" style="width:28px; height:28px; border-radius:50%; object-fit:cover; border:1px solid var(--border);" alt="avatar">`
                            : `<div style="width:28px; height:28px; border-radius:50%; background:var(--purple-primary); display:flex; align-items:center; justify-content:center; font-size:12px; font-weight:700; color:#fff;">${initial}</div>`
                        }
                        <div style="min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">
                            <div style="font-size:12px; font-weight:600; color:var(--text-primary); text-overflow:ellipsis; overflow:hidden;">${escapeHtml(user.name || user.email)}</div>
                            <div style="font-size:10px; color:var(--text-muted); text-transform:uppercase;">${escapeHtml(user.plan || 'Free')}</div>
                        </div>
                    </div>
                    <a href="/auth/logout" style="font-size:11px; color:var(--text-muted); text-decoration:none; padding:4px 6px; border-radius:4px; border:1px solid var(--border);" title="Log out">⎋</a>
                </div>
            `;
        }

        if (navSlot) {
            navSlot.innerHTML = `
                <div style="display:flex; align-items:center; gap:8px;">
                    ${user.avatar_url 
                        ? `<img src="${escapeHtml(user.avatar_url)}" style="width:26px; height:26px; border-radius:50%; object-fit:cover; border:1px solid var(--border);">`
                        : `<span style="width:26px; height:26px; border-radius:50%; background:var(--purple-primary); display:inline-flex; align-items:center; justify-content:center; font-size:11px; font-weight:700; color:#fff;">${initial}</span>`
                    }
                    <span style="font-size:10px; padding:2px 6px; background:rgba(255,255,255,0.08); color:var(--text-secondary); border-radius:4px; font-weight:600;">${planBadge}</span>
                    ${user.is_owner ? `<a href="/admin" class="action-btn" style="text-decoration:none; padding:2px 6px; font-size:11px; color:var(--text-main); background:rgba(255,255,255,0.06); border:1px solid var(--border); font-weight:600;">Owner</a>` : ''}
                    <a href="/auth/logout" class="action-btn" style="text-decoration:none; padding:2px 6px; font-size:11px;" title="Sign out">⎋</a>
                </div>
            `;
        }
    } else {
        if (panel) {
            panel.innerHTML = `<button class="login-btn" onclick="openAuthModal('Sign in to access more features')">Sign in</button>`;
        }
        if (navSlot) {
            navSlot.innerHTML = `<button class="action-btn" onclick="openAuthModal('Sign in to save history and unlock features')">Sign In</button>`;
        }
    }
}

async function initiatePlanPurchase(plan) {
    if (!currentUser) {
        openAuthModal('Please sign in with Google first to upgrade your account.');
        return;
    }
    showToast(`Initiating upgrade for ${plan}...`, 'info');
    try {
        const res = await fetch('/api/payment/verify', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ plan: plan, provider: 'checkout' })
        });
        const data = await res.json();
        if (data.success) {
            showToast(`✓ ${data.message || 'Upgraded successfully!'}`, 'success');
            closeUpgradeModal();
            await loadUserState();
        } else {
            showToast(data.error || 'Payment failed', 'error');
        }
    } catch (e) {
        showToast('Payment processing error: ' + e.message, 'error');
    }
}

function checkCookieConsent() {
    try {
        if (!localStorage.getItem('videolens_cookie_consent')) {
            const banner = document.getElementById('cookieConsentBanner');
            if (banner) banner.style.display = 'flex';
        }
    } catch (e) {}
}

function acceptCookieConsent() {
    try {
        localStorage.setItem('videolens_cookie_consent', 'accepted');
        const banner = document.getElementById('cookieConsentBanner');
        if (banner) banner.style.display = 'none';
        showToast('✓ Privacy preferences saved.', 'success');
    } catch (e) {}
}

function updateQuotaUI(quota) {
    if (!quota) return;
    const usedEl = document.getElementById('quotaUsed');
    const totalEl = document.getElementById('quotaTotal');
    const fillEl = document.getElementById('quotaFill');

    const isUnlimited = quota.limit === -1 || quota.plan === 'unlimited';
    if (usedEl) usedEl.textContent = quota.used || 0;
    if (totalEl) totalEl.textContent = isUnlimited ? '∞' : (quota.limit || 3);
    if (fillEl) {
        if (isUnlimited) {
            fillEl.style.width = '100%';
            fillEl.style.background = 'var(--gradient-cta)';
        } else {
            const limit = quota.limit || 3;
            const pct = Math.min(100, Math.round(((quota.used || 0) / limit) * 100));
            fillEl.style.width = pct + '%';
            if (pct >= 100) fillEl.style.background = 'var(--error)';
            else fillEl.style.background = 'var(--purple-primary)';
        }
    }
}

function openAuthModal(reason = '') {
    const modal = document.getElementById('authModal');
    const reasonEl = document.getElementById('authModalReason');
    if (modal) modal.classList.add('open');
    if (reasonEl && reason) reasonEl.textContent = reason;
}

function closeAuthModal() {
    const modal = document.getElementById('authModal');
    if (modal) modal.classList.remove('open');
}

function openUpgradeModal(quota) {
    const modal = document.getElementById('upgradeModal');
    if (modal) modal.classList.add('open');
}

function closeUpgradeModal() {
    const modal = document.getElementById('upgradeModal');
    if (modal) modal.classList.remove('open');
}

function openSupportModal() {
    const modal = document.getElementById('supportModal');
    if (modal) modal.classList.add('open');
}

function closeSupportModal() {
    const modal = document.getElementById('supportModal');
    if (modal) modal.classList.remove('open');
}

async function redeemCode() {
    const input = document.getElementById('redeemCodeInput');
    const code = input ? input.value.trim() : '';
    if (!code) {
        showToast('Please enter a redemption code', 'warning');
        return;
    }
    try {
        const res = await fetch('/api/redeem', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ code })
        });
        const data = await res.json();
        if (data.success) {
            showToast(data.message || 'Code redeemed successfully!', 'success');
            closeUpgradeModal();
            await loadUserState();
        } else {
            showToast(data.message || 'Invalid redemption code', 'error');
        }
    } catch (e) {
        showToast('Redemption failed: ' + e.message, 'error');
    }
}

function toggleSidebar() {
    const sidebar = document.getElementById('sidebar');
    if (!sidebar) return;
    const collapsed = sidebar.classList.toggle('collapsed');
    localStorage.setItem('sidebarCollapsed', collapsed);
}

// Admin portal functions (used by templates/admin.html)
async function loadAdminDashboard() {
    try {
        const [health, stats, users, videos, logs, keys] = await Promise.all([
            fetch('/admin/api/health').then(r => r.json()).catch(() => ({})),
            fetch('/admin/api/stats').then(r => r.json()).catch(() => ({})),
            fetch('/admin/api/users').then(r => r.json()).catch(() => ([])),
            fetch('/admin/api/videos').then(r => r.json()).catch(() => ([])),
            fetch('/admin/api/logs').then(r => r.json()).catch(() => ([])),
            fetch('/admin/api/api-keys').then(r => r.json()).catch(() => ([]))
        ]);
        if (typeof renderAdminOverview === 'function') renderAdminOverview(health, stats);
        if (typeof renderAdminUsers === 'function') renderAdminUsers(users);
        if (typeof renderAdminVideos === 'function') renderAdminVideos(videos);
        if (typeof renderAdminLogs === 'function') renderAdminLogs(logs);
        if (typeof renderAdminApiKeys === 'function') renderAdminApiKeys(keys);
    } catch (e) {
        console.warn('loadAdminDashboard error:', e);
    }
}

async function generateCodes() {
    const plan = document.getElementById('codePlan')?.value || '10';
    const count = document.getElementById('codeCount')?.value || 5;
    try {
        const res = await fetch('/admin/api/generate-codes', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ plan, count })
        });
        const data = await res.json();
        if (typeof displayGeneratedCodes === 'function') displayGeneratedCodes(data.codes);
    } catch (e) {
        showToast('Code generation failed', 'error');
    }
}
