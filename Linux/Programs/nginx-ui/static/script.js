let currentPath = '/';
let currentFile = null;
let createType = 'file';
let editor = null;
let ctrlPressed = false;
let deleteTarget = null; // Store item to delete
let hasUnsavedChanges = false; // Track unsaved changes
let recordingShortcut = null; // Track which shortcut is being recorded

// Helper function to get editor settings from localStorage
function getEditorSettings() {
    const defaults = {
        fontSize: 14,
        minimap: true,
        wordWrap: false,
        tabSize: 2
    };
    
    const saved = localStorage.getItem('editorSettings');
    if (saved) {
        try {
            return { ...defaults, ...JSON.parse(saved) };
        } catch (e) {
            return defaults;
        }
    }
    return defaults;
}

// Helper function to get keyboard shortcuts from localStorage
function getKeyboardShortcuts() {
    const defaults = {
        save: { key: 'S', ctrl: true, alt: false, shift: false, display: 'Ctrl+S' },
        comment: { key: 'Quote', ctrl: true, alt: false, shift: false, display: "Ctrl+'" }
    };
    
    const saved = localStorage.getItem('keyboardShortcuts');
    if (saved) {
        try {
            return { ...defaults, ...JSON.parse(saved) };
        } catch (e) {
            return defaults;
        }
    }
    return defaults;
}

// Initialize Monaco Editor
require.config({ 
    paths: { 
        'vs': 'https://cdnjs.cloudflare.com/ajax/libs/monaco-editor/0.44.0/min/vs' 
    } 
});

