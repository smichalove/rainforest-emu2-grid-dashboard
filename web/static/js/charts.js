/**
 * Chart.js configurations replicating the physical Matplotlib Kiosk slides
 * with stacked SolarEdge + Chillicon bars and dynamic Y-axis scaling.
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
                    label: "SolarEdge PV (kW)",
                    data: [],
                    backgroundColor: "rgba(245, 158, 11, 0.55)",
                    borderColor: "rgba(245, 158, 11, 0.8)",
                    borderWidth: 0,
                    barPercentage: 1.0,
                    categoryPercentage: 1.0,
                    stack: "solar",
                    yAxisID: "ySolar",
                    order: 3
                },
                {
                    type: "bar",
                    label: "Chillicon PV (kW)",
                    data: [],
                    backgroundColor: "rgba(250, 204, 21, 0.75)",
                    borderColor: "rgba(250, 204, 21, 0.95)",
                    borderWidth: 0,
                    barPercentage: 1.0,
                    categoryPercentage: 1.0,
                    stack: "solar",
                    yAxisID: "ySolar",
                    order: 3
                },
                {
                    type: "line",
                    label: "House Load (kW)",
                    data: [],
                    borderColor: "#ffffff",
                    borderWidth: 2,
                    pointRadius: 0,
                    tension: 0.2,
                    yAxisID: "yGrid",
                    order: 2
                },
                {
                    type: "line",
                    label: "Net Grid Demand (kW)",
                    data: [],
                    borderColor: "#22c55e",
                    segment: {
                        borderColor: ctx => (ctx.p0.parsed.y >= 0 ? "#ef4444" : "#22c55e")
                    },
                    borderWidth: 2.2,
                    pointRadius: 0,
                    tension: 0.2,
                    yAxisID: "yGrid",
                    order: 1
                },
                {
                    type: "line",
                    label: "Battery Storage (SoC)",
                    data: [],
                    borderColor: "#3b82f6",
                    backgroundColor: "rgba(59, 130, 246, 0.22)",
                    fill: { target: { value: -10.0 } },
                    borderWidth: 1.5,
                    pointRadius: 0,
                    spanGaps: false,
                    tension: 0.1,
                    yAxisID: "yGrid",
                    order: 5
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            animation: false,
            interaction: {
                mode: "index",
                intersect: false
            },
            plugins: {
                legend: {
                    display: true,
                    position: "top",
                    align: "end",
                    labels: {
                        color: "#cbd5e1",
                        font: { size: 11, weight: "bold" },
                        boxWidth: 14,
                        padding: 10
                    }
                },
                tooltip: { enabled: true }
            },
            scales: {
                x: {
                    stacked: true,
                    grid: { color: "rgba(255, 255, 255, 0.08)", drawTicks: true },
                    ticks: {
                        color: "#ffffff",
                        font: { size: 11, weight: "bold" },
                        maxRotation: 25,
                        minRotation: 0,
                        maxTicksLimit: 10
                    }
                },
                yGrid: {
                    type: "linear",
                    position: "left",
                    min: -1.0,
                    max: 4.0,
                    title: {
                        display: true,
                        text: "Grid / House Load (kW)",
                        color: "#ffffff",
                        font: { size: 11, weight: "bold" }
                    },
                    grid: {
                        color: ctx => (ctx.tick && ctx.tick.value === 0 ? "#666666" : "rgba(255, 255, 255, 0.05)"),
                        lineWidth: ctx => (ctx.tick && ctx.tick.value === 0 ? 1.5 : 1)
                    },
                    ticks: {
                        color: "#ffffff",
                        font: { size: 11, weight: "bold" }
                    }
                },
                ySolar: {
                    type: "linear",
                    position: "right",
                    stacked: true,
                    min: 0.0,
                    max: 2.0,
                    title: {
                        display: true,
                        text: "Total Solar PV (kW)",
                        color: "#eab308",
                        font: { size: 11, weight: "bold" }
                    },
                    grid: { drawOnChartArea: false },
                    ticks: {
                        color: "#eab308",
                        font: { size: 11, weight: "bold" }
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
                    label: "SolarEdge PV (kW)",
                    data: [],
                    backgroundColor: "rgba(245, 158, 11, 0.55)",
                    borderWidth: 0,
                    barPercentage: 1.0,
                    categoryPercentage: 1.0,
                    stack: "solar",
                    yAxisID: "ySolar",
                    order: 3
                },
                {
                    type: "bar",
                    label: "Chillicon PV (kW)",
                    data: [],
                    backgroundColor: "rgba(250, 204, 21, 0.75)",
                    borderWidth: 0,
                    barPercentage: 1.0,
                    categoryPercentage: 1.0,
                    stack: "solar",
                    yAxisID: "ySolar",
                    order: 3
                },
                {
                    type: "line",
                    label: "House Load (kW)",
                    data: [],
                    borderColor: "#ffffff",
                    borderWidth: 1.8,
                    pointRadius: 0,
                    tension: 0.2,
                    yAxisID: "yGrid",
                    order: 2
                },
                {
                    type: "line",
                    label: "Net Grid (kW)",
                    data: [],
                    borderColor: "#22c55e",
                    segment: {
                        borderColor: ctx => (ctx.p0.parsed.y >= 0 ? "#ef4444" : "#22c55e")
                    },
                    borderWidth: 1.8,
                    pointRadius: 0,
                    tension: 0.2,
                    yAxisID: "yGrid",
                    order: 1
                },
                {
                    type: "line",
                    label: "Battery Storage (SoC)",
                    data: [],
                    borderColor: "#3b82f6",
                    backgroundColor: "rgba(59, 130, 246, 0.22)",
                    fill: { target: { value: -10.0 } },
                    borderWidth: 1.5,
                    pointRadius: 0,
                    spanGaps: false,
                    tension: 0.1,
                    yAxisID: "yGrid",
                    order: 5
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            animation: false,
            interaction: {
                mode: "index",
                intersect: false
            },
            plugins: {
                legend: {
                    display: true,
                    position: "top",
                    align: "end",
                    labels: {
                        color: "#cbd5e1",
                        font: { size: 11, weight: "bold" },
                        boxWidth: 14,
                        padding: 10
                    }
                }
            },
            scales: {
                x: {
                    stacked: true,
                    grid: { color: "rgba(255, 255, 255, 0.08)" },
                    ticks: { color: "#ffffff", font: { size: 11, weight: "bold" }, maxRotation: 25, minRotation: 0, maxTicksLimit: 14 }
                },
                yGrid: {
                    type: "linear",
                    position: "left",
                    min: -2.0,
                    max: 6.0,
                    title: {
                        display: true,
                        text: "Grid / House Load (kW)",
                        color: "#ffffff",
                        font: { size: 11, weight: "bold" }
                    },
                    grid: { color: ctx => (ctx.tick && ctx.tick.value === 0 ? "#666666" : "rgba(255, 255, 255, 0.05)") },
                    ticks: { color: "#ffffff", font: { size: 11, weight: "bold" } }
                },
                ySolar: {
                    type: "linear",
                    position: "right",
                    stacked: true,
                    min: 0.0,
                    max: 6.0,
                    title: {
                        display: true,
                        text: "Total Solar PV (kW)",
                        color: "#eab308",
                        font: { size: 11, weight: "bold" }
                    },
                    grid: { drawOnChartArea: false },
                    ticks: { color: "#eab308", font: { size: 11, weight: "bold" } }
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

function _applyDynamicTimeDomainData(chart, historyData, is14d) {
    const grid = historyData.grid || { timestamps: [], values: [] };
    const se = historyData.solaredge || { values: [] };
    const ch = historyData.chilicon || { values: [] };
    const house = historyData.house_load || { values: [] };
    const bat = historyData.battery || { power_kw: [], soc_percent: [] };

    const labels = (grid.timestamps || []).map(ts => {
        try {
            const d = new Date(ts);
            const m = String(d.getMonth() + 1).padStart(2, "0");
            const day = String(d.getDate()).padStart(2, "0");
            const hr = String(d.getHours()).padStart(2, "0");
            const min = String(d.getMinutes()).padStart(2, "0");
            return is14d ? `${m}-${day} ${hr}:00` : `${m}-${day} ${hr}:${min}`;
        } catch {
            return "";
        }
    });

    const seVals = se.values || [];
    const chVals = ch.values || [];
    const houseVals = house.values || [];
    const gridVals = grid.values || [];
    const batPower = bat.power_kw || [];
    const batSoc = bat.soc_percent || [];

    // Only plot Battery SoC fill when battery is actively charging or discharging (|power| >= 0.05 kW),
    // matching dashboard.py line 1369
    let hasActiveBattery = false;
    const batteryFill = labels.map((_, idx) => {
        const pwr = parseFloat(batPower[idx] || 0);
        const soc = parseFloat(batSoc[idx] !== undefined ? batSoc[idx] : 50.0);
        if (Math.abs(pwr) >= 0.05) {
            hasActiveBattery = true;
            return (soc * 0.1) - 10.0;
        }
        return null;
    });

    // Dynamic Y-Axis scaling for Solar (ySolar) and Grid/Load (yGrid)
    let maxSolar = 0.5;
    for (let i = 0; i < labels.length; i++) {
        const tot = (seVals[i] || 0) + (chVals[i] || 0);
        if (tot > maxSolar) maxSolar = tot;
    }
    chart.options.scales.ySolar.max = Math.max(1.0, Math.ceil(maxSolar * 1.25 * 2) / 2);

    let minGrid = 0.0;
    let maxGrid = 2.0;
    for (let i = 0; i < labels.length; i++) {
        const g = gridVals[i] || 0;
        const h = houseVals[i] || 0;
        if (g < minGrid) minGrid = g;
        if (g > maxGrid) maxGrid = g;
        if (h > maxGrid) maxGrid = h;
    }
    chart.options.scales.yGrid.min = hasActiveBattery ? -10.0 : Math.min(-0.5, Math.floor((minGrid - 0.3) * 2) / 2);
    chart.options.scales.yGrid.max = Math.max(2.5, Math.ceil((maxGrid + 0.4) * 2) / 2);

    chart.data.labels = labels;
    chart.data.datasets[0].data = seVals;
    chart.data.datasets[1].data = chVals;
    chart.data.datasets[2].data = houseVals;
    chart.data.datasets[3].data = gridVals;
    chart.data.datasets[4].data = batteryFill;
    chart.update();
}

function updateSlide1(historyData) {
    if (!chartSlide1) initSlide1Chart();
    if (!chartSlide1 || !historyData) return;
    _applyDynamicTimeDomainData(chartSlide1, historyData, false);
}

function updateSlide2(history14d) {
    if (!chartSlide2) initSlide2Chart();
    if (!chartSlide2 || !history14d) return;
    _applyDynamicTimeDomainData(chartSlide2, history14d, true);
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

