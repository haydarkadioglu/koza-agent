/* MCP Servers UI Logic */

function loadMcpServers() {
    const list = document.getElementById('mcp-servers-list');
    if (!list) return;
    
    list.innerHTML = '<div style="padding: 20px; text-align: center; color: var(--text-muted);"><i class="fa-solid fa-spinner fa-spin"></i> ' + (currentLanguage === 'tr' ? 'Yükleniyor...' : 'Loading...') + '</div>';
    
    if (window.pywebview && window.pywebview.api && window.pywebview.api.mcp_list) {
        window.pywebview.api.mcp_list().then(res => {
            if (res.status === 'success') {
                list.innerHTML = '';
                const servers = res.servers || {};
                const serverNames = Object.keys(servers);
                
                if (serverNames.length === 0) {
                    list.innerHTML = `<div style="padding: 20px; text-align: center; color: var(--text-muted);">${currentLanguage === 'tr' ? 'Kayıtlı sunucu bulunamadı.' : 'No servers registered.'}</div>`;
                    return;
                }
                
                serverNames.forEach(name => {
                    const s = servers[name];
                    let infoStr = '';
                    if (s.command) infoStr = `${s.command} ${(s.args || []).join(' ')}`;
                    else if (s.url) infoStr = s.url;
                    
                    const row = document.createElement('div');
                    row.className = 'custom-list-item';
                    row.innerHTML = `
                        <div class="list-item-content">
                            <strong>${escapeHtml(name)}</strong>
                            <div class="list-item-sub">${escapeHtml(infoStr)}</div>
                        </div>
                        <div class="list-item-actions">
                            <button class="btn btn-secondary btn-sm" onclick="mcpGetTools('${escapeHtml(name)}')"><i class="fa-solid fa-terminal"></i> Tools</button>
                            <button class="btn btn-danger btn-sm" onclick="removeMcpServer('${escapeHtml(name)}')"><i class="fa-solid fa-trash-can"></i></button>
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
    
    let name = '';
    let command = '';
    let args = [];
    let isUrl = url.startsWith('http://') || url.startsWith('https://');
    
    if (isUrl) {
        try {
            const parsed = new URL(url);
            name = parsed.hostname.replace(/[^a-zA-Z0-9_-]/g, '_') + '_' + parsed.port;
        } catch(e) {
            name = "http_server_" + Math.floor(Math.random()*1000);
        }
    } else {
        const parts = url.split(' ');
        command = parts[0];
        args = parts.slice(1);
        const baseCmd = command.split('/').pop().split('\\').pop();
        name = baseCmd + '_' + Math.floor(Math.random()*1000);
    }
    
    const payload = isUrl ? { url: url } : { command: command, args: args };
    
    if (window.pywebview && window.pywebview.api && window.pywebview.api.mcp_add) {
        const btn = event.currentTarget;
        const ogHtml = btn.innerHTML;
        btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i>';
        btn.disabled = true;
        
        window.pywebview.api.mcp_add(name, payload).then(res => {
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

function removeMcpServer(name) {
    if (confirm(`Remove MCP server '${name}'?`)) {
        if (window.pywebview && window.pywebview.api && window.pywebview.api.mcp_remove) {
            window.pywebview.api.mcp_remove(name).then(res => {
                if (res.status === 'success') {
                    loadMcpServers();
                } else {
                    alert("Failed to remove: " + res.message);
                }
            });
        }
    }
}

function mcpGetTools(name) {
    const explorer = document.getElementById('mcp-tools-explorer');
    const title = document.getElementById('mcp-tools-explorer-title');
    const consoleDiv = document.getElementById('mcp-tools-console');
    
    explorer.style.display = 'block';
    title.innerText = `Tools on ${name}`;
    consoleDiv.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Fetching...';
    
    if (window.pywebview && window.pywebview.api && window.pywebview.api.mcp_get_tools) {
        window.pywebview.api.mcp_get_tools(name).then(res => {
            if (res.status === 'success') {
                if (!res.tools || res.tools.length === 0) {
                    consoleDiv.innerHTML = '<span style="color: var(--text-muted);">No tools found.</span>';
                    return;
                }
                let html = '<ul style="margin:0; padding-left:20px;">';
                res.tools.forEach(t => {
                    const funcName = t.function ? t.function.name : t.name;
                    const funcDesc = t.function ? t.function.description : t.description;
                    html += `<li style="margin-bottom: 10px;">
                        <strong style="color: var(--color-green);">${escapeHtml(funcName || '')}</strong>
                        <div style="font-size: 12px; color: var(--text-muted);">${escapeHtml(funcDesc || '')}</div>
                    </li>`;
                });
                html += '</ul>';
                consoleDiv.innerHTML = html;
            } else {
                consoleDiv.innerHTML = `<span style="color: var(--color-red);">Error: ${escapeHtml(res.message)}</span>`;
            }
        });
    }
}

function importMcpConfig() {
    const input = document.getElementById('mcp-import-path');
    const resultDiv = document.getElementById('mcp-import-result');
    const btn = document.getElementById('mcp-import-btn');
    if (!input) return;

    const pathOrUrl = input.value.trim();
    if (!pathOrUrl) return;

    const origHtml = btn.innerHTML;
    btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i>';
    btn.disabled = true;
    resultDiv.style.display = 'none';
    resultDiv.textContent = '';

    if (window.pywebview && window.pywebview.api && window.pywebview.api.mcp_import_config) {
        window.pywebview.api.mcp_import_config(pathOrUrl).then(res => {
            btn.innerHTML = origHtml;
            btn.disabled = false;

            if (res.status === 'success') {
                resultDiv.style.color = 'var(--color-green)';
                resultDiv.textContent = res.message || 'Import successful.';
                resultDiv.style.display = 'block';
                input.value = '';
                loadMcpServers();
            } else {
                resultDiv.style.color = 'var(--color-red)';
                resultDiv.textContent = 'Error: ' + (res.message || 'Unknown error');
                resultDiv.style.display = 'block';
            }
        }).catch(err => {
            btn.innerHTML = origHtml;
            btn.disabled = false;
            resultDiv.style.color = 'var(--color-red)';
            resultDiv.textContent = 'Error: ' + err;
            resultDiv.style.display = 'block';
        });
    }
}
