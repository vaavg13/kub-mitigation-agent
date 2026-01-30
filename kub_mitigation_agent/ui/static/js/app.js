/**
 * KubMitigation Agent UI - Live Trace Viewer
 * 
 * Real-time visualization of experiment execution and agent traces.
 */

class AgentUI {
    constructor() {
        this.ws = null;
        this.currentExperiment = null;
        this.charts = {};
        this.reconnectAttempts = 0;
        this.maxReconnectAttempts = 10;
        this.heartbeatInterval = null;
        
        this.init();
    }
    
    init() {
        this.connectWebSocket();
        this.startHeartbeat();
    }
    
    // =====================
    // WebSocket Connection
    // =====================
    
    connectWebSocket() {
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const wsUrl = `${protocol}//${window.location.host}/ws/trace`;
        
        this.updateConnectionStatus('connecting');
        
        try {
            this.ws = new WebSocket(wsUrl);
            
            this.ws.onopen = () => {
                console.log('WebSocket connected');
                this.updateConnectionStatus('connected');
                this.reconnectAttempts = 0;
            };
            
            this.ws.onclose = () => {
                console.log('WebSocket disconnected');
                this.updateConnectionStatus('disconnected');
                this.scheduleReconnect();
            };
            
            this.ws.onerror = (error) => {
                console.error('WebSocket error:', error);
            };
            
            this.ws.onmessage = (event) => {
                try {
                    const message = JSON.parse(event.data);
                    this.handleMessage(message);
                } catch (e) {
                    console.error('Failed to parse message:', e);
                }
            };
        } catch (error) {
            console.error('Failed to connect WebSocket:', error);
            this.updateConnectionStatus('disconnected');
            this.scheduleReconnect();
        }
    }
    
    scheduleReconnect() {
        if (this.reconnectAttempts < this.maxReconnectAttempts) {
            this.reconnectAttempts++;
            const delay = Math.min(1000 * Math.pow(1.5, this.reconnectAttempts), 10000);
            console.log(`Reconnecting in ${delay}ms (attempt ${this.reconnectAttempts})`);
            setTimeout(() => this.connectWebSocket(), delay);
        }
    }
    
    startHeartbeat() {
        // Periodically check connection
        this.heartbeatInterval = setInterval(() => {
            if (this.ws && this.ws.readyState === WebSocket.OPEN) {
                // Connection is healthy
            } else if (this.ws && this.ws.readyState === WebSocket.CLOSED) {
                this.scheduleReconnect();
            }
        }, 5000);
    }
    
    updateConnectionStatus(status) {
        const statusDot = document.querySelector('.status-dot');
        const statusText = document.querySelector('.status-text');
        
        if (statusDot) {
            statusDot.className = 'status-dot';
            if (status === 'connected') statusDot.classList.add('connected');
            else if (status === 'connecting') statusDot.classList.add('connecting');
        }
        
        if (statusText) {
            statusText.textContent = status === 'connected' ? 'Connected' :
                                    status === 'connecting' ? 'Connecting...' : 'Disconnected';
        }
    }
    
    // =====================
    // Message Handling
    // =====================
    
    handleMessage(message) {
        console.log('Received:', message.type);
        
        switch (message.type) {
            case 'init':
                if (message.experiment) {
                    this.initExperiment(message.experiment);
                } else {
                    this.showWaitingState();
                }
                break;
                
            case 'event':
                this.handleEvent(message.event);
                break;
                
            case 'heartbeat':
                // Keep-alive, ignore
                break;
        }
    }
    
    handleEvent(event) {
        console.log('Event:', event.event_type, event.experiment_id);
        
        switch (event.event_type) {
            case 'experiment_start':
                this.onExperimentStart(event);
                break;
                
            case 'phase':
                this.onPhaseUpdate(event.data);
                break;
                
            case 'step':
                this.onAgentStep(event.data);
                break;
                
            case 'experiment_end':
                this.onExperimentEnd(event.data);
                break;
        }
    }
    
    // =====================
    // Experiment Lifecycle
    // =====================
    
    initExperiment(experiment) {
        this.currentExperiment = experiment;
        this.renderExperiment();
    }
    
    onExperimentStart(event) {
        this.currentExperiment = {
            id: event.experiment_id,
            started_at: event.timestamp,
            config: event.data.config || {},
            phases: [],
            steps: [],
            status: 'running'
        };
        this.renderExperiment();
    }
    
