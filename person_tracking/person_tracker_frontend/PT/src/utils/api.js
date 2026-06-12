/* ============================================================
   SENTINEL PRO — Centralized API Client (Replaces store.js)
   ============================================================ */

const SentinelAPI = {
    // Base URL for the backend API
    _baseUrl: '/api',

    /**
     * Helper to perform fetch requests
     */
    async _request(endpoint, options = {}) {
        const url = `${this._baseUrl}${endpoint}`;
        
        // Setup default headers (adding auth token if it exists)
        const headers = {
            'Content-Type': 'application/json',
            'Accept': 'application/json',
            ...options.headers
        };

        const token = SentinelAuth.getToken();
        if (token) {
            headers['Authorization'] = `Bearer ${token}`;
        }

        const config = {
            ...options,
            headers
        };

        try {
            const response = await fetch(url, config);
            
            // Handle 401 Unauthorized globally
            if (response.status === 401) {
                SentinelAuth.logout();
                window.location.href = '#login';
                throw new Error('Session expired. Please log in again.');
            }

            if (!response.ok) {
                const errText = await response.text();
                throw new Error(`API Error ${response.status}: ${errText}`);
            }

            // Return JSON if content-type is json
            const contentType = response.headers.get('content-type');
            if (contentType && contentType.includes('application/json')) {
                return await response.json();
            }
            return await response.text();

        } catch (error) {
            console.error(`[API Error] ${endpoint}:`, error);
            throw error;
        }
    },

    // ---- Users (Admin) ----
    
    async getUsers() {
        return this._request('/users/');
    },

    async addUser(userData) {
        return this._request('/users/', {
            method: 'POST',
            body: JSON.stringify(userData)
        });
    },

    async updateUser(id, updates) {
        return this._request(`/users/${id}/`, {
            method: 'PATCH',
            body: JSON.stringify(updates)
        });
    },

    async deleteUser(id) {
        return this._request(`/users/${id}/`, {
            method: 'DELETE'
        });
    },

    // ---- Streams ----

    async getStreams() {
        return this._request('/streams/'); // Connects to StreamManageView
    },

    async addStream(streamData) {
        return this._request('/streams/', {
            method: 'POST',
            body: JSON.stringify(streamData)
        });
    },

    async deleteStream(id) {
        return this._request(`/streams/${id}/`, { // Requires adding DELETE to StreamManageView
            method: 'DELETE'
        });
    },

    // ---- Evidence Vault ----

    async getCases() {
        return this._request('/cases/');
    },

    async getEvidence(caseId) {
        // Gets sightings for a specific case
        return this._request(`/sightings/${caseId}/`);
    },

    // ---- Live Tracking ----
    
    async getLiveStatus() {
        return this._request('/live/status/');
    },

    async startLiveTracking(params) {
        return this._request('/live/start/', {
            method: 'POST',
            body: JSON.stringify(params)
        });
    },

    async stopLiveTracking(sessionId) {
        return this._request('/live/stop/', {
            method: 'POST',
            body: JSON.stringify({ session_id: sessionId })
        });
    },

    async getLiveAlerts(sessionId) {
        return this._request(`/live/alerts/${sessionId}/`);
    },

    // ---- Settings / Stats ----

    async getSettings() {
        return this._request('/settings/');
    },

    async updateSettings(updates) {
        return this._request('/settings/', {
            method: 'PATCH',
            body: JSON.stringify(updates)
        });
    },

    async getDashboardStats() {
        return this._request('/v2/metrics/'); // Connects to MetricsView
    }
};

// SentinelAPI is a standalone client. 
