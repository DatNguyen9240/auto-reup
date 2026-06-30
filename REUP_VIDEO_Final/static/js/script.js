/* ============================================
   REUP VIDEO DOUYIN - Application Logic
   Connected to FastAPI backend
   ============================================ */

// --- Config ---
const API_BASE = window.location.origin;
const WS_BASE = `${window.location.protocol === 'https:' ? 'wss:' : 'ws:'}//${window.location.host}`;

// --- Utility Functions ---
function $(selector) {
    return document.querySelector(selector);
}

function $$(selector) {
    return document.querySelectorAll(selector);
}

function showToast(message, type = 'info') {
    const container = $('#toast-container');
    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;

    const icons = {
        success: '✅',
        error: '❌',
        info: 'ℹ️',
        warning: '⚠️'
    };

    toast.innerHTML = `
        <span class="toast-icon">${icons[type] || icons.info}</span>
        <span>${message}</span>
    `;

    container.appendChild(toast);

    setTimeout(() => {
        toast.classList.add('toast-out');
        setTimeout(() => toast.remove(), 300);
    }, 3500);
}

function formatViews(count) {
    if (!count) return '0';
    if (count >= 1000000) return (count / 1000000).toFixed(1) + 'M';
    if (count >= 1000) return (count / 1000).toFixed(1) + 'K';
    return count.toString();
}

// --- Step Navigation ---
const steps = {
    hero: $('#step-hero'),
    info: $('#step-info'),
    processing: $('#step-processing'),
    queue: $('#step-queue'),
    editor: $('#step-editor'),
    complete: $('#step-complete')
};

function showStep(stepName) {
    Object.values(steps).forEach(step => {
        step.classList.remove('step-active');
    });
    steps[stepName].classList.add('step-active');
    window.scrollTo({ top: 0, behavior: 'smooth' });
}

// --- State ---
let currentVideoInfo = null;
let currentTaskId = null;
let currentUrl = null;
let ws = null;
let processStartTime = 0;
let currentSegments = [];
let currentTaskOptions = {};
let translationEngineMessage = '';
let currentBatchTasks = [];

function showReviewQueue(tasks) {
    currentBatchTasks = tasks;
    const queueContainer = $('#video-list-queue');
    queueContainer.innerHTML = '';
    
    tasks.forEach((task, idx) => {
        const isError = task.status === 'error';
        const isDone = task.status === 'completed';
        
        let statusHtml = '';
        let btnHtml = '';
        
        if (isError) {
            statusHtml = `<span style="color: #ef4444; font-size: 0.85rem;">❌ Lỗi: ${task.error}</span>`;
        } else if (isDone) {
            statusHtml = `<span style="color: #10b981; font-size: 0.85rem;">✅ Đã Render xong</span>`;
            btnHtml = `<a href="/api/download/${task.taskId}" download class="btn-primary" style="padding: 6px 12px; font-size: 0.85rem; text-decoration: none;">Tải xuống</a>`;
        } else {
            statusHtml = `<span style="color: #eab308; font-size: 0.85rem;">⏳ Chờ duyệt phụ đề</span>`;
            btnHtml = `<button class="btn-primary" onclick="reviewTask('${task.taskId}')" style="padding: 6px 12px; font-size: 0.85rem;">Duyệt & Chỉnh sửa</button>`;
        }
        
        queueContainer.innerHTML += `
            <div style="background: rgba(255,255,255,0.05); border: 1px solid rgba(255,255,255,0.1); border-radius: 12px; padding: 15px; display: flex; justify-content: space-between; align-items: center;">
                <div style="flex: 1; margin-right: 15px;">
                    <h4 style="margin: 0 0 5px 0; font-size: 1rem; color: #fff;">Video ${idx + 1}: ${task.title.substring(0, 50)}</h4>
                    ${statusHtml}
                </div>
                <div>
                    ${btnHtml}
                </div>
            </div>
        `;
    });
    
    showStep('queue');
}

window.reviewTask = function(taskId) {
    currentTaskId = taskId;
    const taskInQueue = currentBatchTasks.find(t => t.taskId === taskId);
    if (taskInQueue) {
        currentVideoInfo = { title: taskInQueue.title };
    }
    openSubtitleEditor(taskId);
};


