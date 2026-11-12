
(function () {
const SVG_ICONS = {
    scan: '<svg class="w-4 h-4 inline-block -mt-0.5" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"/></svg>',
    scissors: '<svg class="w-4 h-4 inline-block -mt-0.5" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M14.121 14.121L19 19m-7-7l7-7m-7 7l-2.879 2.879a3 3 0 11-4.242-4.242 3 3 0 014.242 0L12 12zm0 0L9.121 9.121a3 3 0 10-4.242 4.242 3 3 0 004.242 0L12 12z"/></svg>',
    crop: '<svg class="w-4 h-4 inline-block -mt-0.5" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M6 2v14a2 2 0 002 2h14M18 22V8a2 2 0 00-2-2H2"/></svg>',
    trash: '<svg class="w-3.5 h-3.5 inline-block -mt-0.5" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"/></svg>',
    save: '<svg class="w-3.5 h-3.5 inline-block -mt-0.5" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M8 7H5a2 2 0 00-2 2v9a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-3m-1 4l-3 3m0 0l-3-3m3 3V4"/></svg>',
    calendar: '<svg class="w-4 h-4 inline-block -mt-0.5" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z"/></svg>',
    clock: '<svg class="w-3.5 h-3.5 inline-block -mt-0.5" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z"/></svg>',
    eye: '<svg class="w-3.5 h-3.5 inline-block -mt-0.5" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"/><path stroke-linecap="round" stroke-linejoin="round" d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z"/></svg>',
    play: '<svg class="w-3.5 h-3.5 inline-block -mt-0.5" fill="currentColor" viewBox="0 0 24 24"><path d="M8 5v14l11-7z"/></svg>',
    settings: '<svg class="w-3.5 h-3.5 inline-block -mt-0.5" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z"/><path stroke-linecap="round" stroke-linejoin="round" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"/></svg>',
    video: '<svg class="w-3.5 h-3.5 inline-block -mt-0.5" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M15 10l4.553-2.276A1 1 0 0121 8.618v6.764a1 1 0 01-1.447.894L15 14M5 18h8a2 2 0 002-2V8a2 2 0 00-2-2H5a2 2 0 00-2 2v8a2 2 0 002 2z"/></svg>',
    check: '<svg class="w-3.5 h-3.5 inline-block -mt-0.5" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M5 13l4 4L19 7"/></svg>',
    camera: '<svg class="w-3.5 h-3.5 inline-block -mt-0.5" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M3 9a2 2 0 012-2h.93a2 2 0 001.664-.89l.812-1.22A2 2 0 0110.07 4h3.86a2 2 0 011.664.89l.812 1.22A2 2 0 0018.07 7H19a2 2 0 012 2v9a2 2 0 01-2 2H5a2 2 0 01-2-2V9z"/><path stroke-linecap="round" stroke-linejoin="round" d="M15 13a3 3 0 11-6 0 3 3 0 016 0z"/></svg>',
    sparkles: '<svg class="w-3.5 h-3.5 inline-block -mt-0.5" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M5 3v4M3 5h4M6 17v4m-2-2h4m5-16l2.286 6.857L21 12l-5.714 2.143L13 21l-2.286-6.857L5 12l5.714-2.143L13 3z"/></svg>',
    users: '<svg class="w-3.5 h-3.5 inline-block -mt-0.5" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M12 4.354a4 4 0 110 5.292M15 21H3v-1a6 6 0 0112 0v1zm0 0h6v-1a6 6 0 00-9-5.197M13 7a4 4 0 11-8 0 4 4 0 018 0z"/></svg>',
    messageSquare: '<svg class="w-3.5 h-3.5 inline-block -mt-0.5" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M8 10h.01M12 10h.01M16 10h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z"/></svg>',
    cpu: '<svg class="w-3.5 h-3.5 inline-block -mt-0.5" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M9 3v2m6-2v2M9 19v2m6-2v2M3 9h2m-2 6h2m14-6h2m-2 6h2M7 19h10a2 2 0 002-2V7a2 2 0 00-2-2H7a2 2 0 00-2 2v10a2 2 0 002 2zM9 9h6v6H9V9z"/></svg>'
};


// ==========================================
// CLIENT-SIDE REACTIVE SPA ENGINE FOR TAURI & WEB
// ==========================================

const BACKEND_BASE = 'http://127.0.0.1:5000';

function getBackendUrl(path) {
    if (!path) return '';
    if (path.startsWith('http://') || path.startsWith('https://')) return path;
    const cleanPath = path.startsWith('/') ? path : '/' + path;
    return BACKEND_BASE + cleanPath;
}

function getTauriInvoke() {
    if (typeof window !== 'undefined') {
        // Auf http://127.0.0.1:5000 blockiert Tauri v2 ACL Standard-IPC ohne Remote-Capability;
        // direkte Same-Origin REST-Fetches auf Flask sind dort ohnehin nativ verfügbar.
        const proto = window.location?.protocol || '';
        const host = window.location?.hostname || '';
        if (proto === 'http:' && (host === '127.0.0.1' || host === 'localhost')) {
            return null;
        }
        if (window.__TAURI__?.core?.invoke) return window.__TAURI__.core.invoke.bind(window.__TAURI__.core);
        if (window.__TAURI__?.invoke) return window.__TAURI__.invoke.bind(window.__TAURI__);
        if (window.__TAURI_INTERNALS__?.invoke) return window.__TAURI_INTERNALS__.invoke.bind(window.__TAURI_INTERNALS__);
    }
    return null;
}

async function apiFetch(url, options = {}) {
    const isFormBody = typeof FormData !== 'undefined' && (options.body instanceof FormData || options.body instanceof URLSearchParams);
    const invoke = isFormBody ? null : getTauriInvoke();
    if (invoke) {
        try {
            const bodyStr = options.body ? (typeof options.body === 'string' ? options.body : JSON.stringify(options.body)) : null;
            const resText = await invoke('api_proxy', {
                endpoint: url,
                method: options.method || 'GET',
                body: bodyStr
            });
            return {
                ok: true,
                status: 200,
                json: async () => JSON.parse(resText),
                text: async () => resText
            };
        } catch (e) {
            console.warn('Tauri api_proxy failed, falling back to direct fetch:', e);
        }
    }
    return fetch(getBackendUrl(url), options);
}

// Cam filters catalogue
const CAM_FILTERS = {'none': 'Kein Filter (Original Facecam)', 'triangle': '3D Dreimacs Pyramide (Prismen-Kopf)', 'inv_triangle': '3D Trichter-Kopf (Megastirn, spitzes Kinn)', 'diamond': '3D Diamant-Kopf (Kristall-Facette)', 'cube': '3D Block-Kopf (Voxel / Steve)', 'gigachad': '3D Gigachad (Breiter Meme-Kiefer)', 'alien': '3D Megamind / Alien (Riesen-Kuppelkopf)', 'hamster': '3D Hamsterbacken (Prall aufgeblasen)', 'pinocchio': '3D Pinocchio (Lange Nase)', 'big_eyes': '3D Glubschaugen (Anime / Manga)', 'tiny_face': '3D Schrumpf-Gesicht (Charlie Kirk Meme)', 'big_mouth': '3D Riesenmund (Scream / Opernsänger)', 'hourglass': '3D Sanduhr (Wespentaille im Gesicht)', 'fisheye': '3D Glaskugel-Bulge (Linsen-Zoom)', 'swirl': '3D Strudel / Wirbel (Vortex-Twist)', 'wave': '3D Wackelpudding (Wobble-Welle)', 'mirror_left': 'Doppel-Links (Alien-Symmetrie)', 'mirror_right': 'Doppel-Rechts (Alien-Symmetrie)', 'stretch_vert': 'Bleistift-Kopf (Langgezogen)', 'squish_wide': 'Wide Meme (Pfannkuchen-Kopf)'};

// Helper: Escape HTML
function escapeHtml(str) {
    if (!str) return '';
    return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

// Helper: Escape JS string literal
function escapeJs(str) {
    if (!str) return '';
    return String(str).replace(/\\/g, '\\\\').replace(/'/g, "\\'").replace(/"/g, '\\"');
}

// Universal backend invoker (supports Tauri invoke and fallback REST API)
async function callBackend(command, args = {}) {
    const invoke = getTauriInvoke();
    if (invoke) {
        try {
            return await invoke(command, args);
        } catch (e) {
            console.warn(`Tauri invoke ${command} error, falling back to REST:`, e);
        }
    }
    const res = await apiFetch('/api/' + command, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(args)
    });
    return await res.json();
}

// Global state cache
let gDashboardData = null;

// Initial load & periodic refresh
async function refreshDashboard(forceRender = false) {
    try {
        gLastDashboardRefresh = Date.now();
        let data = null;
        const invoke = getTauriInvoke();
        if (invoke) {
            try {
                data = await invoke('get_dashboard_data');
            } catch (invokeErr) {
                console.warn('Tauri invoke get_dashboard_data failed, trying REST fallback:', invokeErr);
            }
        }
        if (!data) {
            const res = await apiFetch('/api/dashboard');
            data = await res.json();
        }
        if (data) {
            gDashboardData = data;
            renderDashboard(data, forceRender);
        }
    } catch (err) {
        console.error('Failed to refresh dashboard data:', err);
    }
}

function renderDashboard(data, forceRender = false) {
    // 1. KPI Counts
    if (data.counts) {
        const elH = document.getElementById('kpi-harvested');
        if (elH) elH.innerText = data.counts.harvested;
        const elR = document.getElementById('kpi-ready');
        if (elR) elR.innerText = data.counts.ready;
        const elS = document.getElementById('kpi-scheduled');
        if (elS) elS.innerText = data.counts.scheduled;
        const elP = document.getElementById('kpi-published');
        if (elP) elP.innerText = data.counts.published;

        const thH = document.getElementById('tab-count-harvested');
        if (thH) thH.innerText = data.counts.harvested;
        const thR = document.getElementById('tab-count-ready');
        if (thR) thR.innerText = data.counts.ready;
        const thS = document.getElementById('tab-count-scheduled');
        if (thS) thS.innerText = data.counts.scheduled;

        const qh = document.getElementById('queue-header-count');
        if (qh) qh.innerText = data.counts.harvested;
        const sh = document.getElementById('studio-header-count');
        if (sh) sh.innerText = data.counts.ready;
    }

    // 2. Streamer header count
    if (data.streamers) {
        cachedStreamers = data.streamers;
        const sh = document.getElementById('header-streamer-count');
        if (sh) sh.innerText = data.streamers.length;
    }

    // 3. Account Badges
    if (data.account_status) {
        const yt = document.getElementById('kpi-yt-status');
        if (yt) {
            yt.className = data.account_status.youtube_connected ? 'text-sm font-bold text-emerald-400' : 'text-sm font-bold text-slate-500';
            yt.innerText = 'YT: ' + (data.account_status.youtube_connected ? '✓' : '✗');
        }
        const tt = document.getElementById('kpi-tt-status');
        if (tt) {
            tt.className = data.account_status.tiktok_connected ? 'text-sm font-bold text-emerald-400' : 'text-sm font-bold text-slate-500';
            tt.innerText = 'TikTok: ' + (data.account_status.tiktok_connected ? '✓' : '✗');
        }
    }

    // 4. Render Individual Views
    renderQueue(data.queue_clips, data.older_queue_count);
    renderStudio(data.ready_clips, data.streamer_counts, forceRender);
    renderPlanner(data.scheduled_clips);
    renderPublished(data.published_clips);
    renderStreamers(data.streamers);
}

// ----------------------------------------
// 1. WARTESCHLANGE (QUEUE)
// ----------------------------------------
const DEFAULT_TWITCH_AVATAR = 'https://static-cdn.jtvnw.net/user-default-pictures-uv/cdd517fe-def4-11e9-948e-784f43822e80-profile_image-300x300.png';
let selectedQueueStreamers = new Set();
let cachedQueueClips = [];
let cachedQueueOlderCount = 0;
let cachedStreamers = [];

function toggleQueueStreamerFilter(streamerKey) {
    const key = String(streamerKey || '').trim().toLowerCase();
    if (!key) return;
    if (selectedQueueStreamers.has(key)) {
        selectedQueueStreamers.delete(key);
    } else {
        selectedQueueStreamers.add(key);
    }
    renderQueue(cachedQueueClips, cachedQueueOlderCount);
}

function clearQueueStreamerFilter() {
    selectedQueueStreamers.clear();
    renderQueue(cachedQueueClips, cachedQueueOlderCount);
}

function buildStreamerCountsMap(clips) {
    const counts = new Map();
    (clips || []).forEach(c => {
        const rawName = String(c.streamer || '').trim();
        if (!rawName) return;
        const key = rawName.toLowerCase();
        const existing = counts.get(key);
        if (existing) {
            existing.count += 1;
        } else {
            counts.set(key, { name: rawName, count: 1 });
        }
    });
    return counts;
}

function renderStreamerAvatarFilterBar({ barEl, countsMap, totalCount, selectedSet, onToggleFnName, onClearFnName }) {
    if (!barEl) return;

    if (!countsMap || countsMap.size === 0 || !totalCount) {
        selectedSet.clear();
        barEl.classList.add('hidden');
        barEl.innerHTML = '';
        return;
    }

    const streamerMeta = new Map();
    (cachedStreamers || []).forEach(s => {
        if (s && s.name) {
            streamerMeta.set(String(s.name).toLowerCase(), s);
        }
    });

    for (const sel of Array.from(selectedSet)) {
        if (!countsMap.has(sel)) {
            selectedSet.delete(sel);
        }
    }

    const entries = Array.from(countsMap.entries()).map(([key, val]) => {
        const meta = streamerMeta.get(key);
        return {
            key,
            name: val.name,
            displayName: (meta && meta.display_name) ? meta.display_name : val.name,
            avatarUrl: (meta && meta.avatar_url) ? meta.avatar_url : DEFAULT_TWITCH_AVATAR,
            count: val.count
        };
    }).sort((a, b) => b.count - a.count || a.displayName.localeCompare(b.displayName));

    const hasFilter = selectedSet.size > 0;
    const allActiveClass = !hasFilter
        ? 'bg-amber-500 text-slate-950 border-amber-400 shadow-sm'
        : 'bg-slate-900 text-slate-300 border-slate-700 hover:border-slate-500 hover:text-white';

    const avatarsHtml = entries.map(entry => {
        const isSelected = selectedSet.has(entry.key);
        const btnStateClass = !hasFilter
            ? 'border-slate-700 hover:border-amber-400/80 opacity-95 hover:opacity-100'
            : (isSelected
                ? 'border-amber-400 ring-2 ring-amber-400/70 bg-amber-500/15 opacity-100 scale-105'
                : 'border-slate-800 opacity-45 hover:opacity-95 hover:border-slate-600');
        return `
            <button type="button"
                onclick="${onToggleFnName}('${escapeJs(entry.key)}')"
                title="${escapeHtml(entry.displayName)} (${entry.count} ${entry.count === 1 ? 'Clip' : 'Clips'})"
                aria-pressed="${isSelected ? 'true' : 'false'}"
                class="group relative p-0.5 rounded-full border transition-all duration-150 focus:outline-none ${btnStateClass}">
                <img src="${escapeHtml(entry.avatarUrl)}"
                     alt="${escapeHtml(entry.displayName)}"
                     onerror="this.src='${DEFAULT_TWITCH_AVATAR}'"
                     class="w-9 h-9 rounded-full object-cover bg-slate-950 block">
                <span class="absolute -bottom-1 -right-1 min-w-[18px] h-[18px] px-1 rounded-full text-[10px] font-bold leading-none flex items-center justify-center border ${isSelected ? 'bg-amber-400 text-slate-950 border-slate-950' : 'bg-slate-800 text-slate-200 border-slate-950'}">${entry.count}</span>
                <span class="pointer-events-none opacity-0 group-hover:opacity-100 transition-opacity duration-150 absolute left-1/2 -translate-x-1/2 -top-8 z-30 px-2 py-1 rounded bg-slate-950 border border-slate-700 text-slate-100 text-[11px] font-semibold whitespace-nowrap shadow-lg">${escapeHtml(entry.displayName)}</span>
            </button>
        `;
    }).join('');

    barEl.classList.remove('hidden');
    barEl.innerHTML = `
        <span class="text-xs font-semibold text-slate-400 mr-1 whitespace-nowrap">Streamer:</span>
        <button type="button"
            onclick="${onClearFnName}()"
            class="px-2.5 py-1 rounded-full border text-xs font-semibold transition whitespace-nowrap ${allActiveClass}">
            Alle (${totalCount})
        </button>
        <div class="flex items-center gap-2 flex-wrap">
            ${avatarsHtml}
        </div>
    `;
}

function renderQueueStreamerFilter(clips) {
    renderStreamerAvatarFilterBar({
        barEl: document.getElementById('queue-streamer-filter-bar'),
        countsMap: buildStreamerCountsMap(clips),
        totalCount: clips ? clips.length : 0,
        selectedSet: selectedQueueStreamers,
        onToggleFnName: 'toggleQueueStreamerFilter',
        onClearFnName: 'clearQueueStreamerFilter'
    });
}

function renderQueue(clips, olderCount) {
    cachedQueueClips = clips || [];
    cachedQueueOlderCount = olderCount || 0;

    const tbody = document.getElementById('queue-tbody');
    const emptyState = document.getElementById('queue-empty-state');
    const olderBtn = document.getElementById('btn-delete-older');
    const olderBtnText = document.getElementById('btn-delete-older-text');

    if (olderBtn && olderBtnText) {
        if (olderCount && olderCount > 0) {
            olderBtn.classList.remove('hidden');
            olderBtn.classList.add('flex');
            olderBtnText.innerText = `Gestern & älter löschen (${olderCount})`;
        } else {
            olderBtn.classList.add('hidden');
            olderBtn.classList.remove('flex');
        }
    }

    renderQueueStreamerFilter(cachedQueueClips);

    if (!clips || clips.length === 0) {
        if (tbody) tbody.innerHTML = `<tr><td colspan="8" class="py-12 text-center text-slate-500">Keine Clips in der Warteschlange.</td></tr>`;
        if (emptyState) emptyState.classList.remove('hidden');
        return;
    }
    if (emptyState) emptyState.classList.add('hidden');

    const visibleClips = selectedQueueStreamers.size > 0
        ? clips.filter(c => selectedQueueStreamers.has(String(c.streamer || '').trim().toLowerCase()))
        : clips;

    if (!tbody) return;
    if (visibleClips.length === 0) {
        tbody.innerHTML = `<tr><td colspan="6" class="py-10 text-center text-slate-500">Keine Clips für die ausgewählten Streamer. <button type="button" onclick="clearQueueStreamerFilter()" class="ml-2 text-amber-400 hover:underline font-semibold">Filter zurücksetzen</button></td></tr>`;
        return;
    }

    tbody.innerHTML = visibleClips.map(clip => `
        <tr onclick="openRawPreview('${escapeJs(clip.clip_id)}', '${escapeJs(clip.streamer)}', '${escapeJs(clip.original_title)}', '${clip.view_count}', '${Math.round(clip.duration)}', '${escapeJs(clip.created_ago || '')}', '${escapeJs(clip.created_full || '')}')"
            class="hover:bg-slate-800/40 cursor-pointer transition group">
            <td class="py-3 px-4 text-center whitespace-nowrap">
                <div class="w-7 h-7 rounded bg-slate-800 group-hover:bg-amber-500 group-hover:text-slate-950 text-slate-400 flex items-center justify-center text-xs transition">
                    ▶
                </div>
            </td>
            <td class="py-3 px-4 whitespace-nowrap">
                <span class="font-semibold text-slate-200 text-sm block">${escapeHtml(clip.streamer)}</span>
            </td>
            <td class="py-3 px-4">
                <div class="font-medium text-slate-100 group-hover:text-amber-400 transition text-sm">${escapeHtml(clip.original_title)}</div>
            </td>
            <td class="py-3 px-4 text-slate-400 text-xs whitespace-nowrap">
                <span class="font-mono text-slate-300">${Math.round(clip.duration)}s</span>
                <span class="text-slate-600 mx-1.5">•</span>
                <span class="font-mono text-slate-300">${clip.view_count} Views</span>
            </td>
            <td class="py-3 px-4 text-slate-400 text-xs whitespace-nowrap" title="${escapeHtml(clip.created_full || '')}">
                <span>${escapeHtml(clip.created_ago || '-')}</span>
            </td>
            <td class="py-3 px-4 text-right whitespace-nowrap" onclick="event.stopPropagation()">
                <div class="flex items-center justify-end gap-1.5 opacity-80 group-hover:opacity-100 transition">
                    <button onclick="processOneClip('${clip.clip_id}')" class="px-3 py-1.5 bg-slate-800 hover:bg-amber-500 hover:text-slate-950 text-slate-200 font-semibold text-xs rounded border border-slate-700/80 hover:border-amber-500 transition shadow-sm">
                        In Studio
                    </button>
                    <button onclick="deleteSingleQueueClip('${clip.clip_id}')" class="p-1.5 text-slate-400 hover:text-rose-400 hover:bg-rose-950/40 rounded transition" title="Löschen">
                        ${SVG_ICONS.trash}
                    </button>
                </div>
            </td>
        </tr>
    `).join('');
}

async function processOneClip(clipId) {
    try {
        await apiFetch('/process-one/' + clipId, { method: 'POST' });
        updateStatus();
    } catch (e) {
        console.error(e);
    }
}

async function deleteSingleQueueClip(clipId) {
    if (!confirm('Clip unwiderruflich aus der Warteschlange löschen?')) return;
    try {
        let deleted = false;
        const invoke = getTauriInvoke();
        if (invoke) {
            try {
                await invoke('delete_queue_clip', { clipId });
                deleted = true;
            } catch (invokeErr) {
                console.warn('Tauri invoke delete_queue_clip failed, falling back to REST:', invokeErr);
            }
        }
        if (!deleted) {
            const res = await apiFetch('/queue/delete/' + clipId, {
                method: 'POST',
                headers: { 'X-Requested-With': 'fetch' }
            });
            if (!res.ok) {
                throw new Error('HTTP ' + res.status);
            }
        }
        await refreshDashboard(true);
        showToast('Clip aus Warteschlange gelöscht.', 'info');
    } catch (e) {
        alert('Fehler beim Löschen: ' + e);
    }
}

async function deleteOlderQueue() {
    if (!confirm('Wirklich alle Roh-Clips von gestern und älter löschen?\n\n(Clips von heute bleiben vollständig erhalten)')) return;
    try {
        await apiFetch('/queue/delete-older', { method: 'POST' });
        refreshDashboard();
    } catch (e) {
        alert('Fehler: ' + e);
    }
}

// ----------------------------------------
// 2. STUDIO & FREIGABE
// ----------------------------------------
let selectedStudioStreamers = new Set();
let cachedStudioClips = [];
let gLastStudioPillsSig = '';

function getStudioCardSignature(clip) {
    return JSON.stringify([
        clip.clip_id,
        clip.updated_at || '',
        Boolean(clip.has_video),
        Boolean(clip.is_manually_published),
        clip.sticker_text || '',
        clip.title || '',
        clip.sub_position || '',
        clip.layout_mode || '',
        clip.cam_filter || '',
        clip.transcript || '',
        clip.view_count || 0,
        clip.streamer || '',
        clip.created_ago || '',
        clip.created_full || ''
    ]);
}

function isStudioCardBusy(cardEl) {
    if (!cardEl) return false;
    const active = document.activeElement;
    if (active && cardEl.contains(active)) {
        const tag = active.tagName;
        if (tag === 'TEXTAREA' || tag === 'INPUT' || tag === 'SELECT') {
            return true;
        }
    }
    const video = cardEl.querySelector('video');
    if (video && ((!video.paused && !video.ended) || (video.currentTime > 0 && !video.ended))) {
        return true;
    }
    return false;
}

function buildStudioCardHtml(clip, cardSig) {
    const cacheBust = encodeURIComponent(String(clip.updated_at || '1'));
    const sigAttr = escapeHtml(cardSig || getStudioCardSignature(clip));
    return `
        <div class="bg-slate-900 border border-slate-800 rounded-lg overflow-hidden flex flex-col hover:border-zinc-700 transition-all duration-300 studio-clip-card ${clip.is_manually_published ? 'opacity-40 grayscale hover:grayscale-0 hover:opacity-95 border-emerald-900/80 bg-slate-950/90' : ''}" id="card-${clip.clip_id}" data-streamer="${escapeHtml(clip.streamer.toLowerCase())}" data-card-sig="${sigAttr}" data-video-ver="${escapeHtml(cacheBust)}">
            <!-- Header -->
            <div class="flex justify-between items-center bg-slate-950/90 px-4 py-2.5 border-b border-slate-800">
                <div class="flex items-center gap-2">
                    <span class="bg-zinc-800 border border-zinc-700 text-xs font-semibold px-2 py-0.5 rounded text-amber-400">
                        ${escapeHtml(clip.streamer)}
                    </span>
                    ${clip.created_ago ? `
                    <span class="text-[11px] text-slate-400 font-medium whitespace-nowrap" title="${escapeHtml(clip.created_full || '')}">
                        ${SVG_ICONS.calendar} ${escapeHtml(clip.created_ago)}
                    </span>
                    ` : ''}
                </div>
                <label class="flex items-center gap-2 cursor-pointer bg-slate-900 hover:bg-slate-800 px-3 py-1 rounded-lg border border-slate-700/80 transition" title="Video als veröffentlicht markieren (graut die Karte aus)">
                    <input type="checkbox" onchange="toggleManualPublished('${clip.clip_id}', this.checked)" ${clip.is_manually_published ? 'checked' : ''} class="w-4 h-4 accent-emerald-500 rounded cursor-pointer">
                    <span class="text-xs font-bold ${clip.is_manually_published ? 'text-emerald-400' : 'text-slate-400'}" id="pub-label-${clip.clip_id}">
                        ${clip.is_manually_published ? '✓ Veröffentlicht' : 'Veröffentlicht?'}
                    </span>
                </label>
            </div>

            <!-- Video Player -->
            <div class="relative bg-black aspect-[9/16] w-full max-h-[480px] flex items-center justify-center overflow-hidden">
                ${clip.has_video ? `
                <video id="studio-video-${clip.clip_id}" controls preload="metadata" poster="${getBackendUrl('/thumbnail/' + clip.clip_id + '?v=' + cacheBust)}" class="w-full h-full object-contain">
                    <source src="${getBackendUrl('/video/' + clip.clip_id + '?v=' + cacheBust)}" type="video/mp4">
                </video>
                ` : `
                <div class="text-center p-6 text-slate-500">
                    <div class="w-8 h-8 mx-auto mb-2 border-2 border-amber-400 border-t-transparent rounded-full animate-spin"></div>
                    Video wird gerendert...
                </div>
                `}
                <span class="absolute top-3 right-3 bg-slate-900/90 text-xs text-slate-300 font-semibold px-2 py-1 rounded-md border border-slate-800">
                    ${SVG_ICONS.eye} ${clip.view_count}
                </span>
                ${clip.has_video ? `
                <button type="button" onclick="downloadShortVideo('${clip.clip_id}', this, event)" class="absolute bottom-3 right-3 bg-slate-900 hover:bg-emerald-600 text-white text-xs font-bold px-3 py-1.5 rounded shadow border border-slate-700 transition flex items-center gap-1.5 cursor-pointer z-10" title="Speicherort wählen & HQ Video sichern (Shift-Klick für Downloads-Ordner)">
                    ${SVG_ICONS.save} <span>HQ Download</span>
                </button>
                ` : ''}
            </div>

            <!-- Edit Form -->
            <form id="form-${clip.clip_id}" action="/save/${clip.clip_id}" method="POST" class="p-5 flex-1 flex flex-col justify-between gap-4">
                <div class="space-y-3">
                    <div>
                        <label class="block text-xs font-medium text-slate-300 mb-1">
                            Titel (YouTube / TikTok)
                        </label>
                        <input type="text" name="title" value="${escapeHtml(clip.title || '')}" class="w-full bg-slate-900 border border-slate-700 rounded-md px-3 py-2 text-sm text-white focus:outline-none focus:border-amber-500">
                    </div>

                    <button type="button" onclick="openCropModal('${clip.clip_id}', '${escapeJs(clip.streamer)}', '${escapeJs(clip.title || '')}')" class="w-full py-2.5 px-3 bg-slate-800 hover:bg-slate-700 border border-slate-700 text-slate-200 hover:text-white rounded text-xs font-semibold transition flex items-center justify-center gap-2">
                        ${SVG_ICONS.crop} Clip Editor
                    </button>
                </div>

                <div class="pt-4 border-t border-slate-800 flex flex-col gap-2">
                    <div class="grid grid-cols-2 gap-2">
                        <button type="submit" name="action" value="save" class="py-2 px-3 bg-slate-800 hover:bg-slate-700 border border-slate-700 text-slate-200 font-semibold text-xs rounded transition flex items-center justify-center gap-1.5">
                            ${SVG_ICONS.save} Nur speichern
                        </button>
                        <button type="submit" name="action" value="rerender" class="py-2 px-3 bg-amber-500 hover:bg-amber-400 text-zinc-950 font-semibold text-xs rounded transition flex items-center justify-center gap-1.5 shadow-sm">
                            ${SVG_ICONS.scan} Speichern & Neu Rendern
                        </button>
                    </div>
                    <div class="grid grid-cols-2 gap-2">
                        <button type="submit" name="action" value="schedule" class="py-2 px-3 bg-sky-700 hover:bg-sky-600 font-bold text-xs rounded-lg transition text-white flex items-center justify-center gap-1">
                            ${SVG_ICONS.calendar} Zeitplan
                        </button>
                        <button type="submit" name="action" value="publish_now" class="py-2 px-3 bg-emerald-600 hover:bg-emerald-500 font-bold text-xs rounded-lg transition text-white flex items-center justify-center gap-1">
                            ${SVG_ICONS.play} Sofort posten
                        </button>
                    </div>
                    <div class="text-right pt-0.5">
                        <button type="submit" name="action" value="delete" onclick="return confirm('Clip wirklich löschen?');" class="text-xs text-rose-400 hover:text-rose-300 transition inline-flex items-center gap-1 cursor-pointer">
                            ${SVG_ICONS.trash} Löschen & Ignorieren
                        </button>
                    </div>
                </div>
            </form>
        </div>
    `;
}

function renderStudio(clips, streamerCounts, forceRender = false) {
    const grid = document.getElementById('studio-grid');
    const emptyState = document.getElementById('studio-empty-state');
    const pillsContainer = document.getElementById('streamer-pills-container');

    // Nutzer tippt gerade in einer Studio-Karte -> bei aktivem Formularfokus nicht global eingreifen
    if (!forceRender && grid && document.activeElement && grid.contains(document.activeElement)) {
        const tag = document.activeElement.tagName;
        if (tag === 'TEXTAREA' || tag === 'INPUT' || tag === 'SELECT') {
            return;
        }
    }

    cachedStudioClips = clips || [];

    // Streamer Filter Avatar Bar nur bei tatsächlicher Änderung neu aufbauen
    if (pillsContainer) {
        const totalCount = cachedStudioClips.length;
        const selectedKey = Array.from(selectedStudioStreamers).sort().join(',');
        const pillsSig = JSON.stringify({
            totalCount,
            streamerCounts: streamerCounts || {},
            streamersLen: (cachedStreamers || []).length,
            selectedKey
        });
        if (forceRender || pillsSig !== gLastStudioPillsSig) {
            gLastStudioPillsSig = pillsSig;
            renderStudioStreamerFilter();
        }
    }

    if (!clips || clips.length === 0) {
        if (grid) grid.innerHTML = '';
        if (emptyState) emptyState.classList.remove('hidden');
        return;
    }
    if (emptyState) emptyState.classList.add('hidden');
    if (!grid) return;

    const targetIds = new Set(clips.map(c => c.clip_id));
    Array.from(grid.children).forEach(child => {
        if (child.id && child.id.startsWith('card-')) {
            const cid = child.id.slice(5);
            if (!targetIds.has(cid) && (forceRender || !isStudioCardBusy(child))) {
                child.remove();
            }
        }
    });

    const temp = document.createElement('div');
    let domMutated = false;

    clips.forEach((clip, idx) => {
        const cardSig = getStudioCardSignature(clip);
        const existingCard = document.getElementById('card-' + clip.clip_id);

        if (existingCard) {
            const busy = isStudioCardBusy(existingCard);
            const sameSig = existingCard.getAttribute('data-card-sig') === cardSig;
            const prevVideoVer = existingCard.getAttribute('data-video-ver') || '';
            const nextVideoVer = encodeURIComponent(String(clip.updated_at || '1'));
            const videoVersionChanged = prevVideoVer !== nextVideoVer;
            const vidEl = existingCard.querySelector('video');
            const isActivelyPlaying = Boolean(vidEl && !vidEl.paused && !vidEl.ended);

            if (sameSig) {
                return;
            }
            if (!forceRender && busy) {
                // Hintergrund-Refresh: laufende Video-Wiedergabe oder aktives Formular nicht stören
                return;
            }
            if (forceRender && isActivelyPlaying && !videoVersionChanged) {
                return;
            }
            temp.innerHTML = buildStudioCardHtml(clip, cardSig).trim();
            const newCard = temp.firstElementChild;
            if (newCard) {
                existingCard.replaceWith(newCard);
                if (videoVersionChanged) {
                    try { newCard.querySelector('video')?.load(); } catch (_) {}
                }
                domMutated = true;
            }
            return;
        }

        temp.innerHTML = buildStudioCardHtml(clip, cardSig).trim();
        const newCard = temp.firstElementChild;
        if (!newCard) return;

        const refNode = grid.children[idx] || null;
        grid.insertBefore(newCard, refNode);
        domMutated = true;
    });

    if (domMutated && selectedStudioStreamers.size > 0) {
        applyStudioStreamerFilter();
    }
}

async function scheduleSingleClip(clipId) {
    try {
        await apiFetch('/schedule-one/' + clipId, { method: 'POST' });
        refreshDashboard();
    } catch (e) {
        console.error(e);
    }
}

// ----------------------------------------
// 3. VERÖFFENTLICHUNGS-PLANER
// ----------------------------------------
function renderPlanner(scheduledClips) {
    const tbody = document.getElementById('planner-tbody');
    if (!tbody) return;

    if (!scheduledClips || scheduledClips.length === 0) {
        tbody.innerHTML = `<tr><td colspan="5" class="py-8 text-center text-slate-500">Keine Clips im Veröffentlichungs-Zeitplan. Klicke im Studio auf „📅 Zeitplan“!</td></tr>`;
        return;
    }

    tbody.innerHTML = scheduledClips.map(clip => `
        <tr class="hover:bg-slate-800/40 transition">
            <td class="py-3.5 px-4 font-bold text-amber-400">${escapeHtml(clip.streamer)}</td>
            <td class="py-3.5 px-4 text-slate-200">
                <div class="font-medium line-clamp-1">${escapeHtml(clip.ai_title || clip.original_title)}</div>
            </td>
            <td class="py-3.5 px-4 text-sky-400 font-mono text-xs whitespace-nowrap">
                ${SVG_ICONS.clock} ${escapeHtml(clip.scheduled_publish_at || '-')}
            </td>
            <td class="py-3.5 px-4 text-right space-x-2 whitespace-nowrap">
                <button onclick="publishNow('${clip.clip_id}')" class="px-3 py-1 bg-emerald-600 hover:bg-emerald-500 font-bold text-xs rounded-lg text-white transition active:scale-95 shadow">
                    Sofort hochladen
                </button>
                <button onclick="cancelSchedule('${clip.clip_id}')" class="px-3 py-1 bg-slate-800 hover:bg-slate-700 border border-slate-700 font-bold text-xs rounded-lg text-slate-300 transition">
                    Planung aufheben
                </button>
            </td>
        </tr>
    `).join('');
}

async function publishNow(clipId) {
    if (!confirm('Dieses Video jetzt sofort veröffentlichen?')) return;
    try {
        await apiFetch('/schedule/publish-now/' + clipId, { method: 'POST' });
        refreshDashboard();
    } catch (e) {
        alert('Fehler: ' + e);
    }
}

async function cancelSchedule(clipId) {
    try {
        await apiFetch('/schedule/cancel/' + clipId, { method: 'POST' });
        refreshDashboard();
    } catch (e) {
        alert('Fehler: ' + e);
    }
}

// ----------------------------------------
// 4. PUBLISHED ARCHIVE
// ----------------------------------------
function renderPublished(publishedClips) {
    const tbody = document.getElementById('published-tbody');
    if (!tbody) return;

    if (!publishedClips || publishedClips.length === 0) {
        tbody.innerHTML = `<tr><td colspan="5" class="py-8 text-center text-slate-500">Noch keine Clips veröffentlicht.</td></tr>`;
        return;
    }

    tbody.innerHTML = publishedClips.map(clip => `
        <tr class="hover:bg-slate-800/40 transition">
            <td class="py-3.5 px-4 font-bold text-amber-400">${escapeHtml(clip.streamer)}</td>
            <td class="py-3.5 px-4 text-slate-200">
                <div class="font-medium line-clamp-1">${escapeHtml(clip.ai_title || clip.original_title)}</div>
            </td>
            <td class="py-3.5 px-4 text-slate-400 font-mono text-xs whitespace-nowrap">
                ${escapeHtml(clip.published_at || '-')}
            </td>
            <td class="py-3.5 px-4 text-right">
                ${clip.youtube_video_id ? `
                <a href="https://youtube.com/shorts/${clip.youtube_video_id}" target="_blank" class="text-xs text-red-400 hover:text-red-300 font-bold flex items-center gap-1 justify-end">
                    ${SVG_ICONS.play} Auf YouTube ansehen
                </a>
                ` : `
                <span class="text-xs text-slate-500">Erledigt</span>
                `}
            </td>
        </tr>
    `).join('');
}

// ----------------------------------------
// 5. STREAMER MANAGEMENT (FULL PAGE & COMPACT)
// ----------------------------------------
function renderStreamers(streamers) {
    if (!streamers) return;

    // Update count badges
    const tabCount = document.getElementById('tab-count-streamers');
    if (tabCount) tabCount.innerText = streamers.length;
    const fpCount = document.getElementById('fullpage-streamer-count');
    if (fpCount) fpCount.innerText = streamers.length;
    const filterCount = document.getElementById('streamer-filter-count');
    if (filterCount) filterCount.innerText = `${streamers.length} angezeigt`;

    const fullGrid = document.getElementById('streamer-grid-list');
    if (fullGrid) {
        fullGrid.innerHTML = streamers.map(s => {
            const curLayout = s.layout || 'auto';
            const hasCustom = !!s.custom_crops || !!s.has_custom_crops;
            const avatarUrl = s.avatar_url || 'https://static-cdn.jtvnw.net/user-default-pictures-uv/cdd517fe-def4-11e9-948e-784f43822e80-profile_image-300x300.png';
            const dispName = s.display_name || s.name;
            const isLive = !!s.is_live;
            return `
            <div class="streamer-card bg-slate-900 border ${isLive ? 'border-rose-900/60 shadow-rose-950/20' : 'border-slate-800'} hover:border-slate-700 rounded-lg p-4 shadow-sm transition flex flex-col justify-between gap-3.5" data-streamer="${escapeHtml(s.name.toLowerCase())}">
                <div class="flex items-start justify-between gap-3">
                    <div class="flex items-center gap-3 min-w-0">
                        <div class="relative shrink-0">
                            <img src="${escapeHtml(avatarUrl)}" 
                                 alt="${escapeHtml(s.name)}" 
                                 onerror="this.src='https://static-cdn.jtvnw.net/user-default-pictures-uv/cdd517fe-def4-11e9-948e-784f43822e80-profile_image-300x300.png'"
                                 class="w-11 h-11 rounded-full border ${isLive ? 'border-rose-500' : 'border-slate-700'} object-cover bg-slate-950">
                            <span class="absolute -bottom-0.5 -right-0.5 w-3 h-3 ${isLive ? 'bg-rose-500 animate-pulse' : 'bg-emerald-500'} border-2 border-slate-900 rounded-full" title="${isLive ? 'Jetzt LIVE auf Twitch!' : 'Überwachung aktiv'}"></span>
                        </div>
                        <div class="min-w-0">
                            <div class="flex items-center gap-1.5">
                                <span class="font-bold text-sm text-white truncate block">${escapeHtml(dispName)}</span>
                                ${isLive ? `
                                    <span class="px-1.5 py-0.2 bg-rose-950 text-rose-400 border border-rose-800 text-2xs font-extrabold uppercase rounded animate-pulse tracking-wider">LIVE</span>
                                ` : ''}
                            </div>
                            <a href="https://twitch.tv/${encodeURIComponent(s.name)}" target="_blank" class="text-2xs text-slate-400 hover:text-slate-200 font-mono flex items-center gap-1 hover:underline">
                                <span>twitch.tv/${escapeHtml(s.name)}</span>
                                <svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14"/></svg>
                            </a>
                            ${isLive && s.game ? `
                                <div class="text-2xs text-amber-300 font-medium truncate mt-0.5">🎮 ${escapeHtml(s.game)}</div>
                            ` : ''}
                            <div class="mt-1">
                                ${hasCustom ? `
                                    <span class="inline-flex items-center gap-1 text-2xs font-semibold text-emerald-300 bg-emerald-950/60 border border-emerald-800/60 px-2 py-0.5 rounded">
                                        ${SVG_ICONS.check} Eigener Rahmen aktiv
                                    </span>
                                ` : `
                                    <span class="inline-flex items-center gap-1 text-2xs font-normal text-slate-400 bg-slate-800/80 border border-slate-700 px-2 py-0.5 rounded">
                                        Layout: ${escapeHtml(curLayout)}
                                    </span>
                                `}
                            </div>
                        </div>
                    </div>
                    <button onclick="removeStreamer('${escapeJs(s.name)}')" class="text-slate-500 hover:text-rose-400 p-1.5 hover:bg-rose-950/40 rounded-md transition shrink-0" title="Streamer entfernen">
                        ${SVG_ICONS.trash}
                    </button>
                </div>

                <div class="grid grid-cols-2 gap-2 bg-slate-950/60 p-2.5 rounded-md border border-slate-800/80 text-xs">
                    <div>
                        <label class="block text-2xs font-medium text-slate-400 uppercase tracking-wider mb-1">Min. Views:</label>
                        <input type="number" value="${s.min_clip_views || 25}" min="1" max="100000"
                               onchange="updateStreamerMinViews('${escapeJs(s.name)}', this.value)"
                               class="w-full bg-slate-800 border border-slate-700 focus:border-amber-500 rounded px-2 py-1 text-xs text-amber-300 font-semibold focus:outline-none">
                    </div>
                    <div>
                        <label class="block text-2xs font-medium text-slate-400 uppercase tracking-wider mb-1">Max Clips/Run:</label>
                        <input type="number" value="${s.max_clips_per_run || 2}" min="1" max="10"
                               onchange="updateStreamerMaxClips('${escapeJs(s.name)}', this.value)"
                               class="w-full bg-slate-800 border border-slate-700 focus:border-amber-500 rounded px-2 py-1 text-xs text-white font-semibold focus:outline-none">
                    </div>
                    <div class="col-span-2 mt-0.5">
                        <label class="block text-2xs font-medium text-slate-400 uppercase tracking-wider mb-1">Standard Clip-Layout:</label>
                        <select onchange="updateStreamerLayout('${escapeJs(s.name)}', this.value)"
                                class="w-full bg-slate-800 border border-slate-700 focus:border-amber-500 rounded px-2 py-1 text-xs text-amber-300 font-medium focus:outline-none">
                            <option value="auto" ${curLayout === 'auto' ? 'selected' : ''}>Auto (KI Facecam-Scan)</option>
                            <option value="split_cam_top" ${curLayout === 'split_cam_top' ? 'selected' : ''}>Split-Screen (Cam oben + Game unten)</option>
                            <option value="blur_stack" ${curLayout === 'blur_stack' ? 'selected' : ''}>Keine Cam (Gameplay mit Blur)</option>
                            <option value="single_916" ${curLayout === 'single_916' ? 'selected' : ''}>9:16 Vollbild (IRL)</option>
                            <option value="custom" ${curLayout === 'custom' ? 'selected' : ''}>Eigener gespeicherter Rahmen</option>
                            <option value="top_left" ${curLayout === 'top_left' ? 'selected' : ''}>Cam: Oben Links</option>
                            <option value="top_right" ${curLayout === 'top_right' ? 'selected' : ''}>Cam: Oben Rechts</option>
                            <option value="bottom_left" ${curLayout === 'bottom_left' ? 'selected' : ''}>Cam: Unten Links</option>
                            <option value="bottom_right" ${curLayout === 'bottom_right' ? 'selected' : ''}>Cam: Unten Rechts</option>
                        </select>
                    </div>
                </div>

                <div class="flex items-center gap-2 pt-1 border-t border-slate-800/80">
                    <button type="button" onclick="loadSampleClipDirect('${escapeJs(s.name)}', this)" class="flex-1 py-1.5 px-3 bg-slate-800 hover:bg-slate-700 border border-slate-700 hover:border-amber-500/50 text-amber-300 font-semibold text-xs rounded-md transition flex items-center justify-center gap-1.5" title="Lädt automatisch einen Test-Clip herunter und öffnet den visuellen 16:9 zu 9:16 Rahmen-Editor">
                        ${SVG_ICONS.scissors} <span>Test-Clip & Rahmen einstellen</span>
                    </button>
                    <button type="button" onclick="openStreamerConfigModal('${escapeJs(s.name)}')" class="px-2.5 py-1.5 bg-slate-800 hover:bg-slate-700 border border-slate-700 text-slate-300 hover:text-white text-xs font-semibold rounded-md transition shrink-0" title="Erweiterte Einstellungen">
                        ${SVG_ICONS.settings}
                    </button>
                </div>
            </div>
            `;
        }).join('');
    }

    const container = document.getElementById('streamer-modal-list');
    if (container) {
        container.innerHTML = streamers.map(s => {
            const curLayout = s.layout || 'auto';
            const hasCustom = !!s.custom_crops || !!s.has_custom_crops;
            const avatarUrl = s.avatar_url || 'https://static-cdn.jtvnw.net/user-default-pictures-uv/cdd517fe-def4-11e9-948e-784f43822e80-profile_image-300x300.png';
            const dispName = s.display_name || s.name;
            return `
            <div class="flex items-center justify-between bg-slate-800/80 border border-slate-700/80 p-3 rounded-md hover:border-slate-600 transition gap-3">
                <div class="flex items-center gap-2.5 min-w-0">
                    <img src="${escapeHtml(avatarUrl)}" alt="${escapeHtml(s.name)}" onerror="this.src='https://static-cdn.jtvnw.net/user-default-pictures-uv/cdd517fe-def4-11e9-948e-784f43822e80-profile_image-300x300.png'" class="w-8 h-8 rounded-full border border-slate-700 object-cover bg-slate-950 shrink-0">
                    <div class="min-w-0">
                        <span class="font-bold text-xs text-amber-400 block truncate">${escapeHtml(dispName)}</span>
                        <span class="text-2xs text-slate-400 font-mono">Min. ${s.min_clip_views || 25} Views • Max ${s.max_clips_per_run || 2}</span>
                    </div>
                </div>
                <div class="flex items-center gap-1.5">
                    <button type="button" onclick="loadSampleClipDirect('${escapeJs(s.name)}', this)" class="px-2 py-1 bg-slate-800 hover:bg-slate-700 border border-slate-700 text-amber-300 text-xs font-semibold rounded-md transition flex items-center gap-1" title="Test-Clip & Rahmen">
                        ${SVG_ICONS.scissors} <span>Rahmen</span>
                    </button>
                    <button type="button" onclick="openStreamerConfigModal('${escapeJs(s.name)}')" class="p-1 bg-slate-800 hover:bg-slate-700 border border-slate-700 text-slate-300 hover:text-white text-xs font-semibold rounded-md transition" title="Konfigurieren">
                        ${SVG_ICONS.settings}
                    </button>
                    <button onclick="removeStreamer('${escapeJs(s.name)}')" class="text-rose-400 hover:text-rose-300 p-1 hover:bg-rose-950/50 rounded-md transition" title="Entfernen">
                        ${SVG_ICONS.trash}
                    </button>
                </div>
            </div>
            `;
        }).join('');
    }
}

async function updateStreamerLayout(name, layout) {
    if (!name || !layout) return;
    try {
        await apiFetch('/api/streamers/' + encodeURIComponent(name) + '/layout', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ layout: layout })
        });
        showToast(`Layout für ${name} auf '${layout}' aktualisiert!`, 'success');
        refreshDashboard();
    } catch (e) {
        alert('Fehler beim Ändern des Layouts: ' + e);
    }
}

