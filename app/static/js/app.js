// Main Application View Controller & UI Orchestration

// Global State Variables
let currentTab = 'dashboard';
let jobsData = [];
let selectedJobId = null;
let selectedSegments = [];
let refreshInterval = null;
let globalConfig = {};
let libraryVideos = [];
let pendingVideoItems = [];
let videoQueue = pendingVideoItems;
let currentFilterChannelId = localStorage.getItem('currentFilterChannelId') || '';

// SPA HTML Views Map
const VIEWS = {
    dashboard: 'views/dashboard.html',
    search: 'views/search.html',
    channels: 'views/channels.html',
    config: 'views/config.html'
};

let pollingTimeout = null;
async function runSmartPolling() {
    if (pollingTimeout) clearTimeout(pollingTimeout);
    if (typeof loadJobs === 'function' && currentTab === 'dashboard') {
        await loadJobs();
    }
    const activeStatuses = new Set(['created', 'queued', 'processing', 'rendering', 'running']);
    const hasActiveJobs = (jobsData || []).some(j => activeStatuses.has(j.status));
    const nextDelay = hasActiveJobs ? 5000 : 30000; // 5s when active, 30s when idle
    if (currentTab === 'dashboard') {
        pollingTimeout = setTimeout(runSmartPolling, nextDelay);
    }
}

// Initialize application on DOM ready
document.addEventListener('DOMContentLoaded', async () => {
    // Read initial tab from URL hash (defaults to dashboard)
    // Load configurations and output subfolders persistently once on startup
    await loadGlobalConfig();
    await loadBgmList();
    await loadChannels();
    await checkApiKeysOnStartup();

    // Read initial tab from URL hash (defaults to dashboard)
    const initialTab = window.location.hash.replace('#', '') || 'dashboard';
    await switchTab(initialTab);
    setupQueueDragNDrop();
    renderQueueList();

    // Setup sidebar tab and header tab drag actions
    setupSidebarTabDragNDrop();
    setupHeaderTabDragNDrop();

    // Run smart polling
    runSmartPolling();

    // Refresh on focus
    window.addEventListener('focus', () => {
        if (currentTab === 'dashboard') runSmartPolling();
    });
});

// Tab Routing Switches (Loads views dynamically)
async function switchTab(tab) {
    if (tab === 'config') {
        openConfigModal();
        if (currentTab === 'config') {
            currentTab = 'dashboard';
        }
        window.location.hash = currentTab;
        return;
    }

    currentTab = tab;
    window.location.hash = tab;

    // Toggle menu highlight styles
    const btnDashboard = document.getElementById('btn-tab-dashboard');
    const btnSearch = document.getElementById('btn-tab-search');
    const btnChannels = document.getElementById('btn-tab-channels');

    const tabs = {
        dashboard: btnDashboard,
        search: btnSearch,
        channels: btnChannels
    };

    for (const [t, btn] of Object.entries(tabs)) {
        if (btn) {
            if (t === tab) {
                btn.className = "px-4 py-2 text-xs font-semibold rounded-lg bg-white/10 text-white transition-all flex items-center gap-2";
            } else {
                btn.className = "px-4 py-2 text-xs font-semibold rounded-lg hover:bg-white/5 text-slate-400 hover:text-white transition-all flex items-center gap-2";
            }
        }
    }

    // Toggle sidebar container visibility
    const sidebarContainer = document.getElementById('sidebar-container');
    if (sidebarContainer) {
        if (tab === 'dashboard') {
            sidebarContainer.classList.remove('hidden');
        } else {
            sidebarContainer.classList.add('hidden');
        }
    }

    const container = document.getElementById('app-view');
    if (!container) return;

    // Show loading spinner
    container.innerHTML = `
        <div class="flex-1 flex flex-col items-center justify-center gap-3 py-20 text-slate-400">
            <div class="w-8 h-8 rounded-full border-4 border-purple-500/20 border-t-purple-500 animate-spin"></div>
            <span class="text-xs font-semibold">Đang tải giao diện...</span>
        </div>
    `;

    try {
        const response = await fetch(VIEWS[tab] + '?v=3.6');
        if (response.ok) {
            container.innerHTML = await response.text();

            // Trigger tab initializers
            if (tab === 'dashboard') {
                runSmartPolling();
                if (typeof populateDashboardFilterChannel === 'function') {
                    populateDashboardFilterChannel();
                }
            } else if (tab === 'channels') {
                await initChannelsView();
            } else if (tab === 'config') {
                await loadConfigTab();
            }

            // Populate dynamic selects
            populateDestChannelSelects();
            populateAllLogoSelects();
        } else {
            container.innerHTML = `<div class="flex-1 flex items-center justify-center text-rose-400 font-semibold py-12">Lỗi tải giao diện: ${response.status} ${response.statusText}</div>`;
        }
    } catch (err) {
        container.innerHTML = `<div class="flex-1 flex items-center justify-center text-rose-400 font-semibold py-12">Lỗi kết nối máy chủ: ${err.message}</div>`;
    }
}

// Render the grid list of jobs
function renderJobsList() {
    const container = document.getElementById('jobs-container');
    container.innerHTML = '';

    let filteredJobs = jobsData;
    if (currentFilterChannelId === 'default') {
        filteredJobs = jobsData.filter(job => !job.channel_id || job.channel_id === 'default');
    } else if (currentFilterChannelId) {
        filteredJobs = jobsData.filter(job => job.channel_id === currentFilterChannelId);
    }

    if (filteredJobs.length === 0) {
        container.innerHTML = `
            <div class="col-span-full py-12 text-center text-slate-500 border border-dashed border-white/5 rounded-2xl">
                Không tìm thấy job nào phù hợp với bộ lọc.
            </div>
        `;
        return;
    }

    filteredJobs.forEach(job => {
        const card = document.createElement('div');
        card.className = "glass-card rounded-xl p-4 hover:border-white/15 transition-all flex flex-col gap-3.5 relative group";

        let statusBadge = '';
        if (job.status === 'completed') {
            statusBadge = '<span class="text-[10px] px-2 py-0.5 bg-emerald-500/20 text-emerald-300 font-bold rounded-md border border-emerald-500/20">Hoàn thành</span>';
        } else if (job.status === 'failed') {
            statusBadge = '<span class="text-[10px] px-2 py-0.5 bg-rose-500/20 text-rose-300 font-bold rounded-md border border-rose-500/20">Lỗi</span>';
        } else if (job.status === 'cancelled') {
            statusBadge = '<span class="text-[10px] px-2 py-0.5 bg-slate-950 text-slate-400 font-bold rounded-md border border-white/5">Đã hủy</span>';
        } else if (job.status === 'running') {
            statusBadge = '<span class="text-[10px] px-2 py-0.5 bg-indigo-500/20 text-indigo-300 font-bold rounded-md animate-pulse border border-indigo-500/20">Đang xử lý</span>';
        } else {
            statusBadge = `<span class="text-[10px] px-2 py-0.5 bg-slate-800 text-slate-300 font-bold rounded-md">${job.status}</span>`;
        }

        const totalSteps = Object.keys(job.steps).length;
        const completedSteps = Object.values(job.steps).filter(s => s === 'completed').length;
        const pct = Math.round((completedSteps / totalSteps) * 100);
        const createdDate = parseDashboardDate(job.created_at || job.timestamp || job.date);
        const createdTime = createdDate ? createdDate.toLocaleString() : '';
        const snapshot = job.config_snapshot || {};
        const platformLabel = snapshot.platform || job.platform_folder || '';
        const channelLabel = (globalChannels.find(c => c.id === snapshot.channel_id || c.id === job.channel_id) || {}).name || '';



        let deleteButton = '';
        let resumeButton = '';
        if (job.status !== 'running') {
            if (job.status === 'failed' || job.status === 'cancelled') {
                resumeButton = `
                    <button onclick="resumeJob('${job.job_id}')" class="bg-purple-600/20 hover:bg-purple-600/80 text-purple-300 hover:text-white text-xs font-semibold px-3 py-1.5 rounded-lg border border-purple-500/30 transition-all">
                        ▶️ Tiếp tục
                    </button>
                `;
            }
        } else {
            deleteButton = `
                <button onclick="cancelJob('${job.job_id}')" class="hover:bg-amber-500/10 text-amber-400 text-xs font-semibold px-3 py-1.5 rounded-lg border border-amber-500/20 hover:border-amber-500/40 transition-all">
                    Ngắt
                </button>
            `;
        }

        let completedActionsHtml = '';
        if (job.status === 'completed') {
            const curChannel = globalChannels.find(c => c.id === job.channel_id);
            const curChanName = curChannel ? curChannel.name : null;

            completedActionsHtml = `
                <div class="relative inline-block select-wrapper flex-shrink-0 w-full sm:w-auto">
                    <select onchange="publishJob('${job.job_id}', this.value); this.selectedIndex = 0;" class="w-full sm:w-auto appearance-none bg-slate-900 hover:bg-slate-800 text-slate-200 text-[10px] font-semibold py-1.5 pl-3 pr-8 rounded-lg cursor-pointer transition-all focus:outline-none border border-slate-700/60 hover:border-purple-500/50">
                        <option value="" disabled selected>${curChanName ? 'Kênh: ' + curChanName : 'Chuyển vào kênh'}</option>
                        ${globalChannels.map(c => `<option value="${c.id}">${c.name}</option>`).join('')}
                        ${job.channel_id ? '<option value="default">Output mặc định</option>' : ''}
                    </select>
                    <div class="pointer-events-none absolute inset-y-0 right-0 flex items-center pr-2 text-slate-400">
                        <svg class="h-3 w-3 fill-current" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20"><path d="M9.293 12.95l.707.707L15.657 8l-1.414-1.414L10 10.828 5.757 6.586 4.343 8z"/></svg>
                    </div>
                </div>
            `;
        }

        card.innerHTML = `
            <div class="flex gap-3 items-start min-w-0">
                <!-- Thumbnail/Video Preview -->
                <div class="w-12 h-12 rounded-lg bg-slate-900 border border-white/5 flex-shrink-0 overflow-hidden flex items-center justify-center relative">
                    ${job.status === 'completed'
                ? `<video src="/api/jobs/${job.job_id}/video" class="w-full h-full object-cover" preload="metadata" muted playsinline></video>`
                : job.status === 'running'
                    ? `<div class="absolute inset-0 flex items-center justify-center bg-purple-500/10 text-purple-400">
                                 <svg class="w-5 h-5 animate-spin" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2.5" d="M4 4v5h.582m15.356 2A8.001 8.001 0 1121.21 12H16M4 8h5.183M12 4v4m0 0H8"></path></svg>
                               </div>`
                    : `<div class="absolute inset-0 flex items-center justify-center bg-slate-950 text-slate-500">
                                 <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 10l4.553-2.276A1 1 0 0121 8.618v6.764a1 1 0 01-1.447.894L15 14M5 18h8a2 2 0 002-2V8a2 2 0 00-2-2H5a2 2 0 00-2 2v8a2 2 0 002 2z"></path></svg>
                               </div>`
            }
                </div>

                <div class="flex-1 min-w-0 flex flex-col justify-between h-12">
                    <div class="flex justify-between items-start gap-2">
                        <div class="flex flex-col min-w-0">
                            <span class="text-[9px] font-mono text-purple-400 font-bold leading-none">${job.job_id}</span>
                            <h3 class="font-semibold text-white mt-1 text-xs truncate leading-tight" title="${job.input_path}">
                                ${job.input_path.split(/[\\/]/).pop()}
                            </h3>
                        </div>
                        ${statusBadge}
                    </div>
                </div>
            </div>

            <div class="flex flex-col gap-1">
                ${(platformLabel || channelLabel) ? `<div class="flex flex-wrap gap-1 text-[9px] text-slate-400"><span>${platformLabel || 'Local'}</span>${channelLabel ? `<span>• ${channelLabel}</span>` : ''}</div>` : ''}
                <div class="flex justify-between text-[10px] text-slate-400">
                    <span>Tiến độ</span>
                    <span>${pct}% (${completedSteps}/${totalSteps})</span>
                </div>
                <div class="w-full bg-slate-800 h-1.5 rounded-full overflow-hidden">
                    <div class="bg-gradient-to-r from-purple-500 to-rose-500 h-full transition-all duration-500" style="width: ${pct}%"></div>
                </div>
            </div>

            <div class="flex flex-wrap items-center justify-between gap-2 mt-1 pt-3 border-t border-white/5">
                <span class="text-[10px] text-slate-400 font-medium">${createdTime}</span>
                <div class="flex flex-wrap items-center gap-2">
                    ${resumeButton}
                    ${completedActionsHtml}
                    ${deleteButton}
                    <button onclick="openDetailPanel('${job.job_id}')" class="bg-white/5 hover:bg-white/10 hover:text-white text-slate-300 text-xs font-semibold px-3 py-1.5 rounded-lg border border-white/5 transition-all">
                        Chi Tiết
                    </button>
                </div>
            </div>
        `;
        container.appendChild(card);
    });
}

// Open details panel for editing subtitles and showing progress steps
async function openDetailPanel(jobId) {
    selectedJobId = jobId;
    const job = jobsData.find(j => j.job_id === jobId);
    if (!job) return;

    document.getElementById('detail-job-id-badge').innerText = job.job_id;
    const detailTitle = document.getElementById('detail-job-title');
    if (detailTitle) {
        detailTitle.innerText = getJobDisplayTitle(job);
        detailTitle.title = job.input_path || job.job_id;
    }

    // Pre-select local settings overrides from the job details
    const detailVoice = document.getElementById('detail-voice');
    const detailBgm = document.getElementById('detail-bgm');
    const detailRate = document.getElementById('detail-rate');
    const detailPitch = document.getElementById('detail-pitch');

    if (detailVoice) detailVoice.value = job.voice || 'vi-VN-HoaiMyNeural';
    if (detailBgm) detailBgm.value = job.bgm || '';
    if (detailRate) detailRate.value = job.rate || '+0%';
    if (detailPitch) detailPitch.value = job.pitch || '+0Hz';



    updatePipelineSteps(job);

    // Hide preview video player and captions until completed
    document.getElementById('detail-completed-section').classList.add('hidden');
    document.getElementById('detail-logs-section').classList.remove('hidden');

    // Show details modal overlay
    const panel = document.getElementById('detail-panel');
    panel.classList.remove('hidden');
    setTimeout(() => {
        panel.classList.remove('translate-x-full');
    }, 50);

    const refreshDetailStatus = async () => {
        if (!selectedJobId) return;

        // Refresh job details
        const response = await fetch(`/api/jobs/${selectedJobId}`);
        const freshJob = await response.json();

        updatePipelineSteps(freshJob);

        // Fetch logs
        const logResp = await fetch(`/api/jobs/${selectedJobId}/logs`);
        const logData = await logResp.json();
        const consoleBox = document.getElementById('detail-console');
        consoleBox.innerText = logData.logs || logData.content || "Chưa có nhật ký hoạt động.";
        consoleBox.scrollTop = consoleBox.scrollHeight;

        if (freshJob.status === 'completed') {
            clearInterval(refreshInterval);
            document.getElementById('detail-logs-section').classList.remove('hidden');
            document.getElementById('detail-completed-section').classList.remove('hidden');

            loadTranscript(selectedJobId);
            loadAIcaption(selectedJobId);
        } else if (freshJob.status === 'failed') {
            clearInterval(refreshInterval);
            showToast("Tiến trình Job đã kết thúc thất bại hoặc bị ngắt.", "error");
        }
    };

    // Poll logs and details status every 2 seconds
    if (refreshInterval) clearInterval(refreshInterval);
    await refreshDetailStatus();
    refreshInterval = setInterval(refreshDetailStatus, 2000);
}

// Close details modal overlay
function closeDetailPanel() {
    const panel = document.getElementById('detail-panel');
    panel.classList.add('translate-x-full');
    setTimeout(() => {
        panel.classList.add('hidden');
        selectedJobId = null;
        if (refreshInterval) clearInterval(refreshInterval);
    }, 300);
}

// Update pipeline steps status badges inside details modal
function updatePipelineSteps(job) {
    const list = document.getElementById('pipeline-steps-list');
    list.innerHTML = '';

    const friendlyNames = {
        "intake": "1. Tải / Nhập video",
        "analyze": "2. Phân tích khung hình",
        "extract_audio": "3. Tách âm thanh gốc",
        "transcribe": "4. Nhận diện giọng nói (ASR)",
        "translate": "5. Dịch thuật phụ đề (AI)",
        "tts": "6. Sinh giọng nói mới (TTS)",
        "mix_audio": "7. Trộn âm thanh & nhạc nền",
        "render": "8. Render video dọc 9:16",
        "metadata": "9. Tiêu đề & HashTags (AI)"
    };

    for (const step in friendlyNames) {
        const status = job.steps[step] || "pending";
        let statusIcon = '';
        let textStyle = 'text-slate-400';

        if (status === 'completed') {
            statusIcon = '<span class="text-emerald-400 font-bold">✓ Hoàn tất</span>';
            textStyle = 'text-slate-300';
        } else if (status === 'failed') {
            statusIcon = '<span class="text-rose-400 font-bold">✗ Thất bại</span>';
            textStyle = 'text-white font-semibold';
        } else if (step === job.current_step && job.status === 'running') {
            statusIcon = '<span class="text-purple-400 font-bold animate-pulse">● Đang xử lý</span>';
            textStyle = 'text-white font-semibold';
        } else {
            statusIcon = '<span class="text-slate-600">Đang chờ</span>';
        }

        const li = document.createElement('div');
        li.className = `flex justify-between items-center text-xs py-1.5 border-b border-white/5 ${textStyle}`;
        li.innerHTML = `<span>${friendlyNames[step]}</span> ${statusIcon}`;
        list.appendChild(li);
    }
}

