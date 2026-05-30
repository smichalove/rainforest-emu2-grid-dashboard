import json
import time
import os
import datetime
import google.genai as genai
from google.cloud import storage

PROJECT_ID = "mutua-477100"
LOCATION = "global"
BUCKET_NAME = "mutua-477100-batch-images"
RESULTS_FILE = "/Users/treven/Documents/rainforest-emu2-grid-dashboard/emulation_results.txt"
JOBS_FILE = "/Users/treven/Documents/rainforest-emu2-grid-dashboard/emulated_jobs.json"
SA_PATH = "/Users/treven/Documents/rainforest-emu2-grid-dashboard/Auth/service_account.json"

def main():
    if not os.path.exists(JOBS_FILE):
        print("Job list file not found!")
        return

    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = SA_PATH
    client = genai.Client(vertexai=True, project=PROJECT_ID, location=LOCATION)
    
    with open(JOBS_FILE, "r") as f:
        job_ids = json.load(f)
        
    start_time = datetime.datetime.now()
    
    with open(RESULTS_FILE, "w") as f:
        f.write(f"=== Emulation Polling Started at {start_time.strftime('%H:%M:%S')} ===\n")
    
    while True:
        try:
            states = []
            all_terminal = True
            
            for idx, job_name in enumerate(job_ids):
                job = client.batches.get(name=job_name)
                state_str = str(job.state)
                states.append(state_str)
                if "SUCCEEDED" not in state_str and "FAILED" not in state_str:
                    all_terminal = False
                    
            now_str = datetime.datetime.now().strftime("%H:%M:%S")
            log_line = f"[{now_str}] Checked {len(job_ids)} jobs. States: {', '.join([s.split('.')[-1] for s in states])}\n"
            
            with open(RESULTS_FILE, "a") as f:
                f.write(log_line)
                
            if all_terminal:
                elapsed = datetime.datetime.now() - start_time
                with open(RESULTS_FILE, "a") as f:
                    f.write(f"\n🎉 SUCCESS: All jobs reached terminal states in {elapsed}!\n")
                    f.write(f"Results are available in GCS: gs://{BUCKET_NAME}/dashboard_emulation_output/\n")
                break
                
        except Exception as e:
            with open(RESULTS_FILE, "a") as f:
                f.write(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] Error: {e}\n")
                
        time.sleep(120) # Poll every 2 minutes

if __name__ == "__main__":
    main()
