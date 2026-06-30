// Modern Toast & Confirm modal injection
// Inject elements into body immediately since scripts run at body end
(function() {
    // Inject toast container
    const container = document.createElement('div');
    container.id = 'toast-container';
    container.className = 'fixed top-6 right-6 z-50 flex flex-col gap-3 pointer-events-none';
    document.body.appendChild(container);

    // Inject confirm modal
    const modal = document.createElement('div');
    modal.id = 'confirm-modal';
    modal.className = 'fixed inset-0 z-[100] flex items-center justify-center bg-slate-950/60 backdrop-blur-sm hidden transition-all duration-300 opacity-0';
    modal.innerHTML = `
        <div class="glass-card max-w-sm w-full mx-4 rounded-2xl border border-white/10 p-6 flex flex-col gap-4 shadow-2xl transform scale-95 transition-transform duration-300">
            <div class="flex items-center gap-3">
                <div class="w-10 h-10 rounded-xl bg-amber-500/10 border border-amber-500/20 flex items-center justify-center text-amber-400">
                    <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2.5" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"></path></svg>
                </div>
                <h3 class="font-outfit font-bold text-sm text-slate-100">Xác nhận</h3>
            </div>
            <p id="confirm-message" class="text-xs text-slate-300 font-sans leading-relaxed"></p>
            <div class="flex gap-2.5 justify-end mt-2">
                <button id="confirm-btn-cancel" class="bg-white/5 hover:bg-white/10 text-slate-300 px-4 py-2 rounded-xl text-xs font-semibold transition-colors">
                    Hủy
                </button>
                <button id="confirm-btn-ok" class="bg-purple-600 hover:bg-purple-500 text-white px-4 py-2 rounded-xl text-xs font-semibold transition-colors shadow-lg shadow-purple-500/10">
                    Đồng ý
                </button>
            </div>
        </div>
    `;
    document.body.appendChild(modal);

    // Inject API key modal
    const keyModal = document.createElement('div');
    keyModal.id = 'api-key-modal';
    keyModal.className = 'fixed inset-0 z-[100] flex items-center justify-center bg-slate-950/60 backdrop-blur-sm hidden transition-all duration-300 opacity-0';
    keyModal.innerHTML = `
        <div class="glass-card max-w-md w-full mx-4 rounded-2xl border border-white/10 p-6 flex flex-col gap-4 shadow-2xl transform scale-95 transition-transform duration-300 bg-slate-950/95">
            <div class="flex items-center gap-3">
                <div class="w-10 h-10 rounded-xl bg-purple-500/10 border border-purple-500/20 flex items-center justify-center text-purple-400">
                    <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 7a2 2 0 012 2m-2-2a2 2 0 00-2 2m2-2V5a2 2 0 10-4 0v2m4 0h3.586a1 1 0 01.707.293l2.414 2.414a1 1 0 01.293.707V14a2 2 0 01-2 2H8a2 2 0 01-2-2V9a2 2 0 012-2h1m10 8a3 3 0 01-3 3H7a3 3 0 01-3-3V7a3 3 0 013-3h3"></path></svg>
                </div>
                <h3 class="font-outfit font-bold text-sm text-slate-100">Cấu hình Gemini API Key</h3>
            </div>
            <p class="text-xs text-slate-300 font-sans leading-relaxed">
                Hệ thống hỗ trợ cấu hình xoay tua tối đa <strong>3 API Key</strong> để hạn chế việc cạn kiệt băng thông khi dịch phụ đề.
            </p>
            <div class="flex flex-col gap-3">
                <div class="flex flex-col gap-1.5">
                    <label class="text-[10px] text-slate-400 font-semibold uppercase tracking-wider">Gemini API Key 1 (Chính)</label>
                    <input id="api-key-input-1" type="password" placeholder="AIzaSy... (Bắt buộc)" 
                           class="w-full bg-slate-900/60 border border-white/10 hover:border-white/20 focus:border-purple-500/50 rounded-xl px-4 py-2.5 text-xs text-slate-100 outline-none transition-all placeholder:text-slate-600 font-mono">
                </div>
                <div class="flex flex-col gap-1.5">
                    <label class="text-[10px] text-slate-400 font-semibold uppercase tracking-wider">Gemini API Key 2 (Dự phòng)</label>
                    <input id="api-key-input-2" type="password" placeholder="Không bắt buộc" 
                           class="w-full bg-slate-900/60 border border-white/10 hover:border-white/20 focus:border-purple-500/50 rounded-xl px-4 py-2.5 text-xs text-slate-100 outline-none transition-all placeholder:text-slate-600 font-mono">
                </div>
                <div class="flex flex-col gap-1.5">
                    <label class="text-[10px] text-slate-400 font-semibold uppercase tracking-wider">Gemini API Key 3 (Dự phòng)</label>
                    <input id="api-key-input-3" type="password" placeholder="Không bắt buộc" 
                           class="w-full bg-slate-900/60 border border-white/10 hover:border-white/20 focus:border-purple-500/50 rounded-xl px-4 py-2.5 text-xs text-slate-100 outline-none transition-all placeholder:text-slate-600 font-mono">
                </div>
            </div>
            <div class="flex gap-2.5 justify-end mt-2">
                <button id="api-key-btn-close" class="bg-white/5 hover:bg-white/10 text-slate-300 px-4 py-2 rounded-xl text-xs font-semibold transition-colors">
                    Đóng
                </button>
                <button id="api-key-btn-save" class="bg-purple-600 hover:bg-purple-500 text-white px-4 py-2 rounded-xl text-xs font-semibold transition-colors shadow-lg shadow-purple-500/10">
                    Lưu cấu hình
                </button>
            </div>
        </div>
    `;
    document.body.appendChild(keyModal);
})();