async function saveAsDefaultStreamerLayout() {
    if (!currentCropStreamer) {
        alert('Kein Streamer für diesen Clip ermittelt.');
        return;
    }
    const vw = videoNativeWidth || 1920;
    const vh = videoNativeHeight || 1080;
    
    let customCropsPayload;
    let layoutMode = currentCropMode === 'single_916' ? 'single_916' : 'custom';
    
    if (currentCropMode === 'single_916') {
        customCropsPayload = {
            mode: 'single_916',
            enabled: true,
            single: {
                x_pct: cropState.single.x,
                y_pct: 0.0,
                w_pct: cropState.single.w,
                h_pct: 1.0,
                x: Math.round(cropState.single.x * vw),
                y: 0,
                w: Math.round(cropState.single.w * vw),
                h: vh
            }
        };
    } else {
        customCropsPayload = {
            mode: 'split',
            enabled: true,
            cam: {
                x_pct: cropState.cam.x,
                y_pct: cropState.cam.y,
                w_pct: cropState.cam.w,
                h_pct: cropState.cam.h,
                x: Math.round(cropState.cam.x * vw),
                y: Math.round(cropState.cam.y * vh),
                w: Math.round(cropState.cam.w * vw),
                h: Math.round(cropState.cam.h * vh),
                enabled: cropState.cam.enabled
            },
            game: {
                x_pct: cropState.game.x,
                y_pct: cropState.game.y,
                w_pct: cropState.game.w,
                h_pct: cropState.game.h,
                x: Math.round(cropState.game.x * vw),
                y: Math.round(cropState.game.y * vh),
                w: Math.round(cropState.game.w * vw),
                h: Math.round(cropState.game.h * vh),
                enabled: true
            }
        };
    }
    
    try {
        await apiFetch('/api/streamers/' + encodeURIComponent(currentCropStreamer) + '/layout', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ layout: layoutMode, custom_crops: customCropsPayload })
        });
        showToast(`✓ Standard-Layout für ${currentCropStreamer} gespeichert! Zukünftige Clips werden automatisch so geschnitten.`, 'success');
        refreshDashboard();
    } catch (e) {
        alert('Fehler beim Speichern des Standard-Layouts: ' + e);
    }
}

