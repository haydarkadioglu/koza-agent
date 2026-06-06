let providersMetadata = { providers: [], models: {}, needs_key: [] };

const STT_MODELS = {
    local_whisper: ['tiny', 'base', 'small'],
    openai: ['whisper-1', 'gpt-4o-transcribe', 'gpt-4o-mini-transcribe'],
    gemini: ['gemini-2.0-flash', 'gemini-1.5-flash'],
    deepgram: ['nova-3', 'nova-2', 'base']
};

const TTS_VOICES = {
    system: [
        { value: 'af_sky', label: 'af_sky (Default)' }
    ],
    kokoro: [
        { value: 'af_sky', label: 'af_sky (Female)' },
        { value: 'af_bella', label: 'af_bella (Female)' },
        { value: 'am_adam', label: 'am_adam (Male)' }
    ],
    openai: [
        { value: 'alloy', label: 'alloy' },
        { value: 'nova', label: 'nova' },
        { value: 'shimmer', label: 'shimmer' },
        { value: 'echo', label: 'echo' },
        { value: 'fable', label: 'fable' },
        { value: 'onyx', label: 'onyx' }
    ],
    gemini: [
        { value: 'Kore', label: 'Kore' },
        { value: 'Puck', label: 'Puck' },
        { value: 'Charon', label: 'Charon' },
        { value: 'Fenrir', label: 'Fenrir' },
        { value: 'Aoede', label: 'Aoede' }
    ],
    elevenlabs: [
        { value: '21m00Tcm4TlvDq8ikWAM', label: 'Rachel (21m00Tcm4TlvDq8ikWAM)' },
        { value: 'pNInz6obpgDQGcFmaJgB', label: 'Adam (pNInz6obpgDQGcFmaJgB)' },
        { value: 'EXAVITQu4vr4xnSDxMaL', label: 'Bella (EXAVITQu4vr4xnSDxMaL)' }
    ]
};

function switchSettingsTab(subTabId) {
    document.querySelectorAll('.settings-sub-item').forEach(item => {
        item.classList.remove('active');
    });
    const clickedItem = Array.from(document.querySelectorAll('.settings-sub-item')).find(item => 
        item.getAttribute('onclick').includes(subTabId)
    );
    if (clickedItem) clickedItem.classList.add('active');

    document.querySelectorAll('.settings-panel').forEach(panel => {
        panel.classList.remove('active');
    });
    const activePanel = document.getElementById(`settings-panel-${subTabId}`);
    if (activePanel) activePanel.classList.add('active');
    
    if (subTabId === 'skills') {
        loadPluginsAndSkills();
    }
}

