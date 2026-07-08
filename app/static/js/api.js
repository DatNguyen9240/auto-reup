// API Client operations for AutoTool Studio

function readSubtitleCoverConfig() {
    const valueOf = (id, fallback) => {
        const el = document.getElementById(id);
        return el ? el.value : fallback;
    };
    const numberOf = (id, fallback) => {
        const val = parseFloat(valueOf(id, fallback));
        return Number.isFinite(val) ? val : fallback;
    };

    return {
        subtitle_cover_mode: valueOf('subtitle_cover_mode', 'text_box_only'),
        subtitle_bg_opacity: numberOf('subtitle_bg_opacity', 0.20),
        subtitle_mask_padding_x: numberOf('subtitle_mask_padding_x', 20),
        subtitle_mask_padding_y: numberOf('subtitle_mask_padding_y', 12),
        ocr_sample_interval_sec: numberOf('ocr_sample_interval_sec', 0.75),
        ocr_crop_bottom_ratio: numberOf('ocr_crop_bottom_ratio', 0.45)
    };
}

// Fetch and load jobs list
async function loadJobs() {
    try {
        const response = await fetch('/api/jobs');
        const data = await response.json();
        jobsData = data;
        renderJobsList();
        
        // If details modal is active, refresh the steps status
        if (selectedJobId && !(typeof isEditingSubtitleLayout !== 'undefined' && isEditingSubtitleLayout)) {
            const currentJob = jobsData.find(j => j.job_id === selectedJobId);
            if (currentJob) {
                updatePipelineSteps(currentJob);
            }
        }
    } catch (err) {
        console.error("Failed to load jobs:", err);
    }
}



// Fetch global configuration settings (Tones, Voices, Pitch, Speed Rates)
async function loadGlobalConfig() {
    try {
        const response = await fetch('/api/config');
        if (!response.ok) return;
        globalConfig = await response.json();
        
        // Populate Job Form Select options
        populateSelect('tone', globalConfig.tones, 'review_phim');
        populateSelect('voice', globalConfig.voices, 'vi-VN-HoaiMyNeural');
        populateSelect('rate', globalConfig.rates, '+0%');
        populateSelect('pitch', globalConfig.pitches, '+0Hz');
        
        // Populate Channel Creator Select options
        populateSelect('chan-tone', globalConfig.tones, 'review_phim');
        populateSelect('chan-voice', globalConfig.voices, 'vi-VN-HoaiMyNeural');
        populateSelect('chan-rate', globalConfig.rates, '+0%');
        populateSelect('chan-pitch', globalConfig.pitches, '+0Hz');

        // Populate Detail Panel Override Select options
        populateSelect('detail-voice', globalConfig.voices, 'vi-VN-HoaiMyNeural');
        populateSelect('detail-rate', globalConfig.rates, '+0%');
        populateSelect('detail-pitch', globalConfig.pitches, '+0Hz');
        
        // Populate all logo select dropdowns
        if (typeof populateAllLogoSelects === 'function') {
            populateAllLogoSelects();
        }
    } catch (err) {
        console.error("Failed to load global config:", err);
    }
}

// Submit translation jobs for all queued videos
async function submitJob(e) {
    if (e) e.preventDefault();
    
    if (videoQueue.length === 0) {
        showToast("Vui lòng chọn hoặc kéo thả ít nhất một video để xử lý!", "error");
        return;
    }
    
    const tone = document.getElementById('tone').value;
    const voice = document.getElementById('voice').value;
    const rate = document.getElementById('rate').value;
    const pitch = document.getElementById('pitch').value;
    const bgm = document.getElementById('bgm').value.trim() || null;
    const logo = document.getElementById('logo').value.trim() || null;
    const maskInput = document.getElementById('mask');
    const mask = maskInput ? maskInput.checked : true;
    const subtitle_style = document.getElementById('subtitle_style')?.value || 'default';
    const subtitleCoverConfig = readSubtitleCoverConfig();
    const reverseVideoInput = document.getElementById('reverse_video');
    const reverse_video = reverseVideoInput ? reverseVideoInput.checked : false;

    const channel_folder = null;
    const platform_folder = document.getElementById('dest_platform').value;

    const total = videoQueue.length;
    showToast(`Bắt đầu xếp hàng xử lý ${total} video...`, "success");
    
    // Create copy of the queue so we can clear it safely
    const queueToProcess = [...videoQueue];
    
    // Clear queue & UI
    videoQueue = [];
    renderQueueList();

    // Post each job sequentially to the backend
    for (const input_video of queueToProcess) {
        try {
            const response = await fetch('/api/jobs', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ input_video, tone, voice, rate, pitch, bgm, logo, mask, channel_folder, platform_folder, subtitle_style, reverse_video, ...subtitleCoverConfig })
            });
            
            if (!response.ok) {
                const err = await response.json();
                console.error(`Failed to start job for ${input_video}:`, err.detail);
            }
        } catch (err) {
            console.error(`Network error for ${input_video}:`, err.message);
        }
    }
    
    // Refresh jobs list to show all new jobs
    await loadJobs();
    await loadOutputFolders();
    showToast("Đã thêm các video vào hàng đợi xử lý!", "success");
}

