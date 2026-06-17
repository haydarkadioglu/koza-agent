/* MCP Servers UI Logic */

function loadMcpServers() {
    const list = document.getElementById('mcp-servers-list');
    if (!list) return;
    
    list.innerHTML = '<div style="padding: 20px; text-align: center; color: var(--text-muted);"><i class="fa-solid fa-spinner fa-spin"></i> ' + (currentLanguage === 'tr' ? 'Yükleniyor...' : 'Loading...') + '</div>';
    
    if (window.pywebview && window.pywebview.api && window.pywebview.api.get_mcp_servers) {
        window.pywebview.api.get_mcp_servers().then(res => {
            if (res.status === 'success') {
                list.innerHTML = '';
                const servers = res.data || [];
                
                if (servers.length === 0) {
                    list.innerHTML = `<div style="padding: 20px; text-align: center; color: var(--text-muted);">${currentLanguage === 'tr' ? 'Kayıtlı sunucu bulunamadı.' : 'No servers registered.'}</div>`;
                    return;
                }
                
                servers.forEach(url => {
                    const row = document.createElement('div');
                    row.className = 'custom-list-item';
                    row.innerHTML = `
                        <div class="list-item-content">
                            <strong>${escapeHtml(url)}</strong>
                            <div class="list-item-sub">HTTP Server</div>
                        </div>
                        <div class="list-item-actions">
                            <button class="btn btn-secondary btn-sm" onclick="mcpGetTools('${escapeHtml(url)}')"><i class="fa-solid fa-terminal"></i> Tools</button>
                            <button class="btn btn-danger btn-sm" onclick="removeMcpServer('${escapeHtml(url)}')"><i class="fa-solid fa-trash-can"></i></button>
                        </div>
                    `;
                    list.appendChild(row);
                });
            } else {
                list.innerHTML = `<div style="color: var(--color-red); padding: 10px;">Error: ${res.message}</div>`;
            }
        });
    } else {
        list.innerHTML = `<div style="padding: 20px; text-align: center; color: var(--color-red);">API not ready or missing.</div>`;
    }
}

function addMcpServer() {
    const urlInput = document.getElementById('new-mcp-server-url');
    if (!urlInput) return;
    
    let url = urlInput.value.trim();
    if (!url) return;
    
    if (window.pywebview && window.pywebview.api && window.pywebview.api.add_mcp_server) {
        const btn = event.currentTarget;
        const ogHtml = btn.innerHTML;
        btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i>';
        btn.disabled = true;
        
        window.pywebview.api.add_mcp_server(url).then(res => {
            btn.innerHTML = ogHtml;
            btn.disabled = false;
            
            if (res.status === 'success') {
                urlInput.value = '';
                loadMcpServers();
            } else {
                alert("Failed to add MCP server: " + res.message);
            }
        }).catch(err => {
            btn.innerHTML = ogHtml;
            btn.disabled = false;
            alert("Error: " + err);
        });
    }
}

function removeMcpServer(url) {
    if (confirm(`Remove MCP server '${url}'?`)) {
        if (window.pywebview && window.pywebview.api && window.pywebview.api.delete_mcp_server) {
            window.pywebview.api.delete_mcp_server(url).then(res => {
                if (res.status === 'success') {
                    loadMcpServers();
                } else {
                    alert("Failed to remove: " + res.message);
                }
            });
        }
    }
}

function mcpGetTools(url) {
    const explorer = document.getElementById('mcp-tools-explorer');
    const title = document.getElementById('mcp-tools-explorer-title');
    const consoleDiv = document.getElementById('mcp-tools-console');
    
    explorer.style.display = 'block';
    title.innerText = `Tools on ${url}`;
    consoleDiv.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Fetching...';
    
    if (window.pywebview && window.pywebview.api && window.pywebview.api.test_mcp_connection) {
        window.pywebview.api.test_mcp_connection(url).then(res => {
            if (res.status === 'success') {
                consoleDiv.innerHTML = `<pre style="white-space: pre-wrap; font-family: 'Fira Code', monospace; font-size: 11px; margin: 0; color: #A3E2FF;">${escapeHtml(res.message)}</pre>`;
            } else {
                consoleDiv.innerHTML = `<span style="color: var(--color-red);">Error: ${escapeHtml(res.message)}</span>`;
            }
        });
    }
}