    onPhaseUpdate(data) {
        if (!this.currentExperiment) return;
        
        // Update or add phase
        const existingIdx = this.currentExperiment.phases.findIndex(
            p => p.phase === data.phase && p.status === 'started'
        );
        
        if (data.status === 'completed' && existingIdx >= 0) {
            this.currentExperiment.phases[existingIdx] = data;
        } else {
            this.currentExperiment.phases.push(data);
        }
        
        this.updatePhaseTimeline();
        
        // Update metrics if present
        if (data.metrics && Object.keys(data.metrics).length > 0) {
            this.updateMetrics(data.phase, data.metrics);
        }
    }
    
    onAgentStep(data) {
        if (!this.currentExperiment) return;
        
        this.currentExperiment.steps.push(data);
        this.appendTraceStep(data);
    }
    
    onExperimentEnd(data) {
        if (!this.currentExperiment) return;
        
        this.currentExperiment.status = data.status;
        this.currentExperiment.summary = data.summary;
        
        this.updateExperimentStatus();
        
        if (data.summary) {
            this.renderSummary(data.summary);
        }
    }
    
    // =====================
    // Rendering
    // =====================
    
    showWaitingState() {
        const content = document.getElementById('mainContent');
        if (content) {
            content.innerHTML = `
                <div class="empty-state">
                    <div class="empty-state-icon">⏳</div>
                    <div class="empty-state-title">Waiting for Experiment</div>
                    <div class="empty-state-text">
                        The UI will update automatically when an experiment starts.
                    </div>
                </div>
            `;
        }
    }
    
    renderExperiment() {
        const content = document.getElementById('mainContent');
        if (!content || !this.currentExperiment) return;
        
        const exp = this.currentExperiment;
        const config = exp.config || {};
        
        content.innerHTML = `
            <!-- Experiment Header -->
            <div class="card experiment-header-card">
                <div class="card-header">
                    <h3>${exp.id || 'Experiment'}</h3>
                    <div class="header-tags">
                        <span class="tag ${exp.status === 'running' ? 'info' : exp.status === 'success' ? 'success' : 'error'}" id="statusTag">
                            ${exp.status === 'running' ? '● Running' : exp.status}
                        </span>
                    </div>
                </div>
                <div class="card-body">
                    <div class="experiment-info-row">
                        ${config.namespace ? `<span><strong>Namespace:</strong> ${config.namespace}</span>` : ''}
                        ${config.chaos_config ? `
                            <span><strong>Chaos:</strong> ${config.chaos_config.mode || ''}/${config.chaos_config.fault_type || ''}</span>
                        ` : ''}
                        <span><strong>Started:</strong> ${this.formatTimestamp(exp.started_at)}</span>
                    </div>
                </div>
            </div>
            
            <!-- Phase Timeline -->
            <div class="card">
                <div class="card-header">
                    <h3>Experiment Phases</h3>
                </div>
                <div class="card-body">
                    <div class="phase-timeline-horizontal" id="phaseTimeline">
                        ${this.renderPhaseTimeline()}
                    </div>
                </div>
            </div>
            
            <!-- Metrics -->
            <div class="card" id="metricsCard" style="display: none;">
                <div class="card-header">
                    <h3>Metrics</h3>
                </div>
                <div class="card-body">
                    <div class="metrics-grid" id="metricsGrid"></div>
                </div>
            </div>
            
            <!-- Agent Trace -->
            <div class="card">
                <div class="card-header">
                    <h3>Agent Trace</h3>
                    <span class="step-counter" id="stepCounter">${exp.steps?.length || 0} steps</span>
                </div>
                <div class="card-body">
                    <div class="trace-viewer" id="traceViewer">
                        ${this.renderExistingSteps()}
                    </div>
                </div>
            </div>
            
            <!-- Summary (shown at end) -->
            <div id="summaryContainer"></div>
        `;
    }
    
