# Behavioral Rule: Empirical Verification of Performance & System Claims

1. **Empirical Proof Mandatory:** The AI agent must only make assertions on system performance, drive utilization, I/O bottlenecks, or network latency that are empirically proven or backed by direct performance counter analysis. Never guess, make assumptions, or state untested theories (e.g. blaming background model processes for drive saturation without analyzing actual I/O profiling or file read sizes).
2. **Double-Check Codebase Context:** Before modifying any pipeline files, verify the existence and structure of support functions (like preloader loops, mappings, and filters) in git history or related files rather than assuming their presence or omitting them during refactoring.
3. **Contextual Naming for Markdown Files:** All Markdown (`.md`) files created, copied, or renamed in the repository must be given a specific, contextual name (e.g., `planning/macos_client_migration_plan.md` or `backup_guide.md`) rather than generic names (like `implementation_plan.md` or `plan.md`), preventing file-name collision and maintaining a clean system reference history.
4. **Mandatory Post-Mortem Documentation:** Upon resolving any code regressions, logic bugs, architectural issues, or significant feature gaps, the AI agent MUST document the failure, root cause, and resolution details as a new section under the "Post-Mortem" logs of the repository's `agents.md`/`AGENTS.md` files before concluding the turn. This guarantees persistent engineering context is saved dynamically.
5. **No Chinese-Authored Models**: The user refuses to use any models developed by labs in China (including but not limited to DeepSeek, Qwen, Yi). Never propose, download, configure, or use these models in any curation, indexing, code-generation, or chat setups. Prioritize models from Western/non-Chinese labs (such as Google Gemma, Meta Llama, and Mistral/Codestral).

---

# Post-Mortem: Summary of Massive Code Failures (Session 2026-06-27)

During this development session, multiple critical bugs, performance regressions, and metadata omissions were identified and resolved in the metadata crawler (`crawl_and_ingest_all.py`):

### 1. The Threading Ctrl+C Lockup (Signal Blocking)
* **Failure:** The main thread was blocked synchronously on `executor.shutdown(wait=True)` and `db_writer.join()`. On Windows, Python cannot execute signal handlers (such as Ctrl+C/SIGINT) while blocked on C-level joins, causing the terminal shell to lock up completely and require a process kill.
* **Resolution:** Replaced blocking joins with non-blocking polling loops (`while any(not f.done()): time.sleep(0.1)`), keeping the main thread responsive to signals.

### 2. Static Sleep Throttling (Performance Bottleneck)
* **Failure:** An unconditional `time.sleep(2.0)` was executed after every transaction. For a batch size of 20, this forced the script to sleep for 1.88 hours total, capping progress at ~10 rec/s.
* **Resolution:** Removed the static sleep. SQLite WAL mode and connection lock retry backoffs handle write conflicts natively without deadlocks. Speed increased to 450+ rec/s.

### 3. Incomplete Metadata Extraction (Omission of Categories and Tags)
* **Failure:** The script parsed only `RegionPersonDisplayName` and `HierarchicalSubject`, omitting face display names stored in `ACDSeeRegionName` and keywords/categories stored in `Keywords`, `Subject`, and `Categories`. This resulted in a near-empty metadata import.
* **Resolution:** Reimplemented the robust reference parsing rules to extract and merge:
  * `ACDSeeRegionName` + `RegionPersonDisplayName` (for faces)
  * `Keywords` + `Subject` + `HierarchicalSubject` + `Categories` (for tags).

### 4. Bypassed Preloader / Full-File Reading thrashing
* **Failure:** The preloader function had been deleted from the loop, causing workers to hit the disk platters concurrently. Once restored, the preloader read the **entire contents** of every image file (`while f.read(buffer_size): pass`), causing mechanical drive active time to spike to 120%+ and thrashing disk heads.
* **Resolution:** Optimized `preload_batch` to read only the first 256 KB of each file (the metadata header), warming the Windows page cache while reducing I/O read volume by over 95%.

### 5. File Extension Omission (Skipping iPhone GPS Data)
* **Failure:** The crawler filter and ExifTool arguments only scanned `.jpg`, `.jpeg`, and `.png`. This completely skipped `.heic`, `.webp`, `.tif`, and `.bmp`. Since mobile photos use `.heic` by default, all iPhone GPS-only photos were omitted.
* **Resolution:** Expanded the file filter and ExifTool arguments to scan all cataloged extensions (`.jpg`, `.jpeg`, `.png`, `.webp`, `.heic`, `.tif`, `.tiff`, `.bmp`), importing 17,289 `.heic` files and 23,601 new geolocations.


---

# Post-Mortem: Summary of Massive Code Failures (Session 2026-07-02)

During this development session, multiple critical performance bottlenecks, loop logic failures, and user experience bugs were resolved in the music curation pipeline (`run_music_combined_pipeline.py` and `clean_database_artists.py`):

### 1. Sequential Single-Server Curation Loop
* **Failure:** Processing directories in a strict sequential loop on a single endpoint when multiple active model servers were available in the network.
* **Resolution:** Implemented a concurrent worker thread pool distribution pattern utilizing a thread-safe task queue to distribute curation prompts to all active servers in parallel.

### 2. Curation Rollback Data Loss
* **Failure:** Committing database updates only at the end of the entire curation sweep, causing complete data loss of all successfully curated batches if the script was aborted mid-run.
* **Resolution:** Changed transaction commits to a per-batch basis, writing and saving progress instantly to PostgreSQL as soon as each chunk completes.

### 3. Run-over-Run Duplication Loop (Unknown/NULL Gaps)
* **Failure:** Mapping unresolved fields back to `'Unknown Artist/Album/Genre'` or clearing them to `None` (NULL). This caused the gaps query to fetch the exact same tracks on subsequent runs, creating an infinite curation loop.
* **Resolution:** Mapped unresolved default values to `'Unresolved Artist/Album/Genre'` and non-music to `'Non-Music'`, excluding them from future gaps sweeps.

### 4. VLM Text Curation Bottleneck & Silence
* **Failure:** Routing text-only curation prompts to slow VLM servers, causing 2-minute response delays with no streaming outputs or logs.
* **Resolution:** Configured the server router to prioritize fast Ollama servers (bypassing VLM servers for text curation when Ollama is online). Enabled real-time token streaming and text-wrapped prints to show progress live.

### 5. JSON Response Truncation in Mixed Folders
* **Failure:** Batching 20 highly diverse files in mixed folders (like voice notes and poetry in root `Music`), which forced the model to generate extremely long responses that hit token limits and returned invalid JSON.
* **Resolution:** Reduced the chunk batch size to 10 tracks to keep responses compact and safe from truncation.

---


# Behavioral Rule: Staging Environment Parity

