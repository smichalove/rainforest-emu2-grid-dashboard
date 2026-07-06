# Staging Edge AI Performance & Power Benchmark Report

This document records the performance, latency, and power consumption metrics of local Edge AI model inference workloads executed across the staging hardware cluster.

*   **Date:** July 6, 2026
*   **Target Model:** `gemma2-9b-custom:latest` (Size: 5.8 GB, Quantization: `Q4_K_M`)
*   **Infrastructure Context:** Primary dedicated AI inference servers.

---

## 1. Network Topology under Test

The staging cluster consists of the following machines powered by a shared Uninterruptible Power Supply (UPS):
1.  **`len-big` (192.168.8.51):** Xeon Workstation (Primary Staging Node)
2.  **`steven-len` (192.168.8.156):** Xeon Workstation (Secondary Staging Node)
3.  **`ubunto-giga` (192.168.8.193):** Ubuntu AI Server (Idle during test)
4.  **Network Hardware:** 2x Managed Ethernet Switches

---

## 2. Power Consumption (Concurrent Load)

To measure peak load, identical 2048-token generation tasks were triggered concurrently on both `len-big` and `steven-len`.

*   **Combined Peak Load (UPS Registry):** **`329 Watts`**
*   **Combined Idle Baseline (UPS Registry - both hosts idle):** **`167 Watts`**
*   **Net Dynamic Inference Overhead:** **`162 Watts`** (approx. **`81 Watts`** per active GPU/workstation under active inference load)

This represents an extremely efficient total power envelope for running dual concurrent 9B parameter model inferences on dedicated local hardware.

---

## 3. Hardware Performance Metrics

*   **Benchmark Prompt:** *"Write a detailed Python script to calculate the Discrete Fourier Transform (DFT) from scratch, explain how the mathematics works in a 400-word essay, and list the differences between DFT and FFT."*
*   **Inference Options:** `num_predict: 2048`, `temperature: 0.2`, `stream: false`

### Summary Comparison Table (Warm VRAM Caching)

| Host / Node | IP Address | Decode Speed | Prefill (Prompt) Speed | Generation Output |
| :--- | :--- | :--- | :--- | :--- |
| **`len-big`** | `192.168.8.51` | **`6.68 tokens/sec`** | **`118.2 tokens/sec`** | 683 tokens |
| **`steven-len`** | `192.168.8.156` | **`6.70 tokens/sec`** | **`122.1 tokens/sec`** | 637 tokens |

---

## 4. Key Architectural Observations

### A. VRAM Caching Impact (Cold vs. Warm Prefill)
*   **Cold Boot Prefill:** On the initial run before weights were fully cached/warmed in GPU memory, `len-big` prefilled at **`118.2 tokens/sec`** (0.42s) while `steven-len` took **`35.2 tokens/sec`** (1.42s). 
*   **Warm Boot Prefill:** Once the model was resident in the VRAM, both systems prefilled at identical speeds of **`~120 tokens/sec`**.
*   **Observation:** The startup speedup indicates faster system RAM access or superior PCIe Gen bandwidth configuration on `len-big` when doing cold model loading/swapping from storage/system memory.

### B. Decoding Equivalence
*   Both workstations decode at a matching speed of **`~6.7 - 7.0 tokens/sec`** under parallel load, verifying optimal GPU processing alignment.
