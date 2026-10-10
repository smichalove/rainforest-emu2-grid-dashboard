import sys
import time

print("[1/5] Initializing Python runtime...", flush=True)
_t0 = time.perf_counter()

import datetime
import bisect
import logging
import os
import threading
import tkinter as tk
from typing import Any, Dict, List, Optional, Tuple

print("[2/5] Loading Matplotlib and UI graphics engines...", flush=True)
# Third-party libraries
from PIL import Image, ImageTk
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.collections import LineCollection
import matplotlib.dates as mdates
from matplotlib.figure import Figure

print("[3/5] Loading telemetry and circuit data modules...", flush=True)
# Modular imports
from dashboard_modules import config, io, telemetry, solar, weather, spectral, ai, emporia_vue

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


class OfflineViewer(tk.Tk):
    """Offline GUI window that emulates physical kiosk rendering using historical CSV files."""

    def __init__(self) -> None:
        """Initializes the OfflineViewer window, loads telemetry databases, and prepares subplots.

        Prepares the window dimensions, parses CLI arguments for custom window limits,
        reads local SQLite telemetry databases for grid history and SolarEdge/Chillicon
        API logs, configures Matplotlib canvas layout, and generates widgets.

        Args:
            None.

        Returns:
            None.

        Raises:
            Exception: Logs fallback errors internally if history database or file
                parsing fails.
        """
        super().__init__()
        self.title("Grid Monitor Preview")
        self.configure(bg='black')
        self.geometry("1024x768")
        
        # Bring window to front on macOS desktop
        self.lift()
        self.attributes("-topmost", True)
        self.after(500, lambda: self.attributes("-topmost", False))
        self.focus_force()
        
        self.live_mode: bool = "--live" in sys.argv
        self.chilicon_off: bool = "--chiliconoff" in sys.argv
        self.running: bool = True

        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.bind("<Escape>", self.on_close)
        if not self.live_mode and "--close-on-click" in sys.argv:
            self.bind("<Button-1>", self.on_close)

        import signal
        signal.signal(signal.SIGINT, lambda s, f: self.on_close())
        signal.signal(signal.SIGTERM, lambda s, f: self.on_close())
        self.check_signals()

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

        # Circuit telemetry state
        self.circuit_telemetry = []
        self.last_circuit_fetch_time = 0.0
        self.use_simulated_circuits = "--live-emporia" not in sys.argv

        # Prioritize loading from Mac sync service directory if present
        sync_dir = "/Users/treven/rainforest_db"
        if os.path.exists(sync_dir):
            self.history_file = os.path.join(sync_dir, "grid_history.db")
            self.se_history_file = os.path.join(sync_dir, "solaredge_history.csv")
            self.se_battery_history_file = os.path.join(sync_dir, "solaredge_battery_history.csv")
            self.se_flow_history_file = os.path.join(sync_dir, "solaredge_flow_history.csv")
            self.chilicon_history_file = os.path.join(sync_dir, "chilicon_history.csv")
        else:
            backup_dir = os.path.join(SCRIPT_DIR, 'backups')
            db_path = os.path.join(backup_dir, 'grid_history.db')
            self.history_file = db_path if os.path.exists(db_path) else os.path.join(SCRIPT_DIR, 'grid_history.db')
            self.se_history_file = os.path.join(backup_dir, 'solaredge_history.csv') if os.path.exists(os.path.join(backup_dir, 'solaredge_history.csv')) else os.path.join(SCRIPT_DIR, 'solaredge_history.csv')
            self.se_battery_history_file = os.path.join(backup_dir, 'solaredge_battery_history.csv') if os.path.exists(os.path.join(backup_dir, 'solaredge_battery_history.csv')) else os.path.join(SCRIPT_DIR, 'solaredge_battery_history.csv')
            self.se_flow_history_file = os.path.join(backup_dir, 'solaredge_flow_history.csv') if os.path.exists(os.path.join(backup_dir, 'solaredge_flow_history.csv')) else os.path.join(SCRIPT_DIR, 'solaredge_flow_history.csv')
            self.chilicon_history_file = os.path.join(backup_dir, 'chilicon_history.csv') if os.path.exists(os.path.join(backup_dir, 'chilicon_history.csv')) else os.path.join(SCRIPT_DIR, 'chilicon_history.csv')

        self.summary_cache_file: str = os.path.join(SCRIPT_DIR, 'gemini_summary.json')

        # Check command line for full history, defaulting to standard 14 days of telemetry
        self.cutoff_hours: int = config.HISTORY_HOURS
        for arg in sys.argv:
            if arg.startswith("--history-hours="):
                try:
                    self.cutoff_hours = int(arg.split("=")[1])
                except ValueError:
                    pass
            elif arg == "--full-history":
                self.cutoff_hours = 999999

        # Load historical data
        print("[4/5] Reading telemetry databases and calculating circuits...", flush=True)
        self.load_history_files(self.cutoff_hours)

        # Small banner hardware logos banner
        self.logo_image_tk: Optional[ImageTk.PhotoImage] = None
        try:
            logo_path = os.path.join(SCRIPT_DIR, "scratch", "combined_logos_small.png")
            if os.path.exists(logo_path):
                img = Image.open(logo_path)
                self.logo_image_tk = ImageTk.PhotoImage(img)
        except Exception as e:
            pass

        # Setup GUI Widgets
        self.setup_widgets()

        # Setup overlapping Matplotlib plots
        self.setup_canvas()

        # Initial state variables
        self.current_slide: int = 1
        for i, arg in enumerate(sys.argv):
            if arg.startswith("--slide="):
                try:
                    self.current_slide = int(arg.split("=")[1])
                except ValueError:
                    pass
            elif arg == "--slide" and i + 1 < len(sys.argv):
                try:
                    self.current_slide = int(sys.argv[i + 1])
                except ValueError:
                    pass

        self.local_time_text: str = "Awaiting AI Analysis..."
        self.local_history_text: str = "Awaiting 14-day history summary..."
        self.local_dft_text: str = "Awaiting Frequency Domain Analysis..."
        self.baseline_text: str = ""
        self.local_delta_text: str = ""
        self.cached_full_history_spectrum: Dict[str, Any] = {}

        # Load cached summaries
        self.load_cached_summary()

        # Load Emporia Vue circuit telemetry
        if self.use_simulated_circuits:
            self.circuit_telemetry = emporia_vue.generate_simulated_telemetry()
            self.last_circuit_fetch_time = time.time()
        else:
            client = emporia_vue.EmporiaVueClient()
            self.circuit_telemetry = client.get_circuit_telemetry(use_simulator=False)
            self.last_circuit_fetch_time = time.time()

        print(f"      Calculated {len(self.circuit_telemetry)} circuits & plugs (Mains, Balance, Devices)", flush=True)
        print(f"[5/5] Building GUI layout and rendering Slide {self.current_slide}...", flush=True)

        if hasattr(self, 'peak_loads_label') and self.peak_loads_label is not None:
            top_pill, _ = emporia_vue.get_top_active_loads(self.circuit_telemetry, last_update_ts=self.last_circuit_fetch_time)
            self.peak_loads_label.config(text=top_pill)

        # Initialize time, date, and weather displays
        init_dt = self.timestamps[-1] if self.timestamps else datetime.datetime.now()
        self.time_label.config(text=init_dt.strftime("%H:%M"))
        self.date_label.config(text=init_dt.strftime("%A, %b %d, %Y"))
        self.update_weather_display()

        # Schedule Slide transitions
        if self.live_mode:
            self.after(config.SLIDE_1_DURATION_MS, self.rotate_slides)
            self.start_live_sync_daemon()
            self.start_gui_repaint_loop()
        else:
            # Render immediately in preview mode
            self.update_slide_visibility()

        print(f"✔ Ready! Displaying Slide {self.current_slide} window (1024x768).", flush=True)
        print("  Controls: Press <Escape> or close window to exit.", flush=True)
        print("=" * 60, flush=True)

    def check_signals(self) -> None:
        """Returns control briefly to Python to allow POSIX signals in Tk event loop."""
        if getattr(self, 'running', True):
            self.after(200, self.check_signals)

    def on_close(self, *args: Any) -> None:
        """Immediately and cleanly terminates the process."""
        self.running = False
        try:
            self.destroy()
        except Exception:
            pass
        os._exit(0)

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

        # Weather defaults (skip external API in preview mode for instantaneous startup)
        if self.live_mode:
            try:
                self.weather_map = weather.fetch_historical_weather()
            except Exception:
                self.weather_map = {}
        else:
            self.weather_map = {}

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

        # Peak loads measurement widget
        self.peak_loads_label = tk.Label(
            self.right_header, text="⚡ Top: Awaiting Telemetry...", font=('Helvetica', 10, 'bold'), bg='black', fg='#38bdf8', anchor='e'
        )
        self.peak_loads_label.pack(anchor='e', pady=(0, 2))

        if self.logo_image_tk:
            self.logo_label = tk.Label(self, image=self.logo_image_tk, bg='black')
            self.logo_label.pack(side=tk.TOP, anchor='center', pady=(5, 5))

        # Dynamic header subtitle indicating current slide time window
        self.slide_title_label = tk.Label(
            self, text="24-Hour Period", font=('Helvetica', 18, 'bold'), bg='black', fg='deepskyblue'
        )
        self.slide_title_label.pack(side=tk.TOP, anchor='center', pady=(2, 5))

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
        self.battery_energy_line, = self.ax.plot([], [], color=config.BATTERY_ENERGY_COLOR, label='Battery Stored Energy (SoC)', linewidth=1.8, alpha=0.9, zorder=2.1)
        self.battery_bottom_line, = self.ax.plot([], [], color=config.BATTERY_ENERGY_COLOR, label='_nolegend_', linewidth=1.0, alpha=0.4, zorder=2.0)
        self.battery_rate_line, = self.ax.plot([], [], color=config.EXPORT_COLOR, label='Battery Discharge Rate (kW)', linewidth=1.5, alpha=0.8, zorder=2.0)
        self.battery_fill = None

        # Slide 3 Axis (Circuit & Device Breakdown)
        rect_freq = [0.18, 0.12, 0.78, 0.82]
        self.ax_freq = self.fig.add_axes(rect_freq, facecolor='black')
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
            0.02, 1.02, "Awaiting AI Analysis...", transform=self.ax.transAxes, ha='left', va='top',
            fontsize=config.SUMMARY_FONT_SIZE, color=config.SUMMARY_COLOR, alpha=config.SUMMARY_ALPHA,
            fontfamily='monospace', weight='bold', zorder=10
        )
        self.summary_text_obj_freq = self.ax_freq.text(
            0.02, 1.02, "Awaiting Frequency Domain Analysis...", transform=self.ax_freq.transAxes, ha='left', va='top',
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
        history_explanation = data.get("history_explanation", "")
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
                
            if history_explanation:
                self.local_history_text = history_explanation.strip()
            else:
                self.local_history_text = "Awaiting 14-day history summary..."
                
            self.update_summary_display()

    def update_summary_display(self) -> None:
        """Refreshes subplot text watermarks depending on slide."""
        if self.current_slide == 1:
            text = self.baseline_text
            if self.local_delta_text:
                text += "\n" + self.local_delta_text
            self.summary_text_obj.set_text(self.wrap_text(text).replace('$', '\\$'))
        elif self.current_slide == 2:
            self.summary_text_obj.set_text(self.wrap_text(self.local_history_text).replace('$', '\\$'))
        else:
            pass  # Badge is dynamically drawn by update_chart for Slide 3
            
        # Redraw canvas if initialized
        if hasattr(self, 'canvas') and self.canvas is not None:
            self.canvas.draw_idle()

    def rotate_slides(self) -> None:
        """Slide transition scheduler loop across 3 slides in the user-specified order."""
        if self.current_slide == 1:
            self.current_slide = 2
            delay: int = config.SLIDE_2_DURATION_MS
        elif self.current_slide == 2:
            self.current_slide = 3
            delay = config.SLIDE_3_DURATION_MS
        else:
            self.current_slide = 1
            delay = config.SLIDE_1_DURATION_MS
            
        self.update_slide_visibility()
        self.after(delay, self.rotate_slides)

    def update_slide_visibility(self) -> None:
        """Swaps visibility of axes elements and updates titles."""
        if self.current_slide == 1:
            self.ax.set_visible(True)
            self.ax_bar.set_visible(True)
            self.ax_freq.set_visible(False)
            if hasattr(self, 'slide_title_label') and self.slide_title_label is not None:
                self.slide_title_label.config(text="24-Hour Period", fg='deepskyblue')
        elif self.current_slide == 2:
            self.ax.set_visible(True)
            self.ax_bar.set_visible(True)
            self.ax_freq.set_visible(False)
            if hasattr(self, 'slide_title_label') and self.slide_title_label is not None:
                self.slide_title_label.config(text="Zoom - 14-Day History", fg='orange')
        else:
            self.ax.set_visible(False)
            self.ax_bar.set_visible(False)
            self.ax_freq.set_visible(True)
            if hasattr(self, 'slide_title_label') and self.slide_title_label is not None:
                self.slide_title_label.config(text="Real-Time Circuit & Device Breakdown", fg='turquoise')
            
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
        if self.current_slide in (1, 2):
            with self.data_lock:
                usage_copy: List[float] = list(self.usage)
                timestamps_copy: List[datetime.datetime] = list(self.timestamps)
                se_timestamps_copy: List[datetime.datetime] = list(self.se_timestamps)
                se_power_copy: List[float] = list(self.se_power)
                chilicon_timestamps_copy: List[datetime.datetime] = list(self.chilicon_timestamps)
                chilicon_power_copy: List[float] = list(self.chilicon_power)
                se_load_power_timestamps_copy: List[datetime.datetime] = list(self.se_load_power_timestamps)
                se_load_power_copy: List[float] = list(self.se_load_power)
                se_battery_timestamps_copy: List[datetime.datetime] = list(self.se_battery_timestamps)
                se_battery_power_copy: List[float] = list(self.se_battery_power)
                se_battery_soc_copy: List[float] = list(self.se_battery_soc)

            # Range limit ending at most recent reading
            end_time: datetime.datetime = timestamps_copy[-1] if timestamps_copy else datetime.datetime.now()
            if self.current_slide == 1:
                start_time: datetime.datetime = end_time - datetime.timedelta(hours=24)
            else:
                start_time = end_time - datetime.timedelta(hours=config.HISTORY_HOURS)

            # Slice grid usage data to active window for rendering performance
            if timestamps_copy:
                start_idx: int = max(0, bisect.bisect_left(timestamps_copy, start_time) - 1)
                timestamps_copy = timestamps_copy[start_idx:]
                usage_copy = usage_copy[start_idx:]
                
                # If on Slide 2 and point count is extremely high, downsample with integer stride
                if self.current_slide == 2 and len(usage_copy) > 10000:
                    stride: int = len(usage_copy) // 5000
                    timestamps_copy = timestamps_copy[::stride]
                    usage_copy = usage_copy[::stride]

            # Slice SolarEdge PV data to active window
            if se_timestamps_copy:
                start_idx = max(0, bisect.bisect_left(se_timestamps_copy, start_time) - 1)
                se_timestamps_copy = se_timestamps_copy[start_idx:]
                se_power_copy = se_power_copy[start_idx:]

            # Slice Chillicon PV data to active window
            if chilicon_timestamps_copy:
                start_idx = max(0, bisect.bisect_left(chilicon_timestamps_copy, start_time) - 1)
                chilicon_timestamps_copy = chilicon_timestamps_copy[start_idx:]
                chilicon_power_copy = chilicon_power_copy[start_idx:]

            # Slice SolarEdge Load power data to active window
            if se_load_power_timestamps_copy:
                start_idx = max(0, bisect.bisect_left(se_load_power_timestamps_copy, start_time) - 1)
                se_load_power_timestamps_copy = se_load_power_timestamps_copy[start_idx:]
                se_load_power_copy = se_load_power_copy[start_idx:]

            # Slice SolarEdge Battery data to active window
            if se_battery_timestamps_copy:
                start_idx = max(0, bisect.bisect_left(se_battery_timestamps_copy, start_time) - 1)
                se_battery_timestamps_copy = se_battery_timestamps_copy[start_idx:]
                se_battery_power_copy = se_battery_power_copy[start_idx:]
                se_battery_soc_copy = se_battery_soc_copy[start_idx:]

            if len(usage_copy) > 1:
                x_nums = mdates.date2num(timestamps_copy)
                segments: List[Tuple[Tuple[float, float], Tuple[float, float]]] = []
                colors: List[str] = []
                widths: List[float] = []
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

            if hasattr(self, 'battery_fill') and self.battery_fill is not None:
                try:
                    self.battery_fill.remove()
                except Exception:
                    pass
                self.battery_fill = None

            soc_kwh_copy = []
            battery_bottom_copy = []
            battery_rate_filtered = []
            if len(se_battery_timestamps_copy) > 1:
                for soc, power in zip(se_battery_soc_copy, se_battery_power_copy):
                    if abs(power) < 0.05:
                        soc_kwh_copy.append(float('nan'))
                        battery_bottom_copy.append(float('nan'))
                        battery_rate_filtered.append(float('nan'))
                    else:
                        # Top of battery (fill level): 100% SoC = 0.0, 20% SoC = -8.0
                        soc_kwh_copy.append(soc * 0.1 - 10.0)
                        # Bottom of battery: constant line at -10.0
                        battery_bottom_copy.append(-10.0)
                        if power > 0.05:
                            # Only plot rate when discharging (discharge wattage above X)
                            battery_rate_filtered.append(power)
                        else:
                            # Omit charging rate below X (slope of SoC is sufficient)
                            battery_rate_filtered.append(float('nan'))
                self.battery_energy_line.set_data(se_battery_timestamps_copy, soc_kwh_copy)
                self.battery_bottom_line.set_data(se_battery_timestamps_copy, battery_bottom_copy)
                self.battery_rate_line.set_data(se_battery_timestamps_copy, battery_rate_filtered)
                
                # Render a semi-transparent solid fill representing the energy level
                self.battery_fill = self.ax.fill_between(
                    se_battery_timestamps_copy,
                    battery_bottom_copy,
                    soc_kwh_copy,
                    color=config.BATTERY_ENERGY_COLOR,
                    alpha=0.15,
                    zorder=1.9
                )
            else:
                self.battery_energy_line.set_data([], [])
                self.battery_bottom_line.set_data([], [])
                self.battery_rate_line.set_data([], [])

            self.ax.set_xlim(start_time, end_time)

            # Compute Y-limits dynamically so that the 10 kWh battery curve fits without clipping
            all_y_vals = [y for y in usage_copy if y == y]
            if len(se_load_power_copy) > 0:
                all_y_vals.extend([y for y in se_load_power_copy if y == y])
            if len(se_battery_timestamps_copy) > 0:
                all_y_vals.extend([y for y in soc_kwh_copy if y == y])
                all_y_vals.extend([y for y in battery_bottom_copy if y == y])
                all_y_vals.extend([y for y in battery_rate_filtered if y == y])

            if all_y_vals:
                y_min: float = min(all_y_vals)
                y_max: float = max(all_y_vals)
                y_range: float = max(y_max - y_min, 1.0)
                # Keep top range open to at least 10.0 to fit the battery capacity fully
                self.ax.set_ylim(min(0.0, y_min - 0.15 * y_range), max(10.0, y_max + 0.15 * y_range))

            # Solar edge bar charts
            self.ax_bar.clear()
            self.ax_bar.tick_params(colors='#fbbf24')
            self.ax_bar.yaxis.set_label_position('right')
            self.ax_bar.spines['right'].set_color('#fbbf24')
            self.ax_bar.spines['left'].set_color('none')
            self.ax_bar.spines['top'].set_color('none')
            self.ax_bar.spines['bottom'].set_color('none')
            self.ax_bar.set_ylabel('Total Solar PV (kW)', color='#fbbf24', rotation=270, labelpad=15)
            
            # Pre-group solar data to rounded slots for O(1) alignment checks
            from collections import defaultdict
            se_lookup: Dict[datetime.datetime, List[Tuple[datetime.datetime, float]]] = defaultdict(list)
            for ts, p in zip(se_timestamps_copy, se_power_copy):
                rounded_key = ts.replace(minute=(ts.minute // 10) * 10, second=0, microsecond=0)
                se_lookup[rounded_key].append((ts, p))

            ch_lookup: Dict[datetime.datetime, List[Tuple[datetime.datetime, float]]] = defaultdict(list)
            for ts, p in zip(chilicon_timestamps_copy, chilicon_power_copy):
                rounded_key = ts.replace(minute=(ts.minute // 10) * 10, second=0, microsecond=0)
                ch_lookup[rounded_key].append((ts, p))

            def get_closest_val(slot: datetime.datetime, lookup_dict: Dict[datetime.datetime, List[Tuple[datetime.datetime, float]]]) -> float:
                best_val: float = 0.0
                min_diff: datetime.timedelta = datetime.timedelta(minutes=15)
                for offset_mins in (-10, 0, 10):
                    key = slot + datetime.timedelta(minutes=offset_mins)
                    if key in lookup_dict:
                        for ts, p in lookup_dict[key]:
                            diff = abs(ts - slot)
                            if diff < min_diff:
                                min_diff = diff
                                best_val = p
                return best_val

            bar_times: List[datetime.datetime] = []
            se_heights: List[float] = []
            ch_heights: List[float] = []
            
            # Slide 1 uses 10-minute bars, Slide 2 aggregates to hourly slots to prevent GUI lag
            step_mins: int = 10 if self.current_slide == 1 else 60
            grid_start: datetime.datetime = start_time.replace(minute=(start_time.minute // step_mins) * step_mins, second=0, microsecond=0)
            current_slot: datetime.datetime = grid_start

            while current_slot <= end_time:
                bar_times.append(current_slot)
                se_heights.append(get_closest_val(current_slot, se_lookup))
                ch_heights.append(get_closest_val(current_slot, ch_lookup))
                current_slot += datetime.timedelta(minutes=step_mins)

            if bar_times:
                width_in_days: float = float(step_mins) / (24.0 * 60.0)
                self.ax_bar.bar(bar_times, se_heights, width=width_in_days, color='#fbbf24', alpha=0.1, zorder=1, edgecolor='none')
                self.ax_bar.bar(bar_times, ch_heights, bottom=se_heights, width=width_in_days, color='#ffff00', alpha=0.15, zorder=1.5, edgecolor='none')
                max_power = max([s + c for s, c in zip(se_heights, ch_heights)]) if bar_times else 1.0
                self.ax_bar.set_ylim(0, max_power * 1.1)
            else:
                self.ax_bar.set_ylim(0, 10)

            self.canvas.draw()

        elif self.current_slide == 3:
            self.ax_freq.clear()
            self.ax_freq.set_facecolor('black')
            self.ax_freq.tick_params(colors='white', labelsize=8)
            self.ax_freq.spines['bottom'].set_color('white')
            self.ax_freq.spines['left'].set_color('white')
            self.ax_freq.spines['right'].set_color('none')
            self.ax_freq.spines['top'].set_color('none')
            self.ax_freq.set_xlabel('Power Draw (Watts)', color='white', fontsize=9)

            with self.data_lock:
                circuits_snapshot = list(getattr(self, 'circuit_telemetry', []))
                last_ts = getattr(self, 'last_circuit_fetch_time', 0.0)

            if not circuits_snapshot:
                circuits_snapshot = emporia_vue.generate_simulated_telemetry()
                last_ts = time.time()

            # Separate Main and Balance if present
            main_item = next((c for c in circuits_snapshot if c.get('type') == 'main'), None)
            balance_item = next((c for c in circuits_snapshot if c.get('type') in ('balance', 'residual')), None)

            # Active branch circuits & plugs (> 5W)
            branch_candidates = [
                c for c in circuits_snapshot
                if c.get('type') not in ('main', 'balance', 'residual', 'total') and c.get('watts', 0.0) > 5.0
            ]
            # Pick top 8 active individual consumer loads
            branch_candidates.sort(key=lambda c: c.get('watts', 0.0), reverse=True)
            selected_branches = branch_candidates[:8]

            # Assemble chart items: branches + balance, sorted ascending for barh
            chart_items = list(selected_branches)
            if balance_item and balance_item.get('watts', 0.0) > 0.0:
                chart_items.append(balance_item)

            chart_items.sort(key=lambda c: c.get('watts', 0.0))

            # Pin Whole-Home Main at the very top of the horizontal bar chart
            if main_item:
                chart_items.append(main_item)

            if chart_items:
                names = [c['name'] for c in chart_items]
                watts = [c['watts'] for c in chart_items]
                colors = [c['color'] for c in chart_items]

                display_names = []
                for n in names:
                    sn = (
                        n.replace("1 family room -office", "Office (Panel)")
                        .replace("music room right main (Ch 10)", "Music Right Main")
                        .replace("9 Music room Left", "Music Left Main")
                        .replace("music room left", "Music Left Main")
                        .replace("16 music room", "16 Music Room (Panel)")
                        .replace("8 Kitchen lights & plugs", "Kitchen Lights/Plugs")
                        .replace("7 kitchen plugs", "Kitchen Counter Plugs")
                        .replace("big-len UPS", "Big-Len UPS (Plug)")
                        .replace("giga and lem", "Giga & Lem (Plug)")
                        .replace("A/C (Ch 6 & 13)", "A/C (Panel)")
                        .replace("bedroom ups", "Bedroom UPS (Plug)")
                        .replace("avm 60", "Anthem AVM 60 (Plug)")
                        .replace("kitchen tv", "Kitchen TV (Plug)")
                        .replace("200A Mains (Total)", "200A Mains")
                        .replace("Residual (Unmonitored)", "Balance")
                        .replace("Residual", "Balance")
                    )
                    display_names.append(sn)

                y_pos = list(range(len(chart_items)))
                bars = self.ax_freq.barh(y_pos, watts, color=colors, height=0.65, edgecolor='none', alpha=0.9)
                self.ax_freq.set_yticks(y_pos)
                self.ax_freq.set_yticklabels(display_names, color='white', fontsize=8)

                # Reference whole-home power baseline for percentage calculation
                if main_item and main_item.get('watts', 0.0) > 0:
                    total_ref_w = main_item['watts']
                elif self.se_load_power and self.se_load_power[-1] > 0:
                    total_ref_w = self.se_load_power[-1] * 1000.0
                else:
                    total_ref_w = sum(c.get('watts', 0.0) for c in chart_items if c.get('type') != 'main')

                if total_ref_w <= 0:
                    total_ref_w = max(watts) if watts else 1000.0

                max_w = max(watts) if watts else 100.0
                for bar, w in zip(bars, watts):
                    pct = (w / total_ref_w * 100.0) if total_ref_w > 0 else 0.0
                    label_str = f" {int(round(w))} W ({pct:.1f}%)"
                    self.ax_freq.text(
                        bar.get_width() + (max_w * 0.01), bar.get_y() + bar.get_height() / 2,
                        label_str,
                        va='center', ha='left', color='white', fontsize=8, weight='bold'
                    )

                self.ax_freq.set_xlim(0, max_w * 1.38)
                self.ax_freq.grid(axis='x', color='gray', linestyle=':', alpha=0.3)

                from matplotlib.patches import Patch
                legend_elements = [
                    Patch(facecolor='#c084fc', label='Main & Grid'),
                    Patch(facecolor='#38bdf8', label='Compute & Lab'),
                    Patch(facecolor='#4ade80', label='Audio & Entertainment'),
                    Patch(facecolor='#f87171', label='Major Appliances'),
                    Patch(facecolor='#facc15', label='General Household'),
                    Patch(facecolor='#94a3b8', label='Balance'),
                ]
                self.ax_freq.legend(
                    handles=legend_elements,
                    loc='lower right',
                    facecolor='black', edgecolor='white', labelcolor='white', fontsize=7.5,
                    ncol=2
                )

            elapsed = int(time.time() - last_ts) if last_ts > 0 else 0
            time_str = time.strftime('%H:%M:%S', time.localtime(last_ts)) if last_ts > 0 else "N/A"
            badge_text = f"Telemetry Snapshot: {time_str} ({elapsed}s ago) | Monitored: {len(circuits_snapshot)} Circuits & Plugs"
            self.summary_text_obj_freq = self.ax_freq.text(
                0.02, 1.03, badge_text,
                transform=self.ax_freq.transAxes, ha='left', va='bottom',
                fontsize=9, color='#38bdf8', alpha=0.9,
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
        """Syncs the database and telemetry CSV/JSON cache files from the remote kiosk.

        Raises:
            subprocess.SubprocessError: If the SCP network transfer fails (logged internally).
        """
        logging.info("Checking remote updates from rainforestpi...")
        import subprocess
        try:
            subprocess.run([
                "scp", 
                "steven@rainforestpi:~/rainforest-emu2-grid-dashboard/grid_history.db",
                "steven@rainforestpi:~/rainforest-emu2-grid-dashboard/solaredge*.csv",
                "steven@rainforestpi:~/rainforest-emu2-grid-dashboard/chilicon*.csv",
                "steven@rainforestpi:~/rainforest-emu2-grid-dashboard/*.json",
                SCRIPT_DIR
            ], timeout=15)
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
        ImageGrab.grab(bbox).convert('RGB').save(os.path.join(SCRIPT_DIR, f"1_slide{suffix}.jpeg"), quality=95)
        
        # Save Slide 2
        self.current_slide = 2
        self.update_slide_visibility()
        self.update_idletasks()
        self.update()
        time.sleep(0.5)
        ImageGrab.grab(bbox).convert('RGB').save(os.path.join(SCRIPT_DIR, f"2_slide{suffix}.jpeg"), quality=95)

        # Save Slide 3
        self.current_slide = 3
        self.update_slide_visibility()
        self.update_idletasks()
        self.update()
        time.sleep(0.5)
        ImageGrab.grab(bbox).convert('RGB').save(os.path.join(SCRIPT_DIR, f"3_slide{suffix}.jpeg"), quality=95)


if __name__ == "__main__":
    if "--screenshot" in sys.argv:
        viewer = OfflineViewer()
        viewer.save_screenshot()
        viewer.on_close()
    else:
        viewer = OfflineViewer()
        viewer.mainloop()
