import tkinter as tk
import csv
import os
import json
import datetime
import textwrap
import matplotlib.dates as mdates
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.collections import LineCollection
from typing import List, Any

# Match settings from main dashboard.py
SUMMARY_FONT_SIZE: int = 12
SUMMARY_ALPHA: float = 0.85
SUMMARY_COLOR: str = 'deepskyblue'
IMPORT_COLOR: str = '#f43f5e'  # Modern rose red
EXPORT_COLOR: str = '#00ff00'  # Classic neon green

class OfflineViewer(tk.Tk):
    """Offline viewer that renders the historical grid telemetry for a screenshot."""

    def __init__(self) -> None:
        super().__init__()
        self.title("Grid Monitor Preview")
        self.configure(bg='black')
        
        # Configure windowed fullscreen/maximized size for easy screenshotting
        self.geometry("1024x768")
        
        self.bind("<Escape>", lambda e: self.destroy())
        self.bind("<Button-1>", lambda e: self.destroy())

        self.usage: List[float] = []
        self.timestamps: List[datetime.datetime] = []
        
        # Load local history file copied from the Pi
        self.load_history()

        # UI Text label configuration
        latest_val = self.usage[-1] if self.usage else 0.0
        status = "Exporting (Solar)" if latest_val < 0 else "Importing (Grid)"
        color = EXPORT_COLOR if latest_val < 0 else IMPORT_COLOR
        text = f"{latest_val:.3f} kW | {status}"

        self.status_label: tk.Label = tk.Label(
            self, text=text, font=('Helvetica', 36, 'bold'), bg='black', fg=color
        )
        self.status_label.pack(pady=5)

        # Main container frame to hold chart and insights side-by-side.
        self.main_container: tk.Frame = tk.Frame(self, bg='black')
        self.main_container.pack(fill=tk.BOTH, expand=True)

        # Left side: Chart frame.
        self.chart_frame: tk.Frame = tk.Frame(self.main_container, bg='black')
        self.chart_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # Right side: Insights frame with fixed width.
        self.insights_frame: tk.Frame = tk.Frame(self.main_container, bg='#0f172a', width=350, padx=15, pady=15)
        self.insights_frame.pack_propagate(False)
        self.insights_frame.pack(side=tk.RIGHT, fill=tk.Y, expand=False)

        # Title inside insights frame
        self.insights_title: tk.Label = tk.Label(
            self.insights_frame,
            text="GEMINI GRID INSIGHTS",
            font=('Helvetica', 12, 'bold'),
            bg='#0f172a',
            fg='#38bdf8'
        )
        self.insights_title.pack(anchor='w', pady=(0, 10))

        # Divider line
        divider: tk.Frame = tk.Frame(self.insights_frame, bg='#1e293b', height=2)
        divider.pack(fill=tk.X, pady=(0, 15))

        # Text container for the insights
        self.insights_text: tk.Text = tk.Text(
            self.insights_frame,
            bg='#0f172a',
            fg='#e2e8f0',
            font=('Helvetica', 11),
            wrap=tk.WORD,
            bd=0,
            highlightthickness=0,
            padx=0,
            pady=0
        )
        self.insights_text.pack(fill=tk.BOTH, expand=True)
        self.insights_text.config(state=tk.DISABLED)

        # Matplotlib figure setup
        self.fig: Figure = Figure(figsize=(5, 3), dpi=100, facecolor='black')
        # Adjust margins so that labels and ticks fit comfortably on displays.
        self.fig.subplots_adjust(left=0.10, right=0.95, top=0.95, bottom=0.15)
        
        self.ax: Any = self.fig.add_subplot(111)
        self.ax.set_facecolor('black')
        self.ax.tick_params(colors='white')
        self.ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
        self.fig.autofmt_xdate()
        self.ax.spines['bottom'].set_color('white')
        self.ax.spines['left'].set_color('white')
        self.ax.spines['top'].set_color('black')
        self.ax.spines['right'].set_color('black')
        
        # Dotted horizontal line at 0 kW
        self.ax.axhline(0, color='gray', linestyle='--') 
        
        # LineCollection for dynamic segment styling
        self.lc: LineCollection = LineCollection([], linewidths=1.8, zorder=2)
        self.ax.add_collection(self.lc)
        
        # Integrate Matplotlib canvas inside the chart frame.
        self.canvas: FigureCanvasTkAgg = FigureCanvasTkAgg(self.fig, master=self.chart_frame)
        self.canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)

        # Load cached summary and draw the plot
        self.load_cached_summary()
        self.update_chart()

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

    def load_cached_summary(self) -> None:
        """Loads local gemini_summary.json and sets the watermark."""
        cache_file = 'gemini_summary.json'
        if not os.path.exists(cache_file):
            print("No local gemini_summary.json found.")
            return
            
        try:
            with open(cache_file, 'r') as f:
                data = json.load(f)
                summary = data.get("summary")
                if summary:
                    self.insights_text.config(state=tk.NORMAL)
                    self.insights_text.delete("1.0", tk.END)
                    self.insights_text.insert(tk.END, summary.strip())
                    self.insights_text.config(state=tk.DISABLED)
                    print("Loaded cached Gemini summary.")
        except Exception as e:
            print(f"Failed to load cache: {e}")

    def wrap_text(self, text: str, width: int = 80) -> str:
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

    def update_chart(self) -> None:
        """Draws the dynamic line plot and scales the axes."""
        if len(self.usage) > 1:
            x_nums = mdates.date2num(self.timestamps)
            segments = []
            colors = []
            widths = []
            for i in range(len(self.usage) - 1):
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
        
        if self.timestamps:
            # Match the rolling 24-hour window ending at the last data point
            end_time = self.timestamps[-1]
            start_time = end_time - datetime.timedelta(hours=24)
            self.ax.set_xlim(start_time, end_time)
        
        if self.usage:
            y_min = min(self.usage)
            y_max = max(self.usage)
            padding = max(abs(y_max - y_min) * 0.2, 0.5)
            self.ax.set_ylim(min(0, y_min - padding), max(0, y_max + padding))
            
        self.fig.canvas.draw()

if __name__ == "__main__":
    app = OfflineViewer()
    app.mainloop()
