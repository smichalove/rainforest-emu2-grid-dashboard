"""Tkinter grid monitor dashboard application running on the ingest node.

Delegates hardware communication, file IO, API clients, spectral analysis, and
LLM processing to the dashboard_modules package, retaining UI layout, background
loops, and robust backward-compatible helper delegates.
"""

import csv
import datetime
import json
import logging
import os
import queue
import signal
import urllib.request
import sys
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

# Third-party libraries
from PIL import Image, ImageTk
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.collections import LineCollection
import matplotlib.dates as mdates
from matplotlib.figure import Figure
try:
    import serial
    import serial.tools.list_ports
except ImportError:
    class DummySerial:
        pass
    serial = DummySerial()
    serial.Serial = DummySerial
import tkinter as tk

# Modular Package Imports
from dashboard_modules import config, io, telemetry, solar, weather, spectral, ai

# Setup logging
home_dir: str = os.path.expanduser('~')
script_dir: str = os.path.dirname(os.path.abspath(__file__))
logging.basicConfig(
    filename=os.path.join(home_dir, 'dashboard.log'),
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s'
)


class GridDashboard(tk.Tk):
    """A fullscreen Tkinter dashboard application that visualizes real-time power grid usage.

    This class handles the GUI window lifecycle, mounts the Matplotlib figure canvas,
    orchestrates background daemon loops, and runs a self-healing thread supervisor.
    """

    # --- Class-level defaults to prevent Tkinter __getattr__ recursion during unit tests ---
    solar_off: bool = False
    chilicon_off: bool = False
    local_llm: bool = False
    running: bool = True
    
    usage: List[float] = []
    timestamps: List[datetime.datetime] = []
    max_points: int = 5760

    solaredge_api_key: Optional[str] = None
    solaredge_site_id: Optional[str] = None
    se_timestamps: List[datetime.datetime] = []
    se_power: List[float] = []
    se_battery_timestamps: List[datetime.datetime] = []
    se_battery_power: List[float] = []
    se_battery_soc: List[float] = []

    chilicon_username: Optional[str] = None
    chilicon_password: Optional[str] = None
    chilicon_installation_hash: Optional[str] = None
    chilicon_timestamps: List[datetime.datetime] = []
    chilicon_power: List[float] = []
    chilicon_energy: List[float] = []

    last_weather_fetch_time: Optional[datetime.datetime] = None
    cached_weather: Dict[str, Optional[float]] = {}
    weather_map: Dict[str, Dict[str, Any]] = {}

    latest_status_text: str = "Waiting for data..."
    latest_status_color: str = "white"
    solar_bars_dirty: bool = True
    current_slide: int = 1
    local_time_text: str = "Awaiting AI Analysis..."
    local_dft_text: str = "Awaiting Frequency Domain Analysis..."
    baseline_text: str = ""
    local_delta_text: str = ""

    history_file: str = ""
    se_history_file: str = ""
    se_battery_history_file: str = ""
    chilicon_history_file: str = ""
    summary_cache_file: str = ""
    llm_mode: str = "direct"
    jetson_host: str = "localhost"
    jetson_port: str = "5000"
    jetson_user: str = "steven"
    summary_text_obj: Any = None
    summary_text_obj_freq: Any = None
    serial_thread: Optional[threading.Thread] = None
    solaredge_thread: Optional[threading.Thread] = None
    chilicon_thread: Optional[threading.Thread] = None
    summary_thread: Optional[threading.Thread] = None
    local_delta_thread: Optional[threading.Thread] = None

    se_client: Optional[solar.SolarEdgeClient] = None
    ch_client: Optional[solar.ChilliconClient] = None
    ser: Optional[serial.Serial] = None
    
    status_label: Optional[tk.Label] = None
    sub_status_label: Optional[tk.Label] = None
    chilicon_status_label: Optional[tk.Label] = None
    weather_label: Optional[tk.Label] = None
    time_label: Optional[tk.Label] = None
    date_label: Optional[tk.Label] = None

    _data_lock_inst: Optional[threading.Lock] = None
    # --------------------------------------------------------------------------------------

    def __init__(self) -> None:
        """Initializes the GridDashboard window, plot, and background supervisor."""
        super().__init__()
        self.title("EMU-2 Grid Monitor")
        
        # Kiosk mode settings
        self.attributes("-fullscreen", True)
        self.configure(bg='black')
        self.bind("<Escape>", lambda e: self.destroy())
        self.bind("<Button-1>", lambda e: self.destroy())

        # Thread synchronization lock
        self._data_lock_inst = threading.Lock()
        self.ui_queue: queue.Queue = queue.Queue()

        # Telemetry state buffers
        self.usage = []
        self.timestamps = []
        self.max_points = 5760

        # Solar Edge credentials & arrays
        self.solaredge_api_key = None
        self.solaredge_site_id = None
        self.se_timestamps = []
        self.se_power = []
        self.se_battery_timestamps = []
        self.se_battery_power = []
        self.se_battery_soc = []

        # Chillicon credentials & arrays
        self.chilicon_username = None
        self.chilicon_password = None
        self.chilicon_installation_hash = None
        self.chilicon_timestamps = []
        self.chilicon_power = []
        self.chilicon_energy = []

        # Weather arrays
        self.last_weather_fetch_time = None
        self.cached_weather = {}
        self.weather_map = {}

        # CLI Flags
        self.solar_off = "--solaroff" in sys.argv
        self.chilicon_off = "--chiliconoff" in sys.argv
        self.local_llm = "--localllm" in sys.argv

        # UI State variables
        self.latest_status_text = "Waiting for data..."
        self.latest_status_color = "white"
        self.solar_bars_dirty = True
        self.current_slide = 1
        self.local_time_text = "Awaiting AI Analysis..."
        self.local_dft_text = "Awaiting Frequency Domain Analysis..."
        self.baseline_text = ""
        self.local_delta_text = ""

        # Resolve paths
        self.history_file = os.path.join(script_dir, 'grid_history.csv')
        self.se_history_file = os.path.join(script_dir, 'solaredge_history.csv')
        self.se_battery_history_file = os.path.join(script_dir, 'solaredge_battery_history.csv')
        self.chilicon_history_file = os.path.join(script_dir, 'chilicon_history.csv')
        self.summary_cache_file = os.path.join(script_dir, 'gemini_summary.json')

        # Load configurations and credentials
        self.load_credentials()

        # Load LLM and Jetson sync configurations from environment
        self.llm_mode = os.environ.get("LLM_MODE", "direct").lower().strip()
        self.jetson_host = os.environ.get("JETSON_HOST", "localhost").strip()
        self.jetson_port = os.environ.get("JETSON_PORT", "5000").strip()
        self.jetson_user = os.environ.get("JETSON_USER", "steven").strip()
        logging.info(f"Initialized LLM mode: '{self.llm_mode}' (Jetson: {self.jetson_host}:{self.jetson_port})")

        # Build clients
        self.se_client = solar.SolarEdgeClient(
            api_key=self.solaredge_api_key or "",
            site_id=self.solaredge_site_id or "",
            history_file=self.se_history_file,
            battery_history_file=self.se_battery_history_file
        )
        self.ch_client = solar.ChilliconClient(
            username=self.chilicon_username or "",
            password=self.chilicon_password or "",
            installation_hash=self.chilicon_installation_hash or "",
            history_file=self.chilicon_history_file
        )

        # Load history
        self.load_history_files()

        # Hardware logos small banner
        self.logo_image_tk = None
        try:
            logo_path = os.path.join(script_dir, "scratch", "combined_logos_small.png")
            if os.path.exists(logo_path):
                img = Image.open(logo_path)
                self.logo_image_tk = ImageTk.PhotoImage(img)
        except Exception as e:
            logging.error(f"Failed to load logo banner image: {e}")

        # Setup GUI Widgets
        self.setup_widgets()

        # Canvas & Chart setup
        self.setup_canvas()

        # Launch background threads
        self.running = True
        self.ser = None
        self.start_background_loops()

        # Thread health supervisor loop
        self.start_watchdog_loop()

        # slide rotation loop (initially Slide 1)
        self.after(config.SLIDE_1_DURATION_MS, self.rotate_slides)

        # Start visual refreshing
        self.start_fast_render_loop()
        self.process_ui_queue()

        # Register termination signal handlers
        signal.signal(signal.SIGINT, self.handle_signal)
        signal.signal(signal.SIGTERM, self.handle_signal)
        self.check_signals()

    @property
    def data_lock(self) -> threading.Lock:
        """Get the thread synchronization lock."""
        lock = getattr(self, '_data_lock_inst', None)
        if lock is None:
            lock = threading.Lock()
            self._data_lock_inst = lock
        return lock

    # --- Backward-Compatibility Class Method Delegates with try/except safeguards ---

    def hex_to_signed_int(self, hex_str: str, bits: int = 32) -> int:
        """Converts hex representation to signed integer (delegate)."""
        try:
            return telemetry.hex_to_signed_int(hex_str, bits)
        except Exception as e:
            logging.error(f"Resilient fallback error in hex_to_signed_int: {e}")
            return 0

    def load_credentials(self) -> None:
        """Loads configuration maps and sets system credentials (delegate)."""
        try:
            se_creds, ch_creds = config.load_env_credentials()
            self.solaredge_api_key = se_creds["api_key"]
            self.solaredge_site_id = se_creds["site_id"]
            self.chilicon_username = ch_creds["username"]
            self.chilicon_password = ch_creds["password"]
            self.chilicon_installation_hash = ch_creds["installation_hash"]
        except Exception as e:
            logging.error(f"Resilient fallback error in load_credentials: {e}")

    def load_history(self) -> None:
        """Loads historical measurements from CSV (delegate)."""
        try:
            path = self.history_file if self.history_file else os.path.join(script_dir, 'grid_history.csv')
            self.timestamps, self.usage = telemetry.load_grid_history(path)
        except Exception as e:
            logging.error(f"Resilient fallback error in load_history: {e}")

    def load_solaredge_history(self) -> None:
        """Loads SolarEdge PV history (delegate)."""
        try:
            if not self.solar_off:
                client = self.se_client
                if client is None:
                    path = self.se_history_file if self.se_history_file else os.path.join(script_dir, 'solaredge_history.csv')
                    bat_path = self.se_battery_history_file if self.se_battery_history_file else os.path.join(script_dir, 'solaredge_battery_history.csv')
                    client = solar.SolarEdgeClient("", "", path, bat_path)
                
                self.se_timestamps, self.se_power, self.se_battery_timestamps, self.se_battery_power, self.se_battery_soc = client.load_history()
        except Exception as e:
            logging.error(f"Resilient fallback error in load_solaredge_history: {e}")

    def load_chilicon_history(self) -> None:
        """Loads Chillicon PV history (delegate)."""
        try:
            if not self.chilicon_off:
                client = self.ch_client
                if client is None:
                    path = self.chilicon_history_file if self.chilicon_history_file else os.path.join(script_dir, 'chilicon_history.csv')
                    client = solar.ChilliconClient("", "", "", path)
                
                self.chilicon_timestamps, self.chilicon_power, self.chilicon_energy = client.load_history()
        except Exception as e:
            logging.error(f"Resilient fallback error in load_chilicon_history: {e}")

    def load_cached_summary(self) -> None:
        """Loads previously cached summaries (both time-domain and frequency-domain) from disk."""
        if not self.summary_cache_file or not os.path.exists(self.summary_cache_file):
            self.update_summary_display()
            return
            
        try:
            data = io.read_safe_json(self.summary_cache_file)
            if data:
                ts_str = data.get("timestamp")
                summary = data.get("summary", "")
                dft_explanation = data.get("dft_explanation", "")
                
                if ts_str and summary:
                    try:
                        self.last_summary_time = datetime.datetime.fromisoformat(ts_str)
                    except Exception:
                        self.last_summary_time = None
                        
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
        except Exception as e:
            logging.error(f"Failed to load cached summary: {e}")
            
        self.update_summary_display()

    def fetch_solaredge_data(self) -> None:
        """Polls SolarEdge API (delegate)."""
        try:
            client = self.se_client
            if client is None:
                path = self.se_history_file if self.se_history_file else os.path.join(script_dir, 'solaredge_history.csv')
                bat_path = self.se_battery_history_file if self.se_battery_history_file else os.path.join(script_dir, 'solaredge_battery_history.csv')
                client = solar.SolarEdgeClient(self.solaredge_api_key or "", self.solaredge_site_id or "", path, bat_path)
            
            res = client.fetch_data()
            if res:
                with self.data_lock:
                    self.se_timestamps.append(res["timestamp"])
                    self.se_power.append(res["pv_power"])
                    self.se_battery_timestamps.append(res["timestamp"])
                    self.se_battery_power.append(res["battery_power"])
                    self.se_battery_soc.append(res["battery_soc"])
                self.solar_bars_dirty = True
                if self.sub_status_label is not None:
                    self.ui_queue.put(lambda: self.sub_status_label.config(text=f"SolarEdge PV: {res['pv_power']:.3f} kW"))
        except Exception as e:
            logging.error(f"Resilient fallback error in fetch_solaredge_data: {e}")

    def fetch_chilicon_data(self) -> None:
        """Polls Chillicon API (delegate)."""
        try:
            client = self.ch_client
            if client is None:
                path = self.chilicon_history_file if self.chilicon_history_file else os.path.join(script_dir, 'chilicon_history.csv')
                client = solar.ChilliconClient(self.chilicon_username or "", self.chilicon_password or "", self.chilicon_installation_hash or "", path)
            
            res = client.fetch_data()
            if res:
                power, energy, now = res
                with self.data_lock:
                    self.chilicon_timestamps.append(now)
                    self.chilicon_power.append(power)
                    self.chilicon_energy.append(energy)
                self.solar_bars_dirty = True
                if self.chilicon_status_label is not None:
                    self.ui_queue.put(lambda: self.chilicon_status_label.config(text=f"Chillicon PV: {power:.3f} kW"))
        except Exception as e:
            logging.error(f"Resilient fallback error in fetch_chilicon_data: {e}")

    def generate_hourly_summaries(self) -> str:
        """Formats hourly history summaries (delegate)."""
        try:
            grid_p = self.history_file if self.history_file else os.path.join(script_dir, 'grid_history.csv')
            se_p = self.se_history_file if (not self.solar_off and self.se_history_file) else (os.path.join(script_dir, 'solaredge_history.csv') if not self.solar_off else "")
            se_bat = self.se_battery_history_file if (not self.solar_off and self.se_battery_history_file) else (os.path.join(script_dir, 'solaredge_battery_history.csv') if not self.solar_off else "")
            ch_p = self.chilicon_history_file if (not self.chilicon_off and self.chilicon_history_file) else (os.path.join(script_dir, 'chilicon_history.csv') if not self.chilicon_off else "")
            return ai.generate_hourly_summaries(grid_p, se_p, se_bat, ch_p)
        except Exception as e:
            logging.error(f"Resilient fallback error in generate_hourly_summaries: {e}")
            return ""

    def fetch_gemini_summary(self) -> None:
        """Formats and queries summaries (delegate)."""
        try:
            self.fetch_live_summary()
        except Exception as e:
            logging.error(f"Resilient fallback error in fetch_gemini_summary: {e}")

    def align_and_compute_spectrum(self) -> Tuple[List[float], List[float], List[float], List[float], List[float]]:
        """Computes spectral parameters (delegate)."""
        try:
            with self.data_lock:
                g_ts, g_u = list(self.timestamps), list(self.usage)
                se_ts, se_p = list(self.se_timestamps), list(self.se_power)
                ch_ts, ch_p = list(self.chilicon_timestamps), list(self.chilicon_power)
            return spectral.align_and_compute_spectra(
                g_ts, g_u, se_ts, se_p, ch_ts, ch_p, self.weather_map, self.chilicon_off
            )
        except Exception as e:
            logging.error(f"Resilient fallback error in align_and_compute_spectrum: {e}")
            return [], [], [], [], []

    def process_chunk(self, xml_data: str) -> None:
        """Backward-compatibility mapping for process_serial_chunk (delegate)."""
        try:
            self.process_serial_chunk(xml_data)
        except Exception as e:
            logging.error(f"Resilient fallback error in process_chunk: {e}")

    def read_serial(self) -> None:
        """Backward-compatibility mapping for serial_loop (delegate)."""
        try:
            self.serial_loop()
        except Exception as e:
            logging.error(f"Resilient fallback error in read_serial: {e}")

    def find_emu2_port(self) -> str:
        """Backward-compatibility mapping for telemetry.find_emu2_port (delegate)."""
        try:
            return telemetry.find_emu2_port()
        except Exception as e:
            logging.error(f"Resilient fallback error in find_emu2_port: {e}")
            return '/dev/ttyACM0'

    # --- End of backward-compatibility class methods ---

    def load_history_files(self) -> None:
        """Loads all CSV history arrays on startup."""
        self.load_history()
        self.load_solaredge_history()
        self.load_chilicon_history()

        # Load cached summaries
        self.load_cached_summary()

        # Initial weather map cache load
        try:
            self.weather_map = weather.fetch_historical_weather()
        except Exception as e:
            logging.error(f"Error loading initial historical weather cache: {e}")

    def setup_widgets(self) -> None:
        """Constructs all Tkinter headers, labels, and columns."""
        self.header_frame = tk.Frame(self, bg='black')
        self.header_frame.pack(fill=tk.X, padx=20, pady=10)

        # Left Column (Time & Weather)
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

        # Right Column (Grid Demand & Inverter stats)
        self.right_header = tk.Frame(self.header_frame, bg='black')
        self.right_header.pack(side=tk.RIGHT, anchor='ne')

        self.status_label = tk.Label(
            self.right_header, text="Waiting for data...", font=('Helvetica', config.STATUS_FONT_SIZE, 'bold'), bg='black', fg='white', anchor='e'
        )
        self.status_label.pack(anchor='e', pady=(0, 2))

        self.sub_status_label = tk.Label(
            self.right_header, text="", font=('Helvetica', 16, 'bold'), bg='black', fg='#fbbf24', anchor='e'
        )
        if not self.solar_off:
            self.sub_status_label.pack(anchor='e', pady=(0, 2))
            latest_pv = self.se_power[-1] if self.se_power else 0.0
            self.sub_status_label.config(text=f"SolarEdge PV: {latest_pv:.3f} kW")

        self.chilicon_status_label = tk.Label(
            self.right_header, text="", font=('Helvetica', 16, 'bold'), bg='black', fg='#ffff00', anchor='e'
        )
        if not self.chilicon_off:
            self.chilicon_status_label.pack(anchor='e', pady=(0, 2))
            latest_ch = self.chilicon_power[-1] if self.chilicon_power else 0.0
            self.chilicon_status_label.config(text=f"Chillicon PV: {latest_ch:.3f} kW")

        # Hardware logos küçük banner
        if self.logo_image_tk:
            self.logo_label = tk.Label(self, image=self.logo_image_tk, bg='black')
            self.logo_label.pack(side=tk.TOP, anchor='center', pady=(5, 5))

        # Update labels if initial telemetry was loaded
        if self.usage:
            latest_val = self.usage[-1]
            status = "Solar Export" if latest_val < 0 else "Grid Import"
            color = config.EXPORT_COLOR if latest_val < 0 else config.IMPORT_COLOR
            self.latest_status_text = f"{latest_val:.3f} kW | {status}"
            self.latest_status_color = color
            self.status_label.config(text=self.latest_status_text, fg=self.latest_status_color)

    def setup_canvas(self) -> None:
        """Sets up the overlapping Matplotlib subplots (Slide 1 & Slide 2)."""
        self.fig = Figure(figsize=(5, 3), dpi=100, facecolor='black')
        rect = [0.08, 0.12, 0.88, 0.82]

        # Slide 1 Axis (Time Domain)
        self.ax = self.fig.add_axes(rect)
        self.ax.set_facecolor('black')
        self.ax.tick_params(colors='white')
        self.ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
        self.fig.autofmt_xdate()
        self.ax.spines['bottom'].set_color('white')
        self.ax.spines['left'].set_color('white')
        self.ax.spines['top'].set_color('black')
        self.ax.spines['right'].set_color('black')

        if not self.solar_off:
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

        # LineCollection for Slide 1 Grid plot
        self.lc = LineCollection([], linewidths=1.8, zorder=2)
        self.ax.add_collection(self.lc)

        # Slide 2 Axis (Frequency Domain)
        self.ax_freq = self.fig.add_axes(rect, facecolor='black')
        self.ax_freq.tick_params(colors='white')
        self.ax_freq.spines['bottom'].set_color('white')
        self.ax_freq.spines['left'].set_color('white')
        self.ax_freq.spines['right'].set_color('none')
        self.ax_freq.spines['top'].set_color('none')
        self.ax_freq.set_xlabel('Frequency (Cycles per Day)', color='white', fontsize=9)
        self.ax_freq.set_ylabel('Spectral Amplitude (kW)', color='white', fontsize=9)
        self.ax_freq.set_visible(False)

        # Watermarks
        self.summary_text_obj = self.ax.text(
            0.02, 0.95, "Awaiting AI Analysis...",
            transform=self.ax.transAxes, ha='left', va='top',
            fontsize=config.SUMMARY_FONT_SIZE, color=config.SUMMARY_COLOR, alpha=config.SUMMARY_ALPHA,
            fontfamily='monospace', weight='bold', zorder=10
        )
        self.summary_text_obj_freq = self.ax_freq.text(
            0.02, 0.95, "Awaiting Frequency Domain Analysis...",
            transform=self.ax_freq.transAxes, ha='left', va='top',
            fontsize=config.SUMMARY_FONT_SIZE, color=config.SUMMARY_COLOR, alpha=config.SUMMARY_ALPHA,
            fontfamily='monospace', weight='bold', zorder=10
        )

        self.canvas = FigureCanvasTkAgg(self.fig, master=self)
        self.canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)

    def start_background_loops(self) -> None:
        """Spawns background polling threads for serial & APIs."""
        # 1. EMU-2 Serial Connection
        self.serial_thread = threading.Thread(target=self.serial_loop, name="SerialLoopThread", daemon=True)
        self.serial_thread.start()

        # 2. SolarEdge Client Poller
        self.start_solaredge_loop()

        # 3. Chillicon Client Poller
        self.start_chilicon_loop()

        # 4. AI/Gemini summary loop
        self.summary_thread = threading.Thread(target=self.summary_loop, name="SummaryLoopThread", daemon=True)
        self.summary_thread.start()

        # 5. Local Delta tracking (in decoupled mode)
        if self.llm_mode == "decoupled":
            self.local_delta_thread = threading.Thread(target=self.local_delta_loop, name="LocalDeltaThread", daemon=True)
            self.local_delta_thread.start()

    def start_watchdog_loop(self) -> None:
        """Launches a thread watcher to restart crashed daemon loops."""
        self.watchdog_thread = threading.Thread(target=self.watchdog_loop, name="WatchdogThread", daemon=True)
        self.watchdog_thread.start()

    def watchdog_loop(self) -> None:
        """Polls thread states and performs self-healing reconnects."""
        while self.running:
            time.sleep(60)
            if not self.running:
                break
                
            # Check EMU-2 Serial loop
            if not self.serial_thread.is_alive():
                logging.warning("Supervisor Watchdog detected SerialLoopThread crash! Restarting...")
                self.serial_thread = threading.Thread(target=self.serial_loop, name="SerialLoopThread", daemon=True)
                self.serial_thread.start()

            # Check SolarEdge Loop
            if not self.solar_off and (self.solaredge_thread is None or not self.solaredge_thread.is_alive()):
                logging.warning("Supervisor Watchdog detected SolarEdgeLoopThread crash! Restarting...")
                self.start_solaredge_loop()

            # Check Chillicon Loop
            if not self.chilicon_off and (self.chilicon_thread is None or not self.chilicon_thread.is_alive()):
                logging.warning("Supervisor Watchdog detected ChilliconLoopThread crash! Restarting...")
                self.start_chilicon_loop()

            # Check Summary Loop
            if not self.summary_thread.is_alive():
                logging.warning("Supervisor Watchdog detected SummaryLoopThread crash! Restarting...")
                self.summary_thread = threading.Thread(target=self.summary_loop, name="SummaryLoopThread", daemon=True)
                self.summary_thread.start()

    def serial_loop(self) -> None:
        """Isolated serial polling loop."""
        buffer: str = ""
        while self.running:
            port_to_use = self.find_emu2_port()
            try:
                self.ser = serial.Serial(port_to_use, config.BAUD, timeout=1)
                logging.info(f"Successfully opened {port_to_use} at {config.BAUD} baud.")
            except Exception as e:
                logging.error(f"Failed to open port {port_to_use}: {e}. Retrying in 5s...")
                self.update_ui_text("Hardware disconnected.\nRetrying...")
                time.sleep(5)
                continue

            try:
                while self.running and self.ser.is_open:
                    data = self.ser.read(self.ser.in_waiting or 1)
                    if data:
                        buffer += data.decode('utf-8', errors='ignore')
                        while '<InstantaneousDemand>' in buffer and '</InstantaneousDemand>' in buffer:
                            start = buffer.find('<InstantaneousDemand>')
                            end = buffer.find('</InstantaneousDemand>') + len('</InstantaneousDemand>')
                            chunk = buffer[start:end]
                            self.process_serial_chunk(chunk)
                            buffer = buffer[end:]
                    time.sleep(0.1)
            except Exception as e:
                if self.running:
                    logging.error(f"Serial thread connection error: {e}. Reconnecting in 5s...")
                time.sleep(5)
            finally:
                if self.ser and self.ser.is_open:
                    self.ser.close()

    def process_serial_chunk(self, xml_data: str) -> None:
        """Parses XML grid updates and logs to history."""
        actual_kw = telemetry.parse_xml_telemetry(xml_data)
        if actual_kw is None:
            return
            
        logging.info(f"Parsed Demand: {actual_kw:.3f} kW")
        now_ts = datetime.datetime.now()
        
        with self.data_lock:
            self.usage.append(actual_kw)
            self.timestamps.append(now_ts)
            if len(self.usage) > self.max_points:
                self.usage.pop(0)
                self.timestamps.pop(0)

        # Log to CSV
        telemetry.log_grid_telemetry(self.history_file, now_ts, actual_kw)

        # UI state variables
        status = "Solar Export" if actual_kw < 0 else "Grid Import"
        color = config.EXPORT_COLOR if actual_kw < 0 else config.IMPORT_COLOR
        text = f"{actual_kw:.3f} kW | {status}"
        self.latest_status_text = text
        self.latest_status_color = color

        if self.status_label is not None:
            self.ui_queue.put(lambda: self.status_label.config(text=text, fg=color))

    def start_solaredge_loop(self) -> None:
        """Spawns the background thread to poll SolarEdge every 15 minutes."""
        if self.solar_off:
            return
        self.solaredge_thread = threading.Thread(
            target=self.solaredge_loop, name="SolarEdgeLoopThread", daemon=True
        )
        self.solaredge_thread.start()

    def start_chilicon_loop(self) -> None:
        """Spawns the background thread to poll Chillicon every 15 minutes."""
        if self.chilicon_off:
            return
        self.chilicon_thread = threading.Thread(
            target=self.chilicon_loop, name="ChilliconLoopThread", daemon=True
        )
        self.chilicon_thread.start()

    def solaredge_loop(self) -> None:
        """Isolated SolarEdge API loop."""
        while self.running:
            self.fetch_solaredge_data()
            # Sleep for 15m (converts to 90 sleep segments of 10s to monitor self.running shutdown speed)
            for _ in range(90):
                if not self.running:
                    break
                time.sleep(10)

    def chilicon_loop(self) -> None:
        """Isolated Chillicon scraper loop."""
        while self.running:
            self.fetch_chilicon_data()
            for _ in range(90):
                if not self.running:
                    break
                time.sleep(10)

    def summary_loop(self) -> None:
        """Polls cached AI logs or runs live model queries."""
        time.sleep(10)
        
        if self.llm_mode == "decoupled":
            logging.info("Running in decoupled summary loop (polling cache file).")
            last_mtime: float = 0.0
            while self.running:
                try:
                    if os.path.exists(self.summary_cache_file):
                        mtime = os.path.getmtime(self.summary_cache_file)
                        if mtime > last_mtime:
                            last_mtime = mtime
                            self.load_cached_summary()
                except Exception as e:
                    logging.error(f"Failed in decoupled summary loop: {e}")
                time.sleep(10)
        else:
            logging.info("Running in direct summary loop (querying Gemini API directly).")
            while self.running:
                self.fetch_gemini_summary()
                for _ in range(90):
                    if not self.running:
                        break
                    time.sleep(10)

    def fetch_live_summary(self) -> None:
        """Formats hourly histories and queries Gemini/Ollama directly."""
        if not self.usage or len(self.usage) < 10:
            return

        now = datetime.datetime.now()
        if self.last_summary_time and now - self.last_summary_time < datetime.timedelta(minutes=15):
            return

        csv_data = self.generate_hourly_summaries()
        if not csv_data:
            return

        # Prepare formatting keys
        context = {
            "csv_data": csv_data,
            "current_date_time": now.strftime("%Y-%m-%d %H:%M:%S"),
            "last_data_time": self.timestamps[-1].strftime("%Y-%m-%d %H:%M:%S") if self.timestamps else "N/A"
        }

        prompt_file = "gemma_prompt.txt" if self.local_llm else "gemini_prompt.txt"
        prompt_path = os.path.join(script_dir, prompt_file)

        logging.info("Calling model to fetch grid summary...")
        response = ai.fetch_gemini_summary(
            prompt_template_path=prompt_path,
            context_data=context,
            local_llm=self.local_llm,
            ollama_model=os.environ.get("EDGE_MODEL", "gemma2-edge"),
            gcp_project_id=os.environ.get("GCP_PROJECT")
        )

        self.last_summary_time = now
        # Atomic write to cache JSON
        io.write_safe_json(self.summary_cache_file, {
            "timestamp": now.isoformat(),
            "summary": response,
            "dft_explanation": self.local_dft_text
        })

        self.ui_queue.put(lambda: self.update_background_summary(response))

    def rotate_slides(self) -> None:
        """Rotates active slide view periodically."""
        if self.current_slide == 1:
            self.current_slide = 2
            delay = config.SLIDE_2_DURATION_MS
        else:
            self.current_slide = 1
            delay = config.SLIDE_1_DURATION_MS
        
        self.update_slide_visibility()
        self.after(delay, self.rotate_slides)

    def update_slide_visibility(self) -> None:
        """Hides or reveals Axis elements."""
        if self.current_slide == 1:
            self.ax.set_visible(True)
            if hasattr(self, 'ax_bar') and self.ax_bar is not None:
                self.ax_bar.set_visible(True)
            self.ax_freq.set_visible(False)
        else:
            self.ax.set_visible(False)
            if hasattr(self, 'ax_bar') and self.ax_bar is not None:
                self.ax_bar.set_visible(False)
            self.ax_freq.set_visible(True)
            
        self.update_summary_display()
        self.solar_bars_dirty = True
        status_text = self.status_label.cget("text") if self.status_label is not None else ""
        status_fg = self.status_label.cget("fg") if self.status_label is not None else ""
        self.update_chart(status_text, status_fg)

    def update_weather_display(self) -> None:
        """Refreshes the weather display text label."""
        try:
            live_weather = weather.fetch_live_weather()
            temp = live_weather.get("temp")
            wcode = live_weather.get("weather_code")
            cloud_cover = live_weather.get("cloud_cover")
        except Exception as e:
            logging.error(f"Error fetching live weather in update_weather_display: {e}")
            temp, wcode, cloud_cover = None, None, None
        
        # Load from cache file if live endpoint failed
        if temp is None or wcode is None:
            cache = io.read_safe_json(self.summary_cache_file)
            metrics = cache.get("metrics", {})
            if temp is None:
                temp = metrics.get("temp_max")
            if cloud_cover is None:
                cloud_cover = metrics.get("cloud_cover")
            if wcode is None and cloud_cover is not None:
                cc = float(cloud_cover)
                wcode = 0 if cc < 10 else (1 if cc < 30 else (2 if cc < 60 else 3))
                
        temp_str = f"{temp:.1f}°C" if temp is not None else "N/A"
        
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
        else:
            sky_str = "N/A"
            
        if self.weather_label is not None:
            self.weather_label.config(text=f"{temp_str} | {sky_str}")

    def update_chart(self, label_text: str, color: str) -> None:
        """Draws current line coordinates and stacked bars on the canvas."""
        if self.status_label is not None:
            self.status_label.config(text=label_text, fg=color)
        t0 = time.perf_counter()

        if self.current_slide == 1:
            with self.data_lock:
                usage_copy = list(self.usage)
                timestamps_copy = list(self.timestamps)
                se_timestamps_copy = list(self.se_timestamps)
                se_power_copy = list(self.se_power)
                chilicon_timestamps_copy = list(self.chilicon_timestamps)
                chilicon_power_copy = list(self.chilicon_power)

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

            now = datetime.datetime.now()
            start_time = now - datetime.timedelta(hours=24)
            self.ax.set_xlim(start_time, now)

            if usage_copy:
                y_min = min(usage_copy)
                y_max = max(usage_copy)
                y_range = max(y_max - y_min, 1.0)
                self.ax.set_ylim(min(0.0, y_min - 0.15 * y_range), max(0.0, y_max + 0.85 * y_range))

            # Solar edge bar charts
            if not self.solar_off and hasattr(self, 'ax_bar'):
                if self.solar_bars_dirty:
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

                    while current_slot <= now:
                        bar_times.append(current_slot)
                        
                        # PV 1
                        se_val = 0.0
                        for ts, p in zip(se_timestamps_copy, se_power_copy):
                            if ts <= current_slot and current_slot - ts <= datetime.timedelta(minutes=30):
                                se_val = p
                        se_heights.append(se_val)
                        
                        # PV 2
                        ch_val = 0.0
                        if not self.chilicon_off:
                            for ts, p in zip(chilicon_timestamps_copy, chilicon_power_copy):
                                if ts <= current_slot and current_slot - ts <= datetime.timedelta(minutes=30):
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
                    self.solar_bars_dirty = False

            self.canvas.draw()
            logging.info(f"Canvas draw took {(time.perf_counter() - t0)*1000:.2f} ms (Slide 1)")

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

            freqs, grid_amp, solar_amp, expected_solar_amp, consumption_amp = self.align_and_compute_spectrum()

            if freqs:
                self.ax_freq.plot(freqs, grid_amp, color=config.IMPORT_COLOR, label='Grid Spectrum', linewidth=1.5)
                self.ax_freq.plot(freqs, solar_amp, color='#fbbf24', label='Solar Spectrum (Actual)', linewidth=1.5)
                self.ax_freq.plot(freqs, expected_solar_amp, color=config.EXPECTED_SOLAR_COLOR, linestyle='--', label='Expected Solar (Weather Modulated)', linewidth=1.3)
                self.ax_freq.plot(freqs, consumption_amp, color=config.CONSUMPTION_COLOR, label='Household Consumption (Load)', linewidth=1.5)
                self.ax_freq.axvline(1.0, color='deepskyblue', linestyle='--', alpha=0.5, label='24h Diurnal')
                self.ax_freq.axvline(2.0, color='violet', linestyle='--', alpha=0.5, label='12h Semi-Diurnal')
                self.ax_freq.set_xlim(0.1, 4.0)
                self.ax_freq.grid(color='gray', linestyle=':', alpha=0.3)
                
                # Fetch SNR dB values
                snr_metrics = spectral.calculate_snr_metrics(freqs, grid_amp, solar_amp, consumption_amp)
                grid_diurnal_snr = snr_metrics.get("grid_24h_snr_db", 0.0)
                solar_diurnal_snr = snr_metrics.get("solar_24h_snr_db", 0.0)
                consumption_diurnal_snr = snr_metrics.get("consumption_24h_snr_db", 0.0)
                
                # Render calculated SNR values in the legend
                self.ax_freq.legend(
                    [
                        f'Grid Spectrum (Diurnal SNR: {grid_diurnal_snr:.1f} dB)',
                        f'Solar Spectrum (Diurnal SNR: {solar_diurnal_snr:.1f} dB)',
                        'Expected Solar (Weather Modulated)',
                        f'Household Consumption (Diurnal SNR: {consumption_diurnal_snr:.1f} dB)',
                        '24h Diurnal',
                        '12h Semi-Diurnal'
                    ],
                    facecolor='black', edgecolor='white', labelcolor='white', fontsize=8
                )
                
                max_amp = max(max(grid_amp), max(solar_amp), max(expected_solar_amp), max(consumption_amp)) if grid_amp else 1.0
                self.ax_freq.set_ylim(0, max_amp * 1.85)

            # Recreate watermark
            self.summary_text_obj_freq = self.ax_freq.text(
                0.02, 0.95, self.wrap_text(self.local_dft_text),
                transform=self.ax_freq.transAxes, ha='left', va='top',
                fontsize=config.SUMMARY_FONT_SIZE, color=config.SUMMARY_COLOR, alpha=config.SUMMARY_ALPHA,
                fontfamily='monospace', weight='bold', zorder=10
            )

            self.canvas.draw()
            logging.info(f"Canvas draw took {(time.perf_counter() - t0)*1000:.2f} ms (Slide 2)")

    def start_fast_render_loop(self) -> None:
        """Periodic 2-second GUI repaint loop."""
        self.fast_render_loop()

    def fast_render_loop(self) -> None:
        """Performs time updates, weather display checks, and slide refreshes."""
        if not self.running:
            return
            
        try:
            now_dt = datetime.datetime.now()
            if self.time_label is not None:
                self.time_label.config(text=now_dt.strftime("%H:%M"))
            if self.date_label is not None:
                self.date_label.config(text=now_dt.strftime("%A, %b %d, %Y"))
            self.update_weather_display()

            if self.current_slide == 1:
                self.update_chart(self.latest_status_text, self.latest_status_color)
        except Exception as e:
            logging.error(f"Error in fast_render_loop: {e}")
            
        self.after(2000, self.fast_render_loop)

    def update_background_summary(self, text: str) -> None:
        """Schedules thread-safe update of summary text state variables."""
        marker = "[Live Local Delta (Jetson)"
        if marker in text:
            self.baseline_text = text.split(marker)[0].strip()
            self.local_delta_text = marker + text.split(marker)[1]
        else:
            self.baseline_text = text.strip()
            self.local_delta_text = ""
        self.update_summary_display()

    def update_summary_display(self) -> None:
        """Refreshes the watermark elements inside the subplots."""
        if self.current_slide == 1:
            full_text = self.baseline_text
            if self.local_delta_text:
                full_text += "\n\n" + self.local_delta_text
            if self.summary_text_obj is not None:
                self.summary_text_obj.set_text(self.wrap_text(full_text))
        else:
            if self.summary_text_obj_freq is not None:
                self.summary_text_obj_freq.set_text(self.wrap_text(self.local_dft_text))

    def wrap_text(self, text: str, width: int = 100) -> str:
        """Standard word wrapping formatting utility."""
        import textwrap
        lines = []
        for p in text.split('\n'):
            if p.startswith('-') or p.startswith('*') or p.startswith('['):
                wrapped = textwrap.fill(p, width=width, subsequent_indent='  ')
                lines.append(wrapped)
            else:
                lines.append(textwrap.fill(p, width=width))
        return '\n'.join(lines)

    def update_ui_text(self, text: str) -> None:
        """Safely updates status label text."""
        if self.status_label is not None:
            self.after(0, lambda: self.status_label.config(text=text))
    def local_delta_loop(self) -> None:
        """Runs the 5-minute sync loop, performing SCP and hitting the Jetson server."""
        # Initial sleep for 15 seconds to allow dashboard startup to settle
        time.sleep(15)
        
        logging.info("Starting dashboard local delta sync loop...")
        while self.running:
            try:
                # 1. Check if baseline summary cache file exists or use fallback
                ts_str = None
                clean_baseline = ""
                if os.path.exists(self.summary_cache_file):
                    try:
                        with open(self.summary_cache_file, 'r') as f:
                            cache_data = json.load(f)
                        ts_str = cache_data.get("timestamp")
                        baseline_text = cache_data.get("summary", "")
                        
                        clean_baseline = baseline_text
                        marker = "[Live Local Delta (Jetson)"
                        if marker in clean_baseline:
                            clean_baseline = clean_baseline.split(marker)[0].strip()
                    except Exception as err:
                        logging.error(f"Local Delta Loop: Error reading cache file: {err}")
                
                if not ts_str:
                    # Fallback to 24 hours ago if the cache file doesn't exist or is invalid yet
                    ts_str = (datetime.datetime.now() - datetime.timedelta(hours=24)).strftime("%Y-%m-%d %H:%M:%S")
                    logging.info(f"Local Delta Loop: Baseline cache not found/valid. Using 24h fallback timestamp: {ts_str}")

                # 3. Post request to Jetson server
                url = f"http://{self.jetson_host}:{self.jetson_port}/api/analyze"
                payload = {
                    "baseline_timestamp": ts_str,
                    "baseline_text": clean_baseline
                }
                req_data = json.dumps(payload).encode('utf-8')
                req = urllib.request.Request(
                    url,
                    data=req_data,
                    headers={'Content-Type': 'application/json'}
                )
                
                try:
                    logging.info(f"Local Delta Loop: Requesting analysis from Jetson server at {url}...")
                    with urllib.request.urlopen(req, timeout=120.0) as response:
                        res_body = response.read().decode('utf-8')
                        res_data = json.loads(res_body)
                        llm_response = res_data.get("response", "").strip()
                        dft_explanation = res_data.get("dft_explanation", "").strip()
                        
                        if llm_response:
                            checked_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                            delta_text = f"[Live Local Delta (Jetson) | Checked: {checked_time}]:\n{llm_response}"
                            
                            self.local_delta_text = delta_text
                            if dft_explanation:
                                self.local_dft_text = dft_explanation
                            self.ui_queue.put(self.update_summary_display)
                            logging.info("Local Delta Loop: Successfully queued GUI summary update.")
                        else:
                            logging.warning("Local Delta Loop: Received empty response from Jetson server.")
                except Exception as post_err:
                    logging.error(f"Local Delta Loop: HTTP analysis query failed: {post_err}")
            except Exception as loop_err:
                logging.error(f"Local Delta Loop: Unexpected error: {loop_err}")
                
            for _ in range(30):
                if not self.running:
                    break
                time.sleep(10)

    def destroy(self) -> None:
        """Clean teardown releasing locks, threads, and serial hooks."""
        logging.info("Shutting down GridDashboard...")
        self.running = False
        if hasattr(self, 'ser') and self.ser:
            try:
                if self.ser.is_open:
                    self.ser.close()
            except Exception as e:
                logging.error(f"Error closing serial port: {e}")
        super().destroy()

    def process_ui_queue(self) -> None:
        """Polls the thread-safe UI update queue and runs tasks on the main Tkinter thread."""
        try:
            while True:
                task = self.ui_queue.get_nowait()
                task()
        except queue.Empty:
            pass
        if self.running:
            self.after(100, self.process_ui_queue)

    def handle_signal(self, signum: int, frame: Any) -> None:
        """Interprets termination signals and triggers destruction."""
        self.after(0, self.shutdown_from_signal)

    def shutdown_from_signal(self) -> None:
        """Exits main event loops cleanly."""
        self.destroy()
        self.quit()

    def check_signals(self) -> None:
        """Returns control briefly to Python to capture external signals."""
        if self.running:
            self.after(200, self.check_signals)


if __name__ == "__main__":
    app = GridDashboard()
    app.mainloop()
