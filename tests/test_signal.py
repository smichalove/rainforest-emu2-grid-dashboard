"""Unit tests for the signal processing and Fourier Transform calculations.

This module verifies the Discrete Fourier Transform (DFT) amplitude and phase,
time-domain slope calculations, and daylight duration extraction.
"""

import pytest
import os
import sys
import datetime
import tempfile
import csv
import math

# Add the parent directory to the path so we can import stage_local_summary
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import stage_local_summary

def test_compute_dft_pure_sinusoid():
    """Verify that compute_dft correctly resolves the amplitude and peak hour of a pure 24h sine wave."""
    N = 48
    target_amplitude = 3.5
    target_peak_hour = 13.0  # Peak solar at 1:00 PM
    start_hour = 12.0  # Data starts at 12:00 PM (noon)
    
    # Generate a pure 24-hour cosine wave
    series = []
    for n in range(N):
        current_time_hour = start_hour + n
        val = target_amplitude * math.cos(2.0 * math.pi * (current_time_hour - target_peak_hour) / 24.0)
        # Rectify like solar (no negative values)
        series.append(max(0.0, val))
        
    # Run DFT analysis
    dft_results = stage_local_summary.compute_dft(series, start_hour)
    
    # Check that diurnal cycle (k=2 for N=48) has strong amplitude
    assert "solar_24h_amp" in dft_results
    assert dft_results["solar_24h_amp"] > 1.5  # Rectified wave amplitude is lower than the pure cosine, but should be substantial
    assert "solar_24h_peak_hour" in dft_results
    
    # Peak hour should be close to 13.0 (within 1 hour bin resolution)
    assert abs(dft_results["solar_24h_peak_hour"] - target_peak_hour) <= 1.0

def test_calculate_slope():
    """Test slope (derivative) calculation over the last 3 points."""
    # Test positive ramp
    pos_series = [10.0, 11.5, 13.0]  # +1.5 kW/hr
    pos_slope = stage_local_summary.calculate_slope(pos_series)
    assert abs(pos_slope - 1.5) < 1e-5

    # Test negative decay
    neg_series = [5.0, 4.0, 3.0]  # -1.0 kW/hr
    neg_slope = stage_local_summary.calculate_slope(neg_series)
    assert abs(neg_slope - (-1.0)) < 1e-5

    # Test zero slope
    flat_series = [2.0, 2.0, 2.0]
    flat_slope = stage_local_summary.calculate_slope(flat_series)
    assert abs(flat_slope) < 1e-5

def test_calculate_daylight_duration():
    """Verify that daylight duration is correctly parsed and calculated from sunrise/sunset ISO strings."""
    sunrise_str = "2026-05-30T05:15"
    sunset_str = "2026-05-30T21:30"  # 16 hours and 15 minutes of daylight
    
    duration = stage_local_summary.calculate_daylight_duration(sunrise_str, sunset_str)
    assert abs(duration - 16.25) < 1e-5

def test_extract_hourly_series():
    """Verify that extract_hourly_series properly aligns timestamps, fills gaps, and returns a 48-hour window."""
    with tempfile.NamedTemporaryFile(mode='w', delete=False) as f:
        # Write mock grid data with a gap
        # 2026-05-30 10:00 to 14:00 (with hour 12 missing)
        base_dt = datetime.datetime(2026, 5, 30, 10, 0)
        f.write(f"{(base_dt).isoformat()},1.0\n")
        f.write(f"{(base_dt + datetime.timedelta(hours=1)).isoformat()},1.2\n")
        # Hour 2 (12:00) is skipped to simulate a data gap
        f.write(f"{(base_dt + datetime.timedelta(hours=3)).isoformat()},1.4\n")
        f.write(f"{(base_dt + datetime.timedelta(hours=4)).isoformat()},1.5\n")
        temp_path = f.name
        
    try:
        # Extract series over 6 hours (to test aggregation and interpolation)
        end_time = base_dt + datetime.timedelta(hours=4)
        series, start_hour = stage_local_summary.extract_hourly_series(temp_path, end_time, window_hours=6)
        
        # Array length should be exactly window_hours
        assert len(series) == 6
        
        # Verify interpolation filled the missing hour 12:00 (index 3) with a value between 1.2 and 1.4
        assert 1.2 < series[3] < 1.4
        assert abs(series[3] - 1.3) < 1e-5
    finally:
        os.remove(temp_path)


def test_power_outage_gap_detection() -> None:
    """Verify that detect_telemetry_gaps identifies gaps longer than 30 minutes in CSV history."""
    with tempfile.NamedTemporaryFile(mode='w', delete=False) as f:
        base_dt = datetime.datetime(2026, 5, 30, 10, 0)
        # Write regular entries (every minute)
        f.write(f"{(base_dt).isoformat()},1.0\n")
        f.write(f"{(base_dt + datetime.timedelta(minutes=1)).isoformat()},1.1\n")
        # 1-hour gap (outage) starting at 10:01 until 11:01
        f.write(f"{(base_dt + datetime.timedelta(hours=1, minutes=1)).isoformat()},1.2\n")
        f.write(f"{(base_dt + datetime.timedelta(hours=1, minutes=2)).isoformat()},1.3\n")
        temp_path = f.name

    try:
        baseline_dt = base_dt
        end_time = base_dt + datetime.timedelta(hours=1, minutes=10)
        warnings = stage_local_summary.detect_telemetry_gaps(temp_path, baseline_dt, end_time)
        
        # Verify that we detected exactly 1 gap in the consecutive recordings
        assert len(warnings) == 1
        assert "Power outage or data gap of 60 minutes detected" in warnings[0]
    finally:
        os.remove(temp_path)