// --- DOM Ready ---
document.addEventListener('DOMContentLoaded', () => {
    const urlError = $('#url-error');
    const btnCheckUrl = $('#btn-check-url');
    const btnBackToHero = $('#btn-back-to-hero');
    const btnStartProcess = $('#btn-start-process');
    const btnNewVideo = $('#btn-new-video');
    const btnDownload = $('#btn-download');
    const btnPreview = $('#btn-preview');

    // --- Extract Douyin URL from share text ---
    function extractDouyinUrl(text) {
        if (!text) return '';
        // Find any douyin/tiktok URL in the text
        const match = text.match(/https?:\/\/(v\.douyin\.com|www\.douyin\.com|douyin\.com|vm\.tiktok\.com|www\.tiktok\.com\/)[^\s\u4e00-\u9fff，。！？、]+/i);
        return match ? match[0].replace(/[，。！？、\s]+$/, '').trim() : text.trim();
    }

    // --- Example links ---
    $$('.example-link').forEach(btn => {
        btn.addEventListener('click', () => {
            const firstInput = document.getElementById('url-input-1');
            if (firstInput) {
                firstInput.value = btn.dataset.url;
                firstInput.focus();
                firstInput.dispatchEvent(new Event('input'));
                showToast('Đã điền link ví dụ', 'info');
            }
        });
    });

    let currentVideoInfos = [];
    let validUrls = [];
    
    const multiInputs = document.querySelectorAll('.multi-url-input');
    
    function getUrls() {
        return Array.from(multiInputs).map(inp => inp.value.trim()).filter(l => l);
    }

    // Handle single paste buttons
    document.querySelectorAll('.single-paste-btn').forEach(btn => {
        btn.addEventListener('click', async () => {
            try {
                const text = await navigator.clipboard.readText();
                const targetId = btn.getAttribute('data-target');
                const inp = document.getElementById(targetId);
                
                // If it's multiline, try to distribute it
                const lines = text.split('\n').map(l => l.trim()).filter(l => l);
                if (lines.length > 1) {
                    let lineIdx = 0;
                    for (let i = 0; i < multiInputs.length && lineIdx < lines.length; i++) {
                        // Only overwrite empty ones or the targeted one
                        if (multiInputs[i].id === targetId || !multiInputs[i].value.trim()) {
                            multiInputs[i].value = lines[lineIdx];
                            lineIdx++;
                        }
                    }
                } else {
                    if (inp) inp.value = text;
                }
                multiInputs[0].dispatchEvent(new Event('input'));
            } catch (err) {
                showToast('Không thể dán từ clipboard', 'error');
            }
        });
    });

    // Handle multiline paste into any input
    multiInputs.forEach(inp => {
        inp.addEventListener('input', () => {
            urlError.textContent = '';
            const urls = getUrls();
            $('#link-counter').textContent = `Đã nhập ${urls.length}/5 link`;
        });

        inp.addEventListener('paste', (e) => {
            const pasteData = (e.clipboardData || window.clipboardData).getData('text');
            const lines = pasteData.split('\n').map(l => l.trim()).filter(l => l);
            if (lines.length > 1) {
                e.preventDefault();
                let lineIdx = 0;
                for (let i = 0; i < multiInputs.length && lineIdx < lines.length; i++) {
                    if (multiInputs[i] === inp || !multiInputs[i].value.trim()) {
                        multiInputs[i].value = lines[lineIdx];
                        lineIdx++;
                    }
                }
                multiInputs[0].dispatchEvent(new Event('input'));
            }
        });
    });

    btnCheckUrl.addEventListener('click', async () => {
        const urls = getUrls();

        if (urls.length === 0) {
            urlError.textContent = 'Vui lòng dán ít nhất 1 link video Douyin';
            multiInputs[0].focus();
            return;
        }

        urlError.textContent = '';
        btnCheckUrl.disabled = true;
        
        currentVideoInfos = [];
        validUrls = [];

        try {
            for (let i = 0; i < urls.length; i++) {
                const url = urls[i];
                btnCheckUrl.querySelector('span').textContent = `Đang kiểm tra link ${i+1}/${urls.length}...`;
                
                const resp = await fetch(`${API_BASE}/api/check-url`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ url })
                });

                const data = await resp.json();

                if (!resp.ok) {
                    throw new Error(`Link thứ ${i+1} bị lỗi: ` + (data.detail || 'Lỗi kiểm tra URL'));
                }

                currentVideoInfos.push({ url: url, info: data.data });
                validUrls.push(url);
            }

            // Update video info UI
            $('#video-title').textContent = `Đã tải thông tin ${validUrls.length} video`;
            const detailsContainer = $('#video-details-container');
            detailsContainer.innerHTML = '';
            
            currentVideoInfos.forEach((item, idx) => {
                const info = item.info;
                const views = formatViews(info.view_count || 0);
                const title = info.title || 'Video Douyin';
                detailsContainer.innerHTML += `
                    <div style="margin-bottom: 8px; padding: 10px; background: rgba(0,0,0,0.2); border-radius: 8px; font-size: 0.9rem; text-align: left;">
                        <strong style="color: var(--primary);">Video ${idx + 1}:</strong> ${title.substring(0, 50)}${title.length > 50 ? '...' : ''}
                        <div style="color: #94a3b8; font-size: 0.8rem; margin-top: 4px;">⏱️ ${info.duration_short || '0:00'} | 👁️ ${views} lượt xem</div>
                    </div>
                `;
            });

            showToast(`Đã tải thành công ${validUrls.length} video!`, 'success');
            showStep('info');

        } catch (err) {
            urlError.textContent = err.message || 'Không thể kết nối server';
            showToast(err.message || 'Lỗi kiểm tra URL', 'error');
        } finally {
            btnCheckUrl.disabled = false;
            btnCheckUrl.querySelector('span').textContent = 'Kiểm tra & Tải thông tin';
        }
    });

    // Enter key to check URL (handled via multiInputs instead)
    multiInputs.forEach(inp => {
        inp.addEventListener('keypress', (e) => {
            if (e.key === 'Enter') btnCheckUrl.click();
        });
    });

    // --- Back button ---
    btnBackToHero.addEventListener('click', () => {
        showStep('hero');
    });

    // --- Voice section toggle ---
    const optVoiceover = $('#opt-voiceover input');
    const voiceSection = $('#voice-section');

    function updateVoiceVisibility() {
        voiceSection.style.display = optVoiceover.checked ? 'block' : 'none';
        if (optVoiceover.checked && !window._ttsEnginesLoaded) {
            loadTTSEngines();
        }
    }

    optVoiceover.addEventListener('change', updateVoiceVisibility);
    updateVoiceVisibility();

    // --- Keep original audio toggle ---
    const optKeepAudio = $('#opt-keep-audio input');
    const optKeepBgm = $('#opt-keep-bgm input');
    if (optKeepAudio) {
        optKeepAudio.addEventListener('change', () => {
            if (optKeepAudio.checked) {
                // Uncheck voiceover and disable it
                optVoiceover.checked = false;
                updateVoiceVisibility();
                $('#opt-voiceover').style.opacity = '0.5';
                $('#opt-voiceover').style.pointerEvents = 'none';
                if (optKeepBgm) {
                    optKeepBgm.checked = false;
                    $('#opt-keep-bgm').style.opacity = '0.5';
                    $('#opt-keep-bgm').style.pointerEvents = 'none';
                }
            } else {
                $('#opt-voiceover').style.opacity = '1';
                $('#opt-voiceover').style.pointerEvents = 'auto';
            }
        });
    }

    // --- Start Processing (REAL API) ---
    btnStartProcess.addEventListener('click', async () => {
        const keyInputs = document.querySelectorAll('.gemini-key-input');
        const geminiApiKeyList = Array.from(keyInputs).map(input => input.value.trim()).filter(k => k);
        
        if (geminiApiKeyList.length > 0) {
            localStorage.setItem('geminiApiKeyList', JSON.stringify(geminiApiKeyList));
        } else {
            localStorage.removeItem('geminiApiKeyList');
            localStorage.removeItem('geminiApiKey'); // clear old key
        }

        const baseOptions = {
            translate: $('#opt-translate input').checked,
            subtitle: $('#opt-subtitle input').checked,
            voiceover: optKeepAudio && optKeepAudio.checked ? false : $('#opt-voiceover input').checked,
            watermark: $('#opt-watermark input').checked,
            keep_audio: optKeepAudio ? optKeepAudio.checked : false,
            keep_bgm: optKeepBgm ? optKeepBgm.checked : false,
            voice: $('#selected-voice-key')?.value || 'edge_female',
            gemini_api_key: geminiApiKeyList,
            auto_render: false // Option B: Dừng lại chờ duyệt
        };

        if (!baseOptions.translate && !baseOptions.subtitle && !baseOptions.voiceover && !baseOptions.watermark) {
            showToast('Vui lòng chọn ít nhất 1 tùy chọn xử lý', 'warning');
            return;
        }

        btnStartProcess.disabled = true;
        btnStartProcess.innerHTML = '<span class="loader"></span> Đang xử lý...';
        
        showStep('processing');
        let completedTasks = [];

        for (let i = 0; i < validUrls.length; i++) {
            const url = validUrls[i];
            const currentOptions = { ...baseOptions, url: url };
            
            $('.processing-title').textContent = `Đang xử lý Video ${i + 1}/${validUrls.length}`;
            $('#processing-status').textContent = 'Khởi tạo...';
            resetProcessingSteps();
            translationEngineMessage = ''; // Reset message
            
            try {
                const taskId = await processSingleVideo(currentOptions);
                completedTasks.push({ 
                    url: url, 
                    taskId: taskId, 
                    title: currentVideoInfos[i].info.title,
                    status: 'review_ready'
                });
            } catch (err) {
                showToast(`Lỗi xử lý video ${i + 1}: ${err.message}`, 'error');
                completedTasks.push({
                    url: url,
                    taskId: null,
                    title: currentVideoInfos[i].info.title,
                    status: 'error',
                    error: err.message
                });
            }
        }
        
        btnStartProcess.disabled = false;
        btnStartProcess.innerHTML = '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M5 12l5 5l10 -10"/></svg><span>Bắt đầu tạo Video</span><div class="btn-shimmer"></div>';
        
        if (completedTasks.length > 0) {
            showReviewQueue(completedTasks);
        } else {
            showToast('Không có video nào được xử lý thành công!', 'error');
            showStep('info');
        }
    });

    // --- Process Single Video Promise ---
    function processSingleVideo(options) {
        return new Promise(async (resolve, reject) => {
            try {
                const resp = await fetch(`${API_BASE}/api/process`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(options)
                });

                const data = await resp.json();

                if (!resp.ok) {
                    throw new Error(data.detail || 'Lỗi bắt đầu xử lý');
                }

                const taskId = data.task_id;

                // Build step mapping based on options
                const stepMap = buildActiveSteps(options);
                
                if (ws) { ws.close(); }
                ws = new WebSocket(`${WS_BASE}/ws/progress/${taskId}`);

                ws.onopen = () => {
                    setInterval(() => {
                        if (ws && ws.readyState === WebSocket.OPEN) {
                            ws.send('ping');
                        }
                    }, 15000);
                };

                ws.onmessage = (event) => {
                    if (event.data === 'pong') return;

                    try {
                        const msg = JSON.parse(event.data);
                        handleProgress(msg, stepMap);
                        
                        if (msg.status === 'review_ready' || msg.status === 'completed') {
                            ws.close();
                            resolve(taskId);
                        } else if (msg.status === 'error') {
                            ws.close();
                            reject(new Error(msg.message || 'Lỗi không xác định trong quá trình xử lý'));
                        }
                    } catch (e) {
                        console.error('WebSocket message error:', e);
                    }
                };

                ws.onerror = (err) => {
                    reject(new Error('Mất kết nối server (WebSocket)'));
                };

            } catch (err) {
                reject(err);
            }
        });
    }

    // --- Show Queue UI (moved to global scope) ---

    $('#btn-new-batch')?.addEventListener('click', () => {
        $('#btn-new-video').click();
    });
    
    $('#btn-back-to-queue')?.addEventListener('click', () => {
        showStep('queue');
    });

    // --- New Video ---
    btnNewVideo.addEventListener('click', () => {
        document.querySelectorAll('.multi-url-input').forEach(inp => inp.value = '');
        currentVideoInfo = null;
        currentTaskId = null;
        currentUrl = null;
        if (ws) { ws.close(); ws = null; }
        resetProcessingSteps();
        showStep('hero');
    });

    // --- Preview ---
    btnPreview.addEventListener('click', () => {
        if (!currentTaskId) return;

        const previewUrl = `${API_BASE}/api/preview/${currentTaskId}`;
        const resultVideo = $('#result-video');
        resultVideo.innerHTML = `
            <video controls autoplay style="width:100%;height:100%;position:absolute;inset:0;object-fit:contain;background:#000;">
                <source src="${previewUrl}" type="video/mp4">
                Trình duyệt không hỗ trợ video.
            </video>
        `;
        showToast('Đang tải video xem trước...', 'info');
    });

    // --- Download ---
    btnDownload.addEventListener('click', () => {
        if (!currentTaskId) return;

        const downloadUrl = `${API_BASE}/api/download/${currentTaskId}`;
        const a = document.createElement('a');
        a.href = downloadUrl;
        a.download = `reup_video_${currentTaskId}.mp4`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);

        showToast('Đang tải video xuống...', 'success');
    });

    // Voice preview is now handled dynamically in TTS engine cards
});

