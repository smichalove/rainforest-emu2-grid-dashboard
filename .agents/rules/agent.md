---
trigger: always_on
description: Security (gitleaks) and Google style Python readability rules (strict typing, docstrings, inline comments).
---

# Agent Development Guidelines

This document serves as the official instruction manual for any AI agent or developer contributing to this repository. Always refer to these guidelines before writing or modifying any code.

---

## 1. Security Compliance & Pre-Commit Checks

- **Gitleaks Execution:** 
  > [!IMPORTANT]
  > You must run `gitleaks` to scan for secrets and sensitive information before any git commit or sync operation.
  - Under no circumstances should hardcoded credentials, serial device addresses that leak proprietary details, or personal network settings be committed.

---

## 2. Python Coding & Readability Standards

All Python code must strictly follow the Google Python Style Guide and readability standards. Key requirements include:

### Strict Type Hinting
- Every function, method, and class attribute must be fully type-annotated.
- Avoid using `Any`. Be as specific as possible (e.g., use `List[str]`, `Dict[str, int]`, `Optional[float]`, etc.).

### Mandatory Docstrings
- **Classes:** Every class must include a docstring explaining its purpose, state, and key responsibilities.
- **Functions and Methods:** Every function/method must contain a comprehensive docstring that details:
  - The behavior and purpose of the function.
  - **Args:** Clearly listed arguments with their expected types and descriptions.
  - **Returns:** The return type and description of the output.
  - **Raises:** Any exceptions that could be raised by the function.
  
  Example:
  ```python
  def read_serial_data(port: str, timeout: float) -> str:
      """Reads raw XML telemetry from the EMU-2 serial port.

      Args:
          port: The filesystem path to the serial device (e.g., '/dev/ttyACM0').
          timeout: The read timeout in seconds.

      Returns:
          A string containing the raw XML payload received.

      Raises:
          SerialException: If the serial interface cannot be accessed.
      """
  ```

### Descriptive Inline Comments
- Write descriptive, inline comments for non-trivial logic blocks.
- Document hardware-specific behavior (e.g., Raspberry Pi serial communication, Tkinter UI scaling hacks, X11 configuration workarounds).
- Comments should explain the *why* behind the implementation decisions, not just *what* the code does, to enable other developers and users to quickly understand and debug the dashboard.

---

## 3. Prompt Management Standards

- **External Prompt Files:** 
  > [!IMPORTANT]
  > LLM prompts shall always be drafted in separate external `.txt` files rather than hardcoded in the codebase.
  - The application must load and refresh the prompt template from the file on disk dynamically at runtime (e.g., right before invoking the model).
  - This allows developers or operators to tweak system instructions and prompt context in real-time without restarting or modifying the core dashboard source code.

---

## 4. Command Execution Guidelines

- **Command Explanations:**
  > [!IMPORTANT]
  > For every command executed or proposed on the terminal, the agent must provide a quick, one-line explanation of what the command does and why it is being executed.

---

## 5. Dependency Pinned Requirements

- **Strict Dependency Pinning:**
  > [!IMPORTANT]
  > All Python dependencies listed in `requirements.txt` must be strictly pinned to exact versions (using `==` instead of loose range operators like `>=` or unpinned packages).
  - This ensures build determinism, prevents dependency drift, and complies with Snyk security scanner requirements to prevent vulnerable older package resolutions.

---

## 6. UI & Design Refactoring Guidelines

- **No Unilateral Design Changes:**
  > [!IMPORTANT]
  > You must never make unilateral visual, structural, or layout design changes to the user interface (UI) without first presenting proposals, mockups, or options to the user for feedback and approval.
  - Attempt to resolve visual bugs (such as overlap, alignment, or readability issues) using local style adjustments (e.g. opacity, colors, margins, font sizes) before proposing any major structural layout redesign.

---

## 7. Git Commit & Sync Guidelines

- **Confirm Staging, Committing, and Pushing:**
  > [!IMPORTANT]
  > Never automatically stage, commit, or push files to git. You must always present the changes to the user first and ask for explicit confirmation that they are ready to commit and push.
  - This prevents cluttering the git history with incomplete or untested incremental changes, allowing the user to verify the application's working state first.

- **Avoid Chaining Execution Commands:**
  > [!IMPORTANT]
  > Never execute multiple modifying or deployment commands (such as copying files, installing packages, restarting processes, or running git operations) back-to-back in a single turn.
  - Break tasks into individual steps, check in with the user after key actions, and let them verify or provide feedback rather than forcing them to review and approve a large chain of commands all at once.

