import tkinter as tk
import serial
import xml.etree.ElementTree as ET
import time
import threading
import logging
import datetime
import csv
import os
import json
import signal
import textwrap
import matplotlib.dates as mdates
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.collections import LineCollection
from typing import List, Any, Optional

# Setup logging to keep track of serial port communication and errors.
logging.basicConfig(
    filename='/home/steven/dashboard.log',
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s'
)

# Try to import Google GenAI library. If not installed, log a warning but run GUI without summaries.
GENAI_AVAILABLE = False
try:
    from google import genai
    GENAI_AVAILABLE = True
except ImportError:
    logging.warning("google-genai package is not installed. Gemini background summaries will be disabled.")

# Rainforest EMU-2 hardware communication settings
PORT: str = '/dev/ttyACM0'
BAUD: int = 115200

# Gemini Summary Display Settings
SUMMARY_FONT_SIZE: int = 12
SUMMARY_ALPHA: float = 0.85
SUMMARY_COLOR: str = 'deepskyblue'

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
    """

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
        
        # 5760 points at ~15s intervals equals exactly 24 hours of data.
        self.max_points: int = 5760 
        self.history_file: str = '/home/steven/grid_history.csv'
        
        # Reload historical data from CSV so the graph survives power interruptions.
        self.load_history()

        # UI Text label configuration.
        self.status_label: tk.Label = tk.Label(
            self, text="Waiting for data...", font=('Helvetica', 36, 'bold'), bg='black', fg='white'
        )
        self.status_label.pack(pady=5)

        # Matplotlib figure setup.
        self.fig: Figure = Figure(figsize=(5, 3), dpi=100, facecolor='black')
        # Adjust margins so that labels and ticks fit comfortably on fullscreen displays.
        self.fig.subplots_adjust(left=0.15, right=0.95, top=0.95, bottom=0.15)
        
        self.ax: Any = self.fig.add_subplot(111)
        self.ax.set_facecolor('black')
        self.ax.tick_params(colors='white')
        self.ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
        self.fig.autofmt_xdate()
        self.ax.spines['bottom'].set_color('white')
        self.ax.spines['left'].set_color('white')
        self.ax.spines['top'].set_color('black')
        self.ax.spines['right'].set_color('black')
        
        # Dotted horizontal line at 0 kW to distinguish importing vs exporting power.
        self.ax.axhline(0, color='gray', linestyle='--') 
        
        # LineCollection to draw a plot line with dynamic colors and sleeker thickness.
        self.lc: LineCollection = LineCollection([], linewidths=1.8, zorder=2)
        self.ax.add_collection(self.lc)
        
        # Text object to display Gemini-generated summary in the background of the axes.
        # Uses axes coordinates (transAxes) to place the text in the top-left corner.
        self.summary_text_obj: Any = self.ax.text(
            0.02, 0.95, "",
            transform=self.ax.transAxes,
            ha='left', va='top',
            fontsize=SUMMARY_FONT_SIZE,
            color=SUMMARY_COLOR,
            alpha=SUMMARY_ALPHA,
            fontfamily='monospace',
            weight='bold',
            zorder=0.1
        )
        
        # Integrate Matplotlib canvas with the Tkinter window.
        self.canvas: FigureCanvasTkAgg = FigureCanvasTkAgg(self.fig, master=self)
        self.canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)

        # Summary cache settings to prevent redundant API queries on restart
        self.summary_cache_file: str = '/home/steven/gemini_summary.json'
        self.last_summary_time: Optional[datetime.datetime] = None
        
        # Load cached summary on startup if it exists and is fresh
        self.load_cached_summary()

        # Initialize serial reference to None before thread runs.
        self.ser: Optional[serial.Serial] = None

        # Threading settings for serial interface monitoring.
        self.running: bool = True
        self.thread: threading.Thread = threading.Thread(target=self.read_serial, daemon=True)
        self.thread.start()

        # Start background thread to fetch Gemini grid summaries every 30 minutes.
        self.start_summary_loop()

        # Register OS signal handlers for clean teardown on termination signals (SIGINT, SIGTERM)
        signal.signal(signal.SIGINT, self.handle_signal)
        signal.signal(signal.SIGTERM, self.handle_signal)

        # Start periodic check of signals to ensure responsiveness in Tkinter mainloop
        self.check_signals()

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
                reader = csv.reader(f)
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
                                self.timestamps.append(ts)
                                self.usage.append(float(val_str))
                        except Exception as parse_err:
                            logging.warning(f"Skipping corrupted history row: {row} - Error: {parse_err}")
            logging.info(f"Loaded {len(self.usage)} historical points.")
        except Exception as e:
            logging.error(f"Failed to read history file: {e}")

    def read_serial(self) -> None:
        """Performs long-polling of the EMU-2 USB serial port in a background thread.

        Attempts to open the serial port and read incoming data. It splits incoming
        buffer streams into individual `<InstantaneousDemand>` XML segments and passes
        them to the parser.
        """
        logging.info("Starting background thread to read serial port.")
        try:
            self.ser = serial.Serial(PORT, BAUD, timeout=1)
            logging.info(f"Successfully opened {PORT} at {BAUD} baud.")
        except Exception as e:
            err_msg: str = f"Port Error: {e}"
            logging.error(err_msg)
            self.update_ui_text(err_msg)
            return

        buffer: str = ""
        try:
            while self.running:
                try:
                    if self.ser and self.ser.is_open:
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
                except Exception as e:
                    # Avoid logging spam if the thread is shutting down.
                    if self.running:
                        logging.error(f"Error reading serial data: {e}")
                time.sleep(0.1)
        finally:
            if self.ser:
                try:
                    if self.ser.is_open:
                        self.ser.close()
                    logging.info("Serial connection closed cleanly in read_serial finally block.")
                except Exception as e:
                    logging.error(f"Failed to close serial port in background thread: {e}")

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
                status: str = "Exporting (Solar)" if actual_kw < 0 else "Importing (Grid)"
                color: str = "#00ff00" if actual_kw < 0 else "#ff4444"
                text: str = f"{actual_kw:.3f} kW | {status}"
                
                # Safely execute GUI modifications on the main thread using after().
                self.after(0, self.update_chart, text, color)
        except Exception as e:
            logging.error(f"Error parsing XML chunk: {e}")

    def update_ui_text(self, text: str) -> None:
        """Thread-safely updates the text of the status label widget.

        Args:
            text: The message string to display.
        """
        self.after(0, lambda: self.status_label.config(text=text))

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
        
        # Build segments and dynamically color them: red for importing (>0 kW), green for exporting (<0 kW).
        if len(self.usage) > 1:
            x_nums = mdates.date2num(self.timestamps)
            segments = []
            colors = []
            for i in range(len(self.usage) - 1):
                y1, y2 = self.usage[i], self.usage[i+1]
                segments.append(((x_nums[i], y1), (x_nums[i+1], y2)))
                avg_y = (y1 + y2) / 2.0
                colors.append("#ff4444" if avg_y > 0 else "#00ff00")
            self.lc.set_segments(segments)
            self.lc.set_colors(colors)
        else:
            self.lc.set_segments([])
        
        # Rolling 24-hour X-axis where the newest data is always on the far right.
        now: datetime.datetime = datetime.datetime.now()
        start_time: datetime.datetime = now - datetime.timedelta(hours=24)
        self.ax.set_xlim(start_time, now)
        
        # Dynamically scale Y-axis with some margin above and below minimum/maximum points.
        if self.usage:
            y_min: float = min(self.usage)
            y_max: float = max(self.usage)
            padding: float = max(abs(y_max - y_min) * 0.2, 0.5)
            self.ax.set_ylim(min(0, y_min - padding), max(0, y_max + padding))
            
        # Efficiently queue a redraw request on the matplotlib GUI canvas.
        self.fig.canvas.draw_idle()

    def start_summary_loop(self) -> None:
        """Spawns the background thread to fetch Gemini summaries periodically."""
        self.summary_thread: threading.Thread = threading.Thread(target=self.summary_loop, daemon=True)
        self.summary_thread.start()

    def summary_loop(self) -> None:
        """Periodically fetches grid usage summaries from Gemini every 30 minutes."""
        # Wait 10 seconds for initial startup and history load to settle.
        time.sleep(10)
        while self.running:
            try:
                self.fetch_gemini_summary()
            except Exception as e:
                logging.error(f"Failed in summary loop: {e}")
            
            # Sleep for 30 minutes (1800 seconds), checking self.running every 10 seconds.
            for _ in range(180):
                if not self.running:
                    break
                time.sleep(10)

    def load_cached_summary(self) -> None:
        """Loads a previously cached Gemini summary from disk if it is fresh."""
        if not os.path.exists(self.summary_cache_file):
            return
            
        try:
            with open(self.summary_cache_file, 'r') as f:
                data = json.load(f)
                ts_str = data.get("timestamp")
                summary = data.get("summary")
                
                if ts_str and summary:
                    ts = datetime.datetime.fromisoformat(ts_str)
                    now = datetime.datetime.now()
                    # If it's less than 30 minutes old, load it immediately
                    if now - ts < datetime.timedelta(minutes=30):
                        self.last_summary_time = ts
                        self.summary_text_obj.set_text(self.wrap_text(summary.strip()))
                        logging.info(f"Loaded fresh cached Gemini summary from {ts_str}.")
                        self.fig.canvas.draw_idle()
                    else:
                        logging.info("Cached Gemini summary exists but is older than 30 minutes.")
        except Exception as e:
            logging.error(f"Failed to load cached Gemini summary: {e}")

    def fetch_gemini_summary(self) -> None:
        """Fetches a summary of the current day's data from Gemini.

        Prepares the usage data as a compact CSV string, calls the Gemini model via
        Vertex AI client, and updates the background dashboard visualization.
        """
        if not GENAI_AVAILABLE:
            logging.warning("google-genai package not imported; skipping Gemini summary.")
            return

        # Ensure we have data points to summarize
        if not self.usage or len(self.usage) < 10:
            logging.info("Not enough data to generate Gemini summary.")
            return

        # Check if we already have a fresh summary (either from startup load or previous loop)
        now = datetime.datetime.now()
        if self.last_summary_time and now - self.last_summary_time < datetime.timedelta(minutes=30):
            logging.info("Skipping Gemini call; local cached summary is still fresh.")
            return

        try:
            logging.info("Initiating Gemini API call to fetch grid summary...")
            # 1. Format the data compactly (taking every 4th point / ~1 min intervals)
            # Include both year-month-day and hour-minute to avoid model date hallucinations.
            lines = []
            for i in range(0, len(self.usage), 4):
                ts = self.timestamps[i].strftime("%Y-%m-%d %H:%M")
                val = f"{self.usage[i]:.3f}"
                lines.append(f"{ts},{val}")
            csv_data = "\n".join(lines)

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
                "/home/steven/Auth/service_account.json",
                "/home/steven/auth/service_account.json"
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

            from google import genai

            # 5. Initialize client based on available auth method
            model_name = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
            if api_key:
                logging.info("Initializing GenAI client using developer API key.")
                client = genai.Client(api_key=api_key)
            else:
                logging.info("Initializing GenAI client for Vertex AI.")
                project_id = os.environ.get("GOOGLE_CLOUD_PROJECT", "mutua-477100")
                location = os.environ.get("GOOGLE_CLOUD_LOCATION", "global")
                client = genai.Client(
                    vertexai=True,
                    project=project_id,
                    location=location
                )

            # Load the prompt template from external txt file dynamically at runtime.
            prompt_path: str = os.path.join(os.path.dirname(os.path.abspath(__file__)), "gemini_prompt.txt")
            if not os.path.exists(prompt_path):
                prompt_path = "/home/steven/gemini_prompt.txt"
                
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
            try:
                # Support both {current_date_time} and {last_data_time} placeholders in the template
                prompt: str = prompt_template.format(
                    csv_data=csv_data,
                    current_date_time=current_dt_str,
                    last_data_time=last_dt_str
                )
            except KeyError as ke:
                logging.error(f"Failed to format prompt template due to missing placeholder: {ke}")
                return

            response = client.models.generate_content(
                model=model_name,
                contents=prompt,
            )

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

    def wrap_text(self, text: str, width: int = 80) -> str:
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
        """Updates the background summary text on the main thread.

        Args:
            text: The new summary text block to render in the background.
        """
        wrapped_text = self.wrap_text(text)
        self.summary_text_obj.set_text(wrapped_text)
        self.fig.canvas.draw_idle()

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
