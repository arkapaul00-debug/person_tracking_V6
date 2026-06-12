/* ============================================================
   SENTINEL PRO — Post Processing Live View
   ============================================================
   Polls the backend /status/<case_id>/ endpoint for real-time
   progress, logs, and sighting data instead of simulating.
   ============================================================ */

const PostProcLive = {
    _progress: 0,
    _pollInterval: null,
    _logs: [],
    _startTime: null,
    _caseId: null,
    _status: 'PENDING', // PENDING | PROCESSING | DONE | ERROR
    _videoUrl: null,
    _evidenceVideoUrl: null,
    _fps: '0.0',
    _activeTracks: '0',
    _lastScore: null,
    _sightings: [],
    _sightingsFetched: false,

    render() {
        const isActive = this._status === 'PROCESSING' || this._status === 'PENDING';

        return `
            <div class="panel-layout">
                ${UserSidebar.render('post-processing-live')}
                <main class="panel-content">
                    <div class="page-header">
                        <div>
                            <h1 class="page-title">Post Processing Live</h1>
                            <p class="page-subtitle">Real-time video analysis progress and updates</p>
                        </div>
                        <div class="page-actions">
                            ${isActive ? `
                                <span class="badge badge-green" style="padding:6px 12px;">
                                    <i data-lucide="loader" class="animate-spin" style="width:12px;height:12px;margin-right:4px;"></i>
                                    Processing
                                </span>
                                <button class="btn btn-red" onclick="VideoProcessing.stopProcessing()">
                                    <i data-lucide="square"></i> Stop Processing
                                </button>
                            ` : `
                                <button class="btn btn-ghost" onclick="location.hash='#/user/video-processing'">
                                    <i data-lucide="arrow-left"></i> Back to Setup
                                </button>
                                ${this._status === 'DONE' ? `
                                    <button class="btn btn-blue" onclick="location.hash='#/user/evidence-vault'">
                                        <i data-lucide="archive"></i> View Evidence Vault
                                    </button>
                                ` : ''}
                            `}
                        </div>
                    </div>

                    ${isActive ? this._renderActiveView() : (this._status === 'DONE' ? this._renderCompleteView() : this._renderIdleView())}
                </main>
            </div>
        `;
    },

    _renderActiveView() {
        const eta = this._getETA();
        const videoName = VideoProcessing._uploadedVideo ? VideoProcessing._uploadedVideo.name : 'Unknown';

        return `
            <div class="processing-progress-card" style="margin-bottom:var(--sp-4);">
                <div class="progress-header">
                    <div>
                        <div class="progress-percentage" id="progress-value">${this._progress}%</div>
                        <div style="font-size:var(--fs-sm);color:var(--text-secondary);margin-top:4px;">Processing: ${SentinelHelpers.escapeHtml(videoName)}</div>
                    </div>
                    <div style="text-align:right;">
                        <div class="progress-eta" id="progress-eta">ETA: ${eta}</div>
                        <div style="font-size:var(--fs-xs);color:var(--text-tertiary);margin-top:2px;">Mode: ${VideoProcessing._detectionMode}</div>
                    </div>
                </div>
                <div class="progress-bar" style="height:10px;margin:var(--sp-4) 0;">
                    <div class="progress-bar-fill" id="progress-bar-fill" style="width:${this._progress}%"></div>
                </div>
                <div class="progress-stats">
                    <div class="progress-stat">
                        <div class="progress-stat-value" id="live-fps">${this._fps}</div>
                        <div class="progress-stat-label">FPS</div>
                    </div>
                    <div class="progress-stat">
                        <div class="progress-stat-value" id="active-tracks">${this._activeTracks}</div>
                        <div class="progress-stat-label">Active Tracks</div>
                    </div>
                    <div class="progress-stat">
                        <div class="progress-stat-value" id="elapsed-time">0:00</div>
                        <div class="progress-stat-label">Elapsed Time</div>
                    </div>
                    ${this._lastScore ? `
                    <div class="progress-stat">
                        <div class="progress-stat-value" id="last-score">${this._lastScore}</div>
                        <div class="progress-stat-label">Last Score</div>
                    </div>
                    ` : ''}
                </div>
            </div>

            <div class="card">
                <div class="card-header">
                    <h3 class="card-title"><i data-lucide="terminal" style="width:18px;height:18px;display:inline;vertical-align:middle;margin-right:6px;"></i>Live Analysis Log</h3>
                    <span class="badge badge-blue" id="log-count">${this._logs.length} entries</span>
                </div>
                <div class="analysis-log" id="analysis-log">
                    ${this._logs.map(l => `
                        <div class="log-entry ${l.type}">
                            <span class="log-timestamp">[${l.time}]</span>
                            <span class="log-message">${SentinelHelpers.escapeHtml(l.message)}</span>
                        </div>
                    `).join('')}
                    ${this._logs.length === 0 ? `
                        <div class="log-entry info">
                            <span class="log-timestamp">[${SentinelHelpers.formatTime(new Date())}]</span>
                            <span class="log-message">Waiting for backend to begin processing...</span>
                        </div>
                    ` : ''}
                </div>
            </div>
        `;
    },

    _renderCompleteView() {
        const videoName = VideoProcessing._uploadedVideo ? VideoProcessing._uploadedVideo.name : 'Unknown';

        return `
            <div class="processing-progress-card" style="margin-bottom:var(--sp-4);">
                <div class="progress-header">
                    <div>
                        <div class="progress-percentage" style="color:var(--accent-green);">100%</div>
                        <div style="font-size:var(--fs-sm);color:var(--text-secondary);margin-top:4px;">Completed: ${SentinelHelpers.escapeHtml(videoName)}</div>
                    </div>
                    <div style="text-align:right;">
                        <span class="badge badge-green" style="padding:6px 14px;font-size:var(--fs-sm);">
                            <i data-lucide="check-circle" style="width:14px;height:14px;display:inline;vertical-align:middle;margin-right:4px;"></i>
                            Analysis Complete
                        </span>
                    </div>
                </div>
                <div class="progress-bar" style="height:10px;margin:var(--sp-4) 0;">
                    <div class="progress-bar-fill" style="width:100%;background:var(--accent-green);"></div>
                </div>
            </div>

            ${this._videoUrl ? `
            <div class="card" style="margin-bottom:var(--sp-4);">
                <div class="card-header">
                    <h3 class="card-title"><i data-lucide="video" style="width:18px;height:18px;display:inline;vertical-align:middle;margin-right:6px;"></i>Annotated Output Video</h3>
                    <a href="${this._videoUrl}" download class="btn btn-sm btn-blue">
                        <i data-lucide="download" style="width:14px;height:14px;"></i> Download
                    </a>
                </div>
                <div style="padding:var(--sp-4);">
                    <video controls style="width:100%;border-radius:var(--radius-md);background:#000;">
                        <source src="${this._videoUrl}" type="video/mp4">
                        Your browser does not support the video element.
                    </video>
                </div>
            </div>
            ` : ''}

            ${this._sightings.length > 0 ? `
            <div class="card" style="margin-bottom:var(--sp-4);">
                <div class="card-header">
                    <h3 class="card-title"><i data-lucide="user-check" style="width:18px;height:18px;display:inline;vertical-align:middle;margin-right:6px;"></i>Suspect Sightings</h3>
                    <span class="badge badge-red">${this._sightings.length} found</span>
                </div>
                <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:var(--sp-3);padding:var(--sp-4);">
                    ${this._sightings.map((s, i) => `
                        <div class="card" style="padding:var(--sp-3);background:var(--bg-tertiary);">
                            ${s.url ? `
                            <video controls style="width:100%;border-radius:var(--radius-sm);margin-bottom:var(--sp-2);background:#000;">
                                <source src="${s.url}" type="video/mp4">
                            </video>
                            ` : `
                            <div style="aspect-ratio:16/9;background:var(--bg-quaternary);border-radius:var(--radius-sm);display:flex;align-items:center;justify-content:center;margin-bottom:var(--sp-2);">
                                <i data-lucide="video-off" style="width:24px;height:24px;color:var(--text-tertiary);"></i>
                            </div>
                            `}
                            <div style="display:flex;justify-content:space-between;align-items:center;">
                                <div>
                                    <div style="font-size:var(--fs-sm);font-weight:var(--fw-semibold);color:var(--text-primary);">Sighting #${i + 1}</div>
                                    <div style="font-size:var(--fs-xs);color:var(--text-tertiary);">${s.start}s — ${s.end}s</div>
                                </div>
                                <div>
                                    <span class="badge badge-red" style="font-size:var(--fs-xs);">Score: ${s.score}</span>
                                </div>
                            </div>
                        </div>
                    `).join('')}
                </div>
            </div>
            ` : ''}

            <div class="card">
                <div class="card-header">
                    <h3 class="card-title"><i data-lucide="terminal" style="width:18px;height:18px;display:inline;vertical-align:middle;margin-right:6px;"></i>Analysis Log</h3>
                    <span class="badge badge-blue">${this._logs.length} entries</span>
                </div>
                <div class="analysis-log" id="analysis-log" style="max-height:300px;">
                    ${this._logs.map(l => `
                        <div class="log-entry ${l.type}">
                            <span class="log-timestamp">[${l.time}]</span>
                            <span class="log-message">${SentinelHelpers.escapeHtml(l.message)}</span>
                        </div>
                    `).join('')}
                </div>
            </div>
        `;
    },

    _renderIdleView() {
        return `
            <div class="card">
                <div class="empty-state" style="padding:var(--sp-16);">
                    <i data-lucide="activity" style="width:48px;height:48px;"></i>
                    <p class="empty-state-title">No Active Processing</p>
                    <p class="empty-state-text">Upload a video and start processing from the Video Post Processing module to see live analysis here.</p>
                    <button class="btn btn-blue" onclick="location.hash='#/user/video-processing'" style="margin-top:var(--sp-4);">
                        <i data-lucide="film"></i> Go to Video Processing
                    </button>
                </div>
            </div>
        `;
    },

    _getETA() {
        if (this._progress <= 0) return 'Calculating...';
        if (this._progress >= 100) return 'Complete';

        const elapsed = this._startTime ? (Date.now() - this._startTime) / 1000 : 0;
        if (elapsed <= 0) return 'Calculating...';

        const totalEst = (elapsed / this._progress) * 100;
        const remaining = totalEst - elapsed;
        const mins = Math.floor(remaining / 60);
        const secs = Math.floor(remaining % 60);
        return `${mins}m ${secs}s remaining`;
    },

    _addLog(message, type = 'info') {
        this._logs.push({
            time: SentinelHelpers.formatTime(new Date()),
            message,
            type
        });

        const logEl = document.getElementById('analysis-log');
        if (logEl) {
            const entry = document.createElement('div');
            entry.className = `log-entry ${type}`;
            entry.innerHTML = `
                <span class="log-timestamp">[${SentinelHelpers.formatTime(new Date())}]</span>
                <span class="log-message">${SentinelHelpers.escapeHtml(message)}</span>
            `;
            logEl.appendChild(entry);
            logEl.scrollTop = logEl.scrollHeight;
        }

        const countEl = document.getElementById('log-count');
        if (countEl) countEl.textContent = this._logs.length + ' entries';
    },

    /**
     * Begin polling the backend /status/<case_id>/ endpoint
     */
    _startPolling() {
        if (this._pollInterval) clearInterval(this._pollInterval);
        this._startTime = Date.now();
        this._logs = [];
        this._sightings = [];
        this._sightingsFetched = false;
        this._status = 'PENDING';
        this._progress = 0;

        this._addLog('Connected to backend pipeline', 'info');
        this._addLog(`Detection mode: ${VideoProcessing._detectionMode}`, 'info');
        this._addLog(`Threshold: ${VideoProcessing._threshold}%`, 'info');

        let lastLogCount = 0;

        this._pollInterval = setInterval(async () => {
            if (!this._caseId) {
                clearInterval(this._pollInterval);
                return;
            }

            try {
                const data = await SentinelAPI.getCaseStatus(this._caseId);

                // Update status
                this._status = data.status || 'PROCESSING';

                // Update metrics
                this._fps = data.current_fps || '0.0';
                this._activeTracks = data.active_tracks || '0';
                this._lastScore = data.last_score || null;
                this._videoUrl = data.video_url || null;
                this._evidenceVideoUrl = data.evidence_video_url || null;

                // Process new logs from backend
                const serverLogs = data.logs || [];
                if (serverLogs.length > lastLogCount) {
                    const newLogs = serverLogs.slice(lastLogCount);
                    newLogs.forEach(log => {
                        this._addLog(log.message, log.type || 'info');
                    });
                    lastLogCount = serverLogs.length;
                }

                // Update UI elements
                const fpsEl = document.getElementById('live-fps');
                const tracksEl = document.getElementById('active-tracks');
                const scoreEl = document.getElementById('last-score');
                if (fpsEl) fpsEl.textContent = this._fps;
                if (tracksEl) tracksEl.textContent = this._activeTracks;
                if (scoreEl) scoreEl.textContent = this._lastScore || '-';

                // Update elapsed time
                const elapsed = document.getElementById('elapsed-time');
                if (elapsed && this._startTime) {
                    const secs = Math.floor((Date.now() - this._startTime) / 1000);
                    const m = Math.floor(secs / 60);
                    const s = secs % 60;
                    elapsed.textContent = `${m}:${s.toString().padStart(2, '0')}`;
                }

                // Estimate progress from log count (heuristic until backend provides explicit progress)
                if (this._status === 'PROCESSING') {
                    // Use log density as a rough progress indicator
                    this._progress = Math.min(95, Math.round(serverLogs.length * 2.5));
                    const pVal = document.getElementById('progress-value');
                    const pBar = document.getElementById('progress-bar-fill');
                    const pEta = document.getElementById('progress-eta');
                    if (pVal) pVal.textContent = this._progress + '%';
                    if (pBar) pBar.style.width = this._progress + '%';
                    if (pEta) pEta.textContent = 'ETA: ' + this._getETA();
                }

                // Handle completion
                if (this._status === 'DONE') {
                    clearInterval(this._pollInterval);
                    this._pollInterval = null;
                    this._progress = 100;

                    VideoProcessing._isProcessing = false;

                    this._addLog('Video processing completed successfully', 'success');

                    // Fetch sightings
                    if (!this._sightingsFetched) {
                        this._sightingsFetched = true;
                        try {
                            const sightings = await SentinelAPI.getSightings(this._caseId);
                            this._sightings = sightings || [];
                            this._addLog(`Found ${this._sightings.length} suspect sighting(s)`, 'success');
                        } catch (e) {
                            this._addLog('Could not fetch sightings: ' + e.message, 'warning');
                        }
                    }

                    // Add to local evidence vault
                    SentinelStore.addEvidence({
                        type: 'post',
                        cameraName: 'Post Processing',
                        cameraLocation: 'N/A',
                        detectionMode: VideoProcessing._detectionMode,
                        confidence: this._lastScore ? (this._lastScore * 100).toFixed(1) + '%' : 'N/A',
                        duration: document.getElementById('elapsed-time') ? document.getElementById('elapsed-time').textContent : '0:00',
                        title: `Analysis - ${VideoProcessing._uploadedVideo ? VideoProcessing._uploadedVideo.name : 'Unknown'}`,
                        caseId: this._caseId,
                        videoUrl: this._videoUrl,
                        sightingsCount: this._sightings.length
                    });

                    SentinelStore.addActivity({ type: 'system', message: 'Video processing completed', color: 'green' });
                    SentinelToast.success('Processing Complete', `Video analysis finished. Found ${this._sightings.length} sighting(s).`);

                    // Re-render to show complete view with sightings
                    SentinelRouter.navigate(location.hash);
                }

                // Handle error
                if (this._status === 'ERROR') {
                    clearInterval(this._pollInterval);
                    this._pollInterval = null;
                    VideoProcessing._isProcessing = false;

                    this._addLog('Video processing failed on the backend', 'error');
                    SentinelToast.error('Processing Failed', 'The backend encountered an error.');
                    SentinelRouter.navigate(location.hash);
                }

            } catch (error) {
                console.error('Polling error:', error);
                // Don't stop polling on transient errors — backend might still be starting up
            }
        }, 2000);
    },

    init() {
        // Extract case_id from URL query params
        const hashParts = location.hash.split('?');
        if (hashParts.length > 1) {
            const params = new URLSearchParams(hashParts[1]);
            const caseId = params.get('case');
            if (caseId && caseId !== this._caseId) {
                this._caseId = caseId;
                this._startPolling();
            }
        }

        // Resume polling if case is already active
        if (this._caseId && VideoProcessing._isProcessing && !this._pollInterval) {
            this._startPolling();
        }
    }
};