function loadSettings() {
    window.pywebview.api.get_providers_metadata().then(metaRes => {
        if (metaRes.status === 'success') {
            providersMetadata.providers = metaRes.providers;
            providersMetadata.models = metaRes.models;
            providersMetadata.needs_key = metaRes.needs_key || [];
        }
        
        window.pywebview.api.get_config().then(cfg => {
            // Set languages dropdown
            document.getElementById('setting-lang').value = currentLanguage;
            
            // Populators
            populateProvidersDropdown(cfg.provider);
            populateModelsDropdown(cfg.provider, cfg.model);
            updateApiKeyFieldVisibility(cfg.provider, cfg);
            
            // Fallbacks setup
            const fbEnabled = !!cfg.fallback_provider;
            document.getElementById('setting-fallback-enable').checked = fbEnabled;
            toggleFallback(fbEnabled, cfg);
            
            // Media settings load
            const mediaProv = cfg.media_provider || 'follow';
            let mediaOption = 'follow';
            if (mediaProv === 'gemini') {
                const auth = cfg.providers && cfg.providers.gemini_media && cfg.providers.gemini_media.auth;
                mediaOption = (auth === 'playwright') ? 'gemini_browser' : 'gemini_api';
            } else if (mediaProv === 'openai') {
                mediaOption = 'openai';
            }
            document.getElementById('setting-media-provider').value = mediaOption;
            
            const mediaKeyGroup = document.getElementById('group-media-key');
            const mediaKeyInput = document.getElementById('setting-media-key');
            if (mediaOption === 'gemini_api') {
                mediaKeyGroup.style.display = 'block';
                mediaKeyInput.value = (cfg.providers && cfg.providers.gemini_media && cfg.providers.gemini_media.api_key) || '';
            } else if (mediaOption === 'openai') {
                mediaKeyGroup.style.display = 'block';
                mediaKeyInput.value = (cfg.providers && cfg.providers.openai_media && cfg.providers.openai_media.api_key) || '';
            } else {
                mediaKeyGroup.style.display = 'none';
                mediaKeyInput.value = '';
            }
            
            // Messaging settings
            document.getElementById('setting-tg-token').value = cfg.telegram_token || (cfg.messaging && cfg.messaging.telegram && cfg.messaging.telegram.token) || '';
            document.getElementById('setting-tg-chat').value = (cfg.messaging && cfg.messaging.telegram && cfg.messaging.telegram.chat_id) || '';
            
            document.getElementById('setting-twilio-sid').value = (cfg.messaging && cfg.messaging.twilio && cfg.messaging.twilio.account_sid) || '';
            document.getElementById('setting-twilio-auth').value = (cfg.messaging && cfg.messaging.twilio && cfg.messaging.twilio.auth_token) || '';
            document.getElementById('setting-twilio-from').value = (cfg.messaging && cfg.messaging.twilio && cfg.messaging.twilio.from_number) || '';
            document.getElementById('setting-twilio-wa-from').value = (cfg.messaging && cfg.messaging.twilio && cfg.messaging.twilio.wa_from) || '';
            document.getElementById('setting-twilio-wa-to').value = (cfg.messaging && cfg.messaging.twilio && cfg.messaging.twilio.wa_to) || '';
            
            // General settings
            document.getElementById('setting-tool-approval').checked = !!cfg.tool_approval;
            document.getElementById('setting-coding-autotest').checked = !!(cfg.coding_mode && cfg.coding_mode.auto_test);
            
            // Voice settings
            const voiceEnabled = !!(cfg.voice && cfg.voice.enabled);
            document.getElementById('setting-voice-enable').checked = voiceEnabled;
            document.getElementById('voice-settings-fields').style.display = voiceEnabled ? 'block' : 'none';
            
            if (cfg.voice) {
                const sttProv = cfg.voice.stt ? cfg.voice.stt.provider : 'local_whisper';
                const sttModel = cfg.voice.stt ? cfg.voice.stt.model : 'base';
                const sttLang = cfg.voice.stt ? cfg.voice.stt.language : '';
                
                document.getElementById('setting-voice-stt-prov').value = sttProv;
                populateSTTModels(sttProv, sttModel);
                document.getElementById('setting-voice-stt-lang').value = sttLang;
                
                const ttsProv = cfg.voice.tts ? cfg.voice.tts.provider : 'system';
                const ttsVoice = cfg.voice.tts ? cfg.voice.tts.voice : 'af_sky';
                
                document.getElementById('setting-voice-tts-prov').value = ttsProv;
                populateTTSVoices(ttsProv, ttsVoice);
                
                const dgKey = (cfg.providers && cfg.providers.deepgram && cfg.providers.deepgram.api_key) || '';
                document.getElementById('setting-voice-deepgram-key').value = dgKey;
                
                const elKey = (cfg.providers && cfg.providers.elevenlabs && cfg.providers.elevenlabs.api_key) || '';
                document.getElementById('setting-voice-elevenlabs-key').value = elKey;
                
                updateVoiceKeysVisibility(sttProv, ttsProv);
                loadAudioDevices(cfg.voice.input_device, cfg.voice.output_device);
            }
        });
    });
}

function populateProvidersDropdown(selectedProvider) {
    const provSelect = document.getElementById('setting-provider');
    provSelect.innerHTML = '';
    
    providersMetadata.providers.forEach(p => {
        const opt = document.createElement('option');
        opt.value = p;
        opt.innerText = p.toUpperCase();
        if (p === selectedProvider) opt.selected = true;
        provSelect.appendChild(opt);
    });
}