// Delete a completed or failed job card
async function deleteJob(jobId) {
    const currentJob = jobsData.find(j => j.job_id === jobId);
    if (currentJob && currentJob.status === 'running') {
        alert("Không thể xóa job đang chạy!");
        return;
    }
    const confirmed = await showConfirm(`Bạn có chắc chắn muốn xóa vĩnh viễn công việc ${jobId} và toàn bộ file video liên quan để giải phóng bộ nhớ không?`);
    if (!confirmed) return;
    
    try {
        const response = await fetch(`/api/jobs/${jobId}`, {
            method: 'DELETE'
        });
        if (response.ok) {
            await loadJobs();
            if (selectedJobId === jobId) {
                closeDetailPanel();
            }
            showToast("Đã xóa Job thành công!", "success");
        } else {
            const err = await response.json();
            alert("Lỗi khi xóa: " + err.detail);
        }
    } catch (err) {
        alert("Không kết nối được server: " + err.message);
    }
}

// Cancel a running job
async function cancelJob(jobId) {
    const confirmed = await showConfirm("Bạn có chắc chắn muốn ngắt tiến trình và xóa công việc này không?");
    if (!confirmed) return;
    try {
        // 1. Send cancel request to halt processing
        await fetch(`/api/jobs/${jobId}/cancel`, { method: 'POST' });
        // 2. Send delete request to remove state file and vanish card instantly
        const response = await fetch(`/api/jobs/${jobId}`, { method: 'DELETE' });
        if (response.ok) {
            await loadJobs();
            showToast("Đã ngắt tiến trình và xóa Job thành công!", "success");
        } else {
            const err = await response.json();
            alert("Lỗi khi xóa Job: " + err.detail);
        }
    } catch (err) {
        alert("Lỗi kết nối: " + err.message);
    }
}



// Save subtitle modifications and rerun pipeline from translation step
async function saveAndReRun() {
    const btn = document.getElementById('btn-save-rerun');
    btn.disabled = true;
    btn.innerText = "Đang chạy lại...";

    // Read lồng tiếng and nhạc nền overrides directly from the local Detail Panel select elements
    const voice = document.getElementById('detail-voice').value;
    const bgm = document.getElementById('detail-bgm').value.trim() || null;
    const rate = document.getElementById('detail-rate').value;
    const pitch = document.getElementById('detail-pitch').value;
    
    // Read general parameters
    const tone = 'review_phim';
    const logoInput = document.getElementById('logo');
    const logo = logoInput ? (logoInput.value.trim() || null) : null;
    const mask = true;
    const subtitleCoverConfig = readSubtitleCoverConfig();

    try {
        const response = await fetch(`/api/jobs/${selectedJobId}/transcript`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                segments: selectedSegments,
                reset_from_tts: true,
                tone, voice, rate, pitch, bgm, logo, mask,
                ...subtitleCoverConfig
            })
        });

        if (response.ok) {
            await loadJobs();
            alert("Cập nhật thành công! Job đã bắt đầu sinh lại giọng nói và video.");
            closeDetailPanel();
        } else {
            const err = await response.json();
            alert("Không thể chạy lại: " + err.detail);
        }
    } catch (err) {
        alert("Lỗi: " + err.message);
    } finally {
        btn.disabled = false;
        btn.innerText = "Lưu & Tạo Lại Giọng Đọc/Video";
    }
}

