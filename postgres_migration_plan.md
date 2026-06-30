# PostgreSQL Codebase Migration Plan & Task List

This document outlines the architectural plan, task list, and verification steps for transitioning the photo cataloger codebase from SQLite to a remote/local PostgreSQL database backend.

---

## 1. Connection Architecture Options

To connect our local developer workstation (Mac) and edge client scripts to the production PostgreSQL database running natively on the Windows host `i7office` (`192.168.8.82`), we have two primary architectural options:

### Option A: Secure SSH Tunneling (Backup)
We establish an SSH port-forwarding tunnel that maps local port `5432` to `localhost:5432` on the remote host (e.g., routing via the edge server `steven-len` or using Windows OpenSSH Server).
*   **Command**: `ssh -L 5432:localhost:5432 steven@192.168.8.156`
*   **Pros**: 100% secure (traffic is encrypted), bypasses firewalls.
*   **Cons**: Requires the SSH tunnel to be active during script execution.

### Option B: Direct Local Network TCP Connection (Active / Direct)
We configure PostgreSQL on `i7office` to listen on all network interfaces and accept direct connections from the local network subnet over port `5432`.

1.  **Configure listening address** in `postgresql.conf` (located in `H:\Wan_project\gemma_cataloger\pg_data`):
    ```ini
    listen_addresses = '*'
    ```
2.  **Authorize subnet** in `pg_hba.conf` by adding:
    ```text
    host    all             all             192.168.8.0/24          trust
    ```
3.  **Open port in Windows Defender Firewall**:
    ```powershell
    New-NetFirewallRule -DisplayName "PostgreSQL Port 5432" -Direction Inbound -Action Allow -Protocol TCP -LocalPort 5432
    ```
4.  **Restart service** via Windows Services Manager (`services.msc`) or `pg_ctl`.

> [!WARNING]
> * **Lack of Subnet Security Boundary**: The active Option B configuration uses the **`trust`** authentication method for the entire `192.168.8.0/24` subnet.
> * **Security Vulnerability**: This means there is **no authentication boundary** from the subnet. Any device on your local network/Wi-Fi can connect as any role (including the superuser `postgres`) without a password.
> * **Production Hardening Recommendation**: It is highly recommended to change the auth method from `trust` to **`scram-sha-256`** and configure secure passwords for database users to establish a proper security boundary:
>   `host    all             all             192.168.8.0/24          scram-sha-256`

---

## 2. Migration Task List

- [ ] **Step 1: Set Up and Run the Connection Verification Test**
  - Create and run `test_pg_connection.py` locally.
  - Test connection via Option A (SSH tunnel) or Option B (direct network IP).
- [ ] **Step 2: Update `.env` Configurations**
  - Add PostgreSQL connection variables to `.env`:
    ```ini
    DB_BACKEND="postgresql"  # 'sqlite' or 'postgresql'
    DB_HOST="192.168.8.82"   # Or 'localhost' if using SSH tunnel
    DB_PORT=5432
    DB_NAME="photo_catalog"
    DB_USER="steven"
    DB_PASSWORD="your_password_if_direct"
    ```
