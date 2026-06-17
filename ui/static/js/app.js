// Wait for pywebview to initialize
window.addEventListener('pywebviewready', () => {
    console.log('pywebview bridge ready!');
    
    // Bind keydown events to chat-input textarea
    const chatInput = document.getElementById('chat-input');
    if (chatInput) {
        chatInput.addEventListener('keydown', handleInputKey);
    }
    
    // Restore language preference
    const savedLang = localStorage.getItem('koza_gui_lang');
    if (savedLang) {
        currentLanguage = savedLang;
        document.getElementById('setting-lang').value = savedLang;
    }
    applyLocalization();
    loadInitialData();
    
    // Initial daemon status check and periodic updates
    if (typeof checkDaemonStatus === 'function') {
        checkDaemonStatus();
        setInterval(checkDaemonStatus, 5000);
    }
});

function applyLocalization() {
    const dict = LOCALIZATION[currentLanguage] || LOCALIZATION['en'];
    document.querySelectorAll('[data-localize]').forEach(el => {
        const key = el.getAttribute('data-localize');
        if (dict[key]) {
            el.innerText = dict[key];
        }
    });
    document.querySelectorAll('[data-localize-placeholder]').forEach(el => {
        const key = el.getAttribute('data-localize-placeholder');
        if (dict[key]) {
            el.placeholder = dict[key];
        }
    });
    
    // Update dynamic daemon strings
    if (typeof checkDaemonStatus === 'function') {
        checkDaemonStatus();
    }
}

function changeLanguage(lang) {
    currentLanguage = lang;
    localStorage.setItem('koza_gui_lang', lang);
    applyLocalization();
}

function loadInitialData() {
    loadKanbanTasks();
    loadSessions();
    loadSettings();
    checkApiKeyStatus();
    fetchAppVersion();
    loadInitialChatHistory();
}

function loadInitialChatHistory() {
    if (window.pywebview && window.pywebview.api && window.pywebview.api.get_chat_history) {
        window.pywebview.api.get_chat_history().then(res => {
            if (res.status === 'success' && res.messages) {
                const chatMsgs = document.getElementById('chat-messages');
                if (chatMsgs) {
                    res.messages.forEach(msg => {
                        appendMessageBubble(msg.role === 'user' ? 'user' : 'agent', msg.content);
                    });
                }
            }
        }).catch(err => console.error('Failed to load initial chat history:', err));
    }
}

function fetchAppVersion() {
    if (window.pywebview && window.pywebview.api && window.pywebview.api.get_app_version) {
        window.pywebview.api.get_app_version().then(res => {
            if (res.status === 'success') {
                const el = document.getElementById('app-version-display');
                if (el) el.innerText = 'v' + res.version;
            }
        }).catch(err => console.error('Failed to get app version:', err));
    }
}

function checkApiKeyStatus() {
    if (window.pywebview && window.pywebview.api) {
        window.pywebview.api.get_config().then(cfg => {
            const provider = cfg.provider || 'gemini';
            let hasKey = false;
            if (provider === 'gemini_browser' || provider === 'antigravity') {
                hasKey = true;
            } else {
                const key = cfg.providers && cfg.providers[provider] ? cfg.providers[provider].api_key : '';
                if (key && key.trim() !== '') hasKey = true;
            }
            const warningEl = document.getElementById('api-key-warning');
            if (warningEl) warningEl.style.display = hasKey ? 'none' : 'flex';
        });
    }
}

/* Tabs & UI Switcher */
function switchTab(tabId) {
    activeTab = tabId;
    
    document.querySelectorAll('.customization-item').forEach(btn => {
        btn.classList.remove('active');
    });
    
    const clickedBtn = document.getElementById(`custom-item-${tabId}`);
    if (clickedBtn) clickedBtn.classList.add('active');

    document.querySelectorAll('.tab-pane').forEach(pane => {
        pane.classList.remove('active');
    });
    const pane = document.getElementById(`tab-${tabId}`);
    if (pane) pane.classList.add('active');
    
    if (tabId === 'kanban') loadKanbanTasks();
    if (tabId === 'sessions') loadSessions();
    if (tabId === 'settings') loadSettings();
    if (tabId === 'skills') loadPluginsAndSkills();
    
    // Customization tabs empty loaders
    if (tabId === 'instructions') { if (typeof loadUserProfile === 'function') loadUserProfile(); }
    if (tabId === 'hooks') { if (typeof loadHooksData === 'function') loadHooksData(); }
    if (tabId === 'mcp') { if (typeof loadMcpServers === 'function') loadMcpServers(); }
}