function populateModelsDropdown(provider, selectedModel) {
    const modelSelect = document.getElementById('setting-model');
    const customInput = document.getElementById('setting-model-custom');
    modelSelect.innerHTML = '';
    
    let lookupKey = provider;
    if (!providersMetadata.models[lookupKey]) {
        lookupKey = Object.keys(providersMetadata.models).find(k => k.startsWith(provider)) || provider;
    }
    
    const models = providersMetadata.models[lookupKey] || [];
    models.forEach(m => {
        const opt = document.createElement('option');
        opt.value = m;
        opt.innerText = m;
        if (m === selectedModel) opt.selected = true;
        modelSelect.appendChild(opt);
    });
    
    const otherOpt = document.createElement('option');
    otherOpt.value = 'other';
    otherOpt.innerText = currentLanguage === 'tr' ? 'Diğer / Elle Gir...' : 'Other / Custom...';
    
    const isCustom = selectedModel && !models.includes(selectedModel);
    if (isCustom) {
        otherOpt.selected = true;
        customInput.value = selectedModel;
        customInput.style.display = 'block';
    } else {
        customInput.style.display = 'none';
    }
    modelSelect.appendChild(otherOpt);
}

function updateApiKeyFieldVisibility(provider, cfg) {
    const apiKeyGroup = document.getElementById('group-api-key');
    const oauthGroup = document.getElementById('group-oauth-actions');
    const label = document.getElementById('label-api-key');
    const keyInput = document.getElementById('setting-api-key');
    
    const needsKey = providersMetadata.needs_key.includes(provider) || provider.includes('api');
    
    if (needsKey) {
        apiKeyGroup.style.display = 'block';
        label.innerText = `${provider.toUpperCase()} API Key`;
        const pKey = cfg.providers && cfg.providers[provider] ? cfg.providers[provider].api_key : '';
        keyInput.value = pKey || '';
    } else {
        apiKeyGroup.style.display = 'none';
    }
    
    if (provider.includes('gemini') || provider.includes('google')) {
        oauthGroup.style.display = 'flex';
    } else {
        oauthGroup.style.display = 'none';
    }
}

function onProviderChanged(provider) {
    window.pywebview.api.update_config_value('root', 'provider', provider).then(res => {
        let lookupKey = provider;
        if (!providersMetadata.models[lookupKey]) {
            lookupKey = Object.keys(providersMetadata.models).find(k => k.startsWith(provider)) || provider;
        }
        const defaultModel = (providersMetadata.models[lookupKey] || [''])[0];
        
        window.pywebview.api.update_config_value('root', 'model', defaultModel).then(() => {
            window.pywebview.api.get_config().then(cfg => {
                populateModelsDropdown(provider, defaultModel);
                updateApiKeyFieldVisibility(provider, cfg);
            });
        });
    });
}

function onModelChanged(model) {
    const customInput = document.getElementById('setting-model-custom');
    if (model === 'other') {
        customInput.style.display = 'block';
        customInput.value = '';
        customInput.focus();
    } else {
        customInput.style.display = 'none';
        window.pywebview.api.update_config_value('root', 'model', model);
    }
}

function onCustomModelChanged(customModel) {
    if (customModel.trim()) {
        window.pywebview.api.update_config_value('root', 'model', customModel.trim());
    }
}

function onApiKeyChanged(key) {
    if (!key) return;
    const provider = document.getElementById('setting-provider').value;
    updateNestedConfig(`providers.${provider}.api_key`, key);
}

/* Fallback Provider logic */
function toggleFallback(checked, cfg) {
    const fields = document.getElementById('fallback-fields');
    if (checked) {
        fields.style.display = 'block';
        populateFallbackDropdowns(cfg);
    } else {
        fields.style.display = 'none';
        window.pywebview.api.update_config_value('root', 'fallback_provider', '');
        window.pywebview.api.update_config_value('root', 'fallback_model', '');
    }
}