function showToast(message, type = 'info') {
    const container = document.getElementById('toast-container');
    if (!container) return;
    
    const toast = document.createElement('div');
    toast.className = `pointer-events-auto flex items-center gap-3 px-4 py-3 rounded-xl border backdrop-blur-md shadow-2xl transition-all duration-300 transform translate-x-12 opacity-0 max-w-sm`;
    
    let bgClass = "bg-slate-900/95 border-slate-700/50 text-slate-100";
    let icon = `<svg class="w-4 h-4 text-blue-400 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2.5" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"></path></svg>`;
    
    if (type === 'success') {
        bgClass = "bg-emerald-950/90 border-emerald-500/30 text-emerald-100";
        icon = `<svg class="w-4 h-4 text-emerald-400 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2.5" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"></path></svg>`;
    } else if (type === 'error') {
        bgClass = "bg-rose-950/90 border-rose-500/30 text-rose-100";
        icon = `<svg class="w-4 h-4 text-rose-400 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2.5" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"></path></svg>`;
    } else if (type === 'warning') {
        bgClass = "bg-amber-950/90 border-amber-500/30 text-amber-100";
        icon = `<svg class="w-4 h-4 text-amber-400 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2.5" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"></path></svg>`;
    }
    
    toast.className += ` ${bgClass}`;
    toast.innerHTML = `
        <div class="flex-shrink-0">${icon}</div>
        <div class="text-[11px] font-medium font-sans leading-snug flex-1">${message}</div>
        <button class="ml-2 text-white/30 hover:text-white transition-colors" onclick="this.parentElement.remove()">
            <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2.5" d="M6 18L18 6M6 6l12 12"></path></svg>
        </button>
    `;
    
    container.appendChild(toast);
    
    setTimeout(() => {
        toast.classList.remove('translate-x-12', 'opacity-0');
        toast.classList.add('translate-x-0', 'opacity-100');
    }, 30);
    
    setTimeout(() => {
        toast.classList.remove('translate-x-0', 'opacity-100');
        toast.classList.add('translate-x-12', 'opacity-0');
        setTimeout(() => {
            toast.remove();
        }, 300);
    }, 4000);
}

function showConfirm(message) {
    return new Promise((resolve) => {
        const modal = document.getElementById('confirm-modal');
        const msgEl = document.getElementById('confirm-message');
        const btnOk = document.getElementById('confirm-btn-ok');
        const btnCancel = document.getElementById('confirm-btn-cancel');
        
        if (!modal || !msgEl || !btnOk || !btnCancel) {
            resolve(window.confirm(message));
            return;
        }
        
        msgEl.innerText = message;
        
        // Show modal
        modal.classList.remove('hidden');
        setTimeout(() => {
            modal.classList.remove('opacity-0');
            modal.querySelector('.glass-card').classList.remove('scale-95');
            modal.querySelector('.glass-card').classList.add('scale-100');
        }, 10);
        
        const cleanup = (value) => {
            modal.classList.add('opacity-0');
            modal.querySelector('.glass-card').classList.remove('scale-100');
            modal.querySelector('.glass-card').classList.add('scale-95');
            
            setTimeout(() => {
                modal.classList.add('hidden');
            }, 300);
            
            btnOk.onclick = null;
            btnCancel.onclick = null;
            resolve(value);
        };
        
        btnOk.onclick = () => cleanup(true);
        btnCancel.onclick = () => cleanup(false);
    });
}

