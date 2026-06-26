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
    if (!btn || !icon) return;

    // Remove all state classes
    btn.classList.remove('voice-listening', 'voice-recording', 'voice-transcribing', 'voice-speaking', 'voice-off');

    switch (state) {
        case 'listening':
            _voiceActive = true;
            btn.classList.add('voice-listening');
            btn.title = 'Voice active — listening… (click to stop)';
            icon.className = 'fa-solid fa-microphone';
            break;
        case 'recording':
            btn.classList.add('voice-recording');
            btn.title = 'Recording speech…';
            icon.className = 'fa-solid fa-circle-dot';
            break;
        case 'transcribing':
            btn.classList.add('voice-transcribing');
            btn.title = 'Processing…';
            icon.className = 'fa-solid fa-spinner fa-spin';
            break;
        case 'speaking':
            btn.classList.add('voice-speaking');
            btn.title = 'Koza is speaking…';
            icon.className = 'fa-solid fa-volume-high';
            break;
        default: // 'off'
            _voiceActive = false;
            btn.classList.add('voice-off');
            btn.title = 'Voice Mode (click to activate)';
            icon.className = 'fa-solid fa-microphone';
            break;
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
