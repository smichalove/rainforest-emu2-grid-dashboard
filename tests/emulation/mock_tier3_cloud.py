"""Mock Tier 3 cloud escalation handler.

Simulates the cloud-based Deep Diagnostic agent handover when an anomaly is
detected on the edge stager (Tier 2). Resolves diagnostics locally using
template structures and logs outcomes to a local audit log for verification.
"""

import datetime
import json
import os
from typing import Any, Dict, Optional


class MockTier3CloudResponder:
    """Simulates a cloud-based Deep Diagnostic service.

    Provides a localized offline fallback that mimics Vertex AI cloud diagnostics
    and logs escalated anomalies to an audit log.
    """

    def __init__(self, audit_log_path: Optional[str] = None) -> None:
        """Initializes the responder with an optional audit log path.

        Args:
            audit_log_path: Path to write the JSON escalation audit log.
        """
        if audit_log_path is None:
            # Default to backups/escalations.json in the project root
            self.audit_log_path: str = os.path.abspath(
                os.path.join(os.path.dirname(__file__), "..", "..", "backups", "escalations.json")
            )
        else:
            self.audit_log_path = audit_log_path

    def process_escalation(
        self, slice_id: str, anomaly_type: str, metrics: Dict[str, float]
    ) -> Dict[str, Any]:
        """Processes an escalated microgrid anomaly slice and generates diagnostics.

        Args:
            slice_id: Unique identifier for the anomalous telemetry slice.
            anomaly_type: Description of the anomaly (e.g., 'Peak Demand Spike', 'Battery Inefficiency').
            metrics: Dict of key metrics that triggered the escalation.

        Returns:
            A dictionary containing the cloud diagnostic summary and metadata.
        """
        # Ensure target backup directory exists
        os.makedirs(os.path.dirname(self.audit_log_path), exist_ok=True)

        timestamp_str: str = datetime.datetime.now().isoformat()
        
        # Construct detailed mock deep diagnostic report based on anomaly type
        diagnostic_summary: str = ""
        action_recommendation: str = ""
        
        if "spike" in anomaly_type.lower() or "peak" in anomaly_type.lower():
            diagnostic_summary = (
                f"Cloud analysis of slice {slice_id} indicates a major grid consumption spike. "
                f"Peak load reached {metrics.get('peak_kw', 0.0):.3f} kW. "
                "This load profile matches heavy consumer appliance cycles (e.g., HVAC start-up sequence) "
                "operating concurrently with low battery storage discharge buffer capacity."
            )
            action_recommendation = (
                "Disable auxiliary high-load appliance start-ups during peak utility pricing periods. "
                "Optimize SolarEdge battery discharge schedule to begin 30 minutes earlier."
            )
        elif "battery" in anomaly_type.lower() or "rte" in anomaly_type.lower():
            diagnostic_summary = (
                f"Cloud analysis of slice {slice_id} indicates severe battery degradation or round-trip inefficiency. "
                f"Computed Round-Trip Efficiency (RTE) was {metrics.get('battery_rte', 0.0):.1f}%. "
                "This is significantly below the acceptable 65% efficiency gate, indicating thermal stress or cell fault."
            )
            action_recommendation = (
                "Initiate local battery diagnostic test cycle. Flag for field maintenance if RTE remains below 65% "
                "over the next 3 charge/discharge cycles."
            )
        else:
            diagnostic_summary = (
                f"Cloud analysis of slice {slice_id} detected a spectral rhythm disruption or unknown anomaly. "
                f"Bimodal ratio: {metrics.get('grid_bimodal_ratio', 0.0):.3f}. "
                "Daily frequency cycle shifted, indicating irregular occupant usage patterns or sensor drift."
            )
            action_recommendation = "Re-calibrate local edge spectral filter parameters. Monitor for sensor drift."

        response: Dict[str, Any] = {
            "status": "Escalated_Diagnostic_Complete",
            "escalation_timestamp": timestamp_str,
            "slice_id": slice_id,
            "anomaly_type": anomaly_type,
            "trigger_metrics": metrics,
            "cloud_diagnostic_summary": diagnostic_summary,
            "action_recommendation": action_recommendation,
            "assigned_operator_queue": "Microgrid_Tier3_Support"
        }

        # Append or write to local audit ledger
        ledger: list = []
        if os.path.exists(self.audit_log_path):
            try:
                with open(self.audit_log_path, "r", encoding="utf-8") as f:
                    ledger = json.load(f)
                    if not isinstance(ledger, list):
                        ledger = []
            except Exception:
                ledger = []

        ledger.append(response)

        with open(self.audit_log_path, "w", encoding="utf-8") as f:
            json.dump(ledger, f, indent=2)

        return response