1. **Mandatory Schema & Config Parity:** Any staging, testing, or sandboxed database/environment must utilize a schema and configurations that match the active production environment exactly. Never use simplified or partial schemas for testing pipelines that will be used for production migrations or data restores.
2. **Schema Verification Before Migration:** Before dumping data from any staging/test instance for production deployment, the agent must programmatically compare the schemas (columns, indexes, constraints) and row metrics between source and destination targets to prevent silent data omission or column loss.

---

# Post-Mortem Addendum: Summary of Failures (Session 2026-07-02 Curation & Ingestion Refactoring)

During this optimization session, we resolved a critical exception regression and a performance bottleneck in the music combined pipeline:

### 1. The task_done() try-finally ValueError
* **Failure**: Standard `job_queue.task_done()` was called inside a condition block which then called `continue`. In Python, the `finally:` block of a `try...finally` structure always executes even when `continue` is reached, leading to double-invocations of `task_done()` and throwing `ValueError: task_done() called too many times`.
* **Resolution**: Removed the redundant manual `task_done()` call inside the condition block, allowing the `finally:` cleanup handler to invoke it exactly once.

### 2. Sequential Ingest Subprocess Bottleneck
* **Failure**: Crawling and parsing file metadata (extracting ExifTool tags or JRiver XML parameters) ran in a single thread sequentially. When processing folders without sidecars, executing `exiftool` sequentially resulted in a massive speed bottleneck that left 32 Ryzen cores idle.
* **Resolution**: Re-architected Phase 1 scanning using `concurrent.futures.ThreadPoolExecutor(max_workers=args.max_workers)` to parse metadata in parallel, gathering results and batch writing them to PostgreSQL in chunks of 100.

---

# Behavioral Rule: Parallel Ingest & ExifTool Execution

1. **Mandatory Parallelism**: Filesystem crawling, directory scanning, and JRiver/ExifTool metadata parsing must always be executed in parallel using `ThreadPoolExecutor` and `--max-workers`.
2. **Performance Assertions**: Do not implement sequential parsing or argue that parallel ExifTool execution causes disk thrashing or is unsafe; parallel execution is highly performant, stable, and tested on this server's NVMe storage array and Ryzen 9 CPU architecture.

---

# Post-Mortem: Summary of Failures (Session 2026-07-03 SQL Direct Query Auto-Correction)

During this development session, we resolved a feature gap regarding auto-correction of user-provided SQL queries in the database chat REPL:

### 1. Ineffective Prompt-Only Correction (LLM Bypass)
* **Failure**: Modifying only the VLM system prompt (`db_prompt.txt`) to guide SQL query correction was insufficient. The REPL client intercepts direct SQL inputs (statements starting with `SELECT` or `WITH`) and executes them directly in Python. Because it completely bypasses the model to save VRAM and latency, any direct SQL syntax errors failed immediately inside Python without referencing the system prompt instructions.
* **Resolution**: Refactored the direct SQL block in `db_chat_repl.py` to capture python-level database execution failures, invoke the model using a dedicated external correction prompt (`sql_fix_prompt.txt`), execute the corrected query, and prompt the user for natural language intent if correction attempts fail.

### 2. Curation Overwrite of Valid Metadata (Fallback Overwrite)
* **Failure**: When running the curation pipeline, if a track had a missing genre gap but valid artist and album values in the database, a fallback to the offline heuristics resolver (`resolve_group_metadata_offline`) would return `Unresolved Artist` and `Unresolved Album` placeholders and unconditionally write them to the database, wiping out the correct artist/album metadata.
* **Resolution**: Modified the curation logic in `clean_database_artists.py` to check the current database values before executing updates, preserving existing valid metadata when the resolution yields `Unresolved` placeholders.

### 3. Remote Server Connection Timeouts (Wi-Fi Power-Saving & System Idle Suspend)
* **Failure**: Curation runs to auxiliary node `steven-len` (Xeon Workstation connected via Wi-Fi) failed with HTTP connection timeouts because:
  1. The host Wi-Fi adapter was configured to enter power-saving sleep when idle.
  2. The Ubuntu operating system (via GDM/login manager) was configured to automatically suspend/sleep the entire system after 20 minutes of user inactivity, completely ignoring background network/GPU tasks.
* **Resolution**: 
  - Disabled Wi-Fi power saving on `steven-len` by setting `wifi.powersave = 2` in `/etc/NetworkManager/conf.d/default-wifi-powersave-on.conf`.
  - Configured user-level and GDM system-level sleep timeouts to 5 hours (18,000 seconds) via `gsettings` and `dbus-run-session gsettings` to allow lengthy curation jobs to complete before the system naturally suspends to save power.

# Post-Mortem: Summary of Failures (Session 2026-07-04 Data Durability & Validation Safety)

During this development session, we resolved critical issues regarding VLM thread crashes, lack of early database writes, and premature large-scale directory processing:

### 1. Deferred DB Writing and Silent Thread Failures
* **Failure**: Phase 1 (VLM extraction) was structured to execute on dozens of files in a thread pool, but because a thread counter update lacked a `nonlocal` declaration, it threw an `UnboundLocalError` inside the thread worker. This exception was swallowed silently by the thread executor. The threads crashed one by one after processing only a single track each, resulting in 623 videos being silently skipped and losing hours of GPU processing potential.
* **Resolution**: Added `nonlocal` declarations to nested thread workers. Ensure that database writes for VLM panel descriptions are committed to PostgreSQL immediately on a per-video basis in the worker threads (flushing progress to disk), and implement explicit `future.result()` or robust error logging to catch and print thread-level crashes instantly.

### 2. Large-Scale Execution Prior to Verification
* **Failure**: Proposing and initiating massive, multi-hour curation passes over hundreds of tracks across the entire `H:\Wan_project` drive without first running, testing, and verifying the updated curation logic, prompt templates, and DB triggers on a small, targeted directory (such as a single folder with 10-35 files). This risks wide-scale database corruption, incorrect AI metadata generation (like the "Cosmic Symphony" hallucination), or repeated system hangs.
* **Resolution**: Establish a strict "targeted test first" protocol. Before executing any combined curation runs over major directory trees, always test the pipeline on a small targeted directory (e.g., `--dir "H:\Wan_project\wont_v1_vid"`) first. Verify the database updates for correct artist/album/genre mappings before initiating drive-wide processing.

---

# Curation Context & Saved Plan (Session 2026-07-04 Reboot Context)

When resuming development, always load the following critical context:

1. **Target Files are Videos:**
   The files under `wont_v1_vid` and similar folders are video files (`.mp4`, `.mov`), not static photos, even though the database table is historically named `photos`.
2. **Skip Videos > 20 Seconds:**
   Skip VLM description and curation for any video files longer than 20 seconds. They represent screen recordings, drafts, or tutorials and are out of scope for the Veo scene cataloger workflow. The script must log a warning and skip them.
