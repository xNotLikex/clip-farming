
// ==========================================
// CLIENT-SIDE REACTIVE SPA ENGINE FOR TAURI & WEB
// ==========================================

const isTauri = typeof window !== 'undefined' && window.__TAURI__ !== undefined;

// Cam filters catalogue
const CAM_FILTERS = {'none': '🚫 Kein Filter (Original Facecam)', 'triangle': '🔺 3D Dreimacs Pyramide (Prismen-Kopf)', 'inv_triangle': '🔻 3D Trichter-Kopf (Megastirn, spitzes Kinn)', 'diamond': '💎 3D Diamant-Kopf (Kristall-Facette)', 'cube': '📦 3D Block-Kopf (Minecraft Steve)', 'gigachad': '🗿 3D Gigachad (Breiter Meme-Kiefer)', 'alien': '👽 3D Megamind / Alien (Riesen-Kuppelkopf)', 'hamster': '🎈 3D Hamsterbacken (Prall aufgeblasen)', 'pinocchio': '🤥 3D Pinocchio (Lange Nase)', 'big_eyes': '👀 3D Glubschaugen (Anime / Manga)', 'tiny_face': '🤏 3D Schrumpf-Gesicht (Charlie Kirk Meme)', 'big_mouth': '👄 3D Riesenmund (Scream / Opernsänger)', 'hourglass': '⏳ 3D Sanduhr (Wespentaille im Gesicht)', 'fisheye': '🐟 3D Glaskugel-Bulge (Linsen-Zoom)', 'swirl': '🌀 3D Strudel / Wirbel (Vortex-Twist)', 'wave': '🌊 3D Wackelpudding (Wobble-Welle)', 'mirror_left': '🪞 Doppel-Links (Alien-Symmetrie)', 'mirror_right': '🪞 Doppel-Rechts (Alien-Symmetrie)', 'stretch_vert': '📏 Bleistift-Kopf (Langgezogen)', 'squish_wide': '🗜️ Wide Meme (Pfannkuchen-Kopf)'};

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
    if (isTauri && window.__TAURI__.core && window.__TAURI__.core.invoke) {
        return await window.__TAURI__.core.invoke(command, args);
    } else {
        const res = await fetch('/api/' + command, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(args)
        });
        return await res.json();
    }
}

// Global state cache
let gDashboardData = null;

// Initial load & periodic refresh
async function refreshDashboard() {
    try {
        let data;
        if (isTauri && window.__TAURI__.core && window.__TAURI__.core.invoke) {
            data = await window.__TAURI__.core.invoke('get_dashboard_data');
        } else {
            const res = await fetch('/api/dashboard');
            data = await res.json();
        }
        if (data) {
            gDashboardData = data;
            renderDashboard(data);
        }
    } catch (err) {
        console.error('Failed to refresh dashboard data:', err);
    }
}

function renderDashboard(data) {
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
    renderStudio(data.ready_clips, data.streamer_counts);
    renderPlanner(data.scheduled_clips);
    renderPublished(data.published_clips);
    renderStreamers(data.streamers);
}

// ----------------------------------------
// 1. WARTESCHLANGE (QUEUE)
// ----------------------------------------
function renderQueue(clips, olderCount) {
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

    if (!clips || clips.length === 0) {
        if (tbody) tbody.innerHTML = `<tr><td colspan="8" class="py-12 text-center text-slate-500">Keine Clips in der Warteschlange.</td></tr>`;
        if (emptyState) emptyState.classList.remove('hidden');
        return;
    }
    if (emptyState) emptyState.classList.add('hidden');

    if (!tbody) return;
    tbody.innerHTML = clips.map(clip => `
        <tr onclick="openRawPreview('${escapeJs(clip.clip_id)}', '${escapeJs(clip.streamer)}', '${escapeJs(clip.original_title)}', '${clip.view_count}', '${Math.round(clip.duration)}', '${escapeJs(clip.created_ago || '')}', '${escapeJs(clip.created_full || '')}')"
            class="hover:bg-slate-800/40 transition cursor-pointer group">
            <td class="py-3.5 px-4 font-bold text-purple-400 whitespace-nowrap">${escapeHtml(clip.streamer)}</td>
            <td class="py-3.5 px-4 font-medium text-slate-200">
                <div class="line-clamp-2" title="${escapeHtml(clip.original_title)}">${escapeHtml(clip.original_title)}</div>
            </td>
            <td class="py-3.5 px-4 whitespace-nowrap" title="${escapeHtml(clip.created_full || '')}">
                <div class="flex items-center gap-1.5 text-slate-300 font-medium">
                    <span>📅</span> ${escapeHtml(clip.created_ago || '-')}
                </div>
                ${clip.created_full ? `<span class="text-[11px] text-slate-500 block">${escapeHtml(clip.created_full)}</span>` : ''}
            </td>
            <td class="py-3.5 px-4 text-slate-300 font-semibold whitespace-nowrap">👁️ ${clip.view_count}</td>
            <td class="py-3.5 px-4 text-slate-400 whitespace-nowrap">${Math.round(clip.duration)}s</td>
            <td class="py-3.5 px-4 text-right space-x-2 whitespace-nowrap" onclick="event.stopPropagation()">
                <button onclick="processOneClip('${clip.clip_id}')" class="px-3 py-1.5 bg-gradient-to-r from-purple-600 to-indigo-600 hover:from-purple-500 hover:to-indigo-500 font-bold text-xs rounded-lg shadow-md text-white transition active:scale-95">
                    ✂️ Zuschneiden & Verarbeiten
                </button>
                <button onclick="openCropModal('${clip.clip_id}', '${escapeJs(clip.streamer)}', '${escapeJs(clip.original_title)}')" class="px-3 py-1.5 bg-slate-800 hover:bg-slate-700 border border-slate-700 font-bold text-xs rounded-lg text-slate-200 transition">
                    🎛️ Manuell zuschneiden
                </button>
                <button onclick="deleteSingleQueueClip('${clip.clip_id}')" class="px-2.5 py-1.5 bg-rose-950/60 hover:bg-rose-900 border border-rose-900/50 font-bold text-xs rounded-lg text-rose-300 hover:text-white transition" title="Löschen">
                    🗑️
                </button>
            </td>
        </tr>
    `).join('');
}

