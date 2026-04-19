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
        // Sim mode: update the on-screen joysticks only, no commands sent.
        if (window.__argusSim) return;
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

        setProgrammatic(x, y) {
            // External input (e.g. gamepad). Skip if the user is touching the widget.
            if (this.active) return;
            const nx = Math.max(-1, Math.min(1, x));
            const ny = Math.max(-1, Math.min(1, y));
            if (nx === this.x && ny === this.y) return;
            this.x = nx;
            this.y = ny;
            this.onChange();
            this.draw();
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

    // ── Inline video (always-on; video now sits between the sticks) ─
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
    startVideo();

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

    // ── Gamepad + SIM mode ──────────────────────────────────────────
    const padPill = document.getElementById('pad-pill');
    const simPill = document.getElementById('sim-pill');
    const togglePad = document.getElementById('toggle-pad');
    const toggleSim = document.getElementById('toggle-sim');
    const gimbalValEl = document.getElementById('gimbal-val');
    const sensSlider = document.getElementById('pad-sensitivity');
    const sensValEl = document.getElementById('pad-sensitivity-val');

    // Dead-zone for stick drift on Xbox/PS pads.
    const DEADZONE = 0.12;
    // Expo curve power — >1 makes small deflections extra gentle while still
    // letting full deflection reach 1.0. 2.0 = quadratic (noticeably softer).
    const EXPO_POWER = 2.0;

    // Sensitivity multiplier from the slider (0.10 – 1.00). Default 0.50.
    let sensitivity = sensSlider ? (parseInt(sensSlider.value, 10) / 100) : 0.5;
    function applySensitivity() {
        sensitivity = parseInt(sensSlider.value, 10) / 100;
        sensValEl.textContent = Math.round(sensitivity * 100) + '%';
    }
    if (sensSlider) {
        sensSlider.addEventListener('input', applySensitivity);
        applySensitivity();
    }
    // LT/RT trigger threshold to count as "held".
    const TRIGGER_THRESH = 0.08;
    // Gimbal pitch range matches backend validation: [-90°, +30°].
    const GIMBAL_MIN = -90;
    const GIMBAL_MAX = 30;
    // Send gimbal updates to the backend at most this often.
    const GIMBAL_SEND_INTERVAL_MS = 150;

    // SIM toggle default: ON — safer for first-time controller testing.
    window.__argusSim = toggleSim.checked;
    function syncSimPill() {
        simPill.textContent = 'SIM: ' + (window.__argusSim ? 'ON' : 'OFF');
        simPill.dataset.state = window.__argusSim ? 'on' : 'off';
    }
    syncSimPill();
    toggleSim.addEventListener('change', () => {
        window.__argusSim = toggleSim.checked;
        syncSimPill();
        log('sim', window.__argusSim ? 'on — commands are NOT sent to the drone' : 'off — live control');
    });

    function applyDeadzone(v) {
        if (Math.abs(v) < DEADZONE) return 0;
        // Re-scale so output ramps from 0 → 1 past the deadzone.
        const sign = v < 0 ? -1 : 1;
        return sign * (Math.abs(v) - DEADZONE) / (1 - DEADZONE);
    }

    // Combined shaping for gamepad sticks: deadzone → expo curve → sensitivity
    // scale. Output magnitude is bounded by `sensitivity` (≤ 1.0).
    function shapeStick(raw) {
        const dz = applyDeadzone(raw);
        if (dz === 0) return 0;
        const sign = dz < 0 ? -1 : 1;
        const curved = Math.pow(Math.abs(dz), EXPO_POWER);
        return sign * curved * sensitivity;
    }

    let lastGimbalSentAt = 0;
    let lastGimbalSentValue = null;
    let rafHandle = null;
    let lastActivePad = null;

    window.addEventListener('gamepadconnected', (e) => {
        lastActivePad = e.gamepad.index;
        if (togglePad.checked) setPadPill('connected', e.gamepad.id);
        log('gamepad', 'connected: ' + e.gamepad.id);
    });
    window.addEventListener('gamepaddisconnected', (e) => {
        if (lastActivePad === e.gamepad.index) lastActivePad = null;
        setPadPill('disconnected', '');
        log('gamepad', 'disconnected: ' + e.gamepad.id);
    });

    function setPadPill(state, detail) {
        if (state === 'connected') {
            padPill.textContent = 'PAD: ' + (detail ? detail.slice(0, 14) : 'OK');
        } else if (state === 'off') {
            padPill.textContent = 'PAD: OFF';
        } else {
            padPill.textContent = 'PAD: —';
        }
        padPill.dataset.state = state;
    }

    function pickGamepad() {
        const pads = navigator.getGamepads ? navigator.getGamepads() : [];
        if (!pads) return null;
        if (lastActivePad != null && pads[lastActivePad]) return pads[lastActivePad];
        for (const p of pads) if (p) return p;
        return null;
    }

    async function sendGimbal(pitch) {
        if (window.__argusSim) return;
        try {
            const res = await fetch(API('/gimbal/pitch'), {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ pitch }),
            });
            if (!res.ok) throw new Error(res.status + ' ' + res.statusText);
        } catch (e) {
            log('gimbal', 'send failed: ' + e.message, true);
        }
    }

    function tick() {
        rafHandle = null;
        const now = performance.now();

        if (!togglePad.checked) return;  // loop stopped

        const pad = pickGamepad();
        if (!pad) {
            setPadPill('disconnected', '');
            scheduleTick();
            return;
        }
        if (padPill.dataset.state !== 'connected') setPadPill('connected', pad.id);

        // Stick mapping. Xbox layout:
        //   axes[0] = LSB X (yaw)     axes[1] = LSB Y (throttle; up = -1)
        //   axes[2] = RSB X (roll)    axes[3] = RSB Y (pitch;    up = -1)
        // Stick values are softened with an expo curve and scaled by the
        // user's Sensitivity slider; triggers (gimbal) are left untouched.
        const lX = shapeStick(pad.axes[0] || 0);
        const lY = -shapeStick(pad.axes[1] || 0);   // invert so up = +
        const rX = shapeStick(pad.axes[2] || 0);
        const rY = -shapeStick(pad.axes[3] || 0);

        leftJoy.setProgrammatic(lX, lY);
        rightJoy.setProgrammatic(rX, rY);

        // Triggers: buttons[6] = LT, buttons[7] = RT. Analog on Xbox pads.
        // Direct mapping (hold = tilt, release = return to 0):
        //   RT at 0..1  → pitch 0..GIMBAL_MAX (tilt up)
        //   LT at 0..1  → pitch 0..GIMBAL_MIN (tilt down)
        // Nothing held → target = 0° so the gimbal re-centres.
        const lt = (pad.buttons[6] && pad.buttons[6].value) || 0;
        const rt = (pad.buttons[7] && pad.buttons[7].value) || 0;
        const ltMag = lt > TRIGGER_THRESH ? lt : 0;
        const rtMag = rt > TRIGGER_THRESH ? rt : 0;

        let targetPitch = rtMag * GIMBAL_MAX + ltMag * GIMBAL_MIN;
        if (targetPitch > GIMBAL_MAX) targetPitch = GIMBAL_MAX;
        if (targetPitch < GIMBAL_MIN) targetPitch = GIMBAL_MIN;
        gimbalValEl.textContent = targetPitch.toFixed(0) + '°';

        const rounded = Math.round(targetPitch * 10) / 10;
        if (now - lastGimbalSentAt > GIMBAL_SEND_INTERVAL_MS && rounded !== lastGimbalSentValue) {
            lastGimbalSentAt = now;
            lastGimbalSentValue = rounded;
            sendGimbal(rounded);
        }

        scheduleTick();
    }

    function scheduleTick() {
        if (rafHandle == null) rafHandle = requestAnimationFrame(tick);
    }

    togglePad.addEventListener('change', () => {
        if (togglePad.checked) {
            setPadPill('disconnected', '');  // will flip to connected on next tick if pad found
            scheduleTick();
            log('gamepad', 'enabled — press any button on the pad if not detected');
        } else {
            setPadPill('off', '');
            // Release the sticks so the deadman zeros out the drone.
            leftJoy.setProgrammatic(0, 0);
            rightJoy.setProgrammatic(0, 0);
            log('gamepad', 'disabled');
        }
    });
    setPadPill('off', '');
})();
