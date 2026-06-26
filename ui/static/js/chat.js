let currentAttachments = [];

function handleAttachClick() {
    window.pywebview.api.upload_file().then(res => {
        if (res && res.status === 'success' && res.file) {
            currentAttachments.push(res.file);
            renderAttachments();
        } else if (res && res.status === 'error') {
            alert(res.message);
        }
    });
}

function renderAttachments() {
    const area = document.getElementById('attachment-preview-area');
    if (!area) return;
    area.innerHTML = '';
    if (currentAttachments.length === 0) {
        area.style.display = 'none';
        return;
    }
    area.style.display = 'flex';
    currentAttachments.forEach((file, idx) => {
        const chip = document.createElement('div');
        chip.className = 'attachment-chip';
        
        const iconClass = file.is_image ? 'fa-solid fa-file-image' : 'fa-solid fa-file';
        chip.innerHTML = `
            <i class="${iconClass}"></i>
            <span class="file-name" title="${file.path}">${file.name}</span>
            <button class="remove-btn" onclick="removeAttachment(${idx})">
                <i class="fa-solid fa-times"></i>
            </button>
        `;
        area.appendChild(chip);
    });
}

function removeAttachment(idx) {
    currentAttachments.splice(idx, 1);
    renderAttachments();
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
    currentBubble = null; // Reset bubble so agent reply creates a new one

    
    const welcome = document.querySelector('.welcome-box');
    if (welcome) welcome.remove();

    // Capture attachments
    const attachmentsToSend = [...currentAttachments];
    currentAttachments = [];
    renderAttachments();

    // Render bubble with attachments
    appendMessageBubble('user', message, attachmentsToSend);
    
    document.getElementById('stream-status').style.display = 'flex';
    document.getElementById('status-text').innerText = LOCALIZATION[currentLanguage].thinking;
    
    // Process attachments
    let processedMessage = message;
    let imagePath = null;
    
    const imageAttach = attachmentsToSend.find(att => att.is_image);
    if (imageAttach) {
        imagePath = imageAttach.path;
    }
    
    const nonImages = attachmentsToSend.filter(att => !att.is_image);
    if (nonImages.length > 0) {
        processedMessage += "\n\n--- Attached Files ---\n";
        nonImages.forEach(att => {
            processedMessage += `[File: ${att.name} (Location: ${att.path})]\n`;
        });
    }
    
    window.pywebview.api.send_chat_message(processedMessage, imagePath).then(res => {
        console.log('Chat stream started:', res);
    });
}