def test_prompt_formatting_success() -> None:
    """Verify that formatting gemma_hybrid_prompt.txt is successful without KeyError."""
    prompt_path = os.path.join(os.path.dirname(__file__), "..", "gemma_hybrid_prompt.txt")
    if not os.path.exists(prompt_path):
        pytest.skip("gemma_hybrid_prompt.txt not found")
        
    with open(prompt_path, 'r', encoding='utf-8') as f:
        prompt_template = f.read()
        
    # Attempt to format using typical values, including the newly added sunrise_time and sunset_time
    try:
        formatted = prompt_template.format(
            baseline_time="2026-05-30 10:00:00",
            baseline_text="Baseline Summary Text",
            current_time="2026-05-30 22:00:00",
            delta_import=1.5,
            delta_export=0.0,
            delta_peak=2.5,
            delta_solar=3.0,
            delta_bat_charge=0.5,
            delta_bat_discharge=0.4,
            expected_temp_max=16.0,
            expected_cloud_cover=50.0,
            solar_weather_modulation=0.5,
            month_name="May",
            day_type="Weekend",
            sunrise_time="05:15",
            sunset_time="21:30",
            daylight_duration=16.25,
            solar_24h_amp=2.0,
            solar_24h_peak_hour=stage_local_summary.format_decimal_hour(13.0),
            se_24h_peak_hour=stage_local_summary.format_decimal_hour(11.5),
            ch_24h_peak_hour=stage_local_summary.format_decimal_hour(16.0),
            grid_24h_amp=1.5,
            grid_12h_amp=0.8,
            grid_12h_peak_hour=stage_local_summary.format_decimal_hour(8.0),
            grid_bimodal_ratio=0.53,
            solar_slope=-0.5,
            grid_slope=0.2,
            grid_24h_snr_db=15.6,
            grid_12h_snr_db=12.1,
            solar_24h_snr_db=22.4,
            consumption_24h_snr_db=18.2,
            consumption_12h_snr_db=14.5
        )
        assert "- Daylight Window: 05:15 to 21:30 (16.2 hours duration)" in formatted
        assert "run exactly from sunrise (05:15) to sunset (21:30)" in formatted
        assert "- Solar Weather Modulation Factor: 0.50" in formatted
        assert "- SolarEdge Diurnal Peak Hour (East Array): 11:30" in formatted
        assert "- Chillicon Diurnal Peak Hour (West Array): 16:00" in formatted
    except KeyError as e:
        pytest.fail(f"KeyError was raised during formatting for key: {e}")


def test_calculate_snr_db_pure_signal() -> None:
    """Verify calculate_snr_db correctly identifies high SNR for a pure sinusoidal signal with no noise."""
    import snr_analysis
    
    # 0.1 to 4.0 cycles/day in steps of 0.1
    freqs = [0.1 * i for i in range(1, 41)]
    amplitudes = [0.0] * len(freqs)
    
    # Set peak at 1.0 cycles/day
    idx_10 = freqs.index(1.0)
    amplitudes[idx_10] = 5.0  # 5 kW amplitude
    
    # SNR should be maximum bounded limit because noise power is zero
    snr = snr_analysis.calculate_snr_db(freqs, amplitudes, target_freq=1.0)
    assert snr == snr_analysis.SNR_MAX_LIMIT_DB


def test_calculate_snr_db_noisy_signal() -> None:
    """Verify calculate_snr_db correctly computes decibel ratio for a signal with fixed noise floor."""
    import snr_analysis
    
    freqs = [0.05 * i for i in range(1, 81)]  # 0.05 to 4.0
    amplitudes = [0.0] * len(freqs)
    
    # Set signal peak of 2.0 kW at target frequency of 1.0 cycles/day
    idx_target = freqs.index(1.0)
    amplitudes[idx_target] = 2.0
    
    # Fill noise ranges (0.4 to 0.7 and 1.3 to 1.7) with 0.5 kW amplitude
    noise_ranges = [(0.4, 0.7), (1.3, 1.7)]
    noise_indices = []
    for i, f in enumerate(freqs):
        for r_low, r_high in noise_ranges:
            if r_low <= f <= r_high:
                noise_indices.append(i)
                amplitudes[i] = 0.5
                break
                
    # Signal power: 2.0^2 = 4.0
    # Noise power: 0.5^2 = 0.25
    # Expected Ratio: 4.0 / 0.25 = 16.0
    # Expected SNR: 10 * log10(16) = 12.0411998... dB
    snr = snr_analysis.calculate_snr_db(freqs, amplitudes, target_freq=1.0, noise_ranges=noise_ranges)
    expected_snr = 10.0 * math.log10(16.0)
    assert abs(snr - expected_snr) < 1e-5