async function updateStreamerMinViews(name, minViews) {
    const val = parseInt(minViews, 10);
    if (isNaN(val) || val < 1) return;
    try {
        await apiFetch('/api/streamers/update', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name: name, min_clip_views: val })
        });
        showToast(`Mindest-Views für ${name} auf ${val} geändert!`, 'success');
    } catch (e) {
        alert('Fehler beim Aktualisieren: ' + e);
    }
}

async function updateStreamerMaxClips(name, maxClips) {
    const val = parseInt(maxClips, 10);
    if (isNaN(val) || val < 1) return;
    try {
        await apiFetch('/api/streamers/update', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name: name, max_clips_per_run: val })
        });
        showToast(`Max Clips für ${name} auf ${val} geändert!`, 'success');
    } catch (e) {
        alert('Fehler beim Aktualisieren: ' + e);
    }
}

async function applyBulkMinViews() {
    const input = document.getElementById('bulk-min-views-input');
    if (!input) return;
    const val = parseInt(input.value, 10);
    if (isNaN(val) || val < 1) {
        alert('Bitte eine gültige Zahl für Mindest-Views eingeben.');
        return;
    }
    if (!confirm(`Sollen die Mindest-Views für ALLE Streamer auf ${val} gesetzt werden?`)) return;
    try {
        const res = await apiFetch('/api/streamers/update-all-views', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ min_clip_views: val })
        });
        showToast(`Mindest-Views für alle Streamer auf ${val} gesetzt!`, 'success');
        refreshDashboard();
    } catch (e) {
        alert('Fehler: ' + e);
    }
}

async function openStreamerConfigModal(streamerName) {
    if (!streamerName) return;
    const modal = document.getElementById('streamer-config-modal');
    if (modal) {
        modal.classList.remove('hidden');
        modal.classList.add('flex');
        modal.style.setProperty('display', 'flex', 'important');
    }

    const titleEl = document.getElementById('cfg-modal-streamer-name');
    if (titleEl) titleEl.innerText = streamerName;

    const hiddenName = document.getElementById('cfg-streamer-hidden-name');
    if (hiddenName) hiddenName.value = streamerName;

    const customBadge = document.getElementById('cfg-streamer-custom-badge');
    if (customBadge) {
        customBadge.classList.add('hidden');
        customBadge.classList.remove('flex');
    }

    // Reset sample button state
    const spinner = document.getElementById('btn-sample-spinner');
    const btnText = document.getElementById('btn-sample-text');
    const btn = document.getElementById('btn-load-streamer-sample');
    if (spinner) spinner.classList.add('hidden');
    if (btnText) btnText.innerText = 'Test-Clip laden & Rahmen visuell einstellen';
    if (btn) {
        btn.disabled = false;
        btn.classList.remove('opacity-60', 'cursor-not-allowed');
    }

    try {
        const resp = await apiFetch('/api/streamers/' + encodeURIComponent(streamerName) + '/config');
        const data = await resp.json();
        if (data && data.success) {
            const minViewsInput = document.getElementById('cfg-streamer-min-views');
            if (minViewsInput) minViewsInput.value = data.min_clip_views || 25;

            const maxClipsInput = document.getElementById('cfg-streamer-max-clips');
            if (maxClipsInput) maxClipsInput.value = data.max_clips_per_run || 2;

            const layoutSelect = document.getElementById('cfg-streamer-layout');
            if (layoutSelect) layoutSelect.value = data.layout || 'auto';

            if (customBadge) {
                if (data.has_custom_crops) {
                    customBadge.classList.remove('hidden');
                    customBadge.classList.add('flex');
                } else {
                    customBadge.classList.add('hidden');
                    customBadge.classList.remove('flex');
                }
            }
        }
    } catch (e) {
        console.error('Fehler beim Laden der Streamer-Konfiguration:', e);
    }
}

function closeStreamerConfigModal() {
    const modal = document.getElementById('streamer-config-modal');
    if (modal) {
        modal.classList.add('hidden');
        modal.classList.remove('flex');
        modal.style.setProperty('display', 'none', 'important');
    }
}

async function saveStreamerConfig(event) {
    if (event) event.preventDefault();
    const hiddenName = document.getElementById('cfg-streamer-hidden-name');
    const name = hiddenName ? hiddenName.value.trim() : '';
    if (!name) return;

    const minViews = parseInt(document.getElementById('cfg-streamer-min-views').value, 10) || 25;
    const maxClips = parseInt(document.getElementById('cfg-streamer-max-clips').value, 10) || 2;
    const layout = document.getElementById('cfg-streamer-layout').value || 'auto';

    try {
        await apiFetch('/api/streamers/' + encodeURIComponent(name) + '/config', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                min_clip_views: minViews,
                max_clips_per_run: maxClips,
                layout: layout
            })
        });
        showToast(`✓ Konfiguration für ${name} gespeichert!`, 'success');
        closeStreamerConfigModal();
        refreshDashboard();
    } catch (e) {
        alert('Fehler beim Speichern: ' + e);
    }
}

async function loadSampleClipForStreamer() {
    const hiddenName = document.getElementById('cfg-streamer-hidden-name');
    const name = hiddenName ? hiddenName.value.trim() : '';
    if (!name) {
        alert('Kein Streamer ausgewählt.');
        return;
    }

    const spinner = document.getElementById('btn-sample-spinner');
    const btnText = document.getElementById('btn-sample-text');
    const btn = document.getElementById('btn-load-streamer-sample');

    if (spinner) spinner.classList.remove('hidden');
    if (btnText) btnText.innerText = 'Lade Test-Clip von Twitch herunter...';
    if (btn) {
        btn.disabled = true;
        btn.classList.add('opacity-60', 'cursor-not-allowed');
    }

    try {
        const resp = await apiFetch('/api/streamers/' + encodeURIComponent(name) + '/sample-clip', {
            method: 'POST'
        });
        const data = await resp.json();
        if (data && data.success && data.clip_id) {
            closeStreamerConfigModal();
            closeStreamerModal();
            showToast(`Test-Clip für ${name} bereit! Rahmen anpassen und 'Als Standard für Streamer merken' klicken.`, 'info');
            openCropModal(data.clip_id, name, data.title || ('Test-Clip Vorlage (' + name + ')'));
        } else {
            const err = (data && data.error) ? data.error : 'Konnte keinen Clip laden.';
            showToast('Fehler: ' + err, 'error');
            alert('Fehler: ' + err);
        }
    } catch (e) {
        showToast('Fehler beim Laden des Test-Clips: ' + e, 'error');
        alert('Fehler beim Laden des Test-Clips: ' + e);
    } finally {
        if (spinner) spinner.classList.add('hidden');
        if (btnText) btnText.innerText = 'Test-Clip laden & Rahmen visuell einstellen';
        if (btn) {
            btn.disabled = false;
            btn.classList.remove('opacity-60', 'cursor-not-allowed');
        }
    }
}

async function loadSampleClipDirect(name, btnEl) {
    if (!name) return;
    const oldHtml = btnEl ? btnEl.innerHTML : '';
    if (btnEl) {
        btnEl.disabled = true;
        btnEl.classList.add('opacity-70', 'cursor-not-allowed');
        btnEl.innerHTML = `<span class="inline-block w-3.5 h-3.5 border-2 border-amber-400 border-t-transparent rounded-full animate-spin mr-1"></span><span>Lade Test-Clip...</span>`;
    }
    showToast(`Lade aktuellen Clip von ${name} von Twitch herunter...`, 'info');
    try {
        const resp = await apiFetch('/api/streamers/' + encodeURIComponent(name) + '/sample-clip', {
            method: 'POST'
        });
        const data = await resp.json();
        if (data && data.success && data.clip_id) {
            closeStreamerConfigModal();
            closeStreamerModal();
            showToast(`Test-Clip für ${name} geladen! Rahmen jetzt anpassen.`, 'success');
            openCropModal(data.clip_id, name, data.title || ('Standard-Rahmen Vorlage (' + name + ')'));
        } else {
            const err = (data && data.error) ? data.error : 'Konnte keinen Test-Clip laden. Hat der Streamer aktuelle Clips auf Twitch?';
            showToast('Fehler: ' + err, 'error');
            alert('Fehler: ' + err);
        }
    } catch (e) {
        showToast('Fehler beim Laden des Test-Clips: ' + e, 'error');
        alert('Fehler beim Laden des Test-Clips: ' + e);
    } finally {
        if (btnEl) {
            btnEl.disabled = false;
            btnEl.classList.remove('opacity-70', 'cursor-not-allowed');
            btnEl.innerHTML = oldHtml;
        }
    }
}

function filterStreamersList(searchTerm) {
    const q = (searchTerm || '').trim().toLowerCase();
    const cards = document.querySelectorAll('.streamer-card');
    let count = 0;
    cards.forEach(card => {
        const name = card.getAttribute('data-streamer') || '';
        const match = !q || name.includes(q);
        card.style.display = match ? 'flex' : 'none';
        if (match) count++;
    });
    const cntEl = document.getElementById('streamer-filter-count');
    if (cntEl) cntEl.innerText = `${count} angezeigt`;
}

async function applyBulkMinViewsFromInput(inputId) {
    const input = document.getElementById(inputId || 'bulk-min-views-input');
    if (!input) return;
    const val = parseInt(input.value, 10);
    if (isNaN(val) || val < 1) {
        alert('Bitte eine gültige Zahl für Mindest-Views eingeben.');
        return;
    }
    if (!confirm(`Sollen die Mindest-Views für ALLE Streamer auf ${val} gesetzt werden?`)) return;
    try {
        await apiFetch('/api/streamers/update-all-views', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ min_clip_views: val })
        });
        showToast(`Mindest-Views für alle Streamer auf ${val} gesetzt!`, 'success');
        refreshDashboard();
    } catch (e) {
        alert('Fehler: ' + e);
    }
}

function openSettingsModal() {
    const m = document.getElementById('settings-modal');
    if (m) {
        m.classList.remove('hidden');
        m.classList.add('flex');
        m.style.setProperty('display', 'flex', 'important');
        loadSettingsIntoForm();
    }
}

function closeSettingsModal() {
    const m = document.getElementById('settings-modal');
    if (m) {
        m.classList.add('hidden');
        m.classList.remove('flex');
        m.style.setProperty('display', 'none', 'important');
    }
}

async function loadSettingsIntoForm() {
    try {
        const resp = await apiFetch('/api/settings');
        const s = await resp.json();
        if (!s) return;
        const form = document.getElementById('settings-form');
        if (!form) return;
        
        if (form.elements['autopilot_enabled']) form.elements['autopilot_enabled'].checked = !!s.enabled;
        if (form.elements['interval_minutes']) form.elements['interval_minutes'].value = s.interval_minutes || 30;
        if (form.elements['time_filter']) form.elements['time_filter'].value = s.time_filter || 'LAST_DAY';
        if (form.elements['fallback_to_week']) form.elements['fallback_to_week'].checked = s.fallback_to_week !== false;
        if (form.elements['auto_render']) form.elements['auto_render'].checked = !!s.auto_render;
        if (form.elements['hardware_encoder']) form.elements['hardware_encoder'].value = s.hardware_encoder || 'auto';
        if (form.elements['whisper_model']) form.elements['whisper_model'].value = s.whisper_model || 'small';
    } catch (e) {
        console.error('Fehler beim Laden der Einstellungen:', e);
    }
}