function populateFallbackDropdowns(cfg) {
    const fbProvSelect = document.getElementById('setting-fallback-provider');
    fbProvSelect.innerHTML = '';
    
    providersMetadata.providers.forEach(p => {
        const opt = document.createElement('option');
        opt.value = p;
        opt.innerText = p.toUpperCase();
        if (cfg && p === cfg.fallback_provider) opt.selected = true;
        fbProvSelect.appendChild(opt);
    });
    
    const selectedFb = (cfg && cfg.fallback_provider) || providersMetadata.providers[0];
    onFallbackProviderChanged(selectedFb, cfg ? cfg.fallback_model : null, cfg);
}

function onFallbackProviderChanged(provider, selectedModel, cfg) {
    const modelSelect = document.getElementById('setting-fallback-model');
    modelSelect.innerHTML = '';
    
    let lookupKey = provider;
    if (!providersMetadata.models[lookupKey]) {
        lookupKey = Object.keys(providersMetadata.models).find(k => k.startsWith(provider)) || provider;
    }
    
    const models = providersMetadata.models[lookupKey] || [];
    models.forEach(m => {
        const opt = document.createElement('option');
        opt.value = m;
        opt.innerText = m;
        if (m === selectedModel) opt.selected = true;
        modelSelect.appendChild(opt);
    });
    
    window.pywebview.api.update_config_value('root', 'fallback_provider', provider);
    if (models.length > 0) {
        const defModel = selectedModel || models[0];
        window.pywebview.api.update_config_value('root', 'fallback_model', defModel);
    }
    
    const fbKeyGroup = document.getElementById('group-fallback-key');
    const fbKeyInput = document.getElementById('setting-fallback-key');
    if (providersMetadata.needs_key.includes(provider)) {
        fbKeyGroup.style.display = 'block';
        if (cfg && cfg.providers && cfg.providers[provider]) {
            fbKeyInput.value = cfg.providers[provider].api_key || '';
        }
    } else {
        fbKeyGroup.style.display = 'none';
    }
}

function onFallbackModelChanged(model) {
    window.pywebview.api.update_config_value('root', 'fallback_model', model);
}

function onFallbackKeyChanged(key) {
    const provider = document.getElementById('setting-fallback-provider').value;
    updateNestedConfig(`providers.${provider}.api_key`, key);
}

/* Media settings config */
function onMediaProviderChanged(val) {
    if (val === 'follow') {
        window.pywebview.api.update_config_value('root', 'media_provider', '').then(() => {
            loadSettings();
        });
    } else if (val === 'gemini_browser') {
        window.pywebview.api.update_config_value('root', 'media_provider', 'gemini').then(() => {
            window.pywebview.api.update_nested_config('providers.gemini_media.auth', 'playwright').then(() => {
                loadSettings();
            });
        });
    } else if (val === 'gemini_api') {
        window.pywebview.api.update_config_value('root', 'media_provider', 'gemini').then(() => {
            window.pywebview.api.update_nested_config('providers.gemini_media.auth', 'api_key').then(() => {
                loadSettings();
            });
        });
    } else if (val === 'openai') {
        window.pywebview.api.update_config_value('root', 'media_provider', 'openai').then(() => {
            window.pywebview.api.update_nested_config('providers.openai_media.auth', 'api_key').then(() => {
                loadSettings();
            });
        });
    }
}

function onMediaKeyChanged(key) {
    const val = document.getElementById('setting-media-provider').value;
    if (val === 'gemini_api') {
        updateNestedConfig('providers.gemini_media.api_key', key);
    } else if (val === 'openai') {
        updateNestedConfig('providers.openai_media.api_key', key);
    }
}

/* OAuth & Browser session triggers */
function triggerGoogleOAuth() {
    alert(currentLanguage === 'tr' ? 'Tarayıcıda Google OAuth giriş penceresi açılıyor. Lütfen takip edin...' : 'Opening Google OAuth login in browser. Please follow the instructions...');
    window.pywebview.api.run_google_oauth();
}

