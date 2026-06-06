// Global variables
let activeTab = 'chat';
let isProcessing = false;
let currentToolCard = null;
let currentBubble = null;
let currentLanguage = 'en';

// Localization Dictionary
const LOCALIZATION = {
    en: {
        "brand-sub": "AUTONOMOUS AI AGENT",
        "nav-chat": "Chat",
        "nav-kanban": "Kanban",
        "nav-sessions": "Sessions",
        "nav-settings": "Settings",
        "status-ready": "Connected",
        "chat-title": "Chat",
        "chat-subtitle": "Interact with Koza Agent and command it to perform actions.",
        "chat-reset": "Clear History",
        "welcome-title": "I am Koza. How can I help you?",
        "welcome-text": "I can read files, write and run tests, search the web, or update the Kanban board.",
        "suggest-1": "Explore project structure",
        "suggest-2": "Add Kanban task",
        "suggest-3": "Write code",
        "thinking": "Thinking...",
        "kanban-title": "Kanban Board",
        "kanban-subtitle": "Track tasks and drag them to update their current state.",
        "kanban-new": "New Task",
        "col-todo": "TODO",
        "col-progress": "IN PROGRESS",
        "col-done": "DONE",
        "sessions-title": "Session History",
        "sessions-subtitle": "View and restore previous conversation sessions.",
        "settings-title": "Settings",
        "settings-subtitle": "Configure LLM providers, model preferences, keys, and advanced options.",
        "card-primary": "Primary LLM",
        "label-provider": "Provider",
        "label-model": "Model",
        "btn-google-login": "Login with Google",
        "btn-browser-login": "Browser Session Login",
        "card-fallback": "Fallback LLM",
        "fallback-enable": "Enable Fallback Provider",
        "label-fallback-provider": "Fallback Provider",
        "label-fallback-model": "Fallback Model",
        "card-messaging": "Messaging Integration",
        "card-general": "General & Voice",
        "tool-approval": "Require approval for non-safe tools",
        "auto-test": "Run automatic tests in Coding Mode",
        "voice-enable": "Enable Voice Mode",
        "modal-task-title": "Create New Task",
        "task-title-label": "Title",
        "task-desc-label": "Description",
        "btn-cancel": "Cancel",
        "btn-save": "Save",
        "perm-title": "Tool Execution Permission",
        "perm-prompt": "Koza Agent wants to execute the following tool:",
        "btn-deny": "Deny",
        "btn-allow": "Allow"
    },
    tr: {
        "brand-sub": "OTONOM YAPAY ZEKA AJANI",
        "nav-chat": "Sohbet",
        "nav-kanban": "Kanban",
        "nav-sessions": "Oturumlar",
        "nav-settings": "Ayarlar",
        "status-ready": "Bağlantı Hazır",
        "chat-title": "Sohbet",
        "chat-subtitle": "Koza Agent ile etkileşime geçin ve görevleri yerine getirmesini isteyin.",
        "chat-reset": "Sohbeti Temizle",
        "welcome-title": "Ben Koza. Nasıl yardımcı olabilirim?",
        "welcome-text": "Dosyaları okuyabilir, kod yazıp test edebilir, web'de araştırma yapabilir veya Kanban panosunu güncelleyebilirim.",
        "suggest-1": "Proje yapısını incele",
        "suggest-2": "Kanban görevi ekle",
        "suggest-3": "Asal sayı bulan kod",
        "thinking": "Düşünülüyor...",
        "kanban-title": "Kanban Panosu",
        "kanban-subtitle": "Görevleri takip edin ve sürükleyerek durumlarını güncelleyin.",
        "kanban-new": "Yeni Görev",
        "col-todo": "YAPILACAKLAR",
        "col-progress": "DEVAM EDENLER",
        "col-done": "TAMAMLANANLAR",
        "sessions-title": "Oturum Geçmişi",
        "sessions-subtitle": "Daha önceki sohbet oturumlarınızı görüntüleyin ve yükleyin.",
        "settings-title": "Ayarlar",
        "settings-subtitle": "LLM Sağlayıcısını, model tercihlerini, anahtarları ve gelişmiş özellikleri yapılandırın.",
        "card-primary": "Aktif Sağlayıcı ve Model",
        "label-provider": "Sağlayıcı (Provider)",
        "label-model": "Model",
        "btn-google-login": "Google ile Bağlan",
        "btn-browser-login": "Tarayıcı Oturumu Aç (Playwright)",
        "card-fallback": "Yedek LLM (Fallback)",
        "fallback-enable": "Yedek Sağlayıcıyı Aktifleştir",
        "label-fallback-provider": "Yedek Sağlayıcı",
        "label-fallback-model": "Yedek Model",
        "card-messaging": "Mesajlaşma Entegrasyonları",
        "card-general": "Genel ve Ses",
        "tool-approval": "Güvenli olmayan araçlarda onay iste",
        "auto-test": "Kodlama Modunda testleri otomatik çalıştır",
        "voice-enable": "Ses Modunu Aktifleştir",
        "modal-task-title": "Yeni Görev Oluştur",
        "task-title-label": "Başlık",
        "task-desc-label": "Açıklama",
        "btn-cancel": "İptal",
        "btn-save": "Kaydet",
        "perm-title": "Araç Çalıştırma İzni",
        "perm-prompt": "Koza Agent aşağıdaki aracı çalıştırmak istiyor:",
        "btn-deny": "Reddet",
        "btn-allow": "İzin Ver"
    }
};

