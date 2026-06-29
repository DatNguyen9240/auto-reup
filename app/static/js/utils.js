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
