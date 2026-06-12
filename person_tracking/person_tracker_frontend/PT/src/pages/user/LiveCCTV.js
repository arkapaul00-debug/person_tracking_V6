/* ============================================================
   SENTINEL PRO — Live CCTV Module (v2.0)
   Full rewrite: config page + fullscreen monitoring overlay
   ============================================================ */

const LiveCCTV = {
    // ---- State ----
    _isLive: false,
    _detectionMode: 'hybrid',
    _threshold: 50,
    _targetImages: [],
    _targetName: '',
    _activeStreamId: null,
    _focusedStreamId: null,
    _fullscreenActive: false,
    _alertInterval: null,
    _noiseIntervals: [],
    _clockInterval: null,
    _maxRenderedStreams: 8,
    _savedStreamTab: 'recent',
    _detectedStreamIds: new Set(),

    /* ==========================================================
       RENDER — Main entry (config page)
       ========================================================== */
    render() {
        const streams = SentinelStore.getStreams();
        const settings = SentinelStore.getSettings();
        this._detectionMode = settings.defaultDetectionMode || 'hybrid';
        this._threshold = settings.defaultThreshold || 50;

        return `
            <div class="panel-layout">
                ${UserSidebar.render('live-cctv')}
                <main class="panel-content" style="display:flex;flex-direction:column;">
                    <div class="page-header">
                        <div>
                            <h1 class="page-title">Live CCTV</h1>
                            <p class="page-subtitle">Real-time surveillance and monitoring</p>
                        </div>
                        <div class="page-actions">
                            ${this._isLive ? `
                                <span class="badge badge-green" style="padding:6px 14px;font-size:var(--fs-xs);">
                                    <span class="feed-live-dot" style="margin-right:4px;background:white;"></span> LIVE SESSION ACTIVE
                                </span>
                            ` : ''}
                        </div>
                    </div>

                    <div style="flex:1;overflow-y:auto;display:flex;flex-direction:column;gap:var(--sp-5);padding-bottom:var(--sp-6);">
                        ${this._renderConfig(streams)}
                    </div>
                </main>
            </div>
            ${this._fullscreenActive ? this._renderFullscreenOverlay(streams) : ''}
        `;
    },

    /* ==========================================================
       CONFIG PAGE — All 6 Sections + Saved Library
       ========================================================== */
    _renderConfig(streams) {
        const savedStreams = SentinelStore.getSavedStreams();
        const alerts = SentinelStore.getAlerts().slice(0, 15);

        return `
            <!-- ====== SECTION 1: Add Stream ====== -->
            <div class="config-section">
                <div class="config-section-title">
                    <span class="section-number">1</span>
                    <i data-lucide="plus-circle"></i> Add Stream
                    <span class="badge badge-blue" style="margin-left:auto;">${streams.length} / 3000</span>
                </div>
                <div class="card">
                    <form id="stream-form" onsubmit="LiveCCTV.addStream(event)" style="display:flex;flex-direction:column;gap:var(--sp-3);padding:var(--sp-4);">
                        <div class="form-group">
                            <label class="form-label">Stream URL</label>
                            <input type="text" class="form-input" id="stream-url" placeholder="rtsp://192.168.1.100:554/stream">
                            <div class="form-error" id="stream-url-error"></div>
                        </div>
                        <div class="form-row">
                            <div class="form-group">
                                <label class="form-label">CCTV Camera Name</label>
                                <input type="text" class="form-input" id="stream-name" placeholder="e.g. Main Gate Cam">
                                <div class="form-error" id="stream-name-error"></div>
                            </div>
                            <div class="form-group">
                                <label class="form-label">Location</label>
                                <input type="text" class="form-input" id="stream-location" placeholder="e.g. Building A - Entrance">
                                <div class="form-error" id="stream-location-error"></div>
                            </div>
                        </div>
                        <button type="submit" class="btn btn-blue" style="align-self:flex-start;">
                            <i data-lucide="plus"></i> + Add Stream
                        </button>
                    </form>
                </div>

                ${streams.length > 0 ? `
                <div style="margin-top:var(--sp-4);">
                    <div style="font-size:var(--fs-sm);font-weight:var(--fw-semibold);color:var(--text-secondary);margin-bottom:var(--sp-3);display:flex;align-items:center;gap:var(--sp-2);">
                        <i data-lucide="layout-grid" style="width:16px;height:16px;"></i> Active Streams (${streams.length})
                    </div>
                    <div class="streams-preview-grid">
                        ${streams.map(s => this._renderStreamPreviewCard(s)).join('')}
                    </div>
                </div>
                ` : ''}
            </div>

            <!-- ====== SECTION 2: Target Person ====== -->
            <div class="config-section">
                <div class="config-section-title">
                    <span class="section-number">2</span>
                    <i data-lucide="user-search"></i> Target Person
                </div>
                <div class="card" style="padding:var(--sp-4);">
                    <div class="form-group" style="margin-bottom:var(--sp-3);">
                        <label class="form-label">Target Person Name (Optional)</label>
                        <input type="text" class="form-input" id="target-name" placeholder="Enter suspect / target person name" value="${SentinelHelpers.escapeHtml(this._targetName)}">
                    </div>
                    <div class="file-upload-zone" id="target-upload-zone"
                         onclick="document.getElementById('target-file-input').click()"
                         ondragover="event.preventDefault();this.classList.add('dragover')"
                         ondragleave="this.classList.remove('dragover')"
                         ondrop="LiveCCTV.handleImageDrop(event)">
                        <i data-lucide="upload"></i>
                        <div class="file-upload-text">
                            <span>Click to upload</span> or drag and drop
                        </div>
                        <div style="font-size:var(--fs-xs);color:var(--text-tertiary);">PNG, JPG — up to 10MB each — Multiple images supported</div>
                    </div>
                    <input type="file" id="target-file-input" accept="image/*" multiple style="display:none;" onchange="LiveCCTV.handleImageSelect(event)">
                    <div class="file-preview-grid" id="target-preview-grid">
                        ${this._targetImages.map((img, i) => `
                            <div class="file-preview-item">
                                <img src="${img.data}" alt="${SentinelHelpers.escapeHtml(img.name)}">
                                <button class="file-preview-remove" onclick="LiveCCTV.removeTargetImage(${i})">
                                    <i data-lucide="x" style="width:10px;height:10px;"></i>
                                </button>
                            </div>
                        `).join('')}
                    </div>
                </div>
            </div>

            <!-- ====== SECTION 3: Detection Mode ====== -->
            <div class="config-section">
                <div class="config-section-title">
                    <span class="section-number">3</span>
                    <i data-lucide="scan-face"></i> Detection Mode
                </div>
                <div class="card" style="padding:var(--sp-4);">
                    <div class="detection-modes">
                        <button class="detection-mode-btn ${this._detectionMode === 'face' ? 'active' : ''}" onclick="LiveCCTV.setDetectionMode('face')">
                            <i data-lucide="scan-face" style="width:18px;height:18px;"></i> Face
                        </button>
                        <button class="detection-mode-btn ${this._detectionMode === 'body' ? 'active' : ''}" onclick="LiveCCTV.setDetectionMode('body')">
                            <i data-lucide="person-standing" style="width:18px;height:18px;"></i> Body
                        </button>
                        <button class="detection-mode-btn ${this._detectionMode === 'hybrid' ? 'active' : ''}" onclick="LiveCCTV.setDetectionMode('hybrid')">
                            <i data-lucide="combine" style="width:18px;height:18px;"></i> Hybrid
                        </button>
                    </div>
                </div>
            </div>

            <!-- ====== SECTION 4: Threshold Adjustment ====== -->
            <div class="config-section">
                <div class="config-section-title">
                    <span class="section-number">4</span>
                    <i data-lucide="sliders-horizontal"></i> Threshold Adjustment
                </div>
                <div class="card" style="padding:var(--sp-4);">
                    <div class="threshold-slider-wrapper">
                        <div class="threshold-labels">
                            <span ${this._threshold < 35 ? 'class="active"' : ''}>Sensitive (0.1)</span>
                            <span ${this._threshold >= 35 && this._threshold <= 70 ? 'class="active"' : ''}>Balanced</span>
                            <span ${this._threshold > 70 ? 'class="active"' : ''}>Strict (0.9)</span>
                        </div>
                        <input type="range" class="threshold-slider" min="10" max="90" value="${this._threshold}" oninput="LiveCCTV.setThreshold(this.value)">
                        <div class="threshold-value" id="threshold-display">${this._threshold}%</div>
                    </div>
                    <div style="font-size:var(--fs-xs);color:var(--text-tertiary);margin-top:var(--sp-2);text-align:center;">
                        0.1 → Highly sensitive detection &nbsp;|&nbsp; 0.9 → Highly strict detection
                    </div>
                </div>
            </div>

            <!-- ====== SECTION 5: Start Live Session ====== -->
            <div class="config-section">
                <div class="config-section-title">
                    <span class="section-number">5</span>
                    <i data-lucide="play"></i> Start Live Session
                </div>
                <div class="card" style="padding:var(--sp-5);text-align:center;">
                    <p style="font-size:var(--fs-sm);color:var(--text-secondary);margin-bottom:var(--sp-4);">
                        Launch the fullscreen monitoring window to begin real-time surveillance across all added streams.
                    </p>
                    <button class="btn btn-red btn-lg" id="start-live-btn" onclick="LiveCCTV.startSession()" style="padding:var(--sp-3) var(--sp-8);font-size:var(--fs-md);">
                        <i data-lucide="play"></i> Start Live Session
                    </button>
                </div>
            </div>

            <!-- ====== SECTION 6: Detection Alerts ====== -->
            <div class="config-section">
                <div class="config-section-title">
                    <span class="section-number">6</span>
                    <i data-lucide="alert-triangle" style="color:var(--accent-red);"></i> Detection Alerts
                    <span class="badge badge-red" style="margin-left:auto;">${alerts.length}</span>
                </div>
                ${alerts.length > 0 ? `
                <div class="detection-alerts-list">
                    ${alerts.map(a => this._renderDetectionAlertCard(a)).join('')}
                </div>
                ` : `
                <div class="card">
                    <div class="empty-state" style="padding:var(--sp-6);">
                        <i data-lucide="shield-check"></i>
                        <p class="empty-state-title">No Detections Yet</p>
                        <p class="empty-state-text">Detection alerts will appear here when suspects are identified during live monitoring sessions.</p>
                    </div>
                </div>
                `}
            </div>

            <!-- ====== Saved Stream Library ====== -->
            <div class="config-section">
                <div class="config-section-title">
                    <i data-lucide="bookmark"></i> Saved Stream Library
                    <span class="badge badge-blue" style="margin-left:auto;">${savedStreams.length} saved</span>
                </div>
                <div class="card" style="padding:var(--sp-4);">
                    <div class="saved-library-tabs">
                        <button class="saved-library-tab ${this._savedStreamTab === 'recent' ? 'active' : ''}" onclick="LiveCCTV.setSavedTab('recent')">
                            <i data-lucide="clock" style="width:12px;height:12px;display:inline;vertical-align:middle;margin-right:4px;"></i>Recent
                        </button>
                        <button class="saved-library-tab ${this._savedStreamTab === 'favorites' ? 'active' : ''}" onclick="LiveCCTV.setSavedTab('favorites')">
                            <i data-lucide="star" style="width:12px;height:12px;display:inline;vertical-align:middle;margin-right:4px;"></i>Favorites
                        </button>
                        <button class="saved-library-tab ${this._savedStreamTab === 'all' ? 'active' : ''}" onclick="LiveCCTV.setSavedTab('all')">
                            <i data-lucide="list" style="width:12px;height:12px;display:inline;vertical-align:middle;margin-right:4px;"></i>All
                        </button>
                    </div>
                    ${this._renderSavedStreamList(savedStreams)}
                </div>
            </div>
        `;
    },

    /* ==========================================================
       STREAM PREVIEW CARD (with canvas thumbnail)
       ========================================================== */
    _renderStreamPreviewCard(stream) {
        return `
            <div class="stream-preview-card" id="preview-card-${stream.id}">
                <div class="stream-preview-thumb">
                    <canvas class="feed-noise-canvas" id="noise-${stream.id}" width="320" height="180"></canvas>
                    <div class="stream-preview-overlay">
                        <div>
                            <div class="stream-preview-name">${SentinelHelpers.escapeHtml(stream.name)}</div>
                            <div class="stream-preview-loc">${SentinelHelpers.escapeHtml(stream.location)}</div>
                        </div>
                        <div class="stream-preview-live">
                            <span class="stream-preview-live-dot"></span> READY
                        </div>
                    </div>
                </div>
                <div class="stream-preview-body">
                    <div class="stream-preview-info">
                        <div class="stream-preview-info-name">${SentinelHelpers.escapeHtml(stream.name)}</div>
                        <div class="stream-preview-info-loc">${SentinelHelpers.escapeHtml(stream.location)}</div>
                    </div>
                    <button class="btn btn-icon-sm btn-ghost" onclick="LiveCCTV.removeStream('${stream.id}')" title="Remove" style="color:var(--accent-red);">
                        <i data-lucide="trash-2" style="width:14px;height:14px;"></i>
                    </button>
                </div>
            </div>
        `;
    },

    /* ==========================================================
       DETECTION ALERT CARD (Section 6)
       ========================================================== */
    _renderDetectionAlertCard(alert) {
        return `
            <div class="detection-alert-card">
                <div class="detection-alert-snapshot">
                    <i data-lucide="user" style="width:24px;height:24px;color:var(--text-tertiary);"></i>
                    <div class="alert-detection-box" style="top:15%;left:25%;width:50%;height:60%;"></div>
                </div>
                <div class="detection-alert-body">
                    <div class="detection-alert-header">
                        <div class="detection-alert-cam">
                            <i data-lucide="video" style="width:12px;height:12px;display:inline;vertical-align:middle;margin-right:4px;"></i>
                            ${SentinelHelpers.escapeHtml(alert.camera || 'Unknown Camera')}
                        </div>
                        <div class="detection-alert-time">${SentinelHelpers.formatTime(alert.timestamp)}</div>
                    </div>
                    <div class="detection-alert-loc">
                        <i data-lucide="map-pin"></i>
                        ${SentinelHelpers.escapeHtml(alert.location || 'Unknown Location')}
                    </div>
                    <div class="detection-alert-summary">
                        ${SentinelHelpers.escapeHtml(alert.message || 'Potential suspect detected in frame.')}
                    </div>
                </div>
            </div>
        `;
    },

    /* ==========================================================
       SAVED STREAM LIBRARY
       ========================================================== */
    _renderSavedStreamList(allSaved) {
        let displayStreams = [];
        if (this._savedStreamTab === 'recent') {
            displayStreams = SentinelStore.getRecentStreams(10);
        } else if (this._savedStreamTab === 'favorites') {
            displayStreams = SentinelStore.getFavoriteStreams();
        } else {
            displayStreams = allSaved;
        }

        if (displayStreams.length === 0) {
            const emptyMsg = this._savedStreamTab === 'favorites'
                ? 'No favorite streams yet. Click the star icon to mark favorites.'
                : this._savedStreamTab === 'recent'
                ? 'No recent streams. Added streams are automatically saved here.'
                : 'No saved streams yet.';
            return `
                <div class="empty-state" style="padding:var(--sp-4);">
                    <i data-lucide="bookmark" style="width:20px;height:20px;"></i>
                    <p class="empty-state-text" style="margin-top:var(--sp-2);">${emptyMsg}</p>
                </div>
            `;
        }

        return `
            <div class="saved-streams-list" style="max-height:240px;">
                ${displayStreams.map(s => `
                    <div class="saved-stream-entry" onclick="LiveCCTV.loadSavedStream('${s.id}')">
                        <button class="saved-stream-favorite ${s.favorite ? 'active' : ''}" onclick="event.stopPropagation();LiveCCTV.toggleFavorite('${s.id}')" title="${s.favorite ? 'Remove from favorites' : 'Add to favorites'}">
                            <i data-lucide="${s.favorite ? 'star' : 'star'}" style="width:14px;height:14px;${s.favorite ? 'fill:currentColor;' : ''}"></i>
                        </button>
                        <i data-lucide="video" style="width:14px;height:14px;color:var(--text-tertiary);flex-shrink:0;"></i>
                        <div style="flex:1;min-width:0;">
                            <div class="saved-stream-name">${SentinelHelpers.escapeHtml(s.name || 'Unnamed')}</div>
                            <div class="saved-stream-url">${SentinelHelpers.escapeHtml(s.url)}</div>
                        </div>
                        <button class="btn btn-icon-sm btn-ghost" onclick="event.stopPropagation();LiveCCTV.deleteSavedStream('${s.id}')" style="color:var(--accent-red);">
                            <i data-lucide="x" style="width:12px;height:12px;"></i>
                        </button>
                    </div>
                `).join('')}
            </div>
        `;
    },

    /* ==========================================================
       FULLSCREEN MONITORING OVERLAY
       ========================================================== */
    _renderFullscreenOverlay(streams) {
        if (streams.length === 0) return '';

        const mainStream = this._focusedStreamId
            ? streams.find(s => s.id === this._focusedStreamId) || streams[0]
            : (this._activeStreamId ? streams.find(s => s.id === this._activeStreamId) || streams[0] : streams[0]);
        const otherStreams = streams.filter(s => s.id !== mainStream.id);
        const renderedOthers = otherStreams.slice(0, this._maxRenderedStreams - 1);
        const now = new Date();
        const timeStr = now.toLocaleTimeString();
        const dateStr = now.toLocaleDateString();

        return `
            <div class="fs-overlay" id="fs-overlay">
                <!-- Left Sidebar Navigation -->
                <div class="fs-sidebar">
                    <div class="fs-sidebar-header">
                        <div class="fs-sidebar-title">
                            <i data-lucide="monitor" style="width:18px;height:18px;"></i> Streams
                        </div>
                        <span class="fs-sidebar-count">${streams.length}</span>
                    </div>
                    <div class="fs-sidebar-list">
                        ${streams.map(s => `
                            <div class="fs-sidebar-stream ${s.id === mainStream.id ? 'active' : ''} ${this._detectedStreamIds.has(s.id) ? 'detected' : ''}"
                                 onclick="LiveCCTV.switchStream('${s.id}')" id="fs-sidebar-${s.id}">
                                <div class="fs-stream-status ${this._detectedStreamIds.has(s.id) ? 'detected' : 'online'}"></div>
                                <div class="fs-stream-info">
                                    <div class="fs-stream-name">${SentinelHelpers.escapeHtml(s.name)}</div>
                                    <div class="fs-stream-location">${SentinelHelpers.escapeHtml(s.location)}</div>
                                </div>
                            </div>
                        `).join('')}
                    </div>
                </div>

                <!-- Main Content Area -->
                <div class="fs-main-area">
                    <!-- Top Bar -->
                    <div class="fs-topbar">
                        <div class="fs-topbar-info">
                            <div>
                                <div class="fs-topbar-cam-name" id="fs-cam-name">${SentinelHelpers.escapeHtml(mainStream.name)}</div>
                                <div class="fs-topbar-cam-loc" id="fs-cam-loc">${SentinelHelpers.escapeHtml(mainStream.location)}</div>
                            </div>
                        </div>
                        <div style="display:flex;align-items:center;gap:var(--sp-3);">
                            <span style="font-size:var(--fs-sm);color:var(--text-tertiary);" id="fs-clock">${timeStr} — ${dateStr}</span>
                            <div class="fs-topbar-live">
                                <span class="fs-topbar-live-dot"></span> LIVE
                            </div>
                        </div>
                    </div>

                    <!-- Primary Feed -->
                    <div class="fs-main-feed ${this._detectedStreamIds.has(mainStream.id) ? 'suspect-detected' : ''}" id="fs-main-feed">
                        <canvas class="fs-feed-canvas feed-noise-canvas" id="fs-main-canvas" width="1280" height="720"></canvas>
                        <div class="feed-placeholder-content">
                            <i data-lucide="video"></i>
                            <div class="feed-cam-label">${SentinelHelpers.escapeHtml(mainStream.name)}</div>
                            <div class="feed-status-text">Live feed connected</div>
                        </div>
                        ${this._detectedStreamIds.has(mainStream.id) ? `
                            <div class="fs-detection-box" style="top:25%;left:35%;width:30%;height:50%;"></div>
                        ` : ''}
                        <div class="fs-feed-overlay">
                            <div class="fs-feed-overlay-info">
                                <div class="fs-feed-cam-name">${SentinelHelpers.escapeHtml(mainStream.name)}</div>
                                <div class="fs-feed-cam-loc">${SentinelHelpers.escapeHtml(mainStream.location)}</div>
                                <div class="fs-feed-timestamp" id="fs-feed-time">${timeStr}</div>
                            </div>
                            <div class="feed-live-badge">
                                <span class="feed-live-dot"></span> LIVE
                            </div>
                        </div>
                    </div>

                    <!-- Secondary Stream Grid -->
                    ${renderedOthers.length > 0 ? `
                    <div class="fs-stream-grid" id="fs-stream-grid">
                        ${renderedOthers.map(s => `
                            <div class="fs-stream-cell ${this._detectedStreamIds.has(s.id) ? 'detected' : ''}"
                                 onclick="LiveCCTV.switchStream('${s.id}')" id="fs-cell-${s.id}">
                                <canvas class="fs-feed-canvas feed-noise-canvas" id="fs-canvas-${s.id}" width="320" height="180"></canvas>
                                <div class="feed-placeholder-content" style="transform:scale(0.6);">
                                    <i data-lucide="video"></i>
                                </div>
                                ${this._detectedStreamIds.has(s.id) ? `
                                    <div class="fs-detection-box" style="top:20%;left:30%;width:35%;height:55%;"></div>
                                ` : ''}
                                <div class="fs-stream-cell-overlay">
                                    <div class="fs-stream-cell-name">${SentinelHelpers.escapeHtml(s.name)}</div>
                                </div>
                            </div>
                        `).join('')}
                    </div>
                    ` : ''}

                    <!-- Bottom Control Bar -->
                    <div class="fs-bottom-bar">
                        <button class="fs-exit-btn" onclick="LiveCCTV.exitFullscreen()">
                            <i data-lucide="minimize-2"></i> Exit Fullscreen
                        </button>
                        <button class="fs-stop-btn" onclick="LiveCCTV.stopSession()">
                            <i data-lucide="square"></i> Stop Live Stream
                        </button>
                        <span class="fs-esc-hint">Mode: ${this._detectionMode.toUpperCase()} | Threshold: ${this._threshold}%</span>
                    </div>
                </div>
            </div>
        `;
    },

    /* ==========================================================
       ACTIONS — Stream Management
       ========================================================== */
    addStream(e) {
        e.preventDefault();

        const data = {
            url: document.getElementById('stream-url').value.trim(),
            name: document.getElementById('stream-name').value.trim(),
            location: document.getElementById('stream-location').value.trim()
        };

        // Clear errors
        ['url', 'name', 'location'].forEach(f => {
            const errEl = document.getElementById(`stream-${f}-error`);
            if (errEl) errEl.textContent = '';
        });

        const validation = SentinelValidators.validateStreamForm(data);
        if (!validation.isValid) {
            Object.entries(validation.errors).forEach(([field, msg]) => {
                const errEl = document.getElementById(`stream-${field}-error`);
                if (errEl) errEl.textContent = msg;
            });
            SentinelToast.error('Validation Error', 'Please fill in all required fields.');
            return;
        }

        const streams = SentinelStore.getStreams();
        if (streams.length >= 3000) {
            SentinelToast.error('Limit Reached', 'Maximum of 3,000 streams supported.');
            return;
        }

        SentinelStore.addStream(data);

        // Auto-save stream URL
        const settings = SentinelStore.getSettings();
        if (settings.autoSaveStreams) {
            SentinelStore.saveStreamUrl({ url: data.url, name: data.name, location: data.location });
        }

        SentinelStore.addActivity({ type: 'system', message: `Stream added: ${data.name}`, color: 'green' });
        SentinelToast.success('Stream Added', `${data.name} has been added successfully.`);
        SentinelRouter.navigate(location.hash);
    },

    removeStream(id) {
        SentinelStore.deleteStream(id);
        SentinelToast.info('Stream Removed', 'Camera stream has been removed.');
        SentinelRouter.navigate(location.hash);
    },

    loadSavedStream(id) {
        const saved = SentinelStore.getSavedStreams().find(s => s.id === id);
        if (saved) {
            const urlInput = document.getElementById('stream-url');
            const nameInput = document.getElementById('stream-name');
            const locInput = document.getElementById('stream-location');
            if (urlInput) urlInput.value = saved.url;
            if (nameInput) nameInput.value = saved.name || '';
            if (locInput) locInput.value = saved.location || '';
            SentinelToast.info('Stream Loaded', 'Saved stream URL has been filled in.');
        }
    },

    deleteSavedStream(id) {
        SentinelStore.deleteSavedStream(id);
        SentinelToast.info('Removed', 'Saved stream URL deleted.');
        SentinelRouter.navigate(location.hash);
    },

    toggleFavorite(id) {
        SentinelStore.toggleStreamFavorite(id);
        SentinelRouter.navigate(location.hash);
    },

    setSavedTab(tab) {
        this._savedStreamTab = tab;
        SentinelRouter.navigate(location.hash);
    },

    /* ==========================================================
       ACTIONS — Detection Mode & Threshold
       ========================================================== */
    setDetectionMode(mode) {
        this._detectionMode = mode;
        document.querySelectorAll('.detection-mode-btn').forEach(btn => {
            const btnText = btn.textContent.trim().toLowerCase();
            btn.classList.toggle('active', btnText.includes(mode));
        });
    },

    setThreshold(value) {
        this._threshold = parseInt(value);
        const display = document.getElementById('threshold-display');
        if (display) display.textContent = value + '%';

        const labels = document.querySelectorAll('.threshold-labels span');
        labels.forEach((l, i) => {
            l.classList.remove('active');
            if (i === 0 && value < 35) l.classList.add('active');
            if (i === 1 && value >= 35 && value <= 70) l.classList.add('active');
            if (i === 2 && value > 70) l.classList.add('active');
        });
    },

    /* ==========================================================
       ACTIONS — Image Upload
       ========================================================== */
    handleImageSelect(e) {
        const files = Array.from(e.target.files);
        files.forEach(file => {
            if (file.type.startsWith('image/') && file.size <= 10 * 1024 * 1024) {
                const reader = new FileReader();
                reader.onload = (ev) => {
                    this._targetImages.push({ name: file.name, data: ev.target.result });
                    this._updateImagePreview();
                };
                reader.readAsDataURL(file);
            } else if (file.size > 10 * 1024 * 1024) {
                SentinelToast.warning('File Too Large', `${file.name} exceeds 10MB limit.`);
            }
        });
    },

    handleImageDrop(e) {
        e.preventDefault();
        e.currentTarget.classList.remove('dragover');
        const files = Array.from(e.dataTransfer.files);
        files.forEach(file => {
            if (file.type.startsWith('image/') && file.size <= 10 * 1024 * 1024) {
                const reader = new FileReader();
                reader.onload = (ev) => {
                    this._targetImages.push({ name: file.name, data: ev.target.result });
                    this._updateImagePreview();
                };
                reader.readAsDataURL(file);
            }
        });
    },

    _updateImagePreview() {
        const grid = document.getElementById('target-preview-grid');
        if (!grid) return;
        grid.innerHTML = this._targetImages.map((img, i) => `
            <div class="file-preview-item">
                <img src="${img.data}" alt="${SentinelHelpers.escapeHtml(img.name)}">
                <button class="file-preview-remove" onclick="LiveCCTV.removeTargetImage(${i})">
                    <i data-lucide="x" style="width:10px;height:10px;"></i>
                </button>
            </div>
        `).join('');
        if (typeof lucide !== 'undefined') lucide.createIcons();
    },

    removeTargetImage(index) {
        this._targetImages.splice(index, 1);
        this._updateImagePreview();
    },

    /* ==========================================================
       ACTIONS — Live Session Control
       ========================================================== */
    startSession() {
        const streams = SentinelStore.getStreams();
        if (streams.length === 0) {
            SentinelToast.error('No Streams', 'Please add at least one CCTV stream before starting.');
            return;
        }

        // Save target name
        const nameInput = document.getElementById('target-name');
        if (nameInput) this._targetName = nameInput.value.trim();

        this._isLive = true;
        this._fullscreenActive = true;
        this._activeStreamId = streams[0].id;
        this._focusedStreamId = null;
        this._detectedStreamIds.clear();

        SentinelStore.addActivity({ type: 'system', message: 'Live monitoring session started', color: 'green' });
        SentinelToast.success('Session Started', 'Fullscreen monitoring is now active.');
        SentinelRouter.navigate(location.hash);

        // Start Real WebSocket connection
        this._connectWebSocket();
    },

    stopSession() {
        SentinelModal.confirm({
            title: 'Stop Live Session',
            message: 'Are you sure you want to stop the live monitoring session? All streams will terminate and detection will stop.',
            confirmLabel: 'Stop Session',
            danger: true,
            onConfirm: () => {
                // Fully cleanup session resources
                LiveCCTV._cleanupSession();
                SentinelStore.addActivity({ type: 'system', message: 'Live monitoring session stopped', color: 'red' });
                SentinelModal.close();
                SentinelToast.info('Session Stopped', 'Live monitoring has been terminated. Resources cleaned up.');
                SentinelRouter.navigate('#/user/live-cctv');
            }
        });
    },

    _cleanupSession() {
        this._isLive = false;
        this._fullscreenActive = false;
        this._focusedStreamId = null;
        this._detectedStreamIds.clear();
        if (this._alertInterval) {
            clearInterval(this._alertInterval);
            this._alertInterval = null;
        }
        if (this._ws) {
            this._ws.close();
            this._ws = null;
        }
        if (this._wsReconnectTimer) {
            clearTimeout(this._wsReconnectTimer);
            this._wsReconnectTimer = null;
        }
        if (this._clockInterval) {
            clearInterval(this._clockInterval);
            this._clockInterval = null;
        }
        this._noiseIntervals.forEach(id => cancelAnimationFrame(id));
        this._noiseIntervals = [];
    },

    switchStream(id) {
        this._focusedStreamId = id;
        this._activeStreamId = id;
        if (this._fullscreenActive) {
            SentinelRouter.navigate(location.hash);
        }
    },

    /* ==========================================================
       REAL-TIME WEBSOCKET CONNECTION
       ========================================================== */
    _connectWebSocket() {
        const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        // Assuming the backend runs on the same host but port 8000
        const wsHost = window.location.hostname + ':8000';
        const wsUrl = `${wsProtocol}//${wsHost}/ws/live/`;
        
        console.log(`[Sentinel] Connecting to Live CCTV WebSocket: ${wsUrl}`);
        this._ws = new WebSocket(wsUrl);

        this._ws.onopen = () => {
            console.log('[Sentinel] WebSocket connected');
            SentinelToast.success('Connected', 'Live tracking feed established.');
            
            // Subscribe to active streams
            const streams = SentinelStore.getStreams();
            const streamIds = streams.map(s => s.id);
            this._ws.send(JSON.stringify({
                action: 'subscribe',
                streams: streamIds
            }));
        };

        this._ws.onmessage = (event) => {
            if (!this._isLive || !this._fullscreenActive) return;
            
            try {
                const data = JSON.parse(event.data);
                
                if (data.type === 'live.status') {
                    // Update FPS/Stats (can implement later)
                } else if (data.type === 'live.alert') {
                    this._handleRealAlert(data.data);
                }
            } catch (err) {
                console.error('[Sentinel] WebSocket message error:', err);
            }
        };

        this._ws.onclose = () => {
            console.log('[Sentinel] WebSocket disconnected');
            if (this._isLive && this._fullscreenActive) {
                SentinelToast.warning('Disconnected', 'Live feed lost. Reconnecting...');
                // Auto-reconnect logic
                this._wsReconnectTimer = setTimeout(() => {
                    this._connectWebSocket();
                }, 3000);
            }
        };

        this._ws.onerror = (err) => {
            console.error('[Sentinel] WebSocket error:', err);
        };
    },

    _handleRealAlert(alertData) {
        const streams = SentinelStore.getStreams();
        const stream = streams.find(s => s.id === alertData.camera_id) || streams[0];
        if (!stream) return;

        const confidence = alertData.confidence ? Math.round(alertData.confidence * 100) : 85;

        // Add to detected set
        this._detectedStreamIds.add(stream.id);

        // Auto-focus detected stream
        this._focusedStreamId = stream.id;

        // Create alert
        SentinelStore.addAlert({
            camera: stream.name,
            location: stream.location,
            message: `Suspect detected — Confidence: ${confidence}% — Mode: ${this._detectionMode.toUpperCase()}`,
            type: 'detection',
            confidence: confidence
        });

        // Auto-generate evidence
        SentinelStore.addEvidence({
            type: 'live',
            cameraName: stream.name,
            cameraLocation: stream.location,
            detectionMode: this._detectionMode,
            confidence: confidence + '%',
            duration: '10s',
            title: `Detection - ${stream.name}`,
            targetName: this._targetName || 'Unknown Suspect'
        });

        SentinelStore.addActivity({
            type: 'alert',
            message: `Suspect detected on ${stream.name} (${confidence}%)`,
            color: 'red'
        });

        // Re-render to show detection
        SentinelRouter.navigate(location.hash);

        // Clear detection after 8 seconds
        setTimeout(() => {
            this._detectedStreamIds.delete(stream.id);
            if (this._fullscreenActive) {
                // Update sidebar indicator without full re-render
                const sidebarEl = document.getElementById(`fs-sidebar-${stream.id}`);
                if (sidebarEl) sidebarEl.classList.remove('detected');
                const cellEl = document.getElementById(`fs-cell-${stream.id}`);
                if (cellEl) cellEl.classList.remove('detected');
            }
        }, 8000);
    },

    /* ==========================================================
       CANVAS NOISE RENDERING — simulates CCTV static
       ========================================================== */
    _initNoiseCanvases() {
        const canvases = document.querySelectorAll('.feed-noise-canvas');
        canvases.forEach(canvas => {
            if (!canvas || !canvas.getContext) return;
            const ctx = canvas.getContext('2d');
            const w = canvas.width;
            const h = canvas.height;

            const drawNoise = () => {
                const imageData = ctx.createImageData(w, h);
                const data = imageData.data;
                for (let i = 0; i < data.length; i += 4) {
                    const val = Math.random() * 40 + 10;
                    data[i] = val;
                    data[i + 1] = val + Math.random() * 5;
                    data[i + 2] = val + Math.random() * 10;
                    data[i + 3] = 255;
                }
                ctx.putImageData(imageData, 0, 0);

                // Add scan lines
                ctx.fillStyle = 'rgba(0, 255, 100, 0.02)';
                const lineY = (Date.now() / 30) % h;
                ctx.fillRect(0, lineY, w, 3);

                // Slight green tint overlay
                ctx.fillStyle = 'rgba(0, 200, 100, 0.03)';
                ctx.fillRect(0, 0, w, h);
            };

            const animate = () => {
                if (!this._fullscreenActive && !document.getElementById(canvas.id)) return;
                drawNoise();
                const id = requestAnimationFrame(animate);
                this._noiseIntervals.push(id);
            };

            drawNoise();
            if (this._fullscreenActive || this._isLive) {
                const id = requestAnimationFrame(animate);
                this._noiseIntervals.push(id);
            }
        });
    },

    _startClock() {
        if (this._clockInterval) clearInterval(this._clockInterval);
        this._clockInterval = setInterval(() => {
            const now = new Date();
            const clockEl = document.getElementById('fs-clock');
            const timeEl = document.getElementById('fs-feed-time');
            if (clockEl) clockEl.textContent = now.toLocaleTimeString() + ' — ' + now.toLocaleDateString();
            if (timeEl) timeEl.textContent = now.toLocaleTimeString();
        }, 1000);
    },

    /* ==========================================================
       Exit fullscreen — return to Live CCTV config page
       ========================================================== */
    exitFullscreen() {
        this._cleanupSession();
        SentinelStore.addActivity({ type: 'system', message: 'Exited fullscreen monitoring', color: 'amber' });
        SentinelToast.info('Fullscreen Exited', 'Returned to Live CCTV configuration page.');
        SentinelRouter.navigate('#/user/live-cctv');
    },

    /* ==========================================================
       INIT — Called by router after render
       ========================================================== */
    init() {
        // ESC key handler for fullscreen overlay
        this._escHandler = (e) => {
            if (e.key === 'Escape' && this._fullscreenActive) {
                e.preventDefault();
                this.exitFullscreen();
            }
        };
        document.addEventListener('keydown', this._escHandler);

        // Initialize noise canvases for stream preview thumbnails
        setTimeout(() => {
            this._initNoiseCanvases();
            if (this._fullscreenActive) {
                this._startClock();
            }
        }, 100);
    }
};
