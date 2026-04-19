(function () {
    'use strict';

    const DRONE_ID = window.DRONE_ID;
    if (!DRONE_ID) {
        console.error('ARGUS: window.DRONE_ID not set; did the server inject it?');
    }
    const API = (path) => `/api/drones/${encodeURIComponent(DRONE_ID)}${path}`;

    const logEl = document.getElementById('log');
    const modePill = document.getElementById('mode-pill');
    const wsPill = document.getElementById('ws-pill');
    const vsPill = document.getElementById('vs-pill');
    const banner = document.getElementById('banner');
    const sticksEl = document.getElementById('sticks');
    const droneBadge = document.getElementById('drone-badge');
    if (droneBadge) droneBadge.textContent = DRONE_ID || '—';

    function escapeHtml(s) {
        return String(s).replace(/[&<>"']/g, c =>
            ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
    }

    function log(action, detail, isErr) {
        const li = document.createElement('li');
        const ts = new Date().toLocaleTimeString('en-US', { hour12: false });
        li.innerHTML =
            `<span class="log-ts">${ts}</span>` +
            `<span class="log-action${isErr ? ' log-err' : ''}">${escapeHtml(action)}</span>` +
            `<span class="log-detail">${escapeHtml(detail || '')}</span>`;
        logEl.insertBefore(li, logEl.firstChild);
        while (logEl.children.length > 50) logEl.removeChild(logEl.lastChild);
    }

    // ── Health + mode ───────────────────────────────────────────────
    async function loadHealth() {
        try {
            const res = await fetch(API(''));
            if (!res.ok) throw new Error(res.status + ' ' + res.statusText);
            const d = await res.json();
            const mode = d.mock ? 'mock' : 'live';
            modePill.textContent = 'MODE: ' + mode.toUpperCase();
            modePill.dataset.state = mode;
            log('health', `drone=${d.id}  rc=${d.rc_ip}  mock=${d.mock}`);
        } catch (e) {
            log('health', 'failed: ' + e.message, true);
        }
    }

    // ── Virtual-stick state ─────────────────────────────────────────
    function setVirtualStickOn(on) {
        if (on) {
            vsPill.textContent = 'Virtual Stick: ON';
            vsPill.dataset.state = 'on';
            banner.classList.add('banner--hidden');
            sticksEl.classList.remove('is-disabled');
        } else {
            vsPill.textContent = 'Virtual Stick: OFF';
            vsPill.dataset.state = 'off';
            banner.classList.remove('banner--hidden');
            sticksEl.classList.add('is-disabled');
        }
    }

    // ── HTTP actions ────────────────────────────────────────────────
    async function post(path) {
        const res = await fetch(path, { method: 'POST' });
        if (!res.ok) throw new Error(res.status + ' ' + res.statusText);
        return res.json();
    }

    function wire(buttonId, path, label, onSuccess) {
        document.getElementById(buttonId).addEventListener('click', async () => {
            try {
                const d = await post(path);
                log(label, d.response || 'OK');
                if (onSuccess) onSuccess();
            } catch (e) {
                log(label, 'failed: ' + e.message, true);
            }
        });
    }

    wire('btn-enable', API('/virtual-stick/enable'), 'enable VS', () => setVirtualStickOn(true));
    wire('btn-disable', API('/virtual-stick/disable'), 'DISABLE', () => setVirtualStickOn(false));
    wire('btn-takeoff', API('/takeoff'), 'takeoff');
    wire('btn-land', API('/land'), 'land');
    wire('btn-rth', API('/rth'), 'RTH');

    document.getElementById('btn-clear-log').addEventListener('click', () => {
        logEl.innerHTML = '';
    });

    // ── WebSocket stick stream ──────────────────────────────────────
    let ws = null;
    let reconnectDelay = 500;

    function wsConnect() {
        const proto = location.protocol === 'https:' ? 'wss' : 'ws';
        ws = new WebSocket(`${proto}://${location.host}/ws/drones/${encodeURIComponent(DRONE_ID)}/stick`);

        ws.addEventListener('open', () => {
            wsPill.textContent = 'WS: connected';
            wsPill.dataset.state = 'connected';
            reconnectDelay = 500;
            log('ws', 'connected');
        });

        ws.addEventListener('close', () => {
            wsPill.textContent = 'WS: reconnecting…';
            wsPill.dataset.state = 'disconnected';
            setTimeout(wsConnect, reconnectDelay);
            reconnectDelay = Math.min(reconnectDelay * 2, 5000);
        });

        ws.addEventListener('error', () => { /* close fires right after */ });
    }

    function sendSticks() {
        if (!ws || ws.readyState !== WebSocket.OPEN) return;
        ws.send(JSON.stringify({
            leftX: leftJoy.x,
            leftY: leftJoy.y,
            rightX: rightJoy.x,
            rightY: rightJoy.y,
        }));
    }

    // ── Joystick widget ─────────────────────────────────────────────
    class Joystick {
        constructor(canvasId, onChange) {
            this.canvas = document.getElementById(canvasId);
            this.ctx = this.canvas.getContext('2d');
            this.x = 0;
            this.y = 0;
            this.active = false;
            this.pointerId = null;
            this.onChange = onChange;
            this._attach();
            this.draw();
        }

        _attach() {
            const c = this.canvas;
            c.addEventListener('pointerdown', (e) => {
                if (this.pointerId !== null) return;
                this.pointerId = e.pointerId;
                c.setPointerCapture(e.pointerId);
                this.active = true;
                this._update(e);
                e.preventDefault();
            });
            c.addEventListener('pointermove', (e) => {
                if (!this.active || e.pointerId !== this.pointerId) return;
                this._update(e);
            });
            const end = (e) => {
                if (this.pointerId === null || e.pointerId !== this.pointerId) return;
                this.active = false;
                this.pointerId = null;
                this.x = 0;
                this.y = 0;
                this.onChange();
                this.draw();
            };
            c.addEventListener('pointerup', end);
            c.addEventListener('pointercancel', end);
            c.addEventListener('lostpointercapture', end);
        }

        _update(e) {
            const r = this.canvas.getBoundingClientRect();
            const W = this.canvas.width;
            const H = this.canvas.height;
            const maxR = W / 2 - 24;
            const sx = W / r.width;
            const sy = H / r.height;
            let dx = (e.clientX - r.left) * sx - W / 2;
            let dy = (e.clientY - r.top) * sy - H / 2;
            const len = Math.hypot(dx, dy);
            if (len > maxR) {
                dx = dx * maxR / len;
                dy = dy * maxR / len;
            }
            this.x = dx / maxR;
            this.y = -dy / maxR;
            this.onChange();
            this.draw();
        }

        draw() {
            const ctx = this.ctx;
            const W = this.canvas.width;
            const H = this.canvas.height;
            const cx = W / 2;
            const cy = H / 2;
            const maxR = W / 2 - 24;

            ctx.clearRect(0, 0, W, H);

            const bg = ctx.createRadialGradient(cx, cy, 0, cx, cy, maxR);
            bg.addColorStop(0, '#1a1f28');
            bg.addColorStop(1, '#0d1118');
            ctx.fillStyle = bg;
            ctx.beginPath();
            ctx.arc(cx, cy, maxR, 0, Math.PI * 2);
            ctx.fill();

            ctx.strokeStyle = '#2a3240';
            ctx.lineWidth = 2;
            ctx.stroke();

            ctx.strokeStyle = '#1a2028';
            ctx.lineWidth = 1;
            for (const frac of [0.33, 0.66]) {
                ctx.beginPath();
                ctx.arc(cx, cy, maxR * frac, 0, Math.PI * 2);
                ctx.stroke();
            }

            ctx.strokeStyle = '#232a35';
            ctx.beginPath();
            ctx.moveTo(cx - maxR, cy); ctx.lineTo(cx + maxR, cy);
            ctx.moveTo(cx, cy - maxR); ctx.lineTo(cx, cy + maxR);
            ctx.stroke();

            const kx = cx + this.x * maxR;
            const ky = cy - this.y * maxR;
            const knobR = 20;

            ctx.fillStyle = 'rgba(0, 0, 0, 0.5)';
            ctx.beginPath();
            ctx.arc(kx, ky + 3, knobR, 0, Math.PI * 2);
            ctx.fill();

            const kGrad = ctx.createRadialGradient(kx - 5, ky - 5, 0, kx, ky, knobR);
            if (this.active) {
                kGrad.addColorStop(0, '#a0dcff');
                kGrad.addColorStop(1, '#3eb4ff');
            } else {
                kGrad.addColorStop(0, '#6e7c8a');
                kGrad.addColorStop(1, '#4a5664');
            }
            ctx.fillStyle = kGrad;
            ctx.beginPath();
            ctx.arc(kx, ky, knobR, 0, Math.PI * 2);
            ctx.fill();

            ctx.strokeStyle = this.active ? '#cce8ff' : '#7a8592';
            ctx.lineWidth = 1.5;
            ctx.stroke();

            ctx.fillStyle = this.active ? '#bde3ff' : '#5a6572';
            ctx.font = '11px ui-monospace, SFMono-Regular, monospace';
            ctx.textAlign = 'center';
            ctx.textBaseline = 'alphabetic';
            const xs = (this.x >= 0 ? '+' : '') + this.x.toFixed(2);
            const ys = (this.y >= 0 ? '+' : '') + this.y.toFixed(2);
            ctx.fillText(`x ${xs}   y ${ys}`, cx, H - 10);
        }
    }

    const leftJoy = new Joystick('left-stick', sendSticks);
    const rightJoy = new Joystick('right-stick', sendSticks);

    setVirtualStickOn(false);
    loadHealth();
    wsConnect();

    const linkNewTab = document.getElementById('link-video-new-tab');
    if (linkNewTab && DRONE_ID) {
        linkNewTab.href = `/video?drone=${encodeURIComponent(DRONE_ID)}`;
    }

    // ── Tab switching ───────────────────────────────────────────────
    const tabs = document.querySelectorAll('.tab');
    const panels = document.querySelectorAll('.tab-panel');
    let videoStarted = false;

    function activateTab(name) {
        tabs.forEach(t => t.classList.toggle('is-active', t.dataset.tab === name));
        panels.forEach(p => p.classList.toggle('is-active', p.dataset.panel === name));
        if (name === 'video' && !videoStarted) {
            startVideo();
            videoStarted = true;
        }
    }
    tabs.forEach(t => t.addEventListener('click', () => activateTab(t.dataset.tab)));

    // ── Video tab logic ─────────────────────────────────────────────
    const videoImg = document.getElementById('video-img');
    const videoPlaceholder = document.getElementById('video-placeholder');
    const videoMeta = document.getElementById('video-meta');
    const videoPill = document.getElementById('video-pill');

    function startVideo() {
        videoImg.addEventListener('load', () => {
            videoImg.classList.add('is-loaded');
            videoPlaceholder.classList.add('is-hidden');
        }, { once: true });
        videoImg.addEventListener('error', () => {
            videoMeta.textContent = 'stream error — check phone app';
            videoMeta.className = 'video-meta is-warn';
        });
        videoImg.src = API('/video.mjpg') + '?t=' + Date.now();
    }

    document.getElementById('btn-video-reload').addEventListener('click', () => {
        videoImg.classList.remove('is-loaded');
        videoPlaceholder.classList.remove('is-hidden');
        videoImg.src = '';
        setTimeout(() => { videoImg.src = API('/video.mjpg') + '?t=' + Date.now(); }, 50);
    });

    async function pollVideoStatus() {
        try {
            const r = await fetch(API('/video/status'));
            if (!r.ok) throw new Error(r.status);
            const s = await r.json();
            if (s.connected) {
                const label = `${s.mode.toUpperCase()} · ${s.width}×${s.height} · ${s.fps.toFixed(1)} fps`;
                videoMeta.textContent = label;
                videoMeta.className = 'video-meta is-ok';
                videoPill.textContent = 'VIDEO: ' + (s.mode === 'mock' ? 'MOCK' : `${s.fps.toFixed(0)} fps`);
                videoPill.dataset.state = 'streaming';
            } else {
                videoMeta.textContent = `${s.mode.toUpperCase()} · disconnected — retrying…`;
                videoMeta.className = 'video-meta is-warn';
                videoPill.textContent = 'VIDEO: OFF';
                videoPill.dataset.state = 'disconnected';
            }
        } catch {
            videoMeta.textContent = 'video: backend offline';
            videoMeta.className = 'video-meta is-warn';
            videoPill.textContent = 'VIDEO: —';
            videoPill.dataset.state = 'disconnected';
        }
    }
    pollVideoStatus();
    setInterval(pollVideoStatus, 1500);
})();