// ============================================
// TTS ENGINE CARDS SYSTEM
// ============================================
let _previewAudio = null;
window._ttsEnginesLoaded = false;

const ENGINE_ICONS = {
    microsoft: `<svg width="24" height="24" viewBox="0 0 24 24"><rect x="1" y="1" width="10" height="10" fill="#f25022"/><rect x="13" y="1" width="10" height="10" fill="#7fba00"/><rect x="1" y="13" width="10" height="10" fill="#00a4ef"/><rect x="13" y="13" width="10" height="10" fill="#ffb900"/></svg>`,
    google: `<svg width="24" height="24" viewBox="0 0 24 24"><path d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92a5.06 5.06 0 0 1-2.2 3.32v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.1z" fill="#4285F4"/><path d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" fill="#34A853"/><path d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z" fill="#FBBC05"/><path d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z" fill="#EA4335"/></svg>`,
    kokoro: `<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2z"/><path d="M8 14s1.5 2 4 2 4-2 4-2"/><circle cx="9" cy="9" r="1.5" fill="currentColor"/><circle cx="15" cy="9" r="1.5" fill="currentColor"/></svg>`,
};

const ENGINE_COLORS = {
    'edge-tts': { bg: 'rgba(99, 102, 241, 0.08)', border: 'rgba(99, 102, 241, 0.25)', accent: '#6366f1' },
    'gtts': { bg: 'rgba(16, 185, 129, 0.08)', border: 'rgba(16, 185, 129, 0.25)', accent: '#10b981' },
    'kokoro': { bg: 'rgba(168, 85, 247, 0.08)', border: 'rgba(168, 85, 247, 0.25)', accent: '#a855f7' },
};

