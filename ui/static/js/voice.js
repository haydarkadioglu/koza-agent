/* Voice Mode — GUI integration
 * Bridge API: start_voice_loop(), stop_voice_loop(), is_voice_loop_active()
 * Backend calls back: updateVoiceStatus(state), onVoiceError(msg)
 */

let _voiceActive = false;

/* ── Toggle called by mic button ─────────────────────────────────────── */
async function toggleVoiceMode() {
    if (_voiceActive) {
        await stopVoiceMode();
    } else {
        await startVoiceMode();
    }
}

async function startVoiceMode() {
    if (!window.pywebview?.api?.start_voice_loop) {
        showToast('Voice API not available', 'error');
        return;
    }
    const res = await window.pywebview.api.start_voice_loop();
    if (res.status === 'started' || res.status === 'already_running') {
        _voiceActive = true;
        updateVoiceStatus('listening');
    } else {
        showToast('Could not start voice mode', 'error');
    }
}

async function stopVoiceMode() {
    if (window.pywebview?.api?.stop_voice_loop) {
        await window.pywebview.api.stop_voice_loop();
    }
    _voiceActive = false;
    updateVoiceStatus('off');
}

/* ── Called by Python backend via evaluate_js ────────────────────────── */
function updateVoiceStatus(state) {
    const btn  = document.getElementById('mic-btn');
    const icon = document.getElementById('mic-icon');
    const overlay = document.getElementById('voice-overlay');
    const statusText = document.getElementById('vo-status-text');

    if (btn) {
        btn.classList.remove('voice-listening', 'voice-recording', 'voice-transcribing', 'voice-speaking', 'voice-off');
    }
    if (overlay) {
        overlay.classList.remove('state-listening', 'state-recording', 'state-transcribing', 'state-speaking');
    }

    switch (state) {
        case 'listening':
            _voiceActive = true;
            if (btn) {
                btn.classList.add('voice-listening');
                btn.title = 'Voice active — listening… (click to stop)';
            }
            if (icon) icon.className = 'fa-solid fa-microphone';
            if (overlay) {
                overlay.classList.add('active', 'state-listening');
            }
            if (statusText) statusText.innerText = 'LISTENING';
            break;
        case 'recording':
            _voiceActive = true;
            if (btn) {
                btn.classList.add('voice-recording');
                btn.title = 'Recording speech…';
            }
            if (icon) icon.className = 'fa-solid fa-circle-dot';
            if (overlay) {
                overlay.classList.add('active', 'state-recording');
            }
            if (statusText) statusText.innerText = 'RECORDING';
            break;
        case 'transcribing':
            _voiceActive = true;
            if (btn) {
                btn.classList.add('voice-transcribing');
                btn.title = 'Processing…';
            }
            if (icon) icon.className = 'fa-solid fa-spinner fa-spin';
            if (overlay) {
                overlay.classList.add('active', 'state-transcribing');
            }
            if (statusText) statusText.innerText = 'THINKING';
            break;
        case 'speaking':
            _voiceActive = true;
            if (btn) {
                btn.classList.add('voice-speaking');
                btn.title = 'Koza is speaking…';
            }
            if (icon) icon.className = 'fa-solid fa-volume-high';
            if (overlay) {
                overlay.classList.add('active', 'state-speaking');
            }
            if (statusText) statusText.innerText = 'SPEAKING';
            break;
        default: // 'off'
            _voiceActive = false;
            if (btn) {
                btn.classList.add('voice-off');
                btn.title = 'Voice Mode (click to activate)';
            }
            if (icon) icon.className = 'fa-solid fa-microphone';
            if (overlay) {
                overlay.classList.remove('active');
            }
            break;
    }
}

function updateLastAssistantBubble(text) {
    // 1. Update standard chat bubble
    const chatMsgs = document.getElementById('chat-messages');
    if (chatMsgs) {
        // Find the last message with class agent or assistant
        const bubbles = chatMsgs.querySelectorAll('.message.agent .message-bubble, .message.assistant .message-bubble');
        if (bubbles.length > 0) {
            const lastBubble = bubbles[bubbles.length - 1];
            if (typeof formatMarkdown === 'function') {
                lastBubble.innerHTML = formatMarkdown(text);
            } else {
                lastBubble.innerText = text;
            }
            lastBubble.setAttribute('data-raw', text);
        }
        chatMsgs.scrollTop = chatMsgs.scrollHeight;
    }

    // 2. Update voice overlay transcript
    const voAgent = document.getElementById('vo-agent-text');
    if (voAgent) {
        voAgent.innerText = text;
    }
}

function onVoiceError(msg) {
    _voiceActive = false;
    updateVoiceStatus('off');
    showToast('Voice error: ' + msg, 'error');
}

/* helper — toast if not already defined */
function showToast(msg, type) {
    if (typeof window.showNotification === 'function') {
        window.showNotification(msg, type);
        return;
    }
    const t = document.createElement('div');
    t.style.cssText = `position:fixed;bottom:24px;right:24px;padding:10px 18px;border-radius:8px;font-size:13px;z-index:9999;color:#fff;background:${type==='error'?'#e53935':'#2e7d32'};box-shadow:0 4px 16px rgba(0,0,0,.3)`;
    t.textContent = msg;
    document.body.appendChild(t);
    setTimeout(() => t.remove(), 3500);
}

// Press Escape to exit voice mode
window.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && _voiceActive) {
        stopVoiceMode();
    }
});
