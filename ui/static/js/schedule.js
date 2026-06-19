/* Schedule Tab — UI Logic */

function loadScheduledTasks() {
    const list = document.getElementById('schedule-task-list');
    if (!list) return;
    list.innerHTML = '<div style="text-align:center;color:var(--text-muted);padding:20px;"><i class="fa-solid fa-spinner fa-spin"></i> Loading...</div>';

    if (window.pywebview && window.pywebview.api && window.pywebview.api.schedule_list) {
        window.pywebview.api.schedule_list().then(res => {
            if (res.status === 'success') {
                const tasks = res.tasks || [];
                if (tasks.length === 0) {
                    list.innerHTML = '<div style="text-align:center;color:var(--text-muted);padding:20px;">No scheduled tasks yet. Create one above!</div>';
                    return;
                }
                list.innerHTML = '';
                tasks.forEach(t => {
                    const isOnce = t.cron_expr && t.cron_expr.startsWith('@once:');
                    const scheduleLabel = isOnce
                        ? '🕐 Once: ' + t.cron_expr.replace('@once:', '')
                        : '🔁 ' + t.cron_expr;

                    const row = document.createElement('div');
                    row.className = 'custom-list-item';
                    row.style.cssText = 'display:flex;align-items:center;justify-content:space-between;padding:10px 14px;border-bottom:1px solid rgba(255,255,255,0.04);';
                    row.innerHTML = `
                        <div style="flex:1;min-width:0;">
                            <div style="font-weight:600;font-size:13px;color:var(--text-primary);margin-bottom:2px;">
                                <span style="color:var(--text-muted);font-size:11px;margin-right:6px;">#${t.id}</span>${escapeHtml(t.name)}
                            </div>
                            <div style="font-size:11px;color:var(--text-muted);font-family:monospace;">${escapeHtml(scheduleLabel)}</div>
                            <div style="font-size:11px;color:var(--color-green);font-family:monospace;margin-top:2px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${escapeHtml(t.command.substring(0, 80))}${t.command.length > 80 ? '…' : ''}</div>
                        </div>
                        <button class="btn btn-danger btn-sm" onclick="deleteScheduledTask(${t.id})" style="margin-left:12px;flex-shrink:0;" title="Delete task">
                            <i class="fa-solid fa-trash-can"></i>
                        </button>
                    `;
                    list.appendChild(row);
                });
            } else {
                list.innerHTML = `<div style="color:var(--color-red);padding:10px;">Error: ${escapeHtml(res.message || 'Unknown error')}</div>`;
            }
        }).catch(err => {
            list.innerHTML = `<div style="color:var(--color-red);padding:10px;">Error: ${escapeHtml(String(err))}</div>`;
        });
    } else {
        list.innerHTML = '<div style="color:var(--color-red);padding:10px;">Bridge API not ready.</div>';
    }
}

function createScheduledTask(type) {
    if (!window.pywebview || !window.pywebview.api) return;

    if (type === 'recurring') {
        const name    = document.getElementById('cron-name').value.trim();
        const expr    = document.getElementById('cron-expr').value.trim();
        const command = document.getElementById('cron-command').value.trim();
        if (!name || !expr || !command) {
            alert('Please fill in all fields (Name, Cron Expression, Command).');
            return;
        }
        window.pywebview.api.schedule_create(name, command, expr).then(res => {
            if (res.status === 'success') {
                document.getElementById('cron-name').value = '';
                document.getElementById('cron-expr').value = '';
                document.getElementById('cron-command').value = '';
                loadScheduledTasks();
            } else {
                alert('Error: ' + (res.message || 'Unknown error'));
            }
        });
    } else {
        const name    = document.getElementById('once-name').value.trim();
        const when    = document.getElementById('once-when').value.trim();
        const command = document.getElementById('once-command').value.trim();
        if (!name || !command) {
            alert('Please fill in Name and Command.');
            return;
        }
        // Determine if 'when' is a number (minutes) or ISO string
        const delayMin = parseInt(when, 10);
        const runAt    = isNaN(delayMin) ? when : '';
        const delay    = isNaN(delayMin) ? 10 : delayMin;

        window.pywebview.api.schedule_create_once(name, command, runAt, delay).then(res => {
            if (res.status === 'success') {
                document.getElementById('once-name').value = '';
                document.getElementById('once-when').value = '';
                document.getElementById('once-command').value = '';
                loadScheduledTasks();
            } else {
                alert('Error: ' + (res.message || 'Unknown error'));
            }
        });
    }
}

function deleteScheduledTask(jobId) {
    if (!confirm(`Delete scheduled task #${jobId}?`)) return;
    if (window.pywebview && window.pywebview.api && window.pywebview.api.schedule_delete) {
        window.pywebview.api.schedule_delete(jobId).then(res => {
            loadScheduledTasks();
        });
    }
}