// Load subtitles transcript list inside modal
async function loadTranscript(jobId) {
    const container = document.getElementById('transcript-container');
    if (!container) return;
    try {
        const response = await fetch(`/api/jobs/${jobId}/transcript`);
        if (!response.ok) {
            container.innerHTML = `
                <div class="text-[10px] text-slate-500 italic text-center py-4 bg-slate-900/20 border border-dashed border-white/5 rounded-xl">
                    Chưa tạo được danh sách phụ đề cho Job này.
                </div>
            `;
            selectedSegments = [];
            return;
        }
        const data = await response.json();
        selectedSegments = data;
        container.innerHTML = '';

        data.forEach((seg, idx) => {
            const startSec = (seg.start_ms / 1000).toFixed(1);
            const endSec = (seg.end_ms / 1000).toFixed(1);

            const row = document.createElement('div');
            row.className = "flex flex-col gap-1.5 p-3 rounded-lg bg-white/5 border border-white/5 text-xs";
            row.innerHTML = `
                <div class="flex justify-between text-[10px] text-slate-500 font-semibold">
                    <span>Phân đoạn ${seg.id}</span>
                    <span>⏱ ${startSec}s - ${endSec}s</span>
                </div>
                <div class="text-[11px] text-slate-400 italic">Gốc: "${seg.source_text}"</div>
                <textarea class="w-full bg-slate-950 border border-slate-800 rounded-lg p-2 text-xs text-white focus:outline-none focus:border-purple-500" 
                          rows="1" 
                          oninput="updateSegmentText(${idx}, this.value)">${seg.translated_text || ''}</textarea>
            `;
            container.appendChild(row);
        });
    } catch (err) {
        console.error("Failed to load transcript:", err);
    }
}

// Update subtitle segment value
function updateSegmentText(idx, val) {
    if (selectedSegments[idx]) {
        selectedSegments[idx].translated_text = val;
        selectedSegments[idx].tts_text = val;
    }
}

// Load AI captions metadata
async function loadAIcaption(jobId) {
    try {
        const response = await fetch(`/api/jobs/${jobId}/caption`);
        const data = await response.json();
        const textarea = document.getElementById('caption-textarea');
        if (textarea) {
            textarea.value = data.content || '';
        }
    } catch (err) {
        console.error("Failed to load caption:", err);
    }
}

// Copy AI captions to clipboard
function copyCaption() {
    const textarea = document.getElementById('caption-textarea');
    if (textarea) {
        textarea.select();
        document.execCommand('copy');
        alert('Đã copy caption vào clipboard!');
    }
}

// Render files list under local tree library column
function renderLibrary() {
    const container = document.getElementById('library-container');
    container.innerHTML = '';

    if (libraryVideos.length === 0) {
        container.innerHTML = `<div class="text-[10px] text-center text-slate-500 py-4">Không tìm thấy video nào.</div>`;
        return;
    }

    const groups = {};
    libraryVideos.forEach(v => {
        const f = v.folder || "Thư mục gốc";
        if (!groups[f]) groups[f] = [];
        groups[f].push(v);
    });

    for (const folder in groups) {
        const folderDiv = document.createElement('div');
        folderDiv.className = "flex flex-col gap-1";

        const header = document.createElement('div');
        header.className = "flex items-center gap-1.5 text-[11px] font-semibold text-slate-300 hover:text-white cursor-pointer select-none py-1";
        header.innerHTML = `
            <svg class="w-3.5 h-3.5 text-purple-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-6l-2-2H5a2 2 0 00-2 2z"></path></svg>
            <span>${folder}</span>
            <span class="text-[9px] bg-slate-800 text-slate-400 px-1.5 py-0.2 rounded-full ml-auto">${groups[folder].length}</span>
        `;

        const fileList = document.createElement('div');
        fileList.className = "flex flex-col gap-1 pl-4 border-l border-white/5 ml-1.5 mt-0.5";

        groups[folder].forEach(video => {
            const item = document.createElement('div');
            item.setAttribute('draggable', 'true');

            const isQueued = videoQueue.includes(video.absolute_path);
            const activeClasses = isQueued
                ? "bg-purple-500/20 text-purple-300 border border-purple-500/30"
                : "text-slate-400";

            item.className = `flex items-center justify-between text-[10px] hover:text-white hover:bg-white/5 px-2 py-1 rounded cursor-pointer transition-colors library-video-item active:scale-[0.98] select-none group ${activeClasses}`;
            item.dataset.name = video.name.toLowerCase();
            item.onclick = () => selectLibraryVideo(video.absolute_path, item);
            item.ondragstart = (e) => {
                e.dataTransfer.setData('text/plain', video.absolute_path);
                e.dataTransfer.effectAllowed = 'copy';
                item.classList.add('opacity-50');
                document.querySelectorAll('.drop-zone-card').forEach(card => {
                    card.classList.add('dropzone-pulse');
                });
            };
            item.ondragend = () => {
                item.classList.remove('opacity-50');
                document.querySelectorAll('.drop-zone-card').forEach(card => {
                    card.classList.remove('dropzone-pulse', 'dropzone-hover');
                });
            };
            item.innerHTML = `
                <div class="flex items-center gap-1.5 truncate">
                    <span class="text-slate-500 font-mono select-none">📄</span>
                    <span class="truncate" title="${video.name}">${video.name}</span>
                </div>
                <div class="flex items-center gap-2">
                    <span class="text-[9px] text-slate-500 font-mono flex-shrink-0">${video.size_mb} MB</span>
                </div>
            `;
            fileList.appendChild(item);
        });

        header.onclick = () => {
            fileList.classList.toggle('hidden');
        };

        folderDiv.appendChild(header);
        folderDiv.appendChild(fileList);
        container.appendChild(folderDiv);
    }
}

// Select video from library scanner and copy path into form
function selectLibraryVideo(absPath, element) {
    if (videoQueue.includes(absPath)) {
        // Already in queue -> remove it!
        videoQueue = videoQueue.filter(p => p !== absPath);
        element.classList.remove('bg-purple-500/20', 'text-purple-300', 'border', 'border-purple-500/30');
        element.classList.add('text-slate-400');
        showToast("Đã xóa khỏi hàng chờ", "info");
    } else {
        // Add to queue!
        videoQueue.push(absPath);
        element.classList.remove('text-slate-400');
        element.classList.add('bg-purple-500/20', 'text-purple-300', 'border', 'border-purple-500/30');
        showToast("Đã thêm vào hàng chờ", "success");
    }

    // Update queue list UI
    renderQueueList();
}

// Filter files in local library by typing keyword
function filterLibrary() {
    const q = document.getElementById('library_search').value.toLowerCase().trim();
    document.querySelectorAll('.library-video-item').forEach(item => {
        const name = item.dataset.name;
        const matches = name.includes(q);
        item.style.display = matches ? 'flex' : 'none';
    });
}

// Import searched online video URL
function importSearchedVideo(url) {
    if (!videoQueue.includes(url)) {
        videoQueue.push(url);
        renderQueueList();
        showToast("Đã thêm video vào hàng chờ!", "success");
    } else {
        showToast("Video này đã nằm trong hàng chờ!", "warning");
    }
}

// Toggle display of new channel input based on selection
function toggleNewChannelInput() {
    const select = document.getElementById('dest_channel');
    const container = document.getElementById('new-channel-container');
    if (select && container) {
        if (select.value === '__new__') {
            container.classList.remove('hidden');
        } else {
            container.classList.add('hidden');
        }
    }
}

// Populate dest_channel dropdowns dynamically
function populateDestChannelSelects() {
    const select = document.getElementById('dest_channel');
    if (!select) return;

    // Keep current selected value if any
    const curVal = select.value;
    select.innerHTML = '<option value="">Output chính</option>';

    if (Array.isArray(globalChannels)) {
        globalChannels.forEach(c => {
            const opt = new Option(c.name, c.id);
            select.add(opt);
        });
    }

    const newOpt = new Option('[ + Tạo Page Mới ]', '__new__');
    select.add(newOpt);

    if (curVal) select.value = curVal;
}

// Populate logo selects dynamically from global configuration
function populateAllLogoSelects() {
    const selects = ['logo', 'chan-logo', 'detail-logo', 'subtitle-asset-select'];
    selects.forEach(selectId => {
        const select = document.getElementById(selectId);
        if (select && globalConfig && globalConfig.logos) {
            const curVal = select.value;
            select.innerHTML = '<option value="">Không sử dụng</option>';
            globalConfig.logos.forEach(logo => {
                const opt = new Option(logo, logo);
                select.add(opt);
            });
            if (curVal) select.value = curVal;
        }
    });
}

// Render video queue container UI
function renderQueueList() {
    const list = document.getElementById('queue-list');
    const placeholder = document.getElementById('queue-empty-placeholder');
    if (!list || !placeholder) return;

    if (videoQueue.length === 0) {
        list.innerHTML = '';
        list.classList.add('hidden');
        placeholder.classList.remove('hidden');
        return;
    }

    placeholder.classList.add('hidden');
    list.classList.remove('hidden');
    list.innerHTML = '';

    videoQueue.forEach((path, idx) => {
        const name = path.includes('/') ? path.split('/').pop() : (path.includes('\\') ? path.split('\\').pop() : path);
        const item = document.createElement('div');
        item.className = "flex items-center justify-between bg-slate-950 border border-white/5 rounded-lg py-1.5 px-2.5 text-[10px] text-slate-300 font-medium select-none";
        item.innerHTML = `
            <span class="truncate pr-2 text-left flex-1" title="${path}">${idx + 1}. ${name}</span>
            <button type="button" onclick="removeVideoFromQueue('${path}')" class="text-slate-500 hover:text-rose-400 p-0.5 transition-colors">
                <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"></path></svg>
            </button>
        `;
        list.appendChild(item);
    });
}

// Remove video from the queue manually
function removeVideoFromQueue(path) {
    videoQueue = videoQueue.filter(p => p !== path);
    renderQueueList();
}

// Add manual input URL to the video queue
function addUrlToQueue() {
    const input = document.getElementById('input_video_url');
    if (!input) return;
    const url = input.value.trim();
    if (!url) {
        showToast("Vui lòng nhập URL hợp lệ!", "error");
        return;
    }

    if (videoQueue.includes(url)) {
        showToast("URL này đã có trong hàng đợi!", "warning");
        return;
    }

    videoQueue.push(url);
    input.value = '';
    renderQueueList();
    showToast("Đã thêm URL vào hàng đợi", "success");
}

// Bind drag-and-drop operations for internal library items
function setupQueueDragNDrop() {
    const zone = document.getElementById('queue-drop-zone');
    if (!zone) return;

    ['dragenter', 'dragover'].forEach(eventName => {
        zone.addEventListener(eventName, (e) => {
            e.preventDefault();
            e.stopPropagation();
            zone.classList.add('border-purple-500', 'bg-purple-500/10');
        }, false);
    });

    ['dragleave', 'drop'].forEach(eventName => {
        zone.addEventListener(eventName, (e) => {
            e.preventDefault();
            e.stopPropagation();
            zone.classList.remove('border-purple-500', 'bg-purple-500/10');
        }, false);
    });

    zone.addEventListener('drop', (e) => {
        const dt = e.dataTransfer;
        const path = dt.getData('text/plain');
        if (path) {
            if (!videoQueue.includes(path)) {
                videoQueue.push(path);
                renderQueueList();
                showToast("Đã thêm video kéo thả vào hàng chờ", "success");
            } else {
                showToast("Video này đã nằm trong hàng chờ!", "warning");
            }
        }
    });
}

// Switch between the Configuration Form and Video Queue inside the Persistent Sidebar
function switchSidebarTab(tab) {
    const configTab = document.getElementById('sidebar-tab-config');
    const queueTab = document.getElementById('sidebar-tab-queue');
    const btnConfig = document.getElementById('btn-sidebar-config');
    const btnQueue = document.getElementById('btn-sidebar-queue');

    if (tab === 'config') {
        if (configTab) configTab.classList.remove('hidden');
        if (queueTab) queueTab.classList.add('hidden');

        if (btnConfig) {
            btnConfig.className = "flex-1 py-1.5 text-xs font-semibold rounded-lg bg-white/10 text-white transition-all text-center";
        }
        if (btnQueue) {
            btnQueue.className = "flex-1 py-1.5 text-xs font-semibold rounded-lg text-slate-400 hover:text-white transition-all text-center";
        }
    } else if (tab === 'queue') {
        if (configTab) configTab.classList.add('hidden');
        if (queueTab) queueTab.classList.remove('hidden');

        if (btnConfig) {
            btnConfig.className = "flex-1 py-1.5 text-xs font-semibold rounded-lg text-slate-400 hover:text-white transition-all text-center";
        }
        if (btnQueue) {
            btnQueue.className = "flex-1 py-1.5 text-xs font-semibold rounded-lg bg-white/10 text-white transition-all text-center";
        }
    }
}

// Bind drag and drop listeners on the Sidebar Tab Button
function setupSidebarTabDragNDrop() {
    const tabQueueBtn = document.getElementById('btn-sidebar-queue');
    if (!tabQueueBtn) return;

    let hoverTimer = null;

    tabQueueBtn.addEventListener('dragover', (e) => {
        e.preventDefault();
        e.stopPropagation();
        tabQueueBtn.classList.add('bg-purple-650/40', 'text-white');

        // Auto switch sidebar tab to queue page after 600ms hovering while dragging
        if (!hoverTimer) {
            hoverTimer = setTimeout(() => {
                switchSidebarTab('queue');
            }, 600);
        }
    });

    tabQueueBtn.addEventListener('dragleave', (e) => {
        e.preventDefault();
        e.stopPropagation();
        tabQueueBtn.classList.remove('bg-purple-650/40', 'text-white');
        if (hoverTimer) {
            clearTimeout(hoverTimer);
            hoverTimer = null;
        }
    });

    tabQueueBtn.addEventListener('drop', (e) => {
        e.preventDefault();
        e.stopPropagation();
        tabQueueBtn.classList.remove('bg-purple-650/40', 'text-white');
        if (hoverTimer) {
            clearTimeout(hoverTimer);
            hoverTimer = null;
        }

        const url = e.dataTransfer.getData('text/plain');
        if (url) {
            importSearchedVideo(url);
        }
    });
}

// Global channels list
let globalChannels = [];

// Fetch output channels from backend store
async function loadChannels() {
    try {
        const response = await fetch('/api/pages');
        if (response.ok) {
            globalChannels = await response.json();
            if (typeof populateDashboardFilterChannel === 'function') {
                populateDashboardFilterChannel();
            }
            if (typeof populateDestChannelSelects === 'function') {
                populateDestChannelSelects();
            }
            if (currentTab === 'dashboard' && jobsData.length > 0) {
                renderJobsList();
            }
        }
    } catch (err) {
        console.error("Failed to load channels:", err);
    }
}

// Move/Publish job files to a selected channel directory
async function publishJob(jobId, channelId) {
    if (!channelId) return;

    try {
        const res = await fetch(`/api/jobs/${jobId}/publish`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ channel_id: channelId })
        });
        if (res.ok) {
            showToast("Đã di chuyển video sang kênh thành công!", "success");
            await loadJobs();
        } else {
            const data = await res.json();
            showToast(data.detail || "Lỗi di chuyển video!", "error");
        }
    } catch (err) {
        showToast("Lỗi kết nối máy chủ!", "error");
    }
}

// Open completed video file or destination folder on desktop
async function openOutputMedia(jobId, type) {
    try {
        const res = await fetch(`/api/jobs/${jobId}/path?type=${type}`);
        if (res.ok) {
            const data = await res.json();
            if (data.path) {
                await fetch('/api/media/open', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ path: data.path })
                });
            }
        }
    } catch (err) {
        console.error("Failed to open media path:", err);
    }
}

// Bind drag and drop listeners on the Dashboard Header Tab Button
function setupHeaderTabDragNDrop() {
    const tabDashboardBtn = document.getElementById('btn-tab-dashboard');
    if (!tabDashboardBtn) return;

    let hoverTimer = null;

    tabDashboardBtn.addEventListener('dragover', (e) => {
        e.preventDefault();
        e.stopPropagation();
        tabDashboardBtn.classList.add('bg-purple-650/40', 'text-white');

        // Auto switch tab to dashboard and open queue tab after 600ms hovering while dragging
        if (!hoverTimer) {
            hoverTimer = setTimeout(() => {
                switchTab('dashboard');
                switchSidebarTab('queue');
            }, 600);
        }
    });

    tabDashboardBtn.addEventListener('dragleave', (e) => {
        e.preventDefault();
        e.stopPropagation();
        tabDashboardBtn.classList.remove('bg-purple-650/40', 'text-white');
        if (hoverTimer) {
            clearTimeout(hoverTimer);
            hoverTimer = null;
        }
    });

    tabDashboardBtn.addEventListener('drop', (e) => {
        e.preventDefault();
        e.stopPropagation();
        tabDashboardBtn.classList.remove('bg-purple-650/40', 'text-white');
        if (hoverTimer) {
            clearTimeout(hoverTimer);
            hoverTimer = null;
        }

        const url = e.dataTransfer.getData('text/plain');
        if (url) {
            importSearchedVideo(url);
        }
    });
}

function populateDashboardFilterChannel() {
    const select = document.getElementById('dashboard-filter-channel');
    if (!select) return;

    // Clear dynamic options (keeping index 0 "Tất cả kênh" and index 1 "Output mặc định")
    while (select.options.length > 2) {
        select.remove(2);
    }

    globalChannels.forEach(c => {
        const opt = document.createElement('option');
        opt.value = c.id;
        opt.textContent = c.name;
        select.appendChild(opt);
    });

    select.value = currentFilterChannelId;
}

function filterJobsByChannel(channelId) {
    currentFilterChannelId = channelId;
    localStorage.setItem('currentFilterChannelId', channelId);
    renderJobsList();
}

function onChangeTargetLanguage(lang) {
    const container = document.getElementById('target_locale_container');
    const select = document.getElementById('target_locale');
    if (!container || !select) return;

    // Check lang prefix or exact matching
    const prefix = lang.split('-')[0].toLowerCase();

    if (prefix === 'es') {
        container.classList.remove('hidden');
        select.innerHTML = `
            <option value="es-MX" selected>Mỹ Latinh / Mexico (es-MX)</option>
            <option value="es-ES">Tây Ban Nha (es-ES)</option>
        `;
    } else if (prefix === 'pt') {
        container.classList.remove('hidden');
        select.innerHTML = `
            <option value="pt-BR" selected>Brazil (pt-BR)</option>
            <option value="pt-PT">Bồ Đào Nha (pt-PT)</option>
        `;
    } else {
        container.classList.add('hidden');
        select.innerHTML = '<option value="">Mặc định</option>';
    }
}