async function saveSettingsFromForm(e) {
    if (e && e.preventDefault) e.preventDefault();
    const form = document.getElementById('settings-form');
    if (!form) return false;
    
    const payload = {
        enabled: form.elements['autopilot_enabled'] ? form.elements['autopilot_enabled'].checked : true,
        interval_minutes: parseInt(form.elements['interval_minutes'].value, 10) || 30,
        time_filter: form.elements['time_filter'] ? form.elements['time_filter'].value : 'LAST_DAY',
        fallback_to_week: form.elements['fallback_to_week'] ? form.elements['fallback_to_week'].checked : true,
        auto_render: form.elements['auto_render'] ? form.elements['auto_render'].checked : false,
        hardware_encoder: form.elements['hardware_encoder'] ? form.elements['hardware_encoder'].value : 'auto',
        whisper_model: form.elements['whisper_model'] ? form.elements['whisper_model'].value : 'small'
    };
    
    const submitBtn = form.querySelector('button[type="submit"]');
    if (submitBtn) {
        submitBtn.disabled = true;
        submitBtn.classList.add('opacity-70');
    }

    try {
        const resp = await apiFetch('/api/settings', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        const data = await resp.json();
        if (data && data.success) {
            showToast('Einstellungen erfolgreich gespeichert!', 'success');
            closeSettingsModal();
            if (typeof refreshDashboard === 'function') refreshDashboard();
        } else {
            showToast('Fehler: ' + (data?.error || 'Unbekannter Fehler'), 'error');
        }
    } catch (err) {
        showToast('Fehler beim Speichern: ' + err, 'error');
    } finally {
        if (submitBtn) {
            submitBtn.disabled = false;
            submitBtn.classList.remove('opacity-70');
        }
    }
    return false;
}

async function removeStreamer(name) {
    if (!confirm('Streamer ' + name + ' wirklich entfernen?')) return;
    try {
        await apiFetch('/api/streamers/remove/' + encodeURIComponent(name), { method: 'POST' });
        refreshDashboard();
    } catch (e) {
        alert('Fehler: ' + e);
    }
}

async function addStreamerFromForm(form) {
    const fd = new FormData(form);
    const name = (fd.get('name') || '').trim();
    const min_views = parseInt(fd.get('min_views') || '30', 10);
    const max_clips = parseInt(fd.get('max_clips') || '2', 10);
    if (!name) return;
    try {
        await apiFetch('/api/streamers/add', {
            method: 'POST',
            headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
            body: new URLSearchParams({ name, min_views: String(min_views), max_clips: String(max_clips) }).toString()
        });
        form.reset();
        await refreshDashboard();
    } catch (e) {
        alert('Fehler beim Hinzufügen: ' + e);
    }
}

// ----------------------------------------
// INITIALIZATION
// ----------------------------------------
// C7 Audit-Fix: Intelligentes Polling statt Kaskaden-Loops
let gLastDashboardRefresh = 0;

function initDashboard() {
    refreshDashboard();
    // Regelmäßiges Hintergrund-Polling nur alle 15 Sekunden statt alle 5s
    // (Status-Polling alle 1,5s sorgt bereits bei jeder Änderung für sofortige Updates)
    setInterval(() => {
        // Nur pollen wenn nicht gerade vor kurzem refreshed wurde
        if (Date.now() - gLastDashboardRefresh > 12000) {
            refreshDashboard();
        }
    }, 15000);
}

if (document.readyState === 'loading') {
    window.addEventListener('DOMContentLoaded', initDashboard);
} else {
    initDashboard();
}



        function openStreamerModal() {
            switchTab('streamers');
        }

        function closeStreamerModal() {
            const m = document.getElementById('streamer-modal');
            if (m) {
                m.classList.add('hidden');
                m.classList.remove('flex');
                m.style.display = 'none';
            }
        }

        function applyStudioStreamerFilter() {
            document.querySelectorAll('.studio-clip-card').forEach(card => {
                const st = (card.getAttribute('data-streamer') || '').toLowerCase();
                if (selectedStudioStreamers.size === 0 || selectedStudioStreamers.has(st)) {
                    card.classList.remove('hidden');
                } else {
                    card.classList.add('hidden');
                }
            });
        }

        function renderStudioStreamerFilter() {
            renderStreamerAvatarFilterBar({
                barEl: document.getElementById('streamer-pills-container'),
                countsMap: buildStreamerCountsMap(cachedStudioClips),
                totalCount: cachedStudioClips.length,
                selectedSet: selectedStudioStreamers,
                onToggleFnName: 'toggleStudioStreamerFilter',
                onClearFnName: 'clearStudioStreamerFilter'
            });
            applyStudioStreamerFilter();
        }

        function toggleStudioStreamerFilter(streamerKey) {
            const key = String(streamerKey || '').trim().toLowerCase();
            if (!key) return;
            if (selectedStudioStreamers.has(key)) {
                selectedStudioStreamers.delete(key);
            } else {
                selectedStudioStreamers.add(key);
            }
            gLastStudioPillsSig = '';
            renderStudioStreamerFilter();
        }

        function clearStudioStreamerFilter() {
            selectedStudioStreamers.clear();
            gLastStudioPillsSig = '';
            renderStudioStreamerFilter();
        }

        function filterStudioByStreamer(streamerName) {
            const key = String(streamerName || '').trim().toLowerCase();
            if (!key || key === 'all') {
                clearStudioStreamerFilter();
            } else {
                toggleStudioStreamerFilter(key);
            }
        }

        async function toggleManualPublished(clipId, isChecked) {
            const card = document.getElementById('card-' + clipId);
            const label = document.getElementById('pub-label-' + clipId);
            
            if (isChecked) {
                card.classList.add('opacity-40', 'grayscale', 'hover:grayscale-0', 'hover:opacity-95', 'border-emerald-900/80', 'bg-slate-950/90');
                if (label) {
                    label.innerText = '✓ Veröffentlicht';
                    label.className = 'text-xs font-bold text-emerald-400';
                }
            } else {
                card.classList.remove('opacity-40', 'grayscale', 'hover:grayscale-0', 'hover:opacity-95', 'border-emerald-900/80', 'bg-slate-950/90');
                if (label) {
                    label.innerText = 'Veröffentlicht?';
                    label.className = 'text-xs font-bold text-slate-400';
                }
            }

            try {
                await apiFetch('/api/clip/' + clipId + '/toggle-published', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ is_published: isChecked })
                });
            } catch (e) {
                console.error('Fehler beim Aktualisieren des Veröffentlichungs-Status:', e);
            }
        }
        function switchTab(tabId) {
            if (!tabId) return;
            try {
                localStorage.setItem('clip_farming_active_tab', tabId);
            } catch(e) {}
            document.querySelectorAll('.tab-content').forEach(el => {
                el.classList.add('hidden');
                el.style.display = 'none';
            });
            document.querySelectorAll('.tab-btn').forEach(el => {
                el.classList.remove('active', 'text-amber-400');
                el.classList.add('text-slate-400');
            });
            
            const target = document.getElementById('tab-' + tabId);
            if (target) {
                target.classList.remove('hidden');
                target.style.display = 'block';
            }
            const btn = document.getElementById('tab-' + tabId + '-btn');
            if (btn) {
                btn.classList.add('active', 'text-amber-400');
                btn.classList.remove('text-slate-400');
            }
        }
        (function restoreActiveTabOnLoad() {
            function applySavedTab() {
                try {
                    const urlParams = new URLSearchParams(window.location.search);
                    const tabFromUrl = urlParams.get('tab') || window.location.hash.replace('#', '');
                    const savedTab = tabFromUrl || localStorage.getItem('clip_farming_active_tab');
                    if (savedTab && document.getElementById('tab-' + savedTab)) {
                        switchTab(savedTab);
                    }
                } catch(e) {}
            }
            if (document.readyState === 'loading') {
                document.addEventListener('DOMContentLoaded', applySavedTab);
            } else {
                applySavedTab();
            }
        })();

        var currentPreviewClipId = '';
        var currentPreviewStreamer = '';
        var currentPreviewTitle = '';

        function openRawPreview(clipId, streamer, title, views, duration, createdAgo = '', createdFull = '') {
            currentPreviewClipId = clipId;
            currentPreviewStreamer = streamer;
            currentPreviewTitle = title;
            const sEl = document.getElementById('modal-streamer');
            if (sEl) sEl.innerText = (streamer || '').toUpperCase();
            const tEl = document.getElementById('modal-title');
            if (tEl) tEl.innerText = title || '';
            let statsText = (views || 0) + ' Views • ' + (duration || 0) + 's (Rohdatei auf Festplatte)';
            if (createdAgo) {
                statsText += ' • Erstellt: ' + createdAgo;
            }
            const statsElem = document.getElementById('modal-stats');
            if (statsElem) {
                statsElem.innerText = statsText;
                if (createdFull) {
                    statsElem.title = createdFull;
                }
            }
            
            const player = document.getElementById('modal-video-player');
            if (player) {
                player.poster = getBackendUrl('/thumbnail/' + clipId);
                player.src = getBackendUrl('/raw-video/' + clipId);
                player.load();
                player.play().catch(() => {});
            }

            const procForm = document.getElementById('modal-process-form');
            if (procForm) procForm.action = '/process-one/' + clipId;
            const delForm = document.getElementById('modal-delete-form');
            if (delForm) delForm.action = '/queue/delete/' + clipId;
            const dlRaw = document.getElementById('modal-download-raw');
            if (dlRaw) {
                dlRaw.onclick = (e) => downloadRawVideo(clipId, dlRaw, e);
            }
            
            const modal = document.getElementById('preview-modal');
            if (modal) {
                modal.classList.remove('hidden');
                modal.classList.add('flex');
                modal.style.display = 'flex';
            }
        }

        function closePreviewModal() {
            const player = document.getElementById('modal-video-player');
            if (player) {
                player.pause();
                player.src = '';
            }
            const modal = document.getElementById('preview-modal');
            if (modal) {
                modal.classList.add('hidden');
                modal.classList.remove('flex');
                modal.style.display = 'none';
            }
        }

        let logsOpen = true;
        function toggleLogs() {
            logsOpen = !logsOpen;
            const box = document.getElementById('log-box');
            const icon = document.getElementById('log-toggle-icon');
            if (logsOpen) {
                box.classList.remove('hidden');
                icon.innerText = '▲ Verbergen';
            } else {
                box.classList.add('hidden');
                icon.innerText = '▼ Anzeigen';
            }
        }

let gPrevRunning = false;
let gPrevTaskStatus = '';

function showToast(message, type = 'info') {
    let toast = document.getElementById('ui-toast');
    if (!toast) {
        toast = document.createElement('div');
        toast.id = 'ui-toast';
        document.body.appendChild(toast);
    }

    let borderCls = 'border-zinc-700 bg-zinc-900/95 text-zinc-200';
    let iconSvg = '<svg class="w-4 h-4 text-amber-400 inline-block shrink-0" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/></svg>';

    if (type === 'success') {
        borderCls = 'border-emerald-800 bg-emerald-950/95 text-emerald-100';
        iconSvg = '<svg class="w-4 h-4 text-emerald-400 inline-block shrink-0" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M5 13l4 4L19 7"/></svg>';
    } else if (type === 'error') {
        borderCls = 'border-rose-800 bg-rose-950/95 text-rose-100';
        iconSvg = '<svg class="w-4 h-4 text-rose-400 inline-block shrink-0" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/></svg>';
    }

    toast.className = `fixed bottom-5 right-5 z-50 max-w-sm px-4 py-3 rounded-lg border ${borderCls} shadow-lg text-xs font-medium flex items-center gap-2.5 transition-opacity duration-200`;
    toast.innerHTML = `${iconSvg} <span>${escapeHtml(message)}</span>`;
    toast.style.display = 'flex';
    toast.style.opacity = '1';

    clearTimeout(window._toastTimeout);
    window._toastTimeout = setTimeout(() => {
        toast.style.opacity = '0';
        setTimeout(() => { toast.style.display = 'none'; }, 200);
    }, 4000);
}

async function downloadShortVideo(clipId, btn, evt) {
    if (!clipId) return;
    const isQuick = evt && evt.shiftKey;
    const origHtml = btn ? btn.innerHTML : '';
    if (btn) {
        btn.disabled = true;
        btn.innerHTML = '<span class="inline-block w-3 h-3 border-2 border-slate-300 border-t-transparent rounded-full animate-spin mr-1"></span> <span>' + (isQuick ? 'Speichere...' : 'Öffne...') + '</span>';
    }
    if (isQuick) {
        showToast('Exportiere HQ Video direkt in Downloads...', 'info');
    } else {
        showToast('Speicherort wählen... (Windows-Dialog geöffnet)', 'info');
    }
    try {
        const endpoint = isQuick
            ? '/api/clip/' + encodeURIComponent(clipId) + '/export-to-downloads'
            : '/api/clip/' + encodeURIComponent(clipId) + '/export-dialog';
        const res = await apiFetch(endpoint, {
            method: 'POST',
            headers: { 'Accept': 'application/json' }
        });
        const data = await res.json();
        if (data && data.success) {
            showToast('✓ Video gespeichert: ' + data.filename, 'success');
        } else if (data && data.cancelled) {
            showToast('Speichern abgebrochen', 'info');
        } else {
            const err = (data && data.error) ? data.error : 'Konnte Speicher-Dialog nicht öffnen.';
            showToast('Fehler: ' + err, 'error');
            console.error('Export error:', data);
        }
    } catch (err) {
        console.warn('Export endpoint error:', err);
        showToast('Fehler beim Exportieren: ' + err, 'error');
    } finally {
        if (btn) {
            btn.disabled = false;
            btn.innerHTML = origHtml;
        }
    }
}

