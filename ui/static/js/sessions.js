function loadSessions() {
    window.pywebview.api.get_sessions().then(response => {
        if (response.status === 'success') {
            window.allSessionsCache = response.data;
            const list = document.getElementById('sessions-list');
            list.innerHTML = '';
            
            if (response.data.length === 0) {
                const emptyText = currentLanguage === 'tr' ? 'Kayıtlı oturum bulunamadı.' : 'No saved sessions found.';
                list.innerHTML = `<p class="text-center" style="color:var(--text-muted); padding:40px;">${emptyText}</p>`;
                renderSidebarSessions(response.data);
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
            renderSidebarSessions(response.data);
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

function renderSidebarSessions(sessionsToRender) {
    const sidebarList = document.getElementById('sidebar-sessions-list');
    if (!sidebarList) return;
    sidebarList.innerHTML = '';
    
    if (sessionsToRender.length === 0) {
        const emptyText = currentLanguage === 'tr' ? 'Oturum yok' : 'No sessions';
        sidebarList.innerHTML = `<div style="text-align:center; padding: 20px; color: var(--text-muted); font-size: 12px;">${emptyText}</div>`;
        return;
    }
    
    const groups = { today: [], yesterday: [], previous7: [], previous30: [], older: [] };
    const now = new Date();
    const todayStr = now.toDateString();
    const yesterdayDate = new Date(now); yesterdayDate.setDate(yesterdayDate.getDate() - 1);
    const yesterdayStr = yesterdayDate.toDateString();
    const sevenDaysAgo = new Date(now); sevenDaysAgo.setDate(sevenDaysAgo.getDate() - 7);
    const thirtyDaysAgo = new Date(now); thirtyDaysAgo.setDate(thirtyDaysAgo.getDate() - 30);
    
    sessionsToRender.forEach(sess => {
        const d = new Date(sess.started * 1000);
        if (d.toDateString() === todayStr) groups.today.push(sess);
        else if (d.toDateString() === yesterdayStr) groups.yesterday.push(sess);
        else if (d > sevenDaysAgo) groups.previous7.push(sess);
        else if (d > thirtyDaysAgo) groups.previous30.push(sess);
        else groups.older.push(sess);
    });
    
    const groupLabels = {
        today: currentLanguage === 'tr' ? 'Bugün' : 'Today',
        yesterday: currentLanguage === 'tr' ? 'Dün' : 'Yesterday',
        previous7: currentLanguage === 'tr' ? 'Önceki 7 Gün' : 'Previous 7 Days',
        previous30: currentLanguage === 'tr' ? 'Önceki 30 Gün' : 'Previous 30 Days',
        older: currentLanguage === 'tr' ? 'Daha Eski' : 'Older'
    };
    
    for (const key of ['today', 'yesterday', 'previous7', 'previous30', 'older']) {
        if (groups[key].length > 0) {
            const groupDiv = document.createElement('div');
            groupDiv.className = 'session-group';
            
            const header = document.createElement('div');
            header.className = 'session-group-header';
            header.innerHTML = `<span>${groupLabels[key]}</span>`;
            
            const content = document.createElement('div');
            content.className = 'session-group-content';
            
            groups[key].forEach(sess => {
                const item = document.createElement('div');
                item.className = 'sidebar-session-item';
                item.innerHTML = `
                    <div style="white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 160px;" title="${escapeHtml(sess.title)}">${escapeHtml(sess.title)}</div>
                    <button class="btn btn-sm" onclick="deleteSession(${sess.id}); event.stopPropagation();" style="padding: 2px 6px; font-size: 12px; background: transparent; color: var(--text-muted); border: none;">
                        <i class="fa-solid fa-trash-can"></i>
                    </button>
                `;
                item.onclick = () => loadSessionChat(sess.id);
                content.appendChild(item);
            });
            
            groupDiv.appendChild(header);
            groupDiv.appendChild(content);
            sidebarList.appendChild(groupDiv);
        }
    }
}

function filterSessions(query) {
    if (!window.allSessionsCache) return;
    if (!query || query.trim() === '') {
        renderSidebarSessions(window.allSessionsCache);
        return;
    }
    const q = query.toLowerCase();
    const filtered = window.allSessionsCache.filter(sess => sess.title.toLowerCase().includes(q));
    renderSidebarSessions(filtered);
}