// Unified per-video pending flow. These definitions intentionally override the
// older global queue helpers above while keeping the existing drag/drop callers.
function detectPlatform(url) {
    const value = (url || '').toLowerCase();
    if (value.includes('douyin.com')) return 'Douyin';
    if (value.includes('bilibili.com') || value.includes('b23.tv')) return 'Bilibili';
    if (value.includes('xiaohongshu.com') || value.includes('xhslink.com')) return 'Xiaohongshu';
    if (value.includes('youtube.com') || value.includes('youtu.be')) return 'YouTube';
    return 'Unknown';
}

function defaultPendingConfig() {
    const getVal = (id, fallback) => {
        const el = document.getElementById(id);
        return el ? el.value : fallback;
    };
    const getChecked = (id, fallback) => {
        const el = document.getElementById(id);
        return el ? el.checked : fallback;
    };

    const base = (window.globalConfig && window.globalConfig.defaults)
        ? JSON.parse(JSON.stringify(window.globalConfig.defaults))
        : {};

    return {
        tone: getVal('tone', base.tone || 'review_phim'),
        voice: getVal('voice', base.voice || 'vi-VN-HoaiMyNeural'),
        rate: getVal('rate', base.rate || '+0%'),
        pitch: getVal('pitch', base.pitch || '+0Hz'),
        bgm: getVal('bgm', base.bgm || ''),
        logo: getVal('logo', base.logo || ''),
        channel_id: getVal('dest_channel', base.channel_id || ''),
        platform_folder: getVal('dest_platform', base.platform_folder || ''),
        subtitle_cover_mode: getVal('subtitle_cover_mode', base.subtitle_cover_mode || 'text_box_only'),
        subtitle_bg_opacity: parseFloat(getVal('subtitle_bg_opacity', base.subtitle_bg_opacity || '0.20')),
        subtitle_mask_padding_x: parseInt(getVal('subtitle_mask_padding_x', base.subtitle_mask_padding_x || '20')),
        subtitle_mask_padding_y: parseInt(getVal('subtitle_mask_padding_y', base.subtitle_mask_padding_y || '12')),
        ocr_sample_interval_sec: parseFloat(getVal('ocr_sample_interval_sec', base.ocr_sample_interval_sec || '0.75')),
        ocr_crop_bottom_ratio: parseFloat(getVal('ocr_crop_bottom_ratio', base.ocr_crop_bottom_ratio || '0.45')),
        tts_enabled: getChecked('tts_enabled', base.tts_enabled ?? true),
        subtitles_enabled: getChecked('subtitles_enabled', base.subtitles_enabled ?? true),
        mask: getChecked('mask', base.mask ?? true),
        ocr_only_mode: getChecked('ocr_only_mode', base.ocr_only_mode ?? false),
        target_language: getVal('target_language', base.target_language || 'vi-VN'),
        target_locale: getVal('target_locale', base.target_locale || ''),
        translation_mode: getVal('translation_mode', base.translation_mode || 'natural'),
        subtitle_style: getVal('subtitle_style', base.subtitle_style || 'word_highlight'),
        reverse_video: getChecked('reverse_video', base.reverse_video ?? false),
    };
}

function createPendingVideoItem(url) {
    return {
        id: `pending_${Date.now()}_${Math.random().toString(16).slice(2)}`,
        url,
        normalized_url: url,
        platform: detectPlatform(url),
        config: defaultPendingConfig()
    };
}

function optionList(options, selected, emptyLabel = null) {
    const rows = [];
    if (emptyLabel !== null) rows.push(`<option value="">${emptyLabel}</option>`);
    (options || []).forEach(opt => {
        const value = opt.id ?? opt.value ?? opt;
        const name = opt.name ?? opt.label ?? opt;
        rows.push(`<option value="${value}" ${String(value) === String(selected) ? 'selected' : ''}>${name}</option>`);
    });
    return rows.join('');
}

function pendingBgmOptions(selected) {
    const select = document.getElementById('detail-bgm') || document.getElementById('bgm');
    const values = [];
    if (select) {
        Array.from(select.options).forEach(opt => {
            if (opt.value) values.push({ id: opt.value, name: opt.textContent });
        });
    }
    return optionList(values, selected, 'Không BGM');
}

function pendingLogoOptions(selected) {
    return optionList((globalConfig.logos || []).map(logo => ({ id: logo, name: logo })), selected, 'Không logo');
}

function pendingChannelOptions(selected) {
    return optionList((globalChannels || []).map(c => ({ id: c.id, name: c.name })), selected, 'Output mặc định');
}

function updatePendingConfig(id, key, value) {
    const item = pendingVideoItems.find(entry => entry.id === id);
    if (!item) return;
    if (['subtitle_bg_opacity', 'subtitle_mask_padding_x', 'subtitle_mask_padding_y', 'ocr_sample_interval_sec', 'ocr_crop_bottom_ratio'].includes(key)) {
        const parsed = parseFloat(value);
        item.config[key] = Number.isFinite(parsed) ? parsed : item.config[key];
    } else if (['tts_enabled', 'subtitles_enabled', 'mask', 'ocr_only_mode'].includes(key)) {
        item.config[key] = Boolean(value);
    } else {
        item.config[key] = value;
    }
}

function applyPendingConfigToAll(id) {
    const source = pendingVideoItems.find(entry => entry.id === id);
    if (!source) return;
    pendingVideoItems.forEach(item => {
        if (item.id !== id) item.config = { ...source.config };
    });
    renderQueueList();
    showToast('Đã áp dụng cấu hình cho tất cả video', 'success');
}

function importSearchedVideo(url) {
    if (!pendingVideoItems.some(item => item.url === url)) {
        pendingVideoItems.push(createPendingVideoItem(url));
        videoQueue = pendingVideoItems;
        renderQueueList();
        showToast('Đã thêm video vào hàng chờ', 'success');
    } else {
        showToast('Video này đã nằm trong hàng chờ', 'warning');
    }
}

function renderQueueList() {
    const list = document.getElementById('queue-list');
    const placeholder = document.getElementById('queue-empty-placeholder');
    if (!list || !placeholder) return;

    if (pendingVideoItems.length === 0) {
        list.innerHTML = '';
        list.classList.add('hidden');
        placeholder.classList.remove('hidden');
        return;
    }

    placeholder.classList.add('hidden');
    list.classList.remove('hidden');
    list.innerHTML = '';

    pendingVideoItems.forEach((entry, idx) => {
        const cfg = entry.config;
        const name = entry.url.split(/[\\/]/).pop() || entry.url;
        const row = document.createElement('div');
        row.className = 'bg-slate-950 border border-white/5 rounded-xl p-3 flex flex-col gap-3 text-xs';
        row.innerHTML = `
            <div class="flex items-start justify-between gap-2">
                <div class="min-w-0">
                    <div class="text-[10px] font-bold text-purple-300 uppercase">${idx + 1}. ${entry.platform}</div>
                    <div class="text-slate-200 font-semibold truncate" title="${entry.url}">${name}</div>
                </div>
                <button type="button" onclick="removeVideoFromQueue('${entry.id}')" class="text-slate-500 hover:text-rose-400 p-1 transition-colors">Xóa</button>
            </div>
            <div class="grid grid-cols-2 gap-2">
                <select onchange="updatePendingConfig('${entry.id}','tone',this.value)" class="bg-slate-900 border border-slate-800 rounded-lg p-2" title="Tone">${optionList(globalConfig.tones, cfg.tone)}</select>
                <select onchange="updatePendingConfig('${entry.id}','voice',this.value)" class="bg-slate-900 border border-slate-800 rounded-lg p-2" title="Voice">${optionList(globalConfig.voices, cfg.voice)}</select>
                <select onchange="updatePendingConfig('${entry.id}','rate',this.value)" class="bg-slate-900 border border-slate-800 rounded-lg p-2" title="Rate">${optionList(globalConfig.rates, cfg.rate)}</select>
                <select onchange="updatePendingConfig('${entry.id}','pitch',this.value)" class="bg-slate-900 border border-slate-800 rounded-lg p-2" title="Pitch">${optionList(globalConfig.pitches, cfg.pitch)}</select>
                <select onchange="updatePendingConfig('${entry.id}','bgm',this.value)" class="bg-slate-900 border border-slate-800 rounded-lg p-2" title="BGM">${pendingBgmOptions(cfg.bgm)}</select>
                <select onchange="updatePendingConfig('${entry.id}','channel_id',this.value)" class="bg-slate-900 border border-slate-800 rounded-lg p-2" title="Page">${pendingChannelOptions(cfg.channel_id)}</select>
                <select onchange="updatePendingConfig('${entry.id}','platform_folder',this.value)" class="bg-slate-900 border border-slate-800 rounded-lg p-2" title="Platform">
                    <option value="" ${!cfg.platform_folder ? 'selected' : ''}>Không chia</option><option value="TikTok" ${cfg.platform_folder === 'TikTok' ? 'selected' : ''}>TikTok</option><option value="YouTube" ${cfg.platform_folder === 'YouTube' ? 'selected' : ''}>YouTube</option><option value="Facebook" ${cfg.platform_folder === 'Facebook' ? 'selected' : ''}>Facebook</option><option value="Douyin" ${cfg.platform_folder === 'Douyin' ? 'selected' : ''}>Douyin</option>
                </select>
                
                <select onchange="updatePendingConfig('${entry.id}','target_language',this.value); renderQueueList();" class="bg-slate-900 border border-slate-800 rounded-lg p-2" title="Ngôn ngữ đích">
                    <option value="vi-VN" ${cfg.target_language === 'vi-VN' ? 'selected' : ''}>Tiếng Việt</option>
                    <option value="en-US" ${cfg.target_language === 'en-US' ? 'selected' : ''}>English</option>
                    <option value="es-ES" ${cfg.target_language === 'es-ES' ? 'selected' : ''}>Español</option>
                    <option value="pt-BR" ${cfg.target_language === 'pt-BR' ? 'selected' : ''}>Português</option>
                    <option value="ru-RU" ${cfg.target_language === 'ru-RU' ? 'selected' : ''}>Русский</option>
                    <option value="th-TH" ${cfg.target_language === 'th-TH' ? 'selected' : ''}>Thai</option>
                    <option value="id-ID" ${cfg.target_language === 'id-ID' ? 'selected' : ''}>Indonesian</option>
                    <option value="ja-JP" ${cfg.target_language === 'ja-JP' ? 'selected' : ''}>Japanese</option>
                    <option value="ko-KR" ${cfg.target_language === 'ko-KR' ? 'selected' : ''}>Korean</option>
                </select>
                
                <select onchange="updatePendingConfig('${entry.id}','translation_mode',this.value)" class="bg-slate-900 border border-slate-800 rounded-lg p-2" title="Chế độ dịch">
                    <option value="natural" ${cfg.translation_mode === 'natural' ? 'selected' : ''}>Dịch tự nhiên</option>
                    <option value="localized" ${cfg.translation_mode === 'localized' ? 'selected' : ''}>Bản địa hóa</option>
                    <option value="literal" ${cfg.translation_mode === 'literal' ? 'selected' : ''}>Dịch sát nghĩa</option>
                </select>
                
                <select onchange="updatePendingConfig('${entry.id}','subtitle_style',this.value)" class="bg-slate-900 border border-slate-800 rounded-lg p-2" title="Kiểu phụ đề">
                    <option value="default" ${cfg.subtitle_style === 'default' ? 'selected' : ''}>Hiện cả câu (Mặc định)</option>
                    <option value="karaoke" ${cfg.subtitle_style === 'karaoke' ? 'selected' : ''}>Chạy chữ Karaoke</option>
                    <option value="word_highlight" ${cfg.subtitle_style === 'word_highlight' ? 'selected' : ''}>Hiện từng chữ đơn lẻ</option>
                </select>

                ${(cfg.target_language && (cfg.target_language.startsWith('es') || cfg.target_language.startsWith('pt'))) ? `
                <select onchange="updatePendingConfig('${entry.id}','target_locale',this.value)" class="bg-slate-900 border border-slate-800 rounded-lg p-2 col-span-2" title="Locale">
                    ${cfg.target_language.startsWith('es') ? `
                        <option value="es-MX" ${cfg.target_locale === 'es-MX' ? 'selected' : ''}>Mỹ Latinh (es-MX)</option>
                        <option value="es-ES" ${cfg.target_locale === 'es-ES' ? 'selected' : ''}>Tây Ban Nha (es-ES)</option>
                    ` : `
                        <option value="pt-BR" ${cfg.target_locale === 'pt-BR' ? 'selected' : ''}>Brazil (pt-BR)</option>
                        <option value="pt-PT" ${cfg.target_locale === 'pt-PT' ? 'selected' : ''}>Bồ Đào Nha (pt-PT)</option>
                    `}
                </select>
                ` : ''}
            </div>

            <div class="flex items-center justify-between gap-2 text-[10px] text-slate-400">
                <label class="flex items-center gap-1"><input type="checkbox" ${cfg.ocr_only_mode ? 'checked' : ''} onchange="updatePendingConfig('${entry.id}','ocr_only_mode',this.checked)"> Không lời (OCR)</label>
                <label class="flex items-center gap-1"><input type="checkbox" ${cfg.tts_enabled ? 'checked' : ''} onchange="updatePendingConfig('${entry.id}','tts_enabled',this.checked)"> TTS</label>
                <label class="flex items-center gap-1"><input type="checkbox" ${cfg.subtitles_enabled ? 'checked' : ''} onchange="updatePendingConfig('${entry.id}','subtitles_enabled',this.checked)"> Phụ đề</label>
                <label class="flex items-center gap-1"><input type="checkbox" ${cfg.reverse_video ? 'checked' : ''} onchange="updatePendingConfig('${entry.id}','reverse_video',this.checked)"> Ngược video</label>
                <button type="button" onclick="applyPendingConfigToAll('${entry.id}')" class="text-purple-300 hover:text-white font-semibold">Áp dụng cho tất cả</button>
            </div>
        `;
        list.appendChild(row);
    });
}

function removeVideoFromQueue(id) {
    pendingVideoItems = pendingVideoItems.filter(item => item.id !== id);
    videoQueue = pendingVideoItems;
    renderQueueList();
}

function addUrlToQueue() {
    const input = document.getElementById('input_video_url');
    if (!input) return;
    const urls = input.value.split(/\r?\n/).map(value => value.trim()).filter(Boolean);
    if (urls.length === 0) {
        showToast('Vui lòng nhập ít nhất một link', 'error');
        return;
    }
    let added = 0;
    urls.forEach(url => {
        if (!pendingVideoItems.some(item => item.url === url)) {
            pendingVideoItems.push(createPendingVideoItem(url));
            added += 1;
        }
    });
    videoQueue = pendingVideoItems;
    input.value = '';
    renderQueueList();
    showToast(`Đã thêm ${added} video vào hàng chờ`, 'success');
}

function setupQueueDragNDrop() {
    const zone = document.getElementById('queue-drop-zone');
    if (!zone) return;

    ['dragenter', 'dragover'].forEach(eventName => {
        zone.addEventListener(eventName, (e) => {
            e.preventDefault();
            e.stopPropagation();
            zone.classList.add('border-purple-500', 'bg-purple-500/10');
        }, false);
    });

    ['dragleave', 'drop'].forEach(eventName => {
        zone.addEventListener(eventName, (e) => {
            e.preventDefault();
            e.stopPropagation();
            zone.classList.remove('border-purple-500', 'bg-purple-500/10');
        }, false);
    });

    zone.addEventListener('drop', (e) => {
        const url = e.dataTransfer.getData('text/plain');
        if (url) importSearchedVideo(url);
    });
}

// --- Manual subtitle layout preview flow ---
const DEFAULT_SUBTITLE_LAYOUT = { x: 0.08, y: 0.57, width: 0.84, height: 0.08 };
let subtitleLayoutEditorReady = false;
let subtitleLayoutEditorListenersBound = false;
let subtitleLayoutEditorJobId = null;
let subtitleLayoutState = { ...DEFAULT_SUBTITLE_LAYOUT, background_opacity: 0.20, preset: 'middle' };
let isEditingSubtitleLayout = false;
let subtitleLayoutSubmitMode = 'initial';

function isWaitingForSubtitleLayout(job) {
    return job && (job.status === 'waiting_for_subtitle_layout' || job.status === 'awaiting_subtitle_layout');
}

function getSubtitleLayoutBoxPercent() {
    const box = document.getElementById('subtitle-layout-box');
    const wrap = document.getElementById('subtitle-preview-wrap');
    if (!box || !wrap) return DEFAULT_SUBTITLE_LAYOUT;
    const b = box.getBoundingClientRect();
    const w = wrap.getBoundingClientRect();
    return {
        x: Math.max(0, Math.min(0.95, (b.left - w.left) / w.width)),
        y: Math.max(0, Math.min(0.95, (b.top - w.top) / w.height)),
        width: Math.max(0.10, Math.min(1, b.width / w.width)),
        height: Math.max(0.04, Math.min(0.40, b.height / w.height))
    };
}

function applySubtitleLayoutBox(layout = DEFAULT_SUBTITLE_LAYOUT) {
    const box = document.getElementById('subtitle-layout-box');
    if (!box) return;
    box.style.left = '10%';
    box.style.top = `${(layout.y ?? DEFAULT_SUBTITLE_LAYOUT.y) * 100}%`;
    box.style.width = '80%';
    box.style.height = '8%';
}

let currentSubtitleJob = null;
let activeLayoutFormat = 'fb_reels';
let formatSubtitleLayouts = {};
let formatCrops = {};

let logoRemovedForThisJob = false;