async function downloadRawVideo(clipId, btn, evt) {
    if (!clipId) return;
    const isQuick = evt && evt.shiftKey;
    const origHtml = btn ? btn.innerHTML : '';
    if (btn) {
        btn.disabled = true;
        btn.innerHTML = '<span class="inline-block w-3 h-3 border-2 border-slate-300 border-t-transparent rounded-full animate-spin mr-1"></span> <span>' + (isQuick ? 'Speichere...' : 'Öffne...') + '</span>';
    }
    if (isQuick) {
        showToast('Exportiere Rohdatei direkt in Downloads...', 'info');
    } else {
        showToast('Speicherort wählen... (Windows-Dialog geöffnet)', 'info');
    }
    try {
        const endpoint = isQuick
            ? '/api/clip/' + encodeURIComponent(clipId) + '/export-raw-to-downloads'
            : '/api/clip/' + encodeURIComponent(clipId) + '/export-raw-dialog';
        const res = await apiFetch(endpoint, {
            method: 'POST',
            headers: { 'Accept': 'application/json' }
        });
        const data = await res.json();
        if (data && data.success) {
            showToast('✓ Rohdatei gespeichert: ' + data.filename, 'success');
        } else if (data && data.cancelled) {
            showToast('Speichern abgebrochen', 'info');
        } else {
            const err = (data && data.error) ? data.error : 'Konnte Speicher-Dialog nicht öffnen.';
            showToast('Fehler: ' + err, 'error');
            console.error('Export raw error:', data);
        }
    } catch (err) {
        console.warn('Export raw endpoint error:', err);
        showToast('Fehler beim Exportieren: ' + err, 'error');
    } finally {
        if (btn) {
            btn.disabled = false;
            btn.innerHTML = origHtml;
        }
    }
}

        async function triggerRun() {
            const btn = document.getElementById('btn-trigger');
            const dot = document.getElementById('live-dot');
            const text = document.getElementById('live-status-text');
            const desc = document.getElementById('live-task-desc');

            if (btn) {
                btn.disabled = true;
                btn.className = 'flex items-center gap-2 px-5 py-2.5 bg-zinc-800 text-zinc-400 font-semibold text-xs rounded cursor-not-allowed';
                btn.innerHTML = '<svg class="w-4 h-4 inline-block -mt-0.5 animate-spin" fill="none" stroke="currentColor" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z"></path></svg> Suche läuft auf Twitch...';
            }

            if (dot) dot.className = 'w-2 h-2 rounded-full bg-emerald-400 animate-ping';
            if (text) text.innerText = 'Aktiv: CLIPS SUCHEN';
            if (desc) desc.innerText = 'Starte Twitch-Scan für alle aktiven Streamer...';

            showToast('Twitch-Suche gestartet! Streamer werden nach neuen Clips durchsucht.', 'info');

            try {
                const res = await apiFetch('/api/run', { method: 'POST' });
                const data = await res.json();
                if (data && data.success === false) {
                    showToast(data.message || 'Pipeline läuft bereits!', 'info');
                } else {
                    showToast('Twitch-Scan läuft im Hintergrund. Gefundene Clips erscheinen live.', 'success');
                }
                await updateStatus();
            } catch (e) {
                console.error('Trigger run failed:', e);
                showToast('Fehler beim Starten der Suche: ' + e, 'error');
                if (btn) {
                    btn.disabled = false;
                    btn.className = 'flex items-center gap-2 px-5 py-2.5 bg-amber-500 hover:bg-amber-400 font-semibold text-xs rounded transition text-zinc-950 shadow-sm';
                    btn.innerHTML = SVG_ICONS.scan + ' Neue Clips auf Twitch suchen';
                }
            }
        }

        async function processAll() {
            const btn = document.getElementById('btn-process-all');
            if (btn) {
                btn.disabled = true;
                btn.innerHTML = '<span class="inline-block w-3.5 h-3.5 border-2 border-zinc-950 border-t-transparent rounded-full animate-spin mr-1.5"></span> <span>Schneide alle Clips...</span>';
            }
            try {
                await apiFetch('/api/process-all', { method: 'POST' });
                switchTab('studio');
                updateStatus();
            } catch (e) {
                console.error(e);
                alert('Fehler: ' + e);
            } finally {
                if (btn) {
                    btn.disabled = false;
                    btn.innerHTML = SVG_ICONS.scan + ' Alle Warteschlangen-Clips ins Studio übernehmen';
                }
            }
        }

        async function updateStatus() {
            try {
                const res = await apiFetch('/api/status');
                const data = await res.json();
                
                const dot = document.getElementById('live-dot');
                const text = document.getElementById('live-status-text');
                const desc = document.getElementById('live-task-desc');
                const btn = document.getElementById('btn-trigger');

                // Render Progress Card
                const progressCard = document.getElementById('render-progress-card');
                const progressBar = document.getElementById('render-progress-bar');
                const progressPercent = document.getElementById('render-percent-text');
                const progressEta = document.getElementById('render-eta-text');
                const progressSpeed = document.getElementById('render-speed-badge');
                const progressTitle = document.getElementById('render-progress-title');

                if (data.is_running) {
                    dot.className = 'w-2 h-2 rounded-full bg-emerald-400 animate-ping';
                    text.innerText = 'Aktiv: ' + (data.status || 'ARBEITET').toUpperCase();
                    desc.innerText = (data.current_task || '') + (data.streamer ? ' (' + data.streamer + ')' : '');
                    if (btn) {
                        btn.disabled = true;
                        btn.className = 'flex items-center gap-2 px-5 py-2.5 bg-zinc-800 text-zinc-400 font-semibold text-xs rounded cursor-not-allowed';
                        if (data.status === 'harvesting') {
                            btn.innerHTML = '<svg class="w-4 h-4 inline-block -mt-0.5 animate-spin" fill="none" stroke="currentColor" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z"></path></svg> Suche läuft auf Twitch...';
                        }
                    }

                    // Render Fortschritt einblenden
                    if (data.status === 'rendering' || data.progress_percent > 0) {
                        progressCard.classList.remove('hidden');
                        progressBar.style.width = data.progress_percent + '%';
                        progressPercent.innerText = data.progress_percent + '%';
                        
                        if (data.eta_seconds !== null && data.eta_seconds !== undefined) {
                            progressEta.innerText = 'Noch ca. ' + data.eta_seconds + 's';
                        } else {
                            progressEta.innerText = 'Berechne...';
                        }

                        if (data.speed) {
                            progressSpeed.innerText = data.speed + ' NVENC';
                        }
                        progressTitle.innerText = data.current_task || 'Rendere Video...';
                    } else {
                        progressCard.classList.add('hidden');
                    }
                } else {
                    dot.className = 'w-2 h-2 rounded-full bg-slate-400';
                    text.innerText = 'Standby';
                    desc.innerText = data.current_task || 'Bereit zur Ausführung';
                    progressCard.classList.add('hidden');
                    if (btn) {
                        btn.disabled = false;
                        btn.className = 'flex items-center gap-2 px-5 py-2.5 bg-amber-500 hover:bg-amber-400 font-semibold text-xs rounded transition text-zinc-950 shadow-sm';
                        btn.innerHTML = SVG_ICONS.scan + ' Neue Clips auf Twitch suchen';
                    }

                    // Transition from running -> idle
                    if (gPrevRunning) {
                        if (gPrevTaskStatus === 'rendering') {
                            showToast('Rendering fertiggestellt! Neues Video & Vorschaubild geladen.', 'success');
                        } else {
                            showToast('Aktion abgeschlossen! Dashboard aktualisiert.', 'success');
                        }
                        refreshDashboard();
                    }
                }

                gPrevRunning = data.is_running;
                if (data.is_running) {
                    gPrevTaskStatus = data.status || '';
                }

                if (data.logs && data.logs.length > 0) {
                    document.getElementById('log-count').innerText = data.logs.length + ' Einträge';
                    const logBox = document.getElementById('log-box');
                    logBox.innerHTML = data.logs.slice(-30).map(l => '<div>' + escapeHtml(l) + '</div>').join('');
                    if (logsOpen) {
                        logBox.scrollTop = logBox.scrollHeight;
                    }
                }
            } catch (err) {
                console.error('Polling error:', err);
            }
        }

        // --- VISUELLER ZUSCHNITT & CROPPER ---
        var currentCropClipId = null;
        var currentCropTitle = '';
        var currentCropStreamer = '';
        var currentCropMode = 'split'; // 'split' oder 'single_916'
        var videoNativeWidth = 1920;
        var videoNativeHeight = 1080;
        var cropState = {
            cam: { x: 0.73, y: 0.64, w: 0.26, h: 0.34, enabled: true },
            game: { x: 0.245, y: 0.0, w: 0.51, h: 1.0, enabled: true },
            single: { x: (1 - (608 / 1920)) / 2, y: 0.0, w: 608 / 1920, h: 1.0, enabled: true }
        };
        var activeCropDrag = null;
        var cropVideoInitialized = false;

        function switchCropMode(mode) {
            currentCropMode = mode;
            const btnSplit = document.getElementById('btn-mode-split');
            const btnSingle = document.getElementById('btn-mode-single');
            const tbSplit = document.getElementById('toolbar-split');
            const tbSingle = document.getElementById('toolbar-single');
            const boxCam = document.getElementById('crop-box-cam');
            const boxGame = document.getElementById('crop-box-game');
            const boxSingle = document.getElementById('crop-box-single');
            const btnToggleCam = document.getElementById('btn-crop-toggle-cam');

            if (mode === 'single_916') {
                if (btnSplit) {
                    btnSplit.className = 'flex-1 py-1.5 px-3 rounded text-xs font-medium transition flex items-center justify-center gap-2 bg-zinc-900 hover:bg-zinc-800 text-zinc-400 border border-zinc-800';
                }
                if (btnSingle) {
                    btnSingle.className = 'flex-1 py-1.5 px-3 rounded text-xs font-semibold transition flex items-center justify-center gap-2 bg-emerald-900/90 text-emerald-100 border border-emerald-500 shadow';
                }
                if (tbSplit) {
                    tbSplit.classList.add('hidden');
                    tbSplit.style.display = 'none';
                }
                if (tbSingle) {
                    tbSingle.classList.remove('hidden');
                    tbSingle.style.display = 'flex';
                }
                if (boxCam) boxCam.style.display = 'none';
                if (boxGame) boxGame.style.display = 'none';
                if (boxSingle) boxSingle.style.display = 'flex';
                if (btnToggleCam) {
                    btnToggleCam.innerText = 'Facecam wieder aktivieren';
                    btnToggleCam.className = 'px-2.5 py-1 bg-emerald-900/80 hover:bg-emerald-800 border border-emerald-500 text-xs font-bold rounded text-emerald-200 transition';
                }
                updateBoxDom('single');
            } else {
                if (btnSplit) {
                    btnSplit.className = 'flex-1 py-1.5 px-3 rounded text-xs font-semibold transition flex items-center justify-center gap-2 bg-zinc-700 text-zinc-100 border border-zinc-600';
                }
                if (btnSingle) {
                    btnSingle.className = 'flex-1 py-1.5 px-3 rounded text-xs font-medium transition flex items-center justify-center gap-2 bg-zinc-900 hover:bg-zinc-800 text-zinc-400 border border-zinc-800';
                }
                if (tbSplit) {
                    tbSplit.classList.remove('hidden');
                    tbSplit.style.display = 'block';
                }
                if (tbSingle) {
                    tbSingle.classList.add('hidden');
                    tbSingle.style.display = 'none';
                }
                if (boxCam) boxCam.style.display = 'flex';
                if (boxGame) boxGame.style.display = 'flex';
                if (boxSingle) boxSingle.style.display = 'none';
                if (btnToggleCam) {
                    btnToggleCam.innerText = 'Keine Cam (Vollbild / 1 Rahmen)';
                    btnToggleCam.className = 'px-2.5 py-1 bg-slate-800 hover:bg-rose-900/60 border border-slate-700 text-xs rounded text-slate-300 transition';
                }
                updateBoxDom('cam');
                updateBoxDom('game');
            }
            draw916Preview();
        }

        function toggleCamEnabled() {
            if (currentCropMode === 'single_916') {
                switchCropMode('split');
            } else {
                switchCropMode('single_916');
            }
        }
        window.toggleCamEnabled = toggleCamEnabled;

        var cropFallbackImg = new Image();

        async function openCropModal(clipId, streamer, title) {
            currentCropClipId = clipId;
            currentCropStreamer = streamer || '';
            currentCropTitle = title || '';

            const badge = document.getElementById('crop-modal-clip-badge');
            if (badge) badge.innerText = (streamer ? streamer + ': ' : '') + (title ? title.slice(0, 28) : clipId);

            const cachedClip = (cachedStudioClips || []).find(c => c.clip_id === clipId);
            const cardTitleEl = document.querySelector(`#form-${clipId} input[name="title"]`);
            const modalTitleInput = document.getElementById('crop-title-input');
            const modalStickerInput = document.getElementById('crop-sticker-text-input');
            const modalSubPosSelect = document.getElementById('crop-sub-position-select');
            const modalLayoutSelect = document.getElementById('crop-layout-mode-select');
            const modalFilterSelect = document.getElementById('crop-cam-filter-select');
            const modalTranscriptEl = document.getElementById('crop-transcript-textarea');

            if (modalTitleInput) modalTitleInput.value = (cardTitleEl ? cardTitleEl.value : '') || (cachedClip ? cachedClip.title : '') || title || '';
            if (modalStickerInput) modalStickerInput.value = (cachedClip && cachedClip.sticker_text) ? cachedClip.sticker_text : '';
            if (modalSubPosSelect) modalSubPosSelect.value = (cachedClip && cachedClip.sub_position) ? cachedClip.sub_position : 'bottom';
            if (modalLayoutSelect) modalLayoutSelect.value = (cachedClip && cachedClip.layout_mode) ? cachedClip.layout_mode : 'auto';
            if (modalFilterSelect) modalFilterSelect.value = (cachedClip && cachedClip.cam_filter) ? cachedClip.cam_filter : 'none';
            if (modalTranscriptEl) modalTranscriptEl.value = (cachedClip && cachedClip.transcript) ? cachedClip.transcript : '';

            const modal = document.getElementById('crop-modal');
            if (modal) {
                modal.classList.remove('hidden');
                modal.classList.add('flex');
                modal.style.display = 'flex';
            }

            // Sync visual boxes immediately so they are never at (0, 0)
            updateBoxDom('cam');
            updateBoxDom('game');
            updateBoxDom('single');

            // 1. Preload 16:9 frame into stage image
            const stageImg = document.getElementById('crop-stage-img');
            if (stageImg) {
                stageImg.src = getBackendUrl('/thumbnail/raw/' + encodeURIComponent(clipId) + '?t=' + Date.now());
                stageImg.onload = () => draw916Preview();
            }

            // 2. Preload thumbnail into fallback image for instant canvas rendering
            cropFallbackImg.src = getBackendUrl('/thumbnail/raw/' + encodeURIComponent(clipId) + '?t=' + Date.now());
            cropFallbackImg.onload = () => {
                draw916Preview();
            };

            const vid = document.getElementById('crop-stage-video');
            if (vid) {
                vid.poster = getBackendUrl('/thumbnail/raw/' + encodeURIComponent(clipId));
                vid.muted = true;
                vid.src = getBackendUrl('/raw-video/' + encodeURIComponent(clipId));
                vid.onloadedmetadata = () => {
                    try {
                        vid.currentTime = Math.min(0.5, (vid.duration || 1) / 2);
                    } catch(e) {}
                    draw916Preview();
                };
                vid.onseeked = () => {
                    draw916Preview();
                };
                vid.load();
            }

            // Default Box States: Feste Seitenverhältnisse (3:2 für Cam, 9:10 für Gameplay, 9:16 für Single)
            cropState.cam = {
                x: 1 - (540 / 1920) - 0.02,
                y: 1 - (360 / 1080) - 0.03,
                w: 540 / 1920,
                h: 360 / 1080,
                enabled: true
            };
            cropState.game = {
                x: (1 - (972 / 1920)) / 2,
                y: 0.0,
                w: 972 / 1920,
                h: 1.0,
                enabled: true
            };
            cropState.single = {
                x: (1 - (608 / 1920)) / 2,
                y: 0.0,
                w: 608 / 1920,
                h: 1.0,
                enabled: true
            };
            currentCropMode = 'split';

            // Saved metadata abrufen falls vorhanden
            try {
                const resp = await apiFetch(`/api/clip/${clipId}/meta`);
                const meta = await resp.json();
                if (meta) {
                    if (meta.layout_mode === 'single_916' || (meta.custom_crops && meta.custom_crops.mode === 'single_916')) {
                        currentCropMode = 'single_916';
                        if (meta.custom_crops) {
                            const s = meta.custom_crops.single || meta.custom_crops.single_916;
                            if (s) {
                                if (s.x_pct !== undefined) cropState.single.x = s.x_pct;
                                else if (s.x !== undefined) cropState.single.x = s.x / (meta.video_w || 1920);
                            }
                        }
                    } else if (meta.custom_crops && meta.custom_crops.cam) {
                        currentCropMode = 'split';
                        const c = meta.custom_crops.cam;
                        const g = meta.custom_crops.game;
                        if (c.w_pct) {
                            cropState.cam.w = c.w_pct;
                            cropState.cam.h = c.h_pct;
                        }
                        cropState.cam.x = c.x_pct !== undefined ? c.x_pct : (c.x / (meta.video_w || 1920));
                        cropState.cam.y = c.y_pct !== undefined ? c.y_pct : (c.y / (meta.video_h || 1080));
                        cropState.cam.enabled = c.enabled !== false;

                        if (g) {
                            if (g.w_pct) {
                                cropState.game.w = g.w_pct;
                                cropState.game.h = g.h_pct || (g.w_pct * ((meta.video_w || 1920) / (meta.video_h || 1080)) * (10 / 9));
                            }
                            cropState.game.x = g.x_pct !== undefined ? g.x_pct : (g.x / (meta.video_w || 1920));
                            cropState.game.y = g.y_pct !== undefined ? g.y_pct : 0.0;
                        }
                    }
                    if (meta.title) {
                        currentCropTitle = meta.title;
                        if (modalTitleInput && !cardTitleEl) modalTitleInput.value = meta.title;
                    }
                    if (modalStickerInput && meta.sticker_text !== undefined) {
                        modalStickerInput.value = meta.sticker_text || '';
                    }
                    if (modalSubPosSelect && meta.sub_position) {
                        modalSubPosSelect.value = meta.sub_position;
                    }
                    if (modalLayoutSelect && meta.layout_mode) {
                        modalLayoutSelect.value = meta.layout_mode;
                    }
                    if (meta.cam_filter && modalFilterSelect) {
                        modalFilterSelect.value = meta.cam_filter;
                    }
                    if (modalTranscriptEl && typeof meta.transcript === 'string') {
                        modalTranscriptEl.value = meta.transcript;
                    }
                }
            } catch (e) {
                console.warn('Keine vorherigen Zuschnitt-Metadaten geladen:', e);
            }

            // Sync Cam & Game Größen-Regler
            const curWpx = Math.round(cropState.cam.w * (videoNativeWidth || 1920));
            const curHpx = Math.round(curWpx * (2 / 3));
            syncCamSizeUi(curWpx, curHpx);

            const isVollbild = isGameplayVollbild();
            const curGW = Math.round(cropState.game.w * (videoNativeWidth || 1920));
            const curGH = Math.round(curGW * (isVollbild ? (16 / 9) : (10 / 9)));
            syncGameSizeUi(curGW, curGH);

            switchCropMode(currentCropMode);
            updateBoxDom('cam');
            updateBoxDom('game');
            updateBoxDom('single');

            if (!cropVideoInitialized) {
                initCropInteractions();
                initCropVideoListeners();
                cropVideoInitialized = true;
            }
        }

        function closeCropModal() {
            const vid = document.getElementById('crop-stage-video');
            if (vid) {
                vid.pause();
                vid.src = '';
            }
            const modal = document.getElementById('crop-modal');
            if (modal) {
                modal.classList.add('hidden');
                modal.classList.remove('flex');
                modal.style.display = 'none';
            }
        }

        function initCropVideoListeners() {
            const vid = document.getElementById('crop-stage-video');
            const slider = document.getElementById('crop-time-slider');
            const timeDisp = document.getElementById('crop-time-display');

            vid.addEventListener('loadedmetadata', () => {
                videoNativeWidth = vid.videoWidth || 1920;
                videoNativeHeight = vid.videoHeight || 1080;
                slider.max = vid.duration || 30;
                vid.currentTime = Math.min(2.0, (vid.duration || 10) * 0.1);

                // Sync Cam & Game Größen-Regler
                const curWpx = Math.round(cropState.cam.w * videoNativeWidth);
                const curHpx = Math.round(curWpx * (2 / 3));
                syncCamSizeUi(curWpx, curHpx);

                const isVollbild = isGameplayVollbild();
                const curGW = Math.round(cropState.game.w * videoNativeWidth);
                const curGH = Math.round(curGW * (isVollbild ? (16 / 9) : (10 / 9)));
                syncGameSizeUi(curGW, curGH);

                updateBoxDom('cam');
                updateBoxDom('game');
                updateBoxDom('single');
                draw916Preview();
            });

            vid.addEventListener('timeupdate', () => {
                slider.value = vid.currentTime;
                const cur = formatTime(vid.currentTime);
                const tot = formatTime(vid.duration || 0);
                timeDisp.innerText = `${cur} / ${tot}`;
                draw916Preview();
            });

            vid.addEventListener('seeked', draw916Preview);
            vid.addEventListener('play', () => {
                document.getElementById('crop-play-btn').innerHTML = 'Pause';
            });
            vid.addEventListener('pause', () => {
                document.getElementById('crop-play-btn').innerHTML = 'Abspielen';
            });
        }

        function formatTime(sec) {
            const m = Math.floor(sec / 60);
            const s = Math.floor(sec % 60);
            return `${m < 10 ? '0' : ''}${m}:${s < 10 ? '0' : ''}${s}`;
        }

        function toggleCropVideoPlay() {
            const vid = document.getElementById('crop-stage-video');
            if (vid.paused) vid.play(); else vid.pause();
        }

        function seekCropVideo(delta) {
            const vid = document.getElementById('crop-stage-video');
            vid.currentTime = Math.max(0, Math.min(vid.duration || 60, vid.currentTime + delta));
        }

        function onCropSliderInput(val) {
            const vid = document.getElementById('crop-stage-video');
            vid.currentTime = parseFloat(val);
        }

        function setCamPixelWidth(widthPx) {
            const vw = videoNativeWidth || 1920;
            const vh = videoNativeHeight || 1080;
            const maxAllowedW = Math.min(vw, Math.floor(vh * 1.5));
            const clampedW = Math.max(160, Math.min(maxAllowedW, Math.round(parseFloat(widthPx))));
            const clampedH = Math.round(clampedW * (2 / 3));

            const newW = clampedW / vw;
            const newH = clampedH / vh;

            // Mittelpunkt stabil halten
            const centerX = cropState.cam.x + (cropState.cam.w / 2);
            const centerY = cropState.cam.y + (cropState.cam.h / 2);

            cropState.cam.w = newW;
            cropState.cam.h = newH;
            cropState.cam.x = Math.max(0, Math.min(1 - newW, centerX - (newW / 2)));
            cropState.cam.y = Math.max(0, Math.min(1 - newH, centerY - (newH / 2)));

            syncCamSizeUi(clampedW, clampedH);
            updateBoxDom('cam');
            draw916Preview();
        }

        function syncCamSizeUi(w_px, h_px) {
            const slider = document.getElementById('crop-cam-size-slider');
            const disp = document.getElementById('crop-cam-size-display');
            if (slider && document.activeElement !== slider) slider.value = w_px;
            if (disp) disp.innerText = `${w_px} x ${h_px} px`;

            const bNormal = document.getElementById('btn-size-normal');
            const bSmall = document.getElementById('btn-size-small');
            const bLarge = document.getElementById('btn-size-large');
            const actCls = 'px-2 py-0.5 bg-emerald-900/80 border border-emerald-500 text-2xs font-bold rounded text-emerald-200 shadow transition';
            const inactCls = 'px-2 py-0.5 bg-slate-800 hover:bg-emerald-900/50 border border-slate-700 hover:border-emerald-500 text-2xs rounded text-slate-200 transition';
            if (bNormal) bNormal.className = (w_px === 540) ? actCls : inactCls;
            if (bSmall) bSmall.className = (w_px === 420) ? actCls : inactCls;
            if (bLarge) bLarge.className = (w_px === 680) ? actCls : inactCls;
        }

        function setCamSize(size) {
            if (size === 'small') setCamPixelWidth(420);
            else if (size === 'large') setCamPixelWidth(680);
            else setCamPixelWidth(540);
        }

        function isGameplayVollbild() {
            return currentCropMode === 'single_916' || !cropState.cam.enabled;
        }

        function setGamePixelWidth(widthPx) {
            const vw = videoNativeWidth || 1920;
            const vh = videoNativeHeight || 1080;
            const isVollbild = isGameplayVollbild();

            // Format-Wahl: 
            // Mit Cam -> 9:10 (Höhe = Breite * 10 / 9)
            // Keine Cam / Vollbild -> 9:16 (Höhe = Breite * 16 / 9)
            const ratioW = 9;
            const ratioH = isVollbild ? 16 : 10;

            const maxAllowedW = Math.min(vw, Math.floor(vh * (ratioW / ratioH)));
            const minAllowedW = isVollbild ? 200 : 320;
            const clampedW = Math.max(minAllowedW, Math.min(maxAllowedW, Math.round(parseFloat(widthPx))));
            const clampedH = Math.round(clampedW * (ratioH / ratioW));

            const newW = clampedW / vw;
            const newH = clampedH / vh;

            // Mittelpunkt beibehalten beim Zoomen/Skalieren
            const centerX = cropState.game.x + (cropState.game.w / 2);
            const centerY = cropState.game.y + (cropState.game.h / 2);

            cropState.game.w = newW;
            cropState.game.h = newH;
            cropState.game.x = Math.max(0, Math.min(1 - newW, centerX - (newW / 2)));
            cropState.game.y = Math.max(0, Math.min(1 - newH, centerY - (newH / 2)));

            syncGameSizeUi(clampedW, clampedH);
            updateBoxDom('game');
            draw916Preview();
        }

        function syncGameSizeUi(w_px, h_px) {
            const isVollbild = isGameplayVollbild();
            const vw = videoNativeWidth || 1920;
            const vh = videoNativeHeight || 1080;

            const slider = document.getElementById('crop-game-size-slider');
            const disp = document.getElementById('crop-game-size-display');
            const badge = document.getElementById('crop-game-format-badge');
            const hint = document.getElementById('crop-game-hint-text');

            const bMax = document.getElementById('btn-game-size-max');
            const bMed = document.getElementById('btn-game-size-medium');
            const bSmall = document.getElementById('btn-game-size-small');

            const actCls = 'px-2 py-0.5 bg-sky-900/80 border border-sky-500 text-2xs font-bold rounded text-sky-200 shadow transition';
            const inactCls = 'px-2 py-0.5 bg-slate-800 hover:bg-sky-900/50 border border-slate-700 hover:border-sky-500 text-2xs rounded text-slate-200 transition';

            if (isVollbild) {
                const maxW = Math.min(vw, Math.floor(vh * (9 / 16))); // 608 auf 1080p
                const medW = Math.round(maxW * 0.833); // 506px
                const zoomW = Math.round(maxW * 0.667); // 405px

                if (slider) {
                    slider.min = 200;
                    slider.max = maxW;
                    if (document.activeElement !== slider) slider.value = w_px;
                }
                if (badge) badge.innerText = '(Festes 9:16 Vollbild)';
                if (hint) hint.innerText = '9:16 fest (Vollbild) • Mausrad / Ecken ziehen';

                if (bSmall) {
                    bSmall.innerText = `Zoom (${zoomW}px)`;
                    bSmall.onclick = () => setGamePixelWidth(zoomW);
                    bSmall.className = (Math.abs(w_px - zoomW) <= 5) ? actCls : inactCls;
                }
                if (bMed) {
                    bMed.innerText = `Mittel (${medW}px)`;
                    bMed.onclick = () => setGamePixelWidth(medW);
                    bMed.className = (Math.abs(w_px - medW) <= 5) ? actCls : inactCls;
                }
                if (bMax) {
                    bMax.innerText = `Voll (${maxW}px)`;
                    bMax.onclick = () => setGamePixelWidth(maxW);
                    bMax.className = (Math.abs(w_px - maxW) <= 5) ? actCls : inactCls;
                }
            } else {
                const maxW = Math.min(vw, Math.floor(vh * 0.9)); // 972 auf 1080p
                const medW = 810;
                const zoomW = 648;

                if (slider) {
                    slider.min = 320;
                    slider.max = maxW;
                    if (document.activeElement !== slider) slider.value = w_px;
                }
                if (badge) badge.innerText = '(Festes 9:10 Format)';
                if (hint) hint.innerText = '9:10 fest (Split) • Mausrad / Ecken ziehen';

                if (bSmall) {
                    bSmall.innerText = 'Zoom (648px)';
                    bSmall.onclick = () => setGamePixelWidth(648);
                    bSmall.className = (Math.abs(w_px - 648) <= 5) ? actCls : inactCls;
                }
                if (bMed) {
                    bMed.innerText = 'Mittel (810px)';
                    bMed.onclick = () => setGamePixelWidth(810);
                    bMed.className = (Math.abs(w_px - 810) <= 5) ? actCls : inactCls;
                }
                if (bMax) {
                    bMax.innerText = `Voll (${maxW}px)`;
                    bMax.onclick = () => setGamePixelWidth(maxW);
                    bMax.className = (Math.abs(w_px - maxW) <= 5) ? actCls : inactCls;
                }
            }

            if (disp) disp.innerText = `${w_px} x ${h_px} px`;
        }

        function updateBoxDom(type) {
            const box = document.getElementById('crop-box-' + type);
            if (!box) return;
            const s = cropState[type];
            if (!s) return;
            box.style.left = (s.x * 100) + '%';
            box.style.top = (s.y * 100) + '%';
            box.style.width = (s.w * 100) + '%';
            box.style.height = (s.h * 100) + '%';

            if (currentCropMode === 'single_916') {
                if (type === 'single') box.classList.remove('hidden');
                else box.classList.add('hidden');
            } else {
                if (type === 'single') box.classList.add('hidden');
                else if (type === 'cam') {
                    if (s.enabled) box.classList.remove('hidden');
                    else box.classList.add('hidden');
                } else if (type === 'game') {
                    box.classList.remove('hidden');
                }
            }

            const vw = videoNativeWidth || 1920;
            const vh = videoNativeHeight || 1080;
            const readout = document.getElementById('crop-coords-readout');
            if (readout) {
                if (currentCropMode === 'single_916') {
                    const singlePx = { w: Math.round(cropState.single.w * vw), h: Math.round(cropState.single.h * vh), x: Math.round(cropState.single.x * vw), y: 0 };
                    readout.innerText = `Reines 9:16 IRL: ${singlePx.w}x${singlePx.h} @ (${singlePx.x}, 0) • Feste 9:16 Proportion (100% Video-Höhe)`;
                } else {
                    const camPx = { w: Math.round(cropState.cam.w * vw), h: Math.round(cropState.cam.h * vh), x: Math.round(cropState.cam.x * vw), y: Math.round(cropState.cam.y * vh) };
                    const gamePx = { w: Math.round(cropState.game.w * vw), h: Math.round(cropState.game.h * vh), x: Math.round(cropState.game.x * vw), y: Math.round(cropState.game.y * vh) };
                    readout.innerText = `Cam: ${cropState.cam.enabled ? camPx.w + 'x' + camPx.h + ' @ (' + camPx.x + ',' + camPx.y + ')' : 'Deaktiviert'} • Game: ${gamePx.w}x${gamePx.h} @ (${gamePx.x},${gamePx.y})`;
                }
            }
        }

        function initCropInteractions() {
            const stage = document.getElementById('crop-stage-container');
            if (!stage) return;

            const camBox = document.getElementById('crop-box-cam');
            if (camBox) {
                // Verschieben der Cam-Box
                camBox.addEventListener('pointerdown', (e) => {
                    // Falls auf einen Ecken-Resize-Handle geklickt wurde, kein Move-Drag starten
                    if (e.target.classList.contains('crop-cam-handle')) return;
                    e.preventDefault();
                    e.stopPropagation();
                    const rect = stage.getBoundingClientRect();
                    activeCropDrag = {
                        target: 'cam',
                        startX: e.clientX,
                        startY: e.clientY,
                        stageW: rect.width,
                        stageH: rect.height,
                        initX: cropState.cam.x,
                        initY: cropState.cam.y
                    };
                });

                // Mausrad zum stufenlosen Vergrößern/Verkleinern (3:2 bleibt fest)
                camBox.addEventListener('wheel', (e) => {
                    e.preventDefault();
                    e.stopPropagation();
                    const vw = videoNativeWidth || 1920;
                    const curWpx = cropState.cam.w * vw;
                    const delta = e.deltaY < 0 ? 15 : -15;
                    setCamPixelWidth(curWpx + delta);
                }, { passive: false });
            }

            // Ecken-Resize Handles für stufenlose Cam-Größenänderung mit festem 3:2 Seitenverhältnis
            document.querySelectorAll('.crop-cam-handle').forEach(handleEl => {
                handleEl.addEventListener('pointerdown', (e) => {
                    e.preventDefault();
                    e.stopPropagation();
                    const rect = stage.getBoundingClientRect();
                    const handle = handleEl.getAttribute('data-handle');
                    const vw = videoNativeWidth || 1920;
                    const vh = videoNativeHeight || 1080;

                    activeCropDrag = {
                        target: 'cam_resize',
                        handle: handle,
                        startX: e.clientX,
                        startY: e.clientY,
                        stageW: rect.width,
                        stageH: rect.height,
                        initX: cropState.cam.x,
                        initY: cropState.cam.y,
                        initW: cropState.cam.w,
                        initH: cropState.cam.h,
                        initWpx: cropState.cam.w * vw,
                        anchorX: handle.includes('r') ? cropState.cam.x : cropState.cam.x + cropState.cam.w,
                        anchorY: handle.includes('b') ? cropState.cam.y : cropState.cam.y + cropState.cam.h
                    };
                });
            });

            // Ecken-Resize Handles für stufenlose Gameplay-Größenänderung mit festem 9:10 Seitenverhältnis
            document.querySelectorAll('.crop-game-handle').forEach(handleEl => {
                handleEl.addEventListener('pointerdown', (e) => {
                    e.preventDefault();
                    e.stopPropagation();
                    const rect = stage.getBoundingClientRect();
                    const handle = handleEl.getAttribute('data-handle');
                    const vw = videoNativeWidth || 1920;
                    const vh = videoNativeHeight || 1080;

                    activeCropDrag = {
                        target: 'game_resize',
                        handle: handle,
                        startX: e.clientX,
                        startY: e.clientY,
                        stageW: rect.width,
                        stageH: rect.height,
                        initX: cropState.game.x,
                        initY: cropState.game.y,
                        initW: cropState.game.w,
                        initH: cropState.game.h,
                        initWpx: cropState.game.w * vw,
                        anchorX: handle.includes('r') ? cropState.game.x : cropState.game.x + cropState.game.w,
                        anchorY: handle.includes('b') ? cropState.game.y : cropState.game.y + cropState.game.h
                    };
                });
            });

            const gameBox = document.getElementById('crop-box-game');
            if (gameBox) {
                gameBox.addEventListener('pointerdown', (e) => {
                    if (e.target.classList.contains('crop-game-handle')) return;
                    e.preventDefault();
                    e.stopPropagation();
                    const rect = stage.getBoundingClientRect();
                    activeCropDrag = {
                        target: 'game',
                        startX: e.clientX,
                        startY: e.clientY,
                        stageW: rect.width,
                        stageH: rect.height,
                        initX: cropState.game.x,
                        initY: cropState.game.y
                    };
                });

                // Mausrad zum stufenlosen Gameplay-Vergrößern/Verkleinern (9:10 bleibt fest)
                gameBox.addEventListener('wheel', (e) => {
                    e.preventDefault();
                    e.stopPropagation();
                    const vw = videoNativeWidth || 1920;
                    const curWpx = cropState.game.w * vw;
                    const delta = e.deltaY < 0 ? 20 : -20;
                    setGamePixelWidth(curWpx + delta);
                }, { passive: false });
            }

            const singleBox = document.getElementById('crop-box-single');
            if (singleBox) {
                singleBox.addEventListener('pointerdown', (e) => {
                    e.preventDefault();
                    e.stopPropagation();
                    const rect = stage.getBoundingClientRect();
                    activeCropDrag = {
                        target: 'single',
                        startX: e.clientX,
                        startY: e.clientY,
                        stageW: rect.width,
                        stageH: rect.height,
                        initX: cropState.single.x,
                        initY: 0.0
                    };
                });
            }

            window.addEventListener('pointermove', (e) => {
                if (!activeCropDrag) return;
                const dx = (e.clientX - activeCropDrag.startX) / activeCropDrag.stageW;
                const dy = (e.clientY - activeCropDrag.startY) / activeCropDrag.stageH;

                if (activeCropDrag.target === 'cam') {
                    // Cam bewegt sich frei in X und Y, GRÖSSE BLEIBT FEST (3:2 Format)!
                    cropState.cam.x = Math.max(0, Math.min(1 - cropState.cam.w, activeCropDrag.initX + dx));
                    cropState.cam.y = Math.max(0, Math.min(1 - cropState.cam.h, activeCropDrag.initY + dy));
                    updateBoxDom('cam');
                    draw916Preview();
                } else if (activeCropDrag.target === 'cam_resize') {
                    // Stufenlose Größenänderung über Eckengriffe (3:2 strikt gesperrt)
                    const vw = videoNativeWidth || 1920;
                    const vh = videoNativeHeight || 1080;
                    const handle = activeCropDrag.handle;
                    const dxPx = dx * vw;

                    let targetWpx;
                    if (handle.includes('r')) {
                        targetWpx = activeCropDrag.initWpx + dxPx;
                    } else {
                        targetWpx = activeCropDrag.initWpx - dxPx;
                    }

                    const maxAllowedW = Math.min(vw, Math.floor(vh * 1.5));
                    let clampedWpx = Math.max(160, Math.min(maxAllowedW, Math.round(targetWpx)));
                    let clampedHpx = Math.round(clampedWpx * (2 / 3));

                    let wNorm = clampedWpx / vw;
                    let hNorm = clampedHpx / vh;

                    // Randbegrenzung mit festem Seitenverhältnis
                    if (handle.includes('r')) {
                        if (activeCropDrag.anchorX + wNorm > 1.0) {
                            wNorm = 1.0 - activeCropDrag.anchorX;
                            clampedWpx = Math.round(wNorm * vw);
                            clampedHpx = Math.round(clampedWpx * (2 / 3));
                            hNorm = clampedHpx / vh;
                        }
                    } else {
                        if (activeCropDrag.anchorX - wNorm < 0.0) {
                            wNorm = activeCropDrag.anchorX;
                            clampedWpx = Math.round(wNorm * vw);
                            clampedHpx = Math.round(clampedWpx * (2 / 3));
                            hNorm = clampedHpx / vh;
                        }
                    }

                    if (handle.includes('b')) {
                        if (activeCropDrag.anchorY + hNorm > 1.0) {
                            hNorm = 1.0 - activeCropDrag.anchorY;
                            clampedHpx = Math.round(hNorm * vh);
                            clampedWpx = Math.round(clampedHpx * (3 / 2));
                            wNorm = clampedWpx / vw;
                        }
                    } else {
                        if (activeCropDrag.anchorY - hNorm < 0.0) {
                            hNorm = activeCropDrag.anchorY;
                            clampedHpx = Math.round(hNorm * vh);
                            clampedWpx = Math.round(clampedHpx * (3 / 2));
                            wNorm = clampedWpx / vw;
                        }
                    }

                    clampedWpx = Math.max(160, Math.round(wNorm * vw));
                    clampedHpx = Math.round(clampedWpx * (2 / 3));
                    wNorm = clampedWpx / vw;
                    hNorm = clampedHpx / vh;

                    const newX = handle.includes('l') ? (activeCropDrag.anchorX - wNorm) : activeCropDrag.anchorX;
                    const newY = handle.includes('t') ? (activeCropDrag.anchorY - hNorm) : activeCropDrag.anchorY;

                    cropState.cam.w = wNorm;
                    cropState.cam.h = hNorm;
                    cropState.cam.x = Math.max(0, Math.min(1 - wNorm, newX));
                    cropState.cam.y = Math.max(0, Math.min(1 - hNorm, newY));

                    syncCamSizeUi(clampedWpx, clampedHpx);
                    updateBoxDom('cam');
                    draw916Preview();
                } else if (activeCropDrag.target === 'game_resize') {
                    // Stufenlose Gameplay-Größenänderung über Eckengriffe mit dynamischem Format (9:10 mit Cam vs. 9:16 ohne Cam)
                    const vw = videoNativeWidth || 1920;
                    const vh = videoNativeHeight || 1080;
                    const isVollbild = isGameplayVollbild();
                    const ratioW = 9;
                    const ratioH = isVollbild ? 16 : 10;

                    const handle = activeCropDrag.handle;
                    const dxPx = dx * vw;

                    let targetWpx;
                    if (handle.includes('r')) {
                        targetWpx = activeCropDrag.initWpx + dxPx;
                    } else {
                        targetWpx = activeCropDrag.initWpx - dxPx;
                    }

                    const maxAllowedW = Math.min(vw, Math.floor(vh * (ratioW / ratioH)));
                    const minAllowedW = isVollbild ? 200 : 320;
                    let clampedWpx = Math.max(minAllowedW, Math.min(maxAllowedW, Math.round(targetWpx)));
                    let clampedHpx = Math.round(clampedWpx * (ratioH / ratioW));

                    let wNorm = clampedWpx / vw;
                    let hNorm = clampedHpx / vh;

                    // Randbegrenzung mit festem Seitenverhältnis
                    if (handle.includes('r')) {
                        if (activeCropDrag.anchorX + wNorm > 1.0) {
                            wNorm = 1.0 - activeCropDrag.anchorX;
                            clampedWpx = Math.round(wNorm * vw);
                            clampedHpx = Math.round(clampedWpx * (ratioH / ratioW));
                            hNorm = clampedHpx / vh;
                        }
                    } else {
                        if (activeCropDrag.anchorX - wNorm < 0.0) {
                            wNorm = activeCropDrag.anchorX;
                            clampedWpx = Math.round(wNorm * vw);
                            clampedHpx = Math.round(clampedWpx * (ratioH / ratioW));
                            hNorm = clampedHpx / vh;
                        }
                    }

                    if (handle.includes('b')) {
                        if (activeCropDrag.anchorY + hNorm > 1.0) {
                            hNorm = 1.0 - activeCropDrag.anchorY;
                            clampedHpx = Math.round(hNorm * vh);
                            clampedWpx = Math.round(clampedHpx * (ratioW / ratioH));
                            wNorm = clampedWpx / vw;
                        }
                    } else {
                        if (activeCropDrag.anchorY - hNorm < 0.0) {
                            hNorm = activeCropDrag.anchorY;
                            clampedHpx = Math.round(hNorm * vh);
                            clampedWpx = Math.round(clampedHpx * (ratioW / ratioH));
                            wNorm = clampedWpx / vw;
                        }
                    }

                    clampedWpx = Math.max(minAllowedW, Math.round(wNorm * vw));
                    clampedHpx = Math.round(clampedWpx * (ratioH / ratioW));
                    wNorm = clampedWpx / vw;
                    hNorm = clampedHpx / vh;

                    const newX = handle.includes('l') ? (activeCropDrag.anchorX - wNorm) : activeCropDrag.anchorX;
                    const newY = handle.includes('t') ? (activeCropDrag.anchorY - hNorm) : activeCropDrag.anchorY;

                    cropState.game.w = wNorm;
                    cropState.game.h = hNorm;
                    cropState.game.x = Math.max(0, Math.min(1 - wNorm, newX));
                    cropState.game.y = Math.max(0, Math.min(1 - hNorm, newY));

                    syncGameSizeUi(clampedWpx, clampedHpx);
                    updateBoxDom('game');
                    draw916Preview();
                } else if (activeCropDrag.target === 'game') {
                    // Gameplay bewegt sich frei in X und Y (falls H < 1.0), GRÖSSE BLEIBT FEST (9:10 Format)!
                    cropState.game.x = Math.max(0, Math.min(1 - cropState.game.w, activeCropDrag.initX + dx));
                    cropState.game.y = Math.max(0, Math.min(1 - cropState.game.h, activeCropDrag.initY + dy));
                    updateBoxDom('game');
                    draw916Preview();
                } else if (activeCropDrag.target === 'single') {
                    // 9:16 IRL Rahmen: nur horizontal bewegbar, feste 9:16 Proportion (608x1080 px / 100% Höhe)!
                    cropState.single.x = Math.max(0, Math.min(1 - cropState.single.w, activeCropDrag.initX + dx));
                    cropState.single.y = 0.0;
                    updateBoxDom('single');
                    draw916Preview();
                }
            });

            window.addEventListener('pointerup', () => {
                activeCropDrag = null;
            });
        }

        function applyPreset(presetName) {
            if (presetName === 'cam_br') {
                cropState.cam.x = Math.max(0, 1 - cropState.cam.w - 0.015);
                cropState.cam.y = Math.max(0, 1 - cropState.cam.h - 0.02);
                cropState.cam.enabled = true;
            } else if (presetName === 'cam_tl') {
                cropState.cam.x = 0.015;
                cropState.cam.y = 0.02;
                cropState.cam.enabled = true;
            } else if (presetName === 'cam_tr') {
                cropState.cam.x = Math.max(0, 1 - cropState.cam.w - 0.015);
                cropState.cam.y = 0.02;
                cropState.cam.enabled = true;
            } else if (presetName === 'cam_bl') {
                cropState.cam.x = 0.015;
                cropState.cam.y = Math.max(0, 1 - cropState.cam.h - 0.02);
                cropState.cam.enabled = true;
            } else if (presetName === 'game_center') {
                cropState.game.x = (1 - cropState.game.w) / 2;
                cropState.game.y = Math.max(0, (1 - cropState.game.h) / 2);
            } else if (presetName === 'game_left') {
                cropState.game.x = 0.01;
                cropState.game.y = Math.max(0, (1 - cropState.game.h) / 2);
            } else if (presetName === 'game_right') {
                cropState.game.x = Math.max(0, 1 - cropState.game.w - 0.01);
                cropState.game.y = Math.max(0, (1 - cropState.game.h) / 2);
            } else if (presetName === 'single_center') {
                cropState.single.x = (1 - cropState.single.w) / 2;
                cropState.single.y = 0.0;
            } else if (presetName === 'single_left') {
                cropState.single.x = 0.0;
                cropState.single.y = 0.0;
            } else if (presetName === 'single_right') {
                cropState.single.x = Math.max(0, 1 - cropState.single.w);
                cropState.single.y = 0.0;
            }
            updateBoxDom('cam');
            updateBoxDom('game');
            updateBoxDom('single');
            draw916Preview();
        }

        async function detectFacecamInCropModal() {
            if (!currentCropClipId) return;
            const btn = document.getElementById('btn-crop-detect');
            btn.innerHTML = '<span class="inline-block w-3.5 h-3.5 border-2 border-zinc-200 border-t-transparent rounded-full animate-spin mr-1.5"></span> <span>Erkenne...</span>';
            btn.disabled = true;
            try {
                const resp = await apiFetch(`/api/clip/${currentCropClipId}/detect-cam`);
                const data = await resp.json();
                if (data && data.cam) {
                    const faceCenterX = data.cam.x_pct + (data.cam.w_pct / 2);
                    const faceCenterY = data.cam.y_pct + (data.cam.h_pct / 2);
                    cropState.cam.x = Math.max(0, Math.min(1 - cropState.cam.w, faceCenterX - (cropState.cam.w / 2)));
                    cropState.cam.y = Math.max(0, Math.min(1 - cropState.cam.h, faceCenterY - (cropState.cam.h / 2)));
                    cropState.cam.enabled = true;
                    updateBoxDom('cam');
                    draw916Preview();
                }
            } catch (e) {
                console.error(e);
            } finally {
                btn.innerHTML = `${SVG_ICONS.sparkles} <span>KI Auto-Erkennen</span>`;
                btn.disabled = false;
            }
        }

        function draw916Preview() {
            const canvas = document.getElementById('crop-preview-canvas');
            if (!canvas) return;
            const ctx = canvas.getContext('2d');
            const vidElem = document.getElementById('crop-stage-video');
            const source = (vidElem && vidElem.readyState >= 2) ? vidElem : ((cropFallbackImg && cropFallbackImg.complete && cropFallbackImg.naturalWidth > 0) ? cropFallbackImg : null);

            ctx.fillStyle = '#05070e';
            ctx.fillRect(0, 0, 270, 480);

            if (!source) {
                ctx.fillStyle = '#1e293b';
                ctx.fillRect(10, 10, 250, 460);
                ctx.fillStyle = '#94a3b8';
                ctx.font = '12px sans-serif';
                ctx.textAlign = 'center';
                ctx.fillText('Lade Frame...', 135, 240);
                return;
            }

            const vid = source;
            const vw = source.videoWidth || source.naturalWidth || 1920;
            const vh = source.videoHeight || source.naturalHeight || 1080;

            if (currentCropMode === 'single_916') {
                // Reines 9:16 Vollbild (IRL / Fullscreen) - 1:1 unverzerrt in 9:16 Canvas
                const sx = cropState.single.x * vw;
                const sy = 0;
                const sw = Math.max(16, cropState.single.w * vw);
                const sh = vh;

                try {
                    ctx.drawImage(vid, sx, sy, sw, sh, 0, 0, 270, 480);
                } catch(e) {}

                // Hook Sticker Simulation (oben bei y=120, um Hauptmotiv/Gesicht im Zentrum freizuhalten)
                ctx.fillStyle = '#ffffff';
                ctx.shadowColor = 'rgba(0,0,0,0.6)';
                ctx.shadowBlur = 6;
                const stickerW = 200;
                const stickerH = 24;
                const stickerY = 120;
                ctx.beginPath();
                if (ctx.roundRect) {
                    ctx.roundRect((270 - stickerW) / 2, stickerY - (stickerH / 2), stickerW, stickerH, 6);
                } else {
                    ctx.rect((270 - stickerW) / 2, stickerY - (stickerH / 2), stickerW, stickerH);
                }
                ctx.fill();
                ctx.shadowBlur = 0;
                ctx.fillStyle = '#000000';
                ctx.font = 'bold 9px sans-serif';
                ctx.textAlign = 'center';
                ctx.textBaseline = 'middle';
                const titleText = currentCropTitle ? currentCropTitle.slice(0, 32) : 'TikTok / Shorts Hook';
                ctx.fillText(titleText, 135, stickerY);

            } else if (cropState.cam.enabled) {
                // 1. Top Section: Facecam (1080x720 in 1080x1920 -> 270x180 px)
                const cx = cropState.cam.x * vw;
                const cy = cropState.cam.y * vh;
                const cw = Math.max(16, cropState.cam.w * vw);
                const ch = Math.max(16, cropState.cam.h * vh);

                const filterVal = document.getElementById('crop-cam-filter-select')?.value || 'none';
                if (filterVal === 'triangle') {
                    // 3D Dreimacs Pyramide
                    ctx.save();
                    ctx.beginPath();
                    ctx.moveTo(135, 4);
                    ctx.lineTo(265, 178);
                    ctx.lineTo(5, 178);
                    ctx.closePath();
                    ctx.clip();
                    try { ctx.drawImage(vid, cx, cy, cw, ch, 0, 0, 270, 180); } catch(e) {}
                    ctx.restore();
                } else if (filterVal === 'inv_triangle') {
                    // 3D Trichter-Kopf
                    ctx.save();
                    ctx.beginPath();
                    ctx.moveTo(5, 4);
                    ctx.lineTo(265, 4);
                    ctx.lineTo(135, 178);
                    ctx.closePath();
                    ctx.clip();
                    try { ctx.drawImage(vid, cx, cy, cw, ch, 0, 0, 270, 180); } catch(e) {}
                    ctx.restore();
                } else if (filterVal === 'diamond') {
                    // 3D Diamant-Kopf
                    ctx.save();
                    ctx.beginPath();
                    ctx.moveTo(135, 4);
                    ctx.lineTo(265, 90);
                    ctx.lineTo(135, 176);
                    ctx.lineTo(5, 90);
                    ctx.closePath();
                    ctx.clip();
                    try { ctx.drawImage(vid, cx, cy, cw, ch, 0, 0, 270, 180); } catch(e) {}
                    ctx.restore();
                } else if (filterVal === 'cube') {
                    // 3D Block-Kopf (Steve)
                    ctx.save();
                    ctx.beginPath();
                    ctx.rect(35, 15, 200, 150);
                    ctx.clip();
                    try { ctx.drawImage(vid, cx, cy, cw, ch, 0, 0, 270, 180); } catch(e) {}
                    ctx.restore();
                } else if (filterVal === 'alien') {
                    // 3D Megamind / Alien (Riesen-Stirn)
                    ctx.save();
                    ctx.beginPath();
                    ctx.moveTo(135, 6);
                    ctx.bezierCurveTo(260, 6, 260, 95, 170, 178);
                    ctx.lineTo(100, 178);
                    ctx.bezierCurveTo(10, 95, 10, 6, 135, 6);
                    ctx.closePath();
                    ctx.clip();
                    try { ctx.drawImage(vid, cx, cy, cw, ch, 0, 0, 270, 180); } catch(e) {}
                    ctx.restore();
                } else if (filterVal === 'gigachad') {
                    // 3D Gigachad (Breiter Kiefer)
                    ctx.save();
                    ctx.beginPath();
                    ctx.moveTo(90, 6);
                    ctx.lineTo(180, 6);
                    ctx.bezierCurveTo(220, 60, 265, 120, 265, 176);
                    ctx.lineTo(5, 176);
                    ctx.bezierCurveTo(5, 120, 50, 60, 90, 6);
                    ctx.closePath();
                    ctx.clip();
                    try { ctx.drawImage(vid, cx, cy, cw, ch, 0, 0, 270, 180); } catch(e) {}
                    ctx.restore();
                } else if (filterVal === 'hamster') {
                    // 3D Hamsterbacken
                    try {
                        ctx.drawImage(vid, cx, cy, cw, ch, 0, 0, 270, 180);
                        ctx.drawImage(vid, cx, cy + ch * 0.4, cw, ch * 0.6, -15, 75, 300, 105);
                    } catch(e) {}
                } else if (filterVal === 'pinocchio') {
                    // 3D Pinocchio Langnase
                    try {
                        ctx.drawImage(vid, cx, cy, cw, ch, 0, 0, 270, 180);
                        ctx.drawImage(vid, cx + cw * 0.35, cy + ch * 0.35, cw * 0.3, ch * 0.3, 100, 75, 70, 95);
                    } catch(e) {}
                } else if (filterVal === 'big_eyes') {
                    // 3D Glubschaugen (Anime)
                    try {
                        ctx.drawImage(vid, cx, cy, cw, ch, 0, 0, 270, 180);
                        ctx.drawImage(vid, cx + cw * 0.2, cy + ch * 0.2, cw * 0.6, ch * 0.35, 35, 30, 200, 80);
                    } catch(e) {}
                } else if (filterVal === 'tiny_face') {
                    // 3D Schrumpf-Gesicht (Meme)
                    try {
                        ctx.drawImage(vid, cx, cy, cw, ch, 0, 0, 270, 180);
                        ctx.drawImage(vid, cx + cw * 0.2, cy + ch * 0.2, cw * 0.6, ch * 0.6, 95, 65, 80, 80);
                    } catch(e) {}
                } else if (filterVal === 'big_mouth') {
                    // 3D Riesenmund
                    try {
                        ctx.drawImage(vid, cx, cy, cw, ch, 0, 0, 270, 180);
                        ctx.drawImage(vid, cx + cw * 0.2, cy + ch * 0.55, cw * 0.6, ch * 0.4, 50, 100, 170, 75);
                    } catch(e) {}
                } else if (filterVal === 'hourglass') {
                    // 3D Sanduhr / Wespentaille (Pinch)
                    ctx.save();
                    ctx.beginPath();
                    ctx.moveTo(5, 4);
                    ctx.lineTo(265, 4);
                    ctx.bezierCurveTo(195, 90, 195, 90, 265, 178);
                    ctx.lineTo(5, 178);
                    ctx.bezierCurveTo(75, 90, 75, 90, 5, 4);
                    ctx.closePath();
                    ctx.clip();
                    try { ctx.drawImage(vid, cx, cy, cw, ch, 0, 0, 270, 180); } catch(e) {}
                    ctx.restore();
                } else if (filterVal === 'fisheye') {
                    // 3D Fischauge / Glaskugel
                    ctx.save();
                    ctx.beginPath();
                    ctx.ellipse(135, 90, 130, 86, 0, 0, Math.PI * 2);
                    ctx.clip();
                    try { ctx.drawImage(vid, cx + cw * 0.1, cy + ch * 0.1, cw * 0.8, ch * 0.8, 0, 0, 270, 180); } catch(e) {}
                    ctx.restore();
                } else if (filterVal === 'mirror_left') {
                    // Doppel-Links: Linke Hälfte auf rechts gespiegelt
                    try {
                        ctx.drawImage(vid, cx, cy, cw / 2, ch, 0, 0, 135, 180);
                        ctx.save();
                        ctx.translate(270, 0);
                        ctx.scale(-1, 1);
                        ctx.drawImage(vid, cx, cy, cw / 2, ch, 0, 0, 135, 180);
                        ctx.restore();
                    } catch(e) {}
                } else if (filterVal === 'mirror_right') {
                    // Doppel-Rechts: Rechte Hälfte auf links gespiegelt
                    try {
                        ctx.drawImage(vid, cx + cw / 2, cy, cw / 2, ch, 135, 0, 135, 180);
                        ctx.save();
                        ctx.translate(135, 0);
                        ctx.scale(-1, 1);
                        ctx.drawImage(vid, cx + cw / 2, cy, cw / 2, ch, 0, 0, 135, 180);
                        ctx.restore();
                    } catch(e) {}
                } else if (filterVal === 'stretch_vert') {
                    // Bleistift-Kopf
                    try {
                        ctx.drawImage(vid, cx + cw * 0.22, cy, cw * 0.56, ch, 0, 0, 270, 180);
                    } catch(e) {}
                } else if (filterVal === 'squish_wide') {
                    // ️ Wide Meme
                    try {
                        ctx.drawImage(vid, cx, cy + ch * 0.2, cw, ch * 0.6, 0, 0, 270, 180);
                    } catch(e) {}
                } else {
                    try {
                        ctx.drawImage(vid, cx, cy, cw, ch, 0, 0, 270, 180);
                    } catch(e) {}
                }

                // Filter Badge Tag anzeigen
                if (filterVal && filterVal !== 'none') {
                    const filterLabels = {
                        triangle: '3D Dreimacs Pyramide',
                        inv_triangle: '3D Trichter-Kopf',
                        diamond: '3D Diamant-Kopf',
                        cube: '3D Block-Kopf',
                        gigachad: '3D Gigachad Kiefer',
                        alien: '3D Megamind Alien',
                        hamster: '3D Hamsterbacken',
                        pinocchio: '3D Pinocchio Langnase',
                        big_eyes: '3D Glubschaugen',
                        tiny_face: '3D Schrumpf-Gesicht',
                        big_mouth: '3D Riesenmund',
                        hourglass: '3D Sanduhr Pinch',
                        fisheye: '3D Glaskugel Fischauge',
                        swirl: '3D Strudel Twist',
                        wave: '3D Wackelpudding',
                        mirror_left: 'Doppel-Links',
                        mirror_right: 'Doppel-Rechts',
                        stretch_vert: 'Bleistift-Kopf',
                        squish_wide: 'Wide Meme'
                    };
                    const tag = filterLabels[filterVal] || filterVal;
                    ctx.save();
                    ctx.font = 'bold 9px sans-serif';
                    const tw = ctx.measureText(tag).width;
                    ctx.fillStyle = 'rgba(15, 23, 42, 0.85)';
                    ctx.strokeStyle = '#34d399';
                    ctx.lineWidth = 1;
                    ctx.beginPath();
                    if (ctx.roundRect) ctx.roundRect(8, 8, tw + 14, 18, 4);
                    else ctx.rect(8, 8, tw + 14, 18);
                    ctx.fill();
                    ctx.stroke();
                    ctx.fillStyle = '#34d399';
                    ctx.textAlign = 'left';
                    ctx.textBaseline = 'middle';
                    ctx.fillText(tag, 15, 17);
                    ctx.restore();
                }

                // Divider Seam
                ctx.fillStyle = '#1e1b4b';
                ctx.fillRect(0, 178, 270, 4);
                ctx.fillStyle = '#c084fc';
                ctx.fillRect(0, 179, 270, 2);

                // 2. Bottom Section: Gameplay (1080x1200 in 1080x1920 -> 270x300 px)
                const gx = cropState.game.x * vw;
                const gy = cropState.game.y * vh;
                const gw = Math.max(16, cropState.game.w * vw);
                const gh = Math.max(16, cropState.game.h * vh);

                try {
                    ctx.drawImage(vid, gx, gy, gw, gh, 0, 180, 270, 300);
                } catch(e) {}

                // Hook Sticker Badge Simulation
                ctx.fillStyle = '#ffffff';
                ctx.shadowColor = 'rgba(0,0,0,0.6)';
                ctx.shadowBlur = 6;
                const stickerW = 200;
                const stickerH = 24;
                ctx.beginPath();
                if (ctx.roundRect) {
                    ctx.roundRect((270 - stickerW) / 2, 180 - (stickerH / 2), stickerW, stickerH, 6);
                } else {
                    ctx.rect((270 - stickerW) / 2, 180 - (stickerH / 2), stickerW, stickerH);
                }
                ctx.fill();
                ctx.shadowBlur = 0;
                ctx.fillStyle = '#000000';
                ctx.font = 'bold 9px sans-serif';
                ctx.textAlign = 'center';
                ctx.textBaseline = 'middle';
                const titleText = currentCropTitle ? currentCropTitle.slice(0, 32) : 'TikTok / Shorts Hook';
                ctx.fillText(titleText, 135, 180);

            } else {
                // Reines Vollbild-Gameplay (Festes 9:16 Short)
                const gx = cropState.game.x * vw;
                const gy = cropState.game.y * vh;
                const gw = Math.max(16, cropState.game.w * vw);
                const gh = Math.max(16, cropState.game.h * vh);

                try {
                    ctx.drawImage(vid, gx, gy, gw, gh, 0, 0, 270, 480);
                } catch(e) {}

                // Hook Sticker Simulation (oben bei y=120)
                ctx.fillStyle = '#ffffff';
                ctx.shadowColor = 'rgba(0,0,0,0.6)';
                ctx.shadowBlur = 6;
                const stickerW = 200;
                const stickerH = 24;
                const stickerY = 120;
                ctx.beginPath();
                if (ctx.roundRect) {
                    ctx.roundRect((270 - stickerW) / 2, stickerY - (stickerH / 2), stickerW, stickerH, 6);
                } else {
                    ctx.rect((270 - stickerW) / 2, stickerY - (stickerH / 2), stickerW, stickerH);
                }
                ctx.fill();
                ctx.shadowBlur = 0;
                ctx.fillStyle = '#000000';
                ctx.font = 'bold 9px sans-serif';
                ctx.textAlign = 'center';
                ctx.textBaseline = 'middle';
                const titleText = currentCropTitle ? currentCropTitle.slice(0, 32) : 'TikTok / Shorts Hook';
                ctx.fillText(titleText, 135, stickerY);
            }

            // Subtitle Preview Simulation
            ctx.font = 'bold 11px sans-serif';
            ctx.textAlign = 'center';
            ctx.fillStyle = '#fde047';
            ctx.strokeStyle = '#000000';
            ctx.lineWidth = 2.5;
            ctx.strokeText("[Untertitel Bereich]", 135, 435);
            ctx.fillText("[Untertitel Bereich]", 135, 435);
        }

        async function saveCropCoordinates(renderNow) {
            if (!currentCropClipId) return;
            const vw = videoNativeWidth || 1920;
            const vh = videoNativeHeight || 1080;

            const modalTitleInput = document.getElementById('crop-title-input');
            const modalStickerInput = document.getElementById('crop-sticker-text-input');
            const modalSubPosSelect = document.getElementById('crop-sub-position-select');
            const modalLayoutSelect = document.getElementById('crop-layout-mode-select');
            const modalFilterSelect = document.getElementById('crop-cam-filter-select');
            const modalTranscriptEl = document.getElementById('crop-transcript-textarea');

            let editedTranscript = modalTranscriptEl ? modalTranscriptEl.value : null;
            if (editedTranscript === null) {
                const formEl = document.getElementById('form-' + currentCropClipId);
                if (formEl) {
                    const txEl = formEl.querySelector('textarea[name="transcript"]');
                    if (txEl) editedTranscript = txEl.value;
                }
            }

            const chosenLayout = modalLayoutSelect ? modalLayoutSelect.value : '';
            let payload;
            if (currentCropMode === 'single_916') {
                payload = {
                    layout_mode: chosenLayout && chosenLayout !== 'custom' ? chosenLayout : 'single_916',
                    render_now: renderNow,
                    custom_crops: {
                        mode: 'single_916',
                        enabled: true,
                        single: {
                            x_pct: cropState.single.x,
                            y_pct: 0.0,
                            w_pct: cropState.single.w,
                            h_pct: 1.0,
                            x: Math.round(cropState.single.x * vw),
                            y: 0,
                            w: Math.round(cropState.single.w * vw),
                            h: vh
                        }
                    }
                };
            } else {
                payload = {
                    layout_mode: (chosenLayout && chosenLayout !== 'single_916') ? chosenLayout : 'custom',
                    render_now: renderNow,
                    custom_crops: {
                        mode: 'split',
                        enabled: true,
                        cam: {
                            x_pct: cropState.cam.x,
                            y_pct: cropState.cam.y,
                            w_pct: cropState.cam.w,
                            h_pct: cropState.cam.h,
                            x: Math.round(cropState.cam.x * vw),
                            y: Math.round(cropState.cam.y * vh),
                            w: Math.round(cropState.cam.w * vw),
                            h: Math.round(cropState.cam.h * vh),
                            enabled: cropState.cam.enabled
                        },
                        game: {
                            x_pct: cropState.game.x,
                            y_pct: cropState.game.y,
                            w_pct: cropState.game.w,
                            h_pct: cropState.game.h,
                            x: Math.round(cropState.game.x * vw),
                            y: Math.round(cropState.game.y * vh),
                            w: Math.round(cropState.game.w * vw),
                            h: Math.round(cropState.game.h * vh),
                            enabled: true
                        }
                    }
                };
            }

            if (modalTitleInput) {
                payload.title = modalTitleInput.value.trim();
                const cardTitleEl = document.querySelector(`#form-${currentCropClipId} input[name="title"]`);
                if (cardTitleEl) cardTitleEl.value = payload.title;
            }
            if (modalStickerInput) {
                payload.sticker_text = modalStickerInput.value.trim();
            }
            if (modalSubPosSelect) {
                payload.sub_position = modalSubPosSelect.value;
            }
            if (typeof editedTranscript === 'string') {
                payload.transcript = editedTranscript;
            }
            if (modalFilterSelect) {
                payload.cam_filter = modalFilterSelect.value;
            }

            if (renderNow) {
                const videoEl = document.getElementById('studio-video-' + currentCropClipId);
                if (videoEl) {
                    try {
                        videoEl.pause();
                        videoEl.removeAttribute('src');
                        videoEl.querySelectorAll('source').forEach(s => s.remove());
                        videoEl.load();
                    } catch (e) {}
                }
            }

            try {
                const resp = await apiFetch(`/api/clip/${currentCropClipId}/save-crop`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });
                const res = await resp.json();
                if (res.success) {
                    closeCropModal();
                    if (renderNow) {
                        const renderCard = document.getElementById('render-progress-card');
                        if (renderCard) renderCard.classList.remove('hidden');
                        updateStatus();
                    }
                    refreshDashboard(true);
                }
            } catch (e) {
                alert('Fehler beim Speichern: ' + e);
            }
        }

        async function startTikTokBrowserLogin() {
            const btn = document.getElementById('btn-tt-browser-login');
            const box = document.getElementById('tt-browser-status-box');
            const text = document.getElementById('tt-browser-status-text');

            if (btn) {
                btn.disabled = true;
                btn.classList.add('opacity-70', 'cursor-not-allowed');
            }
            if (box) box.classList.remove('hidden');
            if (text) text.innerText = 'Chrome wird gestartet... Bitte im geöffneten Fenster einloggen (z. B. QR-Code scannen)!';

            try {
                const resp = await apiFetch('/api/accounts/tiktok/browser-login', { method: 'POST' });
                const data = await resp.json();
                if (!data.success) {
                    alert(data.message);
                    if (btn) {
                        btn.disabled = false;
                        btn.classList.remove('opacity-70', 'cursor-not-allowed');
                    }
                    if (box) box.classList.add('hidden');
                    return;
                }

                const pollStart = Date.now();
                const pollTimer = setInterval(async () => {
                    // H6 Audit-Fix: Timeout nach 5 Minuten (300.000 ms)
                    if (Date.now() - pollStart > 300000) {
                        clearInterval(pollTimer);
                        if (btn) {
                            btn.disabled = false;
                            btn.classList.remove('opacity-70', 'cursor-not-allowed');
                        }
                        if (box) box.classList.add('hidden');
                        showToast('TikTok Login-Polling nach 5 Minuten beendet.', 'info');
                        return;
                    }
                    try {
                        const sResp = await apiFetch('/api/accounts/tiktok/browser-login/status');
                        const sData = await sResp.json();
                        if (text && sData.message) text.innerText = sData.message;

                        if (!sData.running) {
                            clearInterval(pollTimer);
                            if (sData.message && sData.message.includes('Erfolgreich')) {
                                if (text) text.innerText = 'Erfolgreich verbunden! Aktualisiere Dashboard...';
                                setTimeout(() => refreshDashboard(), 1200);
                            } else {
                                if (btn) {
                                    btn.disabled = false;
                                    btn.classList.remove('opacity-70', 'cursor-not-allowed');
                                }
                                setTimeout(() => { if (box) box.classList.add('hidden'); }, 4000);
                            }
                        }
                    } catch (err) {
                        console.error('Polling status error:', err);
                    }
                }, 1500);

            } catch (err) {
                alert('Fehler beim Starten des Browser-Logins: ' + err);
                if (btn) {
                    btn.disabled = false;
                    btn.classList.remove('opacity-70', 'cursor-not-allowed');
                }
                if (box) box.classList.add('hidden');
            }
        }

        async function startYouTubeOAuthLogin() {
            const btn = document.getElementById('btn-yt-login');
            const box = document.getElementById('yt-login-status-box');
            const text = document.getElementById('yt-login-status-text');

            if (btn) {
                btn.disabled = true;
                btn.classList.add('opacity-70', 'cursor-not-allowed');
            }
            if (box) box.classList.remove('hidden');
            if (text) text.innerText = 'Google-Anmeldung wird vorbereitet...';

            try {
                const resp = await apiFetch('/api/accounts/youtube/authorize', { method: 'POST' });
                const data = await resp.json();
                if (!data.success || !data.auth_url) {
                    alert(data.message || 'Fehler beim Starten der Google-Anmeldung.');
                    if (btn) {
                        btn.disabled = false;
                        btn.classList.remove('opacity-70', 'cursor-not-allowed');
                    }
                    if (box) box.classList.add('hidden');
                    return;
                }

                // Im neuen Tab öffnen!
                window.open(data.auth_url, '_blank');
                if (text) text.innerText = 'Google-Login im neuen Tab geöffnet! Wähle deinen YouTube-Kanal und klicke auf "Zulassen"...';

                // Status überwachen bis YouTube auf verbunden springt
                const pollStart = Date.now();
                const pollTimer = setInterval(async () => {
                    // H6 Audit-Fix: Timeout nach 5 Minuten (300.000 ms)
                    if (Date.now() - pollStart > 300000) {
                        clearInterval(pollTimer);
                        if (btn) {
                            btn.disabled = false;
                            btn.classList.remove('opacity-70', 'cursor-not-allowed');
                        }
                        if (box) box.classList.add('hidden');
                        showToast('TikTok Login-Polling nach 5 Minuten beendet.', 'info');
                        return;
                    }
                    try {
                        const aResp = await apiFetch('/api/accounts/status');
                        const aData = await aResp.json();
                        if (aData && aData.youtube && aData.youtube.is_connected) {
                            clearInterval(pollTimer);
                            if (text) text.innerText = 'YouTube erfolgreich verbunden! Seite wird aktualisiert...';
                            setTimeout(() => refreshDashboard(), 1500);
                        }
                    } catch (err) {
                        console.error('Polling YT status error:', err);
                    }
                }, 1500);

            } catch (err) {
                alert('Fehler: ' + err);
                if (btn) {
                    btn.disabled = false;
                    btn.classList.remove('opacity-70', 'cursor-not-allowed');
                }
                if (box) box.classList.add('hidden');
            }
        }

        async function exportAllReadyClips(btn) {
    const origHtml = btn ? btn.innerHTML : '';
    if (btn) {
        btn.disabled = true;
        btn.innerHTML = '<span class="inline-block w-3.5 h-3.5 border-2 border-slate-300 border-t-transparent rounded-full animate-spin mr-1"></span><span>Öffne Ordner-Dialog...</span>';
    }
    showToast('Zielordner für alle fertigen Shorts auswählen...', 'info');
    try {
        const res = await apiFetch('/api/export-all-ready', { method: 'POST' });
        const data = await res.json();
        if (data && data.success) {
            showToast(`✓ ${data.count} Shorts erfolgreich exportiert!`, 'success');
        } else if (data && data.cancelled) {
            showToast('Export abgebrochen', 'info');
        } else {
            showToast('Fehler: ' + (data?.error || 'Export fehlgeschlagen'), 'error');
        }
    } catch (e) {
        showToast('Fehler beim Stapel-Export: ' + e, 'error');
    } finally {
        if (btn) {
            btn.disabled = false;
            btn.innerHTML = origHtml;
        }
    }
}