    renderPhaseTimeline() {
        const phases = [
            { name: 'Setup', key: 'setup', icon: '🔧' },
            { name: 'Warmup', key: 'warmup', icon: '🔥' },
            { name: 'Baseline', key: 'baseline', icon: '📊' },
            { name: 'Chaos', key: 'chaos', icon: '💥' },
            { name: 'Mitigation', key: 'mitigation', icon: '🤖' },
            { name: 'Recovery', key: 'recovery', icon: '📈' },
            { name: 'Teardown', key: 'teardown', icon: '🧹' }
        ];
        
        const completedPhases = new Set();
        const activePhase = this.getActivePhase();
        
        if (this.currentExperiment?.phases) {
            for (const p of this.currentExperiment.phases) {
                if (p.status === 'completed') {
                    completedPhases.add(p.phase);
                }
            }
        }
        
        return phases.map((phase, idx) => {
            const isCompleted = completedPhases.has(phase.key);
            const isActive = activePhase === phase.key;
            
            return `
                <div class="phase-step ${isCompleted ? 'completed' : ''} ${isActive ? 'active' : ''}" data-phase="${phase.key}">
                    <div class="phase-icon">${phase.icon}</div>
                    <div class="phase-name">${phase.name}</div>
                    ${idx < phases.length - 1 ? '<div class="phase-connector"></div>' : ''}
                </div>
            `;
        }).join('');
    }
    
    getActivePhase() {
        if (!this.currentExperiment?.phases) return null;
        
        const phases = this.currentExperiment.phases;
        for (let i = phases.length - 1; i >= 0; i--) {
            if (phases[i].status === 'started') {
                return phases[i].phase;
            }
        }
        return null;
    }
    
    updatePhaseTimeline() {
        const timeline = document.getElementById('phaseTimeline');
        if (timeline) {
            timeline.innerHTML = this.renderPhaseTimeline();
        }
    }
    
    renderExistingSteps() {
        if (!this.currentExperiment?.steps?.length) {
            return '<div class="trace-empty">Waiting for agent actions...</div>';
        }
        
        return this.currentExperiment.steps.map((step, idx) => 
            this.renderStep(step, idx)
        ).join('');
    }
    
    renderStep(step, index) {
        const actions = step.actions || [];
        const observations = step.observations || [];
        
        // Check if this is a special action
        const primaryAction = actions[0]?.name || '';
        const isSpecialAction = ['generate_action_plan', 'generate_operational_summary'].includes(primaryAction);
        
        return `
            <div class="trace-step ${isSpecialAction ? 'special-action' : ''}" data-step="${index}">
                <div class="step-header" onclick="app.toggleStep(${index})">
                    <div class="step-number">${step.step_number || index + 1}</div>
                    <div class="step-title">
                        ${this.getStepTitle(primaryAction, actions)}
                    </div>
                    <div class="step-expand">▼</div>
                </div>
                <div class="step-content">
                    ${step.thought ? `
                        <div class="step-section">
                            <div class="step-section-title">Thought</div>
                            <div class="thought-box">${this.escapeHtml(step.thought)}</div>
                        </div>
                    ` : ''}
                    
                    ${this.renderActions(actions, index)}
                    
                    ${this.renderObservations(observations, index, primaryAction)}
                </div>
            </div>
        `;
    }
    
    getStepTitle(primaryAction, actions) {
        const specialTitles = {
            'generate_action_plan': '📋 Action Plan',
            'generate_operational_summary': '📊 Operational Summary',
            'prometheus_get_pod_cpu_timeseries': '📈 Pod CPU Metrics',
            'prometheus_get_pod_memory_timeseries': '📈 Pod Memory Metrics',
            'prometheus_get_service_latency_timeseries': '📈 Service Latency',
            'prometheus_get_node_cpu_timeseries': '📈 Node CPU Metrics',
            'prometheus_get_node_memory_timeseries': '📈 Node Memory Metrics',
            'prometheus_get_ingress_stats': '📈 Ingress Stats',
            'prometheus_get_service_topology': '🔗 Service Topology'
        };
        
        if (specialTitles[primaryAction]) {
            return specialTitles[primaryAction];
        }
        
        return actions.map(a => a.name).join(', ') || 'Action';
    }
    
