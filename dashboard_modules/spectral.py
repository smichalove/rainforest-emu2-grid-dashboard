"""Gap interpolation, Discrete Fourier Transforms, and aligned spectrum math.

Handles calculations for the Frequency Domain Slide 2 of the dashboard.
"""

import datetime
import math
from typing import Any, Dict, List, Optional, Tuple

# Local import
from .config import DEFAULT_WEATHER_FALLBACK
import snr_analysis


def interpolate_gaps(series: List[Optional[float]]) -> List[float]:
    """Fills missing elements (None) in a list using linear interpolation.

    Args:
        series: A list of floats that may contain None elements.

    Returns:
        A list of floats with all None elements replaced by interpolated values.
    """
    n: int = len(series)
    result: List[Optional[float]] = list(series)
    non_none_indices: List[int] = [i for i, x in enumerate(series) if x is not None]
    if not non_none_indices:
        return [0.0] * n
        
    first_valid_idx: int = non_none_indices[0]
    last_valid_idx: int = non_none_indices[-1]
    
    # Forward and backward fill edges
    for i in range(first_valid_idx):
        result[i] = series[first_valid_idx]
    for i in range(last_valid_idx + 1, n):
        result[i] = series[last_valid_idx]
        
    # Linear interpolation for middle gaps
    for i in range(first_valid_idx + 1, last_valid_idx):
        if result[i] is None:
            prev_idx: int = i - 1
            while prev_idx >= first_valid_idx and result[prev_idx] is None:
                prev_idx -= 1
            next_idx: int = i + 1
            while next_idx <= last_valid_idx and result[next_idx] is None:
                next_idx += 1
                
            val_prev: float = result[prev_idx]  # type: ignore
            val_next: float = result[next_idx]  # type: ignore
            ratio: float = (i - prev_idx) / (next_idx - prev_idx)
            result[i] = val_prev + ratio * (val_next - val_prev)
            
    return [float(x) for x in result]  # type: ignore


def compute_dft(amplitudes: List[float], freq_cycles_per_day: float) -> Tuple[float, float, float]:
    """Computes a single DFT frequency bin.

    Args:
        amplitudes: The time-series values.
        freq_cycles_per_day: Frequency cycle rate.

    Returns:
        A tuple of (real_part, imaginary_part, magnitude).
    """
    n_samples = len(amplitudes)
    if n_samples == 0:
        return 0.0, 0.0, 0.0

    omega = (2.0 * math.pi * freq_cycles_per_day) / 24.0
    re = 0.0
    im = 0.0
    for n in range(n_samples):
        re += amplitudes[n] * math.cos(omega * n)
        im += -amplitudes[n] * math.sin(omega * n)
        
    mag = 2.0 * math.sqrt(re**2 + im**2) / n_samples
    return re, im, mag


