// Global variables
let activeTab = 'chat';
let isProcessing = false;
let currentToolCard = null;
let currentBubble = null;
let currentLanguage = 'en';
let isDaemonActive = false;

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
        "sub-llm": "LLM & Auth",
        "sub-fallback": "Fallback LLM",
        "sub-media": "Media Gen",
        "sub-messaging": "Messaging & Sync",
        "sub-voice": "Voice & Hardware",
        "sub-skills": "Plugins & Skills",
        "sub-general": "General",
        "skills-desc": "Enable or disable built-in skill categories and external plugins. Toggling core skills updates config immediately.",
        "btn-interrupt": "Stop",
        "chat-input-placeholder": "Type a message to Koza... (Press Enter to send, Shift+Enter for new line)",
        "sec-plugins": "External Plugins",
        "sec-core-skills": "Core Built-in Skills",
        "sec-templates": "Saved Skill Templates",
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
        "btn-allow": "Allow",
        "daemon-title": "Background Services Daemon",
        "daemon-desc": "Runs background integrations (like the Telegram Bot or Scheduler). These services will keep running even after you close this GUI window.",
        "daemon-checking": "Checking...",
        "daemon-active": "Active",
        "daemon-inactive": "Inactive",
        "daemon-start": "Start",
        "daemon-stop": "Stop",
        "modal-plugin-title": "Create New Plugin",
        "plugin-name-label": "Plugin Name",
        "plugin-desc-label": "Description",
        "plugin-author-label": "Author",
        "btn-new-plugin": "New Plugin",
        "nav-agents": "Sub-agents",
        "agents-title": "Sub-agents & Background Tasks",
        "agents-subtitle": "Monitor and manage autonomous background execution sessions.",
        "btn-run-task": "Run Task",
        "btn-stop-task": "Stop Task",
        "btn-view-logs": "View Logs",
        "label-capabilities": "Capabilities",
        "run-modal-title": "Run Kanban Task",
        "nav-skills": "Skills",
        "skills-title": "Plugins & Skills",
        "self-improve-title": "Self-Evolution Loop (Curator)",
        "self-improve-desc": "Analyze conversation logs automatically in the background to discover new skills and remember user preferences.",
        "self-improve-label": "Enable Background Self-Evolution (Curator)"
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
        "sub-llm": "LLM ve Yetkilendirme",
        "sub-fallback": "Yedek LLM (Fallback)",
        "sub-media": "Medya Üretimi",
        "sub-messaging": "Mesajlaşma ve Senkronizasyon",
        "sub-voice": "Ses ve Donanım",
        "sub-skills": "Eklentiler ve Yetenekler",
        "sub-general": "Genel Ayarlar",
        "skills-desc": "Dahili yetenek kategorilerini ve harici eklentileri etkinleştirin veya devre dışı bırakın. Çekirdek yeteneklerin durumunu değiştirmek konfigürasyonu hemen günceller.",
        "btn-interrupt": "Durdur",
        "chat-input-placeholder": "Koza'ya bir mesaj yazın... (Göndermek için Enter'a, yeni satır için Shift+Enter'a basın)",
        "sec-plugins": "Harici Eklentiler",
        "sec-core-skills": "Çekirdek Dahili Yetenekler",
        "sec-templates": "Kayıtlı Görev Şablonları",
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
        "btn-allow": "İzin Ver",
        "daemon-title": "Arka Plan Servisleri (Daemon)",
        "daemon-desc": "Arka plan entegrasyonlarını (Telegram Botu veya Zamanlayıcı gibi) çalıştırır. Bu servisler bu GUI penceresini kapatsanız bile arka planda çalışmaya devam eder.",
        "daemon-checking": "Kontrol ediliyor...",
        "daemon-active": "Aktif",
        "daemon-inactive": "Pasif",
        "daemon-start": "Başlat",
        "daemon-stop": "Durdur",
        "modal-plugin-title": "Yeni Eklenti Oluştur",
        "plugin-name-label": "Eklenti Adı",
        "plugin-desc-label": "Açıklama",
        "plugin-author-label": "Yazar",
        "btn-new-plugin": "Yeni Eklenti",
        "nav-agents": "Alt Ajanlar",
        "agents-title": "Alt Ajanlar ve Arka Plan Görevleri",
        "agents-subtitle": "Otonom arka plan çalışma oturumlarını izleyin ve yönetin.",
        "btn-run-task": "Çalıştır",
        "btn-stop-task": "Durdur",
        "btn-view-logs": "Günlükleri Gör",
        "label-capabilities": "Yetenekler",
        "run-modal-title": "Kanban Görevini Çalıştır",
        "nav-skills": "Yetenekler",
        "skills-title": "Eklentiler & Yetenekler",
        "self-improve-title": "Öz-Gelişim Küratör Döngüsü",
        "self-improve-desc": "Yeni yetenekler keşfetmek ve kullanıcı tercihlerini hatırlamak için arka planda konuşma günlüklerini otomatik analiz eder.",
        "self-improve-label": "Arka Planda Öz-Gelişimi Etkinleştir (Küratör)"
    }
};

// ── CUSTOM CONFIRM MODAL ──────────────────────────────────────────────────
let customConfirmCallback = null;

function showConfirmModal(text, onConfirm) {
    const modal = document.getElementById('custom-confirm-modal');
    const textEl = document.getElementById('confirm-modal-text');
    const yesBtn = document.getElementById('confirm-modal-yes');
    
    if (modal && textEl && yesBtn) {
        textEl.innerText = text;
        customConfirmCallback = onConfirm;
        
        yesBtn.onclick = function() {
            closeConfirmModal();
            if (customConfirmCallback) customConfirmCallback();
        };
        
        modal.style.display = 'flex';
    } else {
        if (confirm(text)) onConfirm();
    }
}

function closeConfirmModal() {
    const modal = document.getElementById('custom-confirm-modal');
    if (modal) modal.style.display = 'none';
    customConfirmCallback = null;
}

function clearAllHistory() {
    showConfirmModal(
        currentLanguage === 'tr' ? 'Tüm sohbet geçmişini silmek istediğinize emin misiniz? Bu işlem geri alınamaz.' : 'Are you sure you want to delete ALL conversation history? This cannot be undone.',
        () => {
            if (window.pywebview && window.pywebview.api) {
                window.pywebview.api.clear_conversation_history().then(res => {
                    if (res && res.status === 'success') {
                        if (typeof loadSessions === 'function') loadSessions();
                        if (typeof switchTab === 'function') switchTab('chat');
                    }
                });
            }
        }
    );
}

// ── NEW SESSION WIZARD MODAL ──────────────────────────────────────────────
function openNewSessionModal() {
    const modal = document.getElementById('new-session-modal');
    if (modal) {
        modal.style.display = 'flex';
        const input = document.getElementById('wizard-chat-input');
        if (input) input.focus();
    }
}

function closeNewSessionModal() {
    const modal = document.getElementById('new-session-modal');
    if (modal) modal.style.display = 'none';
}

function startSessionFromWizard() {
    const input = document.getElementById('wizard-chat-input');
    const msg = input ? input.value.trim() : '';
    closeNewSessionModal();
    if (typeof startNewSession === 'function') {
        startNewSession(msg);
    } else if (typeof sendMessage === 'function') {
        const chatInput = document.getElementById('chat-input');
        if (chatInput) chatInput.value = msg;
        sendMessage();
    }
}

window.addEventListener('click', function(event) {
    if (event.target.classList && event.target.classList.contains('modal')) {
        event.target.style.display = "none";
    }
});
