"""Unit tests for Emporia Vue mock simulation, circuit classification, and top-load calculations."""

import os
import sys
import time
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from dashboard_modules.emporia_vue import (
    CATEGORY_COLORS,
    classify_circuit,
    generate_simulated_telemetry,
    get_top_active_loads,
    EmporiaVueClient,
)


def test_circuit_classification():
    """Verifies that circuit names are mapped into the correct functional zones."""
    assert classify_circuit("200A Mains")[0] == "Main & Grid"
    assert classify_circuit("200A Mains")[1] == "#c084fc"
    assert classify_circuit("Balance")[0] == "Balance"
    assert classify_circuit("Balance")[1] == "#94a3b8"

    assert classify_circuit("1 family room -office")[0] == "Compute & Lab"
    assert classify_circuit("big-len UPS")[0] == "Compute & Lab"
    assert classify_circuit("giga and lem")[0] == "Compute & Lab"
    assert classify_circuit("MacBook")[0] == "Compute & Lab"
    assert classify_circuit("bedroom ups")[0] == "General Household"

    assert classify_circuit("music room right main (Ch 10)")[0] == "Audio & Entertainment"
    assert classify_circuit("16 music room")[0] == "Audio & Entertainment"
    assert classify_circuit("avm 60")[0] == "Audio & Entertainment"
    assert classify_circuit("kitchen tv")[0] == "Audio & Entertainment"

    assert classify_circuit("A/C (Ch 6 & 13)")[0] == "Major Appliances"
    assert classify_circuit("9 furnace")[0] == "Major Appliances"
    assert classify_circuit("dryer (Ch 15)")[0] == "Major Appliances"
    assert classify_circuit("bedroom floor heat (Ch 12)")[0] == "Major Appliances"

    assert classify_circuit("4 garage 4")[0] == "General Household"
    assert classify_circuit("7 kitchen plugs")[0] == "General Household"
    assert classify_circuit("dining room fan")[0] == "General Household"
    assert classify_circuit("zoo spotlight")[0] == "General Household"


def test_simulated_telemetry_generation():
    """Verifies synthetic generator outputs realistic loads and enforces balance === main - total."""
    telemetry = generate_simulated_telemetry()
    assert len(telemetry) >= 22  # Panel circuits + 13 smart plugs + Mains + Balance
    
    names = [c["name"] for c in telemetry]
    assert "200A Mains" in names
    assert "Balance" in names
    assert "1 family room -office" in names
    assert "music room right main (Ch 10)" in names
    assert "big-len UPS" in names
    assert "avm 60" in names

    panel_sum = 0.0
    mains_w = 0.0
    balance_w = 0.0

    for c in telemetry:
        assert "watts" in c and c["watts"] >= 0.0
        assert "kw" in c and c["kw"] >= 0.0
        assert "category" in c and c["category"] in CATEGORY_COLORS
        assert "color" in c and c["color"].startswith("#")
        assert "type" in c and c["type"] in ["panel", "plug", "main", "balance"]
        assert "timestamp" in c

        if c["type"] == "panel":
            panel_sum += c["watts"]
        elif c["type"] == "main":
            mains_w = c["watts"]
        elif c["type"] == "balance":
            balance_w = c["watts"]

    # Strictly: balance === main - total
    assert mains_w > 0.0
    assert balance_w > 0.0
    assert abs(balance_w - (mains_w - panel_sum)) < 0.01


def test_top_active_loads_formatting():
    """Verifies header pill string formatting in Watts and excludes Mains summaries."""
    circuits = [
        {"name": "200A Mains", "watts": 1850.0, "kw": 1.85, "type": "main", "category": "Main & Grid"},
        {"name": "1 family room -office", "watts": 850.0, "kw": 0.85, "type": "panel", "category": "Compute & Lab"},
        {"name": "music room right main (Ch 10)", "watts": 280.0, "kw": 0.28, "type": "panel", "category": "Audio & Entertainment"},
        {"name": "Balance", "watts": 235.0, "kw": 0.235, "type": "balance", "category": "Balance"},
        {"name": "7 kitchen plugs", "watts": 150.0, "kw": 0.15, "type": "panel", "category": "General Household"},
        {"name": "4 garage 4", "watts": 30.0, "kw": 0.03, "type": "panel", "category": "General Household"},
        {"name": "kettle emporia", "watts": 0.0, "kw": 0.0, "type": "plug", "category": "General Household"},
    ]

    now = time.time()
    pill_text, sorted_list = get_top_active_loads(circuits, n=3, last_update_ts=now - 25)

    assert "⚡ Top:" in pill_text
    # Mains summary line should be excluded from top consumer pill
    assert "Mains" not in pill_text
    # Units must be in Watts (W), not kW/k
    assert "Office 850W" in pill_text
    assert "Music Main 280W" in pill_text
    assert "(25s ago)" in pill_text
    assert len(sorted_list) == len(circuits)


def test_top_active_loads_empty_and_idle():
    """Verifies graceful handling of empty or idle circuits."""
    pill_text, sorted_list = get_top_active_loads([])
    assert pill_text == "⚡ Top: Awaiting Telemetry..."
    assert sorted_list == []

    idle_circuits = [
        {"name": "Circuit 1", "watts": 2.0, "kw": 0.002},
        {"name": "Circuit 2", "watts": 0.0, "kw": 0.0},
    ]
    pill_text, sorted_list = get_top_active_loads(idle_circuits, n=3)
    assert pill_text == "⚡ Top: All circuits idle"


def test_client_circuit_telemetry_simulator_fallback():
    """Verifies client fallback to simulated telemetry."""
    client = EmporiaVueClient(username="test@example.com", token_file="scratch/non_existent.json")
    circuits = client.get_circuit_telemetry(use_simulator=True)
    assert len(circuits) > 0
    assert client.last_fetch_timestamp > 0
    assert client.cached_circuits == circuits
