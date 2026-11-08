/**
 * test_m4_ux_view_stress.js
 * Empirical JavaScript Test Harness for Milestone 4:
 * - Feature F14 (Guided First-Time UX)
 * - Feature F15 (View Segregation & Client Exports)
 *
 * Runs under Node.js by constructing a DOM/Browser mock and executing
 * the exact functions from static/script.js under stress conditions.
 */

const fs = require('fs');
const path = require('path');
const assert = require('assert');

// 1. Read static/script.js source
const scriptPath = path.join(__dirname, 'static', 'script.js');
const scriptSource = fs.readFileSync(scriptPath, 'utf8');

// Helper to extract function body from script.js
function extractFunction(name) {
    const regex = new RegExp(`function\\s+${name}\\s*\\([^{]*\\)\\s*\\{`);
    const match = regex.exec(scriptSource);
    if (!match) {
        throw new Error(`Function ${name} not found in static/script.js`);
    }
    const startIndex = match.index;
    let braceCount = 0;
    let foundFirstBrace = false;
    let endIndex = startIndex;

    for (let i = startIndex; i < scriptSource.length; i++) {
        if (scriptSource[i] === '{') {
            braceCount++;
            foundFirstBrace = true;
        } else if (scriptSource[i] === '}') {
            braceCount--;
            if (foundFirstBrace && braceCount === 0) {
                endIndex = i + 1;
                break;
            }
        }
    }
    return scriptSource.substring(startIndex, endIndex);
}

// 2. Mock DOM Environment
class MockElement {
    constructor(id, tagName = 'div', classes = []) {
        this.id = id;
        this.tagName = tagName.toUpperCase();
        this.classList = {
            _classes: new Set(classes),
            add: (...cls) => cls.forEach(c => this.classList._classes.add(c)),
            remove: (...cls) => cls.forEach(c => this.classList._classes.delete(c)),
            toggle: (cls, force) => {
                if (force === true) this.classList._classes.add(cls);
                else if (force === false) this.classList._classes.delete(cls);
                else if (this.classList._classes.has(cls)) this.classList._classes.delete(cls);
                else this.classList._classes.add(cls);
            },
            contains: (cls) => this.classList._classes.has(cls)
        };
        this.style = {};
        this.attributes = {};
        this.value = '';
        this.innerHTML = '';
        this.textContent = '';
        this.children = [];
        this.listeners = {};
    }

    setAttribute(name, val) {
        this.attributes[name] = String(val);
    }

    getAttribute(name) {
        return this.attributes[name] || null;
    }

    addEventListener(event, cb) {
        if (!this.listeners[event]) this.listeners[event] = [];
        this.listeners[event].push(cb);
    }

    dispatchEvent(event) {
        const type = typeof event === 'string' ? event : event.type;
        if (this.listeners[type]) {
            this.listeners[type].forEach(cb => cb(event));
        }
    }

    appendChild(child) {
        this.children.push(child);
    }

    removeChild(child) {
        this.children = this.children.filter(c => c !== child);
    }

    click() {
        this.clicked = true;
    }
}

class MockLocalStorage {
    constructor() {
        this.store = {};
    }
    getItem(key) {
        return this.store.hasOwnProperty(key) ? this.store[key] : null;
    }
    setItem(key, value) {
        this.store[key] = String(value);
    }
    removeItem(key) {
        delete this.store[key];
    }
    clear() {
        this.store = {};
    }
}