// Wait for pywebview to initialize
window.addEventListener('pywebviewready', () => {
    console.log('pywebview bridge ready!');
    
    // Restore language preference
    const savedLang = localStorage.getItem('koza_gui_lang');
    if (savedLang) {
        currentLanguage = savedLang;
        document.getElementById('setting-lang').value = savedLang;
    }
    applyLocalization();
    loadInitialData();
});

function applyLocalization() {
    const dict = LOCALIZATION[currentLanguage] || LOCALIZATION['en'];
    document.querySelectorAll('[data-localize]').forEach(el => {
        const key = el.getAttribute('data-localize');
        if (dict[key]) {
            el.innerText = dict[key];
        }
    });
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
}

function fillInput(text) {
    const input = document.getElementById('chat-input');
    input.value = text;
    input.focus();
}

/* Chat functionality */
function handleInputKey(event) {
    if (event.key === 'Enter' && !event.shiftKey) {
        event.preventDefault();
        if (isProcessing) {
            interruptChat();
        } else {
            sendMessage();
        }
    }
}

function sendMessage() {
    const input = document.getElementById('chat-input');
    const message = input.value.trim();
    if (!message || isProcessing) return;

    input.value = '';
    isProcessing = true;
    
    const welcome = document.querySelector('.welcome-box');
    if (welcome) welcome.remove();

    appendMessageBubble('user', message);
    
    document.getElementById('stream-status').style.display = 'flex';
    document.getElementById('status-text').innerText = LOCALIZATION[currentLanguage].thinking;
    
    window.pywebview.api.send_chat_message(message).then(res => {
        console.log('Chat stream started:', res);
    });
}

function appendMessageBubble(role, content) {
    const chatMsgs = document.getElementById('chat-messages');
    
    const messageDiv = document.createElement('div');
    messageDiv.classList.add('message', role);
    
    const label = document.createElement('div');
    label.classList.add('message-label');
    label.innerText = role === 'user' ? (currentLanguage === 'tr' ? 'Siz' : 'You') : 'Koza';
    
    const bubble = document.createElement('div');
    bubble.classList.add('message-bubble');
    bubble.innerHTML = formatMarkdown(content);
    
    messageDiv.appendChild(label);
    messageDiv.appendChild(bubble);
    chatMsgs.appendChild(messageDiv);
    chatMsgs.scrollTop = chatMsgs.scrollHeight;
    
    if (role === 'agent') {
        currentBubble = bubble;
    }
}