    renderActions(actions, stepIndex) {
        if (!actions || actions.length === 0) return '';
        
        const primaryAction = actions[0];
        
        // Special rendering for action plan
        if (primaryAction.name === 'generate_action_plan') {
            return this.renderActionPlan(primaryAction.args);
        }
        
        // Special rendering for operational summary
        if (primaryAction.name === 'generate_operational_summary') {
            return this.renderOperationalSummaryAction(primaryAction.args);
        }
        
        // Default rendering
        return `
            <div class="step-section">
                <div class="step-section-title">Actions</div>
                ${actions.map(action => `
                    <div class="action-box">
                        <div class="action-name">${action.name}</div>
                        <div class="action-args">${JSON.stringify(action.args, null, 2)}</div>
                    </div>
                `).join('')}
            </div>
        `;
    }
    
    renderActionPlan(args) {
        return `
            <div class="step-section">
                <div class="action-plan-card">
                    <div class="plan-header">
                        <span class="plan-icon">📋</span>
                        <h4>Action Plan</h4>
                    </div>
                    
                    <div class="plan-field">
                        <label>Objective</label>
                        <p>${this.escapeHtml(args.objective || '')}</p>
                    </div>
                    
                    <div class="plan-field">
                        <label>Situation</label>
                        <p>${this.escapeHtml(args.situation || '')}</p>
                    </div>
                    
                    <div class="plan-field">
                        <label>Steps</label>
                        <ol class="plan-steps">
                            ${(args.steps || []).map(step => `<li>${this.escapeHtml(step)}</li>`).join('')}
                        </ol>
                    </div>
                    
                    <div class="plan-field">
                        <label>Expected Outcomes</label>
                        <ul class="plan-outcomes">
                            ${(args.expected_outcomes || []).map(outcome => `<li>${this.escapeHtml(outcome)}</li>`).join('')}
                        </ul>
                    </div>
                </div>
            </div>
        `;
    }
    
    renderOperationalSummaryAction(args) {
        const statusClass = (args.status || '').toLowerCase().includes('success') ? 'success' : 
                           (args.status || '').toLowerCase().includes('fail') ? 'error' : 'info';
        
        return `
            <div class="step-section">
                <div class="summary-action-card ${statusClass}">
                    <div class="summary-header">
                        <span class="summary-icon">📊</span>
                        <h4>Operational Summary</h4>
                        <span class="tag ${statusClass}">${args.success ? 'Success' : 'Completed'}</span>
                    </div>
                    
                    <div class="summary-field">
                        <label>Objective</label>
                        <p>${this.escapeHtml(args.objective || '')}</p>
                    </div>
                    
                    <div class="summary-field">
                        <label>Status</label>
                        <p class="${statusClass}">${this.escapeHtml(args.status || '')}</p>
                    </div>
                    
                    ${args.problem_location && args.problem_location.length > 0 ? `
                        <div class="summary-field">
                            <label>Problem Location</label>
                            <div class="problem-locations">
                                ${args.problem_location.map(loc => `
                                    <span class="location-tag">
                                        <span class="loc-type">${loc.type || 'resource'}</span>
                                        <span class="loc-name">${loc.name || 'unknown'}</span>
                                    </span>
                                `).join('')}
                            </div>
                        </div>
                    ` : ''}
                    
                    <div class="summary-field">
                        <label>Actions Completed</label>
                        <ul class="summary-list">
                            ${(args.actions_completed || []).map(a => `<li>${this.escapeHtml(a)}</li>`).join('')}
                        </ul>
                    </div>
                    
                    <div class="summary-field">
                        <label>Results Achieved</label>
                        <ul class="summary-list">
                            ${(args.results_achieved || []).map(r => `<li>${this.escapeHtml(r)}</li>`).join('')}
                        </ul>
                    </div>
                </div>
            </div>
        `;
    }
    
    renderObservations(observations, stepIndex, actionName) {
        if (!observations || observations.length === 0) return '';
        
        // For special actions, don't show observation (it's the same as args)
        if (['generate_action_plan', 'generate_operational_summary'].includes(actionName)) {
            return '';
        }
        
        return `
            <div class="step-section">
                <div class="step-section-title">Observations</div>
                ${observations.map((obs, obsIdx) => this.renderSingleObservation(obs, stepIndex, obsIdx)).join('')}
            </div>
        `;
    }
    