function loadJobLogoPreview(job) {
    const logoDiv = document.getElementById('subtitle-logo-preview');
    const logoImg = document.getElementById('subtitle-logo-preview-img');
    if (!logoDiv || !logoImg) return;

    logoDiv.classList.add('hidden');
    logoImg.src = '';

    logoImg.src = `/api/jobs/${job.job_id}/logo?t=${Date.now()}`;

    logoImg.onload = () => {
        logoDiv.classList.remove('hidden');

        const snapshot = job.config_snapshot || {};
        const logoLayout = snapshot.logo_layout || null;

        // Initialize window.logoLayout so drag state is preserved
        window.logoLayout = logoLayout;

        logoDiv.style.left = '';
        logoDiv.style.right = '';
        logoDiv.style.top = '';
        logoDiv.style.bottom = '';
        logoDiv.style.transform = '';

        if (logoLayout && logoLayout.x_percent !== undefined) {
            logoDiv.style.left = `${logoLayout.x_percent * 100}%`;
            logoDiv.style.top = `${logoLayout.y_percent * 100}%`;
            if (logoLayout.width_percent) {
                logoDiv.style.width = `${logoLayout.width_percent * 100}%`;
            } else {
                logoDiv.style.width = '40px';
            }
            if (logoLayout.height_percent) {
                logoDiv.style.height = `${logoLayout.height_percent * 100}%`;
            } else {
                logoDiv.style.height = '25px';
            }
        } else {
            // Reset to default dimensions
            logoDiv.style.width = '40px';
            logoDiv.style.height = '25px';

            // If active layout format is vertical (9:16) where 16:9 landscape is centered,
            // place default logo at the top-left of the original video (left: 6%, top: 36%)
            if (activeLayoutFormat === 'yt_video') {
                logoDiv.style.left = '2.5%';
                logoDiv.style.top = '2.5%';
                window.logoLayout = { x_percent: 0.025, y_percent: 0.025 };
            } else {
                logoDiv.style.left = '2.5%';
                logoDiv.style.top = '35.5%';
                window.logoLayout = { x_percent: 0.025, y_percent: 0.355 };
            }
        }
    };

    logoImg.onerror = () => {
        logoDiv.classList.add('hidden');
        window.logoLayout = null;
    };
}

function switchSubtitleFormat(fmt) {
    if (!currentSubtitleJob) return;
    activeLayoutFormat = fmt;

    // Update button styles
    ['fb_reels', 'yt_shorts', 'yt_video'].forEach(f => {
        const btn = document.getElementById(`layout-switch-${f}`);
        if (btn) {
            if (f === fmt) {
                btn.className = "px-3 py-1.5 text-xs font-semibold rounded-lg bg-purple-600 text-white shadow-sm transition-all";
            } else {
                btn.className = "px-3 py-1.5 text-xs font-semibold rounded-lg text-slate-300 hover:text-white transition-all";
            }
        }
    });

    const wrap = document.getElementById('subtitle-preview-wrap');
    const cropOverlay = document.getElementById('preview-crop-overlay');
    const layoutBox = document.getElementById('subtitle-layout-box');

    if (!wrap || !cropOverlay || !layoutBox) return;

    const isInputHorizontal = currentSubtitleJob.input_aspect_type === 'horizontal';
    const isTargetVertical = (fmt === 'fb_reels' || fmt === 'yt_shorts');
    const reframeMode = currentSubtitleJob.config_snapshot?.[`${fmt}_reframe_mode`] || 'blur_background';
    const showManualCrop = isInputHorizontal && isTargetVertical && (reframeMode === 'manual_crop');

    if (showManualCrop) {
        wrap.className = "relative mx-auto w-full max-w-[450px] aspect-[16/9] bg-black rounded-xl overflow-hidden border border-white/10 select-none";
        cropOverlay.classList.remove('hidden');

        const cropWindow = document.getElementById('preview-crop-window');
        if (layoutBox.parentNode !== cropWindow) {
            cropWindow.appendChild(layoutBox);
        }

        const defaultCrop = { crop_x_percent: 0.342, crop_y_percent: 0, crop_width_percent: 0.316, crop_height_percent: 1.0 };
        const savedCrop = formatCrops[fmt] || currentSubtitleJob.config_snapshot?.[`${fmt}_crop`] || defaultCrop;
        formatCrops[fmt] = { ...savedCrop };

        const leftPercent = formatCrops[fmt].crop_x_percent * 100;
        cropWindow.style.left = `${leftPercent}%`;

        updateCropShades(leftPercent);
        setupCropDragging(cropWindow, wrap);

    } else {
        cropOverlay.classList.add('hidden');
        if (layoutBox.parentNode !== wrap) {
            wrap.appendChild(layoutBox);
        }

        if (isTargetVertical) {
            wrap.className = "relative mx-auto w-full max-w-[340px] aspect-[9/16] bg-black rounded-xl overflow-hidden border border-white/10 select-none";
        } else {
            wrap.className = "relative mx-auto w-full max-w-[450px] aspect-[16/9] bg-black rounded-xl overflow-hidden border border-white/10 select-none";
        }
    }

    const defaultLayout = (fmt === 'yt_video')
        ? { x: 0.08, y: 0.75, width: 0.84, height: 0.08 }
        : { x: 0.08, y: 0.57, width: 0.84, height: 0.08 };

    const savedLayout = formatSubtitleLayouts[fmt] || currentSubtitleJob.config_snapshot?.[`${fmt}_subtitle_layout`] || currentSubtitleJob.config_snapshot?.subtitle_layout || defaultLayout;
    subtitleLayoutState = { ...savedLayout };
    applySubtitleLayoutBox(subtitleLayoutState);

    // Also update logo preview coordinates based on layout format change
    loadJobLogoPreview(currentSubtitleJob);
}

function updateCropShades(leftPercent) {
    const shadeLeft = document.getElementById('preview-crop-shade-left');
    const shadeRight = document.getElementById('preview-crop-shade-right');
    const widthPercent = 31.625;

    if (shadeLeft) shadeLeft.style.width = `${leftPercent}%`;
    if (shadeRight) {
        shadeRight.style.left = `${leftPercent + widthPercent}%`;
        shadeRight.style.width = `${100 - (leftPercent + widthPercent)}%`;
    }
}

function setupCropDragging(cropWindow, wrap) {
    let isDragging = false;
    let startX = 0;
    let startLeft = 0;

    cropWindow.onmousedown = (e) => {
        if (e.target !== cropWindow) return;
        e.preventDefault();
        isDragging = true;
        startX = e.clientX;

        const wrapWidth = wrap.clientWidth;
        const currentLeftPx = parseFloat(cropWindow.style.left) * wrapWidth / 100 || 0;
        startLeft = currentLeftPx;

        document.onmousemove = (moveEvent) => {
            if (!isDragging) return;
            const deltaX = moveEvent.clientX - startX;
            let newLeftPx = startLeft + deltaX;

            const maxLeftPx = wrapWidth - cropWindow.clientWidth;
            newLeftPx = Math.max(0, Math.min(maxLeftPx, newLeftPx));

            const leftPercent = (newLeftPx / wrapWidth) * 100;
            cropWindow.style.left = `${leftPercent}%`;

            if (!formatCrops[activeLayoutFormat]) {
                formatCrops[activeLayoutFormat] = {};
            }
            formatCrops[activeLayoutFormat].crop_x_percent = newLeftPx / wrapWidth;

            updateCropShades(leftPercent);
        };

        document.onmouseup = () => {
            isDragging = false;
            document.onmousemove = null;
            document.onmouseup = null;
        };
    };
}

function saveSubtitleLayoutLocalState() {
    const opacity = parseFloat(document.getElementById('subtitle-layout-opacity')?.value || subtitleLayoutState.background_opacity || '0.20');
    subtitleLayoutState = {
        ...subtitleLayoutState,
        ...getSubtitleLayoutBoxPercent(),
        background_opacity: Number.isFinite(opacity) ? opacity : 0.20
    };
    if (activeLayoutFormat) {
        formatSubtitleLayouts[activeLayoutFormat] = { ...subtitleLayoutState };
    }
}

function updateSubtitleLayoutSummary(job) {
    const summary = document.getElementById('subtitle-layout-summary');
    if (!summary) return;
    const snapshot = job?.config_snapshot || {};
    const opacity = Math.round((snapshot.subtitle_bg_opacity ?? subtitleLayoutState.background_opacity ?? 0.20) * 100);
    summary.innerText = `Opacity: ${opacity}%`;
}

function resetSubtitleLayoutBox() {
    const defaultLayout = (activeLayoutFormat === 'yt_video')
        ? { x: 0.08, y: 0.75, width: 0.84, height: 0.08 }
        : { x: 0.08, y: 0.57, width: 0.84, height: 0.08 };
    subtitleLayoutState = { ...defaultLayout, background_opacity: subtitleLayoutState.background_opacity ?? 0.20, preset: 'custom' };
    applySubtitleLayoutBox(subtitleLayoutState);
    if (activeLayoutFormat) {
        formatSubtitleLayouts[activeLayoutFormat] = { ...subtitleLayoutState };
    }
}

function previewSubtitleBackplateOpacity(value) {
    const box = document.getElementById('subtitle-layout-box');
    if (box) {
        const plate = box.querySelector('.subtitle-plate-bg');
        if (plate) {
            plate.style.background = `rgba(0,0,0,${value})`;
            plate.style.backdropFilter = `blur(10px)`;
            plate.style.webkitBackdropFilter = `blur(10px)`;
        }
    }
    const opacity = parseFloat(value);
    subtitleLayoutState.background_opacity = Number.isFinite(opacity) ? opacity : subtitleLayoutState.background_opacity;
}

function setSubtitleEditorSubmitMode(mode) {
    subtitleLayoutSubmitMode = mode || 'initial';
    const btn = document.getElementById('btn-continue-render');
    if (!btn) return;
    btn.innerText = subtitleLayoutSubmitMode === 'rerender'
        ? 'Render lại với vị trí mới'
        : 'Tiếp tục render video';
}

function escapeHtml(value) {
    return String(value)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#039;');
}

function getJobDisplayTitle(job) {
    const input = job?.input_path || job?.job_id || '';
    try {
        const url = new URL(input);
        const videoId = url.searchParams.get('vid') || url.searchParams.get('modal_id');
        return videoId ? `${url.hostname} / ${videoId}` : url.hostname;
    } catch (_) {
        return input.split(/[\\/]/).pop();
    }
}

function updateSubtitlePreviewText() {
    const box = document.getElementById('subtitle-layout-box');
    const textWrap = box?.querySelector('.subtitle-plate-bg');
    if (!textWrap) return;
    textWrap.textContent = 'Tôi đã bảo bạn làm thế.';
}

async function onChangeEditorChannel(channelId) {
    if (!currentSubtitleJob) return;
    try {
        const res = await fetch(`/api/jobs/${currentSubtitleJob.job_id}/publish`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ channel_id: channelId })
        });
        if (res.ok) {
            const newChanId = channelId === 'default' ? null : channelId;
            currentSubtitleJob.channel_id = newChanId;
            if (currentSubtitleJob.config_snapshot) {
                currentSubtitleJob.config_snapshot.channel_id = newChanId;
            }
            showToast("Đã cập nhật kênh đầu ra thành công!", "success");
            await loadJobs();
            loadJobLogoPreview(currentSubtitleJob);
        } else {
            showToast("Lỗi cập nhật kênh đầu ra!", "error");
        }
    } catch (err) {
        showToast("Lỗi kết nối máy chủ!", "error");
    }
}

function setupSubtitleLayoutEditor(job) {
    const section = document.getElementById('subtitle-layout-section');
    const video = document.getElementById('subtitle-preview-video');
    const box = document.getElementById('subtitle-layout-box');
    const resize = document.getElementById('subtitle-layout-resize');
    const wrap = document.getElementById('subtitle-preview-wrap');
    if (!section || !video || !box || !resize || !wrap) return;

    section.classList.remove('hidden');

    const isNewEditorJob = subtitleLayoutEditorJobId !== job.job_id;
    if (isNewEditorJob) {
        subtitleLayoutEditorJobId = job.job_id;
        currentSubtitleJob = job;
        logoRemovedForThisJob = false;

        const editorChannelSelect = document.getElementById('editor-channel-select');
        if (editorChannelSelect) {
            editorChannelSelect.innerHTML = '<option value="default">Output mặc định</option>';
            (globalChannels || []).forEach(c => {
                const opt = new Option(c.name, c.id);
                editorChannelSelect.add(opt);
            });
            editorChannelSelect.value = job.channel_id || 'default';
        }

        const snapshot = job.config_snapshot || {};
        const styleSelect = document.getElementById('subtitle-layout-style');
        if (styleSelect) {
            styleSelect.value = snapshot.subtitle_style || 'default';
        }
        formatSubtitleLayouts = {};
        formatCrops = {};

        ['fb_reels', 'yt_shorts', 'yt_video'].forEach(fmt => {
            if (snapshot[`${fmt}_subtitle_layout`]) {
                formatSubtitleLayouts[fmt] = snapshot[`${fmt}_subtitle_layout`];
            }
            if (snapshot[`${fmt}_crop`]) {
                formatCrops[fmt] = snapshot[`${fmt}_crop`];
            }
        });

        const selectedOutputs = snapshot.selected_outputs || ['fb_reels'];

        ['fb_reels', 'yt_shorts', 'yt_video'].forEach(fmt => {
            const btn = document.getElementById(`layout-switch-${fmt}`);
            if (btn) {
                if (selectedOutputs.includes(fmt)) {
                    btn.classList.remove('hidden');
                } else {
                    btn.classList.add('hidden');
                }
            }
        });

        activeLayoutFormat = selectedOutputs[0] || 'fb_reels';

        if (!video.src || !video.src.includes(job.job_id)) {
            video.src = `/api/jobs/${job.job_id}/preview-video`;
        }

        if (snapshot.reverse_video) {
            video.style.transform = 'scaleX(-1)';
        } else {
            video.style.transform = '';
        }

        switchSubtitleFormat(activeLayoutFormat);

        // Clear any existing blur boxes from previous jobs
        document.querySelectorAll('.subtitle-blur-box-instance').forEach(el => el.remove());
        subtitleBlurBoxes = [];
        nextBlurBoxId = 1;
        activeBlurBoxId = null;

        // Load multiple blur masks from snapshot
        const savedBlurMasks = job.config_snapshot?.blur_masks || [];
        savedBlurMasks.forEach(mask => {
            const newBox = {
                id: nextBlurBoxId++,
                x_percent: mask.x_percent ?? 0.40,
                y_percent: mask.y_percent ?? 0.15,
                width_percent: mask.width_percent ?? 0.20,
                height_percent: mask.height_percent ?? 0.08,
                opacity: mask.opacity ?? 0.6
            };
            subtitleBlurBoxes.push(newBox);
            createBlurBoxElement(newBox);
        });

        renderBlurMasksList();
        if (subtitleBlurBoxes.length > 0) {
            selectBlurMask(subtitleBlurBoxes[0].id);
        } else {
            const controls = document.getElementById('active-blur-controls');
            if (controls) controls.classList.add('hidden');
        }

        // Dynamically load and show logo preview
        loadJobLogoPreview(job);
    }
    updateSubtitlePreviewText();

    if (subtitleLayoutEditorListenersBound) return;
    subtitleLayoutEditorListenersBound = true;

    let mode = null;
    let start = null;
    const onPointerDown = (e, nextMode) => {
        isEditingSubtitleLayout = true;
        mode = nextMode;
        const rect = box.parentElement.getBoundingClientRect();
        const b = box.getBoundingClientRect();
        start = {
            mouseX: e.clientX,
            mouseY: e.clientY,
            x: b.left - rect.left,
            y: b.top - rect.top,
            w: b.width,
            h: b.height,
            wrapW: rect.width,
            wrapH: rect.height
        };
        e.preventDefault();
        e.stopPropagation();
    };

    box.addEventListener('pointerdown', (e) => {
        if (e.target === resize) return;
        onPointerDown(e, 'move');
    });
    resize.addEventListener('pointerdown', (e) => onPointerDown(e, 'resize'));

    document.addEventListener('pointermove', (e) => {
        if (!mode || !start) return;
        e.preventDefault();
        e.stopPropagation();
        const dx = e.clientX - start.mouseX;
        const dy = e.clientY - start.mouseY;
        if (mode === 'move') {
            const ny = Math.max(0, Math.min(start.wrapH - start.h, start.y + dy));
            box.style.left = '10%';
            box.style.width = '80%';
            box.style.top = `${(ny / start.wrapH) * 100}%`;
        } else {
            const nw = Math.max(start.wrapW * 0.20, Math.min(start.wrapW - start.x, start.w + dx));
            const nh = Math.max(start.wrapH * 0.05, Math.min(start.wrapH * 0.40, start.h + dy));
            box.style.width = `${(nw / start.wrapW) * 100}%`;
            box.style.height = `${(nh / start.wrapH) * 100}%`;
        }
    });

    document.addEventListener('pointerup', (e) => {
        if (mode) {
            e.preventDefault();
            e.stopPropagation();
            saveSubtitleLayoutLocalState();
        }
        mode = null;
        start = null;
        setTimeout(() => {
            isEditingSubtitleLayout = false;
        }, 150);
    });

    // Setup draggable and resizable asset box in review screen
    const assetBox = document.getElementById('subtitle-asset-box');
    const assetResize = document.getElementById('subtitle-asset-resize');


    // Setup draggable logo preview box & resizer
    const logoBox = document.getElementById('subtitle-logo-preview');
    const logoResize = document.getElementById('subtitle-logo-resize');
    if (logoBox) {
        let draggingLogo = false;
        let resizingLogo = false;
        let startX = 0, startY = 0;
        let startLeft = 0, startTop = 0;
        let startWidth = 0, startHeight = 0;

        logoBox.addEventListener('pointerdown', (e) => {
            if (e.target === logoResize || e.target.tagName.toLowerCase() === 'button') return;
            e.preventDefault();
            e.stopPropagation();
            draggingLogo = true;
            startX = e.clientX;
            startY = e.clientY;

            const rect = wrap.getBoundingClientRect();
            const b = logoBox.getBoundingClientRect();
            startLeft = b.left - rect.left;
            startTop = b.top - rect.top;

            const onLogoMove = (moveEvent) => {
                if (!draggingLogo) return;
                const rect = wrap.getBoundingClientRect();
                let deltaX = moveEvent.clientX - startX;
                let deltaY = moveEvent.clientY - startY;

                let newLeftPx = startLeft + deltaX;
                let newTopPx = startTop + deltaY;

                newLeftPx = Math.max(0, Math.min(rect.width - b.width, newLeftPx));
                newTopPx = Math.max(0, Math.min(rect.height - b.height, newTopPx));

                const xPct = newLeftPx / rect.width;
                const yPct = newTopPx / rect.height;

                window.logoLayout = {
                    ...window.logoLayout,
                    x_percent: xPct,
                    y_percent: yPct
                };

                logoBox.style.transform = '';
                logoBox.style.left = `${xPct * 100}%`;
                logoBox.style.top = `${yPct * 100}%`;
            };

            const onLogoUp = () => {
                draggingLogo = false;
                document.removeEventListener('pointermove', onLogoMove);
                document.removeEventListener('pointerup', onLogoUp);
            };

            document.addEventListener('pointermove', onLogoMove);
            document.addEventListener('pointerup', onLogoUp);
        });

        if (logoResize) {
            logoResize.addEventListener('pointerdown', (e) => {
                e.preventDefault();
                e.stopPropagation();
                resizingLogo = true;
                startX = e.clientX;
                startY = e.clientY;

                const rect = wrap.getBoundingClientRect();
                const b = logoBox.getBoundingClientRect();
                startWidth = b.width;
                startHeight = b.height;

                const onLogoResizeMove = (moveEvent) => {
                    if (!resizingLogo) return;
                    let deltaX = moveEvent.clientX - startX;
                    let deltaY = moveEvent.clientY - startY;

                    let newWidthPx = startWidth + deltaX;
                    let newHeightPx = startHeight + deltaY;

                    newWidthPx = Math.max(20, Math.min(rect.width - (b.left - rect.left), newWidthPx));
                    newHeightPx = Math.max(10, Math.min(rect.height - (b.top - rect.top), newHeightPx));

                    const wPct = newWidthPx / rect.width;
                    const hPct = newHeightPx / rect.height;

                    window.logoLayout = {
                        ...window.logoLayout,
                        width_percent: wPct,
                        height_percent: hPct
                    };

                    logoBox.style.width = `${wPct * 100}%`;
                    logoBox.style.height = `${hPct * 100}%`;
                };

                const onLogoResizeUp = () => {
                    resizingLogo = false;
                    document.removeEventListener('pointermove', onLogoResizeMove);
                    document.removeEventListener('pointerup', onLogoResizeUp);
                };

                document.addEventListener('pointermove', onLogoResizeMove);
                document.addEventListener('pointerup', onLogoResizeUp);
            });
        }
    }
}