// ==========================================
// MANUELLE STREAMER-CLIP-SUCHE & IMPORT
// ==========================================
let gManualSearchTimeframe = 'LAST_DAY';
let gManualSearchClips = [];

function formatClipDuration(sec) {
    const s = Math.max(0, Math.round(Number(sec) || 0));
    const m = Math.floor(s / 60);
    const rem = s % 60;
    return `${m}:${rem < 10 ? '0' : ''}${rem}`;
}

function getDbStatusBadgeHtml(dbStatus) {
    if (!dbStatus || dbStatus === 'deleted' || dbStatus === 'failed') return '';
    const map = {
        harvested: { label: 'In Warteschlange', cls: 'bg-sky-500/20 text-sky-300 border-sky-500/40' },
        ready: { label: 'Bereits im Studio', cls: 'bg-emerald-500/20 text-emerald-300 border-emerald-500/40' },
        scheduled: { label: 'Eingeplant', cls: 'bg-purple-500/20 text-purple-300 border-purple-500/40' },
        published: { label: 'Veröffentlicht', cls: 'bg-amber-500/20 text-amber-300 border-amber-500/40' }
    };
    const info = map[dbStatus];
    if (!info) return '';
    return `<span class="text-[10px] font-bold px-2 py-0.5 rounded border ${info.cls}">${info.label}</span>`;
}