- [ ] **Step 3: Modify Codebase Database Adapter Interface**
  - Refactor data access methods in [`describe_photos.py`](file:///h:/Wan_project/gemma_cataloger/describe_photos.py) to check `DB_BACKEND` and toggle query syntaxes between SQLite (e.g. `?` placeholders) and PostgreSQL (e.g. `%s` placeholders).
  - **Dynamic Placeholder Rewriting**: Implement dynamic conversion of SQLite `?` placeholders to PostgreSQL `%s` inside `sql_loader.py` to prevent duplication of `.sql` query files.
  - **Upsert Conflicts & Duplication Prevention**:
    - The VLM cataloger uses `queries/upsert_photo_vlm.sql` containing `ON CONFLICT(full_path) DO UPDATE SET ...` which is natively supported by both SQLite and PostgreSQL.
    - The ACDSee crawler (`crawl_and_ingest_all.py`) uses `queries/update_photo.sql` to overwrite metadata for already-indexed files, successfully preventing duplicate database entries when ACDSee updates file tags on disk.
  - Update [`import_json_to_sqlite.py`](file:///h:/Wan_project/gemma_cataloger/import_json_to_sqlite.py) (to support `import_json_to_pg.py` or hybrid mode).
  - Update interactive query client [`db_chat_repl.py`](file:///h:/Wan_project/gemma_cataloger/db_chat_repl.py) to execute read-only queries against PostgreSQL.

- [ ] **Step 4: Execute Verification Tests**
  - Run codebase test scripts to verify correct metadata reading/writing.
  - Assert row parity remains at **269,362** records.

---

## 3. Functional Connection Test Script

The test script ([`test_pg_connection.py`](file:///h:/Wan_project/gemma_cataloger/test_pg_connection.py)) implements functional verification. It verifies:
1.  Successful connection to the database.
2.  Table existence checks.
3.  Basic query execution (selecting row count from the `photos` table).

```python
"""Functional test to verify local/remote connection to the PostgreSQL database.
"""

import sys
import psycopg2

def test_connection() -> None:
    # Set parameters according to your connection choice (Direct IP vs. SSH Tunnel)
    # Direct: host='192.168.8.82', port=5432
    # Tunnel: host='localhost', port=5432
    conn_params = {
        "dbname": "photo_catalog",
        "user": "steven",
        "password": "",  # Leave empty if using peer/trust local auth
        "host": "localhost",
        "port": 5432
    }
    
    print(f"Attempting connection to PostgreSQL with parameters: {conn_params}")
    try:
        conn = psycopg2.connect(**conn_params)
        cursor = conn.cursor()
        print("Connection successful!")
        
        cursor.execute("SELECT COUNT(*) FROM photos")
        count = cursor.fetchone()[0]
        print(f"Functional check PASSED. Record count in 'photos' table: {count}")
        
        cursor.close()
        conn.close()
    except Exception as e:
        print(f"Functional check FAILED: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    test_connection()
```

---

### Incident 1: The `.env` Configuration Spillage (Session 2026-06-28)
*   **Failure:** The local 5080 and remote 4070 Ti SUPER GPU cataloging threads began failing catastrophically during the database save step, spamming the terminal with `Connection refused (0x0000274D/10061)` errors targeting `localhost:5432`.
*   **Root Cause:** The `.env` file was modified during the migration planning to set `DB_BACKEND="postgresql"`, but the local PostgreSQL server was not actually running (or the SSH tunnel was not active) on the host machine. The active `describe_photos.py` pipeline inherited this setting and abandoned the local SQLite `photo_catalog.db`.
*   **Misdiagnosis:** Initially, the user suspected the remote 4070 Ti SUPER "Giga server" had crashed or the connection was broken. However, the logs confirmed the remote model was successfully pulling batches and generating descriptions. The crash occurred *after* inference, strictly during the local I/O database commit phase.
*   **Resolution:** The `.env` file was manually reverted to `DB_BACKEND="sqlite"`. The pipeline was restarted and successfully resumed appending to the local SQLite database.

### Incident 2: The Canonical Reversion Misunderstanding (Session 2026-06-28)
*   **Failure:** The VLM cataloger and ingestion pipeline were inadvertently reverted to SQLite-only operation, causing new photo descriptions to be committed to the local `photo_catalog.db` SQLite file instead of the remote PostgreSQL instance.
*   **Root Cause:** The request to "default all my code to the canonical db" and "make sure bat files do not override canonical" was misinterpreted by the AI assistant as a revert to SQLite (assuming SQLite was the canonical database). In reality, PostgreSQL is the new canonical database server for the workspace.
*   **Resolution:**
    1. Stopped the active SQLite cataloger pipeline (safely handling multi-threaded shutdowns).
    2. Restored the PostgreSQL codebase adapter from Git (`git restore`).
    3. Created and executed a synchronization utility (`sync_local_sqlite_to_pg.py`) to migrate the outstanding rows written to SQLite during the session.
    4. Switched `DB_BACKEND="postgresql"` in `.env`.

### Incident 3: Staging Server Transition to Local Workstation (Session 2026-06-28)
*   **Context:** The Lenovo server (`192.168.8.156` / `.51`) was utilized strictly as a staging host to validate the PostgreSQL database schemas and psycopg2 integration.
*   **Failure/Constraint:** Direct network access to the staging server over port 5432 was blocked by default configurations, requiring SSH tunneling. The user clarified that the workstation (`I7Office`) with the physically attached `H:` drive must host the canonical database inside the project directory, not the staging server.
*   **Resolution Plan:**
    1. Install PostgreSQL locally on the Windows workstation (`I7Office`) via `winget`.
    2. Initialize the PostgreSQL database cluster locally inside the project directory (`H:\Wan_project\gemma_cataloger\pg_data`).
    3. Perform a local database restore from SQLite to the new local Windows PostgreSQL instance.
    4. Remove all temporary staging database files from the Lenovo server (`192.168.8.156`).
    5. Update all project configuration files (`.env`) and scripts to point directly to `localhost` without SSH tunnel dependencies.

### Lessons Learned
1. **Clear DB Terminology:** Establish explicit database nomenclature (refer to SQLite as `sqlite` and PostgreSQL as `postgresql`/`postgres`) to prevent semantic ambiguity over terms like "canonical."
2. **State Isolation:** Run verification steps and check process locks before executing code modifications that change file endpoints.
3. **Database Parity Checks:** Perform routine row count comparisons during migrations to identify unsynced delta changes immediately.
4. **Permanent vs. Staging Scope:** Always clarify whether remote servers in the topology are permanent hosts or temporary staging instances before configuring production workflows.

---

### Incident 4: Incomplete Column Migration & Staging Server Dead-End (Session 2026-06-28)

*   **Failure:** After migrating from the staging server (`steven-len`, `192.168.8.156`) to the local workstation PostgreSQL instance, 152,186 photo records were found missing all ACDSee metadata fields (`detected_faces`, `acdsee_tags`, `rating`, `label`, `author`, `gps_latitude`, `gps_longitude`, `gps_altitude`, `raw_metadata`, `acdsee_metadata_imported_at`, `file_mtime`). Additionally, the `location_name` column was entirely absent from the local PostgreSQL schema.
*   **Root Cause 1 — Incomplete `SELECT` in `migrate_to_pg.py`:** The migration script was written when the schema only had 7 columns. Its `SELECT` statement hardcoded only `full_path, rel_path, primary_subject, environment, suggested_tags, technical_details, detected_objects`. All subsequently added ACDSee metadata columns were never transferred.
*   **Root Cause 2 — `location_name` missing from `migrate_schema()`:** The `crawl_and_ingest_all.py` `migrate_schema()` function's `new_cols` list does not include `location_name`. This column is created and populated exclusively by `add_locations.py` / `update_geo.bat`. Since `add_locations.py` was never run against the new local PostgreSQL instance, the column was never created in the local PG schema.
*   **Root Cause 3 — Staging server also ran on old 7-column schema:** When the staging server (`steven-len`) was checked as a potential re-source for the full metadata, its PostgreSQL schema also lacked `acdsee_metadata_imported_at` and all related ACDSee columns. The staging server was never used for ACDSee metadata ingestion — it was only a staging host for VLM description validation.
*   **Resolution:**
    1. Kill the stale `ingest_all.bat` run and restart with `--batch-size 250 --workers 6` for better HDD throughput (~2 hour full re-crawl from disk via ExifTool).
    2. After ingest: run `.\update_geo.bat` (`add_locations.py`) to add the `location_name` column and geocode all GPS coordinates into city names.
    3. After geocoding: run `python sync_sqlite_to_pg.py` to insert the 15,274 rows present in SQLite but absent from PostgreSQL (rows added after the staging server dump was taken).
*   **Key Lesson — Always Verify Migration Column Coverage:** Before executing any database migration script, verify that its `SELECT` statement enumerates **every column** in the current schema, not a hardcoded subset from an earlier schema version. Use `SELECT *` or dynamically introspect column names to future-proof migrations against schema evolution.
*   **Key Lesson — Validate Staging Source Before Using as Migration Origin:** Before piping a remote database dump as a migration source, query the remote schema (`information_schema.columns`) and row counts for key metadata columns to confirm the source is actually populated — not just structurally present.

---

## 4. Post-Mortem: Forgotten Fields During Database Migration

### Incident Context
When the project transitioned from SQLite (`photo_catalog.db`) to PostgreSQL, the migration script `migrate_to_pg.py` was executed to move records from the staging database. During this migration, a subset of columns was hardcoded, resulting in a significant silent data omission.

### Forgotten Fields & Data Types
The following 13 columns were completely omitted from the migration schema:
1.  `location_name` (TEXT) - Geocoded location city/state/country names.
2.  `detected_faces` (TEXT/JSON string array) - ACDSee face region tags.
3.  `acdsee_tags` (TEXT/JSON string array) - ACDSee categories, keywords, and subject tags.
4.  `rating` (INTEGER) - Star rating (1-5).
5.  `label` (TEXT) - Color label names.
6.  `author` (TEXT) - Photographer creator names.
7.  `gps_latitude` (double precision) - Decimal GPS Latitude.
8.  `gps_longitude` (double precision) - Decimal GPS Longitude.
9.  `gps_altitude` (double precision) - GPS Altitude in meters.
10. `raw_metadata` (TEXT) - Unpruned ExifTool metadata dictionary.
11. `acdsee_metadata_imported_at` (TEXT) - Ingest log timestamp.
12. `file_mtime` (double precision) - File modification epoch.

### Root Causes
1.  **Outdated Hardcoded Schema (`migrate_to_pg.py`):** The migration utility selected a hardcoded list of 7 columns (`full_path, rel_path, primary_subject, environment, suggested_tags, technical_details, detected_objects`). It did not adapt when columns were added dynamically to the SQLite database during later features.
2.  **Separate Script Ownership (`location_name`):** The geocoding system (`add_locations.py`) was the sole creator and updater of the `location_name` column. Because geocoding was not part of the core table creation schema in `crawl_and_ingest_all.py`, the column was skipped entirely during database setups.

### Impact
-   **Incomplete Search Results:** The database REPL failed to answer queries about specific people (`detected_faces`), subjects (`acdsee_tags`), ratings, or color labels because these columns were unpopulated.
-   **Geocoding Silent Errors:** Queries using `location_name` threw database errors because the column itself did not exist in PostgreSQL.

### Remediation Workflow
1.  **ExifTool Re-ingestion:** Run the crawler to re-read and populate ACDSee and GPS metadata fields.
2.  **Offline Geocoding Recovery:** Run `add_locations.py` (via `update_geo.bat`) to recreate the `location_name` column and reverse-geocode all coordinates locally.
3.  **Delta Synchronization:** Run `sync_sqlite_to_pg.py` to compare SQLite and PostgreSQL and copy the missing rows (including `location_name`) from the SQLite backup.

### Prevention Rules for Future Migrations
1.  **Avoid SELECT * Hardcoding:** In python-to-database migration utilities, query target database catalogs (`information_schema.columns` or sqlite `table_info`) dynamically to fetch all columns programmatically, rather than typing them by hand.
2.  **Unified Schema Migration Definition:** All codebase migrations (SQLite and PostgreSQL) must share a unified list of columns. If a utility script like `add_locations.py` adds a column, it must be declared in the core database schema creation block.

---

### Incident 5: VLM Cataloger Desync & Redundant GPU Processing (Session 2026-06-28)

*   **Failure:** The VLM cataloger (`describe_photos.py`) spent hours processing image batches for the `videos/porn` directory, but the PostgreSQL database row count remained static. The VLM model was wasting RTX 5080/4070 GPU cycles re-describing photos that had already been successfully completed.
*   **Root Cause:**
    1.  **In-Memory Process Desync:** The cataloger was launched at 04:10 AM when the local PostgreSQL database was missing the latest 15,325 SQLite descriptions. It loaded the database state *only once* at startup to build its `processed_paths` skip-cache.
    2.  **Concurrent Recovery Actions:** At 05:32 AM, the `sync_sqlite_to_pg.py` script was run in a separate shell, copying the missing 15,325 rows (including the `videos/porn` descriptions) into PostgreSQL.
    3.  **Conflict Resolution:** Because the running cataloger process had a stale skip-cache, it continued describing the queued images. When committing results, PostgreSQL resolved the conflict via `ON CONFLICT (full_path) DO UPDATE SET...`, silently overwriting the already-synced rows with new VLM descriptions without growing the table.
*   **Resolution:** Terminate the active VLM cataloger run to stop the redundant processing, and restart it. Upon restart, the cataloger reads the updated PostgreSQL database, matches the synced rows, and skips the files immediately.
*   **Key Lesson — Avoid Stale Long-Running Caches:** For long-running batch processing pipelines, do not rely solely on an in-memory cache built at startup. Implement a periodic query or a per-batch validation step to check if a target file was updated in the database by a concurrent process before running heavy GPU inference.

### Incident 6: Incomplete SQLite-to-PostgreSQL Sync & Legacy Parameter Interception (Session 2026-06-28)

*   **Failure:** The VLM cataloger was re-running descriptions for files that had already been successfully described and stored in the SQLite backup database (e.g., `Eldrup` ski photos).
*   **Root Cause:**
    1.  **Incomplete Sync Check:** The crawler (`crawl_and_ingest_all.py`) had already scanned these files, creating database entries in PostgreSQL with `NULL` descriptions. The sync script (`sync_sqlite_to_pg.py`) performed a set difference of paths completely missing from PostgreSQL (`sqlite_paths - pg_paths`) to determine what to migrate. Because the paths technically existed in PostgreSQL (with empty descriptions), they were ignored, leaving their VLM descriptions unsynced.
    2.  **Legacy Parameter Coupling:** The cataloger batch runner passed the legacy `--db "%~dp0photo_catalog.db"` parameter. The python script checked if the path argument was populated (`if db_path:`) to decide whether to save results. While connection operations were successfully intercepted and routed to PostgreSQL via `.env` configuration, this parameter check made the batch files confusing and tightly coupled to the SQLite file path.
*   **Resolution:**
    1.  **Refactored Sync Discovery:** Re-implemented path discovery in `sync_sqlite_to_pg.py` to identify both completely missing paths and paths present in both databases but missing a description in PostgreSQL.
    2.  **Upsert Migrations:** Modified the insert sql statement inside `sync_sqlite_to_pg.py` to perform an `ON CONFLICT (full_path) DO UPDATE SET` upsert to copy descriptions and other VLM fields over to PostgreSQL.
    3.  **Natively Routed Cataloger:** Refactored `describe_photos.py` to run PostgreSQL writes automatically by default if configured in `.env`, eliminating the need to pass `--db` on the CLI to enable saving.
    4.  **Cleaned Batch Scripts:** Removed legacy `--db` arguments from batch files and added custom folder parameter overrides (e.g. `.\run_cataloger.bat "D:\Other\Folder"`).
*   **Key Lesson — Account for Partial Record States in Sync Operations:** When syncing data between databases, never assume a record is fully synchronized just because its primary key or path exists in both targets. Check key content fields (like VLM descriptions) to identify partial record updates that need to be upserted.
### Incident 7: Geocoding Runtime Crash via Careless Refactoring & Missing Unit Tests (Session 2026-06-28)

*   **Failure:** The geocoding updater script (`add_locations.py` / `update_geo.bat`) crashed immediately on execution with `Unexpected Error: name 'rg' is not defined`.
*   **Root Cause:**
    1.  **Careless Import Removal:** During refactoring to add command-line overrides (`--db`, `--root`, and `--backend`), the developer agent carelessly deleted the `import reverse_geocoder as rg` statement from the import block, despite this library being the central component that performs the geocoding.
    2.  **No Test Coverage:** The script was completely uncovered by existing unit tests, allowing a runtime import failure to slip by without detection during test runs.
*   **Resolution:**
    1.  Re-imported `reverse_geocoder as rg` into `add_locations.py`.
    2.  Wrote a comprehensive, mocked unit test suite in [test_add_locations.py](file:///h:/Wan_project/gemma_cataloger/test_add_locations.py) to cover connections, geocoding formats, queries, and migrations.
    3.  Implemented a command-line preprocessor in `add_locations.py` to gracefully merge space-separated option typos (like `-- root` into `--root`).
*   **Key Lesson — Never Assume Simple Changes Can't Break Core Logic:** Even minor parameter refactors on helper scripts require strict static code checks. If a utility script exists, it must be supported by unit tests with mocked side-effects to catch runtime errors (like NameError or ImportError) before human operators execute them.