// Set up Global Context for Testing
function createTestContext() {
    const elements = new Map();
    const registerEl = (el) => { elements.set(el.id, el); return el; };

    // F14 Elements
    registerEl(new MockElement('firstTimeOnboardingBanner', 'div'));
    registerEl(new MockElement('firstTimeInputTooltip', 'div'));
    registerEl(new MockElement('youtubeUrl', 'input'));
    registerEl(new MockElement('clearHeroInputBtn', 'button'));
    registerEl(new MockElement('analyzeSubmitBtn', 'button'));

    // F15 Elements
    registerEl(new MockElement('dashboardDensityToolbar', 'div'));
    registerEl(new MockElement('btnViewCore', 'button', ['active']));
    registerEl(new MockElement('btnViewAdvanced', 'button'));
    registerEl(new MockElement('densityModeNotice', 'div'));
    registerEl(new MockElement('advancedToolsToggleCard', 'div'));
    registerEl(new MockElement('advancedToolsDrawerContent', 'div'));
    registerEl(new MockElement('advancedToggleBtnText', 'span'));
    registerEl(new MockElement('advancedToggleArrow', 'span'));

    // Secondary Analytical Tools
    const secondaryToolIds = [
        'section-videomap', 'section-multitrack', 'section-scorecard',
        'section-entities', 'section-visualmoments', 'section-speakers',
        'section-quotes', 'section-repetitions', 'section-contradictions',
        'section-claims', 'section-copilot', 'section-compare',
        'section-exports', 'section-notes', 'section-clips',
        'section-twitter', 'section-linkedin', 'section-newsletter'
    ];
    secondaryToolIds.forEach(id => {
        registerEl(new MockElement(id, 'div', ['advanced-analytical-tool', 'collapsed']));
    });

    // Subtool Navigation Buttons and Panels
    const subtools = ['graph', 'speakers', 'contradictions', 'copilot', 'exports'];
    subtools.forEach(sub => {
        const btn = new MockElement(`subnav-btn-${sub}`, 'button', sub === 'graph' ? ['active'] : []);
        btn.setAttribute('data-subtool', sub);
        btn.classList.add('advanced-subnav-btn');
        elements.set(btn.id, btn);

        const panel = new MockElement(`subtool-panel-${sub}`, 'div', sub === 'graph' ? ['active'] : []);
        panel.classList.add('advanced-subtool-panel');
        elements.set(panel.id, panel);
    });

    const localStorage = new MockLocalStorage();
    let toastLog = [];
    let blobsCreated = [];
    let startedAnalyses = [];

    const mockDocument = {
        body: new MockElement('body', 'body'),
        getElementById: (id) => elements.get(id) || null,
        createElement: (tag) => new MockElement(`dyn-${Math.random()}`, tag),
        querySelectorAll: (selector) => {
            if (selector === '.advanced-analytical-tool') {
                return secondaryToolIds.map(id => elements.get(id));
            }
            if (selector === '.advanced-subnav-btn') {
                return subtools.map(sub => elements.get(`subnav-btn-${sub}`));
            }
            if (selector === '.advanced-subtool-panel') {
                return subtools.map(sub => elements.get(`subtool-panel-${sub}`));
            }
            return [];
        }
    };

    const mockWindow = {
        dispatchEvent: (ev) => {},
        URL: {
            createObjectURL: (blob) => {
                blobsCreated.push(blob);
                return `blob:mock-${blobsCreated.length}`;
            },
            revokeObjectURL: (url) => {}
        }
    };

    const showToast = (msg, type) => {
        toastLog.push({ msg, type });
    };

    const formatSeconds = (sec) => {
        const m = Math.floor(sec / 60);
        const s = Math.floor(sec % 60);
        return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
    };

    const startAnalysis = (url) => {
        startedAnalyses.push(url);
    };

    return {
        elements,
        localStorage,
        toastLog,
        blobsCreated,
        startedAnalyses,
        mockDocument,
        mockWindow,
        showToast,
        formatSeconds,
        startAnalysis
    };
}