    renderSingleObservation(obs, stepIndex, obsIdx) {
        const hasTs = this.hasTimeseries(obs);
        
        // If it has timeseries, show chart first and collapse raw data
        if (hasTs) {
            return `
                <div class="observation-box has-chart">
                    <div class="chart-container">
                        <canvas id="obsChart-${stepIndex}-${obsIdx}"></canvas>
                    </div>
                    <details class="raw-data-collapse">
                        <summary>Raw Data</summary>
                        <div class="observation-content">${this.formatObservation(obs)}</div>
                    </details>
                </div>
            `;
        }
        
        // Regular observation
        return `
            <div class="observation-box">
                <div class="observation-content">${this.formatObservation(obs)}</div>
            </div>
        `;
    }
    
    appendTraceStep(stepData) {
        const viewer = document.getElementById('traceViewer');
        const counter = document.getElementById('stepCounter');
        
        if (!viewer) return;
        
        // Remove empty state if present
        const empty = viewer.querySelector('.trace-empty');
        if (empty) empty.remove();
        
        const index = this.currentExperiment?.steps?.length - 1 || 0;
        const stepHtml = this.renderStep(stepData, index);
        viewer.insertAdjacentHTML('beforeend', stepHtml);
        
        // Auto-expand the new step
        const newStep = viewer.lastElementChild;
        if (newStep) {
            newStep.classList.add('expanded');
            newStep.scrollIntoView({ behavior: 'smooth', block: 'end' });
            
            // Initialize charts if needed
            this.initializeStepCharts(index);
        }
        
        // Update counter
        if (counter) {
            counter.textContent = `${this.currentExperiment?.steps?.length || 0} steps`;
        }
    }
    
    toggleStep(index) {
        const step = document.querySelector(`.trace-step[data-step="${index}"]`);
        if (step) {
            const wasExpanded = step.classList.contains('expanded');
            step.classList.toggle('expanded');
            
            if (!wasExpanded) {
                this.initializeStepCharts(index);
            }
        }
    }
    
    updateMetrics(phase, metrics) {
        const card = document.getElementById('metricsCard');
        const grid = document.getElementById('metricsGrid');
        
        if (!card || !grid) return;
        
        card.style.display = 'block';
        
        // Add or update metrics
        const phaseLabel = phase.charAt(0).toUpperCase() + phase.slice(1);
        
        if (metrics.success_rate_percent !== undefined) {
            this.updateMetricCard(grid, `${phase}_success`, `${phaseLabel} Success Rate`, 
                `${metrics.success_rate_percent.toFixed(1)}%`,
                metrics.success_rate_percent >= 95 ? 'success' : metrics.success_rate_percent >= 80 ? 'warning' : 'error'
            );
        }
        
        if (metrics.p95_latency_seconds !== undefined) {
            const latencyMs = (metrics.p95_latency_seconds * 1000).toFixed(0);
            this.updateMetricCard(grid, `${phase}_latency`, `${phaseLabel} P95 Latency`, 
                `${latencyMs}ms`
            );
        }
    }
    
    updateMetricCard(container, id, label, value, colorClass = '') {
        let card = container.querySelector(`[data-metric="${id}"]`);
        
        if (!card) {
            card = document.createElement('div');
            card.className = 'metric-card';
            card.dataset.metric = id;
            container.appendChild(card);
        }
        
        card.innerHTML = `
            <div class="metric-label">${label}</div>
            <div class="metric-value ${colorClass}">${value}</div>
        `;
    }
    
    updateExperimentStatus() {
        const tag = document.getElementById('statusTag');
        if (tag && this.currentExperiment) {
            const status = this.currentExperiment.status;
            tag.className = `tag ${status === 'success' ? 'success' : status === 'failed' ? 'error' : 'info'}`;
            tag.textContent = status === 'running' ? '● Running' : status;
        }
    }
    
