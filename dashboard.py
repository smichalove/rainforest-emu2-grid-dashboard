import tkinter as tk
import serial
import xml.etree.ElementTree as ET
import time
import threading
import logging
import datetime
import csv
import os
import matplotlib.dates as mdates
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from typing import List, Any, Optional

# Setup logging to keep track of serial port communication and errors.
logging.basicConfig(
    filename='/home/steven/dashboard.log',
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s'
)

# Rainforest EMU-2 hardware communication settings
PORT: str = '/dev/ttyACM0'
BAUD: int = 115200

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
        line (Any): Matplotlib Line2D plot element.
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
        
        self.line, = self.ax.plot([], [], color='#00ff00', linewidth=3)
        
        # Integrate Matplotlib canvas with the Tkinter window.
        self.canvas: FigureCanvasTkAgg = FigureCanvasTkAgg(self.fig, master=self)
        self.canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)

        # Threading settings for serial interface monitoring.
        self.running: bool = True
        self.thread: threading.Thread = threading.Thread(target=self.read_serial, daemon=True)
        self.thread.start()

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
                        ts: datetime.datetime = datetime.datetime.fromisoformat(row[0])
                        if ts > cutoff:
                            self.timestamps.append(ts)
                            self.usage.append(float(row[1]))
            logging.info(f"Loaded {len(self.usage)} historical points.")
        except Exception as e:
            logging.error(f"Failed to load history: {e}")

    def read_serial(self) -> None:
        """Performs long-polling of the EMU-2 USB serial port in a background thread.

        Attempts to open the serial port and read incoming data. It splits incoming
        buffer streams into individual `<InstantaneousDemand>` XML segments and passes
        them to the parser.
        
        Raises:
            serial.SerialException: Logged internally if the serial port cannot be opened.
        """
        logging.info("Starting background thread to read serial port.")
        try:
            ser: serial.Serial = serial.Serial(PORT, BAUD, timeout=1)
            logging.info(f"Successfully opened {PORT} at {BAUD} baud.")
        except Exception as e:
            err_msg: str = f"Port Error: {e}"
            logging.error(err_msg)
            self.update_ui_text(err_msg)
            return

        buffer: str = ""
        while self.running:
            try:
                # Read waiting data or block for 1 byte if empty.
                data: bytes = ser.read(ser.in_waiting or 1)
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
                logging.error(f"Error reading serial data: {e}")
            time.sleep(0.1)

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

        Adjusts the chart's X-axis range to lock between midnight and midnight of 
        the current day, dynamically recalculates the Y-axis scale with padding,
        and requests the matplotlib canvas to redraw.

        Args:
            label_text: The updated status text displaying kW usage and state.
            color: The color (hex or standard name) to style the label and line.
        """
        self.status_label.config(text=label_text, fg=color)
        
        self.line.set_ydata(self.usage)
        self.line.set_xdata(self.timestamps)
        self.line.set_color(color)
        
        # Enforce static midnight-to-midnight X-axis for a fixed 24-hour visual trend.
        now: datetime.datetime = datetime.datetime.now()
        start_of_day: datetime.datetime = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end_of_day: datetime.datetime = start_of_day + datetime.timedelta(days=1)
        self.ax.set_xlim(start_of_day, end_of_day)
        
        # Dynamically scale Y-axis with some margin above and below minimum/maximum points.
        if self.usage:
            y_min: float = min(self.usage)
            y_max: float = max(self.usage)
            padding: float = max(abs(y_max - y_min) * 0.2, 0.5)
            self.ax.set_ylim(min(0, y_min - padding), max(0, y_max + padding))
            
        # Efficiently queue a redraw request on the matplotlib GUI canvas.
        self.fig.canvas.draw_idle()

if __name__ == "__main__":
    app = GridDashboard()
    app.mainloop()