// Compile sandbox environment
function compileSandbox(ctx) {
    global.document = ctx.mockDocument;
    global.window = ctx.mockWindow;
    global.localStorage = ctx.localStorage;
    global.showToast = ctx.showToast;
    global.formatSeconds = ctx.formatSeconds;
    global.startAnalysis = ctx.startAnalysis;
    global.Event = class Event { constructor(type) { this.type = type; } };
    global.Blob = class Blob {
        constructor(parts, opts) {
            this.content = parts.join('');
            this.type = opts ? opts.type : '';
        }
    };
    global.currentAnalysis = null;
    global.FIRST_VISIT_KEY = 'lensyou_first_visit';
    global.VIEW_MODE_KEY = 'lensyou_view_mode';
    global.currentDashboardViewMode = 'core';
    global.isAdvancedToolsExpanded = false;
    global.currentAdvancedSubtool = 'graph';
    global.setTimeout = (fn, delay) => { fn(); }; // synchronous execution for testing

    const codeToEval = `
        ${extractFunction('initFirstTimeExperience')}
        ${extractFunction('dismissFirstTimeGuide')}
        ${extractFunction('hideFirstTimeTooltip')}
        ${extractFunction('setDashboardViewMode')}
        ${extractFunction('toggleAdvancedTool')}
        ${extractFunction('toggleAdvancedResearchTools')}
        ${extractFunction('ensureAdvancedToolsExpanded')}
        ${extractFunction('switchAdvancedSubtool')}
        ${extractFunction('pasteQuickUrl')}
        ${extractFunction('exportMarkdownDossier')}
        ${extractFunction('exportTranscriptCSV')}

        global.initFirstTimeExperience = initFirstTimeExperience;
        global.dismissFirstTimeGuide = dismissFirstTimeGuide;
        global.hideFirstTimeTooltip = hideFirstTimeTooltip;
        global.setDashboardViewMode = setDashboardViewMode;
        global.toggleAdvancedTool = toggleAdvancedTool;
        global.toggleAdvancedResearchTools = toggleAdvancedResearchTools;
        global.ensureAdvancedToolsExpanded = ensureAdvancedToolsExpanded;
        global.switchAdvancedSubtool = switchAdvancedSubtool;
        global.pasteQuickUrl = pasteQuickUrl;
        global.exportMarkdownDossier = exportMarkdownDossier;
        global.exportTranscriptCSV = exportTranscriptCSV;
        global.getCurrentDashboardViewMode = () => currentDashboardViewMode;
        global.setCurrentAnalysis = (val) => { currentAnalysis = val; };
    `;

    eval(codeToEval);
    return global;
}

// ============================================================================
// TEST SUITE EXECUTION
// ============================================================================

console.log('--- STARTING M4 EMPIRICAL JAVASCRIPT STRESS TESTS ---');

let passedTests = 0;
let totalTests = 0;

function runTest(name, testFn) {
    totalTests++;
    try {
        testFn();
        console.log(`  [PASS] ${name}`);
        passedTests++;
    } catch (err) {
        console.error(`  [FAIL] ${name}`);
        console.error(err);
        process.exitCode = 1;
    }
}

// TEST GROUP 1: F14 First-Visit vs Returning Visit
runTest('F14: First visit with null localStorage reveals banner & tooltip in core mode', () => {
    const ctx = createTestContext();
    const sb = compileSandbox(ctx);

    sb.initFirstTimeExperience();

    const banner = ctx.elements.get('firstTimeOnboardingBanner');
    const tooltip = ctx.elements.get('firstTimeInputTooltip');

    assert.strictEqual(banner.style.display, 'block', 'Banner should be displayed block for new users');
    assert.strictEqual(tooltip.style.display, 'flex', 'Tooltip should be displayed flex for new users');
    assert.strictEqual(sb.getCurrentDashboardViewMode(), 'core', 'Default mode should be core');
});

runTest('F14: Returning visit with dismissed key hides banner & tooltip', () => {
    const ctx = createTestContext();
    ctx.localStorage.setItem('lensyou_first_visit', 'dismissed');
    const sb = compileSandbox(ctx);

    sb.initFirstTimeExperience();

    const banner = ctx.elements.get('firstTimeOnboardingBanner');
    const tooltip = ctx.elements.get('firstTimeInputTooltip');

    assert.strictEqual(banner.style.display, 'none');
    assert.strictEqual(tooltip.style.display, 'none');
});

runTest('F14: Malformed localStorage values handle gracefully without crashing', () => {
    const malformedValues = ['', 'false', '0', 'true', 'null', 'undefined', '{"visited":1}', 'x'.repeat(5000)];
    for (const val of malformedValues) {
        const ctx = createTestContext();
        ctx.localStorage.setItem('lensyou_first_visit', val);
        const sb = compileSandbox(ctx);

        sb.initFirstTimeExperience();

        const banner = ctx.elements.get('firstTimeOnboardingBanner');
        const tooltip = ctx.elements.get('firstTimeInputTooltip');
        assert.strictEqual(banner.style.display, 'none', `Banner should be hidden for value: ${val}`);
        assert.strictEqual(tooltip.style.display, 'none', `Tooltip should be hidden for value: ${val}`);
    }
});