- **Version Control for Major Releases:**
  > [!IMPORTANT]
  > When delivering major feature updates or architectural shifts (such as V3), always create an annotated Git release tag (e.g., `git tag -a v3.0.0 -m "Release v3.0.0: ..."`), and push the tag to all remotes (`origin` and `backup`) to maintain clear historical records and prevent version confusion.

---

## 8. User Approval & Advice Guidelines

- **Always Wait for Explicit Consent on Advice/Proposals:**
  > [!IMPORTANT]
  > When proposing a design change, optimization, or architectural decision (such as altering a polling interval or adding a background loop), you must explain your advice/proposals and wait for the user's explicit consent or approval *before* implementing or executing the changes.
  - Never modify files or run deployment commands based on a proposal you just introduced without first letting the user review and confirm they want to proceed with that approach.

- **Present Multiple Options (High vs. Low Performance/Risk):**
  > [!IMPORTANT]
  > When proposing technical implementations, system configurations, coding designs, database queries/operations, or deployment paths, you must never unilaterally present a single solution, command, or implementation. You MUST present at least two options:
  > 1. An **Optimized / High-Performance Option** (detailing performance benefits, prerequisites, setup/compilation speed, and algorithmic efficiency).
  > 2. A **Simple / Low-Performance fallback Option** (detailing trade-offs, timelines, resource constraints, and ease of implementation).
  - Explicitly call out estimated execution times, risk of data loss, system overhead, and network/hardware bottlenecks for each option so the user can make an informed decision.
  - Use the choice between a slow live `dd` copy vs. a fast offline Mac clone as a standard baseline example of trade-offs in execution time and risk.

---

## 9. Log Inspection Guidelines

- **Human-in-the-Loop Log Sharing:**
  > [!IMPORTANT]
  > When executing background tasks, scripts, or system commands, you must keep the user actively in the loop by sharing and summarizing log outputs.
  - Never parse or analyze logs silently to make internal design decisions without explaining the log findings to the user first.
  - When debugging or running emulation scripts, output status details and progress metrics to the user so they can follow along.

---

## 10. Network Topology & Hostnames

- **Jetson Orin Nano (GPU AI Server)**: `steven@192.168.8.68` (or `nvjetson`)
- **Raspberry Pi (Kiosk Display)**: `steven@rainforestpi` (or `192.168.8.70`)

## 11. Avoid hardcoding values
- use parameters when possible or run time args
- when using global values they should be fomatted like SUMMARY_COLOR: str = 'deepskyblue' and placed after imports (where logical)  or like SUMMARY_FONT_SIZE: int = 10

---

## 12. Local Render Verification Rule

- **Always Verify Local Render Prior to Production Deployment:**
  > [!IMPORTANT]
  > Before committing, pushing, or redeploying any GUI/rendering code to production (the kiosk), you must always generate and verify the local plot rendering (e.g. running `./plot_and_open.sh` or `render_local_plot.py`) to confirm that all slides, watermarks, data lines, and stacked bar charts display correctly.

---

## 13. Production Deployment Safety (LGTM Rule)

- **Mandatory Code Diff & LGTM Before Deployment:**
  > [!IMPORTANT]
  > You must never run any deployment commands or scripts (such as `./redeploy.sh`) to copy code to production hardware (the Raspberry Pi kiosk or the Jetson server) without first:
  > 1. Running `git diff` to view the exact changes.
  > 2. Presenting the detailed code differences to the user.
  > 3. Obtaining their explicit **"LGTM"** or **"Approve deployment"** confirmation.
  - This ensures that unreviewed, experimental, or unapproved code changes in the workspace are never accidentally pushed to production.

---

## 14. High-Risk & Destructive Operations Guardrails

- **Mandatory Caution Warnings for Destructive Commands:**
  > [!CAUTION]
  > Before executing or proposing any command or script that performs destructive operations on disks, filesystems, or critical directories (such as `dd`, `mkfs`, `fdisk`, or recursive deletions), you MUST explicitly warn the user.
  - The warning must use a prominent `> [!CAUTION]` block detailing the exact target device or folder path, the risk of permanent data loss, and a prompt for verification.
  - Never execute or present a destructive command box without first providing this explicit warning.