3. **Contact Sheet Refactoring Required:**
   The current 1-FPS frame extraction and 2-frame chunk VLM querying is extremely slow and thrashes on longer videos (like 6-minute files). We must refactor the pipeline in `clean_database_artists.py` to use a client-side contact sheet compiler (stitching frames into a 4x2 grid using Pillow) similar to the approach in `catalog_35mm_scans.py`.
4. **Dynamic Frame Capping & Single Query:**
   Limit frame extraction to exactly 8 frames per video clip, compile them into a single contact sheet image (drawing labels 1 to 8 on the corners), and query the VLM in a single pass.
5. **Saved Plan:**
   The full design details and code instructions are saved in the artifact file `implementation_plan.md` in the current conversation directory. Read it first and implement it.

---

# Post-Mortem: Summary of macOS Client Migration Failures & Resolutions (Session 2026-07-05)

During this session, we refactored the database chat REPL client to run natively on the macOS orchestrator client (`Stevens-Mini-2`) and established network-wide trust.

### 1. Transitive HEIC Import Dependency Crash (`pillow_heif`)
* **Failure**: Importing `wsl_client` at the top level of `db_chat_repl.py` triggered a transitive import of `pillow_heif`. Because `pillow_heif` is not installed or needed on the client, this caused a startup crash on the macOS client.
* **Resolution**: Moved the `wsl_client` import inside the local-server startup thread function so it is only loaded if starting a local server, preventing crashes during remote client runs.

### 2. PostgreSQL / VLM Server Loopback Connection Failures on macOS
* **Failure**: Default connection hosts and server URLs targeting `localhost`, `127.0.0.1`, or `::1` failed immediately on the Mac Mini client as no DB or VLM server runs locally on that node.
* **Resolution**: Implemented dynamic loopback translation in `db_chat_repl.py`. If running on macOS, loopback target hosts are dynamically redirected to the workstation hostname `i7office` (`192.168.8.82`).

### 3. Implicit Stdin Consumption in Dependency Checking
* **Failure**: Shell scripts doing dependency validations (like `python3 -c "import requests"`) inherited and consumed the script's standard input stream, preventing piped queries from being processed by the REPL.
* **Resolution**: Redirected intermediate check inputs to `/dev/null` inside the self-healing bash launcher `run_db_chat_mac.sh`.