function appendMessageBubble(role, content, attachments = []) {
    const chatMsgs = document.getElementById('chat-messages');
    
    const messageDiv = document.createElement('div');
    messageDiv.classList.add('message', role);
    
    const label = document.createElement('div');
    label.classList.add('message-label');
    
    if (role === 'user') {
        label.innerText = currentLanguage === 'tr' ? 'Siz' : 'You';
    } else {
        let providerName = '';
        let modelName = '';
        const provEl = document.getElementById('setting-provider');
        const modEl = document.getElementById('setting-model');
        const modCustEl = document.getElementById('setting-model-custom');
        
        if (provEl && provEl.value) providerName = provEl.value;
        if (modEl && modEl.value) {
            modelName = modEl.value === 'other' ? (modCustEl ? modCustEl.value : '') : modEl.value;
        }
        
        if (providerName && modelName) {
            label.innerText = `Koza — ${providerName}/${modelName}`;
        } else {
            label.innerText = 'Koza';
        }
    }
    const bubble = document.createElement('div');
    bubble.classList.add('message-bubble');
    bubble.innerHTML = formatMarkdown(content);
    
    if (attachments && attachments.length > 0) {
        const attachContainer = document.createElement('div');
        attachContainer.className = 'bubble-attachments';
        attachContainer.style.display = 'flex';
        attachContainer.style.flexWrap = 'wrap';
        attachContainer.style.gap = '8px';
        attachContainer.style.marginTop = '8px';
        attachContainer.style.borderTop = '1px solid rgba(255, 255, 255, 0.05)';
        attachContainer.style.paddingTop = '6px';
        
        attachments.forEach(file => {
            const chip = document.createElement('div');
            chip.className = 'attachment-chip bubble-chip';
            chip.style.background = 'rgba(255, 255, 255, 0.05)';
            chip.style.border = '1px solid rgba(255, 255, 255, 0.08)';
            chip.style.borderRadius = '6px';
            chip.style.padding = '3px 8px';
            chip.style.fontSize = '11px';
            chip.style.display = 'flex';
            chip.style.alignItems = 'center';
            chip.style.gap = '6px';
            chip.style.color = 'var(--text-primary)';
            
            const iconClass = file.is_image ? 'fa-solid fa-file-image' : 'fa-solid fa-file';
            chip.innerHTML = `<i class="${iconClass}"></i><span>${file.name}</span>`;
            attachContainer.appendChild(chip);
        });
        bubble.appendChild(attachContainer);
    }
    
    messageDiv.appendChild(label);
    messageDiv.appendChild(bubble);
    chatMsgs.appendChild(messageDiv);
    chatMsgs.scrollTop = chatMsgs.scrollHeight;
    
    if (role === 'agent') {
        currentBubble = bubble;
    }

    // Update voice overlay transcript if active
    if (role === 'user') {
        const voUser = document.getElementById('vo-user-text');
        if (voUser) voUser.innerText = content;
        const voAgent = document.getElementById('vo-agent-text');
        if (voAgent) voAgent.innerText = ''; // clear previous agent response
    } else if (role === 'assistant' || role === 'agent') {
        const voAgent = document.getElementById('vo-agent-text');
        if (voAgent) voAgent.innerText = content;
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
    else if (event.type === 'error') {
        appendMessageBubble('agent', `**Error:** ${event.message}`);
        finishProcessing();
    }
    else if (event.type === 'text') {
        // Only hide stream-status if we don't have an active tool running
        if (!currentToolCard) {
            document.getElementById('stream-status').style.display = 'none';
        }
        if (!currentBubble) {
            appendMessageBubble('agent', '');
        }
        currentBubble.innerHTML = formatMarkdown((currentBubble.getAttribute('data-raw') || '') + event.token);
        currentBubble.setAttribute('data-raw', (currentBubble.getAttribute('data-raw') || '') + event.token);
        chatMsgs.scrollTop = chatMsgs.scrollHeight;
    } 
    else if (event.type === 'tool_start') {
        document.getElementById('stream-status').style.display = 'flex';
        document.getElementById('status-text').innerText = `Executing ${event.name}...`;

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
    document.getElementById('perm-tool-args').value = JSON.stringify(payload.args, null, 2);
    document.getElementById('inline-permission-box').style.display = 'flex';
    document.getElementById('inline-perm-args').style.display = 'none';
    document.getElementById('perm-args-icon').className = 'fa-solid fa-chevron-down';
    
    // Scroll to the permission box so it's visible
    const msgs = document.getElementById('chat-messages');
    msgs.scrollTop = msgs.scrollHeight;
}

function resolvePermission(allowed) {
    document.getElementById('inline-permission-box').style.display = 'none';
    const editedArgs = document.getElementById('perm-tool-args').value;
    window.pywebview.api.resolve_permission(allowed, editedArgs);
}

function allowAllSession() {
    // 1. Turn on Turbo Mode
    document.getElementById('setting-turbo-mode').checked = true;
    if (typeof toggleTurboMode === 'function') {
        toggleTurboMode(true);
    }
    // 2. Resolve current permission dialog
    resolvePermission(true);
}

function togglePermArgs() {
    const argsBox = document.getElementById('inline-perm-args');
    const icon = document.getElementById('perm-args-icon');
    if (argsBox.style.display === 'none') {
        argsBox.style.display = 'block';
        icon.className = 'fa-solid fa-chevron-up';
    } else {
        argsBox.style.display = 'none';
        icon.className = 'fa-solid fa-chevron-down';
    }
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

let voiceModeActive = false;

function toggleChatVoice() {
    if (voiceModeActive) {
        window.pywebview.api.stop_voice_loop().then(() => {
            voiceModeActive = false;
            updateVoiceStatus('off');
        });
    } else {
        window.pywebview.api.start_voice_loop().then(res => {
            if (res.status === 'started' || res.status === 'already_running') {
                voiceModeActive = true;
                updateVoiceStatus('listening');
            } else {
                console.error("Failed to start voice loop:", res);
            }
        });
    }
}

function updateVoiceStatus(state) {
    const streamStatus = document.getElementById('stream-status');
    const micBtn = document.getElementById('mic-btn');
    if (!streamStatus) return;

    if (state === 'off') {
        voiceModeActive = false;
        if (micBtn) micBtn.classList.remove('active');
        // Only hide the status bar — do NOT touch mic-btn display or settings checkbox.
        // Voice mode enabled/disabled is controlled by toggleVoice() in settings.js.
        streamStatus.style.display = 'none';
        return;
    }

    if (micBtn) micBtn.classList.add('active');
    streamStatus.style.display = 'flex';

    let iconHTML = '';
    let labelText = '';

    if (state === 'listening') {
        iconHTML = '<i class="fa-solid fa-microphone-lines" style="color: #2CB67D; margin-right: 8px;"></i>';
        labelText = currentLanguage === 'tr' ? 'Dinleniyor...' : 'Listening...';
    } else if (state === 'recording') {
        iconHTML = '<i class="fa-solid fa-microphone" style="color: #ff5555; margin-right: 8px; animation: mic-pulse 1s infinite alternate;"></i>';
        labelText = currentLanguage === 'tr' ? 'Kaydediliyor...' : 'Recording...';
    } else if (state === 'transcribing') {
        iconHTML = '<div class="spinner-circle" style="margin-right: 8px;"></div>';
        labelText = currentLanguage === 'tr' ? 'Yazıya Dökülüyor...' : 'Transcribing...';
    } else if (state === 'speaking') {
        iconHTML = '<i class="fa-solid fa-volume-high" style="color: #7f5af0; margin-right: 8px;"></i>';
        labelText = currentLanguage === 'tr' ? 'Konuşuyor...' : 'Speaking...';
    }

    streamStatus.innerHTML = `${iconHTML}<span id="status-text">${labelText}</span>`;
}

function onVoiceMessageTranscribed(text) {
    const input = document.getElementById('chat-input');
    if (input) {
        input.value = text;
        sendMessage();
    }
}

function onVoiceError(err) {
    console.error("Voice error:", err);
    updateVoiceStatus('off');
    voiceModeActive = false;
    alert("Voice Mode Error: " + err);
}