runTest('F14: Dismissing guide sets localStorage and hides elements', () => {
    const ctx = createTestContext();
    const sb = compileSandbox(ctx);

    sb.initFirstTimeExperience();
    sb.dismissFirstTimeGuide();

    assert.strictEqual(ctx.localStorage.getItem('lensyou_first_visit'), 'dismissed');
    const banner = ctx.elements.get('firstTimeOnboardingBanner');
    const tooltip = ctx.elements.get('firstTimeInputTooltip');
    assert.strictEqual(banner.style.display, 'none');
    assert.strictEqual(tooltip.style.display, 'none');
});

runTest('F14: Saved view mode restored on returning visit', () => {
    const ctx = createTestContext();
    ctx.localStorage.setItem('lensyou_first_visit', 'dismissed');
    ctx.localStorage.setItem('lensyou_view_mode', 'advanced');
    const sb = compileSandbox(ctx);

    sb.initFirstTimeExperience();
    assert.strictEqual(sb.getCurrentDashboardViewMode(), 'advanced');
});

// TEST GROUP 2: F14 1-Click Quick-Start Pills
runTest('F14: pasteQuickUrl populates input and triggers startAnalysis', () => {
    const ctx = createTestContext();
    const sb = compileSandbox(ctx);

    const testUrl = 'https://www.youtube.com/watch?v=qmNCJxvs080';
    sb.pasteQuickUrl(testUrl);

    const input = ctx.elements.get('youtubeUrl');
    assert.strictEqual(input.value, testUrl);
    assert.strictEqual(ctx.startedAnalyses.length, 1);
    assert.strictEqual(ctx.startedAnalyses[0], testUrl);
});

runTest('F14: pasteQuickUrl handles edge cases (empty, whitespace, missing input)', () => {
    const ctx = createTestContext();
    const sb = compileSandbox(ctx);

    // Whitespace URL
    sb.pasteQuickUrl('   https://youtu.be/LqY6hFLMEJw   ');
    assert.strictEqual(ctx.startedAnalyses.length, 1);

    // Missing input element does not throw error
    ctx.elements.delete('youtubeUrl');
    assert.doesNotThrow(() => {
        sb.pasteQuickUrl('https://www.youtube.com/watch?v=aircAruvnKk');
    });
});

// TEST GROUP 3: F15 View Segregation & Density Toolbar
runTest('F15: setDashboardViewMode core collapses all secondary tools and sets executive notice', () => {
    const ctx = createTestContext();
    const sb = compileSandbox(ctx);

    sb.setDashboardViewMode('core');

    assert.strictEqual(ctx.localStorage.getItem('lensyou_view_mode'), 'core');
    const btnCore = ctx.elements.get('btnViewCore');
    const btnAdv = ctx.elements.get('btnViewAdvanced');
    assert.strictEqual(btnCore.classList.contains('active'), true);
    assert.strictEqual(btnAdv.classList.contains('active'), false);

    // Check secondary analytical tools
    const toolIds = [
        'section-videomap', 'section-multitrack', 'section-scorecard',
        'section-speakers', 'section-contradictions', 'section-copilot',
        'section-compare', 'section-exports'
    ];
    toolIds.forEach(id => {
        const el = ctx.elements.get(id);
        assert.strictEqual(el.classList.contains('collapsed'), true, `${id} must be collapsed in core mode`);
    });

    // Check drawer display
    const drawer = ctx.elements.get('advancedToolsDrawerContent');
    assert.strictEqual(drawer.style.display, 'none');
});

runTest('F15: setDashboardViewMode advanced expands all secondary tools and sets full research notice', () => {
    const ctx = createTestContext();
    const sb = compileSandbox(ctx);

    sb.setDashboardViewMode('advanced');

    assert.strictEqual(ctx.localStorage.getItem('lensyou_view_mode'), 'advanced');
    const btnCore = ctx.elements.get('btnViewCore');
    const btnAdv = ctx.elements.get('btnViewAdvanced');
    assert.strictEqual(btnCore.classList.contains('active'), false);
    assert.strictEqual(btnAdv.classList.contains('active'), true);

    // Check secondary analytical tools are expanded
    const toolIds = [
        'section-videomap', 'section-multitrack', 'section-scorecard',
        'section-speakers', 'section-contradictions', 'section-copilot',
        'section-compare', 'section-exports'
    ];
    toolIds.forEach(id => {
        const el = ctx.elements.get(id);
        assert.strictEqual(el.classList.contains('collapsed'), false, `${id} must NOT be collapsed in advanced mode`);
    });

    // Check drawer display
    const drawer = ctx.elements.get('advancedToolsDrawerContent');
    assert.strictEqual(drawer.style.display, 'block');
});

