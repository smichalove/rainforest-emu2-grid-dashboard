# Model Comparison & Semantic Drift Evaluation Report

Generated on: 2026-05-29 22:46:35

This report benchmarks the qualitative summaries, constraint compliance, and inference speed of the local **Gemma 2** edge models against the Google Cloud **Gemini 2.5 Flash** baseline.

## 1. Executive Performance Summary

| Metric | Vertex Gemini 2.5 Flash | Local Gemma 2 2B | Local Gemma 2 9B |
| :--- | :--- | :--- | :--- |
| **Avg Inference Speed** | 67.00s | 11.63s | N/A |
| **Avg Output length** | 308 tokens | 200 tokens | N/A tokens |
| **Constraint Compliance** | 0 / 3 (0%) | 0 / 3 (0%) | N/A |

## 2. Detailed Scenario Analysis

### Scenario 1: High Solar Export Day (2026-05-27)

| Model | Inference Time | Length (tokens) | Formatting | Semantic Overlap (vs Gemini) |
| :--- | :--- | :--- | :--- | :--- |
| gemini-2.5-flash | 70.07s | 337 | ❌ Fail | Baseline |
| gemma2:2b | 10.83s | 198 | ❌ Fail | 25.8% |

#### Mathematical & Fact Extraction Parity

| Extraction Fact | Baseline Gemini 2.5 Flash | Gemma 2 2B | Gemma 2 9B |
| :--- | :--- | :--- | :--- |
| **Net Import** | 16.88 kWh | 17.34 kWh | Not Found |
| **Net Export** | 33.57 kWh | 33.57 kWh | Not Found |
| **Se Gen** | 19.62 kWh | 19.62 kWh | Not Found |
| **Credit** | $3.21 | $3.08 | Not Found |

#### Output Summary Contents

**gemini-2.5-flash** (70.1s, 337 tokens) (Violations: Line 8 exceeds 80 characters (114 chars), Line 9 exceeds 80 characters (908 chars)):
```
Data analyzed from 2026-05-27 00:00 to 2026-05-27 23:00.
Energy Snapshot:
Total Net Imported: 16.88 kWh (Cost: $3.21)
Total Net Exported: 33.57 kWh (Credit: $6.38)
Total SolarEdge Generated: 19.62 kWh
Total Chillicon Generated (Actual/Inferred): 22.68 kWh (3.66 kWh inferred)
Total Home Consumption: 27.28 kWh
Peak Net Grid Import: 2.41 kW (23:00) | Peak Net Grid Export: 5.61 kW (13:00) | Peak SolarEdge PV: 3.13 kW (12:00)
Summary: The system imported 16.88 kWh from the grid, incurring a cost of $3.21. In contrast, it exported 33.57 kWh, earning a credit of $6.38, resulting in a positive net financial outcome of $3.17 for the day. SolarEdge generated a substantial 19.62 kWh of power, showcasing its primary contribution. The Chillicon system produced 22.68 kWh, with 3.66 kWh of this generation inferred during periods where direct data was missing but grid export suggested solar activity. Total home consumption for this 24-hour period was approximately 27.28 kWh, indicating effective utilization of generated energy. The battery charged 0.24 kWh at 13:00 but showed no discharge activity, confirming the absence of any PSE Flex events. Its State of Charge ended the day at 0.0%, suggesting it was fully depleted or manually turned off. Overall, the dual solar setup achieved significant energy independence and net credit.
2026-05-27 23:00
```

**gemma2:2b** (10.8s, 198 tokens) (Violations: Line 11 exceeds 80 characters (552 chars)):
```
Key Statistics:

Total Net Imported: 17.344 kWh
Total Net Exported: 33.569 kWh
SolarEdge Generated: 19.624 kWh
Net Energy Credit: $3.08
Peak Net Grid Demand: 2.406 kW
Peak SolarEdge PV: 3.130 kW
Inferred Chillicon Contribution: 15.767 kWh

Summary:  SolarEdge generated a substantial amount of energy (19.624kWh), outperforming total home consumption (22.183kWh). The net exported energy was significant, reflecting efficient usage and potential battery operation for grid support. Notably, the peak SolarEdge PV production exceeded the measured peak demand (3.130 kW) with solar contribution. Chillicon's estimated contribution suggests some level of assistance.  The Net Energy Credit reflects a positive result, with implications for PSE billing. This analysis was performed on 2026-05-27.
```