async function loadTTSEngines() {
    const grid = $('#tts-engine-grid');
    try {
        const resp = await fetch(`${API_BASE}/api/tts-engines`);
        const data = await resp.json();
        if (data.status !== 'ok') throw new Error('Failed to load engines');

        grid.innerHTML = '';
        const engines = data.engines;
        let totalVoices = 0;

        // Define display order
        const engineOrder = ['edge-tts', 'gtts', 'kokoro'];

        for (const engineKey of engineOrder) {
            const engine = engines[engineKey];
            if (!engine) continue;
            totalVoices += engine.voices.length;

            const colors = ENGINE_COLORS[engineKey] || ENGINE_COLORS['edge-tts'];
            const icon = ENGINE_ICONS[engine.icon] || ENGINE_ICONS.microsoft;

            const card = document.createElement('div');
            card.className = 'tts-engine-card';
            card.dataset.engine = engineKey;
            if (engineKey === 'edge-tts') card.classList.add('tts-engine-active');

            const typeBadge = engine.type === 'cloud'
                ? '<span class="tts-type-badge tts-type-cloud">☁️ Cloud</span>'
                : '<span class="tts-type-badge tts-type-local">💻 Local</span>';

            const availBadge = engine.available
                ? '<span class="tts-avail-badge tts-avail-ready">✅ Sẵn sàng</span>'
                : '<span class="tts-avail-badge tts-avail-install">⬇️ Cần cài</span>';

            // Build voice select options
            let voiceSelectHTML = '';
            if (engine.voices.length === 1) {
                voiceSelectHTML = `
                    <div class="tts-single-voice">
                        <span class="tts-voice-label">${engine.voices[0].label}</span>
                        <span class="tts-voice-desc">${engine.voices[0].description}</span>
                    </div>`;
            } else {
                const options = engine.voices.map((v, idx) => {
                    const genderIcon = v.gender === 'female' ? '♀' : v.gender === 'male' ? '♂' : '◉';
                    return `<option value="${v.key}" ${idx === 0 ? 'selected' : ''}>${genderIcon} ${v.label} — ${v.description}</option>`;
                }).join('');
                voiceSelectHTML = `
                    <select class="tts-voice-select" data-engine="${engineKey}">
                        ${options}
                    </select>`;
            }

            card.innerHTML = `
                <div class="tts-engine-header" style="border-color: ${colors.accent}">
                    <div class="tts-engine-icon">${icon}</div>
                    <div class="tts-engine-meta">
                        <span class="tts-engine-name">${engine.label}</span>
                        <div class="tts-engine-badges">
                            ${typeBadge}
                            ${availBadge}
                            <span class="tts-voice-count">${engine.voices.length} giọng</span>
                        </div>
                    </div>
                </div>
                <div class="tts-engine-body">
                    ${voiceSelectHTML}
                    <button class="btn-tts-preview" data-engine="${engineKey}" title="Nghe thử">
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><polygon points="5 3 19 12 5 21 5 3"/></svg>
                        <span>Nghe thử</span>
                    </button>
                </div>
            `;

            // Click card to select engine
            card.addEventListener('click', (e) => {
                if (e.target.closest('.btn-tts-preview') || e.target.closest('.tts-voice-select')) return;
                selectTTSEngine(card, engineKey);
            });

            grid.appendChild(card);
        }

        // Update total voice count
        const countBadge = $('#voice-count-badge');
        if (countBadge) countBadge.textContent = `${totalVoices} giọng`;

        // Attach preview handlers
        grid.querySelectorAll('.btn-tts-preview').forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.stopPropagation();
                previewTTSVoice(btn);
            });
        });

        // Attach select change handlers
        grid.querySelectorAll('.tts-voice-select').forEach(sel => {
            sel.addEventListener('change', () => {
                const engineKey = sel.dataset.engine;
                const card = sel.closest('.tts-engine-card');
                selectTTSEngine(card, engineKey);
            });
            sel.addEventListener('click', (e) => e.stopPropagation());
        });

        // Auto-select first engine
        selectTTSEngine(grid.querySelector('.tts-engine-card'), 'edge-tts');

        window._ttsEnginesLoaded = true;
    } catch (err) {
        console.error('Failed to load TTS engines:', err);
        grid.innerHTML = `
            <div class="tts-error">
                <span>⚠️ Không thể tải danh sách giọng nói. Server đang chạy?</span>
            </div>`;
    }
}

function selectTTSEngine(card, engineKey) {
    // Remove active from all cards
    $$('.tts-engine-card').forEach(c => c.classList.remove('tts-engine-active'));
    card.classList.add('tts-engine-active');

    // Get selected voice key
    const select = card.querySelector('.tts-voice-select');
    let voiceKey;
    if (select) {
        voiceKey = select.value;
    } else {
        // Single voice engine - find the voice key from card data
        const engines = card.closest('#tts-engine-grid');
        const allCards = engines.querySelectorAll('.tts-engine-card');
        // We need to find the first voice key of this engine
        // Use a data attribute or fallback to mapping
        const engineMap = {
            'edge-tts': 'edge_female',
            'gtts': 'gtts_vi',
            'kokoro': 'kokoro_diem_trinh',
        };
        voiceKey = engineMap[engineKey] || 'edge_female';
    }

    $('#selected-voice-key').value = voiceKey;
}

