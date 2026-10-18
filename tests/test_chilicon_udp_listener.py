"""Unit tests for Chilicon CP-100 UDP 32758 Debug Bridge decoder and ingestor."""

import datetime
import struct
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import chilicon_udp_listener as cud


def _make_inverter_record(
    inv_id: int,
    ts_sec: int,
    rec_type: int = 0x26,
    ac_v_q4: int = 3902,
    dc1_i: int = 3400,
    dc1_v: int = 6800,
    dc2_i: int = 2500,
    dc2_v: int = 10400,
    inst_p_idx: int = 80,
    uptime_ticks: int = 150000000,
    energy_ticks: int = 165708585,
) -> bytes:
    """Builds a synthetic 85-byte Chilicon microinverter telemetry record."""
    buf = bytearray(85)
    struct.pack_into("<II", buf, 0, inv_id, ts_sec)
    buf[8] = rec_type
    struct.pack_into("<H", buf, 24, ac_v_q4)
    struct.pack_into("<H", buf, 26, dc1_i)
    struct.pack_into("<H", buf, 28, dc1_v)
    struct.pack_into("<H", buf, 34, dc2_i)
    struct.pack_into("<H", buf, 36, dc2_v)
    struct.pack_into("<H", buf, 44, inst_p_idx)
    struct.pack_into("<I", buf, 68, uptime_ticks)
    struct.pack_into("<I", buf, 72, energy_ticks)
    return bytes(buf)


def _make_full_udp_payload(
    gw_serial_u32: int = 0x00A1B2C3,
    ts1: int = 845556995,
    ts2: int = 845557085,
    base_ticks: int = 165708585,
    delta_ticks_per_inv: int = 138,
) -> bytes:
    """Builds a complete 1,372-byte Chilicon UDP 32758 packet (Header + 2 Sweeps + CRC)."""
    inv_ids = [
        0x10000001,
        0x10000002,
        0x10000003,
        0x10000004,
        0x10000005,
        0x10000006,
        0x10000007,
        0x10000008,
    ]
    header = struct.pack("<II", gw_serial_u32, 0)
    sweep1 = b"".join(
        _make_inverter_record(
            inv_id=inv_ids[i],
            ts_sec=ts1 + i * 5,
            rec_type=0x22 if i == 1 else 0x26,
            inst_p_idx=70,
            energy_ticks=base_ticks,
        )
        for i in range(8)
    )
    sweep2 = b"".join(
        _make_inverter_record(
            inv_id=inv_ids[i],
            ts_sec=ts2 + i * 5,
            rec_type=0x22 if i == 1 else 0x26,
            inst_p_idx=95,
            energy_ticks=base_ticks + delta_ticks_per_inv,
        )
        for i in range(8)
    )
    trailer = struct.pack("<I", 0xA1193C7B)
    payload = header + sweep1 + sweep2 + trailer
    assert len(payload) == 1372
    return payload


def test_decode_sweep_fields_and_delta_power():
    """Verifies Q12.4 voltage, EUI32 hex ID, lifetime kWh, and d_ticks/dt power calculation."""
    payload = _make_full_udp_payload(
        ts1=845557000,
        ts2=845557090,  # dt = 90 seconds
        base_ticks=165708585,
        delta_ticks_per_inv=138,  # 138 ticks over 90s -> ~70.84W RMS per inverter
    )
    body = payload[8:-4]
    prev_state = {}

    # Sweep 1: no prior state -> falls back to inst_p_idx / RMS_FACTOR
    s1_ts, s1_recs = cud.decode_sweep(body[:680], prev_state)
    assert len(s1_recs) == 8
    assert s1_recs[0]["inverter_id"] == "10000001"
    assert s1_recs[1]["inverter_id"] == "10000002"
    assert s1_recs[1]["record_type"] == 0x22
    assert s1_recs[0]["ac_voltage_v"] == pytest.approx(3902 / 16.0, rel=1e-3)
    assert s1_recs[0]["power_w"] == 70.0
    assert sum(st["lifetime_kwh"] for st in prev_state.values()) == pytest.approx(
        (165708585 * 8) / cud.TICKS_PER_KWH, rel=1e-5
    )

    # Sweep 2: 90s later with +138 ticks per inverter -> computes exact dE/dt power_w
    s2_ts, s2_recs = cud.decode_sweep(body[680:1360], prev_state)
    assert s2_ts > s1_ts
    expected_w = 138 / (90 * (cud.TICKS_PER_WS / 1000.0))
    for rec in s2_recs:
        assert rec["power_w"] == pytest.approx(expected_w, abs=1e-2)


