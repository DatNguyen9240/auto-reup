// Main Application View Controller & UI Orchestration

// Global State Variables
let currentTab = 'dashboard';
let jobsData = [];
let selectedJobId = null;
let selectedSegments = [];
let refreshInterval = null;
let globalConfig = {};
let libraryVideos = [];
let videoQueue = [];
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

    // Poll logs and details status every 2 seconds
    if (refreshInterval) clearInterval(refreshInterval);
    refreshInterval = setInterval(async () => {
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
            document.getElementById('detail-logs-section').classList.add('hidden');
            document.getElementById('detail-completed-section').classList.remove('hidden');
            
            // Set video player src path
            document.getElementById('detail-video-player').src = `/api/jobs/${selectedJobId}/video`;
            
            loadTranscript(selectedJobId);
            loadAIcaption(selectedJobId);
        } else if (freshJob.status === 'failed') {
            clearInterval(refreshInterval);
            showToast("Tiến trình Job đã kết thúc thất bại hoặc bị ngắt.", "error");
        }
    }, 2000);
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