runTest('F15: ensureAdvancedToolsExpanded expands drawer and routes to correct subtool tab', () => {
    const ctx = createTestContext();
    const sb = compileSandbox(ctx);

    // Start in collapsed state
    sb.setDashboardViewMode('core');

    // 1. Videomap -> graph
    sb.ensureAdvancedToolsExpanded('section-videomap');
    assert.strictEqual(ctx.elements.get('advancedToolsDrawerContent').style.display, 'block');
    assert.strictEqual(ctx.elements.get('subtool-panel-graph').classList.contains('active'), true);

    // 2. Speakers -> speakers
    sb.ensureAdvancedToolsExpanded('speakersGrid');
    assert.strictEqual(ctx.elements.get('subtool-panel-speakers').classList.contains('active'), true);

    // 3. Contradictions -> contradictions
    sb.ensureAdvancedToolsExpanded('contradictionsList');
    assert.strictEqual(ctx.elements.get('subtool-panel-contradictions').classList.contains('active'), true);

    // 4. Copilot & Compare -> copilot
    sb.ensureAdvancedToolsExpanded('copilotMessages');
    assert.strictEqual(ctx.elements.get('subtool-panel-copilot').classList.contains('active'), true);

    sb.ensureAdvancedToolsExpanded('compareMatrixTable');
    assert.strictEqual(ctx.elements.get('subtool-panel-copilot').classList.contains('active'), true);

    // 5. Exports -> exports
    sb.ensureAdvancedToolsExpanded('section-exports');
    assert.strictEqual(ctx.elements.get('subtool-panel-exports').classList.contains('active'), true);
});

// TEST GROUP 4: Client-side Markdown and CSV Exports Robustness
runTest('F15: exportMarkdownDossier handles null/empty currentAnalysis gracefully', () => {
    const ctx = createTestContext();
    const sb = compileSandbox(ctx);

    // Null
    sb.setCurrentAnalysis(null);
    sb.exportMarkdownDossier();
    assert.strictEqual(ctx.toastLog.length, 1);
    assert.strictEqual(ctx.toastLog[0].type, 'warning');

    // Empty object
    sb.setCurrentAnalysis({});
    sb.exportMarkdownDossier();
    assert.strictEqual(ctx.blobsCreated.length, 1);
    const md = ctx.blobsCreated[0].content;
    assert.ok(md.includes('Video Intelligence Dossier'));
    assert.ok(md.includes('Unknown Creator'));
});

runTest('F15: exportMarkdownDossier handles diverse polymorphic analysis payloads without crashing', () => {
    const ctx = createTestContext();
    const sb = compileSandbox(ctx);

    const fullPayload = {
        _meta: {
            video_id: 'qmNCJxvs080',
            title: 'Essence of Linear Algebra: Vectors & Matrices (3B1B)',
            author: '3Blue1Brown',
            duration: '14:22'
        },
        video_overview: {
            summary: 'A geometric overview of vector spaces and linear transformations.'
        },
        key_takeaways: [
            'Vectors are arrows rooted at origin.',
            { point: 'Matrix multiplication represents transformation composition.' },
            { takeaway: 'Determinant gives the scaling factor of area.' }
        ],
        chapters: [
            { start_time: '00:00', title: 'Introduction', summary: 'Foundations' },
            { start_seconds: 245, title: 'Transformations', summary: 'Linear maps' }
        ],
        learning: {
            flashcards: [
                { front: 'What is span?', back: 'Set of all linear combinations.' },
                { question: 'What is basis?', answer: 'Linearly independent spanning set.' }
            ]
        }
    };

    sb.setCurrentAnalysis(fullPayload);
    sb.exportMarkdownDossier();

    assert.strictEqual(ctx.blobsCreated.length, 1);
    const md = ctx.blobsCreated[0].content;
    assert.ok(md.includes('Essence of Linear Algebra'));
    assert.ok(md.includes('3Blue1Brown'));
    assert.ok(md.includes('## Executive Summary'));
    assert.ok(md.includes('## Key Strategic Takeaways'));
    assert.ok(md.includes('1. Vectors are arrows rooted at origin.'));
    assert.ok(md.includes('2. Matrix multiplication represents transformation composition.'));
    assert.ok(md.includes('3. Determinant gives the scaling factor of area.'));
    assert.ok(md.includes('## Smart Chapters & Timeline'));
    assert.ok(md.includes('- **00:00** — Introduction'));
    assert.ok(md.includes('- **04:05** — Transformations'));
    assert.ok(md.includes('## Study Flashcards'));
    assert.ok(md.includes('### Card 1: What is span?'));
    assert.ok(md.includes('Set of all linear combinations.'));
    assert.ok(md.includes('### Card 2: What is basis?'));
    assert.ok(md.includes('Linearly independent spanning set.'));
});

