function fillInput(text) {
    const input = document.getElementById('chat-input');
    input.value = text;
    input.focus();
}

/* Chat functionality */
function handleInputKey(event) {
    if (event.key === 'Enter' && !event.shiftKey) {
        event.preventDefault();
        if (!isProcessing) {
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
    updateSendButtonState(true);
    
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
    updateSendButtonState(false);
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

function handleSendClick() {
    if (isProcessing) {
        interruptChat();
    } else {
        sendMessage();
    }
}

function updateSendButtonState(processing) {
    const btn = document.getElementById('send-btn');
    if (!btn) return;
    
    if (processing) {
        btn.classList.add('stop');
        btn.innerHTML = '<i class="fa-solid fa-circle-stop"></i>';
    } else {
        btn.classList.remove('stop');
        btn.innerHTML = '<i class="fa-solid fa-paper-plane"></i>';
    }
}