require(['vs/editor/editor.main'], function() {
    // Register nginx language
    monaco.languages.register({ id: 'nginx' });

    // Define nginx syntax highlighting
    monaco.languages.setMonarchTokensProvider('nginx', {
        defaultToken: '',
        tokenPostfix: '.nginx',
        
        keywords: [
            // Main contexts
            'http', 'server', 'location', 'upstream', 'events', 'stream', 'types', 'map',
            'geo', 'split_clients', 'limit_except',
            
            // Control directives
            'if', 'return', 'rewrite', 'set', 'break', 'include', 'internal',
            
            // Server directives
            'listen', 'server_name', 'root', 'index', 'try_files', 'error_page',
            'recursive_error_pages', 'default_type',
            
            // Proxy directives
            'proxy_pass', 'proxy_set_header', 'proxy_redirect', 'proxy_cache',
            'proxy_cache_valid', 'proxy_cache_key', 'proxy_buffering',
            'proxy_connect_timeout', 'proxy_read_timeout', 'proxy_send_timeout',
            
            // FastCGI directives
            'fastcgi_pass', 'fastcgi_param', 'fastcgi_index', 'fastcgi_split_path_info',
            'fastcgi_cache', 'fastcgi_cache_valid',
            
            // Headers and MIME
            'add_header', 'expires', 'charset', 'add_trailer',
            
            // File serving
            'autoindex', 'autoindex_exact_size', 'autoindex_format',
            'autoindex_localtime', 'sendfile', 'aio', 'directio',
            
            // SSL/TLS
            'ssl', 'ssl_certificate', 'ssl_certificate_key', 'ssl_protocols',
            'ssl_ciphers', 'ssl_prefer_server_ciphers', 'ssl_session_cache',
            'ssl_session_timeout', 'ssl_stapling', 'ssl_stapling_verify',
            
            // Access control
            'allow', 'deny', 'auth_basic', 'auth_basic_user_file',
            'satisfy', 'access_log', 'error_log',
            
            // Limits
            'client_max_body_size', 'client_body_buffer_size',
            'client_header_buffer_size', 'large_client_header_buffers',
            'limit_rate', 'limit_rate_after',
            
            // Timeouts and connections
            'keepalive_timeout', 'keepalive_requests', 'send_timeout',
            'reset_timedout_connection',
            
            // TCP optimization
            'tcp_nopush', 'tcp_nodelay',
            
            // Compression
            'gzip', 'gzip_vary', 'gzip_proxied', 'gzip_comp_level',
            'gzip_types', 'gzip_min_length', 'gzip_disable',
            
            // Worker configuration
            'worker_processes', 'worker_connections', 'worker_rlimit_nofile',
            'worker_priority', 'worker_cpu_affinity',
            
            // Logging
            'log_format', 'open_log_file_cache',
            
            // Variables
            'request_method', 'request_uri', 'uri', 'args', 'query_string',
            
            // Other common directives
            'types_hash_max_size', 'server_tokens', 'underscores_in_headers',
            'ignore_invalid_headers', 'merge_slashes', 'alias'
        ],
        
        operators: ['=', '~', '~*', '!~', '!~*'],
        
        symbols: /[=><!~?:&|+\-*\/\^%]+/,
        
        tokenizer: {
            root: [
                // Comments
                [/#.*$/, 'comment'],
                
                // Numbers with units (must come before general numbers)
                [/\d+[kKmMgGtT]\b/, 'number'],
                [/\d+[mshd]\b/, 'number'],
                [/\d+/, 'number'],
                
                // Variables
                [/\$\w+/, 'variable'],
                
                // Strings (double quotes)
                [/"([^"\\]|\\.)*"/, 'string'],
                [/'([^'\\]|\\.)*'/, 'string'],
                
                // Keywords and directives
                [/[a-z_][\w_]*/, {
                    cases: {
                        '@keywords': 'keyword',
                        '@default': 'type'
                    }
                }],
                
                // Block delimiters
                [/[{}]/, '@brackets'],
                [/[;]/, 'delimiter'],
                
                // Operators
                [/@symbols/, 'operator'],
                
                // Whitespace
                [/\s+/, 'white'],
            ],
        }
    });

    // Configure nginx language settings
    monaco.languages.setLanguageConfiguration('nginx', {
        comments: {
            lineComment: '#'
        },
        brackets: [
            ['{', '}'],
            ['[', ']'],
            ['(', ')']
        ],
        autoClosingPairs: [
            { open: '{', close: '}' },
            { open: '[', close: ']' },
            { open: '(', close: ')' },
            { open: '"', close: '"' },
            { open: "'", close: "'" }
        ],
        surroundingPairs: [
            { open: '{', close: '}' },
            { open: '[', close: ']' },
            { open: '(', close: ')' },
            { open: '"', close: '"' },
            { open: "'", close: "'" }
        ]
    });

    // Load editor settings from localStorage
    const savedSettings = getEditorSettings();
    
    editor = monaco.editor.create(document.getElementById('editor'), {
        value: '',
        language: 'nginx',
        theme: 'vs-dark',
        automaticLayout: true,
        fontSize: savedSettings.fontSize,
        lineNumbers: 'on',
        minimap: {
            enabled: savedSettings.minimap
        },
        scrollBeyondLastLine: false,
        wordWrap: savedSettings.wordWrap ? 'on' : 'off',
        tabSize: savedSettings.tabSize,
        insertSpaces: true,
        renderWhitespace: 'selection',
        formatOnPaste: true,
        formatOnType: true
    });

    // Register custom keyboard shortcuts
    registerCustomShortcuts();

    // Track content changes to detect unsaved changes
    editor.onDidChangeModelContent(() => {
        if (currentFile) {
            hasUnsavedChanges = true;
            updateEditorTitle();
        }
    });

    // Check if password change is required
    checkPasswordChangeRequired();

    // Load username
    loadUserInfo();

    // Add keyboard shortcuts
    setupKeyboardShortcuts();

    // Setup beforeunload warning
    setupBeforeUnloadWarning();

    // Load initial data after editor is ready
    loadFiles('/');
});

function setupBeforeUnloadWarning() {
    window.addEventListener('beforeunload', function(e) {
        if (hasUnsavedChanges) {
            // Most modern browsers ignore custom messages and show their own
            e.preventDefault();
            e.returnValue = ''; // Chrome requires returnValue to be set
            return ''; // Some browsers may still use this
        }
    });
}

