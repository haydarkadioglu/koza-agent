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
            if (mediaOption === 'gemini_api' || mediaOption === 'openai') {
                mediaKeyGroup.style.display = 'block';
                // Show badge instead of masked value
                mediaKeyInput.value = '';
                mediaKeyInput.placeholder = 'Enter new key to update...';
                const mediaPk = mediaOption === 'gemini_api'
                    ? (cfg.providers && cfg.providers.gemini_media && cfg.providers.gemini_media.api_key)
                    : (cfg.providers && cfg.providers.openai_media && cfg.providers.openai_media.api_key);
                if (mediaPk && mediaPk !== '********') {
                    showKeyStatus('media-key-status', 'saved');
                } else if (mediaPk === '********') {
                    showKeyStatus('media-key-status', 'has_key');
                }
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
            
            // Self-Improvement Curator setting
            const selfImproveEnabled = !!(cfg.self_improvement && cfg.self_improvement.enabled);
            const selfImproveEl = document.getElementById('setting-self-improvement');
            if (selfImproveEl) {
                selfImproveEl.checked = selfImproveEnabled;
            }
            
            // Voice settings
            const voiceEnabled = !!(cfg.voice && cfg.voice.enabled);
            document.getElementById('setting-voice-enable').checked = voiceEnabled;
            document.getElementById('voice-settings-fields').style.display = voiceEnabled ? 'block' : 'none';
            
            // Sync mic button visibility with voice.enabled
            const micBtn = document.getElementById('mic-btn');
            if (micBtn) micBtn.style.display = voiceEnabled ? 'flex' : 'none';
            
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
                
                // Check model download status
                if (voiceEnabled) {
                    if (sttProv === 'local_whisper') checkSTTModelStatus(sttModel);
                    if (ttsProv === 'kokoro') checkTTSModelStatus();
                }
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
    const apiKeyGroup   = document.getElementById('group-api-key');
    const oauthGroup    = document.getElementById('group-oauth-actions');
    const anthropicOauthGroup = document.getElementById('group-anthropic-oauth-actions');
    const antigravGroup = document.getElementById('group-antigravity');
    const label         = document.getElementById('label-api-key');
    const keyInput      = document.getElementById('setting-api-key');
    const statusEl      = document.getElementById('api-key-status');

    // ── Antigravity Direct OAuth mode ──────────────────────────────
    if (provider === 'antigravity') {
        antigravGroup.style.display = 'none'; // Hide the proxy inputs completely
        apiKeyGroup.style.display   = 'none';
        oauthGroup.style.display    = 'flex'; // Show Google OAuth
        if (anthropicOauthGroup) anthropicOauthGroup.style.display = 'flex'; // Show Anthropic OAuth
        
        // Query Python bridge for current Google OAuth status
        window.pywebview.api.get_google_oauth_status().then(status => {
            const statusEl = document.getElementById('oauth-connection-status');
            const logoutBtn = document.getElementById('btn-google-logout');
            if (statusEl) {
                if (status.connected) {
                    statusEl.innerHTML = `<span style="color:#2CB67D;"><i class="fa-solid fa-circle-check"></i> Connected to Google: <b>${status.email}</b>${status.project_id ? ` (Project: ${status.project_id})` : ''}</span>`;
                    if (logoutBtn) logoutBtn.style.display = 'inline-flex';
                } else {
                    statusEl.innerHTML = `<span style="color:var(--text-secondary);"><i class="fa-solid fa-circle-info"></i> Not connected to Google account</span>`;
                    if (logoutBtn) logoutBtn.style.display = 'none';
                }
            }
        });

        // Query Python bridge for current Anthropic OAuth status
        if (anthropicOauthGroup) {
            window.pywebview.api.get_anthropic_oauth_status().then(status => {
                const statusEl = document.getElementById('anthropic-oauth-connection-status');
                const logoutBtn = document.getElementById('btn-anthropic-logout');
                if (statusEl) {
                    if (status.connected) {
                        statusEl.innerHTML = `<span style="color:#2CB67D;"><i class="fa-solid fa-circle-check"></i> Connected to Anthropic Claude</span>`;
                        if (logoutBtn) logoutBtn.style.display = 'inline-flex';
                    } else {
                        statusEl.innerHTML = `<span style="color:var(--text-secondary);"><i class="fa-solid fa-circle-info"></i> Not connected to Anthropic account</span>`;
                        if (logoutBtn) logoutBtn.style.display = 'none';
                    }
                }
            });
        }
        return;
    }

    // ── Standard API key providers ─────────────────────────────────
    antigravGroup.style.display = 'none';
    const needsKey = providersMetadata.needs_key.includes(provider) || provider.includes('api');

    if (needsKey) {
        apiKeyGroup.style.display = 'block';
        label.innerText = `${provider.toUpperCase()} API Key`;
        keyInput.value = '';
        keyInput.placeholder = 'Enter new key to update...';
        const savedKey = cfg.providers && cfg.providers[provider] ? cfg.providers[provider].api_key : '';
        if (savedKey && savedKey !== '********') {
            showKeyStatus('api-key-status', 'saved');
        } else if (savedKey === '********') {
            showKeyStatus('api-key-status', 'has_key');
        } else if (statusEl) {
            statusEl.style.display = 'none';
        }
    } else {
        apiKeyGroup.style.display = 'none';
        if (statusEl) statusEl.style.display = 'none';
    }

    if (provider.includes('gemini') || provider.includes('google') || provider === 'google-oauth') {
        oauthGroup.style.display = 'flex';
        if (anthropicOauthGroup) anthropicOauthGroup.style.display = 'none';
        // Query Python bridge for current Google OAuth status
        window.pywebview.api.get_google_oauth_status().then(status => {
            const statusEl = document.getElementById('oauth-connection-status');
            const logoutBtn = document.getElementById('btn-google-logout');
            if (statusEl) {
                if (status.connected) {
                    statusEl.innerHTML = `<span style="color:#2CB67D;"><i class="fa-solid fa-circle-check"></i> Connected to Google: <b>${status.email}</b>${status.project_id ? ` (Project: ${status.project_id})` : ''}</span>`;
                    if (logoutBtn) logoutBtn.style.display = 'inline-flex';
                } else {
                    statusEl.innerHTML = `<span style="color:var(--text-secondary);"><i class="fa-solid fa-circle-info"></i> Not connected to Google account</span>`;
                    if (logoutBtn) logoutBtn.style.display = 'none';
                }
            }
        });
    } else if (provider === 'anthropic-oauth') {
        oauthGroup.style.display = 'none';
        if (anthropicOauthGroup) {
            anthropicOauthGroup.style.display = 'flex';
            // Query Python bridge for current Anthropic OAuth status
            window.pywebview.api.get_anthropic_oauth_status().then(status => {
                const statusEl = document.getElementById('anthropic-oauth-connection-status');
                const logoutBtn = document.getElementById('btn-anthropic-logout');
                if (statusEl) {
                    if (status.connected) {
                        statusEl.innerHTML = `<span style="color:#2CB67D;"><i class="fa-solid fa-circle-check"></i> Connected to Anthropic Claude</span>`;
                        if (logoutBtn) logoutBtn.style.display = 'inline-flex';
                    } else {
                        statusEl.innerHTML = `<span style="color:var(--text-secondary);"><i class="fa-solid fa-circle-info"></i> Not connected to Anthropic account</span>`;
                        if (logoutBtn) logoutBtn.style.display = 'none';
                    }
                }
            });
        }
    } else {
        oauthGroup.style.display = 'none';
        if (anthropicOauthGroup) anthropicOauthGroup.style.display = 'none';
    }
}

