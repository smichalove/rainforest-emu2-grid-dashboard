/**
 * Chart.js configurations replicating the exact physical Matplotlib Kiosk slides.
 */

let chartSlide1 = null;
let chartSlide2 = null;
let chartSlide3 = null;

function initSlide1Chart() {
    const canvas = document.getElementById("timeDomainChart");
    if (!canvas) return;
    const ctx = canvas.getContext("2d");

    chartSlide1 = new Chart(ctx, {
        type: "line",
        data: {
            labels: [],
            datasets: [
                {
                    type: "bar",
                    label: "Solar Generation",
                    data: [],
                    backgroundColor: "rgba(161, 138, 20, 0.42)",
                    borderColor: "rgba(161, 138, 20, 0.65)",
                    borderWidth: 1,
                    barPercentage: 1.0,
                    categoryPercentage: 1.0,
                    yAxisID: "ySolar"
                },
                {
                    type: "line",
                    label: "House Load",
                    data: [],
                    borderColor: "#ffffff",
                    borderWidth: 2,
                    pointRadius: 0,
                    tension: 0.2,
                    yAxisID: "yGrid"
                },
                {
                    type: "line",
                    label: "Net Grid Demand",
                    data: [],
                    borderColor: "#22c55e",
                    segment: {
                        borderColor: ctx => (ctx.p0.parsed.y >= 0 ? "#ef4444" : "#22c55e")
                    },
                    borderWidth: 2.2,
                    pointRadius: 0,
                    tension: 0.2,
                    yAxisID: "yGrid"
                },
                {
                    type: "line",
                    label: "Battery Storage",
                    data: [],
                    borderColor: "#3b82f6",
                    backgroundColor: "rgba(30, 64, 175, 0.4)",
                    fill: true,
                    borderWidth: 1.5,
                    pointRadius: 0,
                    tension: 0.1,
                    yAxisID: "yGrid"
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            animation: false,
            plugins: {
                legend: { display: false },
                tooltip: { enabled: true }
            },
            scales: {
                x: {
                    grid: { color: "rgba(255, 255, 255, 0.08)", drawTicks: true },
                    ticks: {
                        color: "#ffffff",
                        font: { size: 12, weight: "bold" },
                        maxRotation: 30,
                        minRotation: 30,
                        maxTicksLimit: 9
                    }
                },
                yGrid: {
                    type: "linear",
                    position: "left",
                    min: -10.0,
                    max: 10.0,
                    grid: {
                        color: ctx => (ctx.tick.value === 0 ? "#666666" : "rgba(255, 255, 255, 0.05)"),
                        lineWidth: ctx => (ctx.tick.value === 0 ? 1.5 : 1)
                    },
                    ticks: {
                        color: "#ffffff",
                        font: { size: 12, weight: "bold" },
                        stepSize: 2.5
                    }
                },
                ySolar: {
                    type: "linear",
                    position: "right",
                    min: 0.0,
                    max: 4.5,
                    grid: { drawOnChartArea: false },
                    ticks: {
                        color: "#eab308",
                        font: { size: 12, weight: "bold" },
                        stepSize: 0.5
                    }
                }
            }
        }
    });
}

function initSlide2Chart() {
    const canvas = document.getElementById("history14dChart");
    if (!canvas) return;
    const ctx = canvas.getContext("2d");

    chartSlide2 = new Chart(ctx, {
        type: "line",
        data: {
            labels: [],
            datasets: [
                {
                    type: "bar",
                    label: "Solar Generation",
                    data: [],
                    backgroundColor: "rgba(161, 138, 20, 0.38)",
                    borderWidth: 0,
                    barPercentage: 1.0,
                    categoryPercentage: 1.0,
                    yAxisID: "ySolar"
                },
                {
                    type: "line",
                    label: "House Load",
                    data: [],
                    borderColor: "#ffffff",
                    borderWidth: 1.8,
                    pointRadius: 0,
                    tension: 0.2,
                    yAxisID: "yGrid"
                },
                {
                    type: "line",
                    label: "Net Grid",
                    data: [],
                    borderColor: "#22c55e",
                    segment: {
                        borderColor: ctx => (ctx.p0.parsed.y >= 0 ? "#ef4444" : "#22c55e")
                    },
                    borderWidth: 1.8,
                    pointRadius: 0,
                    tension: 0.2,
                    yAxisID: "yGrid"
                },
                {
                    type: "line",
                    label: "Battery Dispatch",
                    data: [],
                    borderColor: "#3b82f6",
                    backgroundColor: "rgba(30, 64, 175, 0.4)",
                    fill: true,
                    borderWidth: 1.5,
                    pointRadius: 0,
                    yAxisID: "yGrid"
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            animation: false,
            plugins: { legend: { display: false } },
            scales: {
                x: {
                    grid: { color: "rgba(255, 255, 255, 0.08)" },
                    ticks: { color: "#ffffff", font: { size: 11, weight: "bold" }, maxRotation: 30, minRotation: 30, maxTicksLimit: 14 }
                },
                yGrid: {
                    type: "linear",
                    position: "left",
                    min: -10.0,
                    max: 10.0,
                    grid: { color: ctx => (ctx.tick.value === 0 ? "#666666" : "rgba(255, 255, 255, 0.05)") },
                    ticks: { color: "#ffffff", font: { size: 12, weight: "bold" }, stepSize: 2.5 }
                },
                ySolar: {
                    type: "linear",
                    position: "right",
                    min: 0.0,
                    max: 6.0,
                    grid: { drawOnChartArea: false },
                    ticks: { color: "#eab308", font: { size: 12, weight: "bold" } }
                }
            }
        }
    });
}

function initSlide3Chart() {
    const canvas = document.getElementById("freqDomainChart");
    if (!canvas) return;
    const ctx = canvas.getContext("2d");

    chartSlide3 = new Chart(ctx, {
        type: "line",
        data: {
            labels: [],
            datasets: [
                {
                    label: "Grid Spectrum (Diurnal SNR: 23.9 dB)",
                    data: [],
                    borderColor: "#f87171",
                    borderWidth: 1.8,
                    pointRadius: 0,
                    tension: 0.15
                },
                {
                    label: "Solar Spectrum (Diurnal SNR: 25.9 dB)",
                    data: [],
                    borderColor: "#fbbf24",
                    borderWidth: 1.8,
                    pointRadius: 0,
                    tension: 0.15
                },
                {
                    label: "Expected Solar (Weather Modulated)",
                    data: [],
                    borderColor: "#facc15",
                    borderDash: [5, 5],
                    borderWidth: 1.5,
                    pointRadius: 0,
                    tension: 0.15
                },
                {
                    label: "Household Consumption (Diurnal SNR: 15.1 dB)",
                    data: [],
                    borderColor: "#ffffff",
                    borderWidth: 1.5,
                    pointRadius: 0,
                    tension: 0.15
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            animation: false,
            plugins: {
                legend: {
                    position: "bottom",
                    align: "end",
                    labels: {
                        color: "#ffffff",
                        font: { size: 11, weight: "bold" },
                        boxWidth: 20
                    }
                }
            },
            scales: {
                x: {
                    title: { display: true, text: "Frequency (Cycles per Day)", color: "#ffffff", font: { size: 12, weight: "bold" } },
                    grid: { color: "rgba(255, 255, 255, 0.08)" },
                    ticks: { color: "#ffffff", font: { size: 12, weight: "bold" }, maxTicksLimit: 9 }
                },
                y: {
                    title: { display: true, text: "Spectral Amplitude (kW)", color: "#ffffff", font: { size: 12, weight: "bold" } },
                    min: 0.0,
                    max: 4.5,
                    grid: { color: "rgba(255, 255, 255, 0.08)" },
                    ticks: { color: "#ffffff", font: { size: 12, weight: "bold" }, stepSize: 0.5 }
                }
            }
        }
    });
}

function updateSlide1(historyData) {
    if (!chartSlide1) initSlide1Chart();
    if (!chartSlide1 || !historyData) return;

    const grid = historyData.grid || { timestamps: [], values: [] };
    const se = historyData.solaredge || { values: [] };
    const ch = historyData.chilicon || { values: [] };
    const house = historyData.house_load || { values: [] };
    const bat = historyData.battery || { power_kw: [] };

    // Format timestamps as "MM-DD HH" (e.g. "08-13 18")
    const labels = grid.timestamps.map(ts => {
        try {
            const d = new Date(ts);
            const m = String(d.getMonth() + 1).padStart(2, '0');
            const day = String(d.getDate()).padStart(2, '0');
            const hr = String(d.getHours()).padStart(2, '0');
            return `${m}-${day} ${hr}`;
        } catch {
            return "";
        }
    });

    // Total Solar = SE + Chillicon
    const totalSolar = (se.values || []).map((v, idx) => v + (ch.values[idx] || 0));

    chartSlide1.data.labels = labels;
    chartSlide1.data.datasets[0].data = totalSolar;
    chartSlide1.data.datasets[1].data = house.values || [];
    chartSlide1.data.datasets[2].data = grid.values || [];
    chartSlide1.data.datasets[3].data = bat.power_kw || [];
    chartSlide1.update();
}

function updateSlide2(history14d) {
    if (!chartSlide2) initSlide2Chart();
    if (!chartSlide2 || !history14d) return;

    const grid = history14d.grid || { timestamps: [], values: [] };
    const se = history14d.solaredge || { values: [] };
    const ch = history14d.chilicon || { values: [] };
    const house = history14d.house_load || { values: [] };
    const bat = history14d.battery || { power_kw: [] };

    const labels = grid.timestamps.map(ts => {
        try {
            const d = new Date(ts);
            const m = String(d.getMonth() + 1).padStart(2, '0');
            const day = String(d.getDate()).padStart(2, '0');
            return `${d.getFullYear()}-${m}-${day}`;
        } catch {
            return "";
        }
    });

    const totalSolar = (se.values || []).map((v, idx) => v + (ch.values[idx] || 0));

    chartSlide2.data.labels = labels;
    chartSlide2.data.datasets[0].data = totalSolar;
    chartSlide2.data.datasets[1].data = house.values || [];
    chartSlide2.data.datasets[2].data = grid.values || [];
    chartSlide2.data.datasets[3].data = bat.power_kw || [];
    chartSlide2.update();
}

function updateSlide3(spectrumData) {
    if (!chartSlide3) initSlide3Chart();
    if (!chartSlide3 || !spectrumData) return;

    const freqs = spectrumData.frequencies_cpd || [];
    chartSlide3.data.labels = freqs.map(f => f.toFixed(1));
    chartSlide3.data.datasets[0].data = spectrumData.grid_spectrum || [];
    chartSlide3.data.datasets[1].data = spectrumData.solar_spectrum || [];
    chartSlide3.data.datasets[2].data = spectrumData.expected_solar || [];
    chartSlide3.data.datasets[3].data = spectrumData.house_spectrum || [];
    chartSlide3.update();
}
