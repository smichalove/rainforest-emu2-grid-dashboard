import csv
import datetime
from collections import defaultdict
import http.cookiejar
import json
import logging
import math
import os
import re
import signal
import statistics
import sys
import textwrap
import threading
import time
from typing import Any, List, Optional, Dict, Tuple
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET

# Third-party libraries
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.collections import LineCollection
import matplotlib.dates as mdates
from matplotlib.figure import Figure
import serial
import serial.tools.list_ports
import tkinter as tk

# Setup logging to keep track of serial port communication and errors.
home_dir: str = os.path.expanduser('~')
logging.basicConfig(
    filename=os.path.join(home_dir, 'dashboard.log'),
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s'
)

# Try to import Google GenAI and HTTPX libraries. If not installed, log a warning
# but run GUI without Vertex AI summaries.
GENAI_AVAILABLE = False
try:
    from google import genai
    from google.genai import types
    import httpx
    GENAI_AVAILABLE = True
except ImportError:
    logging.warning(
        "google-genai or httpx package is not installed. Gemini/Vertex AI background summaries will be disabled."
    )

# Rainforest EMU-2 hardware communication settings
BAUD: int = 115200

# Gemini Summary Display Settings
SUMMARY_FONT_SIZE: int = 10
SUMMARY_ALPHA: float = 0.55
SUMMARY_COLOR: str = 'deepskyblue'

DEFAULT_LAT: str = os.environ.get("WEATHER_LAT", "47.5760")
DEFAULT_LON: str = os.environ.get("WEATHER_LON", "-122.0193")

DEFAULT_WEATHER_FALLBACK: Dict[str, float] = {
    "cloud_cover": 45.0,
    "sunrise_hour": 5.25,
    "sunset_hour": 21.25
}

# Color tokens for grid status and line plot
IMPORT_COLOR: str = '#f43f5e'  # Modern rose/crimson red
EXPORT_COLOR: str = '#00ff00'  # Classic neon green
EXPECTED_SOLAR_COLOR: str = '#ffff00' # Bright yellow for expected weather-modulated solar
CONSUMPTION_COLOR: str = '#d946ef'    # Neon purple/magenta for household consumption

