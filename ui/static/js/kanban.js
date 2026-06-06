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
                
                let actionHtml = '';
                if (task.agent_id) {
                    actionHtml = `
                        <div class="card-agent-status">
                            <i class="fa-solid fa-spinner fa-spin card-spinner"></i>
                            <span class="card-agent-id">#${task.agent_id}</span>
                            <button class="stop-task-btn" title="${LOCALIZATION[currentLanguage]['btn-stop-task']}" onclick="cancelKanbanTask(event, ${task.id}, '${task.agent_id}')">
                                <i class="fa-solid fa-square-minus"></i>
                            </button>
                            <button class="view-logs-btn" title="${LOCALIZATION[currentLanguage]['btn-view-logs']}" onclick="viewKanbanTaskLogs(event, '${task.agent_id}')">
                                <i class="fa-solid fa-terminal"></i>
                            </button>
                        </div>
                    `;
                } else if (task.column !== 'done') {
                    actionHtml = `
                        <button class="play-task-btn" title="${LOCALIZATION[currentLanguage]['btn-run-task']}" onclick="runKanbanTask(event, ${task.id})">
                            <i class="fa-solid fa-play"></i>
                        </button>
                    `;
                }
                
                card.innerHTML = `
                    <h4>${escapeHtml(task.title)}</h4>
                    <p>${escapeHtml(task.description || '')}</p>
                    <div class="kanban-card-footer">
                        <div class="kanban-card-left-actions">
                            ${actionHtml}
                        </div>
                        <button class="delete-task-btn" onclick="deleteTask(event, ${task.id})">
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

function deleteTask(event, taskId) {
    if (event) event.stopPropagation();
    const confText = currentLanguage === 'tr' ? 'Bu görevi silmek istiyor musunuz?' : 'Do you want to delete this task?';
    if (confirm(confText)) {
        window.pywebview.api.delete_kanban_task(taskId).then(res => {
            loadKanbanTasks();
        });
    }
}

function cancelKanbanTask(event, taskId, agentId) {
    if (event) event.stopPropagation();
    const confText = currentLanguage === 'tr' ? 'Bu görevi iptal etmek istiyor musunuz?' : 'Do you want to cancel this task?';
    if (confirm(confText)) {
        window.pywebview.api.cancel_background_task(agentId).then(res => {
            loadKanbanTasks();
        });
    }
}

function viewKanbanTaskLogs(event, agentId) {
    if (event) event.stopPropagation();
    if (window.viewAgentLogs) {
        window.viewAgentLogs(agentId);
    }
}

let selectedTaskIdForRun = null;
function runKanbanTask(event, taskId) {
    if (event) event.stopPropagation();
    selectedTaskIdForRun = taskId;
    document.getElementById('kanban-run-modal').classList.add('active');
}

function submitRunKanbanTask() {
    if (!selectedTaskIdForRun) return;
    const caps = [];
    if (document.getElementById('cap-files').checked) caps.push('files');
    if (document.getElementById('cap-code').checked) caps.push('code');
    if (document.getElementById('cap-browser').checked) caps.push('browser');
    if (document.getElementById('cap-github').checked) caps.push('github');
    if (document.getElementById('cap-devops').checked) caps.push('devops');
    
    const capabilitiesStr = caps.join(',');
    closeKanbanRunModal();
    
    window.pywebview.api.run_kanban_task(selectedTaskIdForRun, capabilitiesStr).then(res => {
        loadKanbanTasks();
        if (res.status !== 'success') {
            alert(res.message);
        }
    });
}

function closeKanbanRunModal() {
    document.getElementById('kanban-run-modal').classList.remove('active');
    selectedTaskIdForRun = null;
}
