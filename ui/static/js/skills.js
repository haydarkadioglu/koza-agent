function getSkillIcon(id) {
    const iconMap = {
        browser_control: 'fa-solid fa-compass',
        code_runner: 'fa-solid fa-code',
        kanban: 'fa-solid fa-chalkboard-user',
        cron: 'fa-solid fa-clock',
        creative: 'fa-solid fa-palette',
        datascience: 'fa-solid fa-chart-line',
        devops: 'fa-solid fa-server',
        email_skill: 'fa-solid fa-envelope',
        finance: 'fa-solid fa-coins',
        gaming: 'fa-solid fa-gamepad',
        github_skill: 'fa-brands fa-github',
        mcp_skill: 'fa-solid fa-network-wired',
        media: 'fa-solid fa-image',
        mlops: 'fa-solid fa-brain',
        productivity: 'fa-solid fa-clipboard-list',
        research: 'fa-solid fa-graduation-cap',
        security: 'fa-solid fa-shield-halved',
        smarthome: 'fa-solid fa-house-laptop',
        social: 'fa-solid fa-share-nodes',
        messaging: 'fa-solid fa-comments',
        sync: 'fa-solid fa-rotate',
        vision: 'fa-solid fa-eye',
        delegation: 'fa-solid fa-users-gear',
        repo_manager: 'fa-solid fa-folder-open'
    };
    return iconMap[id] || 'fa-solid fa-cube';
}