def test_ingest_payload_writes_postgres_and_csv(tmp_path: Path):
    """Verifies ingest_payload inserts 16 inverter rows, 2 system rows, and appends CSV."""
    payload = _make_full_udp_payload()
    csv_file = tmp_path / "chilicon_history.csv"
    prev_state = {}

    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_conn.__enter__.return_value = mock_conn
    mock_conn.cursor.return_value.__enter__.return_value = mock_cur

    mock_pg = MagicMock()
    mock_pg.connect.return_value = mock_conn

    with patch.object(cud, "CHILICON_CSV", csv_file), patch.object(
        cud, "psycopg2", mock_pg
    ):
        cud.ingest_payload(payload, prev_state, append_csv=True)

    # 8 inverter inserts + 1 system insert per sweep * 2 sweeps = 18 SQL executions
    assert mock_cur.execute.call_count == 18
    assert csv_file.exists()
    lines = csv_file.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    parts = lines[0].split(",")
    assert len(parts) == 3
    assert float(parts[1]) == pytest.approx(0.567, abs=0.01)
    assert float(parts[2]) == pytest.approx(17011.9, abs=1.0)


def test_ingest_payload_ignores_invalid_length():
    """Verifies malformed UDP packets != 1372 bytes are safely ignored."""
    prev_state = {}
    mock_pg = MagicMock()
    with patch.object(cud, "psycopg2", mock_pg):
        cud.ingest_payload(b"short_packet", prev_state, append_csv=False)
        mock_pg.connect.assert_not_called()


def test_ingest_payload_csv_only_without_psycopg2(tmp_path: Path):
    """Verifies ingest_payload decodes sweeps and writes CSV on edge nodes without psycopg2."""
    payload = _make_full_udp_payload()
    csv_file = tmp_path / "chilicon_history.csv"
    prev_state = {}

    with patch.object(cud, "CHILICON_CSV", csv_file), patch.object(
        cud, "psycopg2", None
    ):
        cud.ingest_payload(payload, prev_state, append_csv=True)

    assert len(prev_state) == 8
    assert csv_file.exists()
    parts = csv_file.read_text(encoding="utf-8").strip().split(",")
    assert len(parts) == 3
    assert float(parts[1]) == pytest.approx(0.567, abs=0.01)


def test_decode_sweep_sleep_and_dawn_wakeup_guards():
    """Verifies dt == 0 forces 0.0W (sleep) and dt > 900s forces 0.0W (dawn wake-up)."""
    payload_sleep = _make_full_udp_payload(
        ts1=845557000,
        ts2=845557000,  # dt = 0 (frozen timestamp -> inverter sleeping)
        base_ticks=165708585,
        delta_ticks_per_inv=0,
    )
    body_sleep = payload_sleep[8:-4]
    prev_state = {}
    cud.decode_sweep(body_sleep[:680], prev_state)
    _, s2_recs = cud.decode_sweep(body_sleep[680:1360], prev_state)
    assert all(r["power_w"] == 0.0 for r in s2_recs)

    payload_dawn = _make_full_udp_payload(
        ts1=845557000,
        ts2=845587000,  # dt = 30,000s (>900s overnight gap)
        base_ticks=165708585,
        delta_ticks_per_inv=500,
    )
    body_dawn = payload_dawn[8:-4]
    prev_state_dawn = {}
    cud.decode_sweep(body_dawn[:680], prev_state_dawn)
    _, dawn_recs = cud.decode_sweep(body_dawn[680:1360], prev_state_dawn)
    assert all(r["power_w"] == 0.0 for r in dawn_recs)


def test_chillicon_client_defers_to_fresh_udp_csv(tmp_path: Path):
    """Verifies ChilliconClient.fetch_data returns fresh local UDP CSV row without cloud overwrite."""
    from dashboard_modules.solar import ChilliconClient

    csv_file = tmp_path / "chilicon_history.csv"
    now_iso = datetime.datetime.now().isoformat()
    csv_file.write_text(f"{now_iso},0.000,14883.7\n", encoding="utf-8")

    client = ChilliconClient("u", "p", "hash", str(csv_file))
    with patch.object(client.opener, "open") as mock_open:
        res = client.fetch_data()
        assert res is not None
        assert res[0] == 0.0
        assert res[1] == 14883.7
        mock_open.assert_not_called()


def test_chillicon_client_ignores_stale_sunset_bucket(tmp_path: Path):
    """Verifies ChilliconClient.fetch_data does not fall back to a stale afternoon bucket after sunset."""
    import io
    import json
    from dashboard_modules.solar import ChilliconClient

    csv_file = tmp_path / "chilicon_history.csv"
    client = ChilliconClient("u", "p", "hash", str(csv_file))

    # Bucket 100 (~08:20 AM) had 670W, all subsequent buckets are -1, current power is 0.0
    buckets = [-1] * 288
    buckets[100] = 670
    fake_json = json.dumps([buckets, 24058.4, 0.0]).encode("utf-8")
    mock_resp = MagicMock()
    mock_resp.__enter__.return_value = io.BytesIO(fake_json)

    with patch.object(client.opener, "open", return_value=mock_resp):
        res = client.fetch_data()
        assert res is not None
        assert res[0] == 0.0

