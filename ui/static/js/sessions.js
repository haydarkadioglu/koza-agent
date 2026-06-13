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
    showConfirmModal(confText, () => {
        window.pywebview.api.delete_session(sessId).then(res => {
            if (res && res.status === 'success') {
                loadSessions();
                if (window.activeSessionId === sessId) {
                    const messages = document.getElementById('chat-messages');
                    if (messages) messages.innerHTML = '';
                    document.getElementById('session-title-header').innerText = 'New Session';
                    window.activeSessionId = null;
                }
            }
        });
    });
}