function updateEditorTitle() {
    const titleElement = document.getElementById('editorTitle');
    if (currentFile) {
        const fileName = currentFile.split('/').pop();
        if (hasUnsavedChanges) {
            titleElement.textContent = fileName + ' (unsaved)';
            titleElement.style.color = '#f48771';
        } else {
            titleElement.textContent = fileName;
            titleElement.style.color = '#cccccc';
        }
    }
}

function loadUserInfo() {
    fetch('/api/settings')
    .then(r => r.json())
    .then(data => {
        if (data.username) {
            document.getElementById('username').textContent = data.username;
        }
    })
    .catch(e => console.error('Failed to load user info:', e));
}

function registerCustomShortcuts() {
    // Shortcuts are now handled by the global keyboard event listener
    // This function is kept for compatibility but does nothing
}

function getKeyMod(shortcut) {
    let mod = 0;
    if (shortcut.ctrl) mod |= monaco.KeyMod.CtrlCmd;
    if (shortcut.alt) mod |= monaco.KeyMod.Alt;
    if (shortcut.shift) mod |= monaco.KeyMod.Shift;
    return mod || null;
}

function recordShortcut(action, inputElement) {
    recordingShortcut = action;
    inputElement.value = 'Press your key combination...';
    inputElement.style.background = '#094771';
    inputElement.style.color = '#fff';
    
    const keyHandler = function(e) {
        e.preventDefault();
        
        // Ignore modifier-only presses
        if (['Control', 'Alt', 'Shift', 'Meta'].includes(e.key)) {
            return;
        }
        
        // Build shortcut object
        const shortcut = {
            key: getMonacoKeyName(e.key),
            ctrl: e.ctrlKey || e.metaKey,
            alt: e.altKey,
            shift: e.shiftKey,
            display: formatShortcutDisplay(e)
        };
        
        // Update the input
        inputElement.value = shortcut.display;
        inputElement.style.background = '#2d2d30';
        inputElement.style.color = '#4caf50';
        
        // Save to temp storage
        const shortcuts = getKeyboardShortcuts();
        shortcuts[action] = shortcut;
        
        // Remove listener
        document.removeEventListener('keydown', keyHandler);
        recordingShortcut = null;
    };
    
    document.addEventListener('keydown', keyHandler, { once: false });
    
    // Cancel recording if clicked elsewhere
    setTimeout(() => {
        const cancelHandler = function(e) {
            if (e.target !== inputElement && recordingShortcut === action) {
                document.removeEventListener('keydown', keyHandler);
                recordingShortcut = null;
                inputElement.style.background = '#2d2d30';
                inputElement.style.color = '#4caf50';
                // Restore previous value
                const shortcuts = getKeyboardShortcuts();
                inputElement.value = shortcuts[action]?.display || 'Not set';
                document.removeEventListener('click', cancelHandler);
            }
        };
        document.addEventListener('click', cancelHandler, { once: true });
    }, 100);
}

function getMonacoKeyName(key) {
    const keyMap = {
        "'": 'Quote',
        ' ': 'Space',
        'Enter': 'Enter',
        'Escape': 'Escape',
        'Tab': 'Tab',
        'Backspace': 'Backspace',
        'Delete': 'Delete',
        'ArrowUp': 'UpArrow',
        'ArrowDown': 'DownArrow',
        'ArrowLeft': 'LeftArrow',
        'ArrowRight': 'RightArrow'
    };
    
    return keyMap[key] || key.toUpperCase();
}

function formatShortcutDisplay(e) {
    const parts = [];
    if (e.ctrlKey || e.metaKey) parts.push('Ctrl');
    if (e.altKey) parts.push('Alt');
    if (e.shiftKey) parts.push('Shift');
    
    let keyName = e.key;
    if (keyName === "'") keyName = "'";
    else if (keyName === ' ') keyName = 'Space';
    else if (keyName.length === 1) keyName = keyName.toUpperCase();
    
    parts.push(keyName);
    return parts.join('+');
}

