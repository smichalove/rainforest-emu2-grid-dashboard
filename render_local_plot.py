import tkinter as tk
import csv
import os
import json
import datetime
import sys
import textwrap
import math
from collections import defaultdict
import matplotlib.dates as mdates
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.collections import LineCollection
from typing import List, Any, Tuple, Optional, Dict
import urllib.request
from PIL import Image, ImageTk

# Match settings from main dashboard.py
SUMMARY_FONT_SIZE: int = 10
SUMMARY_ALPHA: float = 0.55
SUMMARY_COLOR: str = 'deepskyblue'

# Real-time Status Label Settings
# Font size reduced from 32 to 24 to prevent horizontal clipping on narrow displays (e.g. 800px kiosk).
STATUS_FONT_SIZE: int = 24

IMPORT_COLOR: str = '#f43f5e'  # Modern rose red
EXPORT_COLOR: str = '#00ff00'  # Classic neon green
EXPECTED_SOLAR_COLOR: str = '#ffff00' # Bright yellow for expected weather-modulated solar
CONSUMPTION_COLOR: str = '#d946ef'    # Neon purple/magenta for household consumption

# Slide Rotation Interval Settings (in milliseconds)
SLIDE_1_DURATION_MS: int = 90000  # Stays up for 1.5 minutes
SLIDE_2_DURATION_MS: int = 15000  # Stays up for 15 seconds


# Load environment configuration if present
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
env_path = os.path.join(SCRIPT_DIR, ".env")
if os.path.exists(env_path):
    try:
        with open(env_path, 'r') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ[k.strip()] = v.strip().strip('"').strip("'")
    except Exception as e:
        print(f"Could not load .env file: {e}")

DEFAULT_LAT: str = os.environ.get("WEATHER_LAT", "47.5760")
DEFAULT_LON: str = os.environ.get("WEATHER_LON", "-122.0193")

# Seattle late May weather fallbacks
DEFAULT_WEATHER_FALLBACK: Dict[str, float] = {
    "cloud_cover": 45.0,
    "sunrise_hour": 5.25,
    "sunset_hour": 21.25
}

