/**
 * Primary Kiosk Orchestrator - 2-Slide Physical Kiosk Port.
 */

let currentSlide = 1;
let autoCycleEnabled = true;
let slideTimerSecs = 45;
let slideIntervalHandle = null;
let ws = null;

const SLIDE_DURATIONS = {
    1: 45,  // 24-Hour Period (Time Domain)
    2: 20   // DFT Frequency Spectrum
};

document.addEventListener("DOMContentLoaded", () => {
    initClock();
    initSlide1Chart();
    initSlide3Chart(); // Slide 2 in this mode is DFT

    connectWebSocket();
    fetchAllDatasets();
    startSlideCycle();

    // Periodic background refreshes
    setInterval(fetchAllDatasets, 25000);
});

function initClock() {
    function updateTime() {
        const now = new Date();
        const hr = String(now.getHours()).padStart(2, '0');
        const min = String(now.getMinutes()).padStart(2, '0');
        
        const days = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'];
        const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
        
        const dayName = days[now.getDay()];
        const monthName = months[now.getMonth()];
        const dateNum = now.getDate();
        const year = now.getFullYear();

        const timeEl = document.getElementById("live-time");
        const dateEl = document.getElementById("live-date");
        if (timeEl) timeEl.innerText = `${hr}:${min}`;
        if (dateEl) dateEl.innerText = `${dayName}, ${monthName} ${dateNum}, ${year}`;
    }
    updateTime();
    setInterval(updateTime, 1000);
}

/* ==============================================================================
   WebSocket Real-Time Stream
   ============================================================================== */
function connectWebSocket() {
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const wsUrl = `${protocol}//${window.location.host}/ws/telemetry`;
    
    ws = new WebSocket(wsUrl);

    ws.onmessage = (event) => {
        try {
            const data = JSON.parse(event.data);
            updateHeaderMetrics(data);
        } catch (e) {
            console.error("Error parsing WebSocket payload:", e);
        }
    };

    ws.onclose = () => {
        setTimeout(connectWebSocket, 4000);
    };

    ws.onerror = () => {
        ws.close();
    };
}

/* ==============================================================================
   Live Header Updates
   ============================================================================== */
function updateHeaderMetrics(data) {
    if (!data) return;

    // 1. Net Grid Badge & House Load
    const grid = data.grid || {};
    const netBadgeEl = document.getElementById("live-net-badge");
    const houseLoadEl = document.getElementById("val-house-load");

    if (netBadgeEl && grid.net_kw !== undefined) {
        if (grid.net_kw < 0) {
            netBadgeEl.innerText = `${grid.net_kw.toFixed(3)} kW | Solar Export`;
            netBadgeEl.className = "net-status-line text-export";
        } else {
            netBadgeEl.innerText = `${grid.net_kw.toFixed(3)} kW | Grid Import`;
            netBadgeEl.className = "net-status-line text-import";
        }
    }

    if (houseLoadEl && grid.house_load_kw !== undefined) {
        houseLoadEl.innerText = grid.house_load_kw.toFixed(3);
    }

    // 2. SolarEdge & Chillicon PV
    const solar = data.solar || {};
    const seEl = document.getElementById("val-se-pv");
    const chEl = document.getElementById("val-ch-pv");
    if (seEl && solar.solaredge_kw !== undefined) seEl.innerText = solar.solaredge_kw.toFixed(3);
    if (chEl && solar.chilicon_kw !== undefined) chEl.innerText = solar.chilicon_kw.toFixed(3);

    // 3. Weather & AQI
    const wx = data.weather || {};
    const wxEl = document.getElementById("live-weather");
    if (wxEl) {
        const tempC = wx.temp_f !== undefined ? ((wx.temp_f - 32) * 5 / 9).toFixed(1) : "25.7";
        const clouds = wx.cloud_cover !== undefined ? wx.cloud_cover : 0;
        const desc = wx.description || "Clear";
        wxEl.innerText = `${tempC}°C | ${desc} (${clouds}%)`;
    }

    const pa = (data.air_quality && data.air_quality.purpleair) || {};
    const aqiEl = document.getElementById("live-aqi");
    if (aqiEl) {
        const aqiVal = pa.online ? pa.aqi : 76;
        const cat = pa.online ? pa.category : "Moderate";
        aqiEl.innerText = `AQI: ${aqiVal} (${cat})`;
        if (pa.color) aqiEl.style.color = pa.color;
    }
}

/* ==============================================================================
   Async REST Fetchers
   ============================================================================== */
async function fetchAllDatasets() {
    try {
        const [r1, r2, s1, s2] = await Promise.all([
            fetch("/api/telemetry/history?hours=24").then(r => r.json()),
            fetch("/api/telemetry/spectrum").then(r => r.json()),
            fetch("/api/summary?slide=1").then(r => r.json()),
            fetch("/api/summary?slide=3").then(r => r.json())
        ]);

        updateSlide1(r1);
        updateSlide3(r2);

        const ai1 = document.getElementById("ai-text-1");
        const ai2 = document.getElementById("ai-text-2");
        if (ai1 && s1.summary) ai1.innerText = s1.summary;
        if (ai2 && s2.summary) ai2.innerText = s2.summary;

    } catch (e) {
        console.error("Error loading datasets:", e);
    }
}

/* ==============================================================================
   Slide Switcher & Auto-Cycle Management
   ============================================================================== */
function switchSlide(slideNum) {
    currentSlide = slideNum;
    slideTimerSecs = SLIDE_DURATIONS[currentSlide] || 30;

    for (let i = 1; i <= 2; i++) {
        const slideEl = document.getElementById(`slide-${i}`);
        if (slideEl) {
            slideEl.classList.toggle("active", i === currentSlide);
        }
    }

    // Update Dots
    const dots = document.querySelectorAll(".slide-dots .dot");
    dots.forEach((d, idx) => {
        d.classList.toggle("active", idx + 1 === currentSlide);
    });

    // Update Heading
    const headingEl = document.getElementById("slide-heading");
    if (headingEl) {
        if (currentSlide === 1) {
            headingEl.innerText = "24-Hour Period";
            headingEl.className = "slide-heading slide-theme-cyan";
        } else {
            headingEl.innerText = "DFT Frequency Spectrum";
            headingEl.className = "slide-heading slide-theme-pink";
        }
    }
}

function startSlideCycle() {
    slideTimerSecs = SLIDE_DURATIONS[1];
    if (slideIntervalHandle) clearInterval(slideIntervalHandle);

    slideIntervalHandle = setInterval(() => {
        if (!autoCycleEnabled) return;

        slideTimerSecs--;
        const timerTag = document.getElementById("timer-tag");
        if (timerTag) timerTag.innerText = `${slideTimerSecs}s`;

        if (slideTimerSecs <= 0) {
            let next = currentSlide === 1 ? 2 : 1;
            switchSlide(next);
        }
    }, 1000);
}