---

### Scenario 2: High Grid Import Day (2026-05-26)

| Model | Inference Time | Length (tokens) | Formatting | Semantic Overlap (vs Gemini) |
| :--- | :--- | :--- | :--- | :--- |
| gemini-2.5-flash | 45.26s | 317 | ❌ Fail | Baseline |
| gemma2:2b | 12.62s | 210 | ❌ Fail | 34.0% |

#### Mathematical & Fact Extraction Parity

| Extraction Fact | Baseline Gemini 2.5 Flash | Gemma 2 2B | Gemma 2 9B |
| :--- | :--- | :--- | :--- |
| **Net Import** | Not Found | 21.08 kWh | Not Found |
| **Net Export** | Not Found | 10.78 kWh | Not Found |
| **Se Gen** | Not Found | 7.12 kWh | Not Found |
| **Credit** | $0.19 | $0.29 | Not Found |

#### Output Summary Contents

**gemini-2.5-flash** (45.3s, 317 tokens) (Violations: Line 12 exceeds 80 characters (898 chars)):
```
Data analyzed from 2026-05-26 00:00 to 2026-05-26 23:00

Dashboard Statistics:
Total Net Imported (kWh): 21.601
Total Net Exported (kWh): 10.781
SolarEdge Generated (kWh): 7.123
Inferred Chillicon Contrib. to Export (kWh): 1.134
Net Energy Credit: $0.19
Peak Net Grid Demand (kW): 3.024
Peak SolarEdge PV (kW): 4.197

Over the past 24 hours, the user imported 21.601 kWh from the grid and exported 10.781 kWh, resulting in a net credit of $0.19. SolarEdge generated a total of 7.123 kWh, with a peak production of 4.197 kW at 17:00. The battery system actively participated in two PSE Flex events between 17:00 and 18:00, discharging 7.250 kWh to the grid at the higher $0.50/kWh rate. This strategic discharge contributed significantly to the overall energy credit. The battery's State of Charge dropped from 69.0% to 44.0% during the Flex events and then recharged 2.946 kWh from the grid between 19:00-21:00, reaching 43.5% SoC, which is normal post-Flex behavior. Chillicon generation data was unavailable, but an estimated 1.134 kWh was inferred to contribute to grid exports during 13:00 and 18:00. Total home consumption for this period was approximately 23.381 kWh, demonstrating efficient energy management.

last data point date and time is: 2026-05-26 23:00
```

**gemma2:2b** (12.6s, 210 tokens) (Violations: Line 11 exceeds 80 characters (602 chars)):
```
Key Statistics:

Total Net Imported: 21.079 kWh
Total Net Exported: 10.782 kWh
SolarEdge Generated: 7.123 kWh
Net Energy Credit: $0.29
Peak Net Grid Demand: 3.024 kW
Peak SolarEdge PV: 4.197 kW
Inferred Chillicon Contribution: 1.134 kWh

Summary:  The grid saw a net import of 21.079 kWh and an export of 10.782 kWh, while SolarEdge generated 7.123 kWh for the day.  A credit of $0.29 was received, indicating the use of net-zero energy credits. The peak grid demand reached 3.024 kW, driven by a peak solar output of 4.197 kW from SolarEdge. A slight dip in battery usage is indicated through the in-ferred Chillicon contribution of 1.134 kWh. This likely corresponds to the  flex events which utilized battery discharge. The net energy credit will impact the PSE billing in accordance with local regulations. Data analyzed for 2026-05-26.
```

---

