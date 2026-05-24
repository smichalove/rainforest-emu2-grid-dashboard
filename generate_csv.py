import re
import csv
import datetime

log_file = '/home/steven/dashboard.log'
csv_file = '/home/steven/grid_history.csv'

pattern = re.compile(r'^(\d{4}-\d{2}-\d{2})\s+(\d{2}:\d{2}:\d{2}),\d+\s+\[INFO\]\s+Parsed\s+Demand:\s+([-0-9.]+)\s+kW')

data = []
try:
    with open(log_file, 'r') as f:
        for line in f:
            match = pattern.search(line)
            if match:
                date_str = match.group(1)
                time_str = match.group(2)
                kw_str = match.group(3)
                
                # Combine to ISO format
                iso_ts = f"{date_str}T{time_str}"
                data.append([iso_ts, kw_str])

    # Append to CSV
    with open(csv_file, 'a') as f:
        writer = csv.writer(f)
        for row in data:
            writer.writerow(row)
            
    print(f"Successfully recovered {len(data)} historical data points from logs!")
except Exception as e:
    print(f"Error: {e}")
