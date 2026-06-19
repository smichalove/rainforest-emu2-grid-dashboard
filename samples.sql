-- Samples for the Rainforest EMU-2 Grid Dashboard SQLite database schema.
-- Includes queries for grid_history and analysis_history tables.

-- Query 1: Get the 10 most recent grid telemetry entries.
SELECT timestamp, kw
FROM grid_history
ORDER BY timestamp DESC
LIMIT 10;


-- Query 2: Find the maximum peak grid import (highest power demand from grid) in the database.
SELECT timestamp, kw
FROM grid_history
WHERE kw > 0
ORDER BY kw DESC
LIMIT 1;


-- Query 3: Find the maximum peak solar export (highest power exported back to the grid, represented as negative kw).
SELECT timestamp, kw
FROM grid_history
WHERE kw < 0
ORDER BY kw ASC
LIMIT 1;


-- Query 4: Retrieve all edge-to-cloud escalated analysis slices.
SELECT timestamp, escalation_timestamp, summary_text
FROM analysis_history
WHERE escalation_status = 1
ORDER BY timestamp DESC;


-- Query 5: Calculate the average battery round-trip efficiency (RTE) across all slices where charging occurred.
SELECT 
    timestamp,
    delta_bat_charge,
    delta_bat_discharge,
    (delta_bat_discharge / delta_bat_charge) * 100.0 AS battery_rte_pct
FROM analysis_history
WHERE delta_bat_charge > 0.1
ORDER BY timestamp DESC;


-- Query 6: Group grid usage data by hour of the day to analyze historical daily demand patterns.
SELECT 
    strftime('%H', timestamp) AS hour_of_day,
    ROUND(AVG(kw), 3) AS avg_kw,
    ROUND(MIN(kw), 3) AS min_kw,
    ROUND(MAX(kw), 3) AS max_kw,
    COUNT(*) AS sample_count
FROM grid_history
GROUP BY hour_of_day
ORDER BY hour_of_day;


-- Query 7: List all historical slices where the house load exceeded a peak threshold of 5.0 kW.
SELECT 
    timestamp, 
    se_load_min, 
    se_load_max, 
    se_load_avg, 
    summary_text
FROM analysis_history
WHERE se_load_max > 5.0
ORDER BY se_load_max DESC;


-- Query 8: Correlate expected weather patterns (temperature and cloud cover) with SolarEdge solar generation.
SELECT 
    timestamp, 
    expected_temp_max, 
    expected_cloud_cover, 
    delta_se_solar
FROM analysis_history
WHERE delta_se_solar > 0
ORDER BY expected_temp_max DESC, expected_cloud_cover ASC;


-- Query 9: Count the total number of premium PSE Flex Event discharge days (days with battery discharge > 0.1 kWh).
SELECT 
    COUNT(DISTINCT strftime('%Y-%m-%d', timestamp)) AS flex_event_days_count,
    ROUND(SUM(delta_bat_discharge), 3) AS total_flex_discharge_kwh,
    ROUND(SUM(delta_bat_discharge) * 0.50, 2) AS total_premium_credits_usd
FROM analysis_history
WHERE delta_bat_discharge > 0.1;


-- Query 10: Find slices with anomalous grid spectral diurnal behavior (high import delta but low diurnal phase alignment).
SELECT 
    timestamp, 
    delta_import, 
    delta_peak, 
    spectral_metrics_json
FROM analysis_history
WHERE delta_import > 15.0 AND escalation_status != 1
ORDER BY delta_import DESC;