function resetShortcuts() {
    if (!confirm('Reset all keyboard shortcuts to defaults?')) return;
    
    localStorage.removeItem('keyboardShortcuts');
    
    // Update inputs
    document.getElementById('shortcutSave').value = 'Ctrl+S';
    document.getElementById('shortcutComment').value = "Ctrl+'";
    
    // Re-register shortcuts
    registerCustomShortcuts();
    
    showNotification('Keyboard shortcuts reset to defaults', 'success');
}

function setupKeyboardShortcuts() {
    // Track Ctrl key state for delete mode
    document.addEventListener('keydown', function(e) {
        // Handle Escape key to close delete modal
        if (e.key === 'Escape') {
            if (document.getElementById('deleteModal').classList.contains('show')) {
                hideDeleteModal();
            }
        }
        
        if (e.ctrlKey || e.metaKey) {
            if (!ctrlPressed) {
                ctrlPressed = true;
                updateFileListDeleteMode(true);
            }
        }
        
        // Prevent browser from intercepting our custom shortcuts only if Monaco is ready
        if (window.monaco && window.monaco.editor) {
            const shortcuts = getKeyboardShortcuts();
            
            // Check for save shortcut
            if (shortcuts.save) {
                const matchesSave = 
                    (shortcuts.save.ctrl && (e.ctrlKey || e.metaKey)) &&
                    (shortcuts.save.alt === e.altKey) &&
                    (shortcuts.save.shift === e.shiftKey) &&
                    (e.key.toLowerCase() === shortcuts.save.key.toLowerCase() || 
                     getMonacoKeyName(e.key) === shortcuts.save.key);
                
                if (matchesSave) {
                    e.preventDefault();
                    // Manually trigger save
                    if (typeof saveFile === 'function') {
                        saveFile();
                    }
                }
            }
            
            // Check for comment shortcut
            if (shortcuts.comment) {
                const matchesComment = 
                    (shortcuts.comment.ctrl && (e.ctrlKey || e.metaKey)) &&
                    (shortcuts.comment.alt === e.altKey) &&
                    (shortcuts.comment.shift === e.shiftKey) &&
                    (e.key === "'" || getMonacoKeyName(e.key) === shortcuts.comment.key);
                
                if (matchesComment) {
                    e.preventDefault();
                    // Manually trigger comment toggle
                    if (editor) {
                        editor.trigger('keyboard', 'editor.action.commentLine', {});
                    }
                }
            }
        }
    });

    document.addEventListener('keyup', function(e) {
        if (!e.ctrlKey && !e.metaKey) {
            if (ctrlPressed) {
                ctrlPressed = false;
                updateFileListDeleteMode(false);
            }
        }
    });

    // Also handle when window loses focus
    window.addEventListener('blur', function() {
        if (ctrlPressed) {
            ctrlPressed = false;
            updateFileListDeleteMode(false);
        }
    });
}

function updateFileListDeleteMode(isDeleteMode) {
    const fileItems = document.querySelectorAll('.file-item');
    fileItems.forEach(item => {
        if (isDeleteMode) {
            item.classList.add('delete-mode');
        } else {
            item.classList.remove('delete-mode');
        }
    });
}

function checkPasswordChangeRequired() {
    // Check if password change is required from session storage or by making an API call
    const mustChangePassword = sessionStorage.getItem('must_change_password') === 'true';
    if (mustChangePassword) {
        showForcePasswordChangeModal();
    }
}

function showForcePasswordChangeModal() {
    const modal = document.getElementById('forcePasswordChangeModal');
    modal.classList.add('show');
    // Disable closing by clicking outside
    modal.onclick = (e) => {
        e.stopPropagation();
    };
}