async function previewTTSVoice(btn) {
    const engineKey = btn.dataset.engine;
    const card = btn.closest('.tts-engine-card');
    const select = card.querySelector('.tts-voice-select');
    let voiceKey;

    if (select) {
        voiceKey = select.value;
    } else {
        const engineMap = {
            'edge-tts': 'edge_female',
            'gtts': 'gtts_vi',
            'kokoro': 'kokoro_diem_trinh',
        };
        voiceKey = engineMap[engineKey] || 'edge_female';
    }

    // Stop any playing preview
    if (_previewAudio) {
        _previewAudio.pause();
        _previewAudio = null;
    }

    // Show loading state
    const origHTML = btn.innerHTML;
    btn.innerHTML = '<div class="spinner-tiny"></div><span>Đang tải...</span>';
    btn.disabled = true;

    try {
        const previewUrl = `${API_BASE}/api/tts-preview/${voiceKey}`;
        _previewAudio = new Audio(previewUrl);
        _previewAudio.play();

        _previewAudio.onended = () => {
            btn.innerHTML = origHTML;
            btn.disabled = false;
        };
        _previewAudio.onerror = () => {
            showToast('Không thể phát audio preview', 'error');
            btn.innerHTML = origHTML;
            btn.disabled = false;
        };

        // Auto-select this engine
        selectTTSEngine(card, engineKey);

        setTimeout(() => {
            btn.innerHTML = origHTML;
            btn.disabled = false;
        }, 8000);
    } catch (err) {
        showToast('Lỗi preview: ' + err.message, 'error');
        btn.innerHTML = origHTML;
        btn.disabled = false;
    }
}

// --- WebSocket for Real-time Progress ---
function connectWebSocket(taskId, options) {
    if (ws) { ws.close(); }

    ws = new WebSocket(`${WS_BASE}/ws/progress/${taskId}`);

    // Build step mapping based on options
    const activeSteps = buildActiveSteps(options);

    ws.onopen = () => {
        console.log('WebSocket connected for task:', taskId);
        // Send keep-alive pings
        setInterval(() => {
            if (ws && ws.readyState === WebSocket.OPEN) {
                ws.send('ping');
            }
        }, 15000);
    };

    ws.onmessage = (event) => {
        if (event.data === 'pong') return;

        try {
            const data = JSON.parse(event.data);
            handleProgress(data, activeSteps);
        } catch (e) {
            console.error('WebSocket message error:', e);
        }
    };

    ws.onerror = (err) => {
        console.error('WebSocket error:', err);
    };

    ws.onclose = () => {
        console.log('WebSocket closed');
    };
}

function buildActiveSteps(options) {
    const stepMap = {
        'download': 'ps-download',
        'watermark': 'ps-watermark',
        'transcribe': 'ps-translate',  // STT maps to translate UI step
        'translate': 'ps-translate',
        'blur_chinese': 'ps-translate',  // blur is handled in render step, maps to translate
        'voiceover': 'ps-voiceover',
        'render': 'ps-render',
    };

    // Show/hide steps based on options
    const allStepIds = ['ps-download', 'ps-watermark', 'ps-translate', 'ps-voiceover', 'ps-subtitle', 'ps-render'];

    // ps-translate covers both transcribe and translate
    const showIds = new Set(['ps-download', 'ps-render']);
    if (options.watermark) showIds.add('ps-watermark');
    if (options.translate || options.subtitle || options.blur_chinese) showIds.add('ps-translate');
    if (options.voiceover) showIds.add('ps-voiceover');
    if (options.subtitle) showIds.add('ps-subtitle');

    allStepIds.forEach(id => {
        const el = document.getElementById(id);
        if (el) {
            el.style.display = showIds.has(id) ? 'flex' : 'none';
        }
    });

    return stepMap;
}

function handleProgress(data, stepMap) {
    const { type, step, progress, message, step_percent, file_size_mb } = data;

    if (type === 'progress') {
        // Update progress bar
        updateProgressBar(progress, message);

        // Update step status
        const uiStepId = stepMap[step];
        if (uiStepId) {
            updateProcessStep(uiStepId, step_percent, message);
        }

        // Special: when transcribe starts, also activate the translate UI row
        if (step === 'transcribe' || step === 'translate') {
            updateProcessStep('ps-translate', step_percent,
                step === 'transcribe' ? 'Nhận diện + Dịch nội dung...' : message);
            
            if (step === 'translate' && step_percent === 100) {
                translationEngineMessage = message;
            }
        }

        // When subtitle step is active in render
        if (step === 'render' && step_percent < 30) {
            const subEl = document.getElementById('ps-subtitle');
            if (subEl && subEl.style.display !== 'none') {
                subEl.classList.add('active');
                subEl.querySelector('.ps-status').textContent = 'Đang tạo phụ đề...';
            }
        }
        if (step === 'render' && step_percent >= 30) {
            const subEl = document.getElementById('ps-subtitle');
            if (subEl && subEl.style.display !== 'none') {
                subEl.classList.remove('active');
                subEl.classList.add('done');
                subEl.querySelector('.ps-status').textContent = 'Hoàn thành ✓';
            }
        }
    }

    if (type === 'complete') {
        // Mark all visible steps as done
        document.querySelectorAll('.process-step').forEach(el => {
            if (el.style.display !== 'none') {
                el.classList.remove('active');
                el.classList.add('done');
                const statusEl = el.querySelector('.ps-status');
                // Preserve the custom translation engine message if present
                if (!statusEl.textContent.includes('Dùng') && !statusEl.textContent.includes('dùng')) {
                    statusEl.textContent = 'Hoàn thành ✓';
                }
            }
        });

        updateProgressBar(100, 'Hoàn tất!');

        // Calculate processing time
        const elapsed = Math.round((Date.now() - processStartTime) / 1000);
        $('#process-time').textContent = `${elapsed} giây`;

        if (file_size_mb) {
            $('#file-size').textContent = `~${file_size_mb} MB`;
        }

        setTimeout(() => {
            // Go to editor step instead of complete
            openSubtitleEditor();
            showToast('Video xử lý xong! Chỉnh sửa phụ đề nếu cần.', 'success');
        }, 800);
    }

    if (type === 'error') {
        showToast(message || 'Đã xảy ra lỗi', 'error');
        updateProgressBar(0, message);
        $('#processing-status').textContent = message;
    }
}

