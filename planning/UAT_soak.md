# Fallback Calculation & UAT Soak Plan

This document details the fallback calculation for the home consumption (**Appliance Load**) and outlines the User Acceptance Testing (UAT) soak criteria to verify its stability and accuracy under continuous operation.

---

## Active UAT Status
* **Soak Start Time:** June 5, 2026 @ 11:08 AM (Local Time)
* **Expected Completion Time:** June 12, 2026 @ 11:08 AM (Local Time)
* **Status:** In Progress (Active soaking)

---

## 1. Fallback Appliance Load Calculation
When the SolarEdge API is offline, throttled (e.g., due to the strict 300 requests/daySite API limit), or sleeping overnight, the dashboard cannot fetch direct `LOAD` telemetry. In these events, the dashboard dynamically calculates the **Appliance Load** using our validated physical formula:

$$\text{Appliance Load (Fallback)} = \text{Rainforest Grid} + \text{SolarEdge PV} + \text{Chillicon PV} + \text{Battery Power}$$

Where:
1. **Rainforest Grid:** Instantaneous grid import/export in kW (polled via USB serial every 15 seconds).
2. **SolarEdge PV:** SolarEdge solar generation in kW (cached from the last 6-minute API poll).
3. **Chillicon PV:** Chillicon microinverter solar generation in kW (cached from the last 15-minute API poll).
4. **Battery Power:** Signed battery power in kW (cached from the last 6-minute API poll, where charging is negative and discharging is positive).

### Edge-Case Handling & Clipping
* **Mismatched Timestamps:** Because the solar/battery API metrics have slower update intervals than the 15-second utility meter, rapid load changes can temporarily result in a negative computed load. 
  * *Handling:* The computed load is clipped at a minimum of `0.0 kW`:
    $$\text{Appliance Load} = \max(0.0, \, \text{Calculated Load})$$
* **Offline Solar Gateways:** If either SolarEdge or Chillicon APIs fail completely, the calculation falls back to using the last known cached values.

---

## 2. UAT Soak Testing Specifications
To ensure the integrity of the real-time calculation, the system will undergo a **7-day UAT soak period**. The following parameters will be monitored for success:

### A. Core UAT Success Criteria
* **Discrepancy Tolerance:** The daily integrated total consumption (kWh) computed via the fallback formula must remain within **5.0%** of the direct SolarEdge load logs (when both are available).
* **Negative Load Rate:** Periods where the calculated load goes negative (before clipping) due to polling lag must represent less than **2.0%** of the daily active solar generation timeframe.
* **UI Responsiveness:** The live `House Load` label on the dashboard header must update within 1.0 second of receiving any new Rainforest grid packet (every 15 seconds).

### B. Validation & Anomaly Checks
During the soak period, the stager scripts will actively flag the following anomalies:
* **Impossible Export ratio:** Grid export exceeds total solar generation plus battery discharge (indicates utility meter or sensor drift).
* **Sensor Disconnect:** Active solar generation drops to exactly `0.0 kW` during peak daylight, indicating the gateway has gone offline.

---

## 3. How to Run Soak Analysis
To review the integrity of the fallback calculation during the UAT soak period, execute the energy integration script:
```bash
python3 scratch/validate_consumption_totals.py
```
This will integrate the area under both the SolarEdge native load curve and the fallback curve, reporting the daily cumulative kWh variance.