function triggerGeminiBrowserLogin() {
    alert(currentLanguage === 'tr' ? 'Otomatik tarayıcı oturum açma aracı başlatılıyor (Playwright)...' : 'Starting Playwright automatic browser login...');
    window.pywebview.api.run_gemini_browser_login();
}

function onOAuthCompleted(res) {
    if (res.status === 'success') {
        alert(currentLanguage === 'tr' ? 'Google OAuth bağlantısı başarıyla tamamlandı!' : 'Google OAuth login completed successfully!');
    } else {
        alert(currentLanguage === 'tr' ? 'Giriş başarısız veya iptal edildi.' : 'Login failed or was cancelled.');
    }
}

function onGeminiBrowserLoginCompleted(res) {
    if (res.status === 'success') {
        alert(currentLanguage === 'tr' ? 'Gemini tarayıcı oturumu başarıyla kaydedildi!' : 'Gemini browser session saved successfully!');
    } else {
        alert(currentLanguage === 'tr' ? 'Tarayıcı oturum kaydı başarısız.' : 'Browser login failed.');
    }
}

/* Twilio, voice and general config updates */
function updateNestedConfig(dotPath, value) {
    return window.pywebview.api.update_nested_config(dotPath, value).then(res => {
        console.log('Nested config updated:', res);
        return res;
    });
}

function updateGeneralConfig(section, key, value) {
    return window.pywebview.api.update_config_value(section, key, value).then(res => {
        console.log('Config updated:', res);
        return res;
    });
}

function toggleVoice(enabled) {
    updateGeneralConfig('voice', 'enabled', enabled).then(() => {
        const fields = document.getElementById('voice-settings-fields');
        if (fields) {
            fields.style.display = enabled ? 'block' : 'none';
        }
        if (enabled) {
            window.pywebview.api.get_config().then(cfg => {
                loadAudioDevices(cfg.voice ? cfg.voice.input_device : null, cfg.voice ? cfg.voice.output_device : null);
            });
        }
    });
}

function onSTTProvChanged(val) {
    updateNestedConfig('voice.stt.provider', val).then(() => {
        let defaultModel = '';
        if (val === 'local_whisper') defaultModel = 'base';
        else if (val === 'openai') defaultModel = 'whisper-1';
        else if (val === 'gemini') defaultModel = 'gemini-2.0-flash';
        else if (val === 'deepgram') defaultModel = 'nova-3';
        
        updateNestedConfig('voice.stt.model', defaultModel).then(() => {
            populateSTTModels(val, defaultModel);
            updateVoiceKeysVisibility(val, document.getElementById('setting-voice-tts-prov').value);
        });
    });
}

function onSTTModelChanged(val) {
    updateNestedConfig('voice.stt.model', val);
}

function onTTSProvChanged(val) {
    updateNestedConfig('voice.tts.provider', val).then(() => {
        let defaultModel = '';
        let defaultVoice = 'af_sky';
        if (val === 'openai') {
            defaultModel = 'tts-1';
            defaultVoice = 'alloy';
        } else if (val === 'gemini') {
            defaultModel = 'gemini-2.5-flash-preview-tts';
            defaultVoice = 'Kore';
        } else if (val === 'elevenlabs') {
            defaultModel = 'eleven_multilingual_v2';
            defaultVoice = 'Rachel — 21m00Tcm4TlvDq8ikWAM';
        }
        
        updateNestedConfig('voice.tts.model', defaultModel).then(() => {
            updateNestedConfig('voice.tts.voice', defaultVoice).then(() => {
                populateTTSVoices(val, defaultVoice);
                updateVoiceKeysVisibility(document.getElementById('setting-voice-stt-prov').value, val);
            });
        });
    });
}

function onTTSVoiceChanged(val) {
    updateNestedConfig('voice.tts.voice', val);
}

function onVoiceInputDeviceChanged(val) {
    const parsed = val === 'null' || val === '' ? null : parseInt(val);
    updateNestedConfig('voice.input_device', parsed);
}