function updateProgressBar(percent, message) {
    const progressFill = $('#progress-fill');
    const progressGlow = $('#progress-glow');
    const progressPercent = $('#progress-percent');
    const progressEta = $('#progress-eta');
    const statusEl = $('#processing-status');

    progressFill.style.width = percent + '%';
    progressGlow.style.width = percent + '%';
    progressPercent.textContent = percent + '%';
    statusEl.textContent = message || '';

    const remaining = Math.max(0, Math.round((100 - percent) * 0.6));
    progressEta.textContent = remaining > 0 ? `~${remaining} giây còn lại` : 'Sắp hoàn thành...';
}

function updateProcessStep(stepId, percent, message) {
    const el = document.getElementById(stepId);
    if (!el) return;

    if (percent >= 100) {
        el.classList.remove('active');
        el.classList.add('done');
        el.querySelector('.ps-status').textContent = 'Hoàn thành ✓';
    } else if (percent > 0) {
        el.classList.add('active');
        el.classList.remove('done');
        el.querySelector('.ps-status').textContent = message || 'Đang thực hiện...';
    }
}

// --- Processing Steps Reset ---
function resetProcessingSteps() {
    const stepIds = ['ps-download', 'ps-watermark', 'ps-translate', 'ps-voiceover', 'ps-subtitle', 'ps-render'];
    stepIds.forEach(id => {
        const el = document.getElementById(id);
        if (el) {
            el.classList.remove('active', 'done');
            el.querySelector('.ps-status').textContent = 'Chờ xử lý';
        }
    });
    $('#progress-fill').style.width = '0%';
    $('#progress-glow').style.width = '0%';
    $('#progress-percent').textContent = '0%';
}

// --- Keyboard shortcuts ---
document.addEventListener('keydown', (e) => {
    if (e.ctrlKey && e.key === 'v' && steps.hero.classList.contains('step-active')) {
        const urlInput1 = $('#url-input-1');
        const activeNode = document.activeElement;
        if (activeNode && !activeNode.classList.contains('multi-url-input')) {
            if (urlInput1) urlInput1.focus();
        }
    }

    // Load saved API keys on startup
    const savedApiKeyListStr = localStorage.getItem('geminiApiKeyList');
    if (savedApiKeyListStr) {
        try {
            const savedKeys = JSON.parse(savedApiKeyListStr);
            const keyInputs = document.querySelectorAll('.gemini-key-input');
            savedKeys.forEach((key, index) => {
                if (keyInputs[index]) {
                    keyInputs[index].value = key;
                }
            });
        } catch(e) {}
    } else {
        // Fallback to old single key
        const savedApiKey = localStorage.getItem('geminiApiKey');
        if (savedApiKey) {
            const keyInputs = document.querySelectorAll('.gemini-key-input');
            if (keyInputs[0]) keyInputs[0].value = savedApiKey;
        }
    }
});