    renderSummary(summary) {
        const container = document.getElementById('summaryContainer');
        if (!container) return;
        
        const statusClass = (summary.status || '').toLowerCase().includes('success') ? 'success' : 
                           (summary.status || '').toLowerCase().includes('fail') ? 'error' : '';
        
        container.innerHTML = `
            <div class="card summary-card">
                <div class="card-header">
                    <h3>Operational Summary</h3>
                    <span class="tag ${statusClass}">${summary.status || 'Completed'}</span>
                </div>
                <div class="card-body">
                    <div class="summary-grid">
                        ${summary.objective ? `
                            <div class="summary-item">
                                <span class="summary-label">Objective</span>
                                <span class="summary-value">${this.escapeHtml(summary.objective)}</span>
                            </div>
                        ` : ''}
                        ${summary.problem_location && summary.problem_location.length > 0 ? `
                            <div class="summary-item">
                                <span class="summary-label">Problem Location</span>
                                <span class="summary-value">${Array.isArray(summary.problem_location) ? summary.problem_location.join(', ') : summary.problem_location}</span>
                            </div>
                        ` : ''}
                        ${summary.root_cause ? `
                            <div class="summary-item full-width">
                                <span class="summary-label">Root Cause</span>
                                <span class="summary-value">${this.escapeHtml(summary.root_cause)}</span>
                            </div>
                        ` : ''}
                        ${summary.actions_completed && summary.actions_completed.length > 0 ? `
                            <div class="summary-item full-width">
                                <span class="summary-label">Actions Completed</span>
                                <ul class="summary-list">
                                    ${summary.actions_completed.map(a => `<li>${this.escapeHtml(a)}</li>`).join('')}
                                </ul>
                            </div>
                        ` : ''}
                    </div>
                </div>
            </div>
        `;
        
        container.scrollIntoView({ behavior: 'smooth' });
    }
    
    // =====================
    // Charts
    // =====================
    
    initializeStepCharts(stepIndex) {
        const step = this.currentExperiment?.steps?.[stepIndex];
        if (!step) return;
        
        const observations = step.observations || [];
        observations.forEach((obs, obsIndex) => {
            if (this.hasTimeseries(obs)) {
                this.createObservationChart(obs, `obsChart-${stepIndex}-${obsIndex}`);
            }
        });
    }
    
    hasTimeseries(obs) {
        if (!obs || typeof obs !== 'object') return false;
        
        if (obs.values && typeof obs.values === 'object') {
            return Object.values(obs.values).some(v => Array.isArray(v) && v.length > 1);
        }
        if (obs.metrics && typeof obs.metrics === 'object') {
            return Object.values(obs.metrics).some(v => Array.isArray(v) && v.length > 1);
        }
        return false;
    }
    
    createObservationChart(obs, canvasId) {
        const canvas = document.getElementById(canvasId);
        if (!canvas) return;
        
        if (this.charts[canvasId]) {
            this.charts[canvasId].destroy();
        }
        
        const datasets = [];
        const colors = [
            'rgb(88, 166, 255)',
            'rgb(63, 185, 80)',
            'rgb(248, 81, 73)',
            'rgb(210, 153, 34)',
            'rgb(163, 113, 247)',
            'rgb(57, 197, 207)'
        ];
        
        let dataSource = obs.values || obs.metrics;
        if (!dataSource) return;
        
        let colorIndex = 0;
        for (const [key, values] of Object.entries(dataSource)) {
            if (Array.isArray(values) && values.length > 1 && typeof values[0] === 'number') {
                datasets.push({
                    label: key,
                    data: values,
                    borderColor: colors[colorIndex % colors.length],
                    backgroundColor: colors[colorIndex % colors.length] + '20',
                    tension: 0.3,
                    fill: true
                });
                colorIndex++;
            }
        }
        
        if (datasets.length === 0) return;
        
        const maxLen = Math.max(...datasets.map(d => d.data.length));
        const labels = Array.from({ length: maxLen }, (_, i) => i);
        
        this.charts[canvasId] = new Chart(canvas, {
            type: 'line',
            data: { labels, datasets },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: {
                        position: 'bottom',
                        labels: { color: '#8b949e', boxWidth: 12 }
                    }
                },
                scales: {
                    x: { grid: { color: '#21262d' }, ticks: { color: '#8b949e' } },
                    y: { grid: { color: '#21262d' }, ticks: { color: '#8b949e' } }
                }
            }
        });
    }
    
    // =====================
    // Utilities
    // =====================
    
    formatObservation(obs) {
        if (obs === null || obs === undefined) return 'null';
        if (typeof obs === 'string') return this.escapeHtml(obs);
        return this.escapeHtml(JSON.stringify(obs, null, 2));
    }
    
    formatTimestamp(isoString) {
        if (!isoString) return 'N/A';
        try {
            return new Date(isoString).toLocaleTimeString();
        } catch {
            return isoString;
        }
    }
    
    escapeHtml(text) {
        if (typeof text !== 'string') text = String(text);
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }
}

// Initialize app
let app;
document.addEventListener('DOMContentLoaded', () => {
    app = new AgentUI();
});
