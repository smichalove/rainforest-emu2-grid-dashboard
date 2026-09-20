"""Unit tests for EmporiaVueClient and read_emporia_vue script.

Tests authentication workflows (token re-use, fresh login, getpass prompting),
device and channel enumeration, and realtime usage fetching.
"""

import json
import os
import tempfile
from unittest.mock import MagicMock, patch
import pytest

import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from dashboard_modules.emporia_vue import EmporiaVueClient
from read_emporia_vue import create_emulated_client



class MockChannel:
    def __init__(self, num, name, multiplier=1.0, c_type="50A CT"):
        self.channel_num = num
        self.name = name
        self.channel_multiplier = multiplier
        self.channel_type = c_type


class MockVueDevice:
    def __init__(self, gid, name, model="VUE002", channels=None, nested=None):
        self.device_gid = gid
        self.device_name = name
        self.model = model
        self.firmware = "1.0.0"
        self.connected = True
        self.channels = channels or []
        self.nested_devices = nested or {}


def test_emporia_client_init():
    with tempfile.TemporaryDirectory() as tmpdir:
        token_path = os.path.join(tmpdir, "subdir", "tokens.json")
        client = EmporiaVueClient(username="test@example.com", token_file=token_path)
        assert client.username == "test@example.com"
        assert client.token_file == token_path
        assert os.path.exists(os.path.dirname(token_path))


@patch("dashboard_modules.emporia_vue.pyemvue.PyEmVue")
def test_login_with_cached_tokens(mock_pyemvue_cls):
    with tempfile.TemporaryDirectory() as tmpdir:
        token_path = os.path.join(tmpdir, "tokens.json")
        with open(token_path, "w") as f:
            f.write(json.dumps({"id_token": "fake_token"}))

        mock_vue_inst = mock_pyemvue_cls.return_value
        mock_vue_inst.login.return_value = {"id_token": "fake_token"}

        client = EmporiaVueClient(username="user@example.com", token_file=token_path)
        result = client.login(interactive=False)

        assert result is True
        mock_vue_inst.login.assert_called_with(token_storage_file=token_path)


@patch("getpass.getpass")
@patch("dashboard_modules.emporia_vue.pyemvue.PyEmVue")
def test_fresh_login_with_interactive_prompt(mock_pyemvue_cls, mock_getpass):
    with tempfile.TemporaryDirectory() as tmpdir:
        token_path = os.path.join(tmpdir, "tokens.json")
        with open(token_path, "w") as f:
            f.write("invalid_tokens")
        mock_getpass.return_value = "SecretPass123!"

        mock_vue_inst = mock_pyemvue_cls.return_value
        mock_vue_inst.login.side_effect = [
            Exception("No cached tokens"),  # First attempt via token file fails
            {"id_token": "new_token"}        # Fresh login succeeds
        ]

        client = EmporiaVueClient(username="user@example.com", token_file=token_path)
        result = client.login(interactive=True)

        assert result is True
        mock_getpass.assert_called_once()
        assert mock_vue_inst.login.call_count == 2


@patch("dashboard_modules.emporia_vue.pyemvue.PyEmVue")
def test_get_device_tree(mock_pyemvue_cls):
    mock_vue_inst = mock_pyemvue_cls.return_value
    ch1 = MockChannel("1", "Mains 1", 1.0, "Mains")
    ch2 = MockChannel("2", "HVAC Compressor", 1.0, "50A CT")
    dev = MockVueDevice(12345, "Main Panel Vue", channels=[ch1, ch2])
    mock_vue_inst.get_devices.return_value = [dev]

    client = EmporiaVueClient(username="user@example.com")
    tree = client.get_device_tree()

    assert len(tree) == 1
    assert tree[0]["device_gid"] == 12345
    assert tree[0]["device_name"] == "Main Panel Vue"
    assert len(tree[0]["channels"]) == 2
    assert tree[0]["channels"][1]["name"] == "HVAC Compressor"


def test_format_circuit_summary():
    client = create_emulated_client()
    devices = client.get_device_tree()
    summary = client.format_circuit_summary(devices)

    assert "EMPORIA VUE ENUMERATED DEVICES & CIRCUITS" in summary
    assert "Main Panel Vue 2" in summary
    assert "Heat Pump Outdoor Unit" in summary
    assert "EV Charger (Level 2)" in summary
    assert "IT Server Rack / Homelab" in summary


@patch("dashboard_modules.emporia_vue.pyemvue.PyEmVue")
def test_fetch_realtime_usage(mock_pyemvue_cls):
    mock_vue_inst = mock_pyemvue_cls.return_value
    dev = MockVueDevice(999, "Panel")
    mock_vue_inst.get_devices.return_value = [dev]
    mock_vue_inst.get_device_list_usage.return_value = {999: {"channels": {1: 1500.0}}}

    client = EmporiaVueClient(username="user@example.com")
    usage = client.fetch_realtime_usage()

    assert 999 in usage
    assert usage[999]["channels"][1] == 1500.0