function onVoiceOutputDeviceChanged(val) {
    const parsed = val === 'null' || val === '' ? null : parseInt(val);
    updateNestedConfig('voice.output_device', parsed);
}

function updateVoiceKeysVisibility(sttProv, ttsProv) {
    document.getElementById('group-voice-deepgram-key').style.display = (sttProv === 'deepgram') ? 'block' : 'none';
    document.getElementById('group-voice-elevenlabs-key').style.display = (ttsProv === 'elevenlabs') ? 'block' : 'none';
}

function populateSTTModels(provider, selectedModel) {
    const modelSelect = document.getElementById('setting-voice-stt-model');
    modelSelect.innerHTML = '';
    
    const models = STT_MODELS[provider] || [];
    models.forEach(m => {
        const opt = document.createElement('option');
        opt.value = m;
        opt.innerText = m;
        if (m === selectedModel) opt.selected = true;
        modelSelect.appendChild(opt);
    });
}

function populateTTSVoices(provider, selectedVoice) {
    const voiceSelect = document.getElementById('setting-voice-tts-voice');
    voiceSelect.innerHTML = '';
    
    const voices = TTS_VOICES[provider] || [];
    voices.forEach(v => {
        const opt = document.createElement('option');
        opt.value = v.value;
        opt.innerText = v.label;
        if (v.value === selectedVoice) opt.selected = true;
        voiceSelect.appendChild(opt);
    });
}

function loadAudioDevices(selectedInputIdx, selectedOutputIdx) {
    window.pywebview.api.get_audio_devices().then(res => {
        const inputSelect = document.getElementById('setting-voice-input-device');
        const outputSelect = document.getElementById('setting-voice-output-device');
        if (!inputSelect || !outputSelect) return;
        
        inputSelect.innerHTML = '';
        outputSelect.innerHTML = '';
        
        const defInput = document.createElement('option');
        defInput.value = 'null';
        defInput.innerText = currentLanguage === 'tr' ? 'Sistem Varsayılanı' : 'System Default';
        if (selectedInputIdx === null || selectedInputIdx === undefined) {
            defInput.selected = true;
        }
        inputSelect.appendChild(defInput);
        
        const defOutput = document.createElement('option');
        defOutput.value = 'null';
        defOutput.innerText = currentLanguage === 'tr' ? 'Sistem Varsayılanı' : 'System Default';
        if (selectedOutputIdx === null || selectedOutputIdx === undefined) {
            defOutput.selected = true;
        }
        outputSelect.appendChild(defOutput);
        
        if (res.status === 'success') {
            if (res.input) {
                res.input.forEach(dev => {
                    const opt = document.createElement('option');
                    opt.value = dev.id.toString();
                    opt.innerText = dev.name + (dev.is_default ? ' ★' : '');
                    if (selectedInputIdx !== null && selectedInputIdx !== undefined && dev.id === selectedInputIdx) {
                        opt.selected = true;
                    }
                    inputSelect.appendChild(opt);
                });
            }
            
            if (res.output) {
                res.output.forEach(dev => {
                    const opt = document.createElement('option');
                    opt.value = dev.id.toString();
                    opt.innerText = dev.name + (dev.is_default ? ' ★' : '');
                    if (selectedOutputIdx !== null && selectedOutputIdx !== undefined && dev.id === selectedOutputIdx) {
                        opt.selected = true;
                    }
                    outputSelect.appendChild(opt);
                });
            }
        }
    });
}

