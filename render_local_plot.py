"""Offline Matplotlib local plot renderer for local verification.

Loads historical telemetry data, computes DFT spectra, and generates screen exports.
Uses the shared dashboard_modules configuration and computations.
"""

import datetime
import os
import sys
import threading
import time
import tkinter as tk
from typing import Any, Dict, List, Optional, Tuple

# Third-party libraries
from PIL import Image, ImageTk
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.collections import LineCollection
import matplotlib.dates as mdates
from matplotlib.figure import Figure

# Modular imports
from dashboard_modules import config, io, telemetry, solar, weather, spectral, ai

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


class OfflineViewer(tk.Tk):
    """Offline GUI window that emulates physical kiosk rendering using historical CSV files."""

    def __init__(self) -> None:
        super().__init__()
        self.title("Grid Monitor Preview")
        self.configure(bg='black')
        self.geometry("1024x768")
        
        self.live_mode: bool = "--live" in sys.argv
        self.chilicon_off: bool = "--chiliconoff" in sys.argv

        self.bind("<Escape>", lambda e: self.destroy())
        if not self.live_mode:
            self.bind("<Button-1>", lambda e: self.destroy())

        self._data_lock = threading.Lock()
        self.usage: List[float] = []
        self.timestamps: List[datetime.datetime] = []
        self.se_power: List[float] = []
        self.se_timestamps: List[datetime.datetime] = []
        self.se_battery_timestamps: List[datetime.datetime] = []
        self.se_battery_power: List[float] = []
        self.se_battery_soc: List[float] = []
        self.se_load_power_timestamps: List[datetime.datetime] = []
        self.se_load_power: List[float] = []
        self.chilicon_power: List[float] = []
        self.chilicon_timestamps: List[datetime.datetime] = []
        self.chilicon_energy: List[float] = []

        # File paths
        self.history_file = os.path.join(SCRIPT_DIR, 'grid_history.csv')
        self.se_history_file = os.path.join(SCRIPT_DIR, 'solaredge_history.csv')
        self.se_battery_history_file = os.path.join(SCRIPT_DIR, 'solaredge_battery_history.csv')
        self.se_flow_history_file = os.path.join(SCRIPT_DIR, 'solaredge_flow_history.csv')
        self.chilicon_history_file = os.path.join(SCRIPT_DIR, 'chilicon_history.csv')
        self.summary_cache_file = os.path.join(SCRIPT_DIR, 'gemini_summary.json')

        # Check command line for full history
        self.cutoff_hours = 24
        for arg in sys.argv:
            if arg.startswith("--history-hours="):
                try:
                    self.cutoff_hours = int(arg.split("=")[1])
                except ValueError:
                    pass
            elif arg == "--full-history":
                self.cutoff_hours = 999999

        # Load historical data
        self.load_history_files(self.cutoff_hours)

        # Small banner hardware logos banner
        self.logo_image_tk: Optional[ImageTk.PhotoImage] = None
        try:
            logo_path = os.path.join(SCRIPT_DIR, "scratch", "combined_logos_small.png")
            if os.path.exists(logo_path):
                img = Image.open(logo_path)
                self.logo_image_tk = ImageTk.PhotoImage(img)
        except Exception as e:
            print(f"Failed to load logo banner image: {e}")

        # Setup GUI Widgets
        self.setup_widgets()

        # Setup overlapping Matplotlib plots
        self.setup_canvas()

        # Initial state variables
        self.current_slide: int = 1
        self.local_time_text: str = "Awaiting AI Analysis..."
        self.local_dft_text: str = "Awaiting Frequency Domain Analysis..."
        self.baseline_text: str = ""
        self.local_delta_text: str = ""
        self.cached_full_history_spectrum: Dict[str, Any] = {}

        # Load cached summaries
        self.load_cached_summary()

        # Schedule Slide transitions
        if self.live_mode:
            self.after(config.SLIDE_1_DURATION_MS, self.rotate_slides)
            self.start_live_sync_daemon()
            self.start_gui_repaint_loop()
        else:
            # Render and take screenshot immediately in batch headless mode
            self.update_slide_visibility()

    @property
    def data_lock(self) -> threading.Lock:
        """Lock for safe data synchronization."""
        return self._data_lock

    def load_history_files(self, cutoff_hours: int = 24) -> None:
        """Loads historical data arrays from CSV files."""
        self.timestamps, self.usage = telemetry.load_grid_history(self.history_file, cutoff_hours=cutoff_hours)
        
        # SolarEdge PV, battery, and flow history
        se_client = solar.SolarEdgeClient("", "", self.se_history_file, self.se_battery_history_file, self.se_flow_history_file)
        self.se_timestamps, self.se_power, self.se_battery_timestamps, self.se_battery_power, self.se_battery_soc = se_client.load_history(cutoff_hours=cutoff_hours)
        self.se_load_power_timestamps, self.se_load_power = se_client.load_flow_history(cutoff_hours=cutoff_hours)

        # Chillicon PV history
        ch_client = solar.ChilliconClient("", "", "", self.chilicon_history_file)
        self.chilicon_timestamps, self.chilicon_power, self.chilicon_energy = ch_client.load_history(cutoff_hours=cutoff_hours)

        # Weather defaults
        self.weather_map = weather.fetch_historical_weather()

    def setup_widgets(self) -> None:
        """Draws Tkinter headers and labels."""
        self.header_frame = tk.Frame(self, bg='black')
        self.header_frame.pack(fill=tk.X, padx=20, pady=10)

        # Left Column
        self.left_header = tk.Frame(self.header_frame, bg='black')
        self.left_header.pack(side=tk.LEFT, anchor='nw')

        self.time_label = tk.Label(
            self.left_header, text="00:00", font=('Helvetica', 32, 'bold'), bg='black', fg='deepskyblue', anchor='w'
        )
        self.time_label.pack(anchor='w', pady=(0, 2))

        self.date_label = tk.Label(
            self.left_header, text="", font=('Helvetica', 12, 'bold'), bg='black', fg='#a0aec0', anchor='w'
        )
        self.date_label.pack(anchor='w', pady=(0, 2))

        self.weather_label = tk.Label(
            self.left_header, text="Weather: N/A", font=('Helvetica', 14, 'bold'), bg='black', fg='#fbbf24', anchor='w'
        )
        self.weather_label.pack(anchor='w', pady=(0, 2))

        # Right Column
        self.right_header = tk.Frame(self.header_frame, bg='black')
        self.right_header.pack(side=tk.RIGHT, anchor='ne')

        latest_val = self.usage[-1] if self.usage else 0.0
        status = "Solar Export" if latest_val < 0 else "Grid Import"
        color = config.EXPORT_COLOR if latest_val < 0 else config.IMPORT_COLOR
        text = f"{latest_val:.3f} kW | {status}"

        self.status_label = tk.Label(
            self.right_header, text=text, font=('Helvetica', config.STATUS_FONT_SIZE, 'bold'), bg='black', fg=color, anchor='e'
        )
        self.status_label.pack(anchor='e', pady=(0, 2))

        latest_pv = self.se_power[-1] if self.se_power else 0.0
        self.sub_status_label = tk.Label(
            self.right_header, text=f"SolarEdge PV: {latest_pv:.3f} kW", font=('Helvetica', 16, 'bold'), bg='black', fg='#fbbf24', anchor='e'
        )
        self.sub_status_label.pack(anchor='e', pady=(0, 2))

        self.chilicon_status_label = tk.Label(
            self.right_header, text="", font=('Helvetica', 16, 'bold'), bg='black', fg='#ffff00', anchor='e'
        )
        if not self.chilicon_off:
            self.chilicon_status_label.pack(anchor='e', pady=(0, 2))
            latest_ch = self.chilicon_power[-1] if self.chilicon_power else 0.0
            self.chilicon_status_label.config(text=f"Chillicon PV: {latest_ch:.3f} kW")

        # House Load measurement widget
        if self.se_load_power:
            latest_load = self.se_load_power[-1]
        else:
            latest_rf = self.usage[-1] if self.usage else 0.0
            latest_se_pv = self.se_power[-1] if self.se_power else 0.0
            latest_ch_pv = self.chilicon_power[-1] if self.chilicon_power else 0.0
            latest_bat = self.se_battery_power[-1] if self.se_battery_power else 0.0
            latest_load = max(0.0, latest_rf + latest_se_pv + latest_ch_pv + latest_bat)

        self.load_status_label = tk.Label(
            self.right_header, text=f"House Load: {latest_load:.3f} kW", font=('Helvetica', 16, 'bold'), bg='black', fg=config.CONSUMPTION_COLOR, anchor='e'
        )
        self.load_status_label.pack(anchor='e', pady=(0, 2))

        if self.logo_image_tk:
            self.logo_label = tk.Label(self, image=self.logo_image_tk, bg='black')
            self.logo_label.pack(side=tk.TOP, anchor='center', pady=(5, 5))

        self.summary_label = tk.Label(
            self, text="Awaiting AI Analysis...", font=('Courier', 11, 'bold'),
            bg='black', fg=config.SUMMARY_COLOR, justify='left', anchor='nw', wraplength=980
        )

    def setup_canvas(self) -> None:
        """Configures Matplotlib figure overlays."""
        self.fig = Figure(figsize=(8, 6), dpi=100, facecolor='black')
        rect = [0.08, 0.12, 0.88, 0.82]

        self.ax = self.fig.add_axes(rect)
        self.ax.set_facecolor('black')
        self.ax.tick_params(colors='white')
        self.ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
        self.fig.autofmt_xdate()
        self.ax.spines['bottom'].set_color('white')
        self.ax.spines['left'].set_color('white')
        self.ax.spines['top'].set_color('black')
        self.ax.spines['right'].set_color('black')

        self.ax_bar = self.ax.twinx()
        self.ax_bar.set_ylim(0, 10)
        self.ax_bar.tick_params(colors='#fbbf24')
        self.ax_bar.yaxis.set_label_position('right')
        self.ax_bar.spines['right'].set_color('#fbbf24')
        self.ax_bar.spines['left'].set_color('none')
        self.ax_bar.spines['top'].set_color('none')
        self.ax_bar.spines['bottom'].set_color('none')
        self.ax_bar.set_ylabel('Total Solar PV (kW)', color='#fbbf24', rotation=270, labelpad=15)

        self.ax.set_zorder(self.ax_bar.get_zorder() + 1)
        self.ax.patch.set_visible(False)
        self.ax.axhline(0, color='gray', linestyle='--')

        self.lc = LineCollection([], linewidths=1.8, zorder=2)
        self.ax.add_collection(self.lc)
        self.load_line, = self.ax.plot([], [], color=config.CONSUMPTION_COLOR, label='Appliance Load (SE Approx)', linewidth=1.8, alpha=0.85, zorder=1.8)

        # Slide 2 Axis
        self.ax_freq = self.fig.add_axes(rect, facecolor='black')
        self.ax_freq.tick_params(colors='white')
        self.ax_freq.spines['bottom'].set_color('white')
        self.ax_freq.spines['left'].set_color('white')
        self.ax_freq.spines['right'].set_color('none')
        self.ax_freq.spines['top'].set_color('none')
        self.ax_freq.set_xlabel('Frequency (Cycles per Day)', color='white', fontsize=9)
        self.ax_freq.set_ylabel('Spectral Amplitude (kW)', color='white', fontsize=9)
        self.ax_freq.set_visible(False)

        # Text Objects
        self.summary_text_obj = self.ax.text(
            0.02, 0.95, "Awaiting AI Analysis...", transform=self.ax.transAxes, ha='left', va='top',
            fontsize=config.SUMMARY_FONT_SIZE, color=config.SUMMARY_COLOR, alpha=config.SUMMARY_ALPHA,
            fontfamily='monospace', weight='bold', zorder=10
        )
        self.summary_text_obj_freq = self.ax_freq.text(
            0.02, 0.95, "Awaiting Frequency Domain Analysis...", transform=self.ax_freq.transAxes, ha='left', va='top',
            fontsize=config.SUMMARY_FONT_SIZE, color=config.SUMMARY_COLOR, alpha=config.SUMMARY_ALPHA,
            fontfamily='monospace', weight='bold', zorder=10
        )

        self.canvas = FigureCanvasTkAgg(self.fig, master=self)
        self.canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)

    def load_cached_summary(self) -> None:
        """Loads AI summary records from cache json."""
        data = io.read_safe_json(self.summary_cache_file)
        if not data:
            data = {}
                
        summary = data.get("summary", "")
        dft_explanation = data.get("dft_explanation", "")
        self.cached_full_history_spectrum = data.get("full_history_spectrum", {})
        
        if summary:
            marker = "[Live Local Delta (Jetson)"
            if marker in summary:
                self.baseline_text = summary.split(marker)[0].strip()
                self.local_delta_text = marker + summary.split(marker)[1]
            else:
                self.baseline_text = summary.strip()
                self.local_delta_text = ""
            
            if dft_explanation:
                self.local_dft_text = dft_explanation.strip()
            else:
                self.local_dft_text = "Awaiting Frequency Domain Analysis..."
                
            self.update_summary_display()

    def update_summary_display(self) -> None:
        """Refreshes subplot text watermarks."""
        if self.current_slide == 1:
            text = self.baseline_text
            if self.local_delta_text:
                text += "\n" + self.local_delta_text
            self.summary_text_obj.set_text(self.wrap_text(text).replace('$', '\\$'))
        else:
            self.summary_text_obj_freq.set_text(self.wrap_text(self.local_dft_text).replace('$', '\\$'))
            
        # Redraw canvas if initialized
        if hasattr(self, 'canvas') and self.canvas is not None:
            self.canvas.draw_idle()

    def rotate_slides(self) -> None:
        """Slide transition scheduler loop."""
        self.current_slide = 2 if self.current_slide == 1 else 1
        self.update_slide_visibility()
        delay = config.SLIDE_2_DURATION_MS if self.current_slide == 2 else config.SLIDE_1_DURATION_MS
        self.after(delay, self.rotate_slides)

    def update_slide_visibility(self) -> None:
        """Swaps visibility of axes elements."""
        if self.current_slide == 1:
            self.ax.set_visible(True)
            self.ax_bar.set_visible(True)
            self.ax_freq.set_visible(False)
        else:
            self.ax.set_visible(False)
            self.ax_bar.set_visible(False)
            self.ax_freq.set_visible(True)
            
        self.update_summary_display()
        self.update_chart()

    def update_weather_display(self) -> None:
        """Refreshes the weather header label using Open-Meteo fallbacks with caching to prevent rate limiting."""
        if not hasattr(self, 'last_weather_fetch'):
            self.last_weather_fetch = 0.0
            self.cached_weather = {}
            self.weather_backoff_delay = 10.0
            self.last_weather_attempt = 0.0

        now_time = time.time()
        time_since_last_fetch = now_time - self.last_weather_fetch
        time_since_last_attempt = now_time - self.last_weather_attempt
        
        should_fetch = False
        if self.cached_weather:
            # Weather fetch interval matches Jetson stager local render cadence (15 minutes)
            if time_since_last_fetch > 900.0:
                should_fetch = True
        else:
            if time_since_last_attempt > self.weather_backoff_delay:
                should_fetch = True

        if should_fetch:
            self.last_weather_attempt = now_time
            try:
                live_weather = weather.fetch_live_weather()
                if live_weather:  # Only update cache if we got a valid response
                    self.cached_weather = live_weather
                    self.last_weather_fetch = now_time
                    self.weather_backoff_delay = 10.0  # Reset backoff on success
                else:
                    self.weather_backoff_delay = min(self.weather_backoff_delay * 2, 900.0)
                    print(f"Weather API returned empty. Backing off for {self.weather_backoff_delay:.1f}s.")
            except Exception as e:
                self.weather_backoff_delay = min(self.weather_backoff_delay * 2, 900.0)
                print(f"Error fetching live weather in update_weather_display: {e}. Backing off for {self.weather_backoff_delay:.1f}s.")

        live_weather = self.cached_weather
        temp = live_weather.get("temp")
        wcode = live_weather.get("weather_code")
        cloud_cover = live_weather.get("cloud_cover")
        
        if temp is None or wcode is None:
            cache = io.read_safe_json(self.summary_cache_file)
            metrics = cache.get("metrics", {})
            temp = metrics.get("temp_max")
            cloud_cover = metrics.get("cloud_cover")
            if cloud_cover is not None:
                cc = float(cloud_cover)
                wcode = 0 if cc < 10 else (1 if cc < 30 else (2 if cc < 60 else 3))

        # In-memory backup of the last valid weather values to prevent N/A regressions
        if not hasattr(self, 'last_valid_temp'):
            self.last_valid_temp = None
        if not hasattr(self, 'last_valid_sky_str'):
            self.last_valid_sky_str = None

        if temp is not None:
            temp_str = f"{temp:.1f}°C"
            self.last_valid_temp = temp_str
        else:
            temp_str = self.last_valid_temp if self.last_valid_temp is not None else "N/A"
            
        if wcode is not None:
            sky_map = {
                0: "Clear", 1: "Mainly Clear", 2: "Partly Cloudy", 3: "Overcast",
                45: "Foggy", 48: "Foggy", 51: "Drizzle", 53: "Drizzle", 55: "Drizzle",
                61: "Rainy", 63: "Rainy", 65: "Rainy", 80: "Chance of Rain", 81: "Chance of Rain",
                82: "Chance of Rain", 71: "Snowy", 73: "Snowy", 75: "Snowy", 77: "Snowy",
                85: "Snowy", 86: "Snowy", 95: "Thunderstorm", 96: "Thunderstorm", 99: "Thunderstorm"
            }
            sky_desc = sky_map.get(wcode, "Cloudy")
            sky_str = f"{sky_desc} ({int(cloud_cover)}%)" if cloud_cover is not None else sky_desc
            self.last_valid_sky_str = sky_str
        else:
            sky_str = self.last_valid_sky_str if self.last_valid_sky_str is not None else "N/A"

        self.weather_label.config(text=f"{temp_str} | {sky_str}")

    def update_chart(self) -> None:
        """Refreshes Matplotlib canvas plots."""
        if self.current_slide == 1:
            with self.data_lock:
                usage_copy = list(self.usage)
                timestamps_copy = list(self.timestamps)
                se_timestamps_copy = list(self.se_timestamps)
                se_power_copy = list(self.se_power)
                chilicon_timestamps_copy = list(self.chilicon_timestamps)
                chilicon_power_copy = list(self.chilicon_power)
                se_load_power_timestamps_copy = list(self.se_load_power_timestamps)
                se_load_power_copy = list(self.se_load_power)

            if len(usage_copy) > 1:
                x_nums = mdates.date2num(timestamps_copy)
                segments = []
                colors = []
                widths = []
                for i in range(len(usage_copy) - 1):
                    t1, t2 = timestamps_copy[i], timestamps_copy[i+1]
                    if (t2 - t1).total_seconds() > 600:
                        continue
                    y1, y2 = usage_copy[i], usage_copy[i+1]
                    segments.append(((x_nums[i], y1), (x_nums[i+1], y2)))
                    avg_y = (y1 + y2) / 2.0
                    colors.append(config.IMPORT_COLOR if avg_y > 0 else config.EXPORT_COLOR)
                    widths.append(1.8 if avg_y > 0 else 1.3)
                self.lc.set_segments(segments)
                self.lc.set_colors(colors)
                self.lc.set_linewidths(widths)
            else:
                self.lc.set_segments([])

            if len(se_load_power_copy) > 1:
                self.load_line.set_data(se_load_power_timestamps_copy, se_load_power_copy)
            else:
                self.load_line.set_data([], [])

            # Range limit ending at most recent reading
            end_time = timestamps_copy[-1] if timestamps_copy else datetime.datetime.now()
            start_time = end_time - datetime.timedelta(hours=24)
            self.ax.set_xlim(start_time, end_time)

            if usage_copy:
                y_min, y_max = min(usage_copy), max(usage_copy)
                y_range = max(y_max - y_min, 1.0)
                self.ax.set_ylim(min(0.0, y_min - 0.15 * y_range), max(0.0, y_max + 0.85 * y_range))

            # Stacked bars
            self.ax_bar.clear()
            self.ax_bar.tick_params(colors='#fbbf24')
            self.ax_bar.yaxis.set_label_position('right')
            self.ax_bar.spines['right'].set_color('#fbbf24')
            self.ax_bar.spines['left'].set_color('none')
            self.ax_bar.spines['top'].set_color('none')
            self.ax_bar.spines['bottom'].set_color('none')
            self.ax_bar.set_ylabel('Total Solar PV (kW)', color='#fbbf24', rotation=270, labelpad=15)
            
            bar_times = []
            se_heights = []
            ch_heights = []
            grid_start = start_time.replace(minute=(start_time.minute // 10) * 10, second=0, microsecond=0)
            current_slot = grid_start

            while current_slot <= end_time:
                bar_times.append(current_slot)
                
                # Find closest SolarEdge reading within ±15 minutes
                se_val = 0.0
                min_diff_se = datetime.timedelta(minutes=15)
                for ts, p in zip(se_timestamps_copy, se_power_copy):
                    diff = abs(ts - current_slot)
                    if diff < min_diff_se:
                        min_diff_se = diff
                        se_val = p
                se_heights.append(se_val)
                
                # Find closest Chillicon reading within ±15 minutes
                ch_val = 0.0
                if not self.chilicon_off:
                    min_diff_ch = datetime.timedelta(minutes=15)
                    for ts, p in zip(chilicon_timestamps_copy, chilicon_power_copy):
                        diff = abs(ts - current_slot)
                        if diff < min_diff_ch:
                            min_diff_ch = diff
                            ch_val = p
                ch_heights.append(ch_val)
                current_slot += datetime.timedelta(minutes=10)

            if bar_times:
                width_in_days = 10.0 / (24.0 * 60.0)
                self.ax_bar.bar(bar_times, se_heights, width=width_in_days, color='#fbbf24', alpha=0.1, zorder=1, edgecolor='none')
                self.ax_bar.bar(bar_times, ch_heights, bottom=se_heights, width=width_in_days, color='#ffff00', alpha=0.15, zorder=1.5, edgecolor='none')
                max_power = max([s + c for s, c in zip(se_heights, ch_heights)]) if bar_times else 1.0
                self.ax_bar.set_ylim(0, max_power * 1.1)
            else:
                self.ax_bar.set_ylim(0, 10)

            self.canvas.draw()

        elif self.current_slide == 2:
            self.ax_freq.clear()
            self.ax_freq.set_facecolor('black')
            self.ax_freq.tick_params(colors='white')
            self.ax_freq.spines['bottom'].set_color('white')
            self.ax_freq.spines['left'].set_color('white')
            self.ax_freq.spines['right'].set_color('none')
            self.ax_freq.spines['top'].set_color('none')
            self.ax_freq.set_xlabel('Frequency (Cycles per Day)', color='white', fontsize=9)
            self.ax_freq.set_ylabel('Spectral Amplitude (kW)', color='white', fontsize=9)

            # If we have precomputed full-history spectrum from Jetson, use it!
            if self.cached_full_history_spectrum and "freqs" in self.cached_full_history_spectrum:
                spec = self.cached_full_history_spectrum
                freqs = spec["freqs"]
                grid_amp = spec["grid_amp"]
                solar_amp = spec["solar_amp"]
                expected_solar_amp = spec["expected_solar_amp"]
                consumption_amp = spec["consumption_amp"]
            else:
                with self.data_lock:
                    grid_u = list(self.usage)
                    grid_ts = list(self.timestamps)
                    se_ts = list(self.se_timestamps)
                    se_p = list(self.se_power)
                    ch_ts = list(self.chilicon_timestamps)
                    ch_p = list(self.chilicon_power)

                freqs, grid_amp, solar_amp, expected_solar_amp, consumption_amp = spectral.align_and_compute_spectra(
                    grid_ts, grid_u, se_ts, se_p, ch_ts, ch_p, self.weather_map, self.chilicon_off
                )

            if freqs:
                self.ax_freq.plot(freqs, grid_amp, color=config.IMPORT_COLOR, label='Grid Spectrum', linewidth=1.5)
                self.ax_freq.plot(freqs, solar_amp, color='#fbbf24', label='Solar Spectrum (Actual)', linewidth=1.5)
                self.ax_freq.plot(freqs, expected_solar_amp, color=config.EXPECTED_SOLAR_COLOR, linestyle='--', label='Expected Solar (Weather Modulated)', linewidth=1.3)
                self.ax_freq.plot(freqs, consumption_amp, color=config.CONSUMPTION_COLOR, label='Household Consumption (Load)', linewidth=1.5)
                self.ax_freq.axvline(1.0, color='deepskyblue', linestyle='--', alpha=0.5, label='24h Diurnal')
                self.ax_freq.axvline(2.0, color='violet', linestyle='--', alpha=0.5, label='12h Semi-Diurnal')
                self.ax_freq.set_xlim(0.1, 4.0)
                self.ax_freq.grid(color='gray', linestyle=':', alpha=0.3)

                snr_metrics = spectral.calculate_snr_metrics(freqs, grid_amp, solar_amp, consumption_amp)
                grid_diurnal_snr = snr_metrics.get("grid_24h_snr_db", 0.0)
                solar_diurnal_snr = snr_metrics.get("solar_24h_snr_db", 0.0)
                consumption_diurnal_snr = snr_metrics.get("consumption_24h_snr_db", 0.0)

                self.ax_freq.legend(
                    [
                        f'Grid Spectrum (Diurnal SNR: {grid_diurnal_snr:.1f} dB)',
                        f'Solar Spectrum (Diurnal SNR: {solar_diurnal_snr:.1f} dB)',
                        'Expected Solar (Weather Modulated)',
                        f'Household Consumption (Diurnal SNR: {consumption_diurnal_snr:.1f} dB)',
                        '24h Diurnal',
                        '12h Semi-Diurnal'
                    ],
                    facecolor='black', edgecolor='white', labelcolor='white', fontsize=8,
                    loc='lower right'
                )
                max_amp = max(max(grid_amp), max(solar_amp), max(expected_solar_amp), max(consumption_amp)) if grid_amp else 1.0
                self.ax_freq.set_ylim(0, max_amp * 1.85)

            self.summary_text_obj_freq = self.ax_freq.text(
                0.02, 0.95, self.wrap_text(self.local_dft_text),
                transform=self.ax_freq.transAxes, ha='left', va='top',
                fontsize=config.SUMMARY_FONT_SIZE, color=config.SUMMARY_COLOR, alpha=config.SUMMARY_ALPHA,
                fontfamily='monospace', weight='bold', zorder=10
            )
            self.canvas.draw()

    def start_gui_repaint_loop(self) -> None:
        """Starts dynamic live clock updates."""
        def update_loop():
            if not hasattr(self, 'running') or self.running:
                now_dt = datetime.datetime.now()
                self.time_label.config(text=now_dt.strftime("%H:%M"))
                self.date_label.config(text=now_dt.strftime("%A, %b %d, %Y"))
                self.update_weather_display()
                if self.current_slide == 1:
                    self.update_chart()
                self.after(2000, update_loop)
        self.after(2000, update_loop)

    def start_live_sync_daemon(self) -> None:
        """Spawns an offline sync thread to pull active history files from the Pi."""
        self.running = True
        self.sync_thread = threading.Thread(target=self.sync_loop, daemon=True)
        self.sync_thread.start()

    def sync_loop(self) -> None:
        """Sync loop calling scp transfers."""
        while self.running:
            self.poll_remote_data()
            time.sleep(30)

    def poll_remote_data(self) -> None:
        """Sync files from remote kiosk."""
        logging.info("Checking remote updates from rainforestpi...")
        # Syncing code runs command line helper script
        import subprocess
        try:
            subprocess.run(["scp", "steven@rainforestpi:~/rainforest-emu2-grid-dashboard/*.csv", "steven@rainforestpi:~/rainforest-emu2-grid-dashboard/*.json", SCRIPT_DIR], timeout=15)
            self.load_history_files(self.cutoff_hours)
            self.load_cached_summary()
        except Exception as e:
            logging.error(f"Failed to sync remote telemetry: {e}")

    def wrap_text(self, text: str, width: int = 100) -> str:
        """Text line wrapper helper."""
        import textwrap
        lines = []
        for p in text.split('\n'):
            if p.startswith('-') or p.startswith('*') or p.startswith('['):
                lines.append(textwrap.fill(p, width=width, subsequent_indent='  '))
            else:
                lines.append(textwrap.fill(p, width=width))
        return '\n'.join(lines)

    def save_screenshot(self) -> None:
        """Saves full Tkinter window screenshots using PIL ImageGrab."""
        from PIL import ImageGrab
        import time
        import datetime
        os.makedirs(SCRIPT_DIR, exist_ok=True)
        
        # Populate time and weather manually (since live loop is disabled in headless)
        now_dt = self.timestamps[-1] if self.timestamps else datetime.datetime.now()
        self.time_label.config(text=now_dt.strftime("%H:%M"))
        self.date_label.config(text=now_dt.strftime("%A, %b %d, %Y"))
        self.update_weather_display()
        
        # Force window to front to ensure clean capture
        self.attributes("-topmost", True)
        self.update_idletasks()
        self.update()
        time.sleep(1.0)  # Wait for window manager to render
        
        x = self.winfo_rootx()
        y = self.winfo_rooty()
        w = self.winfo_width()
        h = self.winfo_height()
        bbox = (x, y, x + w, y + h)
        
        suffix = "_full" if self.cutoff_hours > 48 else ""
        
        # Save Slide 1
        self.current_slide = 1
        self.update_slide_visibility()
        self.update_idletasks()
        self.update()
        time.sleep(0.5)
        ImageGrab.grab(bbox).convert('RGB').save(os.path.join(SCRIPT_DIR, f"dashboard_preview{suffix}.jpeg"), quality=95)
        
        # Save Slide 2
        self.current_slide = 2
        self.update_slide_visibility()
        self.update_idletasks()
        self.update()
        time.sleep(0.5)
        ImageGrab.grab(bbox).convert('RGB').save(os.path.join(SCRIPT_DIR, f"dashboard_preview_slide2{suffix}.jpeg"), quality=95)


if __name__ == "__main__":
    viewer = OfflineViewer()
    if "--screenshot" in sys.argv:
        viewer.save_screenshot()
        viewer.destroy()
    else:
        viewer.mainloop()
