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

# Setup logging
logging.basicConfig(
    filename='/home/steven/dashboard.log',
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s'
)

# Settings
PORT = '/dev/ttyACM0'
BAUD = 115200

class GridDashboard(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("EMU-2 Grid Monitor")
        self.attributes("-fullscreen", True)
        self.configure(bg='black')
        
        # Press Escape or click to close (helpful for testing)
        self.bind("<Escape>", lambda e: self.destroy())
        self.bind("<Button-1>", lambda e: self.destroy())

        # Data arrays
        self.usage = []
        self.timestamps = []
        self.max_points = 5760 # Keep last ~24 hours of data (at ~15s interval)
        self.history_file = '/home/steven/grid_history.csv'
        self.load_history()

        # Setup UI
        self.status_label = tk.Label(self, text="Waiting for data...", font=('Helvetica', 36, 'bold'), bg='black', fg='white')
        self.status_label.pack(pady=5)

        # Plot setup
        self.fig = Figure(figsize=(5, 3), dpi=100, facecolor='black')
        self.fig.subplots_adjust(left=0.15, right=0.95, top=0.95, bottom=0.15)
        self.ax = self.fig.add_subplot(111)
        self.ax.set_facecolor('black')
        self.ax.tick_params(colors='white')
        self.ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
        self.fig.autofmt_xdate()
        self.ax.spines['bottom'].set_color('white')
        self.ax.spines['left'].set_color('white')
        self.ax.spines['top'].set_color('black')
        self.ax.spines['right'].set_color('black')
        self.ax.axhline(0, color='gray', linestyle='--') # 0 line
        
        self.line, = self.ax.plot([], [], color='#00ff00', linewidth=3)
        
        self.canvas = FigureCanvasTkAgg(self.fig, master=self)
        self.canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)

        # Start background thread to read serial
        self.running = True
        self.thread = threading.Thread(target=self.read_serial, daemon=True)
        self.thread.start()

    def hex_to_signed_int(self, hex_str, bits=32):
        val = int(hex_str, 16)
        if (val & (1 << (bits - 1))) != 0:
            val = val - (1 << bits)
        return val

    def load_history(self):
        if not os.path.exists(self.history_file):
            return
            
        logging.info("Loading history from CSV...")
        now = datetime.datetime.now()
        cutoff = now - datetime.timedelta(days=1)
        
        try:
            with open(self.history_file, 'r') as f:
                reader = csv.reader(f)
                for row in reader:
                    if len(row) == 2:
                        ts = datetime.datetime.fromisoformat(row[0])
                        if ts > cutoff:
                            self.timestamps.append(ts)
                            self.usage.append(float(row[1]))
            logging.info(f"Loaded {len(self.usage)} historical points.")
        except Exception as e:
            logging.error(f"Failed to load history: {e}")

    def read_serial(self):
        logging.info("Starting background thread to read serial port.")
        try:
            ser = serial.Serial(PORT, BAUD, timeout=1)
            logging.info(f"Successfully opened {PORT} at {BAUD} baud.")
        except Exception as e:
            err_msg = f"Port Error: {e}"
            logging.error(err_msg)
            self.update_ui_text(err_msg)
            return

        buffer = ""
        while self.running:
            try:
                data = ser.read(ser.in_waiting or 1)
                if data:
                    buffer += data.decode('utf-8', errors='ignore')
                    
                    while '<InstantaneousDemand>' in buffer and '</InstantaneousDemand>' in buffer:
                        start = buffer.find('<InstantaneousDemand>')
                        end = buffer.find('</InstantaneousDemand>') + len('</InstantaneousDemand>')
                        
                        chunk = buffer[start:end]
                        self.process_chunk(chunk)
                        buffer = buffer[end:]
            except Exception as e:
                logging.error(f"Error reading serial data: {e}")
            time.sleep(0.1)

    def process_chunk(self, xml_data):
        try:
            root = ET.fromstring(xml_data)
            if root.tag == 'InstantaneousDemand':
                demand = self.hex_to_signed_int(root.find('Demand').text)
                multiplier = int(root.find('Multiplier').text, 16)
                divisor = int(root.find('Divisor').text, 16)
                
                if divisor == 0:
                    logging.warning("Received Divisor of 0, skipping calculation.")
                    return
                actual_kw = (demand * multiplier) / divisor
                logging.info(f"Parsed Demand: {actual_kw:.3f} kW")
                
                # Update data arrays
                now_ts = datetime.datetime.now()
                self.usage.append(actual_kw)
                self.timestamps.append(now_ts)
                if len(self.usage) > self.max_points:
                    self.usage.pop(0)
                    self.timestamps.pop(0)
                    
                # Append to CSV
                try:
                    with open(self.history_file, 'a') as f:
                        writer = csv.writer(f)
                        writer.writerow([now_ts.isoformat(), f"{actual_kw:.3f}"])
                except Exception:
                    pass
                
                # Update UI safely in main thread
                status = "Exporting (Solar)" if actual_kw < 0 else "Importing (Grid)"
                color = "#00ff00" if actual_kw < 0 else "#ff4444"
                text = f"{actual_kw:.3f} kW | {status}"
                self.after(0, self.update_chart, text, color)
        except Exception:
            pass

    def update_ui_text(self, text):
        self.after(0, lambda: self.status_label.config(text=text))

    def update_chart(self, label_text, color):
        self.status_label.config(text=label_text, fg=color)
        
        self.line.set_ydata(self.usage)
        self.line.set_xdata(self.timestamps)
        self.line.set_color(color)
        
        # Lock X-axis to current day (Midnight to Midnight)
        now = datetime.datetime.now()
        start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end_of_day = start_of_day + datetime.timedelta(days=1)
        self.ax.set_xlim(start_of_day, end_of_day)
        
        if self.usage:
            y_min, y_max = min(self.usage), max(self.usage)
            padding = max(abs(y_max - y_min) * 0.2, 0.5)
            self.ax.set_ylim(min(0, y_min - padding), max(0, y_max + padding))
            
        self.fig.canvas.draw_idle()

if __name__ == "__main__":
    app = GridDashboard()
    app.mainloop()
