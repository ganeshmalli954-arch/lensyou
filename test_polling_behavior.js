// test_polling_behavior.js
// Empirical test harness for client polling logic in static/script.js

const assert = require('assert');

// Simulate the exact client polling environment and logic from static/script.js lines 846-906:
function runPollingTest(scenario) {
    return new Promise((resolve, reject) => {
        let pollingInterval = null;
        let isAnalyzing = true;
        let elapsedTimer = 123;
        let currentAnalysis = null;
        let savedHistory = [];
        let dashboardRenderCount = 0;
        let toastMessages = [];
        let pipelineStages = [];
        let pipelineErrors = [];
        let fetchCount = 0;
        let activeIntervalId = null;

        const stopElapsedTimer = () => { elapsedTimer = null; };
        const updatePipelineStageUI = (stage, name, pct) => {
            pipelineStages.push({ stage, name, pct });
        };
        const updateProgressiveModulesUI = (modules) => {};
        const setAnalyzeButtonLoading = (loading) => {};
        const showScreen = (screen) => {};
        const updateUsageCounter = () => {};
        const loadUserState = () => {};
        const saveToHistory = (res) => { savedHistory.push(res); };
        const renderDashboard = (res) => { dashboardRenderCount++; };
        const showToast = (msg, type) => { toastMessages.push({ msg, type }); };
        const showPipelineError = (err) => { pipelineErrors.push(err); };

        // Mock fetch returns sequence of responses from scenario.responses
        const mockFetch = async (url) => {
            fetchCount++;
            const respData = scenario.responses[Math.min(fetchCount - 1, scenario.responses.length - 1)];
            return {
                ok: true,
                json: async () => respData
            };
        };

        const jobId = "test-job-123";

        // Exact code from static/script.js:
        if (pollingInterval) clearInterval(pollingInterval);
        const checkStatus = async () => {
            try {
                const jobRes = await mockFetch('/api/job/' + jobId);
                if (!jobRes.ok) return;
                const jobData = await jobRes.json();

                const progressPct = (jobData.progress !== undefined && jobData.progress !== null)
                    ? jobData.progress
                    : (jobData.stage ? Math.min(100, Math.round((jobData.stage / 9) * 100)) : 0);

                if (jobData.stage) {
                    updatePipelineStageUI(jobData.stage, jobData.stage_name, progressPct);
                }

                if (jobData.modules) {
                    updateProgressiveModulesUI(jobData.modules);
                }

                const isCompleted = (jobData.status === 'completed' || jobData.status === 'partial') && jobData.result;

                if (isCompleted) {
                    if (pollingInterval) clearInterval(pollingInterval);
                    pollingInterval = null;
                    stopElapsedTimer();
                    updatePipelineStageUI(9, jobData.is_partial ? 'Partial Dossier Ready' : 'Dossier ready', 100);

                    setTimeout(() => {
                        currentAnalysis = jobData.result;
                        saveToHistory(jobData.result);
                        renderDashboard(jobData.result);
                        showScreen('dashboard');
                        updateUsageCounter();
                        loadUserState();
                        isAnalyzing = false;
                        setAnalyzeButtonLoading(false);

                        if (jobData.is_partial || jobData.status === 'partial') {
                            showToast('⚠️ Video analysis ready (auxiliary modules partially delivered)', 'info');
                        }
                    }, 50);

                } else if (jobData.status === 'error' || jobData.status === 'failed') {
                    if (pollingInterval) clearInterval(pollingInterval);
                    pollingInterval = null;
                    stopElapsedTimer();
                    isAnalyzing = false;
                    setAnalyzeButtonLoading(false);
                    showPipelineError(jobData.error || 'An error occurred during analysis.');
                }
            } catch (pollErr) {
                console.warn('Poll retry:', pollErr);
            }
        };

        (async () => {
            await checkStatus();
            if (isAnalyzing) {
                pollingInterval = setInterval(checkStatus, 100); // 100ms for fast test execution
            }

            // Let it run for 400ms to observe any timer leaks or repeated polls
            setTimeout(() => {
                const leaked = pollingInterval !== null;
                if (pollingInterval) clearInterval(pollingInterval);
                resolve({
                    fetchCount,
                    dashboardRenderCount,
                    savedHistoryCount: savedHistory.length,
                    toastMessages,
                    pipelineErrors,
                    isAnalyzing,
                    leakedInterval: leaked,
                    pipelineStages
                });
            }, 400);
        })();
    });
}