window.alert = function(message) {
    let type = 'info';
    const text = message.toLowerCase();
    if (text.includes('lỗi') || text.includes('không thể') || text.includes('failed') || text.includes('error')) {
        type = 'error';
    } else if (text.includes('thành công') || text.includes('đã copy') || text.includes('hoàn tất') || text.includes('success')) {
        type = 'success';
    } else if (text.includes('chú ý') || text.includes('cảnh báo') || text.includes('warning')) {
        type = 'warning';
    }
    showToast(message, type);
};

// General helper to populate a select element with items
function populateSelect(selectId, items, defaultValue) {
    const select = document.getElementById(selectId);
    if (!select) return;
    select.innerHTML = '';
    items.forEach(item => {
        const opt = new Option(item.name, item.id);
        if (item.id === defaultValue) {
            opt.selected = true;
        }
        select.add(opt);
    });
}

async function showApiKeyModal() {
    const modal = document.getElementById('api-key-modal');
    const input1 = document.getElementById('api-key-input-1');
    const input2 = document.getElementById('api-key-input-2');
    const input3 = document.getElementById('api-key-input-3');
    const btnSave = document.getElementById('api-key-btn-save');
    const btnClose = document.getElementById('api-key-btn-close');
    
    if (!modal || !input1 || !input2 || !input3 || !btnSave || !btnClose) return;
    
    // Fetch and pre-fill existing API keys
    try {
        const res = await fetch('/api/config/key-check');
        if (res.ok) {
            const data = await res.json();
            input1.value = data.gemini_api_key || '';
            input2.value = data.gemini_api_key_2 || '';
            input3.value = data.gemini_api_key_3 || '';
        }
    } catch (e) {
        console.error("Failed to load existing API keys:", e);
    }

    modal.classList.remove('hidden');
    setTimeout(() => {
        modal.classList.remove('opacity-0');
        modal.querySelector('.glass-card').classList.remove('scale-95');
        modal.querySelector('.glass-card').classList.add('scale-100');
    }, 10);
    
    const hide = () => {
        modal.classList.add('opacity-0');
        modal.querySelector('.glass-card').classList.remove('scale-100');
        modal.querySelector('.glass-card').classList.add('scale-95');
        setTimeout(() => {
            modal.classList.add('hidden');
        }, 300);
    };
    
    btnClose.onclick = hide;
    
    btnSave.onclick = async () => {
        const key = input1.value.trim();
        const key2 = input2.value.trim();
        const key3 = input3.value.trim();
        
        if (!key) {
            showToast("Vui lòng nhập API Key chính (Key 1)!", "error");
            return;
        }
        btnSave.disabled = true;
        btnSave.innerText = "Đang lưu...";
        try {
            const response = await fetch('/api/config/save-key', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ key, key2, key3 })
            });
            if (response.ok) {
                const res = await response.json();
                showToast(res.message || "Lưu API Key thành công!", "success");
                hide();
                // Update key configure button class and text
                const keyBtn = document.getElementById('btn-api-key');
                if (keyBtn) {
                    keyBtn.className = "px-3 py-2 text-xs font-semibold rounded-lg bg-emerald-500/10 border border-emerald-500/20 text-emerald-300 hover:bg-emerald-500/20 transition-all flex items-center gap-1.5 ml-2";
                    keyBtn.innerHTML = "🔑 Key Đã Cấu Hình";
                    keyBtn.classList.remove('animate-pulse');
                }
            } else {
                const err = await response.json();
                showToast(err.detail || "Không thể lưu API Key", "error");
            }
        } catch (err) {
            showToast("Lỗi kết nối máy chủ: " + err.message, "error");
        } finally {
            btnSave.disabled = false;
            btnSave.innerText = "Lưu cấu hình";
        }
    };
}

async function checkApiKeyStatus() {
    try {
        const response = await fetch('/api/config/key-check');
        if (response.ok) {
            const data = await response.json();
            const keyBtn = document.getElementById('btn-api-key');
            if (data.configured) {
                if (keyBtn) {
                    keyBtn.className = "px-3 py-2 text-xs font-semibold rounded-lg bg-emerald-500/10 border border-emerald-500/20 text-emerald-300 hover:bg-emerald-500/20 transition-all flex items-center gap-1.5 ml-2";
                    keyBtn.innerHTML = "🔑 Key Đã Cấu Hình";
                }
            } else {
                if (keyBtn) {
                    keyBtn.className = "px-3 py-2 text-xs font-semibold rounded-lg bg-yellow-500/10 border border-yellow-500/20 text-yellow-300 hover:bg-yellow-500/20 transition-all flex items-center gap-1.5 ml-2 animate-pulse";
                    keyBtn.innerHTML = "🔑 Chưa Có Key";
                }
                showApiKeyModal();
            }
        }
    } catch (err) {
        console.error("Failed to check API key status:", err);
    }
}