function onProviderChanged(provider) {
    let lookupKey = provider;
    if (!providersMetadata.models[lookupKey]) {
        lookupKey = Object.keys(providersMetadata.models).find(k => k.startsWith(provider)) || provider;
    }
    const defaultModel = (providersMetadata.models[lookupKey] || [''])[0];

    window.pywebview.api.update_provider_and_model(provider, defaultModel).then(res => {
        if (res && res.status === 'success') {
            window.pywebview.api.get_config().then(cfg => {
                populateModelsDropdown(provider, defaultModel);
                updateApiKeyFieldVisibility(provider, cfg);
                if (typeof checkApiKeyStatus === 'function') checkApiKeyStatus();
            });
        } else {
            console.error("Error updating provider and model:", res ? res.message : "unknown error");
            const errMsg = res ? res.message : "unknown error";
            alert(currentLanguage === 'tr' 
                ? "Sağlayıcı ve model güncellenirken hata oluştu: " + errMsg 
                : "Error updating provider and model: " + errMsg
            );
        }
    }).catch(err => {
        console.error("Promise rejected in onProviderChanged:", err);
    });
}


/** Save Antigravity Manager proxy settings (base URL + optional API key). */
function saveAntigravityConfig() {
    const url = document.getElementById('setting-antigravity-url').value.trim()
                || 'http://127.0.0.1:8045/v1';
    const key = document.getElementById('setting-antigravity-key').value.trim();
    const statusDiv = document.getElementById('antigravity-save-status');
    const btn = document.getElementById('btn-save-antigravity');

    btn.disabled = true;
    statusDiv.style.display = 'inline-flex';
    statusDiv.innerHTML = '<span style="color:var(--text-secondary);"><i class="fa-solid fa-spinner fa-spin"></i> Saving…</span>';

    const saves = [
        updateNestedConfig('providers.antigravity.base_url', url),
    ];
    if (key) saves.push(updateNestedConfig('providers.antigravity.api_key', key));

    Promise.all(saves).then(() => {
        statusDiv.innerHTML = '<span style="color:#2CB67D;"><i class="fa-solid fa-check"></i> Saved</span>';
        document.getElementById('setting-antigravity-key').value = '';
        document.getElementById('setting-antigravity-key').placeholder = 'sk-… (key saved)';
    }).catch(err => {
        statusDiv.innerHTML = `<span style="color:#ff5555;"><i class="fa-solid fa-xmark"></i> Error: ${err}</span>`;
        btn.disabled = false;
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

/* ── API Key status badge helper ─────────────────────────────────────────── */
/**
 * state: 'saved' | 'has_key' | 'testing' | 'success' | 'error' | 'idle'
 */
function showKeyStatus(elementId, state, message) {
    const el = document.getElementById(elementId);
    if (!el) return;
    el.style.display = 'block';
    const icons = {
        saved:   '<i class="fa-solid fa-check-circle" style="color:#2CB67D"></i>',
        has_key: '<i class="fa-solid fa-key" style="color:#7f5af0"></i>',
        testing: '<i class="fa-solid fa-spinner fa-spin" style="color:#f4a261"></i>',
        success: '<i class="fa-solid fa-check-circle" style="color:#2CB67D"></i>',
        error:   '<i class="fa-solid fa-times-circle" style="color:#e63946"></i>',
        idle:    ''
    };
    const labels = {
        saved:   currentLanguage === 'tr' ? 'Kaydedildi ✓' : 'Saved ✓',
        has_key: currentLanguage === 'tr' ? 'Key kayıtlı (değiştirmek için yenisini girin)' : 'Key saved — enter a new key to update',
        testing: currentLanguage === 'tr' ? 'Test ediliyor...' : 'Testing...',
        success: message || (currentLanguage === 'tr' ? 'Bağlantı başarılı ✓' : 'Connection successful ✓'),
        error:   message || (currentLanguage === 'tr' ? 'Hata — key geçersiz' : 'Error — key invalid'),
        idle:    ''
    };
    el.innerHTML = `${icons[state] || ''} <span style="margin-left:4px;">${labels[state] || message || ''}</span>`;
    if (state === 'idle') el.style.display = 'none';
}

/** Called on every keypress in an API key input — enables the Test button */
function onApiKeyInput(inputId, btnId) {
    const input = document.getElementById(inputId);
    const btn   = document.getElementById(btnId);
    if (btn) btn.disabled = !input || !input.value.trim();
}

/** Test & Save the primary LLM API key */
function testAndSaveApiKey() {
    const provider = document.getElementById('setting-provider').value;
    const key = document.getElementById('setting-api-key').value.trim();
    if (!key) return;
    showKeyStatus('api-key-status', 'testing');
    document.getElementById('btn-test-api-key').disabled = true;
    window.pywebview.api.test_api_key(provider, key).then(res => {
        document.getElementById('btn-test-api-key').disabled = false;
        if (res.status === 'success') {
            showKeyStatus('api-key-status', 'success', res.message);
            if (typeof checkApiKeyStatus === 'function') checkApiKeyStatus();
        } else {
            showKeyStatus('api-key-status', 'error', res.message);
        }
    }).catch(err => {
        document.getElementById('btn-test-api-key').disabled = false;
        showKeyStatus('api-key-status', 'error', String(err));
    });
}

/** Test & Save the fallback API key */
function testAndSaveFallbackKey() {
    const provider = document.getElementById('setting-fallback-provider').value;
    const key = document.getElementById('setting-fallback-key').value.trim();
    if (!key) return;
    showKeyStatus('fallback-key-status', 'testing');
    document.getElementById('btn-test-fallback-key').disabled = true;
    window.pywebview.api.test_api_key(provider, key).then(res => {
        document.getElementById('btn-test-fallback-key').disabled = false;
        if (res.status === 'success') {
            showKeyStatus('fallback-key-status', 'success', res.message);
        } else {
            showKeyStatus('fallback-key-status', 'error', res.message);
        }
    }).catch(err => {
        document.getElementById('btn-test-fallback-key').disabled = false;
        showKeyStatus('fallback-key-status', 'error', String(err));
    });
}

/** Save the media API key (no test — complex provider routing) */
function testAndSaveMediaKey() {
    const val = document.getElementById('setting-media-provider').value;
    const key = document.getElementById('setting-media-key').value.trim();
    if (!key) return;
    const statusEl = document.getElementById('media-key-status');
    showKeyStatus('media-key-status', 'testing');
    document.getElementById('btn-test-media-key').disabled = true;
    let promise;
    if (val === 'gemini_api') {
        promise = updateNestedConfig('providers.gemini_media.api_key', key);
    } else if (val === 'openai') {
        promise = updateNestedConfig('providers.openai_media.api_key', key);
    } else {
        promise = Promise.resolve({status: 'error', message: 'No media provider selected'});
    }
    promise.then(res => {
        document.getElementById('btn-test-media-key').disabled = false;
        if (res && res.status === 'success') {
            showKeyStatus('media-key-status', 'saved');
        } else {
            showKeyStatus('media-key-status', 'error', res ? res.message : 'Save failed');
        }
    }).catch(err => {
        document.getElementById('btn-test-media-key').disabled = false;
        showKeyStatus('media-key-status', 'error', String(err));
    });
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

function logoutGoogleOAuth() {
    if (confirm(currentLanguage === 'tr' ? 'Google OAuth bağlantısını kesmek istiyor musunuz?' : 'Are you sure you want to disconnect Google OAuth?')) {
        window.pywebview.api.logout_google_oauth().then(res => {
            if (res.status === 'success') {
                alert(currentLanguage === 'tr' ? 'Bağlantı kesildi.' : 'Disconnected.');
                window.pywebview.api.get_config().then(cfg => {
                    updateApiKeyFieldVisibility(cfg.provider, cfg);
                });
            } else {
                alert('Error: ' + res.message);
            }
        });
    }
}

function onOAuthCompleted(res) {
    if (res.status === 'success') {
        alert(currentLanguage === 'tr' ? 'Google OAuth bağlantısı başarıyla tamamlandı!' : 'Google OAuth login completed successfully!');
    } else {
        alert(currentLanguage === 'tr' ? 'Giriş başarısız veya iptal edildi.' : 'Login failed or was cancelled.');
    }
    window.pywebview.api.get_config().then(cfg => {
        updateApiKeyFieldVisibility(cfg.provider, cfg);
    });
}

function onGeminiBrowserLoginCompleted(res) {
    if (res.status === 'success') {
        alert(currentLanguage === 'tr' ? 'Gemini tarayıcı oturumu başarıyla kaydedildi!' : 'Gemini browser session saved successfully!');
    } else {
        alert(currentLanguage === 'tr' ? 'Tarayıcı oturum kaydı başarısız.' : 'Browser login failed.');
    }
    window.pywebview.api.get_config().then(cfg => {
        updateApiKeyFieldVisibility(cfg.provider, cfg);
    });
}

function triggerAnthropicOAuth() {
    alert(currentLanguage === 'tr' ? 'Tarayıcıda Anthropic OAuth giriş penceresi açılıyor. Lütfen takip edin...' : 'Opening Anthropic OAuth login in browser. Please follow the instructions...');
    window.pywebview.api.run_anthropic_oauth();
}

function logoutAnthropicOAuth() {
    if (confirm(currentLanguage === 'tr' ? 'Anthropic OAuth bağlantısını kesmek istiyor musunuz?' : 'Are you sure you want to disconnect Anthropic OAuth?')) {
        window.pywebview.api.logout_anthropic_oauth().then(res => {
            if (res.status === 'success') {
                alert(currentLanguage === 'tr' ? 'Bağlantı kesildi.' : 'Disconnected.');
                window.pywebview.api.get_config().then(cfg => {
                    updateApiKeyFieldVisibility(cfg.provider, cfg);
                });
            } else {
                alert('Error: ' + res.message);
            }
        });
    }
}

function onAnthropicOAuthCompleted(res) {
    if (res.status === 'success') {
        alert(currentLanguage === 'tr' ? 'Anthropic OAuth bağlantısı başarıyla tamamlandı!' : 'Anthropic OAuth login completed successfully!');
    } else {
        alert(currentLanguage === 'tr' ? 'Giriş başarısız veya iptal edildi.' : 'Login failed or was cancelled.');
    }
    window.pywebview.api.get_config().then(cfg => {
        updateApiKeyFieldVisibility(cfg.provider, cfg);
    });
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
        // Only toggle mic button visibility — do NOT start/stop the voice loop.
        // The VAD loop starts only when the user explicitly clicks the mic button on chat.
        const micBtn = document.getElementById('mic-btn');
        if (micBtn) micBtn.style.display = enabled ? 'flex' : 'none';
        
        if (enabled) {
            window.pywebview.api.get_config().then(cfg => {
                loadAudioDevices(cfg.voice ? cfg.voice.input_device : null, cfg.voice ? cfg.voice.output_device : null);
                // Check model status when voice is enabled
                const sttProv = cfg.voice && cfg.voice.stt ? cfg.voice.stt.provider : 'local_whisper';
                const sttModel = cfg.voice && cfg.voice.stt ? cfg.voice.stt.model : 'base';
                const ttsProv = cfg.voice && cfg.voice.tts ? cfg.voice.tts.provider : 'system';
                if (sttProv === 'local_whisper') checkSTTModelStatus(sttModel);
                if (ttsProv === 'kokoro') checkTTSModelStatus();
            });
        } else {
            // If voice loop is running, stop it
            if (typeof voiceModeActive !== 'undefined' && voiceModeActive) {
                window.pywebview.api.stop_voice_loop().then(() => {
                    if (typeof voiceModeActive !== 'undefined') voiceModeActive = false;
                    if (typeof updateVoiceStatus === 'function') updateVoiceStatus('off');
                });
            }
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
            // Show/hide STT download row based on provider
            const sttRow = document.getElementById('stt-download-row');
            if (sttRow) sttRow.style.display = (val === 'local_whisper') ? 'flex' : 'none';
            if (val === 'local_whisper') checkSTTModelStatus(defaultModel);
        });
    });
}

function onSTTModelChanged(val) {
    updateNestedConfig('voice.stt.model', val);
    // Re-check model status for local whisper
    const sttProv = document.getElementById('setting-voice-stt-prov').value;
    if (sttProv === 'local_whisper') checkSTTModelStatus(val);
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
                // Show/hide TTS download row based on provider
                const ttsRow = document.getElementById('tts-download-row');
                if (ttsRow) ttsRow.style.display = (val === 'kokoro') ? 'flex' : 'none';
                if (val === 'kokoro') checkTTSModelStatus();
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

/* ── Voice Model Status & Download ──────────────────────────────────────── */

/**
 * Check if the selected Local Whisper STT model is downloaded.
 * Updates #stt-model-status badge and shows/hides #btn-download-stt.
 */
function checkSTTModelStatus(modelName) {
    const row = document.getElementById('stt-download-row');
    const statusEl = document.getElementById('stt-model-status');
    const downloadBtn = document.getElementById('btn-download-stt');
    if (!row || !statusEl) return;
    row.style.display = 'flex';
    statusEl.innerHTML = '<i class="fa-solid fa-spinner fa-spin" style="color:#f4a261; margin-right:4px;"></i>' +
        (currentLanguage === 'tr' ? 'Kontrol ediliyor...' : 'Checking...');
    if (downloadBtn) downloadBtn.style.display = 'none';

    if (!window.pywebview || !window.pywebview.api) return;
    window.pywebview.api.check_voice_model_status('stt', modelName).then(res => {
        if (res.status === 'ready') {
            statusEl.innerHTML = '<i class="fa-solid fa-check-circle" style="color:#2CB67D; margin-right:4px;"></i>' +
                (currentLanguage === 'tr' ? 'Model hazır ✓' : 'Model ready ✓') + ` (${modelName})`;
            if (downloadBtn) downloadBtn.style.display = 'none';
        } else if (res.status === 'missing') {
            statusEl.innerHTML = '<i class="fa-solid fa-triangle-exclamation" style="color:#f4a261; margin-right:4px;"></i>' +
                (currentLanguage === 'tr' ? 'İndirilmemiş' : 'Not downloaded') + ` — ${modelName}`;
            if (downloadBtn) downloadBtn.style.display = 'inline-flex';
        } else {
            statusEl.innerHTML = '<i class="fa-solid fa-times-circle" style="color:#e63946; margin-right:4px;"></i>' +
                (res.message || 'Error');
            if (downloadBtn) downloadBtn.style.display = 'inline-flex';
        }
    }).catch(err => {
        statusEl.innerHTML = '<i class="fa-solid fa-times-circle" style="color:#e63946; margin-right:4px;"></i>' + String(err);
    });
}

/**
 * Check if Kokoro ONNX TTS model files are downloaded.
 */
function checkTTSModelStatus() {
    const row = document.getElementById('tts-download-row');
    const statusEl = document.getElementById('tts-model-status');
    const downloadBtn = document.getElementById('btn-download-tts');
    if (!row || !statusEl) return;
    row.style.display = 'flex';
    statusEl.innerHTML = '<i class="fa-solid fa-spinner fa-spin" style="color:#f4a261; margin-right:4px;"></i>' +
        (currentLanguage === 'tr' ? 'Kontrol ediliyor...' : 'Checking...');
    if (downloadBtn) downloadBtn.style.display = 'none';

    if (!window.pywebview || !window.pywebview.api) return;
    window.pywebview.api.check_voice_model_status('tts', 'kokoro').then(res => {
        if (res.status === 'ready') {
            statusEl.innerHTML = '<i class="fa-solid fa-check-circle" style="color:#2CB67D; margin-right:4px;"></i>' +
                (currentLanguage === 'tr' ? 'Kokoro hazır ✓' : 'Kokoro ONNX ready ✓');
            if (downloadBtn) downloadBtn.style.display = 'none';
        } else if (res.status === 'missing') {
            statusEl.innerHTML = '<i class="fa-solid fa-triangle-exclamation" style="color:#f4a261; margin-right:4px;"></i>' +
                (currentLanguage === 'tr' ? 'İndirilmemiş (~350MB)' : 'Not downloaded (~350MB)');
            if (downloadBtn) downloadBtn.style.display = 'inline-flex';
        } else {
            statusEl.innerHTML = '<i class="fa-solid fa-times-circle" style="color:#e63946; margin-right:4px;"></i>' +
                (res.message || 'Error');
            if (downloadBtn) downloadBtn.style.display = 'inline-flex';
        }
    }).catch(err => {
        statusEl.innerHTML = '<i class="fa-solid fa-times-circle" style="color:#e63946; margin-right:4px;"></i>' + String(err);
    });
}

/**
 * Start downloading a voice model (STT or TTS).
 * category: 'stt' | 'tts'
 * Progress is reported via onVoiceModelDownloadProgress() called from Python.
 */
function downloadVoiceModel(category) {
    const modelName = category === 'stt'
        ? document.getElementById('setting-voice-stt-model').value
        : 'kokoro';

    const statusElId = category === 'stt' ? 'stt-model-status' : 'tts-model-status';
    const downloadBtnId = category === 'stt' ? 'btn-download-stt' : 'btn-download-tts';
    const statusEl = document.getElementById(statusElId);
    const downloadBtn = document.getElementById(downloadBtnId);

    if (downloadBtn) downloadBtn.disabled = true;
    if (statusEl) {
        statusEl.innerHTML = '<i class="fa-solid fa-spinner fa-spin" style="color:#f4a261; margin-right:4px;"></i>' +
            (currentLanguage === 'tr' ? 'İndiriliyor...' : 'Downloading...');
    }

    window.pywebview.api.download_voice_model(category, modelName).then(res => {
        console.log('Download started:', res);
    }).catch(err => {
        if (downloadBtn) downloadBtn.disabled = false;
        if (statusEl) {
            statusEl.innerHTML = '<i class="fa-solid fa-times-circle" style="color:#e63946; margin-right:4px;"></i>' + String(err);
        }
    });
}

/**
 * Callback called by Python backend with download progress.
 * payload: { category, model, status: 'downloading'|'ready'|'error', message }
 */
function onVoiceModelDownloadProgress(payload) {
    const category = payload.category;
    const statusElId = category === 'stt' ? 'stt-model-status' : 'tts-model-status';
    const downloadBtnId = category === 'stt' ? 'btn-download-stt' : 'btn-download-tts';
    const statusEl = document.getElementById(statusElId);
    const downloadBtn = document.getElementById(downloadBtnId);

    if (!statusEl) return;

    if (payload.status === 'downloading') {
        statusEl.innerHTML = '<i class="fa-solid fa-spinner fa-spin" style="color:#f4a261; margin-right:4px;"></i>' +
            (payload.message || (currentLanguage === 'tr' ? 'İndiriliyor...' : 'Downloading...'));
    } else if (payload.status === 'ready') {
        statusEl.innerHTML = '<i class="fa-solid fa-check-circle" style="color:#2CB67D; margin-right:4px;"></i>' +
            (payload.message || (currentLanguage === 'tr' ? 'Hazır ✓' : 'Ready ✓'));
        if (downloadBtn) { downloadBtn.disabled = false; downloadBtn.style.display = 'none'; }
    } else if (payload.status === 'error') {
        statusEl.innerHTML = '<i class="fa-solid fa-times-circle" style="color:#e63946; margin-right:4px;"></i>' +
            (payload.message || 'Error');
        if (downloadBtn) { downloadBtn.disabled = false; downloadBtn.style.display = 'inline-flex'; }
    }
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

function applyGeneralSettings() {
    const btn = document.getElementById('btn-apply-general');
    if (!btn) return;
    const originalHTML = btn.innerHTML;
    btn.innerHTML = '<i class="fa-solid fa-check-double"></i> <span data-localize="btn-applied">Applied!</span>';
    btn.style.background = 'var(--color-green)';
    setTimeout(() => {
        btn.innerHTML = originalHTML;
        btn.style.background = '';
    }, 2000);
}