async function runAll() {
    console.log("=== Scenario 1: Multi-stage poll to COMPLETED ===");
    const res1 = await runPollingTest({
        responses: [
            { status: 'extracting', stage: 1, stage_name: 'Fetching metadata', progress: 10 },
            { status: 'processing', stage: 5, stage_name: 'Generating core intelligence', progress: 60 },
            { status: 'completed', stage: 9, stage_name: 'Preparing dashboard', progress: 100, result: { title: "Done" } }
        ]
    });
    console.log("Result 1:", res1);
    assert.strictEqual(res1.dashboardRenderCount, 1, "Dashboard rendered once");
    assert.strictEqual(res1.leakedInterval, false, "Interval cleanly cleared");
    assert.strictEqual(res1.isAnalyzing, false, "isAnalyzing reset to false");

    console.log("\n=== Scenario 2: Multi-stage poll to PARTIAL failure ===");
    const res2 = await runPollingTest({
        responses: [
            { status: 'extracting', stage: 2, stage_name: 'Resolving transcript', progress: 25 },
            { status: 'processing', stage: 6, stage_name: 'Generating research insights', progress: 70 },
            { status: 'partial', stage: 9, stage_name: 'Completed (Partial)', progress: 100, is_partial: true, result: { title: "Partial Done", _partial: true } }
        ]
    });
    console.log("Result 2:", res2);
    assert.strictEqual(res2.dashboardRenderCount, 1, "Dashboard rendered once");
    assert.strictEqual(res2.leakedInterval, false, "Interval cleanly cleared on partial");
    assert.strictEqual(res2.isAnalyzing, false, "isAnalyzing reset to false on partial");
    assert.strictEqual(res2.toastMessages.length, 1, "Toast shown for partial auxiliary delivery");

    console.log("\n=== Scenario 3: Poll encountering FAILED status ===");
    const res3 = await runPollingTest({
        responses: [
            { status: 'extracting', stage: 2, stage_name: 'Resolving transcript', progress: 25 },
            { status: 'failed', stage: 2, error: 'Could not retrieve transcript' }
        ]
    });
    console.log("Result 3:", res3);
    assert.strictEqual(res3.dashboardRenderCount, 0, "No dashboard rendered on error");
    assert.strictEqual(res3.leakedInterval, false, "Interval cleanly cleared on error");
    assert.strictEqual(res3.isAnalyzing, false, "isAnalyzing reset to false on error");
    assert.strictEqual(res3.pipelineErrors.length, 1, "Pipeline error displayed");

    console.log("\n=== Scenario 4: Immediate COMPLETED on first check (Cached Video) ===");
    const res4 = await runPollingTest({
        responses: [
            { status: 'completed', stage: 9, stage_name: 'Preparing dashboard', progress: 100, result: { title: "Cached Done" } }
        ]
    });
    console.log("Result 4:", res4);

    console.log("\n=== Scenario 5: Immediate PARTIAL on first check ===");
    const res5 = await runPollingTest({
        responses: [
            { status: 'partial', stage: 9, stage_name: 'Completed (Partial)', progress: 100, is_partial: true, result: { title: "Cached Partial" } }
        ]
    });
    console.log("Result 5:", res5);

    console.log("\nAll scenario runs completed.");
}

runAll().catch(console.error);