def align_and_compute_spectra(
    timestamps: List[datetime.datetime],
    usage: List[float],
    se_timestamps: List[datetime.datetime],
    se_power: List[float],
    chilicon_timestamps: List[datetime.datetime],
    chilicon_power: List[float],
    weather_map: Dict[str, Dict[str, Any]],
    chilicon_off: bool = False
) -> Tuple[List[float], List[float], List[float], List[float], List[float]]:
    """Aligns historical telemetry on a uniform hourly grid and computes the DTFT spectrum.

    Args:
        timestamps: Grid timestamps.
        usage: Grid usage demand (kW).
        se_timestamps: SolarEdge timestamps.
        se_power: SolarEdge generation (kW).
        chilicon_timestamps: Chillicon timestamps.
        chilicon_power: Chillicon generation (kW).
        weather_map: Daily weather coordinates map.
        chilicon_off: If Chillicon polling is disabled.

    Returns:
        A tuple of five lists:
        - freqs: frequencies in cycles per day
        - grid_amp: spectral amplitude of grid usage (kW)
        - solar_amp: spectral amplitude of total solar generation (kW)
        - expected_solar_amp: spectral amplitude of expected solar generation (kW)
        - consumption_amp: spectral amplitude of household consumption (kW)
    """
    if not timestamps:
        return [], [], [], [], []

    min_ts = min(timestamps).replace(minute=0, second=0, microsecond=0)
    max_ts = max(timestamps).replace(minute=0, second=0, microsecond=0)
    total_hours = int((max_ts - min_ts).total_seconds() / 3600.0) + 1
    
    target_dts = [min_ts + datetime.timedelta(hours=i) for i in range(total_hours)]
    
    # Align Grid values
    grid_map: Dict[str, List[float]] = {}
    for ts, val in zip(timestamps, usage):
        key = ts.strftime("%Y-%m-%d %H:00")
        if key not in grid_map:
            grid_map[key] = []
        grid_map[key].append(val)
        
    # Align SolarEdge values
    se_map: Dict[str, List[float]] = {}
    for ts, val in zip(se_timestamps, se_power):
        key = ts.strftime("%Y-%m-%d %H:00")
        if key not in se_map:
            se_map[key] = []
        se_map[key].append(val)
        
    # Align Chillicon values
    ch_map: Dict[str, List[float]] = {}
    for ts, val in zip(chilicon_timestamps, chilicon_power):
        key = ts.strftime("%Y-%m-%d %H:00")
        if key not in ch_map:
            ch_map[key] = []
        ch_map[key].append(val)
        
    grid_raw: List[Optional[float]] = []
    solar_raw: List[Optional[float]] = []
    expected_solar_series: List[float] = []
    
    PEAK_SOLAR_CAPACITY: float = 5.0
    
    for dt in target_dts:
        key = dt.strftime("%Y-%m-%d %H:00")
        
        # Grid Avg
        g_vals = grid_map.get(key, [])
        grid_raw.append(sum(g_vals) / len(g_vals) if g_vals else None)
        
        # Solar Avg
        s_val = 0.0
        se_vals = se_map.get(key, [])
        if se_vals:
            s_val += sum(se_vals) / len(se_vals)
        if not chilicon_off:
            ch_vals = ch_map.get(key, [])
            if ch_vals:
                s_val += sum(ch_vals) / len(ch_vals)
        
        if not se_vals and (chilicon_off or key not in ch_map):
            solar_raw.append(None)
        else:
            solar_raw.append(s_val)
            
        # Expected Solar model
        date_key = dt.strftime("%Y-%m-%d")
        day_weather = weather_map.get(date_key, DEFAULT_WEATHER_FALLBACK)
        cloud_cover = day_weather["cloud_cover"]
        sr_hour = day_weather["sunrise_hour"]
        ss_hour = day_weather["sunset_hour"]
        
        h = dt.hour + dt.minute / 60.0
        if sr_hour < h < ss_hour:
            clear_sky = PEAK_SOLAR_CAPACITY * math.sin(math.pi * (h - sr_hour) / (ss_hour - sr_hour))
        else:
            clear_sky = 0.0
            
        modulation = (100.0 - cloud_cover) / 100.0
        expected_solar_series.append(clear_sky * modulation)
            
    grid_series = interpolate_gaps(grid_raw)
    solar_series = interpolate_gaps(solar_raw)
    
    # Load = Grid + Solar
    consumption_series = [g + s for g, s in zip(grid_series, solar_series)]
    
    # Run DTFT spectrum analysis for frequencies 0.1 to 4.0 cycles per day
    freqs = [0.05 + 0.01 * i for i in range(400)]
    
    grid_amp: List[float] = []
    solar_amp: List[float] = []
    expected_solar_amp: List[float] = []
    consumption_amp: List[float] = []
    
    n_samples = len(grid_series)
    if n_samples > 0:
        for f in freqs:
            grid_amp.append(compute_dft(grid_series, f)[2])
            solar_amp.append(compute_dft(solar_series, f)[2])
            expected_solar_amp.append(compute_dft(expected_solar_series, f)[2])
            consumption_amp.append(compute_dft(consumption_series, f)[2])
    else:
        grid_amp = [0.0] * len(freqs)
        solar_amp = [0.0] * len(freqs)
        expected_solar_amp = [0.0] * len(freqs)
        consumption_amp = [0.0] * len(freqs)
        
    return freqs, grid_amp, solar_amp, expected_solar_amp, consumption_amp


def calculate_snr_metrics(
    freqs: List[float],
    grid_amp: List[float],
    solar_amp: List[float],
    consumption_amp: List[float]
) -> Dict[str, float]:
    """Invokes snr_analysis algorithms to compute diurnal/semi-diurnal dB metrics."""
    return snr_analysis.analyze_spectra_snr(freqs, grid_amp, solar_amp, consumption_amp)