async function processOneClip(clipId) {
    try {
        await fetch('/process-one/' + clipId, { method: 'POST' });
        updateStatus();
    } catch (e) {
        console.error(e);
    }
}

async function deleteSingleQueueClip(clipId) {
    if (!confirm('Clip unwiderruflich aus der Warteschlange löschen?')) return;
    try {
        if (isTauri && window.__TAURI__.core && window.__TAURI__.core.invoke) {
            await window.__TAURI__.core.invoke('delete_queue_clip', { clipId });
        } else {
            await fetch('/queue/delete/' + clipId, { method: 'POST' });
        }
        refreshDashboard();
    } catch (e) {
        alert('Fehler beim Löschen: ' + e);
    }
}

async function deleteOlderQueue() {
    if (!confirm('Wirklich alle Roh-Clips von gestern und älter löschen?\n\n(Clips von heute bleiben vollständig erhalten)')) return;
    try {
        await fetch('/queue/delete-older', { method: 'POST' });
        refreshDashboard();
    } catch (e) {
        alert('Fehler: ' + e);
    }
}

// ----------------------------------------
// 2. STUDIO & FREIGABE
// ----------------------------------------
function renderStudio(clips, streamerCounts) {
    const grid = document.getElementById('studio-grid');
    const emptyState = document.getElementById('studio-empty-state');
    const pillsContainer = document.getElementById('streamer-pills-container');

    // Render Streamer Filter Pills
    if (pillsContainer && streamerCounts) {
        const totalCount = clips ? clips.length : 0;
        let pillsHtml = `
            <button onclick="filterStudioByStreamer('all')" id="pill-all" class="streamer-pill active px-3.5 py-1.5 rounded-xl text-xs font-bold bg-purple-600 text-white transition shadow">
                Alle (${totalCount})
            </button>
        `;
        for (const [stName, count] of Object.entries(streamerCounts)) {
            pillsHtml += `
                <button onclick="filterStudioByStreamer('${stName.toLowerCase()}')" id="pill-${stName.toLowerCase()}" class="streamer-pill px-3.5 py-1.5 rounded-xl text-xs font-bold bg-slate-800 text-slate-300 hover:bg-slate-700 transition">
                    ${stName} (${count})
                </button>
            `;
        }
        pillsContainer.innerHTML = pillsHtml;
    }

    if (!clips || clips.length === 0) {
        if (grid) grid.innerHTML = '';
        if (emptyState) emptyState.classList.remove('hidden');
        return;
    }
    if (emptyState) emptyState.classList.add('hidden');

    if (!grid) return;
    grid.innerHTML = clips.map(clip => `
        <div class="bg-slate-900 border border-slate-800 rounded-2xl overflow-hidden shadow-xl flex flex-col hover:border-slate-700 transition-all duration-300 studio-clip-card ${clip.is_manually_published ? 'opacity-40 grayscale hover:grayscale-0 hover:opacity-95 border-emerald-900/80 bg-slate-950/90' : ''}" id="card-${clip.clip_id}" data-streamer="${escapeHtml(clip.streamer.toLowerCase())}">
            <!-- Header -->
            <div class="flex justify-between items-center bg-slate-950/90 px-4 py-2.5 border-b border-slate-800">
                <div class="flex items-center gap-2">
                    <span class="bg-purple-600/90 text-xs font-bold px-2.5 py-1 rounded-md shadow text-white">
                        ${escapeHtml(clip.streamer)}
                    </span>
                    ${clip.created_ago ? `
                    <span class="text-[11px] text-slate-400 font-medium whitespace-nowrap" title="${escapeHtml(clip.created_full || '')}">
                        📅 ${escapeHtml(clip.created_ago)}
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
                <video controls preload="metadata" class="w-full h-full object-contain">
                    <source src="/video/${clip.clip_id}" type="video/mp4">
                </video>
                ` : `
                <div class="text-center p-6 text-slate-500">
                    <span class="text-4xl block mb-2 animate-bounce">⏳</span>
                    Video wird gerendert...
                </div>
                `}
                <span class="absolute top-3 right-3 bg-slate-900/80 text-xs text-slate-300 font-semibold px-2 py-1 rounded-md backdrop-blur">
                    👁️ ${clip.view_count}
                </span>
                ${clip.has_video ? `
                <a href="/download/short/${clip.clip_id}" class="absolute bottom-3 right-3 bg-slate-900/90 hover:bg-emerald-600 text-white text-xs font-bold px-3 py-1.5 rounded-lg shadow-lg border border-slate-700/80 backdrop-blur transition flex items-center gap-1.5" title="Fertiges 9:16 Short in HQ herunterladen">
                    <span>💾</span> HQ Download
                </a>
                ` : ''}
            </div>

            <!-- Edit Form -->
            <form action="/save/${clip.clip_id}" method="POST" class="p-5 flex-1 flex flex-col justify-between gap-4">
                <div class="space-y-3">
                    <div>
                        <label class="block text-xs font-semibold text-pink-400 uppercase tracking-wider mb-1 flex justify-between">
                            <span>💬 TikTok / Shorts Sprechblasen-Hook</span>
                            <span class="text-slate-500 font-normal">Mitte</span>
                        </label>
                        <input type="text" name="sticker_text" value="${escapeHtml(clip.sticker_text || '')}" placeholder="z. B. Was macht er da?!" class="w-full bg-slate-800/90 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-pink-500">
                    </div>

                    <div>
                        <label class="block text-xs font-semibold text-slate-300 uppercase tracking-wider mb-1">
                            📝 Titel (YouTube / TikTok)
                        </label>
                        <input type="text" name="title" value="${escapeHtml(clip.title || '')}" class="w-full bg-slate-800/90 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-purple-500">
                    </div>

                    <div>
                        <label class="block text-xs font-semibold text-amber-400 uppercase tracking-wider mb-1">
                            💬 Untertitel-Platzierung
                        </label>
                        <select name="sub_position" class="w-full bg-slate-800/90 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-amber-500">
                            <option value="bottom" ${clip.sub_position === 'bottom' ? 'selected' : ''}>📌 Unten (Standard, über Shorts-UI)</option>
                            <option value="center" ${clip.sub_position === 'center' ? 'selected' : ''}>📌 Mitte (Unteres Drittel über Game)</option>
                            <option value="top" ${clip.sub_position === 'top' ? 'selected' : ''}>📌 Oben (Über Facecam)</option>
                            <option value="none" ${clip.sub_position === 'none' ? 'selected' : ''}>🚫 Keine Untertitel</option>
                        </select>
                    </div>

                    <div>
                        <label class="block text-xs font-semibold text-purple-400 uppercase tracking-wider mb-1">
                            📐 Video-Layout & Aufteilung
                        </label>
                        <select name="layout_mode" class="w-full bg-slate-800/90 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-purple-500">
                            <option value="auto" ${clip.layout_mode === 'auto' ? 'selected' : ''}>🤖 Automatisch (KI erkennt Facecam)</option>
                            <option value="custom" ${clip.layout_mode === 'custom' ? 'selected' : ''}>🎯 Benutzerdefiniert (Visuelle Rahmen)</option>
                            <option value="single_916" ${clip.layout_mode === 'single_916' ? 'selected' : ''}>📱 Reines 9:16 Vollbild (IRL)</option>
                            <option value="split_cam_top" ${clip.layout_mode === 'split_cam_top' ? 'selected' : ''}>✂️ Split-Screen (Cam oben, Game unten)</option>
                            <option value="blur_stack" ${clip.layout_mode === 'blur_stack' ? 'selected' : ''}>🌫️ Blur-Stack (Hintergrund unscharf)</option>
                        </select>
                        <button type="button" onclick="openCropModal('${clip.clip_id}', '${escapeJs(clip.streamer)}', '${escapeJs(clip.title || '')}')" class="w-full mt-2 py-2 px-3 bg-gradient-to-r from-purple-900/70 to-indigo-900/70 hover:from-purple-800 hover:to-indigo-800 border border-purple-500/60 hover:border-purple-400 text-purple-200 hover:text-white rounded-lg text-xs font-bold transition flex items-center justify-center gap-2 shadow">
                            <span>🎯</span> Bildausschnitt anpassen (Split-Cam oder IRL 9:16)
                        </button>
                    </div>

                    <div>
                        <label class="block text-xs font-semibold text-emerald-400 uppercase tracking-wider mb-1 flex justify-between">
                            <span>🎭 Cam-Filter / Effekt (Snapchat-Style)</span>
                            <span class="text-slate-500 font-normal">Fun-Warp für Facecam</span>
                        </label>
                        <select name="cam_filter" class="w-full bg-slate-800/90 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-emerald-500">
                            ${Object.entries(CAM_FILTERS).map(([k, label]) => `
                                <option value="${k}" ${clip.cam_filter === k ? 'selected' : ''}>${escapeHtml(label)}</option>
                            `).join('')}
                        </select>
                    </div>
                </div>

                <div class="pt-3 border-t border-slate-800 flex items-center gap-3">
                    <button type="submit" class="flex-1 py-2.5 bg-purple-600 hover:bg-purple-500 text-white font-bold text-xs rounded-xl shadow-md transition active:scale-95 flex items-center justify-center gap-1.5">
                        <span>💾</span> Speichern
                    </button>
                    <button type="button" onclick="scheduleSingleClip('${clip.clip_id}')" class="px-3.5 py-2.5 bg-sky-600 hover:bg-sky-500 text-white font-bold text-xs rounded-xl shadow-md transition active:scale-95 flex items-center justify-center gap-1.5" title="Im Zeitplan eintragen">
                        <span>🚀</span> Einplanen
                    </button>
                </div>
            </form>
        </div>
    `).join('');
}