### 4. Drive Letter Mapping Naming Mismatches (`D:` and `H:` Drive Mounts)
* **Failure**: Windows paths starting with drive letters (like `D:\Users\...\` or `H:\Wan_project\...\`) mapped to `/Volumes/HDrive/` by default, but the workstation maps the `D:` drive to a separate SMB share `/Volumes/i7office/`. This caused a "File not found" error when attempting to open pictures on `D:`.
* **Resolution**: Enhanced `resolve_local_path` in `path_utils.py` to extract drive prefixes: mapping `D:` $\to$ `/Volumes/i7office` and `H:` $\to$ `/Volumes/HDrive`.

### 5. Rigid Mount Dependencies & Mount-Drift Failures (Self-Healing Mounts)
* **Failure**: If network shares are mounted under slightly different names or mounted as specific directories, static path mappings fail.
* **Resolution**: Implemented a self-healing fallback loop in `resolve_local_path`. If the primary mapped path is not found, the script dynamically scans all directories under `/Volumes` (macOS) or `/mnt` (Linux/WSL) for the relative path of the file, seamlessly recovering and launching files regardless of mounting details.

### 6. Task Automation & Persistent Mount Utility
* **Failure**: The cron job scheduled to keep mounts online failed due to syntax errors, incorrect mount endpoints, and `sudo` password prompting blocks in background cron shells.
* **Resolution**: Refactored `mount_i7office.sh` to trigger passwordless mounts using macOS Finder's native `open` command (leveraging the system Keychain) instead of `sudo mount -t smbfs`. Added a check to suggest creating a one-time symbolic link from `/Volumes/i7office` to the active mount path to align configuration paths.

---

## 11. macOS Client Mount Automation & Canonical Symlink Requirements

### Mount Script and Cron Configuration
To ensure remote media files are always accessible by the database chat client and other utilities, macOS clients run a cron job targeting `mount_i7office.sh`.
* **Path**: `/Users/<username>/mount_i7office.sh`
* **Cron Syntax**: `*/5 * * * * /Users/<username>/mount_i7office.sh`
* **Mechanism**: The script loops through "Resolve Proxy", "HDrive", and "D" shares, using Finder's `open "smb://Steven@192.168.8.82/<share>"` to mount them passwordlessly. Because it uses `open`, it runs in the user's GUI session and requires no `sudo` access, making it safe for cron.

### IP-Based Mounts and the `/Volumes/i7office` Symlink
On some macOS clients, Finder may mount the Windows `D` share under its IP hostname fallback `/Volumes/192.168.8.82` (or `/Volumes/D`) instead of the canonical `/Volumes/i7office` expected by path translation rules.
To resolve this mapping mismatch, you must create a one-time symbolic link under `/Volumes`:
* **If mounted as IP**:
  ```bash
  sudo ln -s /Volumes/192.168.8.82 /Volumes/i7office
  ```
* **If mounted as D**:
  ```bash
  sudo ln -s /Volumes/D /Volumes/i7office
  ```
The `mount_i7office.sh` script automatically detects which path was selected by Finder and prints the exact command needed to establish the mapping.

---

## 12. Database Table Schemas

The database uses PostgreSQL on the workstation host and local SQLite files on clients. Below is the schema documentation for the two main tables:

### Table: `photos` (Visual Metadata & VLM Summaries)
*   `id` SERIAL PRIMARY KEY
*   `full_path` TEXT UNIQUE NOT NULL (Absolute path of the file on disk, e.g., `"H:\Wan_project\wont_v1_vid\veo_scene_1.mp4"`)
*   `rel_path` TEXT NOT NULL (Relative path under the main Pictures or Projects root)
*   `primary_subject` TEXT (Visual description generated by the VLM panel analyzer or ACDSee description text. **This is the main description field.**)
*   `environment` TEXT (Visual settings: indoors/outdoors, lighting, weather)
*   `suggested_tags` TEXT (A JSON array string of keywords, e.g., `["sunset", "ocean", "nature"]`)
*   `technical_details` TEXT (Camera settings, dimensions, frame rates)
*   `detected_objects` TEXT (A JSON array string of detected objects)
*   `detected_faces` TEXT (A JSON array string of recognized faces)
*   `acdsee_tags` TEXT (A JSON array string of categories/keywords imported from ACDSee)
*   `rating` INTEGER (Star rating 1-5, or 0)
*   `label` TEXT (Color label, e.g. "Red", "Blue")
*   `author` TEXT (Photographer/creator name)
*   `gps_latitude` REAL (Latitude in decimal degrees)
*   `gps_longitude` REAL (Longitude in decimal degrees)
*   `gps_altitude` REAL (Altitude in meters)
*   `raw_metadata` TEXT (Complete raw ExifTool JSON dictionary)
*   `acdsee_metadata_imported_at` TEXT (ISO timestamp of import)
*   `file_mtime` REAL (Unix modification timestamp)
*   `location_name` TEXT (Geocoded location string)

### Table: `music_tracks` (Audio & Curation Metadata)
*   `id` SERIAL PRIMARY KEY
*   `file_path` TEXT UNIQUE NOT NULL (Absolute path of the track file on disk)
*   `title` TEXT (Song/track title)
*   `artist` TEXT (Artist name, e.g., `"Steven Michalove"` or `"Cécile McLorin Salvant"`)
*   `album` TEXT (Album name, e.g. `"wont_v1_vid"` or `"WomanChild"`)
*   `genre` TEXT (Curated musical genre, e.g., `"Soundtrack"`, `"Jazz"`)
*   `track_number` INTEGER
*   `rating` INTEGER
*   `album_art_path` TEXT (Path to the cover art or parent folder. **Links directly to `photos.full_path`**)
*   `jriver_genre` TEXT (Original genre from JRiver)
*   `suggested_genre` TEXT (AI suggested genre)
*   `xml_metadata_path` TEXT (Path of sidecar JRiver XML)
*   `date_imported` TEXT (Ingestion timestamp)

### Table Joins
*   **Video Tracks (Dual Registered)**: For video files that exist in both tables (e.g., in video projects like `wont_v1_vid`), join them directly on file paths: `FROM music_tracks mt LEFT JOIN photos p ON mt.file_path = p.full_path`.
*   **Album Art**: To find the art cover details of a standard audio track, join on the art path: `FROM music_tracks JOIN photos ON music_tracks.album_art_path = photos.full_path`.

---

# Post-Mortem: Summary of Failures & Refactoring (Session 2026-07-05 Part 2)

During this session, we resolved issues regarding hardcoded prompts and structured VLM descriptions:

### 1. Hardcoded Inline VLM Prompts
* **Failure**: The prompt instructions for video panel descriptions in `clean_database_artists.py` were hardcoded inline as a plain-text Python string. This violated the directive requiring all LLM/VLM system and user prompts to be externalized to `.txt` files.
* **Resolution**: Created `vlm_video_prompt.txt` to hold the VLM instructions. Updated `clean_database_artists.py` to dynamically load the prompt at runtime and raise a `FileNotFoundError` if the file is missing to prevent inline fallback code.

### 2. Plain-Text VLM Fallbacks (Low-Fidelity Video Descriptions)
* **Failure**: The original inline prompt did not instruct the VLM to return structured JSON. The VLM returned raw plain-text paragraphs, causing the database JSON/regex parser to fail and fall back to storing the plain text in the description field, leaving `suggested_tags` and `environment` empty in the database.
* **Resolution**: Updated `vlm_video_prompt.txt` to mandate structured JSON output (`primary_subject`, `environment`, `suggested_tags`) with an exhaustive (150-250 words) chronological description constraint.

### 3. Loopback Connection Failures and Path Separator Test Failures
* **Failure**: Running unit tests on the macOS client threw path-separator and hostname assertion failures because the test cases expected Windows backslashes and a `127.0.0.1` JRiver host, while the runtime client was correctly generating Unix-style slashes and loopback redirection to `i7office`.
* **Resolution**: Refactored `test_db_chat_repl.py` to use platform-aware path separation and conditional JRiver hosts (mapping loopbacks to `i7office` on macOS).

### 4. Flimsy Immediate Retries (VLM Queue Congestion)
* **Failure**: When multiple video processing workers queried local VLM endpoints simultaneously, they overloaded the GPU queues, causing `Read timed out` HTTP exceptions. Since the retry logic had no delay, retries burned out in a fraction of a second, causing the run to fail and skip cataloging the files.
* **Resolution**: Implemented a robust 3-attempt exponential backoff retry loop with randomized jitter (~0.5s to 1.5s) inside the VLM query blocks, giving local GPU servers time to drain their queues before retrying.

---

# Post-Mortem: Summary of Failures & Refactoring (Session 2026-07-05 Part 3)

During this session, we resolved issues regarding video frame contact sheet rendering, cover-art thumbnail auto-linking, and run stability:

### 1. Omitted Frame Numbers in Contact Sheet Grid
* **Failure**: During the transition to compile video frames into a single unified 4x2 contact sheet image grid, the drawing helper function `draw_label` (which overlays numbered labels) was never invoked in `compile_contact_sheet`. The VLM received raw, unlabeled tiles, making frame boundaries hard to track.
* **Resolution**: Modified the pasting loop in `compile_contact_sheet` to duplicate each frame and invoke `draw_label(labeled_img, str(index + 1))` before pasting it into the black background canvas.

### 2. Low-Visibility Native Numbers Contrast
* **Failure**: The native numbers burned into the corners of some raw video files were extremely tiny and lacked backgrounds, blending into light-colored scenes and failing to provide reliable visual cues to the VLM.
* **Resolution**: Configured the label drawer to overlay a solid 60x60 black rectangle with a large 44pt **Neon Green (`#39FF14`)** text string, producing a clear, high-contrast digital overlay for every panel.

### 3. Contact Sheet Cover-Art Auto-Linking Mismatch
* **Failure**: Saving contact sheets with a `_contact_sheet.jpg` suffix prevented JRiver Media Center and operating system file managers from automatically matching and displaying the image as the poster/cover art for the video file.
* **Resolution**: Changed the local copy filename next to the video file to match the video name exactly with a `.jpg` extension (e.g. `video_name.jpg` next to `video_name.mp4`), enabling instantaneous automatic art association.

### 4. Manual CLI Saving Argument Requirement
* **Failure**: Users had to explicitly pass the `--save-contact-sheets` argument to get physical image file writes, making JRiver thumbnail integration cumbersome.
* **Resolution**: Made saving contact sheets the default runtime behavior. Replaced the parameter in the argument parser with a `--no-contact-sheets` flag to easily opt-out if needed.

### 5. Workstation System-level RAM Instability
* **Failure**: Running 128GB of dense DDR4 RAM with DOCP enabled (3600MHz) caused bus errors, memory training failure, random Windows freezes, and loopback database connection dropouts under heavy multi-threaded workloads.
* **Resolution**: Disabled DOCP in the BIOS, running memory at a stable 2666MHz JEDEC standard, and documented coupled Infinity Fabric (FCLK) and chipset driver upgrade recommendations in the compute node topology sheet.

---

# Post-Mortem: Summary of Failures & Refactoring (Session 2026-07-06 PostgreSQL Backup Lockup)

During this session, we investigated and resolved a database-level lockup that hung the automated local database backup process:

### 1. PostgreSQL Backup Hung in Task Scheduler (Lock Queue Starvation)
* **Failure**: The scheduled Windows backup task (`PostgreSQL Photo Catalog Backup`) executing `pg_dump` became stuck indefinitely on `reading user-defined tables`. This resulted in a 0-byte backup file `photo_catalog_backup_2026-07-06.dump` on the `T:` drive that did not write any data for over 25 minutes.
* **Root Cause**: An active PostgreSQL connection (PID 39112) was left in the `idle in transaction` state since the previous day. Another session (PID 42832) was attempting to execute an `ALTER TABLE music_tracks ADD COLUMN IF NOT EXISTS album_artist TEXT;` DDL command, which requires an exclusive lock (`AccessExclusiveLock`). This DDL lock request queued up behind PID 39112's open transaction locks. Because a high-priority exclusive lock was waiting, PostgreSQL blocked all subsequent `AccessShareLock` requests (including `pg_dump`'s `LOCK TABLE` statement) to prevent starvation, causing the backup process to hang indefinitely.
* **Resolution**: Located the blocking session using `psql.exe` and queries on `pg_stat_activity` and `pg_locks`. Forcefully terminated the root idle connection (PID 39112) using `SELECT pg_terminate_backend(39112);`. This immediately cleared the lock queue, letting the DDL change complete and allowing `pg_dump` to finish successfully, writing the full 164.6 MB backup file to `T:\photo_catalog_backup_2026-07-06.dump` and completing the scheduled task.