runTest('F15: exportTranscriptCSV handles null/empty analysis and missing fields gracefully', () => {
    const ctx = createTestContext();
    const sb = compileSandbox(ctx);

    // Null analysis
    sb.setCurrentAnalysis(null);
    sb.exportTranscriptCSV();
    assert.strictEqual(ctx.toastLog.length, 1);
    assert.strictEqual(ctx.toastLog[0].type, 'warning');

    // Empty analysis (no transcript in memory)
    sb.setCurrentAnalysis({});
    sb.exportTranscriptCSV();
    assert.strictEqual(ctx.blobsCreated.length, 1);
    const csvFallback = ctx.blobsCreated[0].content;
    assert.ok(csvFallback.includes('Timestamp,Seconds,Text'));
    assert.ok(csvFallback.includes('"00:00",0,"Full transcript not available in memory."'));
});

runTest('F15: exportTranscriptCSV correctly escapes double quotes, commas, and handles polymorphic segments', () => {
    const ctx = createTestContext();
    const sb = compileSandbox(ctx);

    const payload = {
        _meta: { title: 'Complex "Quoted" Lecture, Part 1' },
        _transcript_sample: [
            { timestamp: '00:10', seconds: 10, text: 'Hello, he said "welcome to the class".' },
            { start: 35.5, text: 'Linear transformations preserve "grid lines", keeping them parallel.' },
            { start: 70, event: 'Laughter and applause from audience.' }
        ]
    };

    sb.setCurrentAnalysis(payload);
    sb.exportTranscriptCSV();

    assert.strictEqual(ctx.blobsCreated.length, 1);
    const csv = ctx.blobsCreated[0].content;
    assert.ok(csv.includes('Timestamp,Seconds,Text'));
    // Double quotes properly escaped as ""
    assert.ok(csv.includes('"00:10",10,"Hello, he said ""welcome to the class""."'));
    assert.ok(csv.includes('"00:35",35,"Linear transformations preserve ""grid lines"", keeping them parallel."'));
    assert.ok(csv.includes('"01:10",70,"Laughter and applause from audience."'));
});

// TEST GROUP 5: Adversarial Stress & Chaos Scenarios
runTest('F15: 100 rapid toggles between core and advanced modes preserve consistent DOM and localStorage', () => {
    const ctx = createTestContext();
    const sb = compileSandbox(ctx);

    for (let i = 0; i < 100; i++) {
        const mode = i % 2 === 0 ? 'core' : 'advanced';
        sb.setDashboardViewMode(mode);
    }

    // Final mode was 99 % 2 !== 0 -> advanced
    assert.strictEqual(ctx.localStorage.getItem('lensyou_view_mode'), 'advanced');
    const drawer = ctx.elements.get('advancedToolsDrawerContent');
    assert.strictEqual(drawer.style.display, 'block');

    // One more toggle to core
    sb.setDashboardViewMode('core');
    assert.strictEqual(ctx.localStorage.getItem('lensyou_view_mode'), 'core');
    assert.strictEqual(drawer.style.display, 'none');
});

runTest('F15: ensureAdvancedToolsExpanded handles non-existent or null element IDs safely', () => {
    const ctx = createTestContext();
    const sb = compileSandbox(ctx);

    assert.doesNotThrow(() => {
        sb.ensureAdvancedToolsExpanded(null);
        sb.ensureAdvancedToolsExpanded(undefined);
        sb.ensureAdvancedToolsExpanded('nonExistentElement_999');
        sb.ensureAdvancedToolsExpanded('');
    });
    // Drawer should still expand safely
    assert.strictEqual(ctx.elements.get('advancedToolsDrawerContent').style.display, 'block');
});