// Scan the local folder path for video files
async function scanLocalMedia() {
    const path = document.getElementById('scan_path').value.trim();
    const container = document.getElementById('library-container');
    container.innerHTML = `<div class="text-[10px] text-center text-slate-400 py-4 animate-pulse">Đang quét thư mục...</div>`;
    
    try {
        const response = await fetch(`/api/media/scan?path=${encodeURIComponent(path)}`);
        if (!response.ok) {
            const err = await response.json();
            container.innerHTML = `<div class="text-[10px] text-center text-rose-400 py-4">Lỗi: ${err.detail}</div>`;
            return;
        }
        const data = await response.json();
        libraryVideos = data.videos;
        renderLibrary();
    } catch (err) {
        container.innerHTML = `<div class="text-[10px] text-center text-rose-400 py-4">Không kết nối được server</div>`;
    }
}

// Search online videos from YouTube / Bilibili
async function triggerSearch() {
    const queryInput = document.getElementById('search-query');
    const sourceSelect = document.getElementById('search-source');
    const resultsContainer = document.getElementById('search-results');
    const emptyState = document.getElementById('search-empty');
    const loadingState = document.getElementById('search-loading');
    
    const q = queryInput.value.trim();
    if (!q) {
        alert("Vui lòng nhập từ khóa tìm kiếm!");
        return;
    }
    
    loadingState.classList.remove('hidden');
    emptyState.classList.add('hidden');
    resultsContainer.innerHTML = '';
    
    try {
        const source = sourceSelect.value;
        const response = await fetch(`/api/media/search?q=${encodeURIComponent(q)}&source=${source}`);
        const data = await response.json();
        
        loadingState.classList.add('hidden');
        
        if (data.videos && data.videos.length > 0) {
            emptyState.classList.add('hidden');
            
            if (data.translated_query) {
                const transCard = document.createElement('div');
                transCard.className = "col-span-full bg-purple-500/10 border border-purple-500/20 rounded-xl p-3 text-xs text-purple-300 flex items-center gap-2 mb-2";
                transCard.innerHTML = `
                    <span class="font-extrabold uppercase bg-purple-500/30 px-2.5 py-0.5 rounded text-[9px] tracking-wide text-purple-200">Auto-Translate</span>
                    Dịch từ khóa sang tiếng Trung: <strong>"${data.translated_query}"</strong> để tìm kiếm hiệu quả hơn trên Bilibili.
                `;
                resultsContainer.appendChild(transCard);
            }
            
            data.videos.forEach(video => {
                const card = document.createElement('div');
                card.className = "glass-card rounded-2xl overflow-hidden border border-white/5 flex flex-col group hover:border-purple-500/30 transition-all hover:shadow-lg hover:shadow-purple-500/5 duration-300 cursor-grab active:cursor-grabbing";
                card.setAttribute('draggable', 'true');
                
                card.ondragstart = (e) => {
                    e.dataTransfer.setData('text/plain', video.url);
                    e.dataTransfer.effectAllowed = 'copy';
                    card.classList.add('opacity-40', 'scale-95');
                };
                
                card.ondragend = () => {
                    card.classList.remove('opacity-40', 'scale-95');
                };

                card.innerHTML = `
                    <div class="relative aspect-video bg-slate-900 overflow-hidden">
                        <img src="${video.thumbnail || 'https://images.unsplash.com/photo-1618005182384-a83a8bd57fbe?w=600&auto=format&fit=crop&q=60'}" 
                             alt="thumbnail" 
                             class="w-full h-full object-cover group-hover:scale-105 transition-transform duration-500" 
                             onerror="this.src='https://images.unsplash.com/photo-1618005182384-a83a8bd57fbe?w=600&auto=format&fit=crop&q=60'">
                        <div class="absolute bottom-2 right-2 bg-slate-950/80 backdrop-blur-md px-2 py-0.5 rounded text-[10px] font-semibold text-white">
                            ${video.duration}
                        </div>
                        <div class="absolute top-2 left-2 bg-purple-600/95 backdrop-blur-md px-2 py-0.5 rounded text-[10px] font-bold text-white uppercase tracking-wider">
                            ${video.source}
                        </div>
                    </div>
                    <div class="p-4 flex-1 flex flex-col justify-between gap-3">
                        <div class="flex flex-col gap-1.5">
                            <h3 class="font-outfit font-semibold text-xs text-slate-100 line-clamp-2 leading-snug group-hover:text-purple-400 transition-colors" title="${video.title}">
                                ${video.title}
                            </h3>
                            <p class="text-[10px] text-slate-400 flex items-center gap-1">
                                👁️ ${video.views} lượt xem
                            </p>
                        </div>
                        <button onclick="importSearchedVideo('${video.url}')" 
                                class="w-full py-2 bg-white/5 hover:bg-purple-600 hover:text-white rounded-xl text-[11px] font-semibold text-slate-300 transition-all active:scale-[0.98] border border-white/5 hover:border-transparent flex items-center justify-center gap-1.5">
                            <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2.5" d="M12 4v16m8-8H4"></path></svg>
                            Việt Hóa Video
                        </button>
                    </div>
                `;
                resultsContainer.appendChild(card);
            });
        } else {
            emptyState.classList.remove('hidden');
        }
    } catch (err) {
        loadingState.classList.add('hidden');
        emptyState.classList.remove('hidden');
        alert("Lỗi khi tìm kiếm: " + err.message);
    }
}