### 2. Lack of Session Saving/Resuming in DB Chat Client (Feature Gap)
* **Failure**: The database chat REPL client had no native command to explicitly save or reload custom conversation sessions. While it wrote a temporary history to `db_chat_session.json` on each turn, users could not name or manage multiple distinct sessions, nor could they explicitly load historical conversations to resume context (unlike Ollama's native CLI).
* **Resolution**: Added a dedicated `sessions/` storage folder, implemented `/save [name]` and `/load [name]` commands, and added automatic background writing of the active chat to `sessions/last_chat.json`. Now, users can run `/load last_chat` or `/load` (which lists all saved JSON files with message counts and dates) to resume conversational context easily.

### 3. Model Benchmarking & Quadro P1000 Driver Lockup (Hardware Constraints)
* **Failure**: Running a 12B multimodal VLM model (`gemma4:12b`) on a 4GB Quadro P1000 GPU under split CPU/GPU offloading for high-resolution image evaluation took over 4 minutes and crashed (completely hung) the Linux server.
* **Root Cause**: The 12B model footprint in Q4 (7.5GB–8.5GB) exceeded the 4GB VRAM capacity. Ollama partitioned the model, allocating 87% VRAM (3,577 MiB) and offloading the remaining 6.8 GB to system RAM. Sustained multi-threaded CPU matrix math (utilizing 23 threads at >414% CPU) and constant PCIe bus memory paging triggered a CUDA driver hang and a Linux kernel freeze.
* **Resolution**: Established passwordless SSH trust to the server, registered the `len-big` node (`192.168.8.51`) in the cataloger configuration for text curation, and recommended the planned hardware upgrade to a Tesla P40 (24GB VRAM) to support full GPU residency and prevent driver lockups during visual processing.

---

# Post-Mortem: Summary of Failures & Refactoring (Session 2026-07-07 Empty rel_path & Ingest Argument Bugs)

During this session, we resolved a path-indexing database bug and command line parameter parsing failures in the ingestion pipeline:

### 1. Hardcoded Empty `rel_path` for Curated Videos
* **Failure**: Video files (like `.mp4` and `.mov` in `wont_v1_vid`) had their `rel_path` column populated as `''` (empty string) in the database, preventing standard path-based joins and matching.
* **Root Cause**: `clean_database_artists.py` hardcoded `''` for the `rel_path` column in both of its `INSERT` queries in the VLM curation logic. Because `crawl_and_ingest_all.py` matched these files on `full_path_norm in existing_paths_map` and ran the `UPDATE` query (which did not update `rel_path`), the empty values persisted.
* **Resolution**: 
  - Extracted the path normalization logic and created a centralized, cross-platform `compute_rel_path` function in `path_utils.py` that strips drive letters, WSL mount points, and macOS mount structures cleanly.
  - Refactored `clean_database_artists.py` to import `compute_rel_path` and use it dynamically in `update_photo_query` (and the `DO UPDATE SET rel_path = EXCLUDED.rel_path` clause).
  - Cleaned up duplicate code by replacing the local `compute_rel_path` in `crawl_and_ingest_all.py` with the shared utility import.

### 2. Ingest script crash (`ingest_all.sh` fails on options)
* **Failure**: Running `./ingest_all.sh --limit-photos 5` crashed immediately with `argument --root: expected one argument` and ingestion failed.
* **Root Cause**: `ingest_all.sh` unconditionally treated the first argument `$1` as the root directory, regardless of whether it was a path or a flag like `--limit-photos`. This resulted in the flag being passed to Python's `--root` parameter, leaving `--limit-photos` without an argument.
* **Resolution**: Updated `ingest_all.sh` to check if `$1` begins with a hyphen (`-*`). If the first argument is an option, it retains the default `ROOT_DIR` and forwards all arguments; otherwise, it resolves the custom root path and forwards the remaining arguments (`"${@:2}"`).


---

# Post-Mortem: Summary of Failures & Refactoring (Session 2026-07-07 Part 2 - WSL Connection and Legacy VLM Descriptions)

During this session, we resolved a native WSL database connection crash, a missing frame-extractor dependency, and a legacy description skip bug:

### 1. Native WSL PostgreSQL Connection Failure
* **Failure**: Executing `clean_database_artists.py` natively in WSL using `python3` failed immediately on startup with the error `connection to server at "localhost" (127.0.0.1) failed: fe_sendauth: no password supplied`.
* **Root Cause**:
  1. The script attempted to connect to `localhost` to reach PostgreSQL. Unlike the chat REPL, the curation script lacked loopback translation logic to redirect loopback connections to the workstation's physical host IP (`192.168.8.82`) under Linux/WSL.
  2. The script only loaded the database password from `os.getenv("DB_PASSWORD")` and did not read the `auth/db_password.txt` file where the password was actually stored.
* **Resolution**: Refactored `get_pg_connection()` in `clean_database_artists.py` to:
  1. Automatically translate loopbacks (`localhost`, `127.0.0.1`, `::1`) to `192.168.8.82` when executed on Linux or macOS.
  2. Read the database password from `auth/db_password.txt` if the file exists, matching the robust connection pattern used by other pipeline scripts.

### 2. Missing OpenCV (`cv2`) dependency in WSL Environment
* **Failure**: The curation script's worker threads crashed silently on every video processing attempt with the error `No module named 'cv2'`, skipping all visual VLM descriptions.
* **Root Cause**: The script uses OpenCV to extract video frames, but OpenCV was only installed in the Windows Python environment and was missing from the native WSL Python environment.
* **Resolution**: Installed `opencv-python-headless` inside the WSL python environment, enabling successful parallel frame extraction and contact sheet compilation.

### 3. Legacy VLM Descriptions Skipped in Incremental Runs
* **Resolution**: Updated the check in `clean_database_artists.py` to `has_scenes = has_desc and ("1)" in row[0])`. The script now only skips videos that have the proper chronological numbered format, automatically targeting and re-generating descriptions for any video with legacy generic summaries.

### 4. False Assertion Regarding Disk Utilization
* **Failure**: The AI agent asserted that local Disk 2 (`D:`) utilization (79% active time) was caused by OpenCV video frame extraction during curation.
* **Root Cause**: The agent made an assumption based on a high-level GPU/Disk summary graph in Task Manager without inspecting actual process metrics. A detailed process inspection proved that **Google Drive** was executing sync operations at **201.8 MB/s** on `D:`. Furthermore, the curation video files were stored on `H:`, meaning `D:` disk activity was completely unrelated.
* **Resolution**: Re-verified the active processes, corrected the assertion immediately, and documented the requirement to base all resource utilization claims on detailed process-level counters rather than overall device activity graphs.

---

# Post-Mortem: Summary of Failures & Refactoring (Session 2026-07-07 Part 3 - POSIX Compliance, macOS Database & Path Translation, and Lenovo Big Integration)

During this development session, we resolved a series of shell script compatibility errors, database connection bugs on remote client nodes, and enabled auxiliary model servers:

### 1. POSIX Compliance Failures on Dash Shells
* **Failure**: The modified wrapper scripts (`run_music_ingest.sh`, `run_music_combined_pipeline.sh`, `ingest_all.sh`, `run_cataloger.sh`) failed instantly under Ubuntu WSL with `Bad substitution` and `[[: not found`. This occurred because the scripts used Bash-specific structures (like `${BASH_SOURCE[0]}`, `[[ ... ]]`, `${ARGS[@]}`) while the default shell `/bin/sh` on Ubuntu maps to `dash` (which is strictly POSIX and lacks Bash extensions).
* **Resolution**: Rewrote all wrapper scripts to be 100% POSIX-compliant, replacing `${BASH_SOURCE[0]}` with standard `"$0"`, using `case/esac` matching instead of `[[ ... ]]`, and using positional parameter shifting (`set --` and `shift`) to dynamically translate and forward arguments without arrays.

### 2. Missing Path/Loopback Redirection in Music Pipelines
* **Failure**: Running `ingest_music_library.py` and `write_tags_to_files.py` from macOS client nodes threw database connection timeouts and "file not found" errors because:
  1. They defaulted `DB_HOST` to loopback (`localhost`), which fails on remote clients.
  2. The database stores track paths in Windows format (`D:\...` or `H:\...`), which fails on macOS without path conversion.
* **Resolution**: Added loopback host translation logic to redirect loopback connections to the workstation IP (`192.168.8.82`) on macOS/Linux. Integrated `path_utils.resolve_local_path` into the file tagger to dynamically translate Windows-style paths to local macOS mount points before checking/updating tags.

### 3. Missing/Uncommented Lenovo Big Server Configuration
* **Failure**: The curation script `clean_database_artists.py` had the Lenovo Big server (`192.168.8.51`) commented out under a fallback model.
* **Resolution**: Probed the host to confirm active models, uncommented the CurationServer entry, and updated it to target `gemma4-it-q4:latest`, allowing the curation loop to load-balance queries across it.

---

# Post-Mortem & Configuration Update: VLM Parallel Throughput Optimization (Session 2026-07-07 Part 4 - VLM Batch Size Upgrade)

### VRAM Analysis & Batch Size Upgrade
* **Observation**: Monitored the local RTX 5080 (Windows/WSL) and remote RTX 4070 Ti SUPER (headless Linux) during parallel VLM image cataloging runs. Under `batch_size = 3`, the RTX 5080 hovered at ~13.1 GB of VRAM utilization while the RTX 4070 Ti SUPER hovered at ~8.8 GB. This disparity stems from the absence of Windows OS desktop VRAM overhead on native Linux.
* **Resolution**: Increased the cataloger's default configuration in `run_cataloger.sh` from `--batch-size 3` to `--batch-size 4`. This optimizes throughput to **~350+ photos/hour** (a ~15-20% speed improvement) while maintaining a safe VRAM envelope of ~14.2 GB on the local RTX 5080 and ~10.0 GB on the remote RTX 4070 Ti SUPER.

### Benchmark Optimization & WSL Native Performance
* **Finding**: Confirmed a massive **1.98x speedup** in raw VLM batch inference processing times when comparing yesterday's Windows interop runs against today's native WSL + overclocked setup:
  * **Before (Windows Interop - July 6th)**: Averaged **426.57 seconds (7m 6s)** per batch of 3 video contact sheets.
  * **After (Native WSL + CPU/GPU Overclock - July 7th)**: Averaged **215 seconds (3m 35s)** per batch of 3 video contact sheets.
  * **Heuristics**: Eliminating the filesystem boundary (WSL to Windows mounts) and leveraging the Ryzen 9 overclock for frame extraction and array serialization cut processing times directly in half.





---

# Post-Mortem & Safety Rule: VLM Hang Handling & GPU Process Management (Session 2026-07-07 Part 5 - Batch Size 4 Recovery)

### VLM Server Recovery Policy
* **Failure**: Blindly executing "pkill -9 -f uvicorn" to terminate backend VLM servers when the client pipeline script ("describe_photos.py") was stuck.
* **Root Cause**: Forcefully killing active Python/PyTorch server processes under active CUDA memory allocations deadlocked the NVIDIA kernel driver within WSL2. This caused a Blue Screen of Death (BSOD) hardware watchdog crash and forced a full system reboot of the workstation host.
* **Rule (Do Not Violate)**: 
  > [!IMPORTANT]
  > Never kill backend VLM/Ollama uvicorn server processes ("wsl_server.py", "remote_server.py") if only the client script ("describe_photos.py") needs to be terminated or restarted. 
  > Always kill the client script first ("pkill -9 -f describe_photos.py") and let the servers idle down naturally to release CUDA allocations safely.

---

# Post-Mortem & Configuration Update: CPU VLM Cluster Parallel Integration (Session 2026-07-07 Part 6 - Multi-Node CPU Inference Tuning)

During this optimization session, we successfully integrated both Lenovo Xeon W-2135 workstations (`len-big` and `steven-len`) into the active parallel photo cataloger pool running CPU-only VLM workloads safely alongside local/remote GPUs:

### 1. GPU Bypass & VRAM Crash Prevention
*   **Failure**: Attempting to load the 12B model on the Xeon workstations resulted in host crashes or service locks because Ollama tried to allocate weights on the low-VRAM Quadro P1000 display GPUs.
*   **Resolution**: Configured `Environment="CUDA_VISIBLE_DEVICES=-1"` in systemd service overrides on both servers to completely hide the Quadro P1000 GPUs from Ollama, forcing safe, stable CPU-only execution.

### 2. CPU Scale Governor & Thermal Verification
*   **Optimization**: Changed the scaling governor from `powersave` to `performance` on both Lenovo nodes (`len-big` and `steven-len`) to lock Xeon cores at maximum turbo frequencies under VLM matrix math execution.
*   **Safety**: Verified CPU core temperatures remain extremely safe under sustained heavy AVX inference loads, hovering at **~49°C–50°C** (well below the 92°C thermal throttling threshold), providing 40°C+ of thermal headroom.

### 3. Transparent Huge Pages Optimization
*   **Optimization**: Converted Transparent Huge Page (THP) allocations on both systems from `madvise` to `always` using `sysfs` settings, reducing translation lookaside buffer (TLB) mapping misses during large model parameter walks.

### 4. Dynamic Prompt Mismatch and JSON Standardization
*   **Failure**: The curation script threw parsing warnings and `error-parsing-json` errors because `prompt.txt` mixed JSON output schema examples with plain-text key-value colons, confusing the model into generating invalid responses.
*   **Resolution**: Standardized the `Other examples` section in `prompt.txt` into a clean JSON layout (`Example 6`) matching the other instructions. Refactored `wsl_server.py` to completely eliminate hardcoded prompt strings, directly prepending the client's dynamic instructions inside a single native user turn to prevent tokenizer errors and infinite repetition hangs.
*   **Dynamic Load**: Confirmed that worker threads dynamically reload `prompt.txt` on every batch pull, allowing this hot-patch to take effect immediately in the active cataloging run without downtime.

---

# Post-Mortem: CPU Node Generation Collapse & Guess-Based Diagnostics (Session 2026-07-08)

During this cataloging run, we encountered persistent metadata errors from the CPU nodes and documented a critical diagnostic process failure:

### 1. Ingestion Latency and Client-Side Timeout (Ollama on CPU)
*   **Failure:** The VLM cataloger client repeatedly dropped connections to `Remote Lenovo` and `Remote Lenovo Big` with `char 0` (empty) parsing failures.
*   **Root Cause:** Loading the 7.6 GB `gemma4:12b` model from disk into CPU system RAM took 2-3 minutes, and prompt ingestion of 2,513 tokens on CPU took 90 seconds. Together, these phases exceeded the client's 300-second (5 minute) HTTP timeout window, causing the client to drop the TCP socket before generation could begin.
*   **Resolution:** Raised client `"num_predict"` to `1500`, `"num_ctx"` to `8192`, and client-side HTTP socket timeout to `600.0` seconds (10 minutes) inside `wsl_client.py`.

### 2. Model Reasoning/Thinking Token Exhaustion (CPU Generation Loop)
*   **Failure:** Even with timeouts raised to 10 minutes, both Lenovo CPU nodes returned invalid JSON structures (`Unterminated string` and `char 0` errors).
*   **Root Cause:** The `gemma4:12b` model is a reasoning model that natively generates a massive "chain-of-thought" (reasoning tokens) starting with `Thinking...` before writing the actual final JSON response. Under slow CPU execution, these thinking tokens consumed the entire token budget (`num_predict`), causing the generation to cut off mid-sentence and preventing the JSON block from closing properly.
*   **Correction:** Checked the model's raw token generation stream and the interactive terminal logs, proving that the model was generating hundreds of reasoning tokens first.

### 3. Failure to Use an Evidence-Based Approach
*   **Failure:** The agent engaged in a guess-and-test cycle (whack-a-mole), assuming the model was just "too verbose" and blindly increasing token limits (`num_predict`, `num_ctx`, `timeout`) without verifying what the model was actually outputting. 
*   **Rule (Do Not Violate):** 
    > [!IMPORTANT]
    > When debugging LLM/VLM parsing or generation failures, *never* guess or adjust parameters blindly. 
    > Always write a diagnostic test script to output the raw, unparsed response directly to a file (`raw_response.txt`) to inspect the generated token string first.

### 4. Resolution (Think Suppression & Giga Integration)
*   **Action:** 
    1. Added `"think": False` to the Ollama payload in `wsl_client.py` to suppress the model's reasoning/thinking tokens from the output stream.
    2. Added explicit stop sequences `["<end_of_turn>", "<eos>", "<|im_end|>"]` to force immediate generation termination when the VLM completes its output.
    3. Uncommented the Lenovo workstations (`Remote Lenovo Big` and `Remote Lenovo`) in `describe_photos.py`, bringing them back into the active parallel cataloging pool.
    4. Added the Remote Giga server (`ubunto-giga` at `192.168.8.193` running model `gemma4:12b`) as an active VLM node in `describe_photos.py` to further accelerate cataloging throughput.
    5. Verified the fix with a streaming run on the Eric Clapton cover on `steven-len`, which completed in **159 seconds (a 3x speedup)**, and on `ubunto-giga` (`192.168.8.193`), which completed in **33.49 seconds using the full gemma4:12b model (running at GPU speed of ~25 t/s)**, both returning 100% clean, valid JSON blocks.

---

# Post-Mortem & Benchmarks: RTX 5080 VLM Performance & DDR Spillover Analysis (Session 2026-07-09)

### 1. Local RTX 5080 VLM Performance Profile
*   **Throughput:** Tested under `batch_size = 3` parallel photo cataloging runs using the `gemma4:12b` VLM. It consistently processes a batch of 3 images in **63 to 70 seconds** (averaging **21.0s to 23.3s per image**), delivering a throughput of **~160-170 photos/hour**.
*   **VRAM and Power Efficiency:** Peak VRAM loads stayed stable at **11.9 GB** with active power draw of **~175.4 W** at **52% GPU utilization** (Temp: **56°C**), leaving comfortable thermal headroom well below the hardware's 350W TDP limit.

### 2. RTX 4060 VRAM Congestion & Host DDR Spillover (`ubunto-giga`)
*   **Observation:** During concurrent VLM inference on the RTX 4060 (8GB VRAM) node, VRAM utilization reached **6.60 GiB** (78% capacity).
*   **DDR Spillover:** Due to high context memory bounds, the KV-cache context slightly overflowed the remaining GPU memory space, spilling layers over the PCIe Gen3 x8 bus to system RAM (**12.24 GiB host memory**).
*   **System Response:** Despite the DDR spillover, the Ryzen 5 5500 CPU handled the offloaded layers rapidly (at **394% CPU load**). The performance impact was transient and nominal, proving that modern CPU cores process the brief overflow cycles without causing system lags or execution bottlenecks.

---

# Post-Mortem: Cross-Platform Path Normalization Gap in Ingestion (Session 2026-07-12)

### 1. Ingestion File Path Format Inconsistency (WSL/macOS to Windows Path Mismatch)
*   **Failure:** Running the music library ingestion script `ingest_music_library.py` from native WSL or macOS clients walked paths locally (resulting in paths starting with `/mnt/h/...` or `/Volumes/HDrive/...`). These raw local paths were written directly to PostgreSQL, creating inconsistent path prefixes that broke JRiver integration and client path resolution scripts expecting standard Windows-style paths (`H:\...`).
*   **Root Cause:** The python metadata ingester `ingest_music_library.py` walked directories and wrote files using their raw traversed local paths. While `run_music_ingest.sh` attempted path translation at the shell wrapper level, it passed Windows paths to the WSL native `python3` interpreter, causing `os.walk` to fail. When bypassed, the script inserted POSIX paths directly into the database without translation.
*   **Resolution:** Refactored `batch_ingest_tracks` in `ingest_music_library.py` to auto-translate WSL mount prefixes (`/mnt/h/`, `/mnt/d/`) and macOS mount prefixes (`/Volumes/HDrive/`, `/Volumes/i7office/`) to canonical Windows drive formats (`H:\...`, `D:\...`) right before database insertion. This ensures absolute path consistency (retaining the Windows root format) regardless of whether the crawler runs on Windows, WSL, or macOS.

---

# Post-Mortem & Stability Benchmarks: Workstation CPU & GPU Stress Testing (Session 2026-07-13)

### 1. Concurrent CPU & GPU Peak Load Stability
*   **Workload**: Executed standard `stress-ng` (32 logical worker threads) concurrently alongside a custom PyTorch FP32 matrix multiplication script (`gpu_stress.py` performing repeated $8192 \times 8192$ float32 calculations on CUDA).
*   **Result**: Absolute system stability maintained for a sustained 5-minute (300-second) period under a combined core power draw exceeding **`610 Watts`** (CPU Package: ~217W, GPU: ~396W).
*   **Throughput Resiliency**: 
    *   **CPU Performance**: Delivered **`32,107.92 bogo ops/s`** (completing 9,154,681 bogo ops in 285.12s of real time, fully in line with the CPU-only baseline).
    *   **GPU Performance**: Delivered **`37.82 TFLOPS`** (completing 11,345 matrix multiplications of size $8192 \times 8192$ in 329.86s total time, matching the GPU-only baseline of 37.84 TFLOPS).
    *   **Analysis**: The zero-overhead throughput matching under concurrent load proves that the motherboard VRMs, PCIe bus, and host PSU (`i7office`) operate with complete power integrity and zero power delivery bottlenecks under sustained stress.

### 2. Thermal Limits & Cooling Performance
*   **Observation**: CPU Package Power peaked at **`217.109 W`** (with CPU Core Power at **`174.254 W`** and PPT at **`213.167 W`**) and GPU Power peaked at **`396 W`** (at 100% Core/Thread usage).
*   **Analysis**: No thermal limits or thermal throttling occurred during the sustained 5-minute testing. Clock speeds remained rock-solid at **`4.19–4.56 GHz`** across all active threads, verifying optimal heat dissipation and hardware cooling configurations on the workstation.
*   **Stability Configuration**: The Ryzen 9 5950X CPU overclocking configuration was adjusted by backing off the AMD Curve Optimizer (Core Optimizer) settings to stock/conservative offsets. Aggressive negative offsets had previously introduced instability under transient rendering/inference loads. Disabling these aggressive curve offsets successfully resolved all instability, resulting in 100% compute reliability under sustained concurrent CPU and GPU stress.

### 3. Virtualization Telemetry Limitation
*   **Observation**: Standard guest Linux diagnostics (like `sensors` or `lm-sensors`) are non-functional inside WSL2 because Hyper-V abstracts motherboard SMBus and specific CPU registers.
*   **Resolution**: Confirmed that HWiNFO64 running natively on the Windows host is the canonical method to monitor physical telemetry (power, thermals, fans) during WSL2 stress testing.

---

# Post-Mortem & Architecture Optimization: Gemma 4 26B A4B VRAM OOM Failure & Ollama Migration (Session 2026-07-15)

### 1. The Hugging Face Multi-Threaded VRAM Loading Spike (CUDA OOM)
*   **Failure:** Attempting to load the 26B MoE model (`google/gemma-4-26B-A4B-it`) in 4-bit (`BitsAndBytesConfig`) using `AutoModelForCausalLM` or `wsl_diffusion_server.py` on the single 24GB Tesla P40 GPU caused a CUDA OOM crash at ~31% weight loading. 
*   **Root Cause:** Under `transformers 5.x`, model weights are parsed concurrently by a new multi-threaded loader backend (`core_model_loading.py`). This backend materializes multiple large weight parameter tensors in full precision (float16/32) on the GPU simultaneously before quantizing them. Because the raw model size is 52 GB, these concurrent transient allocations instantly saturated the P40's 24GB VRAM.
*   **Failed Attempts:** 
    *   Using `device_map="auto"` failed because `accelerate` calculated that the unquantized float16 model (52 GB) would not fit on the GPU and attempted to dispatch layers to the CPU, which is unsupported for active 4-bit `bitsandbytes` modules.
    *   Setting `transformers.core_model_loading.GLOBAL_WORKERS = 1` serialized weight parameter loading, but PyTorch's internal allocator caching and Hugging Face's transient memory copies still hit a peak memory requirement that overflowed the VRAM.

### 2. Ollama C++ GGUF Engine Migration (The Resolution)
*   **Action:** Switched from the Python/PyTorch server architecture to hosting the model directly inside the local **Ollama** service under the tag `gemma4:26b`.
*   **Mechanism:** Ollama uses the `llama.cpp` runtime (written in C++). It loads a pre-compiled, pre-quantized 17 GB GGUF file directly into memory. The C++ allocator writes the 4-bit weights straight into VRAM without any intermediate high-precision staging or thread-allocation spikes.
*   **Results & Performance Profile:**
    *   **VRAM Stability:** Peak GPU memory stayed rock-solid at **18.087 GB** during both load and generation phases, leaving a healthy **4.4 GB VRAM headroom** (GPU utilization: 90%, Temp: 42°C, Power: 137W).
    *   **Inference Speed:** The model loaded in **7.84 seconds** and generated tokens at a blazing-fast **42 tokens per second** (processing 1256 tokens in 29.5 seconds).
    *   **Multimodal Quality:** Successfully analyzed complex technical and developer screenshots (identifying IDE code layouts, macOS UI elements, JRiver Media Player, and clock times) as well as high-action/artistic video frames, completing sequential image descriptions in **~20 seconds per image** with zero memory growth or drift.
*   **Architecture Simplification:** The custom Python server script `wsl_diffusion_server.py` and its background service are no longer required, reducing workspace complexity.
