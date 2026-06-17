# Implementation Plan - Dedicated 14-Day History AI Summary

This plan outlines the design and implementation details for generating, verifying, streaming, and rendering a dedicated 14-day history AI summary on Slide 2 ("Zoom - 14-Day History"), resolving the current mismatch where Slide 2 overlays the 24-hour summary.

## Proposed Changes

### Configuration & Prompts

#### [NEW] [gemma_history_prompt.txt](file:///Users/treven/Documents/rainforest-emu2-grid-dashboard/gemma_history_prompt.txt)
* Proposer prompt for the 14-day history view.
* Instructs Gemma to act as a microgrid history analyst, examining the cumulative metrics over the past 14 days (grid imports/exports, solar generation, peak grid demand, battery round-trip efficiency, and average/min/max appliance loads).
* **Battery Cycle & Financial Credits Requirement**: Instructs the model to explicitly evaluate:
  * The number of PSE Flex event days (days where battery discharge > 0.1 kWh).
  * Total energy discharged during Flex events (kWh) and premium credits earned at **$0.50/kWh**.
  * Total generative grid export energy (solar export, kWh) and standard credits earned at the lower rate of **$0.19/kWh**.
  * Compare the value of premium Flex discharge against the standard generative export credit.
* Restricts salutations and conversational greetings ("Good morning", etc.) and enforces plain text.

#### [NEW] [gemma_verify_history_prompt.txt](file:///Users/treven/Documents/rainforest-emu2-grid-dashboard/gemma_verify_history_prompt.txt)
* Verifier prompt for the 14-day history view.
* Instructs the verifier to inspect the proposer's history draft against the raw 14-day telemetry stats, correcting any inaccuracies or hallucinations.
* Enforces strict validation of the battery charge/discharge figures, RTE calculations, Flex event counts, and financial credit amounts.
* Restricts salutations and enforces plain text.

### Protocol Definitions

### [MODIFY] [grid_telemetry.proto](file:///Users/treven/Documents/rainforest-emu2-grid-dashboard/protos/grid_telemetry.proto)
* Modify `AnalysisResponse` to add a new string field for the completed history summary:
  ```proto
  string history_explanation = 18;
  ```
* Modify `AnalysisStreamResponse` to add a new string field for streaming history token chunks:
  ```proto
  string history_token_chunk = 4;
  ```

### gRPC Server & Stager

#### [MODIFY] [grpc_server.py](file:///Users/treven/Documents/rainforest-emu2-grid-dashboard/dashboard_modules/grpc_server.py)
* Update `GetTelemetryAnalysisStream`:
  1. Stream Slide 1 summary tokens (`summary_token_chunk`).
  2. Stream Slide 2 history summary tokens (`history_token_chunk`).
  3. Stream Slide 3 DFT explanation tokens (`dft_token_chunk`).
* When `local_proposer_active` is True:
  * Read the new `gemma_history_prompt.txt` template.
  * Run the local proposer model (Gemma 2B) to generate a draft history summary.
  * Format `gemma_verify_history_prompt.txt` using the 14-day stats and the draft.
  * Query the remote verifier model (Gemma 9B) to stream verified history tokens.
* When running in fallback mode:
  * Stream fallback remote summary tokens directly to `history_token_chunk`.

#### [MODIFY] [stage_local_summary.py](file:///Users/treven/Documents/rainforest-emu2-grid-dashboard/stage_local_summary.py)
* In `calculate_analysis_metrics_and_prompts`:
  * Calculate cumulative metrics and flow stats over the last 14 days using `calculate_deltas(now - 14d)` and `calculate_flow_stats(now - 14d)`.
  * Compute battery round-trip efficiency (RTE) specifically for the 14-day window.
  * **14-Day Financial & Flex Event Analysis**:
    * Segment the 14-day battery discharge data by calendar day to count the number of days with battery discharge > 0.1 kWh (number of Flex events).
    * Sum the total battery discharge during those Flex days to calculate premium credits: `flex_credits = total_flex_discharge_kwh * 0.50` dollars.
    * Use cumulative grid export over the 14 days to calculate standard generative credits: `standard_credits = total_grid_export_kwh * 0.19` dollars.
  * Load and format the new `gemma_history_prompt.txt` template with these extra fields.
* In `format_verify_prompts`:
  * Add a helper to format `gemma_verify_history_prompt.txt` with the 14-day telemetry, credit calculations, and proposer history draft.
* Update `_run_analysis_workflow_inner` to also run proposer-verifier passes for the history summary.
* Save the resulting history summary to `gemini_summary.json` under the key `"history_explanation"`.

### GUI Dashboard & Renderer

#### [MODIFY] [dashboard.py](file:///Users/treven/Documents/rainforest-emu2-grid-dashboard/dashboard.py)
* Initialize `self.local_history_text = "Awaiting 14-day history summary..."` during startup.
* Load `"history_explanation"` from `gemini_summary.json` if it exists.
* In `update_summary_display`:
  * If `self.current_slide == 1`: Set `self.summary_text_obj` to show the 24-hour summary text (`self.baseline_text` + `self.local_delta_text`).
  * If `self.current_slide == 2`: Set `self.summary_text_obj` to show the 14-day history summary text (`self.local_history_text`).
  * If `self.current_slide == 3`: Set `self.summary_text_obj_freq` to show the DFT spectrum text (`self.local_dft_text`).
* In `LocalDeltaLoop`:
  * Read `history_explanation` from `gemini_summary.json`.
  * Append incoming `history_token_chunk` stream updates to `self.local_history_text` and update the UI.
  * Write `history_explanation` back to `gemini_summary.json` when the update cycle completes.

#### [MODIFY] [render_local_plot.py](file:///Users/treven/Documents/rainforest-emu2-grid-dashboard/render_local_plot.py)
* Replicate the logic from `dashboard.py`:
  * Initialize `self.local_history_text` and parse it from `gemini_summary.json`.
  * Update `update_summary_display` to display the history summary on Slide 2 and 24-hour summary on Slide 1.

### Build and Deployment Staging

#### [MODIFY] [redeploy.sh](file:///Users/treven/Documents/rainforest-emu2-grid-dashboard/redeploy.sh)
* Ensure compilation command `./venv/bin/python3 -m grpc_tools.protoc` runs first to compile the updated `.proto` contract.

---

## Verification Plan

### Automated Tests
* Run `redeploy.sh` to compile the updated proto files and execute the standard unit/contract tests.
* Update `tests/emulation/test_grpc_contract.py` or other tests to mock/verify the new `history_token_chunk` field on the stream response.

### Manual Verification
* Run the emulation script `scratch/emulate_with_no_prod_writes.py` to verify:
  1. 14-day metrics calculations are processed successfully.
  2. Local proposer generates a draft history summary, and remote verifier refines it.
  3. Tokens are streamed correctly and written to `gemini_summary.json` as `history_explanation`.
* Run `./plot_and_open.sh` to generate the three slide previews.
* Open `dashboard_preview_slide2.jpeg` to visually inspect that the 14-day history summary is rendered correctly on Slide 2, and `dashboard_preview_full.jpeg` (Slide 1) to confirm that the 24-hour summary is rendered correctly on Slide 1.