function formatMarkdown(text) {
    if (!text) return '';
    let formatted = text.replace(/```([\w]*)\n([\s\S]*?)```/g, (match, lang, code) => {
        return `<pre><code class="language-${lang}">${escapeHtml(code.trim())}</code></pre>`;
    });
    formatted = formatted.replace(/`([^`]+)`/g, '<code>$1</code>');
    formatted = formatted.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
    formatted = formatted.replace(/\n/g, '<br>');
    return formatted;
}

function escapeHtml(text) {
    return text
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#039;");
}

/* Event receiver from Python stream_chat */
function receiveChatEvent(event) {
    console.log('Stream event received:', event);
    const chatMsgs = document.getElementById('chat-messages');
    
    if (event.type === 'thinking') {
        document.getElementById('status-text').innerText = LOCALIZATION[currentLanguage].thinking;
    } 
    else if (event.type === 'text') {
        document.getElementById('stream-status').style.display = 'none';
        if (!currentBubble) {
            appendMessageBubble('agent', '');
        }
        currentBubble.innerHTML = formatMarkdown((currentBubble.getAttribute('data-raw') || '') + event.token);
        currentBubble.setAttribute('data-raw', (currentBubble.getAttribute('data-raw') || '') + event.token);
        chatMsgs.scrollTop = chatMsgs.scrollHeight;
    } 
    else if (event.type === 'tool_start') {
        currentToolCard = document.createElement('div');
        currentToolCard.classList.add('tool-run-card');
        
        const header = document.createElement('div');
        header.classList.add('tool-header-row');
        
        const nameSpan = document.createElement('span');
        nameSpan.innerHTML = `<i class="fa-solid fa-gear fa-spin"></i> Tool: <strong>${event.name}</strong>`;
        
        const durationSpan = document.createElement('span');
        durationSpan.innerText = currentLanguage === 'tr' ? 'Çalışıyor...' : 'Running...';
        durationSpan.classList.add('tool-duration');
        
        header.appendChild(nameSpan);
        header.appendChild(durationSpan);
        currentToolCard.appendChild(header);
        
        const argsPre = document.createElement('pre');
        argsPre.classList.add('tool-output');
        argsPre.innerText = `Args: ${JSON.stringify(event.args, null, 2)}`;
        currentToolCard.appendChild(argsPre);
        
        chatMsgs.appendChild(currentToolCard);
        chatMsgs.scrollTop = chatMsgs.scrollHeight;
        currentBubble = null;
    } 
    else if (event.type === 'tool_done') {
        if (currentToolCard) {
            const durationSpan = currentToolCard.querySelector('.tool-duration');
            if (durationSpan) durationSpan.innerText = `${event.elapsed.toFixed(2)}s`;
            
            const icon = currentToolCard.querySelector('.fa-gear');
            if (icon) {
                icon.classList.remove('fa-gear', 'fa-spin');
                icon.classList.add('fa-check-double');
            }
            
            const outputPre = currentToolCard.querySelector('.tool-output');
            if (outputPre) {
                outputPre.innerText += `\n\nResult:\n${event.result}`;
            }
        }
        currentToolCard = null;
        currentBubble = null;
    } 
    else if (event.type === 'tool_denied') {
        if (currentToolCard) {
            const durationSpan = currentToolCard.querySelector('.tool-duration');
            if (durationSpan) durationSpan.innerText = 'Denied';
            
            const icon = currentToolCard.querySelector('.fa-gear');
            if (icon) {
                icon.classList.remove('fa-gear', 'fa-spin');
                icon.classList.add('fa-circle-xmark');
            }
        }
        currentToolCard = null;
        currentBubble = null;
    }
    else if (event.type === 'interrupted') {
        appendMessageBubble('agent', '*Interrupted.*');
        finishProcessing();
    }
    else if (event.type === 'done') {
        finishProcessing();
    }
}

function finishProcessing() {
    isProcessing = false;
    currentBubble = null;
    currentToolCard = null;
    document.getElementById('stream-status').style.display = 'none';
}

function interruptChat() {
    window.pywebview.api.interrupt_chat().then(() => {
        finishProcessing();
    });
}

function resetChat() {
    const confText = currentLanguage === 'tr' ? 'Sohbet geçmişini sıfırlamak istiyor musunuz?' : 'Do you want to reset conversation history?';
    if (confirm(confText)) {
        window.pywebview.api.reset_chat().then(() => {
            const chatMsgs = document.getElementById('chat-messages');
            chatMsgs.innerHTML = `
                <div class="welcome-box">
                    <i class="fa-solid fa-robot welcome-icon"></i>
                    <h3>${LOCALIZATION[currentLanguage]['welcome-title']}</h3>
                    <p>${LOCALIZATION[currentLanguage]['welcome-text']}</p>
                </div>
            `;
            finishProcessing();
        });
    }
}

/* Tool Permission Dialog handling */
function requestToolPermission(payload) {
    document.getElementById('perm-tool-name').innerText = payload.name;
    document.getElementById('perm-tool-args').innerText = JSON.stringify(payload.args, null, 2);
    document.getElementById('permission-modal').classList.add('active');
}

function resolvePermission(allowed) {
    document.getElementById('permission-modal').classList.remove('active');
    window.pywebview.api.resolve_permission(allowed);
}

/* Kanban Board Logic */
function loadKanbanTasks() {
    window.pywebview.api.get_kanban_tasks().then(response => {
        if (response.status === 'success') {
            const tasks = response.data;
            document.getElementById('cards-todo').innerHTML = '';
            document.getElementById('cards-in_progress').innerHTML = '';
            document.getElementById('cards-done').innerHTML = '';
            
            let counts = { todo: 0, in_progress: 0, done: 0 };
            
            tasks.forEach(task => {
                const card = document.createElement('div');
                card.classList.add('kanban-card');
                card.setAttribute('draggable', 'true');
                card.setAttribute('id', `task-${task.id}`);
                card.setAttribute('ondragstart', 'dragTask(event)');
                
                card.innerHTML = `
                    <h4>${escapeHtml(task.title)}</h4>
                    <p>${escapeHtml(task.description || '')}</p>
                    <div class="kanban-card-footer">
                        <button class="delete-task-btn" onclick="deleteTask(${task.id})">
                            <i class="fa-solid fa-trash"></i>
                        </button>
                    </div>
                `;
                
                const colId = task.column === 'todo' || task.column === 'in_progress' || task.column === 'done' ? task.column : 'todo';
                document.getElementById(`cards-${colId}`).appendChild(card);
                counts[colId]++;
            });
            
            document.getElementById('count-todo').innerText = counts.todo;
            document.getElementById('count-in_progress').innerText = counts.in_progress;
            document.getElementById('count-done').innerText = counts.done;
        }
    });
}

function allowDrop(ev) {
    ev.preventDefault();
}

function dragTask(ev) {
    ev.dataTransfer.setData('text/plain', ev.target.id);
}

function dropTask(ev, column) {
    ev.preventDefault();
    const data = ev.dataTransfer.getData('text/plain');
    const card = document.getElementById(data);
    const taskId = data.split('-')[1];
    document.getElementById(`cards-${column}`).appendChild(card);
    window.pywebview.api.move_kanban_task(taskId, column).then(res => {
        loadKanbanTasks();
    });
}

function openNewTaskModal() {
    document.getElementById('task-title').value = '';
    document.getElementById('task-desc').value = '';
    document.getElementById('task-modal').classList.add('active');
}

function closeTaskModal() {
    document.getElementById('task-modal').classList.remove('active');
}

function submitNewTask() {
    const title = document.getElementById('task-title').value.trim();
    const desc = document.getElementById('task-desc').value.trim();
    if (!title) {
        alert(currentLanguage === 'tr' ? 'Lütfen başlık girin.' : 'Please enter a title.');
        return;
    }
    window.pywebview.api.create_kanban_task(title, desc, 'todo').then(res => {
        closeTaskModal();
        loadKanbanTasks();
    });
}

function deleteTask(taskId) {
    const confText = currentLanguage === 'tr' ? 'Bu görevi silmek istiyor musunuz?' : 'Do you want to delete this task?';
    if (confirm(confText)) {
        window.pywebview.api.delete_kanban_task(taskId).then(res => {
            loadKanbanTasks();
        });
    }
}

/* Sessions tab logic */
function loadSessions() {
    window.pywebview.api.get_sessions().then(response => {
        if (response.status === 'success') {
            const list = document.getElementById('sessions-list');
            list.innerHTML = '';
            
            if (response.data.length === 0) {
                const emptyText = currentLanguage === 'tr' ? 'Kayıtlı oturum bulunamadı.' : 'No saved sessions found.';
                list.innerHTML = `<p class="text-center" style="color:var(--text-muted); padding:40px;">${emptyText}</p>`;
                return;
            }
            
            response.data.forEach(sess => {
                const date = new Date(sess.started * 1000).toLocaleString(currentLanguage === 'tr' ? 'tr-TR' : 'en-US');
                const btnLoadText = currentLanguage === 'tr' ? 'Yükle' : 'Load';
                const row = document.createElement('div');
                row.classList.add('session-row');
                row.innerHTML = `
                    <div class="session-meta">
                        <h4>${escapeHtml(sess.title)}</h4>
                        <span><i class="fa-regular fa-clock"></i> ${date}</span>
                    </div>
                    <div class="session-actions">
                        <button class="btn btn-secondary btn-sm" onclick="loadSessionChat(${sess.id})">
                            <i class="fa-solid fa-folder-open"></i> ${btnLoadText}
                        </button>
                        <button class="btn btn-danger btn-sm" onclick="deleteSession(${sess.id})">
                            <i class="fa-solid fa-trash-can"></i>
                        </button>
                    </div>
                `;
                list.appendChild(row);
            });
        }
    });
}

function loadSessionChat(sessId) {
    window.pywebview.api.load_session(sessId).then(response => {
        if (response.status === 'success') {
            const chatMsgs = document.getElementById('chat-messages');
            chatMsgs.innerHTML = '';
            response.data.forEach(msg => {
                appendMessageBubble(msg.role === 'user' ? 'user' : 'agent', msg.content);
            });
            switchTab('chat');
        }
    });
}

function deleteSession(sessId) {
    const confText = currentLanguage === 'tr' ? 'Bu oturumu kalıcı olarak silmek istiyor musunuz?' : 'Do you want to permanently delete this session?';
    if (confirm(confText)) {
        window.pywebview.api.delete_session(sessId).then(res => {
            loadSessions();
        });
    }
}

/* Settings configuration & dynamic providers */
let providersMetadata = { providers: [], models: {}, needs_key: [] };

function loadSettings() {
    window.pywebview.api.get_providers_metadata().then(metaRes => {
        if (metaRes.status === 'success') {
            providersMetadata.providers = metaRes.providers;
            providersMetadata.models = metaRes.models;
            providersMetadata.needs_key = metaRes.needs_key || [];
        }
        
        window.pywebview.api.get_config().then(cfg => {
            // Set languages dropdown
            document.getElementById('setting-lang').value = currentLanguage;
            
            // Populators
            populateProvidersDropdown(cfg.provider);
            populateModelsDropdown(cfg.provider, cfg.model);
            updateApiKeyFieldVisibility(cfg.provider, cfg);
            
            // Fallbacks setup
            const fbEnabled = !!cfg.fallback_provider;
            document.getElementById('setting-fallback-enable').checked = fbEnabled;
            toggleFallback(fbEnabled, cfg);
            
            // Other settings
            document.getElementById('setting-tg-token').value = cfg.telegram_token || (cfg.messaging && cfg.messaging.telegram && cfg.messaging.telegram.token) || '';
            document.getElementById('setting-tg-chat').value = (cfg.messaging && cfg.messaging.telegram && cfg.messaging.telegram.chat_id) || '';
            document.getElementById('setting-twilio-sid').value = (cfg.messaging && cfg.messaging.twilio && cfg.messaging.twilio.account_sid) || '';
            document.getElementById('setting-twilio-auth').value = (cfg.messaging && cfg.messaging.twilio && cfg.messaging.twilio.auth_token) || '';
            
            document.getElementById('setting-tool-approval').checked = !!cfg.tool_approval;
            document.getElementById('setting-coding-autotest').checked = !!(cfg.coding_mode && cfg.coding_mode.auto_test);
            document.getElementById('setting-voice-enable').checked = !!(cfg.voice && cfg.voice.enabled);
        });
    });
}

function populateProvidersDropdown(selectedProvider) {
    const provSelect = document.getElementById('setting-provider');
    provSelect.innerHTML = '';
    
    providersMetadata.providers.forEach(p => {
        const opt = document.createElement('option');
        opt.value = p;
        opt.innerText = p.toUpperCase();
        if (p === selectedProvider) opt.selected = true;
        provSelect.appendChild(opt);
    });
}

function populateModelsDropdown(provider, selectedModel) {
    const modelSelect = document.getElementById('setting-model');
    const customInput = document.getElementById('setting-model-custom');
    modelSelect.innerHTML = '';
    
    let lookupKey = provider;
    if (!providersMetadata.models[lookupKey]) {
        lookupKey = Object.keys(providersMetadata.models).find(k => k.startsWith(provider)) || provider;
    }
    
    const models = providersMetadata.models[lookupKey] || [];
    models.forEach(m => {
        const opt = document.createElement('option');
        opt.value = m;
        opt.innerText = m;
        if (m === selectedModel) opt.selected = true;
        modelSelect.appendChild(opt);
    });
    
    const otherOpt = document.createElement('option');
    otherOpt.value = 'other';
    otherOpt.innerText = currentLanguage === 'tr' ? 'Diğer / Elle Gir...' : 'Other / Custom...';
    
    const isCustom = selectedModel && !models.includes(selectedModel);
    if (isCustom) {
        otherOpt.selected = true;
        customInput.value = selectedModel;
        customInput.style.display = 'block';
    } else {
        customInput.style.display = 'none';
    }
    modelSelect.appendChild(otherOpt);
}

function updateApiKeyFieldVisibility(provider, cfg) {
    const apiKeyGroup = document.getElementById('group-api-key');
    const oauthGroup = document.getElementById('group-oauth-actions');
    const label = document.getElementById('label-api-key');
    const keyInput = document.getElementById('setting-api-key');
    
    // Check key requirement
    const needsKey = providersMetadata.needs_key.includes(provider) || provider.includes('api');
    
    if (needsKey) {
        apiKeyGroup.style.display = 'block';
        label.innerText = `${provider.toUpperCase()} API Key`;
        // Load key from config if present
        const pKey = cfg.providers && cfg.providers[provider] ? cfg.providers[provider].api_key : '';
        keyInput.value = pKey || '';
    } else {
        apiKeyGroup.style.display = 'none';
    }
    
    // Toggle OAuth/Browser helper logins for Google and Gemini
    if (provider.includes('gemini') || provider.includes('google')) {
        oauthGroup.style.display = 'flex';
    } else {
        oauthGroup.style.display = 'none';
    }
}

function onProviderChanged(provider) {
    window.pywebview.api.update_config_value('root', 'provider', provider).then(res => {
        let lookupKey = provider;
        if (!providersMetadata.models[lookupKey]) {
            lookupKey = Object.keys(providersMetadata.models).find(k => k.startsWith(provider)) || provider;
        }
        const defaultModel = (providersMetadata.models[lookupKey] || [''])[0];
        
        window.pywebview.api.update_config_value('root', 'model', defaultModel).then(() => {
            window.pywebview.api.get_config().then(cfg => {
                populateModelsDropdown(provider, defaultModel);
                updateApiKeyFieldVisibility(provider, cfg);
            });
        });
    });
}

function onModelChanged(model) {
    const customInput = document.getElementById('setting-model-custom');
    if (model === 'other') {
        customInput.style.display = 'block';
        customInput.value = '';
        customInput.focus();
    } else {
        customInput.style.display = 'none';
        window.pywebview.api.update_config_value('root', 'model', model);
    }
}

function onCustomModelChanged(customModel) {
    if (customModel.trim()) {
        window.pywebview.api.update_config_value('root', 'model', customModel.trim());
    }
}

function onApiKeyChanged(key) {
    if (!key) return;
    const provider = document.getElementById('setting-provider').value;
    updateNestedConfig(`providers.${provider}.api_key`, key);
}

/* Fallback Provider logic */
function toggleFallback(checked, cfg) {
    const fields = document.getElementById('fallback-fields');
    if (checked) {
        fields.style.display = 'block';
        // Populate fallback options
        populateFallbackDropdowns(cfg);
    } else {
        fields.style.display = 'none';
        // Disable fallback in config by clearing variables
        window.pywebview.api.update_config_value('root', 'fallback_provider', '');
        window.pywebview.api.update_config_value('root', 'fallback_model', '');
    }
}

function populateFallbackDropdowns(cfg) {
    const fbProvSelect = document.getElementById('setting-fallback-provider');
    fbProvSelect.innerHTML = '';
    
    providersMetadata.providers.forEach(p => {
        const opt = document.createElement('option');
        opt.value = p;
        opt.innerText = p.toUpperCase();
        if (cfg && p === cfg.fallback_provider) opt.selected = true;
        fbProvSelect.appendChild(opt);
    });
    
    // Set active model dropdown for fallback
    const selectedFb = (cfg && cfg.fallback_provider) || providersMetadata.providers[0];
    onFallbackProviderChanged(selectedFb, cfg ? cfg.fallback_model : null, cfg);
}

function onFallbackProviderChanged(provider, selectedModel, cfg) {
    const modelSelect = document.getElementById('setting-fallback-model');
    modelSelect.innerHTML = '';
    
    let lookupKey = provider;
    if (!providersMetadata.models[lookupKey]) {
        lookupKey = Object.keys(providersMetadata.models).find(k => k.startsWith(provider)) || provider;
    }
    
    const models = providersMetadata.models[lookupKey] || [];
    models.forEach(m => {
        const opt = document.createElement('option');
        opt.value = m;
        opt.innerText = m;
        if (m === selectedModel) opt.selected = true;
        modelSelect.appendChild(opt);
    });
    
    // Save to config
    window.pywebview.api.update_config_value('root', 'fallback_provider', provider);
    if (models.length > 0) {
        const defModel = selectedModel || models[0];
        window.pywebview.api.update_config_value('root', 'fallback_model', defModel);
    }
    
    // Fallback key input display
    const fbKeyGroup = document.getElementById('group-fallback-key');
    const fbKeyInput = document.getElementById('setting-fallback-key');
    if (providersMetadata.needs_key.includes(provider)) {
        fbKeyGroup.style.display = 'block';
        if (cfg && cfg.providers && cfg.providers[provider]) {
            fbKeyInput.value = cfg.providers[provider].api_key || '';
        }
    } else {
        fbKeyGroup.style.display = 'none';
    }
}

function onFallbackModelChanged(model) {
    window.pywebview.api.update_config_value('root', 'fallback_model', model);
}

function onFallbackKeyChanged(key) {
    const provider = document.getElementById('setting-fallback-provider').value;
    updateNestedConfig(`providers.${provider}.api_key`, key);
}

/* OAuth & Browser session triggers */
function triggerGoogleOAuth() {
    alert(currentLanguage === 'tr' ? 'Tarayıcıda Google OAuth giriş penceresi açılıyor. Lütfen takip edin...' : 'Opening Google OAuth login in browser. Please follow the instructions...');
    window.pywebview.api.run_google_oauth();
}

function triggerGeminiBrowserLogin() {
    alert(currentLanguage === 'tr' ? 'Otomatik tarayıcı oturum açma aracı başlatılıyor (Playwright)...' : 'Starting Playwright automatic browser login...');
    window.pywebview.api.run_gemini_browser_login();
}

function onOAuthCompleted(res) {
    if (res.status === 'success') {
        alert(currentLanguage === 'tr' ? 'Google OAuth bağlantısı başarıyla tamamlandı!' : 'Google OAuth login completed successfully!');
    } else {
        alert(currentLanguage === 'tr' ? 'Giriş başarısız veya iptal edildi.' : 'Login failed or was cancelled.');
    }
}

function onGeminiBrowserLoginCompleted(res) {
    if (res.status === 'success') {
        alert(currentLanguage === 'tr' ? 'Gemini tarayıcı oturumu başarıyla kaydedildi!' : 'Gemini browser session saved successfully!');
    } else {
        alert(currentLanguage === 'tr' ? 'Tarayıcı oturum kaydı başarısız.' : 'Browser login failed.');
    }
}

/* Twilio, voice and general config updates */
function updateNestedConfig(dotPath, value) {
    window.pywebview.api.update_nested_config(dotPath, value).then(res => {
        console.log('Nested config updated:', res);
    });
}

function updateGeneralConfig(section, key, value) {
    window.pywebview.api.update_config_value(section, key, value).then(res => {
        console.log('Config updated:', res);
    });
}

function toggleVoice(enabled) {
    updateGeneralConfig('voice', 'enabled', enabled);
}
