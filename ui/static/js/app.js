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
}

/* Tabs & UI Switcher */
function switchTab(tabId) {
    activeTab = tabId;
    
    document.querySelectorAll('.nav-item').forEach(btn => {
        btn.classList.remove('active');
    });
    const clickedBtn = Array.from(document.querySelectorAll('.nav-item')).find(btn => 
        btn.getAttribute('onclick').includes(tabId)
    );
    if (clickedBtn) clickedBtn.classList.add('active');

    document.querySelectorAll('.tab-pane').forEach(pane => {
        pane.classList.remove('active');
    });
    document.getElementById(`tab-${tabId}`).classList.add('active');
    
    if (tabId === 'kanban') loadKanbanTasks();
    if (tabId === 'sessions') loadSessions();
    if (tabId === 'settings') loadSettings();
    if (tabId === 'skills') loadPluginsAndSkills();
}
