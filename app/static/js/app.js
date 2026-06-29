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
let currentFilterChannelId = localStorage.getItem('currentFilterChannelId') || 'default';

// SPA HTML Views Map
const VIEWS = {
    dashboard: 'views/dashboard.html',
    search: 'views/search.html',
    cookies: 'views/cookies.html'
};

// Initialize application on DOM ready
document.addEventListener('DOMContentLoaded', async () => {
    // Read initial tab from URL hash (defaults to dashboard)
    // Load configurations and output subfolders persistently once on startup
    await loadGlobalConfig();
    await loadBgmList();
    await loadChannels();

    // Read initial tab from URL hash (defaults to dashboard)
    const initialTab = window.location.hash.replace('#', '') || 'dashboard';
    await switchTab(initialTab);
    setupQueueDragNDrop();
    renderQueueList();
    
    // Setup sidebar tab and header tab drag actions
    setupSidebarTabDragNDrop();
    setupHeaderTabDragNDrop();
    
    // Poll jobs status every 4 seconds in background
    setInterval(async () => {
        if (typeof loadJobs === 'function' && currentTab === 'dashboard') {
            await loadJobs();
        }
    }, 4000);
});

// Tab Routing Switches (Loads views dynamically)
async function switchTab(tab) {
    currentTab = tab;
    window.location.hash = tab;
    
    // Toggle menu highlight styles
    const btnDashboard = document.getElementById('btn-tab-dashboard');
    const btnCookies = document.getElementById('btn-tab-cookies');
    const btnSearch = document.getElementById('btn-tab-search');
    
    if (btnDashboard) {
        btnDashboard.className = tab === 'dashboard' 
            ? "px-4 py-2 text-sm font-semibold rounded-lg bg-white/10 text-white transition-all" 
            : "px-4 py-2 text-sm font-semibold rounded-lg hover:bg-white/5 text-slate-300 hover:text-white transition-all";
    }
    if (btnCookies) {
        btnCookies.className = tab === 'cookies' 
            ? "px-4 py-2 text-sm font-semibold rounded-lg bg-white/10 text-white transition-all" 
            : "px-4 py-2 text-sm font-semibold rounded-lg hover:bg-white/5 text-slate-300 hover:text-white transition-all";
    }
    if (btnSearch) {
        btnSearch.className = tab === 'search' 
            ? "px-4 py-2 text-sm font-semibold rounded-lg bg-white/10 text-white transition-all" 
            : "px-4 py-2 text-sm font-semibold rounded-lg hover:bg-white/5 text-slate-300 hover:text-white transition-all";
    }

    // Toggle sidebar visibility - only show on dashboard page
    const sidebar = document.getElementById('sidebar-container');
    if (sidebar) {
        if (tab === 'dashboard') {
            sidebar.classList.remove('hidden');
        } else {
            sidebar.classList.add('hidden');
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
                await loadJobs();
                if (typeof populateDashboardFilterChannel === 'function') {
                    populateDashboardFilterChannel();
                }
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
        const createdTime = new Date(job.created_at).toLocaleString();
        const snapshot = job.config_snapshot || {};
        const platformLabel = snapshot.platform || job.platform_folder || '';
        const channelLabel = (globalChannels.find(c => c.id === snapshot.channel_id || c.id === job.channel_id) || {}).name || '';



        let deleteButton = '';
        if (job.status !== 'running') {
            deleteButton = `
                <button onclick="deleteJob('${job.job_id}')" class="hover:bg-rose-500/10 text-rose-400 text-xs font-semibold px-3 py-1.5 rounded-lg border border-rose-500/20 hover:border-rose-500/40 transition-all">
                    Xóa
                </button>
            `;
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
    document.getElementById('detail-job-title').innerText = job.input_path.split(/[\\/]/).pop();

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
            
            // Set video player src path
            document.getElementById('detail-video-player').src = `/api/jobs/${selectedJobId}/video`;
            
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
        document.getElementById('detail-video-player').src = '';
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
    try {
        const response = await fetch(`/api/jobs/${jobId}/transcript`);
        const data = await response.json();
        selectedSegments = data;
        
        const container = document.getElementById('transcript-container');
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
        document.getElementById('caption-textarea').value = data.content || '';
    } catch (err) {
        console.error("Failed to load caption:", err);
    }
}

// Copy AI captions to clipboard
function copyCaption() {
    const textarea = document.getElementById('caption-textarea');
    textarea.select();
    document.execCommand('copy');
    alert('Đã copy caption vào clipboard!');
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
    
    const newOpt = new Option('[ + Tạo Kênh Mới ]', '__new__');
    select.add(newOpt);
    
    if (curVal) select.value = curVal;
}

// Populate logo selects dynamically from global configuration
function populateAllLogoSelects() {
    const selects = ['logo', 'chan-logo', 'detail-logo'];
    selects.forEach(selectId => {
        const select = document.getElementById(selectId);
        if (select && globalConfig && globalConfig.logos) {
            const curVal = select.value;
            select.innerHTML = '<option value="">Không sử dụng Logo</option>';
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
        const response = await fetch('/api/channels');
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

// Modal Create Channel
function openCreateChannelModal() {
    console.log("openCreateChannelModal clicked!");
    const nameEl = document.getElementById('chan-new-name');
    const pathEl = document.getElementById('chan-new-path');
    const modalEl = document.getElementById('create-channel-modal');
    console.log("Create Modal Elements found:", !!nameEl, !!pathEl, !!modalEl);
    if (nameEl) nameEl.value = '';
    if (pathEl) pathEl.value = '';
    if (modalEl) {
        modalEl.classList.remove('hidden');
        console.log("Hidden removed, class is now:", modalEl.className);
    }
}
function closeCreateChannelModal() {
    console.log("closeCreateChannelModal clicked!");
    const modalEl = document.getElementById('create-channel-modal');
    if (modalEl) modalEl.classList.add('hidden');
}

// Modal Manage Channels
async function openManageChannelsModal() {
    console.log("openManageChannelsModal clicked!");
    await loadChannels();
    renderManageChannelsList();
    const modalEl = document.getElementById('manage-channels-modal');
    console.log("Manage Modal Element found:", !!modalEl);
    if (modalEl) {
        modalEl.classList.remove('hidden');
        console.log("Hidden removed, class is now:", modalEl.className);
    }
}
function closeManageChannelsModal() {
    console.log("closeManageChannelsModal clicked!");
    const modalEl = document.getElementById('manage-channels-modal');
    if (modalEl) modalEl.classList.add('hidden');
}

// Modal Edit Channel
function openEditChannelModal(id, name, path) {
    console.log("openEditChannelModal clicked!", id, name, path);
    const idEl = document.getElementById('chan-edit-id');
    const nameEl = document.getElementById('chan-edit-name');
    const pathEl = document.getElementById('chan-edit-path');
    const modalEl = document.getElementById('edit-channel-modal');
    console.log("Edit Modal Elements found:", !!idEl, !!nameEl, !!pathEl, !!modalEl);
    if (idEl) idEl.value = id;
    if (nameEl) nameEl.value = name;
    if (pathEl) pathEl.value = path;
    if (modalEl) {
        modalEl.classList.remove('hidden');
        console.log("Hidden removed, class is now:", modalEl.className);
    }
}
function closeEditChannelModal() {
    console.log("closeEditChannelModal clicked!");
    const modalEl = document.getElementById('edit-channel-modal');
    if (modalEl) modalEl.classList.add('hidden');
}



// CRUD operations
async function saveNewChannel() {
    const name = document.getElementById('chan-new-name').value.trim();
    const path = document.getElementById('chan-new-path').value.trim();
    if (!name || !path) {
        showToast("Vui lòng điền đủ Tên Kênh và Đường dẫn!", "warning");
        return;
    }
    
    try {
        const res = await fetch('/api/channels', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ name, path })
        });
        if (res.ok) {
            showToast("Đã lưu kênh output mới!", "success");
            closeCreateChannelModal();
            await loadChannels();
            if (!document.getElementById('manage-channels-modal').classList.contains('hidden')) {
                renderManageChannelsList();
            }
            if (currentTab === 'dashboard') {
                await loadJobs();
            }
        } else {
            const data = await res.json();
            showToast(data.detail || "Lỗi lưu kênh!", "error");
        }
    } catch (err) {
        showToast("Lỗi kết nối máy chủ!", "error");
    }
}

async function updateExistingChannel() {
    const id = document.getElementById('chan-edit-id').value;
    const name = document.getElementById('chan-edit-name').value.trim();
    const path = document.getElementById('chan-edit-path').value.trim();
    if (!name || !path) {
        showToast("Vui lòng điền đủ thông tin!", "warning");
        return;
    }
    
    try {
        const res = await fetch(`/api/channels/${id}`, {
            method: 'PUT',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ name, path })
        });
        if (res.ok) {
            showToast("Đã cập nhật kênh!", "success");
            closeEditChannelModal();
            await loadChannels();
            renderManageChannelsList();
            if (currentTab === 'dashboard') {
                await loadJobs();
            }
        } else {
            const data = await res.json();
            showToast(data.detail || "Lỗi cập nhật!", "error");
        }
    } catch (err) {
        showToast("Lỗi kết nối máy chủ!", "error");
    }
}

async function deleteExistingChannel(id) {
    const confirmed = await showConfirm("Bạn có chắc chắn muốn xóa kênh này?");
    if (!confirmed) return;
    
    try {
        const res = await fetch(`/api/channels/${id}`, { method: 'DELETE' });
        if (res.ok) {
            showToast("Đã xóa kênh!", "success");
            await loadChannels();
            renderManageChannelsList();
            if (currentTab === 'dashboard') {
                await loadJobs();
            }
        } else {
            showToast("Lỗi khi xóa kênh!", "error");
        }
    } catch (err) {
        showToast("Lỗi kết nối máy chủ!", "error");
    }
}

// Render the list of channels in the manage modal
function renderManageChannelsList() {
    const container = document.getElementById('manage-channels-list');
    if (!container) return;
    
    if (globalChannels.length === 0) {
        container.innerHTML = `<div class="text-center text-slate-500 py-6 text-xs font-semibold">Chưa cấu hình kênh nào</div>`;
        return;
    }
    
    container.innerHTML = globalChannels.map(chan => {
        if (!chan) return '';
        const name = chan.name || '';
        const path = chan.path || '';
        const nameEscaped = name.replace(/'/g, "\\'");
        const pathEscaped = path.replace(/\\/g, "\\\\").replace(/'/g, "\\'");
        
        return `
            <div class="flex items-center justify-between bg-slate-900 border border-white/5 p-3 rounded-xl gap-4">
                <div class="flex flex-col min-w-0">
                    <span class="font-semibold text-xs text-white truncate">${name}</span>
                    <span class="text-[10px] text-slate-400 truncate" title="${path}">${path}</span>
                </div>
                <div class="flex items-center gap-1.5 flex-shrink-0">
                    <button onclick="openEditChannelModal('${chan.id}', '${nameEscaped}', '${pathEscaped}')" class="text-[10px] font-bold bg-purple-650/20 text-purple-300 hover:bg-purple-600 hover:text-white px-2.5 py-1.5 rounded-lg border border-purple-500/10 transition-all">Sửa</button>
                    <button onclick="deleteExistingChannel('${chan.id}')" class="text-[10px] font-bold bg-rose-600/20 text-rose-300 hover:bg-rose-650 hover:text-white px-2.5 py-1.5 rounded-lg border border-rose-500/10 transition-all">Xóa</button>
                </div>
            </div>
        `;
    }).filter(html => html !== '').join('');
}

// Move/Publish job files to a selected channel directory
async function publishJob(jobId, channelId) {
    if (!channelId) return;
    
    try {
        const res = await fetch(`/api/jobs/${jobId}/publish`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
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
    return {
        tone: 'review_phim',
        voice: 'vi-VN-HoaiMyNeural',
        rate: '+0%',
        pitch: '+0Hz',
        bgm: '',
        logo: '',
        channel_id: '',
        platform_folder: '',
        subtitle_cover_mode: 'text_box_only',
        subtitle_bg_opacity: 0.42,
        subtitle_mask_padding_x: 20,
        subtitle_mask_padding_y: 12,
        ocr_sample_interval_sec: 0.75,
        ocr_crop_bottom_ratio: 0.45,
        tts_enabled: true,
        subtitles_enabled: true,
        mask: true
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
    } else if (['tts_enabled', 'subtitles_enabled', 'mask'].includes(key)) {
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
                <select onchange="updatePendingConfig('${entry.id}','tone',this.value)" class="bg-slate-900 border border-slate-800 rounded-lg p-2">${optionList(globalConfig.tones, cfg.tone)}</select>
                <select onchange="updatePendingConfig('${entry.id}','voice',this.value)" class="bg-slate-900 border border-slate-800 rounded-lg p-2">${optionList(globalConfig.voices, cfg.voice)}</select>
                <select onchange="updatePendingConfig('${entry.id}','rate',this.value)" class="bg-slate-900 border border-slate-800 rounded-lg p-2">${optionList(globalConfig.rates, cfg.rate)}</select>
                <select onchange="updatePendingConfig('${entry.id}','pitch',this.value)" class="bg-slate-900 border border-slate-800 rounded-lg p-2">${optionList(globalConfig.pitches, cfg.pitch)}</select>
                <select onchange="updatePendingConfig('${entry.id}','bgm',this.value)" class="bg-slate-900 border border-slate-800 rounded-lg p-2">${pendingBgmOptions(cfg.bgm)}</select>
                <select onchange="updatePendingConfig('${entry.id}','logo',this.value)" class="bg-slate-900 border border-slate-800 rounded-lg p-2">${pendingLogoOptions(cfg.logo)}</select>
                <select onchange="updatePendingConfig('${entry.id}','channel_id',this.value)" class="bg-slate-900 border border-slate-800 rounded-lg p-2">${pendingChannelOptions(cfg.channel_id)}</select>
                <select onchange="updatePendingConfig('${entry.id}','platform_folder',this.value)" class="bg-slate-900 border border-slate-800 rounded-lg p-2">
                    <option value="" ${!cfg.platform_folder ? 'selected' : ''}>Không chia</option><option value="TikTok" ${cfg.platform_folder === 'TikTok' ? 'selected' : ''}>TikTok</option><option value="YouTube" ${cfg.platform_folder === 'YouTube' ? 'selected' : ''}>YouTube</option><option value="Facebook" ${cfg.platform_folder === 'Facebook' ? 'selected' : ''}>Facebook</option><option value="Douyin" ${cfg.platform_folder === 'Douyin' ? 'selected' : ''}>Douyin</option>
                </select>
            </div>
            <div class="grid grid-cols-2 gap-2">
                <select onchange="updatePendingConfig('${entry.id}','subtitle_cover_mode',this.value)" class="bg-slate-900 border border-slate-800 rounded-lg p-2">
                    <option value="text_box_only" ${cfg.subtitle_cover_mode !== 'none' ? 'selected' : ''}>Text box only</option><option value="none" ${cfg.subtitle_cover_mode === 'none' ? 'selected' : ''}>None</option>
                </select>
                <input type="number" min="0" max="1" step="0.01" value="${cfg.subtitle_bg_opacity}" onchange="updatePendingConfig('${entry.id}','subtitle_bg_opacity',this.value)" class="bg-slate-900 border border-slate-800 rounded-lg p-2 text-slate-100">
            </div>
            <div class="flex items-center justify-between gap-2 text-[10px] text-slate-400">
                <label><input type="checkbox" ${cfg.tts_enabled ? 'checked' : ''} onchange="updatePendingConfig('${entry.id}','tts_enabled',this.checked)"> TTS</label>
                <label><input type="checkbox" ${cfg.subtitles_enabled ? 'checked' : ''} onchange="updatePendingConfig('${entry.id}','subtitles_enabled',this.checked)"> Subtitle</label>
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
const DEFAULT_SUBTITLE_LAYOUT = { x: 0.08, y: 0.72, width: 0.84, height: 0.11 };
let subtitleLayoutEditorReady = false;
let subtitleLayoutEditorListenersBound = false;
let subtitleLayoutEditorJobId = null;
let subtitleLayoutState = { ...DEFAULT_SUBTITLE_LAYOUT, background_opacity: 0.42, preset: 'middle' };
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
    box.style.left = `${(layout.x ?? DEFAULT_SUBTITLE_LAYOUT.x) * 100}%`;
    box.style.top = `${(layout.y ?? DEFAULT_SUBTITLE_LAYOUT.y) * 100}%`;
    box.style.width = `${(layout.width ?? DEFAULT_SUBTITLE_LAYOUT.width) * 100}%`;
    box.style.height = `${(layout.height ?? DEFAULT_SUBTITLE_LAYOUT.height) * 100}%`;
}

function saveSubtitleLayoutLocalState() {
    const opacity = parseFloat(document.getElementById('subtitle-layout-opacity')?.value || subtitleLayoutState.background_opacity || '0.42');
    subtitleLayoutState = {
        ...subtitleLayoutState,
        ...getSubtitleLayoutBoxPercent(),
        background_opacity: Number.isFinite(opacity) ? opacity : 0.42
    };
}

function updateSubtitleLayoutSummary(job) {
    const summary = document.getElementById('subtitle-layout-summary');
    if (!summary) return;
    const snapshot = job?.config_snapshot || {};
    const opacity = Math.round((snapshot.subtitle_bg_opacity ?? subtitleLayoutState.background_opacity ?? 0.42) * 100);
    const preset = snapshot.subtitle_preset || subtitleLayoutState.preset || 'middle';
    const presetLabel = { low: 'Thap', middle: 'Giua', high: 'Cao', custom: 'Custom' }[preset] || preset;
    summary.innerText = `Preset: ${presetLabel} | Opacity: ${opacity}%`;
}

function resetSubtitleLayoutBox() {
    subtitleLayoutState = { ...DEFAULT_SUBTITLE_LAYOUT, background_opacity: subtitleLayoutState.background_opacity ?? 0.42, preset: 'middle' };
    applySubtitleLayoutBox(DEFAULT_SUBTITLE_LAYOUT);
}

function setSubtitlePreset(preset) {
    const presets = {
        low: { x: 0.08, y: 0.78, width: 0.84, height: 0.10 },
        middle: { x: 0.08, y: 0.72, width: 0.84, height: 0.11 },
        high: { x: 0.08, y: 0.64, width: 0.84, height: 0.11 }
    };
    subtitleLayoutState = { ...subtitleLayoutState, ...(presets[preset] || DEFAULT_SUBTITLE_LAYOUT), preset };
    applySubtitleLayoutBox(subtitleLayoutState);
}

function previewSubtitleBackplateOpacity(value) {
    const box = document.getElementById('subtitle-layout-box');
    if (box) box.style.background = `rgba(0,0,0,${value})`;
    subtitleLayoutState.background_opacity = parseFloat(value) || subtitleLayoutState.background_opacity;
}

function setSubtitleEditorSubmitMode(mode) {
    subtitleLayoutSubmitMode = mode || 'initial';
    const btn = document.getElementById('btn-continue-render');
    if (!btn) return;
    btn.innerText = subtitleLayoutSubmitMode === 'rerender'
        ? 'Render Lai Voi Vi Tri Moi'
        : 'Tiep Tuc Render Video';
}

function escapeHtml(value) {
    return String(value)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#039;');
}

function updateSubtitlePreviewText() {
    const box = document.getElementById('subtitle-layout-box');
    const textWrap = box?.querySelector('div.pointer-events-none');
    if (!textWrap) return;
    const sample = (selectedSegments || []).find(seg => (seg.translated_text || seg.text || '').trim());
    const text = (sample?.translated_text || sample?.text || 'Ba nam truoc, khoi nghiep that bai, no').trim();
    textWrap.innerHTML = `${escapeHtml(text)}<br><span class="text-[10px] font-semibold text-white/80">[Keo tha de chinh vi tri phu de]</span>`;
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
        const saved = job.config_snapshot?.subtitle_layout || DEFAULT_SUBTITLE_LAYOUT;
        const savedOpacity = job.config_snapshot?.subtitle_bg_opacity ?? 0.42;
        const savedPreset = job.config_snapshot?.subtitle_preset || 'middle';
        subtitleLayoutState = { ...DEFAULT_SUBTITLE_LAYOUT, ...saved, background_opacity: savedOpacity, preset: savedPreset };
        if (!video.src || !video.src.includes(job.job_id)) {
            video.src = `/api/jobs/${job.job_id}/preview-video`;
        }
        const opacityInput = document.getElementById('subtitle-layout-opacity');
        if (opacityInput) opacityInput.value = subtitleLayoutState.background_opacity;
        applySubtitleLayoutBox(subtitleLayoutState);
        previewSubtitleBackplateOpacity(subtitleLayoutState.background_opacity);
    }
    updateSubtitlePreviewText();

    if (subtitleLayoutEditorListenersBound) return;
    subtitleLayoutEditorListenersBound = true;

    let mode = null;
    let start = null;
    const onPointerDown = (e, nextMode) => {
        isEditingSubtitleLayout = true;
        mode = nextMode;
        const rect = wrap.getBoundingClientRect();
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
            const nx = Math.max(0, Math.min(start.wrapW - start.w, start.x + dx));
            const ny = Math.max(0, Math.min(start.wrapH - start.h, start.y + dy));
            box.style.left = `${(nx / start.wrapW) * 100}%`;
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
}

async function continueRenderWithSubtitleLayout() {
    if (!selectedJobId) return;
    const btn = document.getElementById('btn-continue-render');
    saveSubtitleLayoutLocalState();
    const opacity = subtitleLayoutState.background_opacity;
    const layout = { ...subtitleLayoutState };
    if (btn) {
        btn.disabled = true;
        btn.innerText = 'Dang render...';
    }
    try {
        const endpoint = subtitleLayoutSubmitMode === 'rerender'
            ? `/api/jobs/${selectedJobId}/rerender-subtitle-layout`
            : `/api/jobs/${selectedJobId}/subtitle-layout`;
        const resp = await fetch(endpoint, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                subtitle_x_percent: layout.x,
                subtitle_y_percent: layout.y,
                subtitle_width_percent: layout.width,
                subtitle_height_percent: layout.height,
                subtitle_bg_opacity: opacity,
                background_opacity: opacity,
                preset: layout.preset || 'custom'
            })
        });
        if (!resp.ok) {
            const err = await resp.json();
            throw new Error(err.detail || 'Khong the tiep tuc render');
        }
        document.getElementById('subtitle-layout-section')?.classList.add('hidden');
        subtitleLayoutEditorJobId = null;
        subtitleLayoutEditorReady = false;
        isEditingSubtitleLayout = false;
        if (subtitleLayoutSubmitMode === 'rerender') {
            const player = document.getElementById('detail-video-player');
            if (player) player.src = `/api/jobs/${selectedJobId}/video?v=${Date.now()}`;
            const freshJob = await (await fetch(`/api/jobs/${selectedJobId}`)).json();
            updateSubtitleLayoutSummary(freshJob);
            showToast('Da render lai video voi vi tri phu de moi', 'success');
        } else {
            showToast('Da luu vi tri phu de, dang render video...', 'success');
        }
        await loadJobs();
    } catch (err) {
        showToast(err.message, 'error');
    } finally {
        if (btn) {
            btn.disabled = false;
            btn.innerText = subtitleLayoutSubmitMode === 'rerender'
                ? 'Render Lai Voi Vi Tri Moi'
                : 'Tiep Tuc Render Video';
        }
    }
}

async function openCompletedSubtitleLayoutEditor() {
    if (!selectedJobId) return;
    const job = await (await fetch(`/api/jobs/${selectedJobId}`)).json();
    document.getElementById('subtitle-layout-section')?.classList.remove('hidden');
    setSubtitleEditorSubmitMode('rerender');
    subtitleLayoutEditorJobId = null;
    setupSubtitleLayoutEditor(job);
    const section = document.getElementById('subtitle-layout-section');
    if (section) section.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

function updatePipelineSteps(job) {
    const list = document.getElementById('pipeline-steps-list');
    if (!list) return;
    list.innerHTML = '';
    const friendlyNames = {
        intake: '1. Tai / Nhap video',
        analyze: '2. Phan tich khung hinh',
        extract_audio: '3. Tach am thanh goc',
        transcribe: '4. Nhan dien giong noi (ASR)',
        translate: '5. Dich thuat phu de (AI)',
        tts: '6. Sinh giong noi moi (TTS)',
        mix_audio: '7. Tron am thanh & nhac nen',
        subtitle_layout: '8. Chon vi tri phu de',
        render: '9. Render video doc 9:16',
        metadata: '10. Tieu de & HashTags (AI)'
    };
    for (const step of Object.keys(friendlyNames)) {
        const status = job.steps?.[step] || 'pending';
        let statusIcon = '<span class="text-slate-600">Dang cho</span>';
        let textStyle = 'text-slate-400';
        if (status === 'completed') {
            statusIcon = '<span class="text-emerald-400 font-bold">Hoan tat</span>';
            textStyle = 'text-slate-300';
        } else if (status === 'failed') {
            statusIcon = '<span class="text-rose-400 font-bold">That bai</span>';
            textStyle = 'text-white font-semibold';
        } else if (step === job.current_step && job.status === 'running') {
            statusIcon = '<span class="text-purple-400 font-bold animate-pulse">Dang xu ly</span>';
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
    document.getElementById('detail-job-title').innerText = job.input_path.split(/[\\/]/).pop();
    document.getElementById('detail-completed-section')?.classList.add('hidden');
    document.getElementById('subtitle-layout-section')?.classList.add('hidden');
    document.getElementById('detail-logs-section')?.classList.remove('hidden');
    updatePipelineSteps(job);

    const panel = document.getElementById('detail-panel');
    panel.classList.remove('hidden');
    setTimeout(() => panel.classList.remove('translate-x-full'), 50);

    const refreshDetailStatus = async () => {
        if (!selectedJobId) return;
        const freshJob = await (await fetch(`/api/jobs/${selectedJobId}`)).json();

        if (!isEditingSubtitleLayout) {
            updatePipelineSteps(freshJob);
        }

        const logResp = await fetch(`/api/jobs/${selectedJobId}/logs`);
        const logData = await logResp.json();
        const consoleBox = document.getElementById('detail-console');
        if (consoleBox && !isEditingSubtitleLayout) {
            consoleBox.innerText = logData.logs || logData.content || 'Chua co nhat ky hoat dong.';
            consoleBox.scrollTop = consoleBox.scrollHeight;
        }

        if (isWaitingForSubtitleLayout(freshJob)) {
            document.getElementById('subtitle-layout-section')?.classList.remove('hidden');
            setSubtitleEditorSubmitMode('initial');
            if (!isEditingSubtitleLayout) {
                setupSubtitleLayoutEditor(freshJob);
            }
        } else {
            document.getElementById('subtitle-layout-section')?.classList.add('hidden');
        }

        if (freshJob.status === 'completed') {
            clearInterval(refreshInterval);
            document.getElementById('detail-completed-section')?.classList.remove('hidden');
            updateSubtitleLayoutSummary(freshJob);
            const player = document.getElementById('detail-video-player');
            if (player) player.src = `/api/jobs/${selectedJobId}/video`;
            loadTranscript(selectedJobId);
            loadAIcaption(selectedJobId);
        } else if (freshJob.status === 'failed') {
            clearInterval(refreshInterval);
            showToast('Job da ket thuc that bai hoac bi ngat.', 'error');
        }
    };

    if (refreshInterval) clearInterval(refreshInterval);
    await refreshDetailStatus();
    refreshInterval = setInterval(refreshDetailStatus, 3500);
}

function closeDetailPanel() {
    const panel = document.getElementById('detail-panel');
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
        const detailPlayer = document.getElementById('detail-video-player');
        if (detailPlayer) detailPlayer.src = '';
        const previewPlayer = document.getElementById('subtitle-preview-video');
        if (previewPlayer) previewPlayer.src = '';
    }, 300);
}