async function continueRenderWithSubtitleLayout() {
    if (!selectedJobId) return;
    const btn = document.getElementById('btn-continue-render');
    saveSubtitleLayoutLocalState();

    if (btn) {
        btn.disabled = true;
        btn.innerText = 'Đang render...';
    }
    try {
        // Crops are no longer saved, default is always blur background

        const opacity = subtitleLayoutState.background_opacity;
        const layout = { ...subtitleLayoutState };

        const endpoint = subtitleLayoutSubmitMode === 'rerender'
            ? `/api/jobs/${selectedJobId}/rerender-subtitle-layout`
            : `/api/jobs/${selectedJobId}/subtitle-layout`;

        const payload = {
            subtitle_x_percent: layout.x,
            subtitle_y_percent: layout.y,
            subtitle_width_percent: layout.width,
            subtitle_height_percent: layout.height,
            subtitle_bg_opacity: opacity,
            background_opacity: opacity,
            preset: layout.preset || 'custom',
            subtitle_style: document.getElementById('subtitle-layout-style')?.value || 'default'
        };

        if (logoRemovedForThisJob) {
            payload.logo_x_percent = -1;
            payload.logo_y_percent = -1;
        } else if (window.logoLayout) {
            payload.logo_x_percent = window.logoLayout.x_percent;
            payload.logo_y_percent = window.logoLayout.y_percent;
            payload.logo_width_percent = window.logoLayout.width_percent || 0.085;
            payload.logo_height_percent = window.logoLayout.height_percent || 0.05;
        }

        const mapLayout = (l) => {
            if (!l) return null;
            return {
                subtitle_x_percent: l.x,
                subtitle_y_percent: l.y,
                subtitle_width_percent: l.width,
                subtitle_height_percent: l.height,
                subtitle_bg_opacity: l.background_opacity || 0.20,
                preset: l.preset || 'custom'
            };
        };
        payload.fb_reels_subtitle_layout = mapLayout(formatSubtitleLayouts.fb_reels);
        payload.yt_shorts_subtitle_layout = mapLayout(formatSubtitleLayouts.yt_shorts);
        payload.yt_video_subtitle_layout = mapLayout(formatSubtitleLayouts.yt_video);

        payload.asset = "";
        payload.blur_masks = subtitleBlurBoxes;

        const resp = await fetch(endpoint, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        if (!resp.ok) {
            const err = await resp.json();
            throw new Error(err.detail || 'Khong the tiep tuc render');
        }
        document.getElementById('subtitle-layout-section')?.classList.add('hidden');
        const panel = document.getElementById('detail-panel');
        if (panel) {
            panel.classList.add('lg:w-[650px]');
        }
        subtitleLayoutEditorJobId = null;
        subtitleLayoutEditorReady = false;
        isEditingSubtitleLayout = false;
        if (subtitleLayoutSubmitMode === 'rerender') {
            const freshJob = await (await fetch(`/api/jobs/${selectedJobId}`)).json();
            updateSubtitleLayoutSummary(freshJob);
            showToast('Đã render lại video với vị trí phụ đề mới', 'success');
        } else {
            showToast('Đã lưu vị trí phụ đề, đang render video...', 'success');
        }
        await loadJobs();
    } catch (err) {
        showToast(err.message, 'error');
    } finally {
        if (btn) {
            btn.disabled = false;
            btn.innerText = subtitleLayoutSubmitMode === 'rerender'
                ? 'Render lại với vị trí mới'
                : 'Tiếp tục render video';
        }
    }
}

function setSubtitlePreviewSize(width) {
    const wrap = document.getElementById('subtitle-preview-wrap');
    if (!wrap) return;
    wrap.style.maxWidth = `${width}px`;

    [200, 260].forEach(w => {
        const btn = document.getElementById(`btn-zoom-${w}`);
        if (btn) {
            if (w === width) {
                btn.className = "px-2.5 py-0.5 text-[9px] rounded font-bold bg-purple-600/30 text-purple-200 border border-purple-500/20 transition-all";
            } else {
                btn.className = "px-2.5 py-0.5 text-[9px] rounded font-bold text-slate-400 hover:text-white transition-all";
            }
        }
    });
}

async function openCompletedSubtitleLayoutEditor() {
    if (!selectedJobId) return;
    const job = await (await fetch(`/api/jobs/${selectedJobId}`)).json();
    document.getElementById('subtitle-layout-section')?.classList.remove('hidden');
    setSubtitleEditorSubmitMode('rerender');
    subtitleLayoutEditorJobId = null;
    setupSubtitleLayoutEditor(job);
    const panel = document.getElementById('detail-panel');
    if (panel) {
        panel.classList.add('lg:w-[650px]');
    }
    const section = document.getElementById('subtitle-layout-section');
    if (section) section.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

function updatePipelineSteps(job) {
    const list = document.getElementById('pipeline-steps-list');
    if (!list) return;
    list.innerHTML = '';
    const friendlyNames = {
        intake: '1. Tải / Nhập video',
        analyze: '2. Phân tích khung hình',
        extract_audio: '3. Tách âm thanh gốc',
        transcribe: '4. Nhận diện giọng nói (ASR)',
        translate: '5. Dịch phụ đề (AI)',
        tts: '6. Sinh giọng nói mới (TTS)',
        mix_audio: '7. Trộn âm thanh & nhạc nền',
        subtitle_layout: '8. Chọn vị trí phụ đề',
        render: '9. Render video',
        metadata: '10. Tiêu đề & Hashtags (AI)'
    };
    for (const step of Object.keys(friendlyNames)) {
        const status = job.steps?.[step] || 'pending';
        let statusIcon = '<span class="text-slate-600">Đang chờ</span>';
        let textStyle = 'text-slate-400';
        if (status === 'completed') {
            statusIcon = '<span class="text-emerald-400 font-bold">Hoàn tất</span>';
            textStyle = 'text-slate-300';
        } else if (status === 'failed') {
            statusIcon = '<span class="text-rose-400 font-bold">Thất bại</span>';
            textStyle = 'text-white font-semibold';
        } else if (step === job.current_step && job.status === 'running') {
            statusIcon = '<span class="text-purple-400 font-bold animate-pulse">Đang xử lý</span>';
            textStyle = 'text-white font-semibold';
        } else if (step === job.current_step && isWaitingForSubtitleLayout(job)) {
            statusIcon = '<span class="text-purple-300 font-bold animate-pulse">Cho ban chon</span>';
            textStyle = 'text-white font-semibold';
        }
        const li = document.createElement('div');
        li.className = `flex justify-between items-center text-xs py-1.5 border-b border-white/5 ${textStyle}`;
        li.innerHTML = `<span>${friendlyNames[step]}</span> ${statusIcon}`;
        list.appendChild(li);
    }
}

async function openDetailPanel(jobId) {
    selectedJobId = jobId;
    const job = jobsData.find(j => j.job_id === jobId) || await (await fetch(`/api/jobs/${jobId}`)).json();
    if (!job) return;

    document.getElementById('detail-job-id-badge').innerText = job.job_id;
    const detailTitle = document.getElementById('detail-job-title');
    if (detailTitle) {
        detailTitle.innerText = getJobDisplayTitle(job);
        detailTitle.title = job.input_path || job.job_id;
    }
    document.getElementById('detail-completed-section')?.classList.add('hidden');
    document.getElementById('subtitle-layout-section')?.classList.add('hidden');
    document.getElementById('detail-logs-section')?.classList.remove('hidden');
    updatePipelineSteps(job);
    renderOutputsList(job);

    const panel = document.getElementById('detail-panel');
    panel.classList.remove('hidden');
    setTimeout(() => panel.classList.remove('translate-x-full'), 50);

    const refreshDetailStatus = async () => {
        if (!selectedJobId) return;
        const freshJob = await (await fetch(`/api/jobs/${selectedJobId}`)).json();

        if (!isEditingSubtitleLayout) {
            updatePipelineSteps(freshJob);
            renderOutputsList(freshJob);
        }

        const logResp = await fetch(`/api/jobs/${selectedJobId}/logs`);
        const logData = await logResp.json();
        const consoleBox = document.getElementById('detail-console');
        if (consoleBox && !isEditingSubtitleLayout) {
            consoleBox.innerText = logData.logs || logData.content || 'Chưa có nhật ký hoạt động.';
            consoleBox.scrollTop = consoleBox.scrollHeight;
        }

        if (isWaitingForSubtitleLayout(freshJob)) {
            panel.classList.add('lg:w-[650px]');
            document.getElementById('subtitle-layout-section')?.classList.remove('hidden');
            setSubtitleEditorSubmitMode('initial');
            if (!isEditingSubtitleLayout) {
                setupSubtitleLayoutEditor(freshJob);
            }
        } else if (document.getElementById('subtitle-layout-section') && !document.getElementById('subtitle-layout-section').classList.contains('hidden')) {
            panel.classList.add('lg:w-[650px]');
        } else {
            panel.classList.add('lg:w-[650px]');
            document.getElementById('subtitle-layout-section')?.classList.add('hidden');
        }

        const activeStatuses = new Set(['queued', 'processing', 'rendering', 'running']);
        const rerunBtn = document.getElementById('btn-detail-rerun');
        if (rerunBtn) {
            if (!activeStatuses.has(freshJob.status) && freshJob.status !== 'created') {
                rerunBtn.classList.remove('hidden');
            } else {
                rerunBtn.classList.add('hidden');
            }
        }

        const deleteBtn = document.getElementById('btn-detail-delete');
        if (deleteBtn) {
            if (!activeStatuses.has(freshJob.status) && freshJob.status !== 'created') {
                deleteBtn.classList.remove('hidden');
            } else {
                deleteBtn.classList.add('hidden');
            }
        }

        const isFinished = !activeStatuses.has(freshJob.status) && freshJob.status !== 'created';
        if (isFinished) {
            clearInterval(refreshInterval);

            // Show config override & transcript editing controls
            document.getElementById('detail-completed-section')?.classList.remove('hidden');
            updateSubtitleLayoutSummary(freshJob);

            // Prefill configuration values from job config snapshot
            const snapshot = freshJob.config_snapshot || {};
            const detVoice = document.getElementById('detail-voice');
            if (detVoice && snapshot.voice) detVoice.value = snapshot.voice;
            const detRate = document.getElementById('detail-rate');
            if (detRate && snapshot.rate) detRate.value = snapshot.rate;
            const detPitch = document.getElementById('detail-pitch');
            if (detPitch && snapshot.pitch) detPitch.value = snapshot.pitch;
            const detBgm = document.getElementById('detail-bgm');
            if (detBgm) detBgm.value = snapshot.bgm || '';

            // Show outputs list only if completed
            const outputsWrap = document.getElementById('detail-outputs-list-wrap');
            if (outputsWrap) {
                if (freshJob.status === 'completed') {
                    outputsWrap.classList.remove('hidden');
                    loadAIcaption(selectedJobId);
                } else {
                    outputsWrap.classList.add('hidden');
                }
            }

            loadTranscript(selectedJobId);

            if (freshJob.status === 'failed') {
                showToast('Công việc đã kết thúc thất bại hoặc bị ngắt.', 'error');
            }
        }
    };

    if (refreshInterval) clearInterval(refreshInterval);
    await refreshDetailStatus();
    refreshInterval = setInterval(refreshDetailStatus, 3500);
}

async function toggleJobPublishedStatus(jobId) {
    try {
        const resp = await fetch(`/api/jobs/${jobId}/toggle-published`, { method: 'POST' });
        if (resp.ok) {
            const data = await resp.json();
            const job = jobsData.find(j => j.job_id === jobId);
            if (job) {
                job.is_published = data.is_published;
            }
            renderJobsList();
            showToast(data.is_published ? "Đã đánh dấu Đã đăng!" : "Đã chuyển về trạng thái Chờ đăng", "success");
        } else {
            showToast("Không thể thay đổi trạng thái đăng video", "error");
        }
    } catch (e) {
        showToast("Lỗi kết nối: " + e.message, "error");
    }
}

function addQuickLinkToQueue() {
    const input = document.getElementById('quick-youtube-url');
    if (!input) return;
    const url = input.value.trim();
    if (!url) {
        showToast('Vui lòng dán link video', 'error');
        return;
    }
    importSearchedVideo(url);
    input.value = '';
}

function renderJobsList() {
    const container = document.getElementById('jobs-container');
    if (!container) return;

    let filteredJobs = [...jobsData];
    if (currentFilterChannelId === 'default') {
        filteredJobs = filteredJobs.filter(job => {
            const channel = job.channel_id || job.channel_name;
            return !channel || channel === 'default';
        });
    } else if (currentFilterChannelId) {
        filteredJobs = filteredJobs.filter(job => {
            const channel = job.channel_id || job.channel_name;
            return channel === currentFilterChannelId;
        });
    }

    const query = (document.getElementById('dashboard-search')?.value || '').trim().toLowerCase();
    const dateFilter = document.getElementById('dashboard-date-filter')?.value || 'all';
    const statusFilter = document.getElementById('dashboard-status-filter')?.value || '';
    const sourceFilter = document.getElementById('dashboard-source-filter')?.value || '';
    const sortMode = document.getElementById('dashboard-sort')?.value || 'newest';

    filteredJobs = filteredJobs.filter(job => {
        if (query) {
            const blob = [
                job.job_id,
                job.source_url,
                job.source_video_id,
                job.video_id,
                job.url,
                job.input_path,
                job.platform,
                job.source_platform,
                job.platform_folder,
                job.caption,
                job.title,
                job.channel_name
            ].filter(Boolean).join(' ').toLowerCase();
            if (!blob.includes(query)) return false;
        }

        if (!matchesDashboardDate(job, dateFilter)) return false;

        if (statusFilter) {
            const normalized = normalizeDashboardStatus(job.status);
            if (statusFilter === 'published') {
                if (job.status !== 'completed' || !job.is_published) return false;
            } else if (statusFilter === 'unpublished') {
                if (job.status !== 'completed' || job.is_published) return false;
            } else if (statusFilter === 'queued') {
                if (!['created', 'queued'].includes(normalized)) return false;
            } else if (statusFilter === 'running') {
                if (!['running', 'processing', 'rendering'].includes(normalized)) return false;
            } else if (normalized !== statusFilter) {
                return false;
            }
        }

        if (sourceFilter) {
            const source = detectDashboardSource(job);
            if (source !== sourceFilter) return false;
        }

        return true;
    });

    filteredJobs.sort((a, b) => sortDashboardJobs(a, b, sortMode));

    if (filteredJobs.length === 0) {
        container.innerHTML = '<div class="col-span-full py-12 text-center text-slate-500 border border-dashed border-white/5 rounded-2xl">Không tìm thấy công việc nào phù hợp với bộ lọc.</div>';
        return;
    }

    // In-place updates when structure matches
    const currentDomIds = Array.from(container.children).map(c => c.getAttribute('data-job-id')).filter(Boolean);
    const newJobIds = filteredJobs.map(j => j.job_id);
    const isSameStructure = currentDomIds.length === newJobIds.length && currentDomIds.every((id, idx) => id === newJobIds[idx]);

    if (isSameStructure) {
        filteredJobs.forEach(job => {
            const card = container.querySelector(`[data-job-id="${job.job_id}"]`);
            if (!card) return;

            const totalSteps = Object.keys(job.steps || {}).length || 1;
            const completedSteps = Object.values(job.steps || {}).filter(s => s === 'completed').length;
            const pct = Number.isFinite(job.progress) ? job.progress : Math.round((completedSteps / totalSteps) * 100);

            const pctText = card.querySelector('.progress-pct');
            if (pctText) pctText.textContent = `${pct}% (${completedSteps}/${totalSteps})`;
            const pctBar = card.querySelector('.progress-bar');
            if (pctBar) pctBar.style.width = `${pct}%`;

            const badgeContainer = card.querySelector('.status-badge-container');
            if (badgeContainer) {
                const newBadgeHtml = statusBadgeHtml(job);
                if (badgeContainer.innerHTML !== newBadgeHtml) {
                    badgeContainer.innerHTML = newBadgeHtml;
                }
            }

            const thumbContainer = card.querySelector('.thumb-container');
            if (thumbContainer) {
                const activeStatuses = new Set(['queued', 'processing', 'rendering', 'running']);
                const newThumbHtml = job.status === 'completed'
                    ? `<video src="/api/jobs/${job.job_id}/video" class="w-full h-full object-cover" preload="metadata" muted playsinline></video>`
                    : activeStatuses.has(job.status)
                        ? '<div class="absolute inset-0 flex items-center justify-center bg-purple-500/10 text-purple-400"><svg class="w-5 h-5 animate-spin" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2.5" d="M4 4v5h.582m15.356 2A8.001 8.001 0 1121.21 12H16M4 8h5.183M12 4v4m0 0H8"></path></svg></div>'
                        : '<div class="absolute inset-0 flex items-center justify-center bg-slate-950 text-slate-500"><svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 10l4.553-2.276A1 1 0 0121 8.618v6.764a1 1 0 01-1.447.894L15 14M5 18h8a2 2 0 002-2V8a2 2 0 00-2-2H5a2 2 0 00-2 2v8a2 2 0 002 2z"></path></svg></div>';
                if (thumbContainer.innerHTML !== newThumbHtml) {
                    thumbContainer.innerHTML = newThumbHtml;
                }
            }

            const actionsContainer = card.querySelector('.actions-container');
            if (actionsContainer) {
                const activeStatuses = new Set(['queued', 'processing', 'rendering', 'running']);
                const actionButton = job.status === 'created'
                    ? `<button onclick="resumeJob('${job.job_id}')" class="hover:bg-emerald-500/10 text-emerald-400 text-xs font-semibold px-3 py-1.5 rounded-lg border border-emerald-500/20 hover:border-emerald-500/40 transition-all">Bắt đầu xử lý</button>`
                    : activeStatuses.has(job.status)
                        ? `<button onclick="cancelJob('${job.job_id}')" class="hover:bg-amber-500/10 text-amber-400 text-xs font-semibold px-3 py-1.5 rounded-lg border border-amber-500/20 hover:border-amber-500/40 transition-all">Ngắt</button>`
                        : `<button onclick="rerunJob('${job.job_id}')" class="hover:bg-purple-500/10 text-purple-400 text-xs font-semibold px-3 py-1.5 rounded-lg border border-purple-500/20 hover:border-purple-500/40 transition-all">Chạy lại</button>`;

                const channelLabel = job.channel_name || (globalChannels.find(c => c.id === job.channel_id) || {}).name || '';
                const channelDropdown = job.status === 'completed'
                    ? `<select onchange="publishJob('${job.job_id}', this.value); this.selectedIndex = 0;" class="appearance-none bg-slate-900 hover:bg-slate-800 text-slate-200 text-[10px] font-semibold py-1.5 pl-3 pr-8 rounded-lg cursor-pointer transition-all focus:outline-none border border-slate-700/60 hover:border-purple-500/50">
                            <option value="" disabled selected>${channelLabel ? 'Page: ' + channelLabel : 'Chuyển vào Page'}</option>
                            ${globalChannels.map(c => `<option value="${c.id}">${c.name}</option>`).join('')}
                            ${job.channel_id ? '<option value="default">Đầu ra mặc định</option>' : ''}
                        </select>`
                    : '';
                const publishToggleBtn = job.status === 'completed'
                    ? `<button onclick="toggleJobPublishedStatus('${job.job_id}')" class="text-[10px] font-bold px-2 py-1.5 rounded-lg border transition-all ${job.is_published ? 'bg-emerald-500/20 text-emerald-300 border-emerald-500/30' : 'bg-slate-900 text-slate-400 hover:text-slate-200 border-slate-700/60'}" title="Đánh dấu đã đăng lên Page">
                        ${job.is_published ? '✓ Đã đăng' : 'Chờ đăng'}
                       </button>`
                    : '';

                const newActionsHtml = `${publishToggleBtn}${channelDropdown}${actionButton}<button onclick="openDetailPanel('${job.job_id}')" class="bg-white/5 hover:bg-white/10 hover:text-white text-slate-300 text-xs font-semibold px-3 py-1.5 rounded-lg border border-white/5 transition-all">Chi tiết</button>`;

                const activeEl = document.activeElement;
                const isUserInteractingWithThisCard = activeEl && card.contains(activeEl) && activeEl.tagName === 'SELECT';

                if (actionsContainer.innerHTML !== newActionsHtml && !isUserInteractingWithThisCard) {
                    actionsContainer.innerHTML = newActionsHtml;
                }
            }
        });
        return;
    }

    container.innerHTML = '';

    filteredJobs.forEach(job => {
        const totalSteps = Object.keys(job.steps || {}).length || 1;
        const completedSteps = Object.values(job.steps || {}).filter(s => s === 'completed').length;
        const pct = Number.isFinite(job.progress) ? job.progress : Math.round((completedSteps / totalSteps) * 100);
        const createdTime = new Date(job.created_at).toLocaleString();
        const snapshot = job.config_snapshot || {};
        const platformLabel = snapshot.platform || job.platform_folder || 'Local';
        const channelLabel = job.channel_name || (globalChannels.find(c => c.id === job.channel_id) || {}).name || '';
        const title = (job.input_path || job.job_id).split(/[\\/]/).pop();
        const activeStatuses = new Set(['queued', 'processing', 'rendering', 'running']);
        const statusHtml = statusBadgeHtml(job);
        const thumb = job.status === 'completed'
            ? `<video src="/api/jobs/${job.job_id}/video" class="w-full h-full object-cover" preload="metadata" muted playsinline></video>`
            : activeStatuses.has(job.status)
                ? '<div class="absolute inset-0 flex items-center justify-center bg-purple-500/10 text-purple-400"><svg class="w-5 h-5 animate-spin" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2.5" d="M4 4v5h.582m15.356 2A8.001 8.001 0 1121.21 12H16M4 8h5.183M12 4v4m0 0H8"></path></svg></div>'
                : '<div class="absolute inset-0 flex items-center justify-center bg-slate-950 text-slate-500"><svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 10l4.553-2.276A1 1 0 0121 8.618v6.764a1 1 0 01-1.447.894L15 14M5 18h8a2 2 0 002-2V8a2 2 0 00-2-2H5a2 2 0 00-2 2v8a2 2 0 002 2z"></path></svg></div>';
        const actionButton = job.status === 'created'
            ? `<button onclick="resumeJob('${job.job_id}')" class="hover:bg-emerald-500/10 text-emerald-400 text-xs font-semibold px-3 py-1.5 rounded-lg border border-emerald-500/20 hover:border-emerald-500/40 transition-all">Bắt đầu xử lý</button>`
            : activeStatuses.has(job.status)
                ? `<button onclick="cancelJob('${job.job_id}')" class="hover:bg-amber-500/10 text-amber-400 text-xs font-semibold px-3 py-1.5 rounded-lg border border-amber-500/20 hover:border-amber-500/40 transition-all">Ngắt</button>`
                : `<button onclick="rerunJob('${job.job_id}')" class="hover:bg-purple-500/10 text-purple-400 text-xs font-semibold px-3 py-1.5 rounded-lg border border-purple-500/20 hover:border-purple-500/40 transition-all">Chạy lại</button>`;
        const channelDropdown = job.status === 'completed'
            ? `<select onchange="publishJob('${job.job_id}', this.value); this.selectedIndex = 0;" class="appearance-none bg-slate-900 hover:bg-slate-800 text-slate-200 text-[10px] font-semibold py-1.5 pl-3 pr-8 rounded-lg cursor-pointer transition-all focus:outline-none border border-slate-700/60 hover:border-purple-500/50">
                    <option value="" disabled selected>${channelLabel ? 'Page: ' + channelLabel : 'Chuyển vào Page'}</option>
                    ${globalChannels.map(c => `<option value="${c.id}">${c.name}</option>`).join('')}
                    ${job.channel_id ? '<option value="default">Đầu ra mặc định</option>' : ''}
                </select>`
            : '';
        const publishToggleBtn = job.status === 'completed'
            ? `<button onclick="toggleJobPublishedStatus('${job.job_id}')" class="text-[10px] font-bold px-2 py-1.5 rounded-lg border transition-all ${job.is_published ? 'bg-emerald-500/20 text-emerald-300 border-emerald-500/30' : 'bg-slate-900 text-slate-400 hover:text-slate-200 border-slate-700/60'}" title="Đánh dấu đã đăng lên Page">
                ${job.is_published ? '✓ Đã đăng' : 'Chờ đăng'}
               </button>`
            : '';
        const card = document.createElement('div');
        card.setAttribute('data-job-id', job.job_id);
        card.className = 'glass-card rounded-xl p-4 hover:border-white/15 transition-all flex flex-col gap-3.5 relative group';
        card.innerHTML = `
            <div class="flex gap-3 items-start min-w-0">
                <div class="thumb-container w-12 h-12 rounded-lg bg-slate-900 border border-white/5 flex-shrink-0 overflow-hidden flex items-center justify-center relative">${thumb}</div>
                <div class="flex-1 min-w-0 flex flex-col justify-between h-12">
                    <div class="flex justify-between items-start gap-2">
                        <div class="flex flex-col min-w-0">
                            <span class="text-[9px] font-mono text-purple-400 font-bold leading-none">${job.job_id}</span>
                            <h3 class="font-semibold text-white mt-1 text-xs truncate leading-tight" title="${escapeHtml(job.input_path || job.job_id)}">${escapeHtml(title)}</h3>
                        </div>
                        <div class="status-badge-container">${statusHtml}</div>
                    </div>
                </div>
            </div>
            <div class="flex flex-col gap-1">
                <div class="flex flex-wrap gap-1 text-[9px] text-slate-400"><span>${escapeHtml(platformLabel)}</span>${channelLabel ? `<span>- ${escapeHtml(channelLabel)}</span>` : ''}</div>
                <div class="flex justify-between text-[10px] text-slate-400"><span>Tiến độ</span><span class="progress-pct">${pct}% (${completedSteps}/${totalSteps})</span></div>
                <div class="w-full bg-slate-800 h-1.5 rounded-full overflow-hidden"><div class="progress-bar bg-gradient-to-r from-purple-500 to-rose-500 h-full transition-all duration-500" style="width: ${pct}%"></div></div>
            </div>
            <div class="flex flex-wrap items-center justify-between gap-2 mt-1 pt-3 border-t border-white/5">
                <span class="text-[10px] text-slate-400 font-medium">${createdTime}</span>
                <div class="actions-container flex flex-wrap items-center gap-2">${publishToggleBtn}${channelDropdown}${actionButton}<button onclick="openDetailPanel('${job.job_id}')" class="bg-white/5 hover:bg-white/10 hover:text-white text-slate-300 text-xs font-semibold px-3 py-1.5 rounded-lg border border-white/5 transition-all">Chi tiết</button></div>
            </div>`;
        container.appendChild(card);
    });
}

function updateDashboardFilters() {
    const dateFilter = document.getElementById('dashboard-date-filter')?.value || 'all';
    document.getElementById('dashboard-custom-date-row')?.classList.toggle('hidden', dateFilter !== 'custom');
    renderJobsList();
}

function resetDashboardFilters() {
    const setValue = (id, value) => {
        const el = document.getElementById(id);
        if (el) el.value = value;
    };
    setValue('dashboard-search', '');
    setValue('dashboard-date-filter', 'all');
    setValue('dashboard-filter-channel', '');
    setValue('dashboard-status-filter', '');
    setValue('dashboard-source-filter', '');
    setValue('dashboard-sort', 'newest');
    setValue('dashboard-date-from', '');
    setValue('dashboard-date-to', '');
    currentFilterChannelId = '';
    localStorage.setItem('currentFilterChannelId', '');
    updateDashboardFilters();
}

function parseDashboardDate(value) {
    const date = value ? new Date(value) : null;
    return date && !Number.isNaN(date.getTime()) ? date : null;
}

function matchesDashboardDate(job, filter) {
    if (!filter || filter === 'all') return true;
    const date = parseDashboardDate(job.created_at || job.timestamp || job.date);
    if (!date) return true;
    const now = new Date();
    const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
    if (filter === 'today') return date >= today;
    if (filter === '7d') return date >= new Date(now.getTime() - 7 * 24 * 60 * 60 * 1000);
    if (filter === '30d') return date >= new Date(now.getTime() - 30 * 24 * 60 * 60 * 1000);
    if (filter === 'custom') {
        const fromValue = document.getElementById('dashboard-date-from')?.value;
        const toValue = document.getElementById('dashboard-date-to')?.value;
        const from = fromValue ? new Date(`${fromValue}T00:00:00`) : null;
        const to = toValue ? new Date(`${toValue}T23:59:59`) : null;
        if (from && date < from) return false;
        if (to && date > to) return false;
    }
    return true;
}

function normalizeDashboardStatus(status) {
    const value = status || '';
    if (value === 'waiting_for_subtitle_layout' || value === 'awaiting_subtitle_layout') return 'running';
    return value;
}

function statusBadgeHtml(job) {
    const status = normalizeDashboardStatus(job.status);
    if (status === 'completed') return '<span class="text-[10px] px-2 py-0.5 bg-emerald-500/20 text-emerald-300 font-bold rounded-md border border-emerald-500/20">Hoàn thành</span>';
    if (status === 'failed') return '<span class="text-[10px] px-2 py-0.5 bg-rose-500/20 text-rose-300 font-bold rounded-md border border-rose-500/20">Lỗi</span>';
    if (status === 'cancelled') return '<span class="text-[10px] px-2 py-0.5 bg-slate-950 text-slate-400 font-bold rounded-md border border-white/5">Đã hủy</span>';
    if (status === 'queued') return '<span class="text-[10px] px-2 py-0.5 bg-slate-700/60 text-slate-200 font-bold rounded-md border border-white/5">Đang chờ</span>';
    if (status === 'running') return '<span class="text-[10px] px-2 py-0.5 bg-indigo-500/20 text-indigo-300 font-bold rounded-md animate-pulse border border-indigo-500/20">Đang xử lý</span>';
    if (status === 'created') return '<span class="text-[10px] px-2 py-0.5 bg-slate-800 text-slate-300 font-bold rounded-md">Đã tạo</span>';
    return `<span class="text-[10px] px-2 py-0.5 bg-slate-800 text-slate-300 font-bold rounded-md">${escapeHtml(status || 'created')}</span>`;
}

function detectDashboardSource(job) {
    const explicit = job.source_platform || job.platform || job.platform_folder || job.config_snapshot?.platform;
    if (explicit) {
        const normalized = String(explicit).toLowerCase();
        if (normalized.includes('douyin')) return 'Douyin';
        if (normalized.includes('bilibili')) return 'Bilibili';
        if (normalized.includes('xiaohongshu')) return 'Xiaohongshu';
        if (normalized.includes('upload') || normalized.includes('local')) return 'Upload local';
    }
    const text = [job.source_url, job.url, job.input_path].filter(Boolean).join(' ').toLowerCase();
    if (text.includes('douyin.com')) return 'Douyin';
    if (text.includes('bilibili.com') || text.includes('b23.tv')) return 'Bilibili';
    if (text.includes('xiaohongshu.com') || text.includes('xhslink.com')) return 'Xiaohongshu';
    return text.startsWith('http') ? '' : 'Upload local';
}

function sortDashboardJobs(a, b, mode) {
    const progressOf = (job) => {
        if (Number.isFinite(job.progress)) return job.progress;
        const steps = job.steps || {};
        const total = Math.max(Object.keys(steps).length, 1);
        return Math.round((Object.values(steps).filter(s => s === 'completed').length / total) * 100);
    };
    if (mode === 'oldest') return (parseDashboardDate(a.created_at)?.getTime() || 0) - (parseDashboardDate(b.created_at)?.getTime() || 0);
    if (mode === 'progress_desc') return progressOf(b) - progressOf(a);
    if (mode === 'progress_asc') return progressOf(a) - progressOf(b);
    if (mode === 'status') return String(a.status || '').localeCompare(String(b.status || ''));
    return (parseDashboardDate(b.created_at)?.getTime() || 0) - (parseDashboardDate(a.created_at)?.getTime() || 0);
}

function closeDetailPanel() {
    const panel = document.getElementById('detail-panel');
    panel.classList.add('lg:w-[650px]');
    panel.classList.add('translate-x-full');
    setTimeout(() => {
        panel.classList.add('hidden');
        selectedJobId = null;
        subtitleLayoutEditorJobId = null;
        subtitleLayoutEditorReady = false;
        isEditingSubtitleLayout = false;
        if (refreshInterval) {
            clearInterval(refreshInterval);
            refreshInterval = null;
        }
        const previewPlayer = document.getElementById('subtitle-preview-video');
        if (previewPlayer) previewPlayer.src = '';
    }, 300);
}

function renderOutputsList(job) {
    const container = document.getElementById('outputs-list-container');
    if (!container) return;
    container.innerHTML = '';

    const snapshot = job.config_snapshot || {};
    const selectedOutputs = snapshot.selected_outputs || [];

    if (selectedOutputs.length === 0) {
        container.innerHTML = '<div class="text-[10px] text-slate-500 text-center py-2">Chưa cấu hình output nào.</div>';
        return;
    }

    selectedOutputs.forEach(outType => {
        const outData = job.outputs?.[outType] || {
            output_type: outType,
            render_status: 'pending',
            upload_status: 'pending'
        };

        const friendlyOutNames = {
            "fb_reels": "Facebook Reels (9:16)",
            "yt_shorts": "YouTube Shorts (9:16)",
            "yt_video": "YouTube Video (16:9)"
        };

        const friendlyName = friendlyOutNames[outType] || outType;

        let statusBadge = '';
        if (outData.render_status === 'completed') {
            statusBadge = '<span class="text-[10px] bg-emerald-500/20 text-emerald-400 border border-emerald-500/10 px-2 py-0.5 rounded-lg font-bold">Hoàn thành</span>';
        } else if (outData.render_status === 'rendering') {
            statusBadge = '<span class="text-[10px] bg-purple-500/20 text-purple-400 border border-purple-500/10 px-2 py-0.5 rounded-lg font-bold animate-pulse">Đang Render...</span>';
        } else if (outData.render_status === 'failed') {
            statusBadge = '<span class="text-[10px] bg-rose-500/20 text-rose-400 border border-rose-500/10 px-2 py-0.5 rounded-lg font-bold">Thất bại</span>';
        } else {
            statusBadge = '<span class="text-[10px] bg-slate-800 text-slate-400 border border-slate-700/60 px-2 py-0.5 rounded-lg font-bold">Đang chờ</span>';
        }

        const div = document.createElement('div');
        div.className = "flex flex-col gap-2 p-3 bg-white/5 border border-white/5 rounded-xl text-xs";

        let buttonsHtml = '';

        // Manual crop is removed in favor of default blur background reframe

        if (outData.render_status === 'completed') {
            buttonsHtml += `
                <a href="/api/jobs/${job.job_id}/video?output_type=${outType}" target="_blank" class="bg-emerald-500/10 hover:bg-emerald-500/20 text-emerald-400 border border-emerald-500/20 text-[10px] px-2.5 py-1.5 rounded-lg font-semibold flex items-center gap-1 transition-all active:scale-[0.98] no-underline">
                    👁️ Xem Video
                </a>
                <button onclick="openOutputsFolder('${job.job_id}')" class="bg-white/5 hover:bg-white/10 text-slate-300 border border-white/5 text-[10px] px-2.5 py-1.5 rounded-lg font-semibold flex items-center gap-1 transition-all active:scale-[0.98]">
                    📁 Mở Thư Mục
                </button>
            `;
        }

        buttonsHtml += `
            <button onclick="renderSpecificOutput('${job.job_id}', '${outType}')" class="bg-white/5 hover:bg-white/10 text-slate-300 border border-white/5 text-[10px] px-2.5 py-1.5 rounded-lg font-semibold flex items-center gap-1 transition-all active:scale-[0.98] ml-auto">
                ⚡ Render Lại
            </button>
        `;

        // Output metadata for copy
        let metadataHtml = '';
        if (job.steps.metadata === 'completed') {
            if (outType === 'yt_shorts') {
                const title = snapshot.youtube_shorts_title || "Video dịch tự động #shorts";
                const desc = snapshot.youtube_shorts_description || "Video dịch & lồng tiếng bởi AutoTool Studio #shorts";
                metadataHtml = `
                    <div class="mt-2 flex flex-col gap-2 border-t border-white/5 pt-2.5">
                        <div class="flex items-center justify-between">
                            <span class="text-[10px] text-slate-400 font-semibold uppercase">Tiêu đề YouTube Shorts</span>
                            <button onclick="copyText(this, '${escapeHtml(title)}')" class="text-[9px] text-purple-400 font-bold hover:underline">Copy</button>
                        </div>
                        <div class="bg-slate-950 border border-slate-900 rounded p-1.5 font-mono text-[10px] text-slate-300">${escapeHtml(title)}</div>
                        
                        <div class="flex items-center justify-between">
                            <span class="text-[10px] text-slate-400 font-semibold uppercase">Mô tả Shorts</span>
                            <button onclick="copyText(this, '${escapeHtml(desc)}')" class="text-[9px] text-purple-400 font-bold hover:underline">Copy</button>
                        </div>
                        <div class="bg-slate-950 border border-slate-900 rounded p-1.5 font-mono text-[10px] text-slate-300 whitespace-pre-wrap">${escapeHtml(desc)}</div>
                    </div>
                `;
            } else if (outType === 'yt_video') {
                const title = snapshot.youtube_video_title || "Video dịch & lồng tiếng tự động bởi AutoTool Studio";
                const desc = snapshot.youtube_video_description || "Video dịch & lồng tiếng tự động từ tiếng Trung sang tiếng Việt bằng AutoTool.";
                metadataHtml = `
                    <div class="mt-2 flex flex-col gap-2 border-t border-white/5 pt-2.5">
                        <div class="flex items-center justify-between">
                            <span class="text-[10px] text-slate-400 font-semibold uppercase">Tiêu đề YouTube Video</span>
                            <button onclick="copyText(this, '${escapeHtml(title)}')" class="text-[9px] text-purple-400 font-bold hover:underline">Copy</button>
                        </div>
                        <div class="bg-slate-950 border border-slate-900 rounded p-1.5 font-mono text-[10px] text-slate-300">${escapeHtml(title)}</div>
                        
                        <div class="flex items-center justify-between">
                            <span class="text-[10px] text-slate-400 font-semibold uppercase">Mô tả YouTube Video</span>
                            <button onclick="copyText(this, '${escapeHtml(desc)}')" class="text-[9px] text-purple-400 font-bold hover:underline">Copy</button>
                        </div>
                        <div class="bg-slate-950 border border-slate-900 rounded p-1.5 font-mono text-[10px] text-slate-300 whitespace-pre-wrap">${escapeHtml(desc)}</div>
                    </div>
                `;
            } else if (outType === 'fb_reels') {
                const caption = snapshot.facebook_caption || "Video Việt hóa & lồng tiếng tự động bởi AutoTool";
                const hashtags = snapshot.facebook_hashtags || "#autotool #dichphim #reviewphim";
                metadataHtml = `
                    <div class="mt-2 flex flex-col gap-2 border-t border-white/5 pt-2.5">
                        <div class="flex items-center justify-between">
                            <span class="text-[10px] text-slate-400 font-semibold uppercase">Caption Reels</span>
                            <button onclick="copyText(this, '${escapeHtml(caption)} ${escapeHtml(hashtags)}')" class="text-[9px] text-purple-400 font-bold hover:underline">Copy</button>
                        </div>
                        <div class="bg-slate-950 border border-slate-900 rounded p-1.5 font-mono text-[10px] text-slate-300 whitespace-pre-wrap">${escapeHtml(caption)} ${escapeHtml(hashtags)}</div>
                    </div>
                `;
            }
        }

        div.innerHTML = `
            <div class="flex justify-between items-center">
                <span class="font-semibold text-slate-200">${friendlyName}</span>
                ${statusBadge}
            </div>
            <div class="flex gap-2 items-center">
                ${buttonsHtml}
            </div>
            ${metadataHtml}
        `;
        container.appendChild(div);
    });
}

function escapeHtml(text) {
    if (!text) return '';
    return text
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#039;")
        .replace(/\n/g, "\\n");
}

function copyText(btn, text) {
    navigator.clipboard.writeText(text.replace(/\\n/g, "\n")).then(() => {
        const originalText = btn.innerText;
        btn.innerText = "Copied!";
        setTimeout(() => {
            btn.innerText = originalText;
        }, 1500);
    });
}

let isDraggingCrop = false;
let dragStartLeft = 0;
let dragStartX = 0;
let activeCropJobId = null;
let activeCropOutputType = null;

function openCropEditor(jobId, outputType) {
    activeCropJobId = jobId;
    activeCropOutputType = outputType;

    const job = jobsData.find(j => j.job_id === jobId);
    if (!job) return;

    const snapshot = job.config_snapshot || {};
    const reframeMode = snapshot[`${outputType}_reframe_mode`] || 'blur_background';
    document.getElementById('crop-reframe-mode').value = reframeMode;
    toggleReframeMode(reframeMode);

    const video = document.getElementById('crop-video-player');
    video.src = `/api/jobs/${jobId}/preview-video`;
    video.play();

    const overlay = document.getElementById('crop-overlay-box');
    const shadeLeft = document.getElementById('crop-shade-left');
    const shadeRight = document.getElementById('crop-shade-right');

    // Load current crop coordinates if any
    const crop = snapshot[`${outputType}_crop`] || {
        crop_x_percent: 0.342,
        crop_y_percent: 0.0,
        crop_width_percent: 0.316,
        crop_height_percent: 1.0
    };

    const workspaceWidth = 640;
    const overlayWidth = 202.5; // 360 * 9 / 16

    const currentLeft = crop.crop_x_percent * workspaceWidth;
    overlay.style.left = `${currentLeft}px`;
    overlay.style.width = `${overlayWidth}px`;

    shadeLeft.style.width = `${currentLeft}px`;
    shadeRight.style.left = `${currentLeft + overlayWidth}px`;
    shadeRight.style.width = `${workspaceWidth - (currentLeft + overlayWidth)}px`;

    document.getElementById('crop-modal').classList.remove('hidden');

    // Drag setup
    overlay.onmousedown = (e) => {
        e.preventDefault();
        isDraggingCrop = true;
        dragStartX = e.clientX;
        dragStartLeft = parseFloat(overlay.style.left) || 0;

        document.onmousemove = (moveEvent) => {
            if (!isDraggingCrop) return;
            let deltaX = moveEvent.clientX - dragStartX;
            let newLeft = dragStartLeft + deltaX;

            // Bound check
            newLeft = Math.max(0, Math.min(workspaceWidth - overlayWidth, newLeft));
            overlay.style.left = `${newLeft}px`;

            shadeLeft.style.width = `${newLeft}px`;
            shadeRight.style.left = `${newLeft + overlayWidth}px`;
            shadeRight.style.width = `${workspaceWidth - (newLeft + overlayWidth)}px`;
        };

        document.onmouseup = () => {
            isDraggingCrop = false;
            document.onmousemove = null;
            document.onmouseup = null;
        };
    };
}

function closeCropModal() {
    document.getElementById('crop-modal').classList.add('hidden');
    const video = document.getElementById('crop-video-player');
    video.pause();
    video.src = '';
}

function resetCrop() {
    const workspaceWidth = 640;
    const overlayWidth = 202.5;
    const centerLeft = (workspaceWidth - overlayWidth) / 2;

    const overlay = document.getElementById('crop-overlay-box');
    const shadeLeft = document.getElementById('crop-shade-left');
    const shadeRight = document.getElementById('crop-shade-right');

    overlay.style.left = `${centerLeft}px`;
    shadeLeft.style.width = `${centerLeft}px`;
    shadeRight.style.left = `${centerLeft + overlayWidth}px`;
    shadeRight.style.width = `${workspaceWidth - (centerLeft + overlayWidth)}px`;
}

async function saveCrop() {
    const overlay = document.getElementById('crop-overlay-box');
    const left = parseFloat(overlay.style.left) || 0;

    const workspaceWidth = 640;
    const overlayWidth = 202.5;

    // Calculate percentages
    const cropX = left / workspaceWidth;
    const cropY = 0.0;
    const cropW = overlayWidth / workspaceWidth;
    const cropH = 1.0;

    const reframeMode = document.getElementById('crop-reframe-mode').value;

    await saveCropConfig(activeCropJobId, activeCropOutputType, reframeMode, cropX, cropY, cropW, cropH);
    closeCropModal();
}

function toggleReframeMode(val) {
    const overlay = document.getElementById('crop-overlay-box');
    const shadeLeft = document.getElementById('crop-shade-left');
    const shadeRight = document.getElementById('crop-shade-right');
    if (val === 'blur_background') {
        overlay.classList.add('hidden');
        shadeLeft.classList.add('hidden');
        shadeRight.classList.add('hidden');
    } else {
        overlay.classList.remove('hidden');
        shadeLeft.classList.remove('hidden');
        shadeRight.classList.remove('hidden');
    }
}

async function checkApiKeysOnStartup() {
    try {
        const response = await fetch('/api/config/key-check');
        if (response.ok) {
            const data = await response.json();
            if (!data.configured) {
                // Main key is empty: highlight config button and alert
                const btn = document.getElementById('btn-tab-config');
                if (btn) {
                    btn.classList.add('animate-pulse', 'border', 'border-purple-500', 'text-purple-300');
                }
                showToast("Cảnh báo: Chưa cấu hình Gemini API Key chính!", "error");
            }

            // Prefill inputs if they exist in DOM
            const key1 = document.getElementById('gemini-key-1');
            if (key1) {
                key1.value = data.gemini_api_key || '';
                for (let i = 2; i <= 10; i++) {
                    const el = document.getElementById(`gemini-key-${i}`);
                    if (el) el.value = data[`gemini_api_key_${i}`] || '';
                }
            }
            const exportPathEl = document.getElementById('system-export-path');
            if (exportPathEl) exportPathEl.value = data.default_export_path || '';
        }
    } catch (e) {
        console.error("Failed to check keys:", e);
    }
}

async function loadConfigTab() {
    try {
        const response = await fetch('/api/config/key-check');
        if (response.ok) {
            const data = await response.json();
            const key1 = document.getElementById('gemini-key-1');
            if (key1) {
                key1.value = data.gemini_api_key || '';
                for (let i = 2; i <= 10; i++) {
                    const el = document.getElementById(`gemini-key-${i}`);
                    if (el) el.value = data[`gemini_api_key_${i}`] || '';
                }
            }
            const exportPathEl = document.getElementById('system-export-path');
            if (exportPathEl) exportPathEl.value = data.default_export_path || '';

            checkKeysStatus();
        }
    } catch (e) {
        console.error("Failed to load config tab keys:", e);
    }
}

async function openConfigModal() {
    const modal = document.getElementById('config-modal');
    if (modal) {
        modal.classList.remove('hidden');
        await loadConfigTab();
    }
}

function closeConfigModal() {
    const modal = document.getElementById('config-modal');
    if (modal) {
        modal.classList.add('hidden');
    }
}

function openKeysModal() {
    openConfigModal();
}

async function checkKeysStatus() {
    for (let i = 1; i <= 10; i++) {
        const el = document.getElementById(`key-status-${i}`);
        if (el) {
            el.className = "text-[9px] font-bold text-indigo-400 float-right animate-pulse";
            el.innerText = "⏳ Đang kiểm tra...";
        }
    }

    try {
        const res = await fetch('/api/config/key-status');
        if (res.ok) {
            const data = await res.json();
            for (let i = 1; i <= 10; i++) {
                const status = data[`key_${i}`];
                const el = document.getElementById(`key-status-${i}`);
                if (el) {
                    el.className = "text-[9px] font-bold float-right";
                    el.classList.remove('animate-pulse');
                    if (status === 'hoat_dong') {
                        el.classList.add('text-emerald-400');
                        el.innerText = '🟢 Hoạt động';
                    } else if (status === 'het_quota') {
                        el.classList.add('text-amber-400');
                        el.innerText = '🟡 Hết quota (429)';
                    } else if (status === 'khong_hop_le') {
                        el.classList.add('text-rose-400');
                        el.innerText = '❌ Không hợp lệ';
                    } else if (status === 'chua_cau_hinh') {
                        el.classList.add('text-slate-500');
                        el.innerText = '⚪ Chưa nhập';
                    } else {
                        el.classList.add('text-rose-400');
                        el.innerText = status || '❌ Lỗi';
                    }
                }
            }
        }
    } catch (e) {
        console.error("Failed to check keys status:", e);
        for (let i = 1; i <= 10; i++) {
            const el = document.getElementById(`key-status-${i}`);
            if (el) {
                el.className = "text-[9px] font-bold text-rose-500 float-right";
                el.innerText = "❌ Lỗi kết nối";
            }
        }
    }
}

function closeKeysModal() {
    // No-op for compatibility
}

async function saveGeminiKeys() {
    const k1 = document.getElementById('gemini-key-1').value.trim();
    const payload = { key: k1 };

    for (let i = 2; i <= 10; i++) {
        const el = document.getElementById(`gemini-key-${i}`);
        payload[`key${i}`] = el ? el.value.trim() : '';
    }

    if (!k1) {
        showToast("Lỗi: Gemini API Key chính không được để trống!", "error");
        return;
    }

    const exportPathVal = document.getElementById('system-export-path')?.value.trim() || '';

    showToast("Đang lưu cấu hình...", "info");
    try {
        // Save export path
        await fetch('/api/config/save-export-path', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ default_export_path: exportPathVal })
        });
        const res = await fetch('/api/config/save-key', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        if (res.ok) {
            showToast("Đã lưu cấu hình xoay tua API Keys thành công!", "success");

            // Remove pulse highlight from button if fixed
            const btn = document.getElementById('btn-tab-config');
            if (btn) {
                btn.classList.remove('animate-pulse', 'border', 'border-purple-500', 'text-purple-300');
            }

            checkKeysStatus();
        } else {
            const err = await res.json();
            showToast(err.detail || "Không thể lưu API Keys", "error");
        }
    } catch (e) {
        showToast("Lỗi kết nối: " + e.message, "error");
    }
}

let isDraggingLogo = false;
let logoDragStartX = 0;
let logoDragStartY = 0;
let logoDragStartLeft = 0;
let logoDragStartTop = 0;

window.logoLayout = null; // Stores { x_percent, y_percent }

function openLogoPositionEditor() {
    const modal = document.getElementById('logo-position-modal');
    if (!modal) return;

    const container = document.getElementById('logo-workspace-container');
    const box = document.getElementById('logo-draggable-box');
    const video = document.getElementById('logo-position-video-player');

    // Set video background if any video is queued
    if (pendingVideoItems && pendingVideoItems.length > 0) {
        const item = pendingVideoItems[0];
        // If it's a local path, we can request preview
        if (item.url && !item.url.startsWith('http')) {
            video.src = `/api/videos/preview?path=${encodeURIComponent(item.url)}`;
            video.play().catch(e => console.log("Failed playing preview:", e));
        } else {
            video.src = '';
        }
    } else {
        video.src = '';
    }

    // Load pre-existing layout if any
    const layout = window.logoLayout || { x_percent: 0.4375, y_percent: 0.055 };

    const workspaceWidth = 640;
    const workspaceHeight = 360;
    const boxWidth = 80;
    const boxHeight = 45;

    const currentLeft = layout.x_percent * workspaceWidth;
    const currentTop = layout.y_percent * workspaceHeight;

    box.style.left = `${currentLeft}px`;
    box.style.top = `${currentTop}px`;

    document.getElementById('logo-pos-x-val').innerText = `${(layout.x_percent * 100).toFixed(1)}%`;
    document.getElementById('logo-pos-y-val').innerText = `${(layout.y_percent * 100).toFixed(1)}%`;

    modal.classList.remove('hidden');

    // Setup mouse dragging logic
    box.onmousedown = (e) => {
        e.preventDefault();
        isDraggingLogo = true;

        logoDragStartX = e.clientX;
        logoDragStartY = e.clientY;
        logoDragStartLeft = parseFloat(box.style.left) || 0;
        logoDragStartTop = parseFloat(box.style.top) || 0;

        document.onmousemove = (moveEvent) => {
            if (!isDraggingLogo) return;

            let deltaX = moveEvent.clientX - logoDragStartX;
            let deltaY = moveEvent.clientY - logoDragStartY;

            let newLeft = logoDragStartLeft + deltaX;
            let newTop = logoDragStartTop + deltaY;

            // Bounds check
            newLeft = Math.max(0, Math.min(workspaceWidth - boxWidth, newLeft));
            newTop = Math.max(0, Math.min(workspaceHeight - boxHeight, newTop));

            box.style.left = `${newLeft}px`;
            box.style.top = `${newTop}px`;

            // Update UI coordinates labels
            const xPct = newLeft / workspaceWidth;
            const yPct = newTop / workspaceHeight;
            document.getElementById('logo-pos-x-val').innerText = `${(xPct * 100).toFixed(1)}%`;
            document.getElementById('logo-pos-y-val').innerText = `${(yPct * 100).toFixed(1)}%`;
        };

        document.onmouseup = () => {
            isDraggingLogo = false;
            document.onmousemove = null;
            document.onmouseup = null;
        };
    };
}

function closeLogoPositionModal() {
    document.getElementById('logo-position-modal').classList.add('hidden');
    const video = document.getElementById('logo-position-video-player');
    video.pause();
    video.src = '';
}

function resetLogoPosition() {
    const workspaceWidth = 640;
    const workspaceHeight = 360;
    const boxWidth = 80;
    const boxHeight = 45;

    const centerLeft = (workspaceWidth - boxWidth) / 2;
    const topOffset = 20; // 5.5%

    const box = document.getElementById('logo-draggable-box');
    box.style.left = `${centerLeft}px`;
    box.style.top = `${topOffset}px`;

    document.getElementById('logo-pos-x-val').innerText = `${((centerLeft / workspaceWidth) * 100).toFixed(1)}%`;
    document.getElementById('logo-pos-y-val').innerText = `${((topOffset / workspaceHeight) * 100).toFixed(1)}%`;
}

function saveLogoPosition() {
    const box = document.getElementById('logo-draggable-box');
    const left = parseFloat(box.style.left) || 0;
    const top = parseFloat(box.style.top) || 0;

    const workspaceWidth = 640;
    const workspaceHeight = 360;

    const xPct = left / workspaceWidth;
    const yPct = top / workspaceHeight;

    window.logoLayout = {
        x_percent: parseFloat(xPct.toFixed(4)),
        y_percent: parseFloat(yPct.toFixed(4))
    };

    showToast("Đã lưu vị trí logo thành công!", "success");
    closeLogoPositionModal();
}