/* Background Daemon Management */
function updateDaemonUI(active, pid) {
    isDaemonActive = active;
    const dict = LOCALIZATION[currentLanguage] || LOCALIZATION['en'];
    
    // Sidebar elements
    const sidebarLight = document.getElementById('sidebar-daemon-light');
    const sidebarText = document.getElementById('sidebar-daemon-text');
    const sidebarBtn = document.getElementById('sidebar-daemon-btn');
    
    // Panel elements
    const panelLight = document.getElementById('daemon-panel-light');
    const panelStatus = document.getElementById('daemon-panel-status');
    const panelBtn = document.getElementById('daemon-panel-btn');
    
    if (active) {
        const activeLabel = dict["daemon-active"] || "Active";
        const stopLabel = dict["daemon-stop"] || "Stop";
        
        if (sidebarLight) {
            sidebarLight.className = "pulse green";
            sidebarLight.style.backgroundColor = ""; 
        }
        if (sidebarText) {
            sidebarText.innerText = `Daemon: ${activeLabel}${pid ? ' (PID ' + pid + ')' : ''}`;
        }
        if (sidebarBtn) {
            sidebarBtn.innerText = stopLabel;
            sidebarBtn.style.display = "inline-block";
        }
        
        if (panelLight) {
            panelLight.className = "pulse green";
            panelLight.style.backgroundColor = "";
        }
        if (panelStatus) {
            panelStatus.innerText = `${activeLabel}${pid ? ' (PID ' + pid + ')' : ''}`;
            panelStatus.style.color = "var(--color-green, #00FF87)";
        }
        if (panelBtn) {
            panelBtn.innerText = stopLabel;
            panelBtn.style.display = "inline-block";
        }
    } else {
        const inactiveLabel = dict["daemon-inactive"] || "Inactive";
        const startLabel = dict["daemon-start"] || "Start";
        
        if (sidebarLight) {
            sidebarLight.className = "pulse";
            sidebarLight.style.backgroundColor = "var(--text-muted, #718096)";
        }
        if (sidebarText) {
            sidebarText.innerText = `Daemon: ${inactiveLabel}`;
        }
        if (sidebarBtn) {
            sidebarBtn.innerText = startLabel;
            sidebarBtn.style.display = "inline-block";
        }
        
        if (panelLight) {
            panelLight.className = "pulse";
            panelLight.style.backgroundColor = "var(--text-muted, #718096)";
        }
        if (panelStatus) {
            panelStatus.innerText = inactiveLabel;
            panelStatus.style.color = "var(--text-secondary, #A0AEC0)";
        }
        if (panelBtn) {
            panelBtn.innerText = startLabel;
            panelBtn.style.display = "inline-block";
        }
    }
}

function checkDaemonStatus() {
    if (window.pywebview && window.pywebview.api && window.pywebview.api.get_daemon_status) {
        window.pywebview.api.get_daemon_status().then(res => {
            if (res && res.status === 'success') {
                updateDaemonUI(res.active, res.pid);
            }
        }).catch(err => {
            console.error("Failed to check daemon status:", err);
        });
    }
}

function toggleDaemon(enable) {
    const dict = LOCALIZATION[currentLanguage] || LOCALIZATION['en'];
    const label = enable ? (dict["daemon-checking"] || "Starting...") : (dict["daemon-checking"] || "Stopping...");
    
    const sidebarText = document.getElementById('sidebar-daemon-text');
    const panelStatus = document.getElementById('daemon-panel-status');
    const sidebarBtn = document.getElementById('sidebar-daemon-btn');
    const panelBtn = document.getElementById('daemon-panel-btn');
    
    if (sidebarText) sidebarText.innerText = `Daemon: ${label}`;
    if (panelStatus) panelStatus.innerText = label;
    if (sidebarBtn) sidebarBtn.disabled = true;
    if (panelBtn) panelBtn.disabled = true;
    
    window.pywebview.api.toggle_daemon(enable).then(res => {
        if (sidebarBtn) sidebarBtn.disabled = false;
        if (panelBtn) panelBtn.disabled = false;
        
        if (res && res.status === 'success') {
            checkDaemonStatus();
        } else {
            alert(res ? res.message : "Error toggling daemon");
            checkDaemonStatus();
        }
    }).catch(err => {
        if (sidebarBtn) sidebarBtn.disabled = false;
        if (panelBtn) panelBtn.disabled = false;
        console.error("Error toggling daemon:", err);
        checkDaemonStatus();
    });
}

function toggleDaemonFromSidebar() {
    toggleDaemon(!isDaemonActive);
}

function toggleDaemonFromPanel() {
    toggleDaemon(!isDaemonActive);
}