async function scheduleSingleClip(clipId) {
    try {
        await fetch('/schedule-one/' + clipId, { method: 'POST' });
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
            <td class="py-3.5 px-4 font-bold text-purple-400">${escapeHtml(clip.streamer)}</td>
            <td class="py-3.5 px-4 text-slate-200">
                <div class="font-medium line-clamp-1">${escapeHtml(clip.ai_title || clip.original_title)}</div>
            </td>
            <td class="py-3.5 px-4 text-sky-400 font-mono text-xs whitespace-nowrap">
                <span>⏰</span> ${escapeHtml(clip.scheduled_publish_at || '-')}
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
        await fetch('/schedule/publish-now/' + clipId, { method: 'POST' });
        refreshDashboard();
    } catch (e) {
        alert('Fehler: ' + e);
    }
}

async function cancelSchedule(clipId) {
    try {
        await fetch('/schedule/cancel/' + clipId, { method: 'POST' });
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
            <td class="py-3.5 px-4 font-bold text-purple-400">${escapeHtml(clip.streamer)}</td>
            <td class="py-3.5 px-4 text-slate-200">
                <div class="font-medium line-clamp-1">${escapeHtml(clip.ai_title || clip.original_title)}</div>
            </td>
            <td class="py-3.5 px-4 text-slate-400 font-mono text-xs whitespace-nowrap">
                ${escapeHtml(clip.published_at || '-')}
            </td>
            <td class="py-3.5 px-4 text-right">
                ${clip.youtube_video_id ? `
                <a href="https://youtube.com/shorts/${clip.youtube_video_id}" target="_blank" class="text-xs text-red-400 hover:text-red-300 font-bold flex items-center gap-1 justify-end">
                    <span>▶️</span> Auf YouTube ansehen
                </a>
                ` : `
                <span class="text-xs text-slate-500">Erledigt</span>
                `}
            </td>
        </tr>
    `).join('');
}

// ----------------------------------------
// 5. STREAMER MANAGEMENT MODAL
// ----------------------------------------
function renderStreamers(streamers) {
    const container = document.getElementById('streamer-modal-list');
    if (!container || !streamers) return;

    container.innerHTML = streamers.map(s => `
        <div class="flex justify-between items-center bg-slate-800/80 border border-slate-700/80 px-3.5 py-2.5 rounded-xl hover:border-slate-600 transition">
            <div class="flex items-center gap-3">
                <span class="font-bold text-sm text-purple-300">${escapeHtml(s.name)}</span>
                <span class="text-xs bg-slate-700 text-slate-400 px-2 py-0.5 rounded-md font-mono">Min. ${s.min_clip_views} Views</span>
                <span class="text-xs bg-slate-700 text-slate-400 px-2 py-0.5 rounded-md font-mono">Max. ${s.max_clips_per_run} Clips</span>
            </div>
            <button onclick="removeStreamer('${escapeJs(s.name)}')" class="text-rose-400 hover:text-rose-300 p-1.5 hover:bg-rose-950/50 rounded-lg transition" title="Entfernen">
                🗑️
            </button>
        </div>
    `).join('');
}

async function removeStreamer(name) {
    if (!confirm('Streamer ' + name + ' wirklich entfernen?')) return;
    try {
        await fetch('/api/streamers/remove/' + encodeURIComponent(name), { method: 'POST' });
        refreshDashboard();
    } catch (e) {
        alert('Fehler: ' + e);
    }
}

// ----------------------------------------
// INITIALIZATION
// ----------------------------------------
window.addEventListener('DOMContentLoaded', () => {
    refreshDashboard();
    setInterval(refreshDashboard, 5000);
});



        function openStreamerModal() {
            document.getElementById('streamer-modal').classList.remove('hidden');
        }

        function closeStreamerModal() {
            document.getElementById('streamer-modal').classList.add('hidden');
        }

        function filterStudioByStreamer(streamerName) {
            document.querySelectorAll('.streamer-pill').forEach(btn => {
                btn.classList.remove('active', 'bg-purple-600', 'text-white');
                btn.classList.add('bg-slate-800', 'text-slate-300');
            });
            
            const activePill = document.getElementById('pill-' + streamerName);
            if (activePill) {
                activePill.classList.remove('bg-slate-800', 'text-slate-300');
                activePill.classList.add('active', 'bg-purple-600', 'text-white');
            }

            document.querySelectorAll('.studio-clip-card').forEach(card => {
                if (streamerName === 'all' || card.getAttribute('data-streamer') === streamerName) {
                    card.classList.remove('hidden');
                } else {
                    card.classList.add('hidden');
                }
            });
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
                await fetch('/api/clip/' + clipId + '/toggle-published', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ is_published: isChecked })
                });
            } catch (e) {
                console.error('Fehler beim Aktualisieren des Veröffentlichungs-Status:', e);
            }
        }
        function switchTab(tabId) {
            document.querySelectorAll('.tab-content').forEach(el => el.classList.add('hidden'));
            document.querySelectorAll('.tab-btn').forEach(el => el.classList.remove('active', 'text-purple-400'));
            
            const target = document.getElementById('tab-' + tabId);
            if (target) target.classList.remove('hidden');
            const btn = document.getElementById('tab-' + tabId + '-btn');
            if (btn) {
                btn.classList.add('active');
                btn.classList.remove('text-slate-400');
            }
        }

        let currentPreviewClipId = '';
        let currentPreviewStreamer = '';
        let currentPreviewTitle = '';

        function openRawPreview(clipId, streamer, title, views, duration, createdAgo = '', createdFull = '') {
            currentPreviewClipId = clipId;
            currentPreviewStreamer = streamer;
            currentPreviewTitle = title;
            document.getElementById('modal-streamer').innerText = streamer.toUpperCase();
            document.getElementById('modal-title').innerText = title;
            let statsText = '👁️ ' + views + ' Views • ⏱️ ' + duration + 's (Rohdatei auf Festplatte)';
            if (createdAgo) {
                statsText += ' • 📅 Erstellt: ' + createdAgo;
            }
            const statsElem = document.getElementById('modal-stats');
            statsElem.innerText = statsText;
            if (createdFull) {
                statsElem.title = createdFull;
            }
            
            const player = document.getElementById('modal-video-player');
            player.src = '/raw-video/' + clipId;
            player.load();
            player.play();

            document.getElementById('modal-process-form').action = '/process-one/' + clipId;
            document.getElementById('modal-delete-form').action = '/queue/delete/' + clipId;
            document.getElementById('modal-download-raw').href = '/download/raw/' + clipId;
            document.getElementById('preview-modal').classList.remove('hidden');
        }

        function closePreviewModal() {
            const player = document.getElementById('modal-video-player');
            player.pause();
            player.src = '';
            document.getElementById('preview-modal').classList.add('hidden');
        }

        let logsOpen = false;
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

        async function triggerRun() {
            const btn = document.getElementById('btn-trigger');
            btn.disabled = true;
            btn.innerHTML = '<span>⏳</span> Scanne Twitch...';
            try {
                await fetch('/api/run', { method: 'POST' });
            } catch (e) {
                console.error(e);
            }
        }

        async function processAll() {
            const btn = document.getElementById('btn-process-all');
            if (btn) {
                btn.disabled = true;
                btn.innerHTML = '<span>⏳</span> Schneide alle Clips...';
            }
            try {
                await fetch('/api/process-all', { method: 'POST' });
                switchTab('studio');
            } catch (e) {
                console.error(e);
            }
        }

        async function updateStatus() {
            try {
                const res = await fetch('/api/status');
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
                    text.innerText = 'Aktiv: ' + data.status.toUpperCase();
                    desc.innerText = data.current_task + (data.streamer ? ' (' + data.streamer + ')' : '');
                    if (btn) {
                        btn.disabled = true;
                        btn.className = 'flex items-center gap-2 px-5 py-2.5 bg-slate-800 text-slate-400 font-bold text-sm rounded-xl cursor-not-allowed';
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
                    desc.innerText = data.current_task;
                    progressCard.classList.add('hidden');
                    if (btn) {
                        btn.disabled = false;
                        btn.className = 'flex items-center gap-2 px-5 py-2.5 bg-gradient-to-r from-purple-600 to-pink-600 hover:from-purple-500 hover:to-pink-500 font-bold text-sm rounded-xl shadow-lg shadow-purple-500/20 transition transform active:scale-95 text-white';
                        btn.innerHTML = '<span>⚡</span> Neue Clips auf Twitch suchen';
                    }
                }

                if (data.logs && data.logs.length > 0) {
                    document.getElementById('log-count').innerText = data.logs.length + ' Einträge';
                    const logBox = document.getElementById('log-box');
                    logBox.innerHTML = data.logs.slice(-30).map(l => '<div>' + l + '</div>').join('');
                    if (logsOpen) {
                        logBox.scrollTop = logBox.scrollHeight;
                    }
                }
            } catch (err) {
                console.error('Polling error:', err);
            }
        }

        // --- VISUELLER ZUSCHNITT & CROPPER ---
        let currentCropClipId = null;
        let currentCropTitle = '';
        let currentCropStreamer = '';
        let currentCropMode = 'split'; // 'split' oder 'single_916'
        let videoNativeWidth = 1920;
        let videoNativeHeight = 1080;
        let cropState = {
            cam: { x: 0.73, y: 0.64, w: 0.26, h: 0.34, enabled: true },
            game: { x: 0.245, y: 0.0, w: 0.51, h: 1.0, enabled: true },
            single: { x: (1 - (608 / 1920)) / 2, y: 0.0, w: 608 / 1920, h: 1.0, enabled: true }
        };
        let activeCropDrag = null;
        let cropVideoInitialized = false;

        function switchCropMode(mode) {
            currentCropMode = mode;
            const btnSplit = document.getElementById('btn-mode-split');
            const btnSingle = document.getElementById('btn-mode-single');
            const tbSplit = document.getElementById('toolbar-split');
            const tbSingle = document.getElementById('toolbar-single');
            const boxCam = document.getElementById('crop-box-cam');
            const boxGame = document.getElementById('crop-box-game');
            const boxSingle = document.getElementById('crop-box-single');

            if (mode === 'single_916') {
                if (btnSplit) {
                    btnSplit.className = 'flex-1 py-2 px-3 rounded-lg text-xs font-bold transition flex items-center justify-center gap-2 bg-slate-800 hover:bg-slate-700 text-slate-300';
                }
                if (btnSingle) {
                    btnSingle.className = 'flex-1 py-2 px-3 rounded-lg text-xs font-bold transition flex items-center justify-center gap-2 bg-gradient-to-r from-fuchsia-600 to-pink-600 text-white shadow-lg shadow-fuchsia-500/20';
                }
                if (tbSplit) tbSplit.classList.add('hidden');
                if (tbSingle) tbSingle.classList.remove('hidden');
                if (boxCam) boxCam.classList.add('hidden');
                if (boxGame) boxGame.classList.add('hidden');
                if (boxSingle) boxSingle.classList.remove('hidden');
                updateBoxDom('single');
            } else {
                if (btnSplit) {
                    btnSplit.className = 'flex-1 py-2 px-3 rounded-lg text-xs font-bold transition flex items-center justify-center gap-2 bg-gradient-to-r from-purple-600 to-indigo-600 text-white shadow-lg shadow-purple-500/20';
                }
                if (btnSingle) {
                    btnSingle.className = 'flex-1 py-2 px-3 rounded-lg text-xs font-bold transition flex items-center justify-center gap-2 bg-slate-800 hover:bg-slate-700 text-slate-300';
                }
                if (tbSplit) tbSplit.classList.remove('hidden');
                if (tbSingle) tbSingle.classList.add('hidden');
                if (boxCam && cropState.cam.enabled) boxCam.classList.remove('hidden');
                if (boxGame) boxGame.classList.remove('hidden');
                if (boxSingle) boxSingle.classList.add('hidden');
                updateBoxDom('cam');
                updateBoxDom('game');
            }
            draw916Preview();
        }

        async function openCropModal(clipId, streamer, title) {
            currentCropClipId = clipId;
            currentCropStreamer = streamer || '';
            currentCropTitle = title || '';

            const badge = document.getElementById('crop-modal-clip-badge');
            if (badge) badge.innerText = (streamer ? streamer + ': ' : '') + (title ? title.slice(0, 28) : clipId);

            const cardFilterSelect = document.querySelector(`form[action="/save/${clipId}"] select[name="cam_filter"]`);
            const filterVal = cardFilterSelect ? cardFilterSelect.value : 'none';
            const modalFilterSelect = document.getElementById('crop-cam-filter-select');
            if (modalFilterSelect) modalFilterSelect.value = filterVal;

            const modal = document.getElementById('crop-modal');
            modal.classList.remove('hidden');

            const vid = document.getElementById('crop-stage-video');
            vid.src = '/raw-video/' + clipId;
            vid.load();

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
                const resp = await fetch(`/api/clip/${clipId}/meta`);
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
                    if (meta.title) currentCropTitle = meta.title;
                    if (meta.cam_filter && modalFilterSelect) {
                        modalFilterSelect.value = meta.cam_filter;
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
            document.getElementById('crop-modal').classList.add('hidden');
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
                document.getElementById('crop-play-btn').innerHTML = '⏸️ Pause';
            });
            vid.addEventListener('pause', () => {
                document.getElementById('crop-play-btn').innerHTML = '▶️ Abspielen';
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
                if (hint) hint.innerText = '🔒 9:16 fest (Vollbild) • Mausrad / Ecken ziehen';

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
                if (hint) hint.innerText = '🔒 9:10 fest (Split) • Mausrad / Ecken ziehen';

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
                    readout.innerText = `📱 Reines 9:16 IRL: ${singlePx.w}x${singlePx.h} @ (${singlePx.x}, 0) • Feste 9:16 Proportion (100% Video-Höhe)`;
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
            btn.innerHTML = '<span>⏳</span> Erkenne...';
            btn.disabled = true;
            try {
                const resp = await fetch(`/api/clip/${currentCropClipId}/detect-cam`);
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
                btn.innerHTML = '<span>🤖</span> KI Auto-Erkennen';
                btn.disabled = false;
            }
        }

        function toggleCamEnabled() {
            cropState.cam.enabled = !cropState.cam.enabled;
            const btn = document.getElementById('btn-crop-toggle-cam');
            const vw = videoNativeWidth || 1920;
            const vh = videoNativeHeight || 1080;

            if (cropState.cam.enabled) {
                btn.innerText = '🚫 Keine Cam (Vollbild)';
                btn.className = 'px-2.5 py-1 bg-slate-800 hover:bg-rose-900/60 border border-slate-700 text-xs rounded-lg text-slate-300 transition';
                
                // Zu 9:10 Split-Format wechseln (Höhe beibehalten, Breite anpassen)
                const curHpx = Math.round(cropState.game.h * vh);
                const targetWpx = Math.round(curHpx * (9 / 10));
                setGamePixelWidth(targetWpx);
            } else {
                btn.innerText = '✅ Facecam wieder aktivieren';
                btn.className = 'px-2.5 py-1 bg-emerald-900/80 border border-emerald-500 text-xs font-bold rounded-lg text-emerald-200 transition';
                
                // Zu 9:16 Vollbild-Format wechseln (Höhe beibehalten, Breite anpassen)
                const curHpx = Math.round(cropState.game.h * vh);
                const targetWpx = Math.round(curHpx * (9 / 16));
                setGamePixelWidth(targetWpx);
            }
            updateBoxDom('cam');
            updateBoxDom('game');
            draw916Preview();
        }

        function draw916Preview() {
            const canvas = document.getElementById('crop-preview-canvas');
            if (!canvas) return;
            const ctx = canvas.getContext('2d');
            const vid = document.getElementById('crop-stage-video');
            if (!vid || vid.readyState < 2) return;

            const vw = vid.videoWidth || 1920;
            const vh = vid.videoHeight || 1080;

            ctx.fillStyle = '#05070e';
            ctx.fillRect(0, 0, 270, 480);

            if (currentCropMode === 'single_916') {
                // 📱 Reines 9:16 Vollbild (IRL) - 1:1 unverzerrt in 9:16 Canvas
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
                const titleText = currentCropTitle ? currentCropTitle.slice(0, 32) : '💬 TikTok / Shorts Hook';
                ctx.fillText(titleText, 135, stickerY);

            } else if (cropState.cam.enabled) {
                // 1. Top Section: Facecam (1080x720 in 1080x1920 -> 270x180 px)
                const cx = cropState.cam.x * vw;
                const cy = cropState.cam.y * vh;
                const cw = Math.max(16, cropState.cam.w * vw);
                const ch = Math.max(16, cropState.cam.h * vh);

                const filterVal = document.getElementById('crop-cam-filter-select')?.value || 'none';
                if (filterVal === 'triangle') {
                    // 🔺 3D Dreimacs Pyramide
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
                    // 🔻 3D Trichter-Kopf
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
                    // 💎 3D Diamant-Kopf
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
                    // 📦 3D Block-Kopf (Steve)
                    ctx.save();
                    ctx.beginPath();
                    ctx.rect(35, 15, 200, 150);
                    ctx.clip();
                    try { ctx.drawImage(vid, cx, cy, cw, ch, 0, 0, 270, 180); } catch(e) {}
                    ctx.restore();
                } else if (filterVal === 'alien') {
                    // 👽 3D Megamind / Alien (Riesen-Stirn)
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
                    // 🗿 3D Gigachad (Breiter Kiefer)
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
                    // 🎈 3D Hamsterbacken
                    try {
                        ctx.drawImage(vid, cx, cy, cw, ch, 0, 0, 270, 180);
                        ctx.drawImage(vid, cx, cy + ch * 0.4, cw, ch * 0.6, -15, 75, 300, 105);
                    } catch(e) {}
                } else if (filterVal === 'pinocchio') {
                    // 🤥 3D Pinocchio Langnase
                    try {
                        ctx.drawImage(vid, cx, cy, cw, ch, 0, 0, 270, 180);
                        ctx.drawImage(vid, cx + cw * 0.35, cy + ch * 0.35, cw * 0.3, ch * 0.3, 100, 75, 70, 95);
                    } catch(e) {}
                } else if (filterVal === 'big_eyes') {
                    // 👀 3D Glubschaugen (Anime)
                    try {
                        ctx.drawImage(vid, cx, cy, cw, ch, 0, 0, 270, 180);
                        ctx.drawImage(vid, cx + cw * 0.2, cy + ch * 0.2, cw * 0.6, ch * 0.35, 35, 30, 200, 80);
                    } catch(e) {}
                } else if (filterVal === 'tiny_face') {
                    // 🤏 3D Schrumpf-Gesicht (Meme)
                    try {
                        ctx.drawImage(vid, cx, cy, cw, ch, 0, 0, 270, 180);
                        ctx.drawImage(vid, cx + cw * 0.2, cy + ch * 0.2, cw * 0.6, ch * 0.6, 95, 65, 80, 80);
                    } catch(e) {}
                } else if (filterVal === 'big_mouth') {
                    // 👄 3D Riesenmund
                    try {
                        ctx.drawImage(vid, cx, cy, cw, ch, 0, 0, 270, 180);
                        ctx.drawImage(vid, cx + cw * 0.2, cy + ch * 0.55, cw * 0.6, ch * 0.4, 50, 100, 170, 75);
                    } catch(e) {}
                } else if (filterVal === 'hourglass') {
                    // ⏳ 3D Sanduhr / Wespentaille (Pinch)
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
                    // 🐟 3D Fischauge / Glaskugel
                    ctx.save();
                    ctx.beginPath();
                    ctx.ellipse(135, 90, 130, 86, 0, 0, Math.PI * 2);
                    ctx.clip();
                    try { ctx.drawImage(vid, cx + cw * 0.1, cy + ch * 0.1, cw * 0.8, ch * 0.8, 0, 0, 270, 180); } catch(e) {}
                    ctx.restore();
                } else if (filterVal === 'mirror_left') {
                    // 🪞 Doppel-Links: Linke Hälfte auf rechts gespiegelt
                    try {
                        ctx.drawImage(vid, cx, cy, cw / 2, ch, 0, 0, 135, 180);
                        ctx.save();
                        ctx.translate(270, 0);
                        ctx.scale(-1, 1);
                        ctx.drawImage(vid, cx, cy, cw / 2, ch, 0, 0, 135, 180);
                        ctx.restore();
                    } catch(e) {}
                } else if (filterVal === 'mirror_right') {
                    // 🪞 Doppel-Rechts: Rechte Hälfte auf links gespiegelt
                    try {
                        ctx.drawImage(vid, cx + cw / 2, cy, cw / 2, ch, 135, 0, 135, 180);
                        ctx.save();
                        ctx.translate(135, 0);
                        ctx.scale(-1, 1);
                        ctx.drawImage(vid, cx + cw / 2, cy, cw / 2, ch, 0, 0, 135, 180);
                        ctx.restore();
                    } catch(e) {}
                } else if (filterVal === 'stretch_vert') {
                    // 📏 Bleistift-Kopf
                    try {
                        ctx.drawImage(vid, cx + cw * 0.22, cy, cw * 0.56, ch, 0, 0, 270, 180);
                    } catch(e) {}
                } else if (filterVal === 'squish_wide') {
                    // 🗜️ Wide Meme
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
                        triangle: '🔺 3D Dreimacs Pyramide',
                        inv_triangle: '🔻 3D Trichter-Kopf',
                        diamond: '💎 3D Diamant-Kopf',
                        cube: '📦 3D Block-Kopf',
                        gigachad: '🗿 3D Gigachad Kiefer',
                        alien: '👽 3D Megamind Alien',
                        hamster: '🎈 3D Hamsterbacken',
                        pinocchio: '🤥 3D Pinocchio Langnase',
                        big_eyes: '👀 3D Glubschaugen',
                        tiny_face: '🤏 3D Schrumpf-Gesicht',
                        big_mouth: '👄 3D Riesenmund',
                        hourglass: '⏳ 3D Sanduhr Pinch',
                        fisheye: '🐟 3D Glaskugel Fischauge',
                        swirl: '🌀 3D Strudel Twist',
                        wave: '🌊 3D Wackelpudding',
                        mirror_left: '🪞 Doppel-Links',
                        mirror_right: '🪞 Doppel-Rechts',
                        stretch_vert: '📏 Bleistift-Kopf',
                        squish_wide: '🗜️ Wide Meme'
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
                const titleText = currentCropTitle ? currentCropTitle.slice(0, 32) : '💬 TikTok / Shorts Hook';
                ctx.fillText(titleText, 135, 180);

            } else {
                // 📱 Reines Vollbild-Gameplay (Festes 9:16 Short)
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
                const titleText = currentCropTitle ? currentCropTitle.slice(0, 32) : '💬 TikTok / Shorts Hook';
                ctx.fillText(titleText, 135, stickerY);
            }

            // Subtitle Preview Simulation
            ctx.font = 'bold 11px sans-serif';
            ctx.textAlign = 'center';
            ctx.fillStyle = '#fde047';
            ctx.strokeStyle = '#000000';
            ctx.lineWidth = 2.5;
            ctx.strokeText("💬 [Untertitel Bereich]", 135, 435);
            ctx.fillText("💬 [Untertitel Bereich]", 135, 435);
        }

        async function saveCropCoordinates(renderNow) {
            if (!currentCropClipId) return;
            const vw = videoNativeWidth || 1920;
            const vh = videoNativeHeight || 1080;

            let editedTranscript = null;
            const formEl = document.getElementById('form-' + currentCropClipId);
            if (formEl) {
                const txEl = formEl.querySelector('textarea[name="transcript"]');
                if (txEl) editedTranscript = txEl.value;
            }

            let payload;
            if (currentCropMode === 'single_916') {
                payload = {
                    layout_mode: 'single_916',
                    render_now: renderNow,
                    transcript: editedTranscript,
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
                    layout_mode: 'custom',
                    render_now: renderNow,
                    transcript: editedTranscript,
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

            const modalFilterSelect = document.getElementById('crop-cam-filter-select');
            if (modalFilterSelect) {
                payload.cam_filter = modalFilterSelect.value;
                const cardFilterSelect = document.querySelector(`form[action="/save/${currentCropClipId}"] select[name="cam_filter"]`);
                if (cardFilterSelect) cardFilterSelect.value = modalFilterSelect.value;
            }

            try {
                const resp = await fetch(`/api/clip/${currentCropClipId}/save-crop`, {
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
                    }
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
                const resp = await fetch('/api/accounts/tiktok/browser-login', { method: 'POST' });
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

                const pollTimer = setInterval(async () => {
                    try {
                        const sResp = await fetch('/api/accounts/tiktok/browser-login/status');
                        const sData = await sResp.json();
                        if (text && sData.message) text.innerText = sData.message;

                        if (!sData.running) {
                            clearInterval(pollTimer);
                            if (sData.message && sData.message.includes('Erfolgreich')) {
                                if (text) text.innerText = '✅ Erfolgreich verbunden! Aktualisiere Dashboard...';
                                setTimeout(() => window.location.reload(), 1200);
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
                const resp = await fetch('/api/accounts/youtube/authorize', { method: 'POST' });
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
                if (text) text.innerText = '👉 Google-Login im neuen Tab geöffnet! Wähle deinen YouTube-Kanal und klicke auf "Zulassen"...';

                // Status überwachen bis YouTube auf verbunden springt
                const pollTimer = setInterval(async () => {
                    try {
                        const aResp = await fetch('/api/accounts/status');
                        const aData = await aResp.json();
                        if (aData && aData.youtube && aData.youtube.is_connected) {
                            clearInterval(pollTimer);
                            if (text) text.innerText = '✅ YouTube erfolgreich verbunden! Seite wird aktualisiert...';
                            setTimeout(() => window.location.reload(), 1500);
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

        setInterval(updateStatus, 1500);
        updateStatus();
    