function selectManualTimeframe(tf) {
    gManualSearchTimeframe = tf || 'LAST_DAY';
    document.querySelectorAll('.manual-tf-btn').forEach(btn => {
        const isActive = btn.dataset.tf === gManualSearchTimeframe;
        if (isActive) {
            btn.className = 'manual-tf-btn px-2.5 py-1.5 rounded-md text-xs font-semibold bg-amber-500 text-zinc-950 transition';
        } else {
            btn.className = 'manual-tf-btn px-2.5 py-1.5 rounded-md text-xs font-semibold text-slate-400 hover:text-white transition';
        }
    });
    const input = document.getElementById('manual-search-streamer');
    if (input && input.value.trim()) {
        searchManualStreamerClips();
    }
}

function closeManualSearchResults() {
    const box = document.getElementById('manual-search-results');
    if (box) box.classList.add('hidden');
}

async function searchManualStreamerClips() {
    const input = document.getElementById('manual-search-streamer');
    const btn = document.getElementById('btn-manual-search');
    const resultsBox = document.getElementById('manual-search-results');
    const infoEl = document.getElementById('manual-search-streamer-info');
    const grid = document.getElementById('manual-search-grid');

    const streamer = input ? input.value.trim() : '';
    if (!streamer) {
        showToast('Bitte zuerst einen Twitch Streamer-Namen eingeben.', 'error');
        if (input) input.focus();
        return;
    }

    const origBtnHtml = btn ? btn.innerHTML : '';
    if (btn) {
        btn.disabled = true;
        btn.innerHTML = '<span class="inline-block w-3.5 h-3.5 border-2 border-zinc-950 border-t-transparent rounded-full animate-spin"></span><span>Suche...</span>';
    }

    try {
        const url = `/api/twitch/search-clips?streamer=${encodeURIComponent(streamer)}&timeframe=${encodeURIComponent(gManualSearchTimeframe)}&limit=24`;
        const res = await apiFetch(url, { method: 'GET' });
        const data = await res.json();

        if (!data || !data.success) {
            showToast(data?.error || 'Suche fehlgeschlagen.', 'error');
            if (resultsBox && grid) {
                resultsBox.classList.remove('hidden');
                if (infoEl) infoEl.innerHTML = `<span class="text-xs font-semibold text-rose-400">${escapeHtml(data?.error || 'Kein Streamer gefunden')}</span>`;
                grid.innerHTML = '';
            }
            return;
        }

        const st = data.streamer || {};
        gManualSearchClips = data.clips || [];

        if (resultsBox) resultsBox.classList.remove('hidden');

        const tfLabels = {
            LAST_DAY: 'Letzte 24h',
            LAST_WEEK: 'Letzte 7 Tage',
            LAST_MONTH: 'Letzte 30 Tage',
            ALL_TIME: 'Alle Zeiten'
        };
        const tfLabel = tfLabels[data.time_filter] || data.time_filter;

        if (infoEl) {
            const avatarHtml = st.avatar_url
                ? `<img src="${escapeHtml(st.avatar_url)}" alt="" class="w-7 h-7 rounded-full border border-slate-700 object-cover">`
                : '';
            infoEl.innerHTML = `
                ${avatarHtml}
                <div>
                    <span class="text-xs font-bold text-white">${escapeHtml(st.display_name || st.login || streamer)}</span>
                    <span class="text-[11px] text-slate-400 ml-2">${gManualSearchClips.length} Clips gefunden (${escapeHtml(tfLabel)})</span>
                </div>
            `;
        }

        if (!grid) return;
        if (gManualSearchClips.length === 0) {
            grid.innerHTML = `
                <div class="col-span-full py-8 text-center text-xs text-slate-400 bg-slate-950/50 rounded-lg border border-slate-800/80">
                    Keine Clips für <strong>${escapeHtml(st.display_name || streamer)}</strong> im Zeitfenster <strong>${escapeHtml(tfLabel)}</strong> gefunden. Probiere ein größeres Zeitfenster (z. B. 7 Tage oder 30 Tage).
                </div>
            `;
            return;
        }

        grid.innerHTML = gManualSearchClips.map((c, idx) => {
            const statusBadge = getDbStatusBadgeHtml(c.db_status);
            const thumbUrl = c.thumbnail_url ? escapeHtml(c.thumbnail_url) : '';
            const viewsFormatted = Number(c.view_count || 0).toLocaleString('de-DE');
            const alreadyInStudio = c.db_status === 'ready';
            return `
                <div class="bg-slate-950/90 border border-slate-800 hover:border-amber-500/40 rounded-lg overflow-hidden flex flex-col transition">
                    <div class="relative aspect-video bg-black overflow-hidden group">
                        ${thumbUrl
                            ? `<img src="${thumbUrl}" alt="${escapeHtml(c.title)}" loading="lazy" class="w-full h-full object-cover group-hover:scale-105 transition-transform duration-300">`
                            : `<div class="w-full h-full flex items-center justify-center text-slate-600 text-xs">Kein Vorschaubild</div>`
                        }
                        <div class="absolute top-2 left-2 bg-black/75 backdrop-blur-sm px-2 py-0.5 rounded text-[11px] font-bold text-amber-400 flex items-center gap-1">
                            ${SVG_ICONS.eye} ${viewsFormatted}
                        </div>
                        <div class="absolute top-2 right-2 bg-black/75 backdrop-blur-sm px-1.5 py-0.5 rounded text-[11px] font-mono font-semibold text-white">
                            ${formatClipDuration(c.duration)}
                        </div>
                        ${c.game ? `<div class="absolute bottom-2 left-2 bg-black/75 backdrop-blur-sm px-2 py-0.5 rounded text-[10px] font-medium text-slate-200 max-w-[85%] truncate">${escapeHtml(c.game)}</div>` : ''}
                    </div>
                    <div class="p-3 flex flex-col flex-1 justify-between gap-3">
                        <div>
                            <div class="text-xs font-bold text-slate-100 line-clamp-2 leading-snug" title="${escapeHtml(c.title)}">${escapeHtml(c.title)}</div>
                            <div class="flex items-center justify-between gap-2 mt-1.5">
                                <span class="text-[11px] text-slate-400" title="${escapeHtml(c.created_full || '')}">${escapeHtml(c.created_ago || '')}</span>
                                <span id="manual-clip-badge-${idx}">${statusBadge}</span>
                            </div>
                        </div>
                        <div class="flex items-center gap-1.5 pt-2 border-t border-slate-800/80">
                            <button type="button" onclick="importTwitchClipToStudio(${idx}, 'studio', this)"
                                class="flex-1 py-1.5 px-2.5 ${alreadyInStudio ? 'bg-slate-800 hover:bg-amber-500 hover:text-zinc-950 text-slate-300' : 'bg-amber-500 hover:bg-amber-400 text-zinc-950'} font-bold text-[11px] rounded transition flex items-center justify-center gap-1">
                                ${SVG_ICONS.scissors} <span>${alreadyInStudio ? 'Neu ins Studio' : 'Ins Studio importieren'}</span>
                            </button>
                            <button type="button" onclick="importTwitchClipToStudio(${idx}, 'queue', this)" title="Clip zuerst in Warteschlange laden"
                                class="py-1.5 px-2.5 bg-slate-800 hover:bg-slate-700 text-slate-300 font-semibold text-[11px] rounded border border-slate-700 transition">
                                + Queue
                            </button>
                        </div>
                    </div>
                </div>
            `;
        }).join('');
    } catch (e) {
        showToast('Fehler bei der Twitch-Suche: ' + e, 'error');
    } finally {
        if (btn) {
            btn.disabled = false;
            btn.innerHTML = origBtnHtml;
        }
    }
}