// Load all BGM files currently in examples/music
async function loadBgmList() {
    try {
        const response = await fetch('/api/music');
        if (!response.ok) return [];
        const bgmFiles = await response.json();
        
        // Update dashboard select
        const bgmSelect = document.getElementById('bgm');
        if (bgmSelect) {
            bgmSelect.innerHTML = '<option value="">Không sử dụng BGM</option>';
            bgmFiles.forEach(file => {
                const valueName = file.replace(/\.[^/.]+$/, "");
                const opt = new Option(file, valueName);
                bgmSelect.add(opt);
            });
        }
        
        // Update Channel form select
        const chanBgmSelect = document.getElementById('chan-bgm');
        if (chanBgmSelect) {
            chanBgmSelect.innerHTML = '<option value="">Không sử dụng BGM</option>';
            bgmFiles.forEach(file => {
                const valueName = file.replace(/\.[^/.]+$/, "");
                const opt = new Option(file, valueName);
                chanBgmSelect.add(opt);
            });
        }

        // Update Detail Panel select
        const detailBgmSelect = document.getElementById('detail-bgm');
        if (detailBgmSelect) {
            detailBgmSelect.innerHTML = '<option value="">Không sử dụng BGM</option>';
            bgmFiles.forEach(file => {
                const valueName = file.replace(/\.[^/.]+$/, "");
                const opt = new Option(file, valueName);
                detailBgmSelect.add(opt);
            });
        }
        
        // Update modal installed list
        const installedList = document.getElementById('installed-bgm-list');
        if (installedList) {
            if (bgmFiles.length === 0) {
                installedList.innerHTML = '<div class="text-center text-[10px] py-4 text-slate-500">Chưa có bản nhạc nào trong thư mục. Hãy bấm Tải về ở trên!</div>';
            } else {
                installedList.innerHTML = bgmFiles.map(file => `
                    <div class="flex items-center justify-between p-2 rounded bg-white/5">
                        <span class="font-medium text-slate-200">🎵 ${file}</span>
                        <span class="text-[10px] text-slate-500">Đã cài đặt</span>
                    </div>
                `).join('');
            }
        }
        
        return bgmFiles;
    } catch (err) {
        console.error("Failed to load BGM list:", err);
        return [];
    }
}

function openBgmManager() {
    const modal = document.getElementById('bgm-modal');
    if (modal) {
        modal.classList.remove('hidden');
    }
    loadBgmList();
}

function closeBgmManager() {
    const modal = document.getElementById('bgm-modal');
    if (modal) {
        modal.classList.add('hidden');
    }
}

async function downloadPresetBgm(url, filename, buttonEl) {
    const originalText = buttonEl.innerText;
    buttonEl.disabled = true;
    buttonEl.innerText = "Đang tải...";
    
    try {
        const response = await fetch('/api/music/download', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ url, filename })
        });
        
        if (response.ok) {
            const data = await response.json();
            showToast(data.message || "Tải nhạc thành công!", "success");
            await loadBgmList();
        } else {
            const err = await response.json();
            showToast(err.detail || "Không thể tải nhạc", "error");
        }
    } catch (err) {
        showToast("Lỗi kết nối máy chủ: " + err.message, "error");
    } finally {
        buttonEl.disabled = false;
        buttonEl.innerText = originalText;
    }
}