### Scenario 3: Battery Dispatch / Flex Event Day (2026-05-28)

| Model | Inference Time | Length (tokens) | Formatting | Semantic Overlap (vs Gemini) |
| :--- | :--- | :--- | :--- | :--- |
| gemini-2.5-flash | 85.66s | 270 | ❌ Fail | Baseline |
| gemma2:2b | 11.44s | 192 | ❌ Fail | 33.8% |

#### Mathematical & Fact Extraction Parity

| Extraction Fact | Baseline Gemini 2.5 Flash | Gemma 2 2B | Gemma 2 9B |
| :--- | :--- | :--- | :--- |
| **Net Import** | 6.66 kWh | Not Found | Not Found |
| **Net Export** | 33.88 kWh | Not Found | Not Found |
| **Se Gen** | 19.01 kWh | Not Found | Not Found |
| **Credit** | $7.61 | Not Found | Not Found |

#### Output Summary Contents

**gemini-2.5-flash** (85.7s, 270 tokens) (Violations: Too many lines: 16 (Limit is 15), Line 14 exceeds 80 characters (683 chars)):
```
Data analyzed from 2026-05-28 00:00 to 2026-05-28 19:00

Total Net Imported: 6.657 kWh
Total Net Exported: 33.881 kWh
SolarEdge Generated: 19.009 kWh
Chillicon Generated (Actual): 21.920 kWh
Inferred Chillicon Contribution: 0.000 kWh
Net Energy Cost/Credit: 7.61
Peak Net Grid Demand: 1.044 kW
Peak Net Grid Export: 4.640 kW
Peak SolarEdge PV: 2.710 kW
Peak Chillicon PV: 3.840 kW

During the period from 2026-05-28 00:00 to 2026-05-28 19:00, the system achieved a net 7.61 credit. A total of 6.657 kWh was imported from the grid, while 33.881 kWh was exported, driven by strong solar production. SolarEdge generated 19.009 kWh (peak 2.710 kW), and Chillicon systems contributed 21.920 kWh (peak 3.840 kW) with no additional kWh inferred. The battery discharged 7.368 kWh across 2 PSE Flex event hours, earning premium credit, and charged 0.234 kWh. Total home consumption was 20.970 kWh. Battery charging, like the 0.234 kWh at 12:00, is normal system behavior for maintaining capacity, and this period did not show the typical 0.96 kWh post-Flex battery recharge.

2026-05-28 19:00
```

**gemma2:2b** (11.4s, 192 tokens) (Violations: Line 1 exceeds 80 characters (265 chars), Line 3 exceeds 80 characters (473 chars)):
```
Key statistics are as follows: Total Net Imported = 6.656 kWh, Total Net Exported = 33.882 kWh, SolarEdge Generated = 19.009 kWh, Net Energy Credit = $7.46, Peak Net Grid Demand = 1.866 kW, Peak SolarEdge PV = 2.710 kW, Inferred Chillicon Contribution = 10.156 kWh.

Summary: Our system experienced a net import of 6.656 kWh and exported 33.882 kWh today.  SolarEdge generated 19.009 kWh of energy, which was significantly lower than our total home consumption at 19.839 kWh. Battery status suggests no Flex events occurred today. The Chillicon contribution was 10.156 kWh, likely due to a solar energy backup system or a combined grid and battery storage solution. Our net energy credit is $7.46, which may be reflected in our PSE billing.

Data analyzed for 2026-05-28.
```

---

## 3. Conclusions and Recommendation

- **Computational Overhead**: Local edge inference on the Jetson Orin Nano is fully self-contained ($0 token cost). Gemma 2 2B provides blistering speed (~10-15s) and fits easily in system memory. Gemma 2 9B provides superior logical reasoning but requires significant unified memory and runs slower.
- **Parity Analysis**: Analyze the semantic overlap and numeric fact extraction to determine if Gemma 2 can fully substitute Gemini 2.5 Flash without manual parameter tweaking.