// ============================================
// SUBTITLE EDITOR
// ============================================
function formatSrtTime(seconds) {
    seconds = parseFloat(seconds) || 0;
    const h = Math.floor(seconds / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    const s = Math.floor(seconds % 60);
    const ms = Math.floor((seconds % 1) * 1000);
    return `${String(h).padStart(2,'0')}:${String(m).padStart(2,'0')}:${String(s).padStart(2,'0')},${String(ms).padStart(3,'0')}`;
}

function parseSrtTime(str) {
    const parts = str.replace(',', '.').split(':');
    if (parts.length === 3) {
        return parseFloat(parts[0]) * 3600 + parseFloat(parts[1]) * 60 + parseFloat(parts[2]);
    }
    return 0;
}

async function openSubtitleEditor() {
    if (!currentTaskId) return;

    try {
        const response = await fetch(`${API_BASE}/api/segments/${currentTaskId}`);
        if (!response.ok) throw new Error('Failed to load segments');
        const data = await response.json();
        
        if (!data.segments || data.segments.length === 0) {
            showStep('complete');
            return;
        }
        
        currentSegments = data.segments;
        
        // Set header info
        $('#editor-filename').textContent = (currentVideoInfo?.title || 'video') + '.mp4';
        $('#editor-seg-count').textContent = `${currentSegments.length} segments`;

    } catch (err) {
        console.error('Lỗi khi tải phụ đề:', err);
        showStep('complete');
        return;
    }

    // Set video src to preview
    const videoSrc = `${API_BASE}/api/preview/${currentTaskId}`;
    $('#editor-video-src').src = videoSrc;
    const videoEl = $('#editor-video');
    videoEl.load();
    
    $('#draggable-sub').style.display = 'block';

    // Populate translation info box
    const infoBox = $('#editor-translation-info');
    const descEl = $('#translation-engine-desc');
    if (translationEngineMessage) {
        // Extract the part in parentheses
        const match = translationEngineMessage.match(/\((.*?)\)/);
        let msgToShow = translationEngineMessage;
        
        infoBox.classList.remove('success', 'warning');
        
        if (translationEngineMessage.includes('Gemini AI')) {
            infoBox.classList.add('success');
            if (match) msgToShow = match[1];
        } else if (translationEngineMessage.includes('Google Translate') || translationEngineMessage.includes('dự phòng')) {
            infoBox.classList.add('warning');
            if (match) msgToShow = "Sử dụng Google Translate dự phòng (Gemini hiện đang quá tải)";
        }
        
        descEl.textContent = msgToShow;
        infoBox.style.display = 'flex';
    } else {
        infoBox.style.display = 'none';
    }

    // Render segments
    renderSegmentCards();

    // Video time update → highlight active segment
    videoEl.addEventListener('timeupdate', onVideoTimeUpdate);
    showStep('editor');
}

function renderSegmentCards() {
    const container = $('#editor-segments');
    container.innerHTML = '';

    currentSegments.forEach((seg, i) => {
        const words = (seg.text_vi || '').split(/\s+/).filter(Boolean).length;
        const card = document.createElement('div');
        card.className = 'seg-card';
        card.dataset.idx = i;

        card.innerHTML = `
            <div class="seg-time-row">
                <div class="seg-time">
                    <input type="text" class="seg-start" value="${formatSrtTime(seg.start)}" data-idx="${i}">
                    <span class="seg-time-arrow">→</span>
                    <input type="text" class="seg-end" value="${formatSrtTime(seg.end)}" data-idx="${i}">
                </div>
                <span class="seg-words">${words} words</span>
            </div>
            <div class="seg-zh">${seg.text_zh || ''}</div>
            <textarea class="seg-vi-input" data-idx="${i}" rows="1">${seg.text_vi || ''}</textarea>
        `;

        container.appendChild(card);
    });

    // Auto-resize textareas
    $$('.seg-vi-input').forEach(ta => {
        ta.style.height = 'auto';
        ta.style.height = ta.scrollHeight + 'px';

        ta.addEventListener('input', (e) => {
            const idx = parseInt(e.target.dataset.idx);
            currentSegments[idx].text_vi = e.target.value;
            e.target.style.height = 'auto';
            e.target.style.height = e.target.scrollHeight + 'px';
            // Update word count
            const words = e.target.value.split(/\s+/).filter(Boolean).length;
            e.target.closest('.seg-card').querySelector('.seg-words').textContent = `${words} words`;
        });
    });

    // Time input handlers
    $$('.seg-start').forEach(inp => {
        inp.addEventListener('change', (e) => {
            const idx = parseInt(e.target.dataset.idx);
            currentSegments[idx].start = parseSrtTime(e.target.value);
        });
    });
    $$('.seg-end').forEach(inp => {
        inp.addEventListener('change', (e) => {
            const idx = parseInt(e.target.dataset.idx);
            currentSegments[idx].end = parseSrtTime(e.target.value);
        });
    });

    // Click card to jump video
    $$('.seg-card').forEach(card => {
        card.addEventListener('click', (e) => {
            if (e.target.tagName === 'TEXTAREA' || e.target.tagName === 'INPUT') return;
            const idx = parseInt(card.dataset.idx);
            const videoEl = $('#editor-video');
            videoEl.currentTime = currentSegments[idx]?.start || 0;
            videoEl.play();
        });
    });
}

function onVideoTimeUpdate() {
    const videoEl = $('#editor-video');
    const currentTime = videoEl.currentTime;

    let activeIdx = -1;
    for (let i = 0; i < currentSegments.length; i++) {
        if (currentTime >= currentSegments[i].start && currentTime <= currentSegments[i].end) {
            activeIdx = i;
            break;
        }
    }

    // Highlight active card
    $$('.seg-card').forEach((card, i) => {
        card.classList.toggle('seg-active', i === activeIdx);
    });
}

// --- Editor Button Handlers ---
document.addEventListener('DOMContentLoaded', () => {
    // Skip editor → go to queue or complete
    $('#btn-skip-editor')?.addEventListener('click', () => {
        if (!currentTaskId) return;
        const taskInQueue = currentBatchTasks.find(t => t.taskId === currentTaskId);
        if (taskInQueue) {
            taskInQueue.status = 'completed';
            showReviewQueue(currentBatchTasks);
        } else {
            const elapsed = Math.round((Date.now() - processStartTime) / 1000);
            $('#process-time').textContent = `${elapsed} giây`;
            showStep('complete');
        }
    });

    $('#btn-complete-back-queue')?.addEventListener('click', () => {
        if (currentBatchTasks && currentBatchTasks.length > 0) {
            showReviewQueue(currentBatchTasks);
        } else {
            showStep('hero');
        }
    });
    // Save & Re-render
    $('#btn-save-render')?.addEventListener('click', async () => {
        if (!currentTaskId) return;

        const btn = $('#btn-save-render');
        if (btn.disabled) return; // Prevent double-click
        btn.disabled = true;
        btn.innerHTML = `
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="animation:spin 1s linear infinite">
                <line x1="12" y1="2" x2="12" y2="6"/><line x1="12" y1="18" x2="12" y2="22"/>
                <line x1="4.93" y1="4.93" x2="7.76" y2="7.76"/><line x1="16.24" y1="16.24" x2="19.07" y2="19.07"/>
                <line x1="2" y1="12" x2="6" y2="12"/><line x1="18" y1="12" x2="22" y2="12"/>
                <line x1="4.93" y1="19.07" x2="7.76" y2="16.24"/><line x1="16.24" y1="7.76" x2="19.07" y2="4.93"/>
            </svg>
            <span>Đang lưu & render... 0%</span>
        `;

        try {
            // 1. Save segments
            await fetch(`${API_BASE}/api/segments/${currentTaskId}`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ segments: currentSegments })
            });

            showToast('Đã lưu phụ đề, đang render lại video...', 'info');

            // 1.5 Compute absolute drag position as percentage of real video BEFORE clearing src
            const video = document.getElementById('editor-video');
            const dragSub = document.getElementById('draggable-sub');
            let posX = 50.0;
            let posY = 85.0;
            
            if (video && dragSub && dragSub.style.display !== 'none' && video.videoHeight > 0) {
                const rect = video.getBoundingClientRect();
                const videoRatio = video.videoWidth / video.videoHeight;
                const boxRatio = rect.width / rect.height;
                
                let drawnWidth = rect.width;
                let drawnHeight = rect.height;
                if (videoRatio > boxRatio) {
                    drawnHeight = rect.width / videoRatio;
                } else {
                    drawnWidth = rect.height * videoRatio;
                }
                
                const blackBarX = (rect.width - drawnWidth) / 2;
                const blackBarY = (rect.height - drawnHeight) / 2;
                
                const subLeftPx = dragSub.offsetLeft;
                const subTopPx = dragSub.offsetTop;
                const subHeightPx = dragSub.clientHeight;
                
                const subCenterX = subLeftPx;
                const subBottomY = subTopPx + (subHeightPx / 2);
                
                let realX = subCenterX - blackBarX;
                let realY = subBottomY - blackBarY;
                
                posX = (realX / drawnWidth) * 100;
                posY = (realY / drawnHeight) * 100;
                
                posX = Math.max(0, Math.min(100, posX));
                posY = Math.max(0, Math.min(100, posY));
            }

            // 1.8 Release video file lock on Windows
            const videoElement = $('#editor-video');
            if (videoElement) {
                videoElement.pause();
                videoElement.removeAttribute('src');
                videoElement.load();
            }

            const renderResp = await fetch(`${API_BASE}/api/re-render/${currentTaskId}`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ pos_x: posX, pos_y: posY })
            });

            if (!renderResp.ok) {
                const errData = await renderResp.json();
                throw new Error(errData.detail || errData.message || 'Lỗi gửi yêu cầu render');
            }

            // 3. Poll for status every 2 seconds
            const pollInterval = setInterval(async () => {
                try {
                    const resp = await fetch(`${API_BASE}/api/re-render-status/${currentTaskId}`);
                    const data = await resp.json();

                    if (data.status === 'running') {
                        btn.querySelector('span').textContent =
                            `${data.message || 'Đang render...'} ${data.progress || 0}%`;

                    } else if (data.status === 'complete') {
                        clearInterval(pollInterval);
                        showToast('✅ Render xong! Video đã được cập nhật.', 'success');

                        // Reload video preview
                        const videoEl = $('#editor-video');
                        const videoSrc = $('#editor-video-src');
                        if (videoEl && videoSrc) {
                            videoSrc.src = `${API_BASE}/api/preview/${currentTaskId}?t=${Date.now()}`;
                            videoEl.load();
                        }

                        if (data.file_size_mb) {
                            $('#file-size').textContent = `~${data.file_size_mb} MB`;
                        }

                        // Reset button
                        btn.innerHTML = `
                            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                                <path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z"></path>
                                <polyline points="17 21 17 13 7 13 7 21"></polyline>
                                <polyline points="7 3 7 8 15 8"></polyline>
                            </svg>
                            <span>Lưu & Render lại video</span>
                        `;
                        btn.disabled = false;
                        
                        // Update queue status (but DO NOT redirect, let user preview)
                        const taskInQueue = currentBatchTasks.find(t => t.taskId === currentTaskId);
                        if (taskInQueue) {
                            taskInQueue.status = 'completed';
                        }

                    } else if (data.status === 'error') {
                        clearInterval(pollInterval);
                        showToast(`❌ Lỗi: ${data.message || 'Không xác định'}`, 'error');
                        btn.disabled = false;
                        btn.innerHTML = `<span>Thử lại</span>`;
                    }
                } catch (e) {
                    console.error('Poll error', e);
                }
            }, 2000);

        } catch (err) {
            showToast(err.message, 'error');
            btn.innerHTML = `<span>Thử lại</span>`;
            btn.disabled = false;
        }
    });

    // Find & Replace Modal
    $('#btn-find-replace')?.addEventListener('click', () => {
        $('#find-replace-modal').style.display = 'flex';
        $('#find-input').focus();
    });

    $('#btn-close-modal')?.addEventListener('click', () => {
        $('#find-replace-modal').style.display = 'none';
    });

    $('#btn-cancel-fr')?.addEventListener('click', () => {
        $('#find-replace-modal').style.display = 'none';
    });

    $('#btn-do-replace')?.addEventListener('click', async () => {
        const findText = $('#find-input').value;
        const replaceText = $('#replace-input').value;
        const caseSensitive = $('#case-sensitive').checked;

        if (!findText) {
            showToast('Vui lòng nhập từ cần tìm', 'warning');
            return;
        }

        try {
            const resp = await fetch(`${API_BASE}/api/find-replace/${currentTaskId}`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ find: findText, replace: replaceText, case_sensitive: caseSensitive })
            });

            const data = await resp.json();

            if (data.segments) {
                currentSegments = data.segments;
                renderSegmentCards();
            }

            showToast(`Đã thay thế ${data.replaced || 0} đoạn`, 'success');
            $('#find-replace-modal').style.display = 'none';
        } catch (err) {
            showToast('Lỗi: ' + err.message, 'error');
        }
    });

    // Export buttons
    $('#btn-export-srt')?.addEventListener('click', () => exportSegments('srt'));
    $('#btn-export-lines')?.addEventListener('click', () => exportSegments('lines'));
    $('#btn-export-txt')?.addEventListener('click', () => exportSegments('txt'));

    // Handle re-render messages from WebSocket
    const origOnMessage = ws?.onmessage;
});

function exportSegments(fmt) {
    if (!currentTaskId) return;
    window.open(`${API_BASE}/api/export/${currentTaskId}/${fmt}`, '_blank');
    showToast(`Đang xuất file ${fmt.toUpperCase()}...`, 'success');
}

// --- Subtitle Drag and Drop ---
const dragSub = document.getElementById('draggable-sub');
const videoWrap = document.getElementById('editor-video-wrap');
let isDraggingSub = false;

if (dragSub && videoWrap) {
    dragSub.addEventListener('mousedown', (e) => {
        isDraggingSub = true;
        e.preventDefault();
    });

    document.addEventListener('mousemove', (e) => {
        if (!isDraggingSub) return;
        const rect = videoWrap.getBoundingClientRect();
        
        let x = e.clientX - rect.left;
        let y = e.clientY - rect.top;
        
        // Clamp to wrap
        y = Math.max(0, Math.min(y, rect.height));

        const pctY = (y / rect.height) * 100;
        
        dragSub.style.left = '50%'; // Lock X axis
        dragSub.style.top = pctY + '%';
        dragSub.style.bottom = 'auto'; // override default CSS bottom
    });

    document.addEventListener('mouseup', () => {
        isDraggingSub = false;
    });
}