async function downloadCustomBgm() {
    const url = document.getElementById('custom-bgm-url').value.trim();
    let filename = document.getElementById('custom-bgm-name').value.trim();
    
    if (!url) {
        showToast("Vui lòng nhập đường dẫn URL tải nhạc!", "error");
        return;
    }
    if (!filename) {
        filename = url.split('/').pop().split('?')[0] || "music.mp3";
    }
    
    try {
        const response = await fetch('/api/music/download', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ url, filename })
        });
        
        if (response.ok) {
            const data = await response.json();
            showToast(data.message || "Tải nhạc thành công!", "success");
            document.getElementById('custom-bgm-url').value = '';
            document.getElementById('custom-bgm-name').value = '';
            await loadBgmList();
        } else {
            const err = await response.json();
            showToast(err.detail || "Không thể tải nhạc", "error");
        }
    } catch (err) {
        showToast("Lỗi kết nối: " + err.message, "error");
    }
}

// Open local outputs folder in Windows Explorer
async function openOutputsFolder(jobId = null) {
    try {
        const response = await fetch('/api/outputs/open', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ job_id: jobId })
        });
        
        if (response.ok) {
            const data = await response.json();
            showToast(data.message || "Đang mở thư mục...", "success");
        } else {
            const err = await response.json();
            showToast(err.detail || "Không thể mở thư mục", "error");
        }
    } catch (err) {
        showToast("Lỗi kết nối: " + err.message, "error");
    }
}

// Open native folder dialog and auto scan directory
async function browseLocalFolder() {
    try {
        const response = await fetch('/api/media/browse', { method: 'POST' });
        if (response.ok) {
            const data = await response.json();
            if (data.path) {
                document.getElementById('scan_path').value = data.path;
                showToast(`Đã chọn thư mục: ${data.path}`, "success");
                await scanLocalMedia();
            }
        } else {
            const err = await response.json();
            showToast("Lỗi chọn thư mục: " + err.detail, "error");
        }
    } catch (err) {
        showToast("Lỗi kết nối: " + err.message, "error");
    }
}

// Open currently scanned library path in Windows Explorer
async function openLibraryFolder() {
    const path = document.getElementById('scan_path').value.trim();
    if (!path) {
        showToast("Vui lòng nhập hoặc chọn thư mục trước!", "warning");
        return;
    }
    
    try {
        const response = await fetch('/api/media/open', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ path: path })
        });
        
        if (response.ok) {
            showToast(`Đã mở thư mục: ${path}`, "success");
        } else {
            const err = await response.json();
            showToast("Lỗi mở thư mục: " + err.detail, "error");
        }
    } catch (err) {
        showToast("Lỗi kết nối: " + err.message, "error");
    }
}