function changePasswordForced() {
    const currentPassword = document.getElementById('currentPassword').value;
    const newPassword = document.getElementById('newPassword').value;
    const confirmPassword = document.getElementById('confirmPassword').value;

    if (!currentPassword || !newPassword || !confirmPassword) {
        showNotification('Please fill in all fields', 'error');
        return;
    }

    if (newPassword.length < 8) {
        showNotification('New password must be at least 8 characters long', 'error');
        return;
    }

    if (newPassword !== confirmPassword) {
        showNotification('New passwords do not match', 'error');
        return;
    }

    fetch('/api/change-password', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ 
            current_password: currentPassword, 
            new_password: newPassword 
        })
    })
    .then(r => r.json())
    .then(data => {
        if (data.success) {
            showNotification('Password changed successfully!', 'success');
            sessionStorage.removeItem('must_change_password');
            document.getElementById('forcePasswordChangeModal').classList.remove('show');
            // Clear the form
            document.getElementById('currentPassword').value = '';
            document.getElementById('newPassword').value = '';
            document.getElementById('confirmPassword').value = '';
        } else {
            showNotification(data.error || 'Failed to change password', 'error');
        }
    })
    .catch(e => showNotification('Network error', 'error'));
}

function loadFiles(path) {
    currentPath = path;
    fetch('/api/files/list', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path })
    })
    .then(r => r.json())
    .then(data => {
        if (data.items) {
            renderFileList(data.items);
            renderBreadcrumb(data.current_path);
        } else {
            showNotification(data.error || 'Failed to load files', 'error');
        }
    })
    .catch(e => showNotification('Network error', 'error'));
}

function renderFileList(items) {
    const fileList = document.getElementById('fileList');
    fileList.innerHTML = '';

    items.forEach(item => {
        const div = document.createElement('div');
        div.className = 'file-item';
        
        // Apply delete-mode class if Ctrl is currently pressed
        if (ctrlPressed) {
            div.classList.add('delete-mode');
        }
        
        // Create the main clickable area
        const clickArea = document.createElement('div');
        clickArea.style.display = 'flex';
        clickArea.style.alignItems = 'center';
        clickArea.style.gap = '10px';
        clickArea.style.flex = '1';
        clickArea.style.cursor = 'pointer';
        clickArea.onclick = (e) => {
            // Check if Ctrl/Cmd is pressed - if so, delete instead of open
            if (e.ctrlKey || e.metaKey) {
                e.preventDefault();
                deleteItem(item.path, item.name, item.type);
            } else {
                if (item.type === 'directory') {
                    loadFiles(item.path);
                } else {
                    loadFile(item.path, item.name);
                }
            }
        };

        const icon = item.type === 'directory' ? '📁' : '📄';
        const size = item.type === 'file' ? formatBytes(item.size) : '';
        
        clickArea.innerHTML = `
            <div class="file-icon">${icon}</div>
            <div class="file-info">
                <div class="file-name">${item.name}</div>
                <div class="file-meta">${size}</div>
            </div>
        `;

        // Create delete button
        const deleteBtn = document.createElement('button');
        deleteBtn.className = 'file-delete-btn';
        deleteBtn.innerHTML = '🗑️';
        deleteBtn.title = `Delete ${item.type === 'directory' ? 'folder' : 'file'}`;
        deleteBtn.onclick = (e) => {
            e.stopPropagation(); // Prevent triggering the file/folder open
            deleteItem(item.path, item.name, item.type);
        };

        div.appendChild(clickArea);
        div.appendChild(deleteBtn);
        fileList.appendChild(div);
    });
}

function deleteItem(path, name, type) {
    // Store the item to delete
    deleteTarget = { path, name, type };
    
    // Set the confirmation message
    const itemType = type === 'directory' ? 'folder' : 'file';
    const confirmMsg = type === 'directory' 
        ? `Are you sure you want to delete the folder <strong>"${name}"</strong> and all its contents? This action cannot be undone.`
        : `Are you sure you want to delete the file <strong>"${name}"</strong>? This action cannot be undone.`;
    
    document.getElementById('deleteModalMessage').innerHTML = confirmMsg;
    document.getElementById('deleteModal').classList.add('show');
    
    // Auto-focus the delete button after a short delay
    setTimeout(() => {
        document.getElementById('confirmDeleteBtn').focus();
    }, 100);
}

function hideDeleteModal() {
    document.getElementById('deleteModal').classList.remove('show');
    deleteTarget = null;
}

function confirmDelete() {
    if (!deleteTarget) return;
    
    const { path, name, type } = deleteTarget;
    const itemType = type === 'directory' ? 'folder' : 'file';
    
    // Hide modal
    hideDeleteModal();

    fetch('/api/files/delete', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path: path })
    })
    .then(r => r.json())
    .then(data => {
        if (data.success) {
            showNotification(`${itemType.charAt(0).toUpperCase() + itemType.slice(1)} deleted successfully`, 'success');
            
            // If currently viewing the deleted file, clear the editor
            if (currentFile === path) {
                currentFile = null;
                document.getElementById('editorTitle').textContent = 'No file selected';
                document.getElementById('emptyState').style.display = 'flex';
                document.getElementById('editor').style.display = 'none';
                document.getElementById('saveBtn').style.display = 'none';
                document.getElementById('deleteBtn').style.display = 'none';
            }
            
            loadFiles(currentPath);
        } else {
            showNotification(data.error || `Failed to delete ${itemType}`, 'error');
        }
    })
    .catch(e => showNotification('Network error', 'error'));
}

function renderBreadcrumb(path) {
    const breadcrumb = document.getElementById('breadcrumb');
    const parts = path.split('/').filter(p => p);
    
    let html = '<span class="breadcrumb-item" onclick="loadFiles(\'/\')">🏠 Home</span>';
    let currentPath = '';
    
    parts.forEach(part => {
        currentPath += '/' + part;
        html += ` <span>/</span> <span class="breadcrumb-item" onclick="loadFiles('${currentPath}')">${part}</span>`;
    });
    
    breadcrumb.innerHTML = html;
}

function loadFile(path, name) {
    currentFile = path;
    
    fetch('/api/files/read', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path })
    })
    .then(r => r.json())
    .then(data => {
        if (data.content !== undefined) {
            editor.setValue(data.content);
            
            // Reset unsaved changes flag when loading a file
            hasUnsavedChanges = false;
            
            document.getElementById('editorTitle').textContent = name;
            document.getElementById('editorTitle').style.color = '#cccccc';
            document.getElementById('emptyState').style.display = 'none';
            document.getElementById('editor').style.display = 'block';
            document.getElementById('saveBtn').style.display = 'block';
            document.getElementById('deleteBtn').style.display = 'block';
        } else {
            showNotification(data.error || 'Failed to load file', 'error');
        }
    })
    .catch(e => showNotification('Network error', 'error'));
}

function saveFile() {
    if (!currentFile) return;

    const content = editor.getValue();
    
    fetch('/api/files/write', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path: currentFile, content })
    })
    .then(r => r.json())
    .then(data => {
        if (data.success) {
            showNotification('File saved successfully', 'success');
            
            // Clear unsaved changes flag after successful save
            hasUnsavedChanges = false;
            updateEditorTitle();
            
            // Refresh the file list to show backup files and updated sizes
            loadFiles(currentPath);
        } else {
            showNotification(data.error || 'Failed to save file', 'error');
        }
    })
    .catch(e => showNotification('Network error', 'error'));
}

function deleteFile() {
    if (!currentFile || !confirm('Are you sure you want to delete this file?')) return;

    fetch('/api/files/delete', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path: currentFile })
    })
    .then(r => r.json())
    .then(data => {
        if (data.success) {
            showNotification('File deleted successfully', 'success');
            currentFile = null;
            document.getElementById('editorTitle').textContent = 'No file selected';
            document.getElementById('emptyState').style.display = 'flex';
            document.getElementById('editor').style.display = 'none';
            document.getElementById('saveBtn').style.display = 'none';
            document.getElementById('deleteBtn').style.display = 'none';
            loadFiles(currentPath);
        } else {
            showNotification(data.error || 'Failed to delete file', 'error');
        }
    })
    .catch(e => showNotification('Network error', 'error'));
}

function showCreateModal(type) {
    createType = type;
    document.getElementById('createModalTitle').textContent = `Create New ${type === 'file' ? 'File' : 'Folder'}`;
    document.getElementById('newItemName').value = '';
    document.getElementById('createModal').classList.add('show');
    
    // Auto-focus the input field after a short delay to ensure modal is visible
    setTimeout(() => {
        document.getElementById('newItemName').focus();
    }, 100);
}