class OfflineViewer(tk.Tk):
    """Offline viewer that renders the historical grid telemetry for a screenshot."""

    def __init__(self) -> None:
        super().__init__()
        self.title("Grid Monitor Preview")
        self.configure(bg='black')
        
        # Configure windowed fullscreen/maximized size for easy screenshotting
        self.geometry("1024x768")
        
        self.live_mode: bool = "--live" in sys.argv
        
        self.bind("<Escape>", lambda e: self.destroy())
        if not self.live_mode:
            self.bind("<Button-1>", lambda e: self.destroy())

        self.usage: List[float] = []
        self.timestamps: List[datetime.datetime] = []
        self.se_power: List[float] = []
        self.se_timestamps: List[datetime.datetime] = []
        self.chilicon_power: List[float] = []
        self.chilicon_timestamps: List[datetime.datetime] = []
        self.chilicon_off: bool = "--chiliconoff" in sys.argv
        
        # Load local history file copied from the Pi
        self.load_history()
        self.load_solaredge_history()
        self.load_chilicon_history()
        self.weather_map = self.fetch_historical_weather()

        # Load combined hardware logos small banner
        self.logo_image_tk: Optional[ImageTk.PhotoImage] = None
        try:
            logo_path = os.path.join(SCRIPT_DIR, "scratch", "combined_logos_small.png")
            if os.path.exists(logo_path):
                img = Image.open(logo_path)
                self.logo_image_tk = ImageTk.PhotoImage(img)
        except Exception as e:
            print(f"Failed to load logo banner image: {e}")

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

        latest_val = self.usage[-1] if self.usage else 0.0
        # Use shorter status texts to avoid truncating on narrow screens.
        status = "Solar Export" if latest_val < 0 else "Grid Import"
        color = EXPORT_COLOR if latest_val < 0 else IMPORT_COLOR
        text = f"{latest_val:.3f} kW | {status}"

        self.status_label: tk.Label = tk.Label(
            self.right_header, text=text, font=('Helvetica', STATUS_FONT_SIZE, 'bold'), bg='black', fg=color, anchor='e'
        )
        self.status_label.pack(anchor='e', pady=(0, 2))

        latest_pv = self.se_power[-1] if self.se_power else 0.0
        self.sub_status_label: tk.Label = tk.Label(
            self.right_header, text=f"SolarEdge PV: {latest_pv:.3f} kW", font=('Helvetica', 16, 'bold'), bg='black', fg='#fbbf24', anchor='e'
        )
        self.sub_status_label.pack(anchor='e', pady=(0, 2))

        self.chilicon_status_label: tk.Label = tk.Label(
            self.right_header, text="", font=('Helvetica', 16, 'bold'), bg='black', fg='#ffff00', anchor='e'
        )
        if not self.chilicon_off:
            self.chilicon_status_label.pack(anchor='e', pady=(0, 2))
            latest_ch = self.chilicon_power[-1] if self.chilicon_power else 0.0
            self.chilicon_status_label.config(text=f"Chillicon PV: {latest_ch:.3f} kW")

        # Center Column for Hardware Logos
        if self.logo_image_tk:
            self.logo_label: tk.Label = tk.Label(
                self, image=self.logo_image_tk, bg='black'
            )
            self.logo_label.pack(side=tk.TOP, anchor='center', pady=(5, 5))

        # AI Summary text label below the header frame
        self.summary_label: tk.Label = tk.Label(
            self, text="Awaiting AI Analysis...", font=('Courier', 11, 'bold'),
            bg='black', fg=SUMMARY_COLOR, justify='left', anchor='nw',
            wraplength=980
        )
        # We do not pack the Tkinter summary label to prevent squishing the chart.
        # Instead, the summary is overlaid directly inside the Matplotlib chart background.

        # Matplotlib figure setup - expanded size for two subplots
        self.fig: Figure = Figure(figsize=(8, 6), dpi=100, facecolor='black')
        
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
        
        # Secondary axes for SolarEdge bar chart along the bottom
        self.ax_bar = self.ax.twinx()
        self.ax_bar.set_ylim(0, 10)  # Fixed arbitrary high limit so bars stay at bottom
        self.ax_bar.tick_params(colors='#fbbf24')
        self.ax_bar.yaxis.set_label_position('right')
        self.ax_bar.spines['right'].set_color('#fbbf24')
        self.ax_bar.spines['left'].set_color('none')
        self.ax_bar.spines['top'].set_color('none')
        self.ax_bar.spines['bottom'].set_color('none')
        self.ax_bar.set_ylabel('Total Solar PV (kW)', color='#fbbf24', rotation=270, labelpad=15)
        
        # Swap z-order so the main ax sits on top of ax_bar
        self.ax.set_zorder(self.ax_bar.get_zorder() + 1)
        self.ax.patch.set_visible(False)  # Must be transparent so ax_bar behind it is visible
        
        # Dotted horizontal line at 0 kW
        self.ax.axhline(0, color='gray', linestyle='--') 
        
        # LineCollection for dynamic segment styling
        self.lc: LineCollection = LineCollection([], linewidths=1.8, zorder=3)
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

        # Background summary text watermark for Slide 1 (Time Domain)
        self.summary_text_obj: Any = self.ax.text(
            0.02, 0.95, "Awaiting AI Analysis...",
            transform=self.ax.transAxes,
            ha='left', va='top',
            fontsize=SUMMARY_FONT_SIZE,
            color=SUMMARY_COLOR,
            alpha=SUMMARY_ALPHA,
            fontfamily='monospace',
            weight='bold',
            zorder=10
        )

        # Background summary text watermark for Slide 2 (Frequency Domain)
        self.summary_text_obj_freq: Any = self.ax_freq.text(
            0.02, 0.95, "Awaiting Frequency Domain Analysis...",
            transform=self.ax_freq.transAxes,
            ha='left', va='top',
            fontsize=SUMMARY_FONT_SIZE,
            color=SUMMARY_COLOR,
            alpha=SUMMARY_ALPHA,
            fontfamily='monospace',
            weight='bold',
            zorder=10
        )

        
        # State variables for Slide Rotation
        self.current_slide: int = 2 if "--slide2" in sys.argv else 1
        self.local_time_text: str = "Awaiting AI Analysis..."
        self.local_dft_text: str = "Awaiting Frequency Domain Analysis..."
        self.preview_filename: str = "dashboard_preview_slide2.jpeg" if self.current_slide == 2 else "dashboard_preview.jpeg"
        
        self.canvas: FigureCanvasTkAgg = FigureCanvasTkAgg(self.fig, master=self)
        self.canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)

        # Update initial slide visibility
        if self.current_slide == 2:
            self.ax.set_visible(False)
            self.ax_bar.set_visible(False)
            self.ax_freq.set_visible(True)
        else:
            self.ax.set_visible(True)
            self.ax_bar.set_visible(True)
            self.ax_freq.set_visible(False)

        # Load cached summary and draw the plot
        self.load_cached_summary()
        self.update_chart()

        # Schedule automatic screenshot generation or live polling loop
        if self.live_mode:
            self.after(2000, self.poll_remote_data)
            self.after(SLIDE_1_DURATION_MS, self.rotate_slides)

        # Capture screenshot only if explicitly requested on-demand
        if "--screenshot" in sys.argv:
            self.after(1500, self.save_screenshot)

    def load_history(self) -> None:
        """Loads data from local grid_history.csv file."""
        history_file = 'grid_history.csv'
        if not os.path.exists(history_file):
            print("Error: grid_history.csv not found in local directory!")
            return
            
        print("Loading local history...")
        # Get the latest timestamp in the file to establish the 24-hour cutoff
        last_ts = None
        try:
            with open(history_file, 'r') as f:
                reader = csv.reader(f)
                rows = list(reader)
                if rows:
                    for row in reversed(rows):
                        if len(row) == 2:
                            try:
                                last_ts = datetime.datetime.fromisoformat(row[0].strip())
                                break
                            except ValueError:
                                continue
        except Exception as e:
            print(f"Failed to pre-scan history file: {e}")
            return

        if not last_ts:
            print("No valid timestamps found in history.")
            return

        cutoff = last_ts - datetime.timedelta(days=1)
        
        try:
            with open(history_file, 'r') as f:
                reader = csv.reader(f)
                for row in reader:
                    if len(row) == 2:
                        try:
                            ts_str = row[0].replace('\x00', '').strip()
                            val_str = row[1].replace('\x00', '').strip()
                            if not ts_str or not val_str:
                                continue
                            ts = datetime.datetime.fromisoformat(ts_str)
                            if ts > cutoff:
                                self.timestamps.append(ts)
                                self.usage.append(float(val_str))
                        except Exception:
                            continue
            print(f"Loaded {len(self.usage)} data points.")
        except Exception as e:
            print(f"Failed to read history file: {e}")

    def load_solaredge_history(self) -> None:
        """Loads SolarEdge historical telemetry from CSV file."""
        se_history_file = 'solaredge_history.csv'
        if not os.path.exists(se_history_file):
            print("Warning: solaredge_history.csv not found.")
            return
            
        print("Loading local SolarEdge history...")
        # Align with the same 24-hour cutoff as the main history file
        if self.timestamps:
            cutoff = self.timestamps[-1] - datetime.timedelta(days=1)
        else:
            cutoff = datetime.datetime.now() - datetime.timedelta(days=1)
            
        try:
            with open(se_history_file, 'r') as f:
                reader = csv.reader(f)
                for row in reader:
                    if len(row) == 2:
                        try:
                            ts_str = row[0].strip().replace('\x00', '')
                            val_str = row[1].strip().replace('\x00', '')
                            if not ts_str or not val_str:
                                continue
                            ts = datetime.datetime.fromisoformat(ts_str)
                            if ts > cutoff:
                                self.se_timestamps.append(ts)
                                self.se_power.append(float(val_str))
                        except Exception:
                            continue
            print(f"Loaded {len(self.se_power)} SolarEdge historical data points.")
        except Exception as e:
            print(f"Failed to read SolarEdge history file: {e}")

    def load_chilicon_history(self) -> None:
        """Loads Chillicon historical telemetry from CSV file."""
        if self.chilicon_off:
            return
        chilicon_history_file = 'chilicon_history.csv'
        if not os.path.exists(chilicon_history_file):
            print("Warning: chilicon_history.csv not found.")
            return
            
        print("Loading local Chillicon history...")
        if self.timestamps:
            cutoff = self.timestamps[-1] - datetime.timedelta(days=1)
        else:
            cutoff = datetime.datetime.now() - datetime.timedelta(days=1)
            
        try:
            with open(chilicon_history_file, 'r') as f:
                reader = csv.reader(f)
                for row in reader:
                    if len(row) == 3:
                        try:
                           ts_str = row[0].strip().replace('\x00', '')
                           val_str = row[1].strip().replace('\x00', '')
                           if not ts_str or not val_str:
                               continue
                           ts = datetime.datetime.fromisoformat(ts_str)
                           if ts > cutoff:
                               self.chilicon_timestamps.append(ts)
                               self.chilicon_power.append(float(val_str))
                        except Exception:
                           continue
            print(f"Loaded {len(self.chilicon_power)} Chillicon historical data points.")
        except Exception as e:
            print(f"Failed to read Chillicon history file: {e}")

    def fetch_historical_weather(self, lat: str = DEFAULT_LAT, lon: str = DEFAULT_LON) -> Dict[str, Dict[str, Any]]:
        """Fetches daily average cloud cover, sunrise, and sunset times from Open-Meteo API.

        Args:
            lat: Latitude of target location.
            lon: Longitude of target location.

        Returns:
            A dictionary mapping date string "YYYY-MM-DD" to weather parameters.
        """
        url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&past_days=5&daily=cloud_cover_mean,sunrise,sunset&timezone=auto"
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=10) as response:
                res = json.loads(response.read().decode('utf-8'))
                daily = res.get("daily", {})
                times = daily.get("time", [])
                cloud_covers = daily.get("cloud_cover_mean", [])
                sunrises = daily.get("sunrise", [])
                sunsets = daily.get("sunset", [])
                
                weather_data = {}
                for i, t_str in enumerate(times):
                    sr_hour, ss_hour = 5.25, 21.25
                    if i < len(sunrises) and sunrises[i]:
                        try:
                            sr_dt = datetime.datetime.fromisoformat(sunrises[i])
                            sr_hour = sr_dt.hour + sr_dt.minute / 60.0
                        except Exception:
                            pass
                    if i < len(sunsets) and sunsets[i]:
                        try:
                            ss_dt = datetime.datetime.fromisoformat(sunsets[i])
                            ss_hour = ss_dt.hour + ss_dt.minute / 60.0
                        except Exception:
                            pass
                    cc = cloud_covers[i] if (i < len(cloud_covers) and cloud_covers[i] is not None) else 45.0
                    
                    weather_data[t_str] = {
                        "cloud_cover": cc,
                        "sunrise_hour": sr_hour,
                        "sunset_hour": ss_hour
                    }
                return weather_data
        except Exception as e:
            print(f"Error fetching historical weather in offline viewer: {e}")
            return {}

    def rotate_slides(self) -> None:
        """Rotates active slide state and refreshes chart visibility.

        Raises:
            None.
        """
        if self.current_slide == 1:
            self.current_slide = 2
            delay = SLIDE_2_DURATION_MS
        else:
            self.current_slide = 1
            delay = SLIDE_1_DURATION_MS
        self.update_slide_visibility()
        self.after(delay, self.rotate_slides)

    def update_slide_visibility(self) -> None:
        """Toggles the visibility of time-series axes and frequency-domain axes.

        Raises:
            None.
        """
        if self.current_slide == 1:
            self.ax.set_visible(True)
            self.ax_bar.set_visible(True)
            self.ax_freq.set_visible(False)
        else:
            self.ax.set_visible(False)
            self.ax_bar.set_visible(False)
            self.ax_freq.set_visible(True)
            
        self.load_cached_summary()
        self.fig.canvas.draw_idle()

    def poll_remote_data(self) -> None:
        """Periodically syncs history files from the Raspberry Pi and reloads them."""
        import subprocess
        import threading
        
        def run_sync() -> None:
            try:
                print("Live polling: Syncing telemetry logs from Raspberry Pi...")
                files_to_sync = [
                    "grid_history.csv",
                    "solaredge_history.csv",
                    "chilicon_history.csv",
                    "solaredge_battery_history.csv",
                    "gemini_summary.json"
                ]
                
                # Fetch each key file from Raspberry Pi
                for f in files_to_sync:
                    cmd = ["scp", f"steven@rainforestpi:~/rainforest-emu2-grid-dashboard/{f}", f"./{f}"]
                    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                
                # Request UI update in Tkinter main thread
                self.after(0, self.reload_and_refresh)
            except Exception as e:
                print(f"Error syncing remote data: {e}")
                
        # Run sync in background daemon thread
        threading.Thread(target=run_sync, daemon=True).start()
        
        # Schedule next poll in 10 seconds
        self.after(10000, self.poll_remote_data)

    def reload_and_refresh(self) -> None:
        """Reloads all datasets and updates the Tkinter UI and matplotlib canvas."""
        print("Reloading local data and refreshing canvas...")
        
        self.usage = []
        self.timestamps = []
        self.se_power = []
        self.se_timestamps = []
        self.chilicon_power = []
        self.chilicon_timestamps = []
        
        self.load_history()
        self.load_solaredge_history()
        self.load_chilicon_history()
        self.weather_map = self.fetch_historical_weather()
        
        # Update UI Text labels
        latest_val = self.usage[-1] if self.usage else 0.0
        # Shorter strings are used here to prevent left-side text truncation on narrower layouts.
        status = "Solar Export" if latest_val < 0 else "Grid Import"
        color = EXPORT_COLOR if latest_val < 0 else IMPORT_COLOR
        text = f"{latest_val:.3f} kW | {status}"
        self.status_label.config(text=text, fg=color)
        
        latest_pv = self.se_power[-1] if self.se_power else 0.0
        self.sub_status_label.config(text=f"SolarEdge PV: {latest_pv:.3f} kW")
        
        if not self.chilicon_off:
            latest_ch = self.chilicon_power[-1] if self.chilicon_power else 0.0
            self.chilicon_status_label.config(text=f"Chillicon PV: {latest_ch:.3f} kW")
            
        # Load summary watermark
        self.load_cached_summary()
        
        # Redraw charts
        self.update_chart()

    def fetch_live_weather(self, lat: str = DEFAULT_LAT, lon: str = DEFAULT_LON) -> Dict[str, Optional[float]]:
        """Fetches the live weather (current temp, weather code, cloud cover) from Open-Meteo API.

        Args:
            lat: Latitude of target location.
            lon: Longitude of target location.

        Returns:
            A dictionary containing:
            - "temp": float (current temperature in °C) or None
            - "weather_code": float (WMO code) or None
            - "cloud_cover": float (0-100) or None

        Raises:
            None: All exceptions (e.g. urllib.error.URLError) are caught internally and logged.
        """
        url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&current=temperature_2m,weather_code,cloud_cover&timezone=auto"
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=5) as response:
                res = json.loads(response.read().decode('utf-8'))
                current = res.get("current", {})
                return {
                    "temp": current.get("temperature_2m"),
                    "weather_code": current.get("weather_code"),
                    "cloud_cover": current.get("cloud_cover")
                }
        except Exception as e:
            print(f"Error fetching live weather: {e}")
            return {}

    def load_cached_summary(self) -> None:
        """Loads local weather and sets the clock/weather watermarks and AI summaries."""
        # 1. Update Time/Date Widgets
        if self.timestamps:
            latest_dt = self.timestamps[-1]
            time_str = latest_dt.strftime("%H:%M")
            date_str = latest_dt.strftime("%A, %b %d, %Y")
        else:
            time_str = "N/A"
            date_str = "N/A"
            
        self.time_label.config(text=time_str)
        self.date_label.config(text=date_str)
        
        # 2. Fetch live weather (temp, weather code, cloud cover)
        live_weather = self.fetch_live_weather()
        temp = live_weather.get("temp")
        wcode = live_weather.get("weather_code")
        cloud_cover = live_weather.get("cloud_cover")
        
        # Determine cache file path and load summary
        cache_file = 'gemini_summary.json'
            
        summary = ""
        dft_explanation = ""
        if os.path.exists(cache_file):
            try:
                with open(cache_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    summary = data.get("summary", "").strip()
                    dft_explanation = data.get("dft_explanation", "").strip()
            except Exception as e:
                print(f"Failed to load cache: {e}")
                
        # Update internal summary variables
        if summary:
            self.local_time_text = summary
        if dft_explanation:
            self.local_dft_text = dft_explanation
            
        # Select active summary based on current slide
        active_summary = self.local_time_text if self.current_slide == 1 else self.local_dft_text
        self.summary_label.config(text=active_summary)
        
        # Update matplotlib text watermarks
        self.summary_text_obj.set_text(self.wrap_text(self.local_time_text))
        self.summary_text_obj_freq.set_text(self.wrap_text(self.local_dft_text))
        
        # If live fetch failed, fallback to cache metrics
        if temp is None or wcode is None:
            print("Live weather fetch failed or incomplete; checking cache fallback...")
            if os.path.exists(cache_file):
                try:
                    with open(cache_file, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                        metrics = data.get("metrics", {})
                        if temp is None:
                            temp = metrics.get("temp_max")
                        if cloud_cover is None:
                            cloud_cover = metrics.get("cloud_cover")
                        # Since weather code isn't in metrics, estimate wcode from cloud cover
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
                except Exception as e:
                    print(f"Failed to read cache fallback: {e}")
        
        # 3. Update Weather Widgets
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



    def wrap_text(self, text: str, width: int = 100) -> str:
        # Clean up markdown code block indicators for a cleaner raw text presentation
        text = text.replace("```json", "").replace("```", "")
        # Normalize carriage returns and other line endings to standard newlines
        text = text.replace('\r\n', '\n').replace('\r', '\n')
        paragraphs = text.split('\n\n')
        wrapped_paragraphs = []
        for para in paragraphs:
            lines = para.split('\n')
            is_structured = False
            for line in lines:
                stripped = line.strip()
                if stripped.startswith(('*', '-', '1.', '2.', '3.')) or '   ' in line or '\t' in line:
                    is_structured = True
                    break
                    
            if is_structured:
                wrapped_lines = []
                for line in lines:
                    if len(line) <= width:
                        wrapped_lines.append(line)
                    else:
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
                wrapped_paragraphs.append(textwrap.fill(para, width=width))
                
        return '\n\n'.join(wrapped_paragraphs)

    def _local_interpolate_gaps(self, series: List[Optional[float]]) -> List[float]:
        """Fills missing elements (None) in a list using linear interpolation."""
        n = len(series)
        result = list(series)
        non_none_indices = [i for i, x in enumerate(series) if x is not None]
        if not non_none_indices:
            return [0.0] * n
            
        first_valid_idx = non_none_indices[0]
        last_valid_idx = non_none_indices[-1]
        
        for i in range(first_valid_idx):
            result[i] = series[first_valid_idx]
        for i in range(last_valid_idx + 1, n):
            result[i] = series[last_valid_idx]
            
        for i in range(first_valid_idx + 1, last_valid_idx):
            if result[i] is None:
                prev_idx = i - 1
                while prev_idx >= first_valid_idx and result[prev_idx] is None:
                    prev_idx -= 1
                next_idx = i + 1
                while next_idx <= last_valid_idx and result[next_idx] is None:
                    next_idx += 1
                    
                val_prev = result[prev_idx]
                val_next = result[next_idx]
                ratio = (i - prev_idx) / (next_idx - prev_idx)
                result[i] = val_prev + ratio * (val_next - val_prev)
                
        return [float(x) for x in result]

    def align_and_compute_spectrum(self) -> Tuple[List[float], List[float], List[float], List[float], List[float]]:
        """Aligns historical telemetry on a uniform hourly grid and computes the DTFT spectrum."""
        if not self.timestamps:
            return [], [], [], [], []
            
        min_ts = min(self.timestamps).replace(minute=0, second=0, microsecond=0)
        max_ts = max(self.timestamps).replace(minute=0, second=0, microsecond=0)
        total_hours = int((max_ts - min_ts).total_seconds() / 3600.0) + 1
        
        target_dts = [min_ts + datetime.timedelta(hours=i) for i in range(total_hours)]
        
        # Build raw series with gaps
        grid_map = defaultdict(list)
        for ts, val in zip(self.timestamps, self.usage):
            grid_map[ts.strftime("%Y-%m-%d %H:00")].append(val)
            
        # SolarEdge
        se_map = defaultdict(list)
        for ts, val in zip(self.se_timestamps, self.se_power):
            se_map[ts.strftime("%Y-%m-%d %H:00")].append(val)
            
        # Chillicon
        ch_map = defaultdict(list)
        for ts, val in zip(self.chilicon_timestamps, self.chilicon_power):
            ch_map[ts.strftime("%Y-%m-%d %H:00")].append(val)
            
        grid_raw: List[Optional[float]] = []
        solar_raw: List[Optional[float]] = []
        expected_solar_series: List[float] = []
        
        PEAK_SOLAR_CAPACITY: float = 5.0
        
        for dt in target_dts:
            key = dt.strftime("%Y-%m-%d %H:00")
            g_vals = grid_map[key]
            grid_raw.append(sum(g_vals) / len(g_vals) if g_vals else None)
            
            s_val = 0.0
            se_vals = se_map[key]
            if se_vals:
                s_val += sum(se_vals) / len(se_vals)
            if not self.chilicon_off:
                ch_vals = ch_map[key]
                if ch_vals:
                    s_val += sum(ch_vals) / len(ch_vals)
            
            # If no data is available for both, mark as None to interpolate
            if not se_vals and (self.chilicon_off or not ch_map[key]):
                solar_raw.append(None)
            else:
                solar_raw.append(s_val)
                
            # Model expected solar profile
            date_key = dt.strftime("%Y-%m-%d")
            day_weather = self.weather_map.get(date_key, DEFAULT_WEATHER_FALLBACK)
            cloud_cover = day_weather["cloud_cover"]
            sr_hour = day_weather["sunrise_hour"]
            ss_hour = day_weather["sunset_hour"]
            
            # Decimal hour of day
            h = dt.hour + dt.minute / 60.0
            if sr_hour < h < ss_hour:
                clear_sky = PEAK_SOLAR_CAPACITY * math.sin(math.pi * (h - sr_hour) / (ss_hour - sr_hour))
            else:
                clear_sky = 0.0
                
            modulation = (100.0 - cloud_cover) / 100.0
            expected_solar_series.append(clear_sky * modulation)
                
        grid_series = self._local_interpolate_gaps(grid_raw)
        solar_series = self._local_interpolate_gaps(solar_raw)
        
        # Calculate household consumption (Load = Grid + Solar)
        consumption_series = [g + s for g, s in zip(grid_series, solar_series)]
        
        # Run DTFT spectrum analysis for frequencies 0.1 to 4.0 cycles per day
        freqs = [0.05 + 0.01 * i for i in range(400)]
        
        import snr_analysis
        grid_amp = snr_analysis.compute_dtft_spectrum(grid_series, freqs)
        solar_amp = snr_analysis.compute_dtft_spectrum(solar_series, freqs)
        expected_solar_amp = snr_analysis.compute_dtft_spectrum(expected_solar_series, freqs)
        consumption_amp = snr_analysis.compute_dtft_spectrum(consumption_series, freqs)
            
        return freqs, grid_amp, solar_amp, expected_solar_amp, consumption_amp

    def update_chart(self) -> None:
        """Draws the dynamic line plot and scales the axes."""
        if len(self.usage) > 1:
            x_nums = mdates.date2num(self.timestamps)
            segments = []
            colors = []
            widths = []
            for i in range(len(self.usage) - 1):
                t1, t2 = self.timestamps[i], self.timestamps[i+1]
                # Skip segment connection if there is a gap > 10 minutes (power outage or log halt)
                if (t2 - t1).total_seconds() > 600:
                    continue
                y1, y2 = self.usage[i], self.usage[i+1]
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
            
            # Draw the bar chart on the twin axes using stacked SolarEdge and Chillicon data
            self.ax_bar.clear()
            self.ax_bar.tick_params(colors='#fbbf24')
            self.ax_bar.yaxis.set_label_position('right')
            self.ax_bar.spines['right'].set_color('#fbbf24')
            self.ax_bar.spines['left'].set_color('none')
            self.ax_bar.spines['top'].set_color('none')
            self.ax_bar.spines['bottom'].set_color('none')
            self.ax_bar.set_ylabel('Total Solar PV (kW)', color='#fbbf24', rotation=270, labelpad=15)
            
            end_time = self.timestamps[-1] if self.timestamps else datetime.datetime.now()
            start_time = end_time - datetime.timedelta(hours=24)
            
            # Align both SolarEdge and Chillicon on a regular, forward-filled 10-minute grid
            bar_times = []
            se_heights = []
            ch_heights = []
            
            # Start at start_time rounded down to the nearest 10-minute slot
            grid_start = start_time.replace(minute=(start_time.minute // 10) * 10, second=0, microsecond=0)
            current_slot = grid_start
            
            while current_slot <= end_time:
                bar_times.append(current_slot)
                
                # Find most recent SolarEdge power value <= current_slot and within 30 minutes
                se_val = 0.0
                for ts, p in zip(self.se_timestamps, self.se_power):
                    if ts <= current_slot and current_slot - ts <= datetime.timedelta(minutes=30):
                        se_val = p
                se_heights.append(se_val)
                
                # Find most recent Chillicon power value <= current_slot and within 30 minutes
                ch_val = 0.0
                if not self.chilicon_off:
                    for ts, p in zip(self.chilicon_timestamps, self.chilicon_power):
                        if ts <= current_slot and current_slot - ts <= datetime.timedelta(minutes=30):
                            ch_val = p
                ch_heights.append(ch_val)
                
                current_slot += datetime.timedelta(minutes=10)
            
            if bar_times:
                width_in_days = 10.0 / (24.0 * 60.0) # 10 minutes
                bar_x = mdates.date2num(bar_times)
                # Draw SolarEdge (bottom)
                self.ax_bar.bar(bar_x, se_heights, width=width_in_days, color='#fbbf24', alpha=0.1, zorder=1, edgecolor='none')
                # Draw Chillicon (stacked on top of SolarEdge - bright neon yellow)
                self.ax_bar.bar(bar_x, ch_heights, bottom=se_heights, width=width_in_days, color='#ffff00', alpha=0.15, zorder=1.5, edgecolor='none')
                
                max_power = max([s + c for s, c in zip(se_heights, ch_heights)]) if bar_times else 1.0
                self.ax_bar.set_ylim(0, max_power * 1.1)
            else:
                self.ax_bar.set_ylim(0, 10)
        
        if self.timestamps:
            # Match the rolling 24-hour window ending at the last data point
            end_time = self.timestamps[-1]
            start_time = end_time - datetime.timedelta(hours=24)
            self.ax.set_xlim(start_time, end_time)
            self.ax_bar.set_xlim(start_time, end_time)
        
        if self.usage:
            y_min = min(self.usage)
            y_max = max(self.usage)
            # Increase top padding to leave the top portion of the plot completely free for text watermarks
            y_range = max(y_max - y_min, 1.0)
            y_lim_min = min(0.0, y_min - 0.15 * y_range)
            y_lim_max = max(0.0, y_max + 0.85 * y_range)
            self.ax.set_ylim(y_lim_min, y_lim_max)
            
        # Draw the frequency spectrum on the bottom subplot
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
            import snr_analysis
            snrs = snr_analysis.analyze_spectra_snr(freqs, grid_amp, solar_amp, consumption_amp)
            
            grid_label = f"Net Grid (24h SNR: {snrs['grid_24h_snr_db']:.1f} dB, 12h: {snrs['grid_12h_snr_db']:.1f} dB)"
            solar_label = f"Solar PV (Actual) (24h SNR: {snrs['solar_24h_snr_db']:.1f} dB)"
            consumption_label = f"Household Load (24h SNR: {snrs['consumption_24h_snr_db']:.1f} dB, 12h: {snrs['consumption_12h_snr_db']:.1f} dB)"

            self.ax_freq.plot(freqs, grid_amp, color=IMPORT_COLOR, label=grid_label, linewidth=1.5)
            self.ax_freq.plot(freqs, solar_amp, color='#fbbf24', label=solar_label, linewidth=1.5)
            self.ax_freq.plot(freqs, expected_solar_amp, color=EXPECTED_SOLAR_COLOR, linestyle='--', label='Expected Solar (Weather Modulated)', linewidth=1.3)
            self.ax_freq.plot(freqs, consumption_amp, color=EXPECTED_SOLAR_COLOR if 'CONSUMPTION_COLOR' not in globals() else CONSUMPTION_COLOR, label=consumption_label, linewidth=1.5)
            # Highlight physical rhythms (diurnal = 1.0, semi-diurnal = 2.0)
            self.ax_freq.axvline(1.0, color='deepskyblue', linestyle='--', alpha=0.5, label='24h Diurnal')
            self.ax_freq.axvline(2.0, color='violet', linestyle='--', alpha=0.5, label='12h Semi-Diurnal')
            self.ax_freq.set_xlim(0.1, 4.0)

            # Increase top padding to leave the top portion of the plot free for text watermarks
            max_amp = max(max(grid_amp), max(solar_amp), max(expected_solar_amp), max(consumption_amp)) if grid_amp else 1.0
            self.ax_freq.set_ylim(0, max_amp * 1.85)

            self.ax_freq.grid(color='gray', linestyle=':', alpha=0.3)
            self.ax_freq.legend(facecolor='black', edgecolor='white', labelcolor='white', fontsize=8)

        # Recreate the text watermark on ax_freq since it was cleared
        self.summary_text_obj_freq = self.ax_freq.text(
            0.02, 0.95, self.wrap_text(self.local_dft_text),
            transform=self.ax_freq.transAxes,
            ha='left', va='top',
            fontsize=SUMMARY_FONT_SIZE,
            color=SUMMARY_COLOR,
            alpha=SUMMARY_ALPHA,
            fontfamily='monospace',
            weight='bold',
            zorder=10
        )
        # Ensure twin axis x-limits are perfectly synchronized with the main axis
        self.ax_bar.set_xlim(self.ax.get_xlim())
            
        self.fig.canvas.draw()

    def save_screenshot(self) -> None:
        """Programmatically captures the TK window and saves it to the preview filename."""
        self.attributes('-topmost', True)
        self.lift()
        self.focus_force()
        self.update()
        
        # Give the OS window manager a brief moment to bring the window to the front
        import time
        time.sleep(0.5)
        
        # Retrieve coordinates relative to the screen
        x = self.winfo_rootx()
        y = self.winfo_rooty()
        w = self.winfo_width()
        h = self.winfo_height()
        
        import platform
        import subprocess
        
        if platform.system() == "Darwin":
            try:
                # Use macOS's built-in screencapture tool which handles Retina scaling and coordinates cleanly.
                # Format: screencapture -o -t jpg -R x,y,w,h output.jpeg
                cmd = ["screencapture", "-o", "-t", "jpg", "-R", f"{x},{y},{w},{h}", self.preview_filename]
                subprocess.run(cmd, check=True)
                print(f"Successfully captured and saved {self.preview_filename} via macOS screencapture!")
            except Exception as e:
                print(f"macOS screencapture failed: {e}. Trying PIL fallback...")
                self._pil_fallback(x, y, w, h)
        else:
            self._pil_fallback(x, y, w, h)
            
        if "--close" in sys.argv:
            print("Auto-closing window as requested by --close option.")
            self.destroy()

    def _pil_fallback(self, x: int, y: int, w: int, h: int) -> None:
        from PIL import ImageGrab
        try:
            img = ImageGrab.grab(bbox=(x, y, x + w, y + h))
            img.convert('RGB').save(self.preview_filename, 'JPEG', quality=95)
            print(f"Successfully captured and saved {self.preview_filename} via PIL ImageGrab!")
        except Exception as e:
            print(f"Error capturing screenshot via PIL: {e}. Trying direct Matplotlib savefig fallback...")
            try:
                # Fallback to saving the Matplotlib figure directly to file (bypasses screen capture permission checks)
                self.fig.savefig(self.preview_filename, facecolor='black', edgecolor='none', bbox_inches='tight')
                print(f"Successfully saved {self.preview_filename} via direct Matplotlib savefig fallback!")
            except Exception as save_err:
                print(f"Failed to save Matplotlib figure directly: {save_err}")

if __name__ == "__main__":
    app = OfflineViewer()
    app.mainloop()