// Unified per-video submit flow. Overrides the older global-config submitJob.
async function submitJob(e) {
    if (e) e.preventDefault();

    if (!Array.isArray(pendingVideoItems) || pendingVideoItems.length === 0) {
        showToast('Vui lòng thêm ít nhất một video vào hàng chờ', 'error');
        return;
    }

    const queueToProcess = pendingVideoItems.map(item => ({
        ...item,
        config: { ...item.config }
    }));
    pendingVideoItems = [];
    videoQueue = pendingVideoItems;
    renderQueueList();

    const selected_outputs = [];
    const chkFb = document.getElementById('queue-out-fb-reels') || document.getElementById('out-fb-reels');
    const chkShorts = document.getElementById('queue-out-yt-shorts') || document.getElementById('out-yt-shorts');
    const chkVideo = document.getElementById('queue-out-yt-video') || document.getElementById('out-yt-video');
    if (chkFb?.checked) selected_outputs.push('fb_reels');
    if (chkShorts?.checked) selected_outputs.push('yt_shorts');
    if (chkVideo?.checked) selected_outputs.push('yt_video');

    for (const item of queueToProcess) {
        const cfg = item.config;
        const payload = {
            input_video: item.normalized_url || item.url,
            tone: cfg.tone,
            voice: cfg.voice,
            rate: cfg.rate,
            pitch: cfg.pitch,
            bgm: cfg.bgm || null,
            logo: cfg.logo || null,
            mask: cfg.mask && cfg.subtitles_enabled,
            tts_enabled: cfg.tts_enabled,
            subtitles_enabled: cfg.subtitles_enabled,
            ocr_only_mode: cfg.ocr_only_mode ?? false,
            channel_folder: null,
            platform_folder: cfg.platform_folder || '',
            channel_id: cfg.channel_id || null,
            target_language: cfg.target_language || 'vi-VN',
            target_locale: cfg.target_locale || null,
            translation_mode: cfg.translation_mode || 'natural',
            subtitle_style: cfg.subtitle_style || 'default',
            subtitle_cover_mode: cfg.subtitles_enabled ? cfg.subtitle_cover_mode : 'none',
            subtitle_bg_opacity: cfg.subtitle_bg_opacity,
            subtitle_mask_padding_x: cfg.subtitle_mask_padding_x,
            subtitle_mask_padding_y: cfg.subtitle_mask_padding_y,
            ocr_sample_interval_sec: cfg.ocr_sample_interval_sec,
            ocr_crop_bottom_ratio: cfg.ocr_crop_bottom_ratio,
            selected_outputs: selected_outputs.length > 0 ? selected_outputs : null,
            reverse_video: cfg.reverse_video ?? false,
            config_snapshot: {
                url: item.url,
                normalized_url: item.normalized_url,
                platform: item.platform,
                selected_outputs: selected_outputs.length > 0 ? selected_outputs : null,
                logo_position: document.getElementById('logo_position')?.value || 'top_left',
                logo_layout: window.logoLayout || null,
                reverse_video: cfg.reverse_video ?? false,
                ...cfg
            }
        };

        try {
            const response = await fetch('/api/jobs', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });
            if (!response.ok) {
                const err = await response.json();
                console.error(`Failed to start job for ${item.url}:`, err.detail);
                showToast(err.detail || `Không tạo được job: ${item.url}`, 'error');
            }
        } catch (err) {
            console.error(`Network error for ${item.url}:`, err.message);
            showToast(`Lỗi kết nối khi tạo job: ${item.url}`, 'error');
        }
    }

    await loadJobs();
    showToast(`Đã tạo ${queueToProcess.length} job riêng`, 'success');
}

async function saveCropConfig(jobId, outputType, reframeMode, cropX, cropY, cropW, cropH) {
    try {
        const res = await fetch(`/api/jobs/${jobId}/crop`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                output_type: outputType,
                reframe_mode: reframeMode,
                crop_x_percent: cropX,
                crop_y_percent: cropY,
                crop_width_percent: cropW,
                crop_height_percent: cropH
            })
        });
        if (res.ok) {
            showToast("Lưu tọa độ crop thành công!", "success");
            await loadJobs();
        } else {
            const err = await res.json();
            showToast(err.detail || "Không thể lưu tọa độ crop", "error");
        }
    } catch (e) {
        showToast("Lỗi kết nối: " + e.message, "error");
    }
}

async function renderSpecificOutput(jobId, outputType) {
    try {
        showToast(`Đang gửi yêu cầu render ${outputType}...`, "info");
        const res = await fetch(`/api/jobs/${jobId}/render-output`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ output_type: outputType })
        });
        if (res.ok) {
            showToast("Đã bắt đầu render ở tiến trình ngầm!", "success");
            await loadJobs();
        } else {
            const err = await res.json();
            showToast(err.detail || "Không thể yêu cầu render", "error");
        }
    } catch (e) {
        showToast("Lỗi kết nối: " + e.message, "error");
    }
}

async function uploadLogo(input) {
    if (!input.files || input.files.length === 0) return;
    const file = input.files[0];
    
    const formData = new FormData();
    formData.append("file", file);
    
    showToast(`Đang tải lên logo ${file.name}...`, "info");
    try {
        const response = await fetch('/api/logo/upload', {
            method: 'POST',
            body: formData
        });
        if (response.ok) {
            const res = await response.json();
            showToast(res.message || "Tải lên logo thành công!", "success");
            
            // Reload config to update all logo dropdowns
            await loadGlobalConfig();
            
            // Select the newly uploaded logo in the dropdown
            const select = document.getElementById('logo');
            if (select) {
                select.value = file.name;
            }
        } else {
            const err = await response.json();
            showToast(err.detail || "Không thể tải lên logo", "error");
        }
    } catch (e) {
        showToast("Lỗi kết nối: " + e.message, "error");
    } finally {
        input.value = ''; // Reset input
    }
}