function hideCreateModal() {
    document.getElementById('createModal').classList.remove('show');
}

function handleCreateKeyPress(event) {
    // Submit on Enter key
    if (event.key === 'Enter') {
        event.preventDefault();
        createItem();
    }
}

function createItem() {
    const name = document.getElementById('newItemName').value.trim();
    if (!name) {
        showNotification('Please enter a name', 'error');
        return;
    }

    const path = currentPath === '/' ? `/${name}` : `${currentPath}/${name}`;

    fetch('/api/files/create', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path, type: createType })
    })
    .then(r => r.json())
    .then(data => {
        if (data.success) {
            showNotification(data.message, 'success');
            hideCreateModal();
            loadFiles(currentPath);
        } else {
            showNotification(data.error || 'Failed to create item', 'error');
        }
    })
    .catch(e => showNotification('Network error', 'error'));
}

function showSettings() {
    fetch('/api/settings')
    .then(r => r.json())
    .then(data => {
        document.getElementById('nginxDir').value = data.nginx_dir || '/etc/nginx';
        document.getElementById('settingsUsername').value = data.username || '';
        
        // Load Docker settings
        document.getElementById('dockerEnabled').checked = data.docker_enabled || false;
        document.getElementById('dockerContainerName').value = data.docker_container_name || '';
        
        // Show/hide Docker container name field based on checkbox
        toggleDockerContainerField();
        
        // Clear password fields
        document.getElementById('settingsCurrentPassword').value = '';
        document.getElementById('settingsNewPassword').value = '';
        document.getElementById('settingsConfirmPassword').value = '';
        
        // Load editor settings from localStorage
        const editorSettings = getEditorSettings();
        document.getElementById('editorFontSize').value = editorSettings.fontSize;
        document.getElementById('editorMinimap').checked = editorSettings.minimap;
        document.getElementById('editorWordWrap').checked = editorSettings.wordWrap;
        document.getElementById('editorTabSize').value = editorSettings.tabSize;
        
        // Load keyboard shortcuts
        const shortcuts = getKeyboardShortcuts();
        document.getElementById('shortcutSave').value = shortcuts.save?.display || 'Ctrl+S';
        document.getElementById('shortcutComment').value = shortcuts.comment?.display || "Ctrl+'";
        
        document.getElementById('settingsModal').classList.add('show');
    });
}

function applyEditorSettings(settings) {
    if (!editor) return;
    
    editor.updateOptions({
        fontSize: settings.fontSize,
        minimap: { enabled: settings.minimap },
        wordWrap: settings.wordWrap ? 'on' : 'off',
        tabSize: settings.tabSize
    });
}

function hideSettings() {
    document.getElementById('settingsModal').classList.remove('show');
}

function toggleDockerContainerField() {
    const dockerEnabled = document.getElementById('dockerEnabled').checked;
    const containerGroup = document.getElementById('dockerContainerGroup');
    if (dockerEnabled) {
        containerGroup.style.display = 'block';
    } else {
        containerGroup.style.display = 'none';
    }
}

// Add event listener for Docker checkbox
document.addEventListener('DOMContentLoaded', function() {
    const dockerCheckbox = document.getElementById('dockerEnabled');
    if (dockerCheckbox) {
        dockerCheckbox.addEventListener('change', toggleDockerContainerField);
    }
});