runTest('F15: exportMarkdownDossier handles extreme Unicode, emojis, and math symbols without corruption', () => {
    const ctx = createTestContext();
    const sb = compileSandbox(ctx);

    const unicodePayload = {
        _meta: {
            video_id: 'math_sym_123',
            title: 'λ-Calculus & ∇²∇·E = ρ/ε₀: 🧠 神经网络 / תורת הקבוצות',
            author: 'Prof. Gödel 🎓',
            duration: '01:59:59'
        },
        video_overview: {
            summary: 'Mathematical foundations featuring ∀x ∃y (P(x,y) ∧ ¬Q(y)) with emojis 🚀✨.'
        },
        key_takeaways: [
            'Theorem 1: ∑_{i=1}^n i = n(n+1)/2.',
            { point: 'Lemma 2: ∫_{-∞}^∞ e^{-x²} dx = √π.' }
        ],
        chapters: [
            { start_time: '00:00', title: 'Chapter 1: 基礎概念 (Basics)', summary: 'Intro' }
        ],
        learning: {
            flashcards: [
                { front: 'What is ℵ₀ (Aleph-null)?', back: 'Cardinality of ℕ (the natural numbers).' }
            ]
        }
    };

    sb.setCurrentAnalysis(unicodePayload);
    sb.exportMarkdownDossier();

    assert.strictEqual(ctx.blobsCreated.length, 1);
    const md = ctx.blobsCreated[0].content;
    assert.ok(md.includes('λ-Calculus'));
    assert.ok(md.includes('∇²∇·E'));
    assert.ok(md.includes('Prof. Gödel 🎓'));
    assert.ok(md.includes('∀x ∃y'));
    assert.ok(md.includes('∑_{i=1}^n'));
    assert.ok(md.includes('∫_{-∞}^∞'));
    assert.ok(md.includes('基礎概念'));
    assert.ok(md.includes('ℵ₀ (Aleph-null)'));
});

runTest('F15: exportTranscriptCSV handles chaotic transcripts (tabs, CRLF, NaN, malformed segments)', () => {
    const ctx = createTestContext();
    const sb = compileSandbox(ctx);

    const chaoticPayload = {
        _meta: { title: 'Chaotic "Transcript" Test: 123' },
        _transcript_sample: [
            { timestamp: null, start: 0, text: 'First line with \t tab and \r\n CRLF.' },
            { timestamp: '00:45', seconds: 45, text: 'Quotation "inside" another "quote" with , comma.' },
            { start: 90.75, text: '' }, // empty text
            { timestamp: '02:00', seconds: 120, event: 'Background music playing [Theme 1]' },
            {} // totally empty segment
        ]
    };

    sb.setCurrentAnalysis(chaoticPayload);
    sb.exportTranscriptCSV();

    assert.strictEqual(ctx.blobsCreated.length, 1);
    const csv = ctx.blobsCreated[0].content;
    assert.ok(csv.includes('Timestamp,Seconds,Text'));
    assert.ok(csv.includes('""inside"" another ""quote"" with , comma.'));
    assert.ok(csv.includes('Background music playing [Theme 1]'));
});

runTest('F14: 50 rapid pasteQuickUrl submissions do not corrupt input or cause state failure', () => {
    const ctx = createTestContext();
    const sb = compileSandbox(ctx);

    const urls = [
        'https://www.youtube.com/watch?v=qmNCJxvs080',
        'https://youtu.be/LqY6hFLMEJw',
        'https://www.youtube.com/watch?v=aircAruvnKk'
    ];

    for (let i = 0; i < 50; i++) {
        const u = urls[i % urls.length];
        sb.pasteQuickUrl(u);
        assert.strictEqual(ctx.elements.get('youtubeUrl').value, u);
    }
    assert.strictEqual(ctx.startedAnalyses.length, 50);
});

console.log(`\n=== JAVASCRIPT STRESS TEST RESULTS: ${passedTests}/${totalTests} PASSED ===`);
if (passedTests === totalTests) {
    process.exit(0);
} else {
    process.exit(1);
}

