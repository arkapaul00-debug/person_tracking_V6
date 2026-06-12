/* ============================================================
   SENTINEL PRO — Backend API Integration
   ============================================================ */

const SentinelAPI = {
    /**
     * Helper to get CSRF token from cookies if needed
     */
    getCSRFToken() {
        let cookieValue = null;
        if (document.cookie && document.cookie !== '') {
            const cookies = document.cookie.split(';');
            for (let i = 0; i < cookies.length; i++) {
                const cookie = cookies[i].trim();
                if (cookie.substring(0, 'csrftoken'.length + 1) === ('csrftoken' + '=')) {
                    cookieValue = decodeURIComponent(cookie.substring('csrftoken'.length + 1));
                    break;
                }
            }
        }
        return cookieValue;
    },

    /**
     * Start forensic video analysis
     * @param {FormData} formData - Contains video file, reference images, mode, and threshold
     */
    async analyzeVideo(formData) {
        try {
            const response = await fetch('/analyze/', {
                method: 'POST',
                headers: {
                    'X-CSRFToken': this.getCSRFToken()
                },
                body: formData
            });
            if (!response.ok) {
                const errorData = await response.json();
                throw new Error(errorData.message || 'Failed to start analysis');
            }
            return await response.json();
        } catch (error) {
            console.error('API Error (analyzeVideo):', error);
            throw error;
        }
    },

    /**
     * Poll case status and logs
     * @param {string} caseId 
     */
    async getCaseStatus(caseId) {
        try {
            const response = await fetch(`/status/${caseId}/`);
            if (!response.ok) throw new Error('Failed to get case status');
            return await response.json();
        } catch (error) {
            console.error('API Error (getCaseStatus):', error);
            throw error;
        }
    },

    /**
     * Get sightings for a completed case
     * @param {string} caseId 
     */
    async getSightings(caseId) {
        try {
            const response = await fetch(`/sightings/${caseId}/`);
            if (!response.ok) throw new Error('Failed to get sightings');
            return await response.json();
        } catch (error) {
            console.error('API Error (getSightings):', error);
            throw error;
        }
    },

    /**
     * Start live CCTV stream analysis
     * @param {FormData} formData - Contains mode, threshold, stream_ids, references
     */
    async startLiveStream(formData) {
        try {
            const response = await fetch('/api/live/start/', {
                method: 'POST',
                headers: {
                    'X-CSRFToken': this.getCSRFToken()
                },
                body: formData
            });
            if (!response.ok) {
                const text = await response.text();
                throw new Error(`Failed to start live stream: HTTP ${response.status} - ${text}`);
            }
            return await response.json();
        } catch (error) {
            console.error('API Error (startLiveStream):', error);
            throw error;
        }
    },

    /**
     * Stop live CCTV stream analysis
     */
    async stopLiveStream() {
        try {
            const response = await fetch('/api/live/stop/', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': this.getCSRFToken()
                }
            });
            if (!response.ok) throw new Error('Failed to stop live stream');
            return await response.json();
        } catch (error) {
            console.error('API Error (stopLiveStream):', error);
            throw error;
        }
    },

    /**
     * Add a new CCTV stream to the backend registry
     */
    async addStream(data) {
        try {
            const response = await fetch('/api/streams/', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': this.getCSRFToken()
                },
                body: JSON.stringify({
                    name: data.name,
                    rtsp_url: data.url,
                    location: data.location
                })
            });
            if (!response.ok) throw new Error('Failed to add stream');
            return await response.json();
        } catch (error) {
            console.error('API Error (addStream):', error);
            throw error;
        }
    },

    /**
     * Get all registered streams from the backend
     */
    async getStreams() {
        try {
            const response = await fetch('/api/streams/');
            if (!response.ok) throw new Error('Failed to get streams');
            return await response.json();
        } catch (error) {
            console.error('API Error (getStreams):', error);
            throw error;
        }
    },

    /**
     * Remove a stream from the backend registry
     * @param {string} streamId
     */
    async removeStream(streamId) {
        try {
            const response = await fetch('/api/streams/', {
                method: 'DELETE',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': this.getCSRFToken()
                },
                body: JSON.stringify({ stream_id: streamId })
            });
            if (!response.ok) throw new Error('Failed to remove stream');
            return await response.json();
        } catch (error) {
            console.error('API Error (removeStream):', error);
            throw error;
        }
    },

    /**
     * Get live session status from the backend orchestrator
     */
    async getLiveStatus() {
        try {
            const response = await fetch('/api/live/status/');
            if (!response.ok) throw new Error('Failed to get live status');
            return await response.json();
        } catch (error) {
            console.error('API Error (getLiveStatus):', error);
            throw error;
        }
    },

    /**
     * Get live detection alerts for a session
     * @param {string} sessionId
     */
    async getLiveAlerts(sessionId) {
        try {
            const response = await fetch(`/api/live/alerts/${sessionId}/`);
            if (!response.ok) throw new Error('Failed to get live alerts');
            return await response.json();
        } catch (error) {
            console.error('API Error (getLiveAlerts):', error);
            throw error;
        }
    },

    /**
     * Get system health status
     */
    async getHealth() {
        try {
            const response = await fetch('/api/v2/health/');
            if (!response.ok) throw new Error('Failed to get health');
            return await response.json();
        } catch (error) {
            console.error('API Error (getHealth):', error);
            throw error;
        }
    },

    /**
     * Get engine metrics
     */
    async getMetrics() {
        try {
            const response = await fetch('/api/v2/metrics/');
            if (!response.ok) throw new Error('Failed to get metrics');
            return await response.json();
        } catch (error) {
            console.error('API Error (getMetrics):', error);
            throw error;
        }
    },

    /**
     * Get evidence chain for audit
     */
    async getEvidenceChain() {
        try {
            const response = await fetch('/api/v2/evidence/chain/');
            if (!response.ok) throw new Error('Failed to get evidence chain');
            return await response.json();
        } catch (error) {
            console.error('API Error (getEvidenceChain):', error);
            throw error;
        }
    },

    /**
     * Export signed evidence package
     * @param {object} data - evidence_ids, clip_paths, output_path, case_id, actor
     */
    async exportEvidence(data) {
        try {
            const response = await fetch('/api/v2/evidence/export/', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': this.getCSRFToken()
                },
                body: JSON.stringify(data)
            });
            if (!response.ok) throw new Error('Failed to export evidence');
            return await response.json();
        } catch (error) {
            console.error('API Error (exportEvidence):', error);
            throw error;
        }
    }
};
