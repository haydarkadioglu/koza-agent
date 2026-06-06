let agentsPollInterval = null;
let currentViewingAgentId = null;

function escapeHtml(text) {
    if (!text) return '';
    return text.toString()
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#039;");
}

function loadAgentsTasks() {
    if (!window.pywebview || !window.pywebview.api) return;
    
    window.pywebview.api.get_background_tasks().then(response => {
        if (response.status === 'success') {
            renderAgentsList(response.data);
        }
    });
}

function startAgentsPolling() {
    if (agentsPollInterval) clearInterval(agentsPollInterval);
    loadAgentsTasks();
    agentsPollInterval = setInterval(loadAgentsTasks, 3000);
}

function stopAgentsPolling() {
    if (agentsPollInterval) {
        clearInterval(agentsPollInterval);
        agentsPollInterval = null;
    }
}

// Ensure polling starts when switching to agents tab, and stops when switching away
// Hook into switchTab
const originalSwitchTab = switchTab;
switchTab = function(tabId) {
    originalSwitchTab(tabId);
    if (tabId === 'agents') {
        startAgentsPolling();
    } else {
        stopAgentsPolling();
    }
};

function renderAgentsList(tasks) {
    const grid = document.getElementById('agents-grid');
    if (!grid) return;
    
    if (!tasks || tasks.length === 0) {
        grid.innerHTML = `
            <div class="agents-empty-state" style="grid-column: 1 / -1;">
                <i class="fa-solid fa-robot"></i>
                <p>${currentLanguage === 'tr' ? 'Henüz arka plan görevi veya alt ajan yok.' : 'No background tasks or sub-agents yet.'}</p>
            </div>
        `;
        return;
    }
    
    grid.innerHTML = tasks.map(task => {
        const isRunning = task.status === 'running';
        const typeLabel = task.type === 'coding' ? 'Coding Session' : 'Sub-agent';
        
        let statusClass = `status-${task.status}`;
        let statusLabel = task.status;
        if (currentLanguage === 'tr') {
            if (task.status === 'pending') statusLabel = 'Bekliyor';
            else if (task.status === 'running') statusLabel = 'Çalışıyor';
            else if (task.status === 'done') statusLabel = 'Tamamlandı';
            else if (task.status === 'error') statusLabel = 'Hata';
            else if (task.status === 'cancelled') statusLabel = 'İptal Edildi';
        }
        
        let actionBtn = '';
        if (isRunning) {
            actionBtn = `
                <button class="btn btn-danger" onclick="cancelAgent('${task.id}')">
                    <i class="fa-solid fa-square-minus"></i> ${currentLanguage === 'tr' ? 'Durdur' : 'Stop'}
                </button>
            `;
        }
        
        return `
            <div class="agent-card ${statusClass}">
                <div class="agent-card-header">
                    <span class="agent-card-id">#${task.id}</span>
                    <span class="agent-card-type">${typeLabel}</span>
                </div>
                <div class="agent-card-goal">${escapeHtml(task.goal)}</div>
                <div class="agent-card-status-pill ${statusClass}">
                    <span class="pulse ${task.status === 'running' ? 'yellow' : (task.status === 'pending' ? 'yellow' : (task.status === 'done' ? 'green' : 'red'))}"></span>
                    ${statusLabel}
                </div>
                <div class="agent-card-meta">
                    <span>${currentLanguage === 'tr' ? 'Süre' : 'Elapsed'}: ${task.elapsed_seconds}s</span>
                    <span>${task.current_persona ? `[${task.current_persona}]` : ''}</span>
                </div>
                <div class="agent-card-actions">
                    <button class="btn btn-secondary" onclick="viewAgentLogs('${task.id}')">
                        <i class="fa-solid fa-terminal"></i> ${currentLanguage === 'tr' ? 'Günlük' : 'Logs'}
                    </button>
                    ${actionBtn}
                </div>
            </div>
        `;
    }).join('');
}

function cancelAgent(agentId) {
    const confText = currentLanguage === 'tr' ? 'Bu görevi iptal etmek istiyor musunuz?' : 'Do you want to cancel this task?';
    if (confirm(confText)) {
        window.pywebview.api.cancel_background_task(agentId).then(res => {
            loadAgentsTasks();
        });
    }
}

function viewAgentLogs(agentId) {
    currentViewingAgentId = agentId;
    document.getElementById('agent-details-modal').classList.add('active');
    document.getElementById('modal-agent-id').innerText = agentId;
    document.getElementById('agent-logs-content').textContent = currentLanguage === 'tr' ? 'Günlükler yükleniyor...' : 'Loading logs...';
    
    pollAgentLogs();
}

function pollAgentLogs() {
    if (!currentViewingAgentId) return;
    
    window.pywebview.api.get_background_task_details(currentViewingAgentId).then(response => {
        if (response.status === 'success' && currentViewingAgentId === response.data.id) {
            const data = response.data;
            const logConsole = document.getElementById('agent-logs-content');
            
            let output = `[Goal]: ${data.goal}\n[Status]: ${data.status.toUpperCase()}\n\n`;
            output += data.logs || (currentLanguage === 'tr' ? 'Günlük çıktısı yok.' : 'No log output yet.');
            
            logConsole.textContent = output;
            logConsole.scrollTop = logConsole.scrollHeight;
            
            if (data.status === 'running' || data.status === 'pending') {
                setTimeout(pollAgentLogs, 2000);
            }
        }
    });
}

function closeAgentDetailsModal() {
    document.getElementById('agent-details-modal').classList.remove('active');
    currentViewingAgentId = null;
}

window.viewAgentLogs = viewAgentLogs;

function submitManualAgent() {
    const goal = document.getElementById('manual-agent-goal').value.trim();
    if (!goal) {
        alert(currentLanguage === 'tr' ? 'Lütfen bir hedef girin.' : 'Please enter a goal.');
        return;
    }
    const mode = document.getElementById('manual-agent-mode').value;
    const caps = [];
    if (document.getElementById('manual-cap-files').checked) caps.push('files');
    if (document.getElementById('manual-cap-code').checked) caps.push('code');
    if (document.getElementById('manual-cap-browser').checked) caps.push('browser');
    if (document.getElementById('manual-cap-github').checked) caps.push('github');
    if (document.getElementById('manual-cap-devops').checked) caps.push('devops');
    
    const capabilitiesStr = caps.join(',');
    
    document.getElementById('manual-agent-goal').value = '';
    
    window.pywebview.api.start_background_task(goal, mode, "", capabilitiesStr).then(res => {
        loadAgentsTasks();
        if (res.status !== 'success') {
            alert(res.message);
        }
    });
}