class GridDashboard(tk.Tk):
    """A fullscreen Tkinter dashboard application that visualizes real-time power grid usage.

    This class handles the GUI window lifecycle, reads telemetry data from a serial 
    connection in a background thread, maintains a persistent CSV log of past usage,
    and displays a 24-hour Midnight-to-Midnight chart using matplotlib.
    
    Attributes:
        usage (List[float]): Historical and current demand measurements in kW.
        timestamps (List[datetime.datetime]): Timestamp of each demand measurement.
        max_points (int): Maximum number of data points to hold in memory (~24 hours of logs).
        history_file (str): Filesystem path to the persistent CSV history file.
        running (bool): Thread safety flag to control the background serial loop.
        thread (threading.Thread): Background thread handling serial port polling.
        status_label (tk.Label): GUI text label displaying current demand.
        fig (Figure): Matplotlib Figure for the grid graph.
        ax (Any): Matplotlib Axes representing the plot area.
        lc (LineCollection): Matplotlib LineCollection plot element.
        summary_text_obj (Any): Matplotlib Text object for displaying background summaries.
        canvas (FigureCanvasTkAgg): Canvas widget connecting matplotlib and Tkinter.
        solar_off (bool): If True, suppresses SolarEdge polling and plotting.
        chilicon_off (bool): If True, suppresses Chillicon polling and plotting.
        local_llm (bool): If True, uses local Ollama instead of Vertex AI.
        solaredge_api_key (Optional[str]): API key for SolarEdge.
        solaredge_site_id (Optional[str]): Site ID for SolarEdge.
        chilicon_username (Optional[str]): Username for Chillicon login.
        chilicon_password (Optional[str]): Password for Chillicon login.
        chilicon_installation_hash (Optional[str]): Installation hash for Chillicon API.
        summary_cache_file (str): File path for local summary cache.
        last_summary_time (Optional[datetime.datetime]): Timestamp of last successful summary query.
    """
    solar_off = False

    @property
    def data_lock(self) -> threading.Lock:
        """Get or initialize the data lock for thread-safe list operations."""
        if '_data_lock' not in self.__dict__:
            self.__dict__['_data_lock'] = threading.Lock()
        return self.__dict__['_data_lock']

    def __init__(self) -> None:
        """Initializes the GridDashboard window, plot, and background serial reader.

        Sets up the fullscreen GUI environment, binds exit shortcuts, loads historical
        data from CSV, generates the matplotlib chart interface, and spawns the serial
        port listener thread.
        """
        super().__init__()
        self.title("EMU-2 Grid Monitor")
        
        # Configure fullscreen mode to allow kiosk-like operation on Raspberry Pi.
        self.attributes("-fullscreen", True)
        self.configure(bg='black')
        
        # Press Escape or click anywhere to exit the kiosk dashboard (prevents lockouts during testing).
        self.bind("<Escape>", lambda e: self.destroy())
        self.bind("<Button-1>", lambda e: self.destroy())

        # In-memory arrays to hold data points for plotting.
        self.usage: List[float] = []
        self.timestamps: List[datetime.datetime] = []
        
        # Latest status text and color parsed from serial telemetry
        self.latest_status_text: str = "Waiting for data..."
        self.latest_status_color: str = "white"
        self.solar_bars_dirty: bool = True
        
        # Check command line flags
        self.solar_off: bool = "--solaroff" in sys.argv
        self.chilicon_off: bool = "--chiliconoff" in sys.argv
        self.local_llm: bool = "--localllm" in sys.argv
        
        # SolarEdge PV and Battery In-memory arrays and paths
        self.se_timestamps: List[datetime.datetime] = []
        self.se_power: List[float] = []
        self.se_battery_timestamps: List[datetime.datetime] = []
        self.se_battery_power: List[float] = []
        self.se_battery_soc: List[float] = []
        self.solaredge_api_key: Optional[str] = None
        self.solaredge_site_id: Optional[str] = None

        # Chillicon Solar In-memory arrays and parameters
        self.chilicon_timestamps: List[datetime.datetime] = []
        self.chilicon_power: List[float] = []
        self.chilicon_energy: List[float] = []
        self.chilicon_username: Optional[str] = None
        self.chilicon_password: Optional[str] = None
        self.chilicon_installation_hash: Optional[str] = None
        self.chilicon_opener: Optional[urllib.request.OpenerDirector] = None
        
        # 5760 points at ~15s intervals equals exactly 24 hours of data.
        self.max_points: int = 5760 
        # Resolve history file location, defaulting to local directory if present
        script_dir: str = os.path.dirname(os.path.abspath(__file__))
        local_history: str = os.path.join(script_dir, 'grid_history.csv')
        self.history_file: str = local_history if os.path.exists(local_history) else os.path.join(home_dir, 'grid_history.csv')
        
        local_se_history: str = os.path.join(script_dir, 'solaredge_history.csv')
        self.se_history_file: str = local_se_history if os.path.exists(local_se_history) else os.path.join(home_dir, 'solaredge_history.csv')
        
        local_se_battery_history: str = os.path.join(script_dir, 'solaredge_battery_history.csv')
        self.se_battery_history_file: str = local_se_battery_history if os.path.exists(local_se_battery_history) else os.path.join(home_dir, 'solaredge_battery_history.csv')

        local_chilicon_history: str = os.path.join(script_dir, 'chilicon_history.csv')
        self.chilicon_history_file: str = local_chilicon_history if os.path.exists(local_chilicon_history) or not os.path.exists(os.path.join(home_dir, 'chilicon_history.csv')) else os.path.join(home_dir, 'chilicon_history.csv')
        
        self.last_weather_fetch_time: Optional[datetime.datetime] = None
        self.cached_weather: Dict[str, Optional[float]] = {}
        
        self.load_credentials()
        
        # Reload historical data from CSV so the graph survives power interruptions.
        self.load_history()
        self.load_solaredge_history()
        self.load_chilicon_history()

        # Create a container frame for the two-column header layout
        self.header_frame: tk.Frame = tk.Frame(self, bg='black')
        self.header_frame.pack(fill=tk.X, padx=20, pady=10)

        # Left column (Time and Weather)
        self.left_header: tk.Frame = tk.Frame(self.header_frame, bg='black')
        self.left_header.pack(side=tk.LEFT, anchor='nw')

        self.time_label: tk.Label = tk.Label(
            self.left_header, text="00:00", font=('Helvetica', 32, 'bold'), bg='black', fg='deepskyblue', anchor='w'
        )
        self.time_label.pack(anchor='w', pady=(0, 2))

        self.date_label: tk.Label = tk.Label(
            self.left_header, text="", font=('Helvetica', 12, 'bold'), bg='black', fg='#a0aec0', anchor='w'
        )
        self.date_label.pack(anchor='w', pady=(0, 2))

        self.weather_label: tk.Label = tk.Label(
            self.left_header, text="Weather: N/A", font=('Helvetica', 14, 'bold'), bg='black', fg='#fbbf24', anchor='w'
        )
        self.weather_label.pack(anchor='w', pady=(0, 2))

        # Right column (SolarEdge and Chillicon + Grid status)
        self.right_header: tk.Frame = tk.Frame(self.header_frame, bg='black')
        self.right_header.pack(side=tk.RIGHT, anchor='ne')

        self.status_label: tk.Label = tk.Label(
            self.right_header, text="Waiting for data...", font=('Helvetica', 32, 'bold'), bg='black', fg='white', anchor='e'
        )
        self.status_label.pack(anchor='e', pady=(0, 2))

        self.sub_status_label: tk.Label = tk.Label(
            self.right_header, text="", font=('Helvetica', 16, 'bold'), bg='black', fg='#fbbf24', anchor='e'
        )
        if not self.solar_off:
            self.sub_status_label.pack(anchor='e', pady=(0, 2))
            latest_pv = self.se_power[-1] if self.se_power else 0.0
            self.sub_status_label.config(text=f"SolarEdge PV: {latest_pv:.3f} kW")

        self.chilicon_status_label: tk.Label = tk.Label(
            self.right_header, text="", font=('Helvetica', 16, 'bold'), bg='black', fg='#ffff00', anchor='e'
        )
        if not self.chilicon_off:
            self.chilicon_status_label.pack(anchor='e', pady=(0, 2))
            latest_ch = self.chilicon_power[-1] if self.chilicon_power else 0.0
            self.chilicon_status_label.config(text=f"Chillicon PV: {latest_ch:.3f} kW")

        # AI Summary text label below the header frame
        self.summary_label: tk.Label = tk.Label(
            self, text="Awaiting AI Analysis...", font=('Courier', 11, 'bold'),
            bg='black', fg=SUMMARY_COLOR, justify='left', anchor='nw',
            wraplength=1200
        )
        self.summary_label.pack(fill=tk.X, padx=20, pady=(5, 10))

        # Matplotlib figure setup.
        self.fig: Figure = Figure(figsize=(5, 3), dpi=100, facecolor='black')
        
        # We place both axes in the same rect so they overlap and swap visibility
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
        
        # Secondary axes for SolarEdge bar chart along the bottom of Slide 1
        if not self.solar_off:
            self.ax_bar = self.ax.twinx()
            self.ax_bar.set_ylim(0, 10)
            self.ax_bar.tick_params(colors='#fbbf24')
            self.ax_bar.yaxis.set_label_position('right')
            self.ax_bar.spines['right'].set_color('#fbbf24')
            self.ax_bar.spines['left'].set_color('none')
            self.ax_bar.spines['top'].set_color('none')
            self.ax_bar.spines['bottom'].set_color('none')
            self.ax_bar.set_ylabel('SolarEdge PV (kW)', color='#fbbf24', rotation=270, labelpad=15)
            
            self.ax.set_zorder(self.ax_bar.get_zorder() + 1)
            self.ax.patch.set_visible(False)
        
        # Dotted horizontal line at 0 kW
        self.ax.axhline(0, color='gray', linestyle='--') 
        
        # LineCollection for Slide 1
        self.lc: LineCollection = LineCollection([], linewidths=1.8, zorder=2)
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
        self.ax_freq.set_visible(False) # Invisible by default
        
        # State variables for Slide Rotation
        self.current_slide: int = 1
        self.local_time_text: str = "Awaiting AI Analysis..."
        self.local_dft_text: str = "Awaiting Frequency Domain Analysis..."
        
        # Fetch initial daily weather parameters (5 days forecast)
        self.weather_map: Dict[str, Dict[str, Any]] = self.fetch_historical_weather()
        
        # Schedule slide rotation loop (every 29 seconds)
        self.after(29000, self.rotate_slides)
        
        # Integrate Matplotlib canvas with the Tkinter window.
        self.canvas: FigureCanvasTkAgg = FigureCanvasTkAgg(self.fig, master=self)
        self.canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)

        # Summary cache settings to prevent redundant API queries on restart
        self.summary_cache_file: str = os.path.join(script_dir, 'gemini_summary.json')
        self.last_summary_time: Optional[datetime.datetime] = None
        
        # Resolve LLM integration mode: 'direct' (default) or 'decoupled' (cache consumer)
        self.llm_mode: str = os.environ.get("LLM_MODE", "direct").lower().strip()
        if self.local_llm:
            self.llm_mode = "direct"
        logging.info(f"Initialized LLM mode: '{self.llm_mode}' (local_llm={self.local_llm})")
        
        # Initialize text buffers for baseline and local delta rendering
        self.baseline_text: str = ""
        self.local_delta_text: str = ""
        
        # Load Jetson network configs
        self.jetson_host: str = os.environ.get("JETSON_HOST", "localhost")
        self.jetson_user: str = os.environ.get("JETSON_USER", "nvidia")
        self.jetson_backup_path: str = os.environ.get("JETSON_BACKUP_PATH", "~/rainforest-emu2-grid-dashboard/backups/")
        self.jetson_port: int = int(os.environ.get("JETSON_PORT", "5000"))
        
        # Load cached summary on startup
        self.load_cached_summary()

        # If historical data is loaded, draw the chart and status label immediately on startup.
        if self.usage:
            latest_val: float = self.usage[-1]
            status: str = "Combined Solar Export (PV)" if latest_val < 0 else "Importing (Grid)"
            color: str = EXPORT_COLOR if latest_val < 0 else IMPORT_COLOR
            text: str = f"{latest_val:.3f} kW | {status}"
            self.latest_status_text = text
            self.latest_status_color = color
            self.update_chart(text, color)

        # Initialize serial reference to None before thread runs.
        self.ser: Optional[serial.Serial] = None

        # Threading settings for serial interface monitoring.
        self.running: bool = True
        self.thread: threading.Thread = threading.Thread(target=self.read_serial, daemon=True)
        self.thread.start()

        # Start background thread to fetch Gemini grid summaries every 30 minutes.
        self.start_summary_loop()
        
        # Start background thread to poll SolarEdge every 15 minutes.
        self.start_solaredge_loop()

        # Start background thread to poll Chillicon every 10 minutes.
        self.start_chilicon_loop()

        # Start background thread for local delta tracking in decoupled mode
        if self.llm_mode == "decoupled":
            self.start_local_delta_loop()

        # Register OS signal handlers for clean teardown on termination signals (SIGINT, SIGTERM)
        signal.signal(signal.SIGINT, self.handle_signal)
        signal.signal(signal.SIGTERM, self.handle_signal)

        # Start periodic check of signals to ensure responsiveness in Tkinter mainloop
        self.check_signals()

        # Start the real-time 2-second GUI polling and rendering loop
        self.start_fast_render_loop()

    def hex_to_signed_int(self, hex_str: str, bits: int = 32) -> int:
        """Converts a hexadecimal string representation of a number into a signed integer.

        This is used to parse signed data outputs from the Rainforest EMU-2 hardware.

        Args:
            hex_str: The hexadecimal string to convert.
            bits: The bit-width of the target integer (defaults to 32).

        Returns:
            The decoded signed integer value.
        """
        val: int = int(hex_str, 16)
        # Perform 2's complement conversion if the sign bit is set.
        if (val & (1 << (bits - 1))) != 0:
            val = val - (1 << bits)
        return val

    def load_history(self) -> None:
        """Loads grid usage data from the CSV history file.

        Reads values that are less than 24 hours old from the persistent file 
        specified by `self.history_file`. This populates the chart upon startup 
        so data survives power losses.
        """
        if not os.path.exists(self.history_file):
            return
            
        logging.info("Loading history from CSV...")
        now: datetime.datetime = datetime.datetime.now()
        # Only load the last 24 hours to prevent chart congestion and excessive memory usage.
        cutoff: datetime.datetime = now - datetime.timedelta(days=1)
        try:
            with open(self.history_file, 'r') as f:
                reader = csv.reader(line.replace('\x00', '') for line in f)
                for row in reader:
                    if len(row) == 2:
                        try:
                            # Strip out any null bytes that can occur during abrupt power cuts.
                            ts_str = row[0].replace('\x00', '').strip()
                            val_str = row[1].replace('\x00', '').strip()
                            if not ts_str or not val_str:
                                continue
                            ts: datetime.datetime = datetime.datetime.fromisoformat(ts_str)
                            if ts > cutoff:
                                with self.data_lock:
                                    self.timestamps.append(ts)
                                    self.usage.append(float(val_str))
                        except Exception as parse_err:
                            logging.warning(f"Skipping corrupted history row: {row} - Error: {parse_err}")
            logging.info(f"Loaded {len(self.usage)} historical points.")
        except Exception as e:
            logging.error(f"Failed to read history file: {e}")

    def load_credentials(self) -> None:
        """Loads credentials and settings from environment or local Auth files."""
        # Check for local .env file in the script directory and load environment variables
        script_dir = os.path.dirname(os.path.abspath(__file__))
        env_path = os.path.join(script_dir, ".env")
        if os.path.exists(env_path):
            try:
                with open(env_path, 'r') as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith("#") and "=" in line:
                            k, v = line.split("=", 1)
                            k = k.strip()
                            v = v.strip().strip('"').strip("'")
                            os.environ[k] = v
                logging.info("Loaded environment variables from local .env file.")
            except Exception as env_err:
                logging.warning(f"Could not parse local .env file: {env_err}")

        self.solaredge_api_key = os.environ.get("SOLAREDGE_API_KEY")
        self.solaredge_site_id = os.environ.get("SOLAREDGE_SITE_ID")
        self.chilicon_username = os.environ.get("CHILICON_USERNAME")
        self.chilicon_password = os.environ.get("CHILICON_PASSWORD")
        self.chilicon_installation_hash = os.environ.get("CHILICON_INSTALLATION_HASH")
        
        script_dir = os.path.dirname(os.path.abspath(__file__))
        possible_paths = [
            os.path.join(script_dir, "Auth/solaredge_config.json"),
            os.path.join(script_dir, "auth/solaredge_config.json"),
            os.path.join(home_dir, "Auth/solaredge_config.json"),
            os.path.join(home_dir, "auth/solaredge_config.json")
        ]
        
        for path in possible_paths:
            if os.path.exists(path):
                try:
                    with open(path, 'r') as f:
                        data = json.load(f)
                        if not self.solaredge_api_key:
                            self.solaredge_api_key = data.get("api_key")
                        if not self.solaredge_site_id:
                            self.solaredge_site_id = data.get("site_id")
                        logging.info(f"Loaded SolarEdge credentials from: {path}")
                        break
                except Exception as e:
                    logging.warning(f"Could not parse credentials file {path}: {e}")

        # Load Chillicon credentials
        possible_chilicon_paths = [
            os.path.join(script_dir, "Auth/chilicon_config.json"),
            os.path.join(script_dir, "auth/chilicon_config.json"),
            os.path.join(home_dir, "Auth/chilicon_config.json"),
            os.path.join(home_dir, "auth/chilicon_config.json")
        ]
        for path in possible_chilicon_paths:
            if os.path.exists(path):
                try:
                    with open(path, 'r') as f:
                        data = json.load(f)
                        if not self.chilicon_username:
                            self.chilicon_username = data.get("username")
                        if not self.chilicon_password:
                            self.chilicon_password = data.get("password")
                        if not self.chilicon_installation_hash:
                            self.chilicon_installation_hash = data.get("installation_hash")
                        logging.info(f"Loaded Chillicon credentials from: {path}")
                        break
                except Exception as e:
                    logging.warning(f"Could not parse Chillicon credentials file {path}: {e}")

    def load_solaredge_history(self) -> None:
        """Loads SolarEdge PV and battery history from CSV."""
        if self.solar_off:
            return
            
        now: datetime.datetime = datetime.datetime.now()
        cutoff: datetime.datetime = now - datetime.timedelta(days=1)
        
        if os.path.exists(self.se_history_file):
            logging.info("Loading SolarEdge PV history from CSV...")
            try:
                with open(self.se_history_file, 'r') as f:
                    reader = csv.reader(line.replace('\x00', '') for line in f)
                    for row in reader:
                        if len(row) == 2:
                            try:
                                ts_str = row[0].replace('\x00', '').strip()
                                val_str = row[1].replace('\x00', '').strip()
                                if not ts_str or not val_str:
                                    continue
                                ts = datetime.datetime.fromisoformat(ts_str)
                                if ts > cutoff:
                                    self.se_timestamps.append(ts)
                                    self.se_power.append(float(val_str))
                            except Exception as parse_err:
                                logging.warning(f"Skipping corrupted SolarEdge PV row: {row} - Error: {parse_err}")
                logging.info(f"Loaded {len(self.se_power)} SolarEdge PV historical points.")
            except Exception as e:
                logging.error(f"Failed to read SolarEdge PV history file: {e}")

        if os.path.exists(self.se_battery_history_file):
            logging.info("Loading SolarEdge battery history from CSV...")
            try:
                with open(self.se_battery_history_file, 'r') as f:
                    reader = csv.reader(line.replace('\x00', '') for line in f)
                    for row in reader:
                        if len(row) == 3:
                            try:
                                ts_str = row[0].replace('\x00', '').strip()
                                p_str = row[1].replace('\x00', '').strip()
                                soc_str = row[2].replace('\x00', '').strip()
                                if not ts_str or not p_str or not soc_str:
                                    continue
                                ts = datetime.datetime.fromisoformat(ts_str)
                                if ts > cutoff:
                                    self.se_battery_timestamps.append(ts)
                                    self.se_battery_power.append(float(p_str))
                                    self.se_battery_soc.append(float(soc_str))
                            except Exception as parse_err:
                                logging.warning(f"Skipping corrupted SolarEdge battery row: {row} - Error: {parse_err}")
                logging.info(f"Loaded {len(self.se_battery_power)} SolarEdge battery historical points.")
            except Exception as e:
                logging.error(f"Failed to read SolarEdge battery history file: {e}")

    def load_chilicon_history(self) -> None:
        """Loads Chillicon PV and energy history from CSV."""
        if self.chilicon_off:
            return
            
        now: datetime.datetime = datetime.datetime.now()
        cutoff: datetime.datetime = now - datetime.timedelta(days=1)
        
        if os.path.exists(self.chilicon_history_file):
            logging.info("Loading Chillicon history from CSV...")
            try:
                with open(self.chilicon_history_file, 'r') as f:
                    reader = csv.reader(line.replace('\x00', '') for line in f)
                    for row in reader:
                        if len(row) == 3:
                            try:
                                ts_str = row[0].replace('\x00', '').strip()
                                p_str = row[1].replace('\x00', '').strip()
                                e_str = row[2].replace('\x00', '').strip()
                                if not ts_str or not p_str or not e_str:
                                    continue
                                ts = datetime.datetime.fromisoformat(ts_str)
                                if ts > cutoff:
                                    self.chilicon_timestamps.append(ts)
                                    self.chilicon_power.append(float(p_str))
                                    self.chilicon_energy.append(float(e_str))
                            except Exception as parse_err:
                                logging.warning(f"Skipping corrupted Chillicon row: {row} - Error: {parse_err}")
                logging.info(f"Loaded {len(self.chilicon_power)} Chillicon historical points.")
            except Exception as e:
                logging.error(f"Failed to read Chillicon history file: {e}")

    def chilicon_login(self) -> bool:
        """Logs into Chilicon Cloud and stores session cookies.

        Returns:
            True if the login succeeded and cookies were stored, False otherwise.
        """
        if not self.chilicon_username or not self.chilicon_password:
            logging.error("Chillicon credentials not set. Cannot log in.")
            return False
            
        login_url = "https://cloud.chiliconpower.com/login"
        try:
            logging.info("Fetching Chillicon login page for CSRF token...")
            req = urllib.request.Request(login_url, headers={'User-Agent': 'Mozilla/5.0'})
            with self.chilicon_opener.open(req, timeout=15) as r:
                html = r.read().decode('utf-8')
                csrf_match = re.search(r'name=["\']csrfmiddlewaretoken["\']\s+value=["\']([^"\']+)["\']', html)
                csrf_token = csrf_match.group(1) if csrf_match else None
                
            login_payload = {
                'username': self.chilicon_username,
                'password': self.chilicon_password
            }
            if csrf_token:
                login_payload['csrfmiddlewaretoken'] = csrf_token
                
            data = urllib.parse.urlencode(login_payload).encode('utf-8')
            req = urllib.request.Request(
                login_url,
                data=data,
                headers={
                    'User-Agent': 'Mozilla/5.0',
                    'Referer': login_url,
                    'Content-Type': 'application/x-www-form-urlencoded'
                }
            )
            with self.chilicon_opener.open(req, timeout=15) as r:
                res_url = r.geturl()
                logging.info(f"Chillicon login response URL: {res_url}")
                return True
        except Exception as e:
            logging.error(f"Error logging into Chillicon: {e}")
            return False

    def fetch_chilicon_data(self) -> None:
        """Polls Chillicon API and logs to history."""
        if self.chilicon_off:
            return
        if not self.chilicon_username or not self.chilicon_password or not self.chilicon_installation_hash:
            logging.info("Chillicon credentials/installation hash not set. Skipping poll.")
            return

        if self.chilicon_opener is None:
            cj = http.cookiejar.CookieJar()
            self.chilicon_opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
            if not self.chilicon_login():
                return

        today_str = datetime.date.today().isoformat()
        owner_update_url = f"https://cloud.chiliconpower.com/ajax/fetchOwnerUpdate?today={today_str}"
        
        req = urllib.request.Request(
            owner_update_url,
            headers={
                'User-Agent': 'Mozilla/5.0',
                'Referer': f"https://cloud.chiliconpower.com/installation/{self.chilicon_installation_hash}",
                'X-Requested-With': 'XMLHttpRequest'
            }
        )
        
        try:
            logging.info("Polling Chillicon API fetchOwnerUpdate...")
            with self.chilicon_opener.open(req, timeout=15) as response:
                res = response.read().decode('utf-8')
                try:
                    parsed = json.loads(res)
                except Exception:
                    logging.info("Chillicon session might have expired or response invalid. Re-authenticating...")
                    if self.chilicon_login():
                        with self.chilicon_opener.open(req, timeout=15) as retry_response:
                            res = retry_response.read().decode('utf-8')
                            parsed = json.loads(res)
                    else:
                        raise ValueError("Failed to re-authenticate with Chillicon")
                        
                if len(parsed) >= 3:
                    energy_wh = float(parsed[1])
                    power_kw = float(parsed[2])
                    now = datetime.datetime.now()
                    
                    logging.info(f"Chillicon current power: {power_kw:.3f} kW, Daily Energy: {energy_wh:.1f} Wh")
                    
                    with self.data_lock:
                        self.chilicon_timestamps.append(now)
                        self.chilicon_power.append(power_kw)
                        self.chilicon_energy.append(energy_wh)
                        
                        cutoff = now - datetime.timedelta(days=1)
                        while self.chilicon_timestamps and self.chilicon_timestamps[0] < cutoff:
                            self.chilicon_timestamps.pop(0)
                            self.chilicon_power.pop(0)
                            self.chilicon_energy.pop(0)
                        
                    try:
                        with open(self.chilicon_history_file, 'a') as f:
                            writer = csv.writer(f)
                            writer.writerow([now.isoformat(), f"{power_kw:.3f}", f"{energy_wh:.1f}"])
                    except Exception as file_err:
                        logging.error(f"Failed to write Chillicon history: {file_err}")
                    
                    self.solar_bars_dirty = True
                    self.after(0, lambda: self.chilicon_status_label.config(text=f"Chillicon PV: {power_kw:.3f} kW"))
                    self.after(0, lambda: self.update_chart(self.status_label.cget("text"), self.status_label.cget("fg")))
                else:
                    logging.warning(f"Unexpected Chillicon API response format: {parsed}")
        except Exception as e:
            logging.error(f"Error polling Chillicon API: {e}")

    def start_chilicon_loop(self) -> None:
        """Spawns the background thread to poll Chillicon every 15 minutes."""
        if self.chilicon_off:
            return
        self.chilicon_thread: threading.Thread = threading.Thread(target=self.chilicon_loop, daemon=True)
        self.chilicon_thread.start()

    def chilicon_loop(self) -> None:
        """Background loop to fetch Chillicon power data every 15 minutes."""
        self.fetch_chilicon_data()
        while self.running:
            for _ in range(90):
                if not self.running:
                    break
                time.sleep(10)
            if self.running:
                self.fetch_chilicon_data()

    def fetch_solaredge_data(self) -> None:
        """Polls SolarEdge API and logs to history."""
        if not self.solaredge_api_key or not self.solaredge_site_id:
            logging.info("SolarEdge credentials not set. Skipping poll.")
            return

        now = datetime.datetime.now()
        hour = now.hour + now.minute / 60.0
        
        # Smart Sunrise/Sunset Polling check
        # Skip polling outside potential daylight hours (5:00 AM to 9:30 PM) to conserve calls
        if hour < 5.0 or hour > 21.5:
            logging.info("Outside of daytime window. Skipping SolarEdge poll.")
            return

        url = f"https://monitoringapi.solaredge.com/site/{self.solaredge_site_id}/currentPowerFlow?api_key={self.solaredge_api_key}&format=json"
        try:
            logging.info("Polling SolarEdge API currentPowerFlow...")
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=10) as response:
                data = json.loads(response.read().decode('utf-8'))
                flow = data.get("siteCurrentPowerFlow", {})
                
                # PV Solar Power
                pv = flow.get("pv") or flow.get("PV") or {}
                power_kw = pv.get("currentPower", 0.0)
                
                logging.info(f"SolarEdge PV current power: {power_kw:.3f} kW")
                
                with self.data_lock:
                    self.se_timestamps.append(now)
                    self.se_power.append(power_kw)
                    if len(self.se_power) > self.max_points:
                        self.se_power.pop(0)
                        self.se_timestamps.pop(0)
                
                try:
                    with open(self.se_history_file, 'a') as f:
                        writer = csv.writer(f)
                        writer.writerow([now.isoformat(), f"{power_kw:.3f}"])
                except Exception as file_err:
                    logging.error(f"Failed to write SolarEdge PV history: {file_err}")
                
                # Storage (Battery) Power & SoC
                storage = flow.get("storage") or flow.get("STORAGE") or {}
                raw_battery_kw = storage.get("currentPower", 0.0)
                battery_soc = storage.get("chargeLevel", 0.0)
                status = storage.get("status", "Idle")
                
                # Sign battery power: positive for discharging, negative for charging
                if status == "Charging":
                    battery_kw = -raw_battery_kw
                elif status == "Discharging":
                    battery_kw = raw_battery_kw
                else:
                    battery_kw = 0.0
                    
                logging.info(f"SolarEdge Storage status: {status}, raw power: {raw_battery_kw:.3f} kW (signed: {battery_kw:.3f} kW), SoC: {battery_soc:.1f}%")
                
                with self.data_lock:
                    self.se_battery_timestamps.append(now)
                    self.se_battery_power.append(battery_kw)
                    self.se_battery_soc.append(battery_soc)
                    
                    if len(self.se_battery_power) > self.max_points:
                        self.se_battery_power.pop(0)
                        self.se_battery_timestamps.pop(0)
                        self.se_battery_soc.pop(0)
                    
                try:
                    with open(self.se_battery_history_file, 'a') as f:
                        writer = csv.writer(f)
                        writer.writerow([now.isoformat(), f"{battery_kw:.3f}", f"{battery_soc:.1f}"])
                except Exception as file_err:
                    logging.error(f"Failed to write SolarEdge battery history: {file_err}")
                
                # Redraw is handled dynamically when update_chart runs, or we trigger it explicitly
                self.solar_bars_dirty = True
                self.after(0, lambda: self.sub_status_label.config(text=f"SolarEdge PV: {power_kw:.3f} kW"))
                self.after(0, lambda: self.update_chart(self.status_label.cget("text"), self.status_label.cget("fg")))
                
        except Exception as e:
            logging.error(f"Error polling SolarEdge API currentPowerFlow: {e}")

    def start_solaredge_loop(self) -> None:
        """Spawns the background thread to poll SolarEdge every 15 minutes."""
        if self.solar_off:
            return
        self.solaredge_thread: threading.Thread = threading.Thread(target=self.solaredge_loop, daemon=True)
        self.solaredge_thread.start()

    def solaredge_loop(self) -> None:
        """Background loop to fetch SolarEdge power data every 15 minutes."""
        self.fetch_solaredge_data()
        while self.running:
            # Sleep for 15 minutes (900 seconds), checking self.running every 10 seconds.
            for _ in range(90):
                if not self.running:
                    break
                time.sleep(10)
            if self.running:
                self.fetch_solaredge_data()

    def find_emu2_port(self) -> str:
        """Dynamically searches for the EMU-2 serial port.
        
        Scans all available COM/TTY ports and returns the first one that appears
        to be a USB CDC device (like ttyACM) or has Rainforest in the manufacturer name.

        Returns:
            The device path of the serial port (e.g., '/dev/ttyACM0').
        """
        ports = serial.tools.list_ports.comports()
        for p in ports:
            # Rainforest meters typically enumerate as USB CDC devices (ttyACM)
            if 'ACM' in p.device or 'Rainforest' in str(p.manufacturer):
                return p.device
        return '/dev/ttyACM0'  # Fallback

    def read_serial(self) -> None:
        """Performs long-polling of the EMU-2 USB serial port in a background thread.

        Attempts to open the serial port and read incoming data. Features a 5-second
        exponential-style reconnection loop to recover gracefully from USB disconnects
        or device reboots.
        """
        logging.info("Starting background thread to read serial port.")
        buffer: str = ""
        
        while self.running:
            port_to_use = self.find_emu2_port()
            try:
                self.ser = serial.Serial(port_to_use, BAUD, timeout=1)
                logging.info(f"Successfully opened {port_to_use} at {BAUD} baud.")
            except Exception as e:
                err_msg: str = f"Failed to open port {port_to_use}: {e}. Retrying in 5s..."
                logging.error(err_msg)
                self.update_ui_text("Hardware disconnected.\nRetrying...")
                time.sleep(5)
                continue

            try:
                while self.running and self.ser.is_open:
                    # Read waiting data or block for 1 byte if empty.
                    data: bytes = self.ser.read(self.ser.in_waiting or 1)
                    if data:
                        buffer += data.decode('utf-8', errors='ignore')
                        
                        # Search and extract full XML chunks for parsing.
                        while '<InstantaneousDemand>' in buffer and '</InstantaneousDemand>' in buffer:
                            start: int = buffer.find('<InstantaneousDemand>')
                            end: int = buffer.find('</InstantaneousDemand>') + len('</InstantaneousDemand>')
                            
                            chunk: str = buffer[start:end]
                            self.process_chunk(chunk)
                            # Remove the processed chunk from the buffer.
                            buffer = buffer[end:]
                    time.sleep(0.1)
            except serial.SerialException as e:
                if self.running:
                    logging.error(f"Serial connection lost: {e}. Reconnecting in 5 seconds...")
                time.sleep(5)
            except Exception as e:
                if self.running:
                    logging.error(f"Unexpected error reading serial data: {e}")
                time.sleep(5)
            finally:
                if self.ser and self.ser.is_open:
                    self.ser.close()

    def process_chunk(self, xml_data: str) -> None:
        """Parses a single XML block containing grid demand telemetry.

        Extracts the demand, multiplier, and divisor tags from the InstantaneousDemand 
        schema. Computes the real-time kilowatt (kW) usage, updates the in-memory arrays,
        logs the data to the CSV file, and schedules a thread-safe UI update.

        Args:
            xml_data: The XML string payload to parse.
        """
        try:
            root: ET.Element = ET.fromstring(xml_data)
            if root.tag == 'InstantaneousDemand':
                # Demand, Multiplier, and Divisor values are provided in hex format by the hardware.
                demand_elem = root.find('Demand')
                multiplier_elem = root.find('Multiplier')
                divisor_elem = root.find('Divisor')

                demand_text: Optional[str] = demand_elem.text if demand_elem is not None else None
                multiplier_text: Optional[str] = multiplier_elem.text if multiplier_elem is not None else None
                divisor_text: Optional[str] = divisor_elem.text if divisor_elem is not None else None

                if not demand_text or not multiplier_text or not divisor_text:
                    logging.warning("Missing vital XML tags in InstantaneousDemand payload.")
                    return

                demand: int = self.hex_to_signed_int(demand_text)
                multiplier: int = int(multiplier_text, 16)
                divisor: int = int(divisor_text, 16)
                
                if divisor == 0:
                    logging.warning("Received Divisor of 0, skipping calculation.")
                    return
                # Calculate real-world kilowatt (kW) usage.
                actual_kw: float = (demand * multiplier) / divisor
                logging.info(f"Parsed Demand: {actual_kw:.3f} kW")
                
                # Append the new reading to memory arrays.
                now_ts: datetime.datetime = datetime.datetime.now()
                with self.data_lock:
                    self.usage.append(actual_kw)
                    self.timestamps.append(now_ts)
                    
                    # Ensure the arrays do not grow indefinitely and cause OOM.
                    if len(self.usage) > self.max_points:
                        self.usage.pop(0)
                        self.timestamps.pop(0)
                    
                # Append the telemetry point to the local CSV log.
                try:
                    with open(self.history_file, 'a') as f:
                        writer = csv.writer(f)
                        writer.writerow([now_ts.isoformat(), f"{actual_kw:.3f}"])
                except Exception:
                    pass
                
                # Format current status. Green indicates solar export, red indicates grid import.
                status: str = "Combined Solar Export (PV)" if actual_kw < 0 else "Importing (Grid)"
                color: str = EXPORT_COLOR if actual_kw < 0 else IMPORT_COLOR
                text: str = f"{actual_kw:.3f} kW | {status}"
                
                # Save status text and color as state variables.
                self.latest_status_text = text
                self.latest_status_color = color
                
                # Safely execute status label modifications immediately on the main thread using after().
                self.after(0, lambda: self.status_label.config(text=text, fg=color))
        except ET.ParseError as e:
            logging.warning(f"Fragmented XML dropped: {e}")
            return
        except Exception as e:
            logging.error(f"Error parsing XML chunk: {e}")

    def update_ui_text(self, text: str) -> None:
        """Thread-safely updates the text of the status label widget.

        Args:
            text: The message string to display.
        """
        self.after(0, lambda: self.status_label.config(text=text))

    def fetch_live_weather(self, lat: str = DEFAULT_LAT, lon: str = DEFAULT_LON) -> Dict[str, Optional[float]]:
        """Fetches the live weather from Open-Meteo API, cached for 15 minutes.

        Args:
            lat: Latitude of target location.
            lon: Longitude of target location.

        Returns:
            A dictionary containing:
            - "temp": float or None
            - "weather_code": float or None
            - "cloud_cover": float or None

        Raises:
            None: All exceptions (e.g. urllib.error.URLError) are caught internally.
        """
        now = datetime.datetime.now()
        if (hasattr(self, 'last_weather_fetch_time') and 
            self.last_weather_fetch_time is not None and 
            hasattr(self, 'cached_weather') and 
            self.cached_weather and 
            (now - self.last_weather_fetch_time).total_seconds() < 900):
            return self.cached_weather

        url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&current=temperature_2m,weather_code,cloud_cover&timezone=auto"
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=5) as response:
                res = json.loads(response.read().decode('utf-8'))
                current = res.get("current", {})
                data = {
                    "temp": current.get("temperature_2m"),
                    "weather_code": current.get("weather_code"),
                    "cloud_cover": current.get("cloud_cover")
                }
                self.cached_weather = data
                self.last_weather_fetch_time = now
                return data
        except Exception as e:
            logging.error(f"Error fetching live weather: {e}")
            if hasattr(self, 'cached_weather') and self.cached_weather:
                return self.cached_weather
            return {}

    def fetch_historical_weather(self, lat: str = DEFAULT_LAT, lon: str = DEFAULT_LON) -> Dict[str, Dict[str, Any]]:
        """Fetches daily average cloud cover, sunrise, and sunset times from Open-Meteo API.

        Args:
            lat: Latitude of target location.
            lon: Longitude of target location.

        Returns:
            A dictionary mapping date string "YYYY-MM-DD" to weather parameters.

        Raises:
            None: All exceptions are caught internally and logged.
        """
        url: str = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&past_days=5&daily=cloud_cover_mean,sunrise,sunset&timezone=auto"
        try:
            req: urllib.request.Request = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=10) as response:
                res: Dict[str, Any] = json.loads(response.read().decode('utf-8'))
                daily: Dict[str, Any] = res.get("daily", {})
                times: List[str] = daily.get("time", [])
                cloud_covers: List[Optional[float]] = daily.get("cloud_cover_mean", [])
                sunrises: List[str] = daily.get("sunrise", [])
                sunsets: List[str] = daily.get("sunset", [])
                
                weather_data: Dict[str, Dict[str, Any]] = {}
                for i, t_str in enumerate(times):
                    sr_hour: float = 5.25
                    ss_hour: float = 21.25
                    if i < len(sunrises) and sunrises[i]:
                        try:
                            sr_dt: datetime.datetime = datetime.datetime.fromisoformat(sunrises[i])
                            sr_hour = sr_dt.hour + sr_dt.minute / 60.0
                        except Exception:
                            pass
                    if i < len(sunsets) and sunsets[i]:
                        try:
                            ss_dt: datetime.datetime = datetime.datetime.fromisoformat(sunsets[i])
                            ss_hour = ss_dt.hour + ss_dt.minute / 60.0
                        except Exception:
                            pass
                    cc: float = cloud_covers[i] if (i < len(cloud_covers) and cloud_covers[i] is not None) else 45.0
                    
                    weather_data[t_str] = {
                        "cloud_cover": cc,
                        "sunrise_hour": sr_hour,
                        "sunset_hour": ss_hour
                    }
                return weather_data
        except Exception as e:
            logging.error(f"Error fetching historical weather in main dashboard: {e}")
            return {}

    def _local_interpolate_gaps(self, series: List[Optional[float]]) -> List[float]:
        """Fills missing elements (None) in a list using linear interpolation.

        Args:
            series: A list of floats that may contain None elements.

        Returns:
            A list of floats with all None elements replaced by interpolated values.

        Raises:
            None.
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

    def align_and_compute_spectrum(self) -> Tuple[List[float], List[float], List[float], List[float], List[float]]:
        """Aligns historical telemetry on a uniform hourly grid and computes the DTFT spectrum.

        Returns:
            A tuple of five lists:
            - freqs: frequencies in cycles per day
            - grid_amp: spectral amplitude of grid usage (kW)
            - solar_amp: spectral amplitude of total solar generation (kW)
            - expected_solar_amp: spectral amplitude of expected solar generation (kW)
            - consumption_amp: spectral amplitude of household consumption (kW)

        Raises:
            None.
        """
        with self.data_lock:
            timestamps_copy = list(self.timestamps)
            usage_copy = list(self.usage)
            se_timestamps_copy = list(self.se_timestamps)
            se_power_copy = list(self.se_power)
            chilicon_timestamps_copy = list(self.chilicon_timestamps)
            chilicon_power_copy = list(self.chilicon_power)

        if not timestamps_copy:
            return [], [], [], [], []
            
        min_ts: datetime.datetime = min(self.timestamps).replace(minute=0, second=0, microsecond=0)
        max_ts: datetime.datetime = max(self.timestamps).replace(minute=0, second=0, microsecond=0)
        total_hours: int = int((max_ts - min_ts).total_seconds() / 3600.0) + 1
        
        target_dts: List[datetime.datetime] = [min_ts + datetime.timedelta(hours=i) for i in range(total_hours)]
        
        # Build raw series with gaps
        grid_map: Dict[str, List[float]] = defaultdict(list)
        for ts, val in zip(timestamps_copy, usage_copy):
            grid_map[ts.strftime("%Y-%m-%d %H:00")].append(val)
            
        # SolarEdge
        se_map: Dict[str, List[float]] = defaultdict(list)
        for ts, val in zip(se_timestamps_copy, se_power_copy):
            se_map[ts.strftime("%Y-%m-%d %H:00")].append(val)
            
        # Chillicon
        ch_map: Dict[str, List[float]] = defaultdict(list)
        for ts, val in zip(chilicon_timestamps_copy, chilicon_power_copy):
            ch_map[ts.strftime("%Y-%m-%d %H:00")].append(val)
            
        grid_raw: List[Optional[float]] = []
        solar_raw: List[Optional[float]] = []
        expected_solar_series: List[float] = []
        
        PEAK_SOLAR_CAPACITY: float = 5.0
        
        for dt in target_dts:
            key: str = dt.strftime("%Y-%m-%d %H:00")
            g_vals: List[float] = grid_map[key]
            grid_raw.append(sum(g_vals) / len(g_vals) if g_vals else None)
            
            s_val: float = 0.0
            se_vals: List[float] = se_map[key]
            if se_vals:
                s_val += sum(se_vals) / len(se_vals)
            if not self.chilicon_off:
                ch_vals: List[float] = ch_map[key]
                if ch_vals:
                    s_val += sum(ch_vals) / len(ch_vals)
            
            # If no data is available for both, mark as None to interpolate
            if not se_vals and (self.chilicon_off or not ch_map[key]):
                solar_raw.append(None)
            else:
                solar_raw.append(s_val)
                
            # Model expected solar profile
            date_key: str = dt.strftime("%Y-%m-%d")
            day_weather: Dict[str, float] = self.weather_map.get(date_key, DEFAULT_WEATHER_FALLBACK)
            cloud_cover: float = day_weather["cloud_cover"]
            sr_hour: float = day_weather["sunrise_hour"]
            ss_hour: float = day_weather["sunset_hour"]
            
            # Decimal hour of day
            h: float = dt.hour + dt.minute / 60.0
            if sr_hour < h < ss_hour:
                clear_sky: float = PEAK_SOLAR_CAPACITY * math.sin(math.pi * (h - sr_hour) / (ss_hour - sr_hour))
            else:
                clear_sky = 0.0
                
            modulation: float = (100.0 - cloud_cover) / 100.0
            expected_solar_series.append(clear_sky * modulation)
                
        grid_series: List[float] = self._local_interpolate_gaps(grid_raw)
        solar_series: List[float] = self._local_interpolate_gaps(solar_raw)
        
        # Calculate household consumption (Load = Grid + Solar)
        consumption_series: List[float] = [g + s for g, s in zip(grid_series, solar_series)]
        
        # Run DTFT spectrum analysis for frequencies 0.1 to 4.0 cycles per day
        freqs: List[float] = [0.05 + 0.01 * i for i in range(400)]
        
        # Compute DTFT
        grid_amp: List[float] = []
        solar_amp: List[float] = []
        expected_solar_amp: List[float] = []
        consumption_amp: List[float] = []
        
        n_samples: int = len(grid_series)
        if n_samples > 0:
            for f in freqs:
                omega: float = (2.0 * math.pi * f) / 24.0
                
                # Grid
                re_g: float = 0.0
                im_g: float = 0.0
                for n in range(n_samples):
                    re_g += grid_series[n] * math.cos(omega * n)
                    im_g += -grid_series[n] * math.sin(omega * n)
                grid_amp.append(2.0 * math.sqrt(re_g**2 + im_g**2) / n_samples)
                
                # Solar
                re_s: float = 0.0
                im_s: float = 0.0
                for n in range(n_samples):
                    re_s += solar_series[n] * math.cos(omega * n)
                    im_s += -solar_series[n] * math.sin(omega * n)
                solar_amp.append(2.0 * math.sqrt(re_s**2 + im_s**2) / n_samples)
                
                # Expected Solar
                re_es: float = 0.0
                im_es: float = 0.0
                for n in range(n_samples):
                    re_es += expected_solar_series[n] * math.cos(omega * n)
                    im_es += -expected_solar_series[n] * math.sin(omega * n)
                expected_solar_amp.append(2.0 * math.sqrt(re_es**2 + im_es**2) / n_samples)
                
                # Household Consumption (Load)
                re_c: float = 0.0
                im_c: float = 0.0
                for n in range(n_samples):
                    re_c += consumption_series[n] * math.cos(omega * n)
                    im_c += -consumption_series[n] * math.sin(omega * n)
                consumption_amp.append(2.0 * math.sqrt(re_c**2 + im_c**2) / n_samples)
        else:
            grid_amp = [0.0] * len(freqs)
            solar_amp = [0.0] * len(freqs)
            expected_solar_amp = [0.0] * len(freqs)
            consumption_amp = [0.0] * len(freqs)
            
        return freqs, grid_amp, solar_amp, expected_solar_amp, consumption_amp

    def rotate_slides(self) -> None:
        """Rotates the active slide and updates axis visibility and the AI summary display.

        Raises:
            None.
        """
        if self.current_slide == 1:
            self.current_slide = 2
        else:
            self.current_slide = 1
        
        self.update_slide_visibility()
        self.after(29000, self.rotate_slides)

    def update_slide_visibility(self) -> None:
        """Swaps the visibility of the time-domain and frequency-domain subplots and updates the AI summary text.

        Raises:
            None.
        """
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
        # Trigger an immediate redraw of the new slide so it updates instantly
        self.solar_bars_dirty = True
        self.update_chart(self.status_label.cget("text"), self.status_label.cget("fg"))

    def update_weather_display(self) -> None:
        """Fetches and updates the weather display widget text."""
        live_weather = self.fetch_live_weather()
        temp = live_weather.get("temp")
        wcode = live_weather.get("weather_code")
        cloud_cover = live_weather.get("cloud_cover")
        
        # Fallback to cache file if live query is empty
        if temp is None or wcode is None:
            cache_file = self.summary_cache_file
            if os.path.exists(cache_file):
                try:
                    with open(cache_file, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                        metrics = data.get("metrics", {})
                        if temp is None:
                            temp = metrics.get("temp_max")
                        if cloud_cover is None:
                            cloud_cover = metrics.get("cloud_cover")
                        if wcode is None and cloud_cover is not None:
                            cc = float(cloud_cover)
                            if cc < 10:
                                wcode = 0
                            elif cc < 30:
                                wcode = 1
                            elif cc < 60:
                                wcode = 2
                            else:
                                wcode = 3
                except Exception:
                    pass
                    
        if temp is not None:
            temp_str = f"{temp:.1f}°C"
        else:
            temp_str = "N/A"
            
        if wcode is not None:
            if wcode == 0:
                sky_desc = "Clear"
            elif wcode == 1:
                sky_desc = "Mainly Clear"
            elif wcode == 2:
                sky_desc = "Partly Cloudy"
            elif wcode == 3:
                sky_desc = "Overcast"
            elif wcode in (45, 48):
                sky_desc = "Foggy"
            elif wcode in (51, 53, 55):
                sky_desc = "Drizzle"
            elif wcode in (61, 63, 65):
                sky_desc = "Rainy"
            elif wcode in (80, 81, 82):
                sky_desc = "Chance of Rain"
            elif wcode in (71, 73, 75, 77, 85, 86):
                sky_desc = "Snowy"
            elif wcode in (95, 96, 99):
                sky_desc = "Thunderstorm"
            else:
                sky_desc = "Cloudy"
            
            if cloud_cover is not None:
                sky_str = f"{sky_desc} ({int(cloud_cover)}%)"
            else:
                sky_str = sky_desc
        else:
            sky_str = "N/A"
            
        self.weather_label.config(text=f"{temp_str} | {sky_str}")

    def update_chart(self, label_text: str, color: str) -> None:
        """Updates the status text label and redraws the grid usage graph.

        Adjusts the chart's X-axis range to show a rolling 24-hour window ending at
        the current time, dynamically recalculates the Y-axis scale with padding,
        and requests the matplotlib canvas to redraw.

        Args:
            label_text: The updated status text displaying kW usage and state.
            color: The color (hex or standard name) to style the label and line.
        """
        self.status_label.config(text=label_text, fg=color)
        
        t0 = time.perf_counter()
        
        if self.current_slide == 1:
            # Thread-safe copy of telemetry data lists
            with self.data_lock:
                usage_copy = list(self.usage)
                timestamps_copy = list(self.timestamps)
                se_timestamps_copy = list(self.se_timestamps)
                se_power_copy = list(self.se_power)
                chilicon_timestamps_copy = list(self.chilicon_timestamps)
                chilicon_power_copy = list(self.chilicon_power)
            
            # Build segments and dynamically color/size them: red for importing (>0 kW), green for exporting (<0 kW).
            if len(usage_copy) > 1:
                x_nums = mdates.date2num(timestamps_copy)
                segments = []
                colors = []
                widths = []
                for i in range(len(usage_copy) - 1):
                    t1, t2 = timestamps_copy[i], timestamps_copy[i+1]
                    # Skip segment connection if there is a gap > 10 minutes (power outage or log halt)
                    if (t2 - t1).total_seconds() > 600:
                        continue
                    y1, y2 = usage_copy[i], usage_copy[i+1]
                    segments.append(((x_nums[i], y1), (x_nums[i+1], y2)))
                    avg_y = (y1 + y2) / 2.0
                    if avg_y > 0:
                        colors.append(IMPORT_COLOR)
                        widths.append(1.8)
                    else:
                        colors.append(EXPORT_COLOR)
                        widths.append(1.3)
                self.lc.set_segments(segments)
                self.lc.set_colors(colors)
                self.lc.set_linewidths(widths)
            else:
                self.lc.set_segments([])
            
            # Rolling 24-hour X-axis where the newest data is always on the far right.
            now: datetime.datetime = datetime.datetime.now()
            start_time: datetime.datetime = now - datetime.timedelta(hours=24)
            self.ax.set_xlim(start_time, now)
            
            # Dynamically scale Y-axis with some margin above and below minimum/maximum points.
            if usage_copy:
                y_min: float = min(usage_copy)
                y_max: float = max(usage_copy)
                # Increase top padding to leave the top portion of the plot completely free for text watermarks
                y_range: float = max(y_max - y_min, 1.0)
                y_lim_min: float = min(0.0, y_min - 0.15 * y_range)
                y_lim_max: float = max(0.0, y_max + 0.85 * y_range)
                self.ax.set_ylim(y_lim_min, y_lim_max)
                
            # Draw SolarEdge and Chillicon stacked bars on secondary Y-axis
            if not self.solar_off and hasattr(self, 'ax_bar'):
                if getattr(self, 'solar_bars_dirty', True):
                    self.ax_bar.clear()
                    self.ax_bar.tick_params(colors='#fbbf24')
                    self.ax_bar.yaxis.set_label_position('right')
                    self.ax_bar.spines['right'].set_color('#fbbf24')
                    self.ax_bar.spines['left'].set_color('none')
                    self.ax_bar.spines['top'].set_color('none')
                    self.ax_bar.spines['bottom'].set_color('none')
                    self.ax_bar.set_ylabel('Total Solar PV (kW)', color='#fbbf24', rotation=270, labelpad=15)
                    
                    # Align both SolarEdge and Chillicon on a 10-minute grid
                    grid_se = defaultdict(list)
                    grid_ch = defaultdict(list)
                    
                    for ts, p in zip(se_timestamps_copy, se_power_copy):
                        if ts >= start_time:
                            m = (ts.minute // 10) * 10
                            rounded = ts.replace(minute=m, second=0, microsecond=0)
                            grid_se[rounded].append(p)
                            
                    if not self.chilicon_off:
                        for ts, p in zip(chilicon_timestamps_copy, chilicon_power_copy):
                            if ts >= start_time:
                                m = (ts.minute // 10) * 10
                                rounded = ts.replace(minute=m, second=0, microsecond=0)
                                grid_ch[rounded].append(p)
                    
                    all_keys = sorted(list(set(list(grid_se.keys()) + list(grid_ch.keys()))))
                    
                    if all_keys:
                        bar_times = []
                        se_heights = []
                        ch_heights = []
                        for k in all_keys:
                            bar_times.append(k)
                            se_heights.append(sum(grid_se[k])/len(grid_se[k]) if grid_se[k] else 0.0)
                            ch_heights.append(sum(grid_ch[k])/len(grid_ch[k]) if grid_ch[k] else 0.0)
                            
                        width_in_days = 10.0 / (24.0 * 60.0) # 10 minutes
                        # Draw SolarEdge (bottom)
                        self.ax_bar.bar(bar_times, se_heights, width=width_in_days, color='#fbbf24', alpha=0.1, zorder=1, edgecolor='none')
                        # Draw Chillicon (stacked on top of SolarEdge - bright neon yellow)
                        self.ax_bar.bar(bar_times, ch_heights, bottom=se_heights, width=width_in_days, color='#ffff00', alpha=0.15, zorder=1.5, edgecolor='none')
                        
                        max_power = max([s + c for s, c in zip(se_heights, ch_heights)]) if all_keys else 1.0
                        self.ax_bar.set_ylim(0, max_power * 3)
                    else:
                        self.ax_bar.set_ylim(0, 10)
                    self.solar_bars_dirty = False
            
            # Request redraw on matplotlib canvas
            self.fig.canvas.draw()
            t1 = time.perf_counter()
            logging.info(f"Matplotlib canvas draw took {(t1 - t0)*1000:.2f} ms (current_slide=1)")
            
        elif self.current_slide == 2:
            # Draw the frequency spectrum on self.ax_freq
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
                self.ax_freq.plot(freqs, grid_amp, color=IMPORT_COLOR, label='Grid Spectrum', linewidth=1.5)
                self.ax_freq.plot(freqs, solar_amp, color='#fbbf24', label='Solar Spectrum (Actual)', linewidth=1.5)
                self.ax_freq.plot(freqs, expected_solar_amp, color=EXPECTED_SOLAR_COLOR, linestyle='--', label='Expected Solar (Weather Modulated)', linewidth=1.3)
                self.ax_freq.plot(freqs, consumption_amp, color=CONSUMPTION_COLOR, label='Household Consumption (Load)', linewidth=1.5)
                # Highlight physical rhythms (diurnal = 1.0, semi-diurnal = 2.0)
                self.ax_freq.axvline(1.0, color='deepskyblue', linestyle='--', alpha=0.5, label='24h Diurnal')
                self.ax_freq.axvline(2.0, color='violet', linestyle='--', alpha=0.5, label='12h Semi-Diurnal')
                self.ax_freq.set_xlim(0.1, 4.0)
                self.ax_freq.grid(color='gray', linestyle=':', alpha=0.3)
                self.ax_freq.legend(facecolor='black', edgecolor='white', labelcolor='white', fontsize=8)
                
            self.fig.canvas.draw()
            t1 = time.perf_counter()
            logging.info(f"Matplotlib canvas draw took {(t1 - t0)*1000:.2f} ms (current_slide=2)")

    def start_fast_render_loop(self) -> None:
        """Starts the periodic real-time GUI render loop."""
        logging.info("Starting real-time 2-second GUI render loop.")
        self.fast_render_loop()

    def fast_render_loop(self) -> None:
        """Tkinter loop running every 2 seconds to refresh time, weather, and redraw Slide 1 if active."""
        if not self.running:
            return
            
        try:
            # 1. Update Time Widget
            now_dt = datetime.datetime.now()
            time_str = now_dt.strftime("%H:%M")
            date_str = now_dt.strftime("%A, %b %d, %Y")
            self.time_label.config(text=time_str)
            self.date_label.config(text=date_str)
            
            # 2. Update Weather Widget (uses Open-Meteo cache)
            self.update_weather_display()
            
            # 3. Redraw Slide 1 if active
            if self.current_slide == 1:
                self.update_chart(self.latest_status_text, self.latest_status_color)
        except Exception as e:
            logging.error(f"Error in fast_render_loop: {e}")
            
        self.after(2000, self.fast_render_loop)

    def start_summary_loop(self) -> None:
        """Spawns the background thread to fetch Gemini summaries periodically."""
        self.summary_thread: threading.Thread = threading.Thread(target=self.summary_loop, daemon=True)
        self.summary_thread.start()

    def summary_loop(self) -> None:
        """Periodically polls or fetches grid usage summaries based on LLM_MODE."""
        # Wait 10 seconds for initial startup to settle.
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
                
                # Poll cache file modification time every 10 seconds
                for _ in range(1):
                    if not self.running:
                        break
                    time.sleep(10)
        else:
            logging.info("Running in direct summary loop (querying Gemini API directly).")
            while self.running:
                try:
                    self.fetch_gemini_summary()
                except Exception as e:
                    logging.error(f"Failed in direct summary loop: {e}")
                
                # Sleep for 15 minutes (900 seconds), checking self.running every 10 seconds.
                for _ in range(90):
                    if not self.running:
                        break
                    time.sleep(10)

    def load_cached_summary(self) -> None:
        """Loads previously cached summaries (both time-domain and frequency-domain) from disk.

        Raises:
            None.
        """
        loaded: bool = False
        if os.path.exists(self.summary_cache_file):
            try:
                with open(self.summary_cache_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    ts_str = data.get("timestamp")
                    summary = data.get("summary", "")
                    dft_explanation = data.get("dft_explanation", "")
                    
                    if ts_str and summary:
                        ts = self.parse_timestamp(ts_str)
                        if ts:
                            self.last_summary_time = ts
                            
                            # Split baseline and local delta if possible, or just set baseline
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
                                
                            loaded = True
                            logging.info("Loaded cached Gemini summary and local explanations from disk.")
            except Exception as e:
                logging.error(f"Failed to load cached summary: {e}")
            except Exception as e:
                logging.error(f"Failed to load cached Gemini summary: {e}")
                
        self.update_summary_display()

    def generate_hourly_summaries(self) -> str:
        """Parses the entire historical CSV files and computes hourly min, max, avg, and median.
        
        Returns:
            A compact CSV string representation of Net Grid and SolarEdge PV data bucketed by hour.
        """
        if not os.path.exists(self.history_file):
            return ""
            
        hourly_data = defaultdict(list)
        try:
            with open(self.history_file, 'r') as f:
                reader = csv.reader(line.replace('\x00', '') for line in f)
                for row in reader:
                    if len(row) == 2:
                        ts_str = row[0].strip().replace('\x00', '')
                        val_str = row[1].strip().replace('\x00', '')
                        if not ts_str or not val_str:
                            continue
                        # Fast string slicing to grab "YYYY-MM-DDTHH" without expensive datetime parsing
                        hour_key = ts_str[:13].replace('T', ' ') + ":00"
                        try:
                            hourly_data[hour_key].append(float(val_str))
                        except ValueError:
                            continue
        except Exception as e:
            logging.error(f"Error parsing history file for aggregation: {e}")
            return ""
            
        se_hourly_data = defaultdict(list)
        if not self.solar_off and os.path.exists(self.se_history_file):
            try:
                with open(self.se_history_file, 'r') as f:
                    reader = csv.reader(line.replace('\x00', '') for line in f)
                    for row in reader:
                        if len(row) == 2:
                            ts_str = row[0].strip().replace('\x00', '')
                            val_str = row[1].strip().replace('\x00', '')
                            if not ts_str or not val_str:
                                continue
                            hour_key = ts_str[:13].replace('T', ' ') + ":00"
                            try:
                                se_hourly_data[hour_key].append(float(val_str))
                            except ValueError:
                                continue
            except Exception as e:
                logging.error(f"Error parsing SolarEdge history for aggregation: {e}")
                
        se_battery_hourly_data = defaultdict(list)
        if not self.solar_off and os.path.exists(self.se_battery_history_file):
            try:
                with open(self.se_battery_history_file, 'r') as f:
                    reader = csv.reader(line.replace('\x00', '') for line in f)
                    for row in reader:
                        if len(row) == 3:
                            ts_str = row[0].strip().replace('\x00', '')
                            p_str = row[1].strip().replace('\x00', '')
                            soc_str = row[2].strip().replace('\x00', '')
                            if not ts_str or not p_str or not soc_str:
                                continue
                            hour_key = ts_str[:13].replace('T', ' ') + ":00"
                            try:
                                se_battery_hourly_data[hour_key].append((float(p_str), float(soc_str)))
                            except ValueError:
                                continue
            except Exception as e:
                logging.error(f"Error parsing SolarEdge battery history for aggregation: {e}")
                
        chilicon_hourly_data = defaultdict(list)
        if not self.chilicon_off and os.path.exists(self.chilicon_history_file):
            try:
                with open(self.chilicon_history_file, 'r') as f:
                    reader = csv.reader(line.replace('\x00', '') for line in f)
                    for row in reader:
                        if len(row) == 3:
                            ts_str = row[0].strip().replace('\x00', '')
                            p_str = row[1].strip().replace('\x00', '')
                            if not ts_str or not p_str:
                                continue
                            hour_key = ts_str[:13].replace('T', ' ') + ":00"
                            try:
                                chilicon_hourly_data[hour_key].append(float(p_str))
                            except ValueError:
                                continue
            except Exception as e:
                logging.error(f"Error parsing Chillicon history for aggregation: {e}")

        lines = ["Hour,Avg_kW,Min_kW,Max_kW,Median_kW,SE_Avg_kW,SE_Max_kW,SE_Energy_kWh,Battery_Avg_kW,Battery_SoC,Chillicon_Avg_kW,Chillicon_Max_kW,Chillicon_Energy_kWh"]
        all_hours = sorted(list(set(
            list(hourly_data.keys()) + 
            list(se_hourly_data.keys()) + 
            list(se_battery_hourly_data.keys()) + 
            list(chilicon_hourly_data.keys())
        )))
        
        for hour in all_hours:
            vals = hourly_data[hour]
            se_vals = se_hourly_data[hour]
            bat_vals = se_battery_hourly_data[hour]
            ch_vals = chilicon_hourly_data[hour]
            
            if vals:
                avg_kw = sum(vals) / len(vals)
                min_kw = min(vals)
                max_kw = max(vals)
                med_kw = statistics.median(vals)
            else:
                avg_kw, min_kw, max_kw, med_kw = 0.0, 0.0, 0.0, 0.0
                
            if se_vals:
                se_avg_kw = sum(se_vals) / len(se_vals)
                se_max_kw = max(se_vals)
                se_energy_kwh = se_avg_kw * 1.0
            else:
                se_avg_kw, se_max_kw, se_energy_kwh = 0.0, 0.0, 0.0
                
            if bat_vals:
                bat_powers = [v[0] for v in bat_vals]
                bat_socs = [v[1] for v in bat_vals]
                bat_avg_kw = sum(bat_powers) / len(bat_powers)
                bat_avg_soc = sum(bat_socs) / len(bat_socs)
            else:
                bat_avg_kw, bat_avg_soc = 0.0, 0.0
                
            if ch_vals:
                ch_avg_kw = sum(ch_vals) / len(ch_vals)
                ch_max_kw = max(ch_vals)
                ch_energy_kwh = ch_avg_kw * 1.0
            else:
                ch_avg_kw, ch_max_kw, ch_energy_kwh = 0.0, 0.0, 0.0
                
            lines.append(f"{hour},{avg_kw:.3f},{min_kw:.3f},{max_kw:.3f},{med_kw:.3f},{se_avg_kw:.3f},{se_max_kw:.3f},{se_energy_kwh:.3f},{bat_avg_kw:.3f},{bat_avg_soc:.1f},{ch_avg_kw:.3f},{ch_max_kw:.3f},{ch_energy_kwh:.3f}")
            
        return "\n".join(lines)

    def fetch_gemini_summary(self) -> None:
        """Fetches a summary of the current day's data from Gemini.

        Prepares the usage data as a compact CSV string, calls the Gemini model via
        Vertex AI client, and updates the background dashboard visualization.
        """
        if not self.local_llm and not GENAI_AVAILABLE:
            logging.warning("google-genai or httpx package is not imported; skipping Gemini summary.")
            return

        # Ensure we have data points to summarize
        if not self.usage or len(self.usage) < 10:
            logging.info("Not enough data to generate Gemini summary.")
            return

        # Check if we already have a fresh summary (either from startup load or previous loop)
        now = datetime.datetime.now()
        if self.last_summary_time and now - self.last_summary_time < datetime.timedelta(minutes=15):
            logging.info("Skipping Gemini call; local cached summary is still fresh.")
            return

        try:
            logging.info("Initiating Gemini API call to fetch grid summary...")
            # 1. Generate ultra-compact hourly summaries of the ENTIRE historical dataset
            csv_data = self.generate_hourly_summaries()
            if not csv_data or len(csv_data.split('\n')) < 2:
                logging.warning("No historical data available for Gemini summary.")
                return

            if self.local_llm:
                logging.info("Initiating native local Jetson Ollama API call...")
                
                # --- Configuration & Environment Setup ---
                # Attempt to parse local .env file manually if python-dotenv isn't loaded globally.
                # This ensures we dynamically fetch the active Jetson IP and Model without hardcoding.
                env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
                ollama_host = os.environ.get("OLLAMA_HOST")
                model_name = os.environ.get("EDGE_MODEL", "gemma2-edge")
                
                if not ollama_host and os.path.exists(env_path):
                    try:
                        with open(env_path, 'r') as f:
                            for line in f:
                                if line.strip().startswith("OLLAMA_HOST="):
                                    ollama_host = line.split("=", 1)[1].strip().strip('"').strip("'")
                                elif line.strip().startswith("EDGE_MODEL="):
                                    model_name = line.split("=", 1)[1].strip().strip('"').strip("'")
                    except Exception as env_err:
                        logging.warning(f"Could not parse local .env file for Ollama config: {env_err}")
                
                # Fallback to localhost if no network IP was specified
                if not ollama_host:
                    ollama_host = "http://localhost:11434/api/generate"

                # --- Prompt Template Loading ---
                prompt_path: str = os.path.join(os.path.dirname(os.path.abspath(__file__)), "gemma_prompt.txt")
                if not os.path.exists(prompt_path):
                    logging.error(f"Required local prompt template not found at: {prompt_path}")
                    return

                try:
                    with open(prompt_path, 'r', encoding='utf-8') as pf:
                        prompt_template: str = pf.read()
                except Exception as pe:
                    logging.error(f"Failed to read Ollama prompt file {prompt_path}. Error: {pe}")
                    return

                # --- Natively Calculate Grid Telemetry Statistics ---
                # To minimize LLM token overhead on edge devices, we calculate the absolute 
                # min/max/sums natively in Python instead of asking the LLM to aggregate the CSV.
                reader = csv.reader(csv_data.splitlines())
                next(reader)  # skip header
                
                total_imported = 0.0
                total_exported = 0.0
                se_generated = 0.0
                battery_discharged = 0.0
                battery_charged = 0.0
                chilicon_generated = 0.0
                inferred_chilicon = 0.0
                
                peak_grid_import = 0.0
                peak_grid_export = 0.0
                peak_se_pv = 0.0
                
                day_date_str = "N/A"
                
                rows = list(reader)
                if rows:
                    day_date_str = rows[-1][0][:10]
                    
                for row in rows:
                    if len(row) < 13:
                        continue
                    
                    avg_kw = float(row[1])
                    min_kw = float(row[2])
                    max_kw = float(row[3])
                    se_avg = float(row[5])
                    se_max = float(row[6])
                    se_energy = float(row[7])
                    bat_avg = float(row[8])
                    ch_avg = float(row[10])
                    ch_energy = float(row[12])
                    
                    # 1. Grid Imports / Exports (kWh)
                    if avg_kw > 0:
                        total_imported += avg_kw * 1.0
                    else:
                        total_exported += abs(avg_kw) * 1.0
                        
                    # Peaks
                    if max_kw > 0:
                        peak_grid_import = max(peak_grid_import, max_kw)
                    if min_kw < 0:
                        peak_grid_export = max(peak_grid_export, abs(min_kw))
                        
                    # 2. SolarEdge Generated
                    se_generated += se_energy
                    peak_se_pv = max(peak_se_pv, se_max)
                    
                    # 3. Battery Activity
                    if bat_avg > 0:
                        battery_discharged += bat_avg * 1.0
                    else:
                        battery_charged += abs(bat_avg) * 1.0
                        
                    # 4. Chillicon Generated
                    chilicon_generated += ch_energy
                    
                    # 5. Inferred Chillicon
                    if avg_kw < 0:
                        grid_export_rate = abs(avg_kw)
                        inferred_rate = grid_export_rate - se_avg - max(0.0, bat_avg)
                        if inferred_rate > 0:
                            inferred_chilicon += inferred_rate * 1.0
                            
                # Net Billing Impact
                import_cost = total_imported * 0.19
                export_credit = total_exported * 0.19
                flex_bonus = battery_discharged * 0.31
                net_credit = export_credit - import_cost + flex_bonus
                
                # Estimate Home Consumption
                total_solar = se_generated + (chilicon_generated if chilicon_generated > 0 else inferred_chilicon)
                home_consumption = total_solar + total_imported - total_exported + battery_discharged - battery_charged
                if home_consumption < 0:
                    home_consumption = 0.0
                
                # Hydrate the prompt template with native telemetry
                prompt: str = prompt_template.format(
                    total_imported=total_imported,
                    total_exported=total_exported,
                    se_generated=se_generated,
                    inferred_chilicon=inferred_chilicon,
                    net_credit=net_credit,
                    peak_grid_import=peak_grid_import,
                    peak_se_pv=peak_se_pv,
                    home_consumption=home_consumption,
                    day_date=day_date_str
                )

                # --- Execute Native HTTP POST to Jetson ---
                payload = {"model": model_name, "prompt": prompt, "stream": False}
                req = urllib.request.Request(
                    ollama_host, 
                    data=json.dumps(payload).encode('utf-8'), 
                    headers={'Content-Type': 'application/json'}
                )
                
                start_time = time.time()
                try:
                    # Execute synchronous HTTP POST, blocking this background thread
                    with urllib.request.urlopen(req, timeout=120.0) as response:
                        result = json.loads(response.read().decode('utf-8'))
                        elapsed = time.time() - start_time
                        summary_text = result.get('response', '').strip()
                        
                        if summary_text:
                            # Append metadata proving the edge model was used
                            retrieved_time = now.strftime("%Y-%m-%d %H:%M:%S")
                            summary_text += f"\n\n[Edge Model: {model_name} | Generated: {retrieved_time} | Inference Time: {elapsed:.1f}s]"
                            
                            # Cache the summary to disk
                            try:
                                with open(self.summary_cache_file, 'w') as f:
                                    json.dump({
                                        "timestamp": now.isoformat(),
                                        "summary": summary_text
                                    }, f)
                                logging.info("Cached new Local Jetson summary to disk.")
                            except Exception as cache_err:
                                logging.error(f"Failed to cache local summary to disk: {cache_err}")
                            
                            # Cache and update GUI safely on main thread
                            self.last_summary_time = now
                            self.after(0, self.update_background_summary, summary_text)
                            logging.info(f"Local Jetson summary successfully generated in {elapsed:.1f}s.")
                            
                            # Return early, bypassing the Vertex AI fallback
                            return
                except Exception as ollama_err:
                    logging.error(f"Local Ollama API failed: {ollama_err}")
                    return

            # 2. Check for API key (via Environment variable or local .env file)
            api_key = os.environ.get("GEMINI_API_KEY")
            if not api_key:
                # Try reading .env in the same directory as the script
                env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
                if os.path.exists(env_path):
                    try:
                        with open(env_path, 'r') as f:
                            for line in f:
                                if line.strip().startswith("GEMINI_API_KEY="):
                                    api_key = line.split("=", 1)[1].strip().strip('"').strip("'")
                                    break
                    except Exception as env_err:
                        logging.warning(f"Could not parse local .env file: {env_err}")

            # 3. Setup the service account credentials if available
            possible_paths = [
                os.path.join(os.path.dirname(os.path.abspath(__file__)), "Auth/service_account.json"),
                os.path.join(os.path.dirname(os.path.abspath(__file__)), "auth/service_account.json"),
                os.path.join(os.path.dirname(os.path.abspath(__file__)), "../Auth/service_account.json"),
                os.path.join(os.path.dirname(os.path.abspath(__file__)), "../auth/service_account.json"),
                os.path.join(home_dir, "Auth/service_account.json"),
                os.path.join(home_dir, "auth/service_account.json")
            ]
            for path in possible_paths:
                if os.path.exists(path):
                    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = path
                    logging.info(f"Using service account key found at: {path}")
                    break

            has_service_account = "GOOGLE_APPLICATION_CREDENTIALS" in os.environ

            # 4. Verify we have at least one authentication method configured
            if not api_key and not has_service_account:
                logging.warning("Neither GEMINI_API_KEY nor GOOGLE_APPLICATION_CREDENTIALS is set; skipping Gemini summary.")
                return

            # 5. Initialize client based on available auth method
            model_name = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
            http_opts = types.HttpOptions(httpx_client=httpx.Client(timeout=60.0))
            if api_key:
                logging.info("Initializing GenAI client using developer API key.")
                client = genai.Client(api_key=api_key, http_options=http_opts)
            else:
                logging.info("Initializing GenAI client for Vertex AI.")
                project_id = os.environ.get("GOOGLE_CLOUD_PROJECT")
                # Fix: If project_id is missing, read it directly from the service account JSON
                # to prevent the Vertex AI SDK from hanging for 120 seconds while probing the network.
                if not project_id and has_service_account:
                    try:
                        with open(os.environ["GOOGLE_APPLICATION_CREDENTIALS"], 'r') as key_file:
                            sa_data = json.load(key_file)
                            project_id = sa_data.get("project_id")
                            logging.info(f"Auto-extracted project_id '{project_id}' from Service Account JSON.")
                    except Exception as json_err:
                        logging.warning(f"Could not read project_id from service account: {json_err}")
                
                location = os.environ.get("GOOGLE_CLOUD_LOCATION", "global")
                client = genai.Client(
                    vertexai=True,
                    project=project_id,
                    location=location,
                    http_options=http_opts
                )

            # Load the prompt template from external txt file dynamically at runtime.
            prompt_path: str = os.path.join(os.path.dirname(os.path.abspath(__file__)), "gemini_prompt.txt")
            if not os.path.exists(prompt_path):
                prompt_path = os.path.join(home_dir, "gemini_prompt.txt")
                
            if not os.path.exists(prompt_path):
                logging.error(f"Required external prompt template not found at: {prompt_path}")
                return

            try:
                with open(prompt_path, 'r', encoding='utf-8') as pf:
                    prompt_template: str = pf.read()
                logging.info(f"Successfully loaded external prompt template from {prompt_path}")
            except Exception as pe:
                logging.error(f"Failed to read prompt file {prompt_path}. Error: {pe}")
                return

            # Format the CSV data and relevant date placeholders (both current time and last telemetry time)
            current_dt_str: str = now.strftime("%Y-%m-%d %H:%M:%S")
            last_dt_str: str = self.timestamps[-1].strftime("%Y-%m-%d %H:%M:%S") if self.timestamps else "N/A"
            
            # Extract the starting date/time from the first row of our aggregated CSV (skipping the header)
            lines_data = csv_data.split('\n')
            first_dt_str = lines_data[1].split(',')[0] if len(lines_data) > 1 else "N/A"
            
            try:
                # Support placeholders in the template
                prompt: str = prompt_template.format(
                    csv_data=csv_data,
                    current_date_time=current_dt_str,
                    last_data_time=last_dt_str,
                    first_data_time=first_dt_str
                )
            except KeyError as ke:
                logging.error(f"Failed to format prompt template due to missing placeholder: {ke}")
                return

            # Native Exponential Backoff Retry Loop
            backoff_delays = [2, 4, 8]
            response = None
            
            for attempt, delay in enumerate(backoff_delays + [0]):
                try:
                    response = client.models.generate_content(
                        model=model_name,
                        contents=prompt,
                    )
                    break # Success
                except Exception as api_err:
                    if attempt < len(backoff_delays):
                        logging.warning(f"Gemini API call failed: {api_err}. Retrying in {delay}s...")
                        time.sleep(delay)
                    else:
                        logging.error(f"Gemini API completely failed after retries: {api_err}")
                        raise

            summary_text = response.text
            if summary_text:
                # Remove any leading/trailing blank lines
                summary_text = summary_text.strip()
                
                # Cache the summary to disk
                try:
                    with open(self.summary_cache_file, 'w') as f:
                        json.dump({
                            "timestamp": now.isoformat(),
                            "summary": summary_text
                        }, f)
                    logging.info("Cached new Gemini summary to disk.")
                except Exception as cache_err:
                    logging.error(f"Failed to cache summary to disk: {cache_err}")

                self.last_summary_time = now
                self.after(0, self.update_background_summary, summary_text)
                logging.info("Gemini summary successfully generated and updated.")

        except Exception as e:
            logging.error(f"Error fetching summary from Gemini: {e}")

    def wrap_text(self, text: str, width: int = 100) -> str:
        """Wraps text lines to a maximum width while preserving layout and lists.

        This method splits the incoming text by double newlines into paragraphs,
        detects if a paragraph is structured (like a list or table), and wraps
        paragraphs or individual lines accordingly to prevent text running off the screen.

        Args:
            text: The input text block to wrap.
            width: The maximum character width per line.

        Returns:
            The wrapped text block with line breaks inserted.
        """
        # Normalize carriage returns and other line endings to standard newlines
        text = text.replace('\r\n', '\n').replace('\r', '\n')
        paragraphs = text.split('\n\n')
        wrapped_paragraphs = []
        for para in paragraphs:
            lines = para.split('\n')
            is_structured = False
            for line in lines:
                stripped = line.strip()
                # Detect bullet lists or table-like columns (separated by multiple spaces)
                if stripped.startswith(('*', '-', '1.', '2.', '3.')) or '   ' in line or '\t' in line:
                    is_structured = True
                    break
                    
            if is_structured:
                wrapped_lines = []
                for line in lines:
                    if len(line) <= width:
                        wrapped_lines.append(line)
                    else:
                        # Wrap the line while maintaining the initial indentation level
                        initial_indent = len(line) - len(line.lstrip())
                        indent_str = " " * initial_indent
                        wrapped_lines.append(textwrap.fill(
                            line,
                            width=width,
                            initial_indent=indent_str,
                            subsequent_indent=indent_str + "  "
                        ))
                wrapped_paragraphs.append('\n'.join(wrapped_lines))
            else:
                # Wrap regular paragraph text blocks
                wrapped_paragraphs.append(textwrap.fill(para, width=width))
                
        return '\n\n'.join(wrapped_paragraphs)

    def update_background_summary(self, text: str) -> None:
        """Updates the background summary text on the main thread."""
        self.baseline_text = text
        self.update_summary_display()

    def update_summary_display(self) -> None:
        """Merges baseline and local delta summaries and renders them in the Tkinter label widget."""
        full_text = ""
        if self.current_slide == 1:
            if hasattr(self, 'baseline_text') and self.baseline_text:
                clean_baseline = self.baseline_text.strip()
                marker = "[Live Local Delta (Jetson)"
                if marker in clean_baseline:
                    clean_baseline = clean_baseline.split(marker)[0].strip()
                full_text += clean_baseline
                
            if hasattr(self, 'local_delta_text') and self.local_delta_text:
                if full_text:
                    full_text += "\n\n"
                full_text += self.local_delta_text.strip()
        else:
            # Slide 2: Frequency-domain AI explanation
            if hasattr(self, 'local_dft_text') and self.local_dft_text:
                full_text = self.local_dft_text.strip()
            else:
                full_text = "Awaiting Frequency Domain Analysis..."
                
        self.summary_label.config(text=full_text)
        self.fig.canvas.draw_idle()
        
        # Save the merged summary to disk for offline viewing tools (view_dashboard.sh)
        try:
            time_domain_summary = ""
            if hasattr(self, 'baseline_text') and self.baseline_text:
                clean_baseline = self.baseline_text.strip()
                marker = "[Live Local Delta (Jetson)"
                if marker in clean_baseline:
                    clean_baseline = clean_baseline.split(marker)[0].strip()
                time_domain_summary += clean_baseline
            if hasattr(self, 'local_delta_text') and self.local_delta_text:
                if time_domain_summary:
                    time_domain_summary += "\n\n"
                time_domain_summary += self.local_delta_text.strip()

            merged_payload = {
                "timestamp": self.last_summary_time.isoformat() if self.last_summary_time else datetime.datetime.now().isoformat(),
                "summary": time_domain_summary,
                "dft_explanation": self.local_dft_text if hasattr(self, 'local_dft_text') else ""
            }
            with open(self.summary_cache_file, "w", encoding="utf-8") as f:
                json.dump(merged_payload, f, indent=4)
        except Exception as write_err:
            logging.error(f"Failed to write merged summary to disk: {write_err}")


    def parse_timestamp(self, ts_str: str) -> Optional[datetime.datetime]:
        """Robust parser for naive datetime strings."""
        ts_str = ts_str.strip().replace('\x00', '')
        for fmt in (
            "%Y-%m-%dT%H:%M:%S.%f",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d %H:%M:%S.%f"
        ):
            try:
                return datetime.datetime.strptime(ts_str, fmt)
            except ValueError:
                continue
        try:
            return datetime.datetime.fromisoformat(ts_str)
        except ValueError:
            return None

    def start_local_delta_loop(self) -> None:
        """Spawns the background thread to poll local deltas from the Jetson server."""
        self.local_delta_thread = threading.Thread(target=self.local_delta_loop, daemon=True)
        self.local_delta_thread.start()

    def local_delta_loop(self) -> None:
        """Runs the 15-minute sync loop, performing SCP and hitting the Jetson server."""
        import subprocess
        import shutil
        
        # Initial sleep for 15 seconds to allow dashboard startup to settle
        time.sleep(15)
        
        logging.info("Starting dashboard local delta sync loop...")
        while self.running:
            try:
                # 1. Sync CSVs to Jetson
                logging.info("Local Delta Loop: Syncing CSV history files to Jetson...")
                files_to_sync = []
                for f_path in (self.history_file, self.se_history_file, self.se_battery_history_file, self.chilicon_history_file):
                    if os.path.exists(f_path):
                        files_to_sync.append(f_path)
                        
                if files_to_sync:
                    if self.jetson_host == "localhost":
                        # Local copy
                        dest_dir = os.path.expanduser(self.jetson_backup_path) if self.jetson_backup_path.startswith("~") else self.jetson_backup_path
                        os.makedirs(dest_dir, exist_ok=True)
                        for f_path in files_to_sync:
                            try:
                                shutil.copy(f_path, dest_dir)
                            except Exception as copy_err:
                                logging.error(f"Local Delta Loop: Failed to copy {f_path} locally: {copy_err}")
                    else:
                        # Remote rsync for delta-transfer efficiency
                        dest = f"{self.jetson_user}@{self.jetson_host}:{self.jetson_backup_path}"
                        cmd = ["rsync", "-aqz"] + files_to_sync + [dest]
                        try:
                            subprocess.run(cmd, check=True, timeout=30)
                            logging.info(f"Local Delta Loop: Successfully synced CSVs to Jetson via rsync: {dest}")
                        except Exception as rsync_err:
                            logging.error(f"Local Delta Loop: rsync failed: {rsync_err}")
                
                # 2. Check if baseline summary cache file exists or use fallback
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
                            self.after(0, self.update_summary_display)
                            logging.info("Local Delta Loop: Successfully updated GUI summary text.")
                        else:
                            logging.warning("Local Delta Loop: Received empty response from Jetson server.")
                except Exception as post_err:
                    logging.error(f"Local Delta Loop: HTTP analysis query failed: {post_err}")
            except Exception as loop_err:
                logging.error(f"Local Delta Loop: Unexpected error: {loop_err}")
                
            for _ in range(90):
                if not self.running:
                    break
                time.sleep(10)

    def destroy(self) -> None:
        """Cleanly destroys the dashboard application, stopping threads and closing serial ports.

        Overrides the default Tkinter destroy method to ensure that all background processes
        and serial handles are released before the process exits.
        """
        logging.info("Destroying dashboard window. Cleaning up background tasks...")
        self.running = False
        
        # Close serial port if open to release hardware lock.
        if hasattr(self, 'ser') and self.ser:
            try:
                if self.ser.is_open:
                    self.ser.close()
                    logging.info("Serial connection closed cleanly on destroy.")
            except Exception as e:
                logging.error(f"Error closing serial port during destroy: {e}")
                
        super().destroy()

    def handle_signal(self, signum: int, frame: Any) -> None:
        """Handles termination signals by initiating a clean shutdown.

        This callback is registered with the OS signal module. It queues a shutdown
        operation on the main thread loop to avoid race conditions.

        Args:
            signum: The signal number received (e.g., SIGINT or SIGTERM).
            frame: The current stack frame object (unused).
        """
        logging.info(f"Received OS signal {signum}. Scheduling graceful shutdown...")
        # Use after() to schedule destruction on the main thread.
        self.after(0, self.shutdown_from_signal)

    def shutdown_from_signal(self) -> None:
        """Destroys the window and exits the application from a signal handler.

        This method is invoked on the main Tkinter thread to safely trigger widget destruction
        and exit the event mainloop.
        """
        self.destroy()
        self.quit()

    def check_signals(self) -> None:
        """Periodic callback to allow Python signal handlers to run in Tkinter mainloop.

        Tkinter's main loop blocks the main thread, which can delay OS signal processing.
        By setting up a rapid periodic timer callback, we return control to the Python
        interpreter briefly, letting Python check and invoke signal handlers.
        """
        if self.running:
            self.after(200, self.check_signals)

if __name__ == "__main__":
    app = GridDashboard()
    app.mainloop()
