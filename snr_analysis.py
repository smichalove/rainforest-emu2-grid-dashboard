"""Discrete Fourier Transform Signal-to-Noise Ratio (SNR) Analysis Module.

This module provides utility functions to compute the Signal-to-Noise Ratio (SNR)
of diurnal (24-hour) and semi-diurnal (12-hour) periodic rhythms extracted from
microgrid energy telemetry. It evaluates spectral stability, offering quantitative
metrics of daily schedule predictability.
"""

import math
from typing import Dict, List, Optional, Tuple

# -------------------------------------------------------------
# Configuration Constants & Default Frequency Bands
# -------------------------------------------------------------
# Default noise bands for diurnal rhythm (avoiding 0.0-0.3 DC/weather and 0.8-1.2 diurnal peaks)
DEFAULT_DIURNAL_NOISE_RANGES: List[Tuple[float, float]] = [(0.4, 0.7), (1.3, 1.7)]

# Default noise bands for semi-diurnal rhythm (avoiding 1.8-2.2 semi-diurnal peaks)
DEFAULT_SEMIDIURNAL_NOISE_RANGES: List[Tuple[float, float]] = [(1.3, 1.7), (2.3, 2.7)]

# Default half-width defining the signal band centered at the target frequency
DEFAULT_SIGNAL_BAND_HALF_WIDTH: float = 0.05

# Upper and lower bounds for SNR values in dB to prevent math singularities (e.g. infinity)
SNR_MIN_LIMIT_DB: float = -50.0
SNR_MAX_LIMIT_DB: float = 50.0


def calculate_snr_db(
    freqs: List[float],
    amplitudes: List[float],
    target_freq: float,
    signal_band_half_width: float = DEFAULT_SIGNAL_BAND_HALF_WIDTH,
    noise_ranges: Optional[List[Tuple[float, float]]] = None
) -> float:
    """Calculates the Signal-to-Noise Ratio (SNR) of a periodic frequency component in decibels (dB).

    The signal power is computed as the square of the maximum amplitude resolved within
    the target signal band: [target_freq - signal_band_half_width, target_freq + signal_band_half_width].
    The noise floor power is calculated as the average of the squared amplitudes (power) 
    within non-periodic noise frequency bands.

    Args:
        freqs: List of frequencies analyzed in cycles/day.
        amplitudes: Corresponding resolved spectral amplitudes in kW.
        target_freq: The target periodic frequency of interest (e.g., 1.0 for diurnal, 2.0 for semi-diurnal).
        signal_band_half_width: The half-width defining the signal band around target_freq.
        noise_ranges: A list of (low, high) frequency ranges to use for noise floor evaluation.
            If None, default non-periodic bands are selected based on target_freq.

    Returns:
        The computed Signal-to-Noise Ratio in decibels (dB).

    Raises:
        ValueError: If the input lists have mismatched lengths or are empty.
    """
    if len(freqs) != len(amplitudes):
        raise ValueError("Frequencies and amplitudes lists must be of the same length.")
    if not freqs:
        raise ValueError("Input lists cannot be empty.")

    # 1. Define the signal band limits
    low_sig = target_freq - signal_band_half_width
    high_sig = target_freq + signal_band_half_width

    # Extract all amplitudes within the signal band
    signal_amps: List[float] = [
        amplitudes[i] for i, f in enumerate(freqs)
        if low_sig <= f <= high_sig
    ]

    # If no exact bins hit the signal band range, find the single closest bin
    if not signal_amps:
        closest_idx: int = min(range(len(freqs)), key=lambda idx: abs(freqs[idx] - target_freq))
        signal_amps = [amplitudes[closest_idx]]

    # Signal power is proportional to the square of the peak amplitude
    signal_power: float = max(signal_amps) ** 2

    # 2. Define the noise bands limits
    if noise_ranges is None:
        # Assign defaults based on target frequency
        if abs(target_freq - 1.0) < 0.1:
            noise_ranges = DEFAULT_DIURNAL_NOISE_RANGES
        elif abs(target_freq - 2.0) < 0.1:
            noise_ranges = DEFAULT_SEMIDIURNAL_NOISE_RANGES
        else:
            # Fallback dynamic ranges: exclude signal band and DC/infra-low components
            noise_ranges = [
                (0.2, target_freq - 2.0 * signal_band_half_width),
                (target_freq + 2.0 * signal_band_half_width, target_freq + 1.0)
            ]

    # Extract all amplitudes falling within the noise ranges
    noise_amps: List[float] = []
    for r_low, r_high in noise_ranges:
        noise_amps.extend([
            amplitudes[i] for i, f in enumerate(freqs)
            if r_low <= f <= r_high
        ])

    # Fallback if selected noise bands contain no frequency bins
    if not noise_amps:
        # Use all bins above DC (0.2 cycles/day) excluding the signal band
        noise_amps = [
            amplitudes[i] for i, f in enumerate(freqs)
            if f >= 0.2 and not (low_sig <= f <= high_sig)
        ]

    # If still empty, use all bins to avoid division by zero
    if not noise_amps:
        noise_amps = list(amplitudes)

    # Noise power is the mean of the squared noise amplitudes
    noise_power: float = sum(val ** 2 for val in noise_amps) / len(noise_amps)

    # 3. Calculate SNR in dB with safety checks for log singularities
    if noise_power <= 0.0:
        return SNR_MAX_LIMIT_DB if signal_power > 0.0 else 0.0

    if signal_power <= 0.0:
        return SNR_MIN_LIMIT_DB

    ratio: float = signal_power / noise_power
    snr_db: float = 10.0 * math.log10(ratio)

    # Bound the result to keep formatting clean and avoid mathematical overflows
    return max(SNR_MIN_LIMIT_DB, min(SNR_MAX_LIMIT_DB, snr_db))


