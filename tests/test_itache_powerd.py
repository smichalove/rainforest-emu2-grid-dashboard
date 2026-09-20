"""Unit test suite for the iTach and Emporia Vue power daemon (`powerd.py`).

This test module verifies the dual-condition safety guard logic for rack cooling
fans, live wattage conversions from raw kWh/sec telemetry, and fail-safe behavior
under simulated cloud API outages.

Test Coverage:
    - `test_fans_run_when_anthem_on`: Ensures fans remain active whenever the Anthem
      processor sensor is in state '1'.
    - `test_fans_run_when_vinyl_workload_active`: Validates that standalone amplifier
      power draw exceeding 530.0W triggers active fan cooling even when Anthem is '0'.
    - `test_fans_shutdown_only_when_both_off`: Asserts that fans power down only when
      both Anthem is '0' and circuit draw is confirmed <= 530.0W.
    - `test_fans_fail_safe_on_telemetry_error`: Verifies fail-safe retention (fans ON)
      if the Emporia API returns None or encounters network errors.
    - `test_emporia_power_monitor_calculation`: Confirms mathematical conversion
      from instantaneous kWh/sec to Watts (`Watts = kWh * 3.6e6`).
"""

import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'itache_prod')))

import powerd
from powerd import should_rack_fans_run, EmporiaPowerMonitor


def test_fans_run_when_anthem_on() -> None:
    """Verifies that rack fans always run when the Anthem power sensor is active ('1').

    Args:
        None.

    Returns:
        None.
    """
    with patch.object(powerd.EMPORIA_MONITOR, 'get_channel_watts', return_value=0.0):
        assert should_rack_fans_run(sensor_state='1') is True

    with patch.object(powerd.EMPORIA_MONITOR, 'get_channel_watts', return_value=600.0):
        assert should_rack_fans_run(sensor_state='1') is True

    with patch.object(powerd.EMPORIA_MONITOR, 'get_channel_watts', return_value=None):
        assert should_rack_fans_run(sensor_state='1') is True


def test_fans_run_when_vinyl_workload_active() -> None:
    """Verifies that rack fans run when Anthem is OFF but power draw exceeds 600W.

    Args:
        None.

    Returns:
        None.
    """
    with patch.object(powerd.EMPORIA_MONITOR, 'get_channel_watts', return_value=600.1):
        assert should_rack_fans_run(sensor_state='0') is True

    with patch.object(powerd.EMPORIA_MONITOR, 'get_channel_watts', return_value=750.0):
        assert should_rack_fans_run(sensor_state='0') is True


def test_fans_shutdown_only_when_both_off() -> None:
    """Verifies that rack fans power down only when Anthem is OFF and draw <= 600W.

    Args:
        None.

    Returns:
        None.
    """
    with patch.object(powerd.EMPORIA_MONITOR, 'get_channel_watts', return_value=600.0):
        assert should_rack_fans_run(sensor_state='0') is False

    with patch.object(powerd.EMPORIA_MONITOR, 'get_channel_watts', return_value=550.0):
        assert should_rack_fans_run(sensor_state='0') is False

    with patch.object(powerd.EMPORIA_MONITOR, 'get_channel_watts', return_value=0.0):
        assert should_rack_fans_run(sensor_state='0') is False


def test_fans_fail_safe_on_telemetry_error() -> None:
    """Verifies that fans fail-safe to ON if Emporia telemetry returns None.

    Args:
        None.

    Returns:
        None.
    """
    with patch.object(powerd.EMPORIA_MONITOR, 'get_channel_watts', return_value=None):
        assert should_rack_fans_run(sensor_state='0') is True


@patch("powerd.pyemvue.PyEmVue")
def test_emporia_power_monitor_calculation(mock_pyemvue_cls: MagicMock) -> None:
    """Verifies mathematical conversion from kWh per second to Watts.

    Args:
        mock_pyemvue_cls: Mocked PyEmVue class constructor.

    Returns:
        None.
    """
    mock_vue = mock_pyemvue_cls.return_value
    mock_vue.login.return_value = {"id_token": "token123"}

    mock_channel = MagicMock()
    # 0.000147222 kWh in 1 sec = ~530.0 Watts
    mock_channel.usage = 0.000147222

    mock_device = MagicMock()
    mock_device.channels = {"10": mock_channel}
    mock_vue.get_device_list_usage.return_value = {100920: mock_device}

    with tempfile.NamedTemporaryFile(suffix=".json") as tmp_token:
        monitor = EmporiaPowerMonitor(token_file=Path(tmp_token.name), device_gid=100920, channel_num="10")
        watts = monitor.get_channel_watts()

        assert watts is not None
        assert round(watts, 1) == 530.0