function onChangeSubtitleAssetOpacity(opacity) {
    const box = document.getElementById('subtitle-asset-box');
    if (!box) return;
    subtitleAssetBoxState.opacity = 1.0;
    box.style.opacity = 1.0;
}

let subtitleBlurBoxes = [];
let activeBlurBoxId = null;
let nextBlurBoxId = 1;

function addNewBlurMask() {
    const wrap = document.getElementById('subtitle-preview-wrap');
    if (!wrap) return;

    const newBox = {
        id: nextBlurBoxId++,
        x_percent: 0.40,
        y_percent: 0.15,
        width_percent: 0.20,
        height_percent: 0.08,
        opacity: 0.6
    };

    subtitleBlurBoxes.push(newBox);
    createBlurBoxElement(newBox);
    renderBlurMasksList();
    selectBlurMask(newBox.id);
}

function createBlurBoxElement(boxData) {
    const wrap = document.getElementById('subtitle-preview-wrap');
    if (!wrap) return;

    const box = document.createElement('div');
    box.id = `subtitle-blur-box-${boxData.id}`;
    box.className = 'subtitle-blur-box-instance absolute cursor-move border border-dashed border-indigo-400/80 bg-white/10 shadow-lg flex items-center justify-center text-center rounded select-none';
    box.style.left = `${boxData.x_percent * 100}%`;
    box.style.top = `${boxData.y_percent * 100}%`;
    box.style.width = `${boxData.width_percent * 100}%`;
    box.style.height = `${boxData.height_percent * 100}%`;
    box.style.zIndex = '10';

    const blurPx = boxData.opacity * 30;
    box.style.backdropFilter = `blur(${blurPx}px)`;
    box.style.webkitBackdropFilter = `blur(${blurPx}px)`;

    box.innerHTML = `
        <span class="text-[8px] font-bold text-indigo-200 uppercase pointer-events-none select-none">HỘP LÀM MỜ #${boxData.id}</span>
        <div id="subtitle-blur-resize-${boxData.id}" class="subtitle-blur-resize-handle absolute right-0 bottom-0 w-3 h-3 cursor-se-resize rounded-tl bg-indigo-500/95"></div>
    `;

    wrap.appendChild(box);

    let dragging = false;
    let startX = 0, startY = 0;
    let startLeft = 0, startTop = 0;

    box.addEventListener('pointerdown', (e) => {
        const resizeHandle = document.getElementById(`subtitle-blur-resize-${boxData.id}`);
        if (e.target === resizeHandle) return;

        e.preventDefault();
        e.stopPropagation();
        selectBlurMask(boxData.id);
        dragging = true;
        startX = e.clientX;
        startY = e.clientY;
        startLeft = parseFloat(box.style.left) || 0;
        startTop = parseFloat(box.style.top) || 0;

        const onMove = (mv) => {
            if (!dragging) return;
            const rect = wrap.getBoundingClientRect();
            let deltaX = mv.clientX - startX;
            let deltaY = mv.clientY - startY;

            let newLeftPx = (startLeft / 100) * rect.width + deltaX;
            let newTopPx = (startTop / 100) * rect.height + deltaY;

            newLeftPx = Math.max(0, Math.min(rect.width - box.offsetWidth, newLeftPx));
            newTopPx = Math.max(0, Math.min(rect.height - box.offsetHeight, newTopPx));

            boxData.x_percent = newLeftPx / rect.width;
            boxData.y_percent = newTopPx / rect.height;

            box.style.left = `${boxData.x_percent * 100}%`;
            box.style.top = `${boxData.y_percent * 100}%`;
        };

        const onUp = () => {
            dragging = false;
            document.removeEventListener('pointermove', onMove);
            document.removeEventListener('pointerup', onUp);
        };

        document.addEventListener('pointermove', onMove);
        document.addEventListener('pointerup', onUp);
    });

    const resizeHandle = document.getElementById(`subtitle-blur-resize-${boxData.id}`);
    if (resizeHandle) {
        let resizing = false;
        let startW = 0, startH = 0;

        resizeHandle.addEventListener('pointerdown', (e) => {
            e.preventDefault();
            e.stopPropagation();
            selectBlurMask(boxData.id);
            resizing = true;
            startX = e.clientX;
            startY = e.clientY;
            startW = parseFloat(box.style.width) || 20;
            startH = parseFloat(box.style.height) || 8;

            const onResizeMove = (mv) => {
                if (!resizing) return;
                const rect = wrap.getBoundingClientRect();
                let deltaX = mv.clientX - startX;
                let deltaY = mv.clientY - startY;

                let newWidthPx = (startW / 100) * rect.width + deltaX;
                let newHeightPx = (startH / 100) * rect.height + deltaY;

                let leftPx = parseFloat(box.style.left) / 100 * rect.width;
                let topPx = parseFloat(box.style.top) / 100 * rect.height;

                newWidthPx = Math.max(rect.width * 0.05, Math.min(rect.width - leftPx, newWidthPx));
                newHeightPx = Math.max(rect.height * 0.02, Math.min(rect.height - topPx, newHeightPx));

                boxData.width_percent = newWidthPx / rect.width;
                boxData.height_percent = newHeightPx / rect.height;

                box.style.width = `${boxData.width_percent * 100}%`;
                box.style.height = `${boxData.height_percent * 100}%`;
            };

            const onResizeUp = () => {
                resizing = false;
                document.removeEventListener('pointermove', onResizeMove);
                document.removeEventListener('pointerup', onResizeUp);
            };

            document.addEventListener('pointermove', onResizeMove);
            document.addEventListener('pointerup', onResizeUp);
        });
    }
}

function selectBlurMask(id) {
    activeBlurBoxId = id;

    document.querySelectorAll('.subtitle-blur-box-instance').forEach(el => {
        if (el.id === `subtitle-blur-box-${id}`) {
            el.classList.remove('border-dashed', 'border-indigo-400/80');
            el.classList.add('border-solid', 'border-indigo-500', 'ring-1', 'ring-indigo-500/50');
            const handle = el.querySelector('.subtitle-blur-resize-handle');
            if (handle) handle.classList.remove('hidden');
        } else {
            el.classList.remove('border-solid', 'border-indigo-500', 'ring-1', 'ring-indigo-500/50');
            el.classList.add('border-dashed', 'border-indigo-400/80');
            const handle = el.querySelector('.subtitle-blur-resize-handle');
            if (handle) handle.classList.add('hidden');
        }
    });

    const boxData = subtitleBlurBoxes.find(b => b.id === id);
    if (!boxData) return;

    const controls = document.getElementById('active-blur-controls');
    const title = document.getElementById('active-blur-title');
    const opacitySlider = document.getElementById('active-blur-opacity-slider');

    if (controls && title && opacitySlider) {
        controls.classList.remove('hidden');
        title.innerText = `Chỉnh sửa Hộp #${id}`;
        opacitySlider.value = boxData.opacity;
    }
    renderBlurMasksList();
}

function deleteActiveBlurMask() {
    if (activeBlurBoxId === null) return;
    deleteBlurMask(activeBlurBoxId);
}

function deleteBlurMask(id) {
    subtitleBlurBoxes = subtitleBlurBoxes.filter(b => b.id !== id);
    const el = document.getElementById(`subtitle-blur-box-${id}`);
    if (el) el.remove();

    if (activeBlurBoxId === id) {
        activeBlurBoxId = null;
        const controls = document.getElementById('active-blur-controls');
        if (controls) controls.classList.add('hidden');
    }

    renderBlurMasksList();
    if (subtitleBlurBoxes.length > 0 && activeBlurBoxId === null) {
        selectBlurMask(subtitleBlurBoxes[0].id);
    }
}

function onActiveBlurOpacityChange(opacity) {
    if (activeBlurBoxId === null) return;
    const boxData = subtitleBlurBoxes.find(b => b.id === activeBlurBoxId);
    if (!boxData) return;

    boxData.opacity = parseFloat(opacity);

    const el = document.getElementById(`subtitle-blur-box-${activeBlurBoxId}`);
    if (el) {
        const blurPx = boxData.opacity * 30;
        el.style.backdropFilter = `blur(${blurPx}px)`;
        el.style.webkitBackdropFilter = `blur(${blurPx}px)`;
    }
    renderBlurMasksList();
}

function renderBlurMasksList() {
    const container = document.getElementById('blur-masks-list');
    if (!container) return;

    if (subtitleBlurBoxes.length === 0) {
        container.innerHTML = '<span class="italic text-[10px] text-slate-500">Chưa có hộp làm mờ nào được thêm.</span>';
        return;
    }

    container.innerHTML = '';
    subtitleBlurBoxes.forEach(b => {
        const isSelected = b.id === activeBlurBoxId;
        const pill = document.createElement('div');
        pill.className = `flex items-center gap-1.5 px-2 py-0.5 rounded text-[10px] font-medium transition cursor-pointer select-none ${isSelected ? 'bg-indigo-600/30 border border-indigo-500 text-indigo-200' : 'bg-slate-800/80 border border-slate-700/60 text-slate-300 hover:bg-slate-800'}`;

        pill.innerHTML = `
            <span onclick="selectBlurMask(${b.id})">Hộp #${b.id} (Mờ: ${Math.round(b.opacity * 100)}%)</span>
            <button type="button" onclick="event.stopPropagation(); deleteBlurMask(${b.id})" class="text-slate-400 hover:text-rose-400 font-bold ml-0.5">×</button>
        `;

        container.appendChild(pill);
    });
}

async function rerunJob(jobId) {
    try {
        const resp = await fetch(`/api/jobs/${jobId}/rerun`, { method: 'POST' });
        if (resp.ok) {
            showToast("Đã gửi yêu cầu chạy lại công việc!", "success");
            await loadJobs();
        } else {
            const err = await resp.json();
            showToast(err.detail || "Không thể chạy lại công việc", "error");
        }
    } catch (e) {
        showToast("Lỗi kết nối: " + e.message, "error");
    }
}

async function rerunDetailJob() {
    if (!selectedJobId) return;
    const btn = document.getElementById('btn-detail-rerun');
    if (btn) {
        btn.disabled = true;
        btn.innerText = 'Đang gửi...';
    }
    try {
        const resp = await fetch(`/api/jobs/${selectedJobId}/rerun`, { method: 'POST' });
        if (resp.ok) {
            showToast("Đã gửi yêu cầu chạy lại công việc!", "success");
            closeDetailPanel();
            await loadJobs();
        } else {
            const err = await resp.json();
            showToast(err.detail || "Không thể chạy lại công việc", "error");
        }
    } catch (e) {
        showToast("Lỗi kết nối: " + e.message, "error");
    } finally {
        if (btn) {
            btn.disabled = false;
            btn.innerText = '🔄 Chạy lại';
        }
    }
}

// Pages management CRUD page helpers
async function initChannelsView() {
    // Populate the Logo dropdown
    const select = document.getElementById('chan-logo');
    if (select) {
        select.innerHTML = '<option value="">Không sử dụng</option>';
        try {
            const resp = await fetch('/api/assets/list');
            if (resp.ok) {
                const logos = await resp.json();
                logos.forEach(logo => {
                    const opt = document.createElement('option');
                    opt.value = logo;
                    opt.textContent = logo;
                    select.appendChild(opt);
                });
            }
        } catch (e) {
            console.error("Failed to load global assets list for Page logo:", e);
        }
    }
    // Render list cards
    renderChannelsListView();
}

function renderChannelsListView() {
    const listContainer = document.getElementById('modal-channel-list');
    if (!listContainer) return;

    listContainer.innerHTML = '';

    if (globalChannels.length === 0) {
        listContainer.innerHTML = '<div class="col-span-full py-12 text-center text-slate-500 border border-dashed border-white/5 rounded-2xl">Chưa có cấu hình Page nào. Nhập thông tin bên trái để tạo mới!</div>';
        return;
    }

    globalChannels.forEach(c => {
        const card = document.createElement('div');
        card.className = "glass-card rounded-2xl p-5 border border-white/5 hover:border-purple-500/30 transition-all duration-300 flex flex-col justify-between gap-4";
        card.innerHTML = `
            <div class="flex flex-col gap-2">
                <div class="flex items-center justify-between border-b border-white/5 pb-2">
                    <span class="font-outfit font-bold text-sm text-slate-200">📺 ${escapeHtml(c.name)}</span>
                    <div class="flex gap-2">
                        <button onclick="editChannel('${c.id}')" class="text-[10px] text-purple-400 font-semibold hover:underline">Sửa</button>
                        <button onclick="deleteChannelData('${c.id}')" class="text-[10px] text-rose-400 font-semibold hover:underline">Xóa</button>
                    </div>
                </div>
                <div class="flex flex-col gap-1 text-[10px] text-slate-400 font-mono">
                    <div class="truncate">📁 Thư mục: ${escapeHtml(c.path)}</div>
                    ${c.logo ? `<div class="truncate text-purple-400">🖼️ Logo: ${escapeHtml(c.logo)}</div>` : ''}
                </div>
            </div>
            <button onclick="openChannelLocalFolder('${c.id}')" class="w-full py-1.5 bg-white/5 hover:bg-purple-600/30 rounded-lg text-[10px] font-semibold text-slate-300 border border-white/5 transition-all flex items-center justify-center gap-1.5">
                📁 Mở thư mục Page
            </button>
        `;
        listContainer.appendChild(card);
    });
}

function editChannel(id) {
    const chan = globalChannels.find(c => c.id === id);
    if (!chan) return;

    document.getElementById('chan-modal-title').innerText = "Chỉnh Sửa Page";
    document.getElementById('edit-channel-id').value = chan.id;
    document.getElementById('chan-name').value = chan.name;
    document.getElementById('chan-path').value = chan.path;

    const logoSelect = document.getElementById('chan-logo');
    if (logoSelect) {
        logoSelect.value = chan.logo || '';
    }
}

function cancelChannelEdit() {
    document.getElementById('chan-modal-title').innerText = "Cấu Hình Page Mới";
    document.getElementById('edit-channel-id').value = "";
    document.getElementById('channel-form').reset();
}

async function saveChannel(event) {
    if (event) event.preventDefault();

    const id = document.getElementById('edit-channel-id').value;
    const name = document.getElementById('chan-name').value.trim();
    const path = document.getElementById('chan-path').value.trim();
    const logoSelect = document.getElementById('chan-logo');
    const logo = logoSelect ? logoSelect.value : '';

    const payload = {
        name, path, logo
    };

    try {
        let resp;
        if (id) {
            resp = await fetch(`/api/pages/${id}`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });
        } else {
            resp = await fetch('/api/pages', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });
        }

        if (resp.ok) {
            showToast("Lưu cấu hình Page thành công!", "success");
            cancelChannelEdit();
            await loadChannels();
            renderChannelsListView();
        } else {
            const err = await resp.json();
            showToast(err.detail || "Không thể lưu Page", "error");
        }
    } catch (e) {
        showToast("Lỗi kết nối máy chủ: " + e.message, "error");
    }
}

async function deleteChannelData(id) {
    const confirmed = confirm("Bạn có chắc chắn muốn xóa Page này? Cấu hình mặc định của Page sẽ bị loại bỏ.");
    if (!confirmed) return;

    try {
        const resp = await fetch(`/api/pages/${id}`, { method: 'DELETE' });
        if (resp.ok) {
            showToast("Đã xóa Page thành công!", "success");
            await loadChannels();
            renderChannelsListView();
        } else {
            const err = await resp.json();
            showToast(err.detail || "Không thể xóa Page", "error");
        }
    } catch (e) {
        showToast("Lỗi kết nối: " + e.message, "error");
    }
}

async function openChannelLocalFolder(id) {
    try {
        const resp = await fetch(`/api/pages/${id}/open`, { method: 'POST' });
        if (resp.ok) {
            showToast("Đang mở thư mục Page...", "success");
        } else {
            const err = await resp.json();
            showToast(err.detail || "Không thể mở thư mục", "error");
        }
    } catch (e) {
        showToast("Lỗi kết nối: " + e.message, "error");
    }
}

async function resumeJob(jobId) {
    showToast("Đang gửi yêu cầu tiếp tục dự án...", "info");
    try {
        const resp = await fetch(`/api/jobs/${jobId}/resume`, { method: 'POST' });
        if (resp.ok) {
            showToast("Đã gửi yêu cầu tiếp tục thành công!", "success");
            await loadJobs();
        } else {
            const err = await resp.json();
            showToast(err.detail || "Không thể tiếp tục dự án", "error");
        }
    } catch (e) {
        showToast("Lỗi kết nối: " + e.message, "error");
    }
}