function saveSettings() {
    const nginxDir = document.getElementById('nginxDir').value.trim();
    const newUsername = document.getElementById('settingsUsername').value.trim();
    const currentPassword = document.getElementById('settingsCurrentPassword').value;
    const newPassword = document.getElementById('settingsNewPassword').value;
    const confirmPassword = document.getElementById('settingsConfirmPassword').value;
    
    // Get Docker settings
    const dockerEnabled = document.getElementById('dockerEnabled').checked;
    const dockerContainerName = document.getElementById('dockerContainerName').value.trim();
    
    // Validate Docker settings
    if (dockerEnabled && !dockerContainerName) {
        showNotification('Docker container name is required when Docker mode is enabled', 'error');
        return;
    }
    
    // Get editor settings
    const editorFontSize = parseInt(document.getElementById('editorFontSize').value);
    const editorMinimap = document.getElementById('editorMinimap').checked;
    const editorWordWrap = document.getElementById('editorWordWrap').checked;
    const editorTabSize = parseInt(document.getElementById('editorTabSize').value);
    
    // Validate editor settings
    if (editorFontSize < 10 || editorFontSize > 24) {
        showNotification('Font size must be between 10 and 24', 'error');
        return;
    }
    if (editorTabSize < 2 || editorTabSize > 8) {
        showNotification('Tab size must be between 2 and 8', 'error');
        return;
    }
    
    // Save editor settings to localStorage
    const editorSettings = {
        fontSize: editorFontSize,
        minimap: editorMinimap,
        wordWrap: editorWordWrap,
        tabSize: editorTabSize
    };
    localStorage.setItem('editorSettings', JSON.stringify(editorSettings));
    
    // Apply editor settings immediately
    applyEditorSettings(editorSettings);
    
    // Save keyboard shortcuts to localStorage
    const currentShortcuts = getKeyboardShortcuts();
    localStorage.setItem('keyboardShortcuts', JSON.stringify(currentShortcuts));
    
    // Re-register keyboard shortcuts with new bindings
    registerCustomShortcuts();
    
    // Check if password change is requested
    const changePassword = currentPassword || newPassword || confirmPassword;
    
    if (changePassword) {
        // Validate password change
        if (!currentPassword) {
            showNotification('Please enter your current password', 'error');
            return;
        }
        if (!newPassword) {
            showNotification('Please enter a new password', 'error');
            return;
        }
        if (newPassword.length < 8) {
            showNotification('New password must be at least 8 characters long', 'error');
            return;
        }
        if (newPassword !== confirmPassword) {
            showNotification('New passwords do not match', 'error');
            return;
        }
    }
    
    // Prepare update data
    const updates = {
        nginx_dir: nginxDir,
        docker_enabled: dockerEnabled,
        docker_container_name: dockerContainerName
    };
    
    if (newUsername) {
        updates.username = newUsername;
    }
    
    if (changePassword) {
        updates.current_password = currentPassword;
        updates.new_password = newPassword;
    }
    
    fetch('/api/settings', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(updates)
    })
    .then(r => r.json())
    .then(data => {
        if (data.success) {
            showNotification(data.message || 'Settings saved successfully', 'success');
            
            // Update username display if changed
            if (data.username) {
                document.getElementById('username').textContent = data.username;
            }
            
            hideSettings();
            
            // If password was changed, user might need to re-login
            if (changePassword && data.password_changed) {
                setTimeout(() => {
                    showNotification('Password changed. Please log in again.', 'success');
                    setTimeout(() => {
                        fetch('/logout', { method: 'POST' })
                        .then(() => window.location.href = '/login');
                    }, 2000);
                }, 1000);
            } else {
                loadFiles('/');
            }
        } else {
            showNotification(data.error || 'Failed to save settings', 'error');
        }
    })
    .catch(e => showNotification('Network error', 'error'));
}

function logout() {
    fetch('/logout', { method: 'POST' })
    .then(() => window.location.href = '/login');
}

function showNotification(message, type) {
    const notification = document.getElementById('notification');
    notification.textContent = message;
    notification.className = `notification ${type} show`;
    setTimeout(() => {
        notification.classList.remove('show');
    }, 3000);
}

function formatBytes(bytes) {
    if (bytes === 0) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return Math.round(bytes / Math.pow(k, i) * 100) / 100 + ' ' + sizes[i];
}

// Close modals on outside click
document.getElementById('createModal').addEventListener('click', (e) => {
    if (e.target.classList.contains('modal')) {
        hideCreateModal();
    }
});

document.getElementById('settingsModal').addEventListener('click', (e) => {
    if (e.target.classList.contains('modal')) {
        hideSettings();
    }
});

document.getElementById('deleteModal').addEventListener('click', (e) => {
    if (e.target.classList.contains('modal')) {
        hideDeleteModal();
    }
});