function loadPluginsAndSkills() {
    const pluginsContainer = document.getElementById('plugins-list-container');
    const coreContainer = document.getElementById('core-skills-list-container');
    const templatesContainer = document.getElementById('templates-list-container');

    if (pluginsContainer) {
        pluginsContainer.innerHTML = `<div style="grid-column: 1/-1; text-align: center; color: var(--text-muted); font-size: 12px; padding: 20px;">${currentLanguage === 'tr' ? 'Eklentiler yükleniyor...' : 'Loading plugins...'}</div>`;
    }
    if (coreContainer) {
        coreContainer.innerHTML = `<div style="grid-column: 1/-1; text-align: center; color: var(--text-muted); font-size: 12px; padding: 20px;">${currentLanguage === 'tr' ? 'Yetenekler yükleniyor...' : 'Loading core skills...'}</div>`;
    }
    if (templatesContainer) {
        templatesContainer.innerHTML = `<div style="grid-column: 1/-1; text-align: center; color: var(--text-muted); font-size: 12px; padding: 20px;">${currentLanguage === 'tr' ? 'Şablonlar yükleniyor...' : 'Loading templates...'}</div>`;
    }

    // Load External Plugins
    window.pywebview.api.get_plugins().then(res => {
        if (!pluginsContainer) return;
        pluginsContainer.innerHTML = '';
        if (res.status === 'success' && res.data && res.data.length > 0) {
            res.data.forEach(plugin => {
                const card = document.createElement('div');
                card.className = 'skill-card';
                
                const iconColor = plugin.enabled ? 'var(--color-yellow)' : 'var(--text-secondary)';
                const btnText = plugin.enabled 
                    ? (currentLanguage === 'tr' ? 'Etkin' : 'Enabled') 
                    : (currentLanguage === 'tr' ? 'Devre Dışı' : 'Disabled');
                const btnClass = plugin.enabled ? 'enabled' : 'disabled';
                
                card.innerHTML = `
                    <div class="skill-info">
                        <div class="skill-name">
                            <i class="fa-solid fa-puzzle-piece" style="color: ${iconColor};"></i>
                            <span>${plugin.name}</span>
                            <span style="font-size: 10px; color: var(--text-muted); font-weight: normal; margin-left: 4px;">v${plugin.version}</span>
                        </div>
                        <div class="skill-desc">${plugin.description || ''}</div>
                        <div class="skill-meta">Author: ${plugin.author || 'Unknown'} | Tools: ${plugin.tool_count}</div>
                    </div>
                    <button class="skill-toggle-btn ${btnClass}" onclick="togglePlugin('${plugin.name}', ${!plugin.enabled})">
                        ${btnText}
                    </button>
                `;
                pluginsContainer.appendChild(card);
            });
        } else {
            pluginsContainer.innerHTML = `
                <div style="grid-column: 1/-1; text-align: center; color: var(--text-muted); font-size: 12px; padding: 20px;">
                    ${currentLanguage === 'tr' ? 'Harici eklenti bulunamadı.' : 'No external plugins installed.'}
                </div>
            `;
        }
    }).catch(err => {
        if (pluginsContainer) {
            pluginsContainer.innerHTML = `<div style="grid-column: 1/-1; text-align: center; color: var(--color-red); font-size: 12px; padding: 20px;">Error: ${err}</div>`;
        }
    });

    // Load Core Skills
    window.pywebview.api.get_core_skills().then(res => {
        if (!coreContainer) return;
        coreContainer.innerHTML = '';
        if (res.status === 'success' && res.data && res.data.length > 0) {
            res.data.forEach(skill => {
                const card = document.createElement('div');
                card.className = 'skill-card';
                
                const iconClass = getSkillIcon(skill.id);
                const iconColor = skill.enabled ? 'var(--color-green)' : 'var(--text-secondary)';
                const btnText = skill.enabled 
                    ? (currentLanguage === 'tr' ? 'Etkin' : 'Enabled') 
                    : (currentLanguage === 'tr' ? 'Devre Dışı' : 'Disabled');
                const btnClass = skill.enabled ? 'enabled' : 'disabled';
                
                card.innerHTML = `
                    <div class="skill-info">
                        <div class="skill-name">
                            <i class="${iconClass}" style="color: ${iconColor};"></i>
                            <span>${skill.name}</span>
                        </div>
                        <div class="skill-desc">${skill.desc || ''}</div>
                    </div>
                    <button class="skill-toggle-btn ${btnClass}" onclick="toggleCoreSkill('${skill.id}', ${!skill.enabled})">
                        ${btnText}
                    </button>
                `;
                coreContainer.appendChild(card);
            });
        } else {
            coreContainer.innerHTML = `
                <div style="grid-column: 1/-1; text-align: center; color: var(--text-muted); font-size: 12px; padding: 20px;">
                    ${currentLanguage === 'tr' ? 'Dahili yetenek bulunamadı.' : 'No core skills found.'}
                </div>
            `;
        }
    }).catch(err => {
        if (coreContainer) {
            coreContainer.innerHTML = `<div style="grid-column: 1/-1; text-align: center; color: var(--color-red); font-size: 12px; padding: 20px;">Error: ${err}</div>`;
        }
    });

    // Load Skill Templates
    window.pywebview.api.get_skill_templates().then(res => {
        if (!templatesContainer) return;
        templatesContainer.innerHTML = '';
        if (res.status === 'success' && res.data && res.data.length > 0) {
            res.data.forEach(tmpl => {
                const card = document.createElement('div');
                card.className = 'skill-card';
                
                card.innerHTML = `
                    <div class="skill-info">
                        <div class="skill-name">
                            <i class="fa-solid fa-file-code" style="color: var(--text-primary);"></i>
                            <span>${tmpl.name}</span>
                        </div>
                        <div class="skill-desc">${tmpl.desc || ''}</div>
                        <div class="skill-meta">
                            ${currentLanguage === 'tr' ? 'Adımlar' : 'Steps'}: ${tmpl.steps ? tmpl.steps.length : 0} | 
                            ${currentLanguage === 'tr' ? 'Kullanım' : 'Uses'}: ${tmpl.use_count || 0}
                        </div>
                    </div>
                    <button class="skill-delete-btn" onclick="deleteSkillTemplate('${tmpl.name}')">
                        <i class="fa-solid fa-trash-can"></i> ${currentLanguage === 'tr' ? 'Sil' : 'Delete'}
                    </button>
                `;
                templatesContainer.appendChild(card);
            });
        } else {
            templatesContainer.innerHTML = `
                <div style="grid-column: 1/-1; text-align: center; color: var(--text-muted); font-size: 12px; padding: 20px;">
                    ${currentLanguage === 'tr' ? 'Kayıtlı şablon bulunamadı.' : 'No saved skill templates found.'}
                </div>
            `;
        }
    }).catch(err => {
        if (templatesContainer) {
            templatesContainer.innerHTML = `<div style="grid-column: 1/-1; text-align: center; color: var(--color-red); font-size: 12px; padding: 20px;">Error: ${err}</div>`;
        }
    });
}

function toggleCoreSkill(skillId, enable) {
    window.pywebview.api.toggle_core_skill(skillId, enable).then(res => {
        if (res.status === 'success') {
            loadPluginsAndSkills();
        } else {
            alert((currentLanguage === 'tr' ? 'Hata: ' : 'Error: ') + (res.message || 'Unknown error'));
        }
    });
}

function togglePlugin(pluginName, enable) {
    window.pywebview.api.toggle_plugin(pluginName, enable).then(res => {
        if (res.status === 'success') {
            loadPluginsAndSkills();
        } else {
            alert((currentLanguage === 'tr' ? 'Hata: ' : 'Error: ') + (res.message || 'Unknown error'));
        }
    });
}

function deleteSkillTemplate(name) {
    const confText = currentLanguage === 'tr' 
        ? `'${name}' şablonunu silmek istediğinize emin misiniz?` 
        : `Are you sure you want to delete template '${name}'?`;
    if (confirm(confText)) {
        window.pywebview.api.delete_skill_template(name).then(res => {
            if (res.status === 'success') {
                loadPluginsAndSkills();
            } else {
                alert((currentLanguage === 'tr' ? 'Hata: ' : 'Error: ') + (res.message || 'Unknown error'));
            }
        });
    }
}