async function importTwitchClipToStudio(index, mode, btn) {
    const clip = gManualSearchClips[index];
    if (!clip) return;

    const origHtml = btn ? btn.innerHTML : '';
    if (btn) {
        btn.disabled = true;
        btn.innerHTML = '<span class="inline-block w-3 h-3 border-2 border-current border-t-transparent rounded-full animate-spin"></span> <span>Lädt...</span>';
    }

    try {
        const res = await apiFetch('/api/twitch/import-clip', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                clip_id: clip.clip_id,
                streamer: clip.streamer,
                title: clip.title,
                url: clip.url,
                view_count: clip.view_count,
                duration: clip.duration,
                created_at: clip.created_at,
                mode: mode || 'studio'
            })
        });
        const data = await res.json();
        if (!data || !data.success) {
            showToast(data?.error || 'Import fehlgeschlagen.', 'error');
            if (btn) {
                btn.disabled = false;
                btn.innerHTML = origHtml;
            }
            return;
        }

        const badgeEl = document.getElementById(`manual-clip-badge-${index}`);
        if (mode === 'queue') {
            clip.db_status = 'harvested';
            if (badgeEl) badgeEl.innerHTML = getDbStatusBadgeHtml('harvested');
            showToast(`✓ "${clip.title}" in Warteschlange importiert!`, 'success');
            if (btn) {
                btn.innerHTML = '✓ Queue';
                btn.disabled = false;
            }
            refreshDashboard();
        } else {
            showToast(`✂️ Studio-Import für "${clip.title}" gestartet (Transkription & 9:16 Schnitt läuft)...`, 'success');
            if (badgeEl) badgeEl.innerHTML = '<span class="text-[10px] font-bold px-2 py-0.5 rounded border bg-amber-500/20 text-amber-300 border-amber-500/40">Wird gerendert...</span>';
            if (btn) {
                btn.innerHTML = '✓ Gestartet';
                btn.disabled = false;
            }
            updateStatus();
        }
    } catch (e) {
        showToast('Fehler beim Importieren: ' + e, 'error');
        if (btn) {
            btn.disabled = false;
            btn.innerHTML = origHtml;
        }
    }
}

// Global Form Interceptor for SPA
        document.addEventListener('submit', async (e) => {
            const form = e.target;
            if (form && form.tagName === 'FORM') {
                const rawAction = form.getAttribute('action');
                if (rawAction && !rawAction.startsWith('javascript:')) {
                    e.preventDefault();
                    const actionUrl = rawAction;
                    const method = (form.getAttribute('method') || 'GET').toUpperCase();
                    const submitVal = e.submitter ? e.submitter.value : '';
                    const submitBtn = e.submitter || null;
                    const origBtnHtml = submitBtn ? submitBtn.innerHTML : '';
                    // Wichtig: FormData VOR submitBtn.disabled = true erzeugen, da deaktivierte
                    // Submit-Buttons sonst vom Browser aus FormData ausgeschlossen werden!
                    let formData = null;
                    if (method === 'POST') {
                        formData = new FormData(form, e.submitter);
                        if (submitBtn && submitBtn.name && !formData.has(submitBtn.name)) {
                            formData.set(submitBtn.name, submitBtn.value || '');
                        }
                    }
                    if (submitVal === 'delete' || submitVal === 'rerender') {
                        const cardVideo = form.closest('.studio-clip-card')?.querySelector('video');
                        if (cardVideo) {
                            try {
                                cardVideo.pause();
                                cardVideo.querySelectorAll('source').forEach(s => s.remove());
                                cardVideo.removeAttribute('src');
                                cardVideo.load();
                            } catch (_) {}
                            await new Promise(r => setTimeout(r, 80));
                        }
                    }
                    if (submitBtn) {
                        submitBtn.disabled = true;
                        submitBtn.classList.add('opacity-70');
                    }
                    if (submitVal === 'rerender') {
                        const renderCard = document.getElementById('render-progress-card');
                        if (renderCard) renderCard.classList.remove('hidden');
                        showToast('Neu-Rendern gestartet (Untertitel & Layout werden aktualisiert)...', 'info');
                        updateStatus();
                    }
                    try {
                        let options = {
                            method,
                            headers: { 'X-Requested-With': 'fetch' }
                        };
                        if (method === 'POST') {
                            options.body = formData;
                        }
                        const res = await apiFetch(actionUrl, options);
                        if (!res.ok) {
                            let errDetail = `HTTP ${res.status}`;
                            try {
                                const errJson = await res.json();
                                if (errJson && errJson.error) errDetail = errJson.error;
                            } catch (_) {}
                            throw new Error(errDetail);
                        }
                        await refreshDashboard(true);
                        if (submitVal === 'delete') {
                            showToast('Clip aus Studio gelöscht.', 'info');
                        } else if (submitVal === 'rerender') {
                            showToast('Short erfolgreich neu gerendert!', 'success');
                        } else if (submitVal === 'schedule') {
                            showToast('Clip im Veröffentlichungs-Zeitplan eingereiht!', 'success');
                        } else if (submitVal === 'publish_now') {
                            showToast('Veröffentlichung gestartet!', 'success');
                        } else if (actionUrl.startsWith('/save/')) {
                            showToast('Änderungen & Untertiteltext gespeichert!', 'success');
                        }
                    } catch (err) {
                        console.error('Form submission failed:', err);
                        alert('Aktion fehlgeschlagen: ' + err);
                    } finally {
                        if (submitBtn) {
                            submitBtn.disabled = false;
                            submitBtn.classList.remove('opacity-70');
                            if (origBtnHtml) submitBtn.innerHTML = origBtnHtml;
                        }
                    }
                }
            }
        });

        // Explicitly attach all interactive functions to window
        window.exportAllReadyClips = exportAllReadyClips;
        window.switchTab = switchTab;
        window.addStreamerFromForm = addStreamerFromForm;
        window.__realOpenCropModal = openCropModal;
        window.__realOpenRawPreview = openRawPreview;
        window.openStreamerModal = openStreamerModal;
        window.closeStreamerModal = closeStreamerModal;
        window.openStreamerConfigModal = openStreamerConfigModal;
        window.closeStreamerConfigModal = closeStreamerConfigModal;
        window.saveStreamerConfig = saveStreamerConfig;
        window.loadSampleClipForStreamer = loadSampleClipForStreamer;
        window.loadSampleClipDirect = loadSampleClipDirect;
        window.filterStreamersList = filterStreamersList;
        window.applyBulkMinViewsFromInput = applyBulkMinViewsFromInput;
        window.loadStreamerConfigIntoForm = openStreamerConfigModal;
        window.__realSaveStreamerConfig = saveStreamerConfig;
        window.__realLoadSampleClipForStreamer = loadSampleClipForStreamer;
        window.__realLoadSampleClipDirect = loadSampleClipDirect;
        window.__realOpenStreamerConfigModal = openStreamerConfigModal;
        window.openSettingsModal = openSettingsModal;
        window.closeSettingsModal = closeSettingsModal;
        window.saveSettingsFromForm = saveSettingsFromForm;
        window.loadSettingsIntoForm = loadSettingsIntoForm;
        window.updateStreamerMinViews = updateStreamerMinViews;
        window.updateStreamerMaxClips = updateStreamerMaxClips;
        window.updateStreamerLayout = updateStreamerLayout;
        window.saveAsDefaultStreamerLayout = saveAsDefaultStreamerLayout;
        window.applyBulkMinViews = applyBulkMinViews;
        window.filterStudioByStreamer = filterStudioByStreamer;
        window.toggleStudioStreamerFilter = toggleStudioStreamerFilter;
        window.clearStudioStreamerFilter = clearStudioStreamerFilter;
        window.toggleQueueStreamerFilter = toggleQueueStreamerFilter;
        window.clearQueueStreamerFilter = clearQueueStreamerFilter;
        window.triggerRun = triggerRun;
        window.__realTriggerRun = triggerRun;
        window.showToast = showToast;
        window.processAll = processAll;
        window.openCropModal = openCropModal;
        window.closeCropModal = closeCropModal;
        window.openRawPreview = openRawPreview;
        window.closePreviewModal = closePreviewModal;
        window.deleteSingleQueueClip = deleteSingleQueueClip;
        window.deleteOlderQueue = deleteOlderQueue;
        window.processOneClip = processOneClip;
        window.scheduleSingleClip = scheduleSingleClip;
        window.publishNow = publishNow;
        window.cancelSchedule = cancelSchedule;
        window.toggleManualPublished = toggleManualPublished;
        window.removeStreamer = removeStreamer;
        window.applyPreset = applyPreset;
        window.seekCropVideo = seekCropVideo;
        window.toggleCropVideoPlay = toggleCropVideoPlay;
        window.setCamPixelWidth = setCamPixelWidth;
        window.setGamePixelWidth = setGamePixelWidth;
        window.startTikTokBrowserLogin = startTikTokBrowserLogin;
        window.startYouTubeOAuthLogin = startYouTubeOAuthLogin;
        window.switchCropMode = switchCropMode;
        window.toggleCamEnabled = toggleCamEnabled;
        window.toggleLogs = toggleLogs;
        window.saveCropCoordinates = saveCropCoordinates;
        window.detectFacecamInCropModal = detectFacecamInCropModal;
        window.refreshDashboard = refreshDashboard;
        window.updateStatus = updateStatus;
        window.selectManualTimeframe = selectManualTimeframe;
        window.searchManualStreamerClips = searchManualStreamerClips;
        window.closeManualSearchResults = closeManualSearchResults;
        window.importTwitchClipToStudio = importTwitchClipToStudio;
        window.escapeJs = escapeJs;

        window.addEventListener('error', (e) => {
            console.error('GLOBAL JS ERROR:', e.message, e.filename, e.lineno);
        });

        console.log('Clip Farming UI Engine initialized. All actions attached.');

        setInterval(updateStatus, 1500);
        updateStatus();
})();