def analyze_spectra_snr(
    freqs: List[float],
    grid_amp: List[float],
    solar_amp: List[float],
    consumption_amp: List[float]
) -> Dict[str, float]:
    """Computes diurnal (24h) and semi-diurnal (12h) SNR values for microgrid spectra.

    This function extracts the relative strength of the periodic daily rhythms
    (diurnal generation/consumption and bimodal demand peaks) against their
    corresponding non-periodic noise floors.

    Args:
        freqs: List of frequencies analyzed in cycles/day.
        grid_amp: Spectrum amplitudes for Net Grid demand in kW.
        solar_amp: Spectrum amplitudes for Solar PV generation in kW.
        consumption_amp: Spectrum amplitudes for Household Consumption load in kW.

    Returns:
        A dictionary containing the calculated SNR metrics in decibels (dB):
        - "grid_24h_snr_db": Net Grid 24h Diurnal SNR
        - "grid_12h_snr_db": Net Grid 12h Semi-Diurnal SNR
        - "solar_24h_snr_db": Solar PV 24h Diurnal SNR
        - "consumption_24h_snr_db": Household Consumption 24h Diurnal SNR
        - "consumption_12h_snr_db": Household Consumption 12h Semi-Diurnal SNR
    """
    grid_24h: float = calculate_snr_db(freqs, grid_amp, 1.0)
    grid_12h: float = calculate_snr_db(freqs, grid_amp, 2.0)
    
    solar_24h: float = calculate_snr_db(freqs, solar_amp, 1.0)
    
    consumption_24h: float = calculate_snr_db(freqs, consumption_amp, 1.0)
    consumption_12h: float = calculate_snr_db(freqs, consumption_amp, 2.0)

    return {
        "grid_24h_snr_db": grid_24h,
        "grid_12h_snr_db": grid_12h,
        "solar_24h_snr_db": solar_24h,
        "consumption_24h_snr_db": consumption_24h,
        "consumption_12h_snr_db": consumption_12h,
    }


def compute_dtft_spectrum(series: List[float], freqs: List[float]) -> List[float]:
    """Computes the DTFT amplitude spectrum of a series at specified frequencies.

    Args:
        series: List of floats representing hourly measurements.
        freqs: List of target frequencies to evaluate in cycles/day.

    Returns:
        A list of resolved spectral amplitudes in kW corresponding to each frequency.
    """
    n_samples = len(series)
    amplitudes: List[float] = []
    if n_samples == 0:
        return [0.0] * len(freqs)

    for f in freqs:
        omega = (2.0 * math.pi * f) / 24.0
        re = 0.0
        im = 0.0
        for n in range(n_samples):
            re += series[n] * math.cos(omega * n)
            im += -series[n] * math.sin(omega * n)
        # Normalized amplitude
        amp = 2.0 * math.sqrt(re**2 + im**2) / n_samples
        amplitudes.append(amp)
    return amplitudes
