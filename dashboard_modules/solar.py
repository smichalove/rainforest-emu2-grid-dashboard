"""SolarEdge and Chillicon Solar API clients and history data loaders.

Handles background polling loops, session logins, and CSV persistence using the
centralized io helper functions.
"""

import datetime
import http.cookiejar
import json
import logging
import re
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

# Local imports
from .io import read_clean_csv, write_csv_row


class SolarEdgeClient:
    """Handles credentials, data polling, and CSV storage for SolarEdge API.

    Attributes:
        api_key (str): SolarEdge API Key.
        site_id (str): SolarEdge site ID.
        history_file (str): Path to write SolarEdge PV generation records.
        battery_history_file (str): Path to write SolarEdge battery records.
        flow_history_file (str): Path to write SolarEdge load/grid flow records.
    """

    def __init__(self, api_key: str, site_id: str, history_file: str, battery_history_file: str, flow_history_file: Optional[str] = None) -> None:
        self.api_key: str = api_key
        self.site_id: str = site_id
        self.history_file: str = history_file
        self.battery_history_file: str = battery_history_file
        self.flow_history_file: str = flow_history_file or history_file.replace("solaredge_history.csv", "solaredge_flow_history.csv")

    def load_history(self, cutoff_hours: int = 24) -> Tuple[
        List[datetime.datetime], List[float], List[datetime.datetime], List[float], List[float]
    ]:
        """Loads historical SolarEdge data from CSV, cleaning corruptions.

        Returns:
            Tuple: (pv_timestamps, pv_power, battery_timestamps, battery_power, battery_soc)
        """
        now = datetime.datetime.now()
        cutoff = now - datetime.timedelta(hours=cutoff_hours)

        pv_ts: List[datetime.datetime] = []
        pv_power: List[float] = []
        bat_ts: List[datetime.datetime] = []
        bat_power: List[float] = []
        bat_soc: List[float] = []

        # Load PV Power History
        pv_rows = read_clean_csv(self.history_file)
        for row in pv_rows:
            if len(row) == 2:
                try:
                    ts = datetime.datetime.fromisoformat(row[0])
                    val = float(row[1])
                    if ts > cutoff:
                        pv_ts.append(ts)
                        pv_power.append(val)
                except Exception as e:
                    logging.debug(f"Corrupted SolarEdge PV history row: {row} - Error: {e}")

        # Load Battery Storage History
        bat_rows = read_clean_csv(self.battery_history_file)
        for row in bat_rows:
            if len(row) == 3:
                try:
                    ts = datetime.datetime.fromisoformat(row[0])
                    power = float(row[1])
                    soc = float(row[2])
                    if ts > cutoff:
                        bat_ts.append(ts)
                        bat_power.append(power)
                        bat_soc.append(soc)
                except Exception as e:
                    logging.debug(f"Corrupted SolarEdge battery history row: {row} - Error: {e}")

        return pv_ts, pv_power, bat_ts, bat_power, bat_soc

    def load_flow_history(self, cutoff_hours: int = 24) -> Tuple[List[datetime.datetime], List[float]]:
        """Loads historical SolarEdge flow data (specifically load_power) from CSV.

        Args:
            cutoff_hours: Number of hours in the past to load.

        Returns:
            Tuple of (timestamps, load_power_in_kw).
        """
        now = datetime.datetime.now()
        cutoff = now - datetime.timedelta(hours=cutoff_hours)
        
        load_ts: List[datetime.datetime] = []
        load_power: List[float] = []
        
        rows = read_clean_csv(self.flow_history_file)
        for row in rows:
            if len(row) >= 3:
                try:
                    ts = datetime.datetime.fromisoformat(row[0])
                    val = float(row[2])  # load_power is at index 2
                    if ts > cutoff:
                        load_ts.append(ts)
                        load_power.append(val)
                except Exception as e:
                    logging.debug(f"Corrupted SolarEdge flow history row: {row} - Error: {e}")
                    
        return load_ts, load_power

    def fetch_data(self) -> Optional[Dict[str, Any]]:
        """Polls the SolarEdge API currentPowerFlow endpoint and logs history.

        Retrieves real-time power generation, household consumption (load),
        grid imports/exports, and battery storage/SoC data, then writes them
        to their respective CSV database files.

        Returns:
            A dictionary containing parsed API flow values, or None if the
            request or parsing fails. The dictionary contains:
                - 'pv_power' (float): Solar generation in kW.
                - 'battery_power' (float): Signed battery power in kW.
                - 'battery_soc' (float): Battery state of charge in %.
                - 'load_power' (float): Home demand power in kW.
                - 'grid_import' (float): Power imported from the grid in kW.
                - 'grid_export' (float): Power exported to the grid in kW.
                - 'timestamp' (datetime.datetime): Fetch timestamp.
        """
        now = datetime.datetime.now()

        url = (
            f"https://monitoringapi.solaredge.com/site/{self.site_id}/"
            f"currentPowerFlow?api_key={self.api_key}&format=json"
        )
        try:
            logging.info("Polling SolarEdge API currentPowerFlow...")
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=10) as response:
                data = json.loads(response.read().decode('utf-8'))
                flow = data.get("siteCurrentPowerFlow", {})
                
                # Extract PV Power
                pv = flow.get("pv") or flow.get("PV") or {}
                pv_power = pv.get("currentPower", 0.0)
                write_csv_row(self.history_file, [now.isoformat(), f"{pv_power:.3f}"])

                # Extract Load (Home Consumption)
                load_obj = flow.get("load") or flow.get("LOAD") or {}
                load_power = load_obj.get("currentPower", 0.0)

                # Extract Grid flow
                grid_obj = flow.get("grid") or flow.get("GRID") or {}
                grid_power = grid_obj.get("currentPower", 0.0)
                
                # Check connections list for flow direction (import vs export)
                connections = flow.get("connections", [])
                grid_import = 0.0
                grid_export = 0.0
                for conn in connections:
                    f = str(conn.get("from", "")).upper()
                    t = str(conn.get("to", "")).upper()
                    if f == "GRID" and t == "LOAD":
                        grid_import = grid_power
                    elif t == "GRID":
                        grid_export = grid_power

                # Extract Battery Storage
                storage_obj = flow.get("storage") or flow.get("STORAGE") or {}
                raw_battery_power = storage_obj.get("currentPower", 0.0)
                battery_soc = storage_obj.get("chargeLevel", 0.0)
                battery_status = str(storage_obj.get("status", "")).upper()
                
                # Math for signed battery power (positive = discharging, negative = charging)
                if battery_status == "DISCHARGING":
                    signed_battery_power = raw_battery_power
                elif battery_status == "CHARGING":
                    signed_battery_power = -raw_battery_power
                else:
                    signed_battery_power = 0.0

                write_csv_row(
                    self.battery_history_file,
                    [now.isoformat(), f"{signed_battery_power:.3f}", f"{battery_soc:.1f}"]
                )

                write_csv_row(
                    self.flow_history_file,
                    [now.isoformat(), f"{pv_power:.3f}", f"{load_power:.3f}", f"{grid_import:.3f}", f"{grid_export:.3f}"]
                )

                return {
                    "pv_power": pv_power,
                    "battery_power": signed_battery_power,
                    "battery_soc": battery_soc,
                    "load_power": load_power,
                    "grid_import": grid_import,
                    "grid_export": grid_export,
                    "timestamp": now
                }
        except Exception as e:
            logging.error(f"Error polling SolarEdge API: {e}")
            return None


class ChilliconClient:
    """Handles logins, cookies, and data polling for Chillicon Microgrid Cloud.

    Attributes:
        username (str): login username.
        password (str): login password.
        installation_hash (str): Chillicon dashboard hash.
        history_file (str): Path to write Chillicon generation records.
    """

    def __init__(self, username: str, password: str, installation_hash: str, history_file: str) -> None:
        self.username: str = username
        self.password: str = password
        self.installation_hash: str = installation_hash
        self.history_file: str = history_file
        self.cookie_jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.cookie_jar))

    def load_history(self, cutoff_hours: int = 24) -> Tuple[List[datetime.datetime], List[float], List[float]]:
        """Loads historical Chillicon generation data from CSV.

        Returns:
            Tuple of lists: (timestamps, power_in_kw, total_daily_energy_in_wh).
        """
        now = datetime.datetime.now()
        cutoff = now - datetime.timedelta(hours=cutoff_hours)

        timestamps: List[datetime.datetime] = []
        power: List[float] = []
        energy: List[float] = []

        rows = read_clean_csv(self.history_file)
        for row in rows:
            if len(row) == 3:
                try:
                    ts = datetime.datetime.fromisoformat(row[0])
                    p = float(row[1])
                    e = float(row[2])
                    if ts > cutoff:
                        timestamps.append(ts)
                        power.append(p)
                        energy.append(e)
                except Exception as ex:
                    logging.debug(f"Corrupted Chillicon history row: {row} - Error: {ex}")

        return timestamps, power, energy

    def login(self) -> bool:
        """Logs into Chillicon Cloud and stores session cookies.

        Returns:
            True if authentication succeeded, False otherwise.
        """
        login_url = "https://cloud.chiliconpower.com/login"
        try:
            logging.info("Fetching Chillicon login page for CSRF token...")
            req = urllib.request.Request(login_url, headers={'User-Agent': 'Mozilla/5.0'})
            with self.opener.open(req, timeout=15) as r:
                html = r.read().decode('utf-8')
                csrf_match = re.search(r'name=["\']csrfmiddlewaretoken["\']\s+value=["\']([^"\']+)["\']', html)
                csrf_token = csrf_match.group(1) if csrf_match else None
                
            login_payload = {
                'username': self.username,
                'password': self.password
            }
            if csrf_token:
                login_payload['csrfmiddlewaretoken'] = csrf_token
                
            data = urllib.parse.urlencode(login_payload).encode('utf-8')
            req = urllib.request.Request(
                login_url,
                data=data,
                headers={
                    'User-Agent': 'Mozilla/5.0',
                    'Referer': login_url,
                    'Content-Type': 'application/x-www-form-urlencoded'
                }
            )
            with self.opener.open(req, timeout=15) as r:
                logging.info(f"Chillicon login response URL: {r.geturl()}")
                return True
        except Exception as e:
            logging.error(f"Error logging into Chillicon: {e}")
            return False

    def fetch_data(self) -> Optional[Tuple[float, float, datetime.datetime]]:
        """Polls Chillicon Cloud API. Performs automatic re-login on session timeouts.

        Returns:
            A tuple of (power_kw, energy_wh, timestamp), or None if failed.
        """
        today_str = datetime.date.today().isoformat()
        owner_update_url = f"https://cloud.chiliconpower.com/ajax/fetchOwnerUpdate?today={today_str}"
        
        req = urllib.request.Request(
            owner_update_url,
            headers={
                'User-Agent': 'Mozilla/5.0',
                'Referer': f"https://cloud.chiliconpower.com/installation/{self.installation_hash}",
                'X-Requested-With': 'XMLHttpRequest'
            }
        )
        
        try:
            logging.info("Polling Chillicon API fetchOwnerUpdate...")
            with self.opener.open(req, timeout=15) as response:
                res = response.read().decode('utf-8')
                try:
                    parsed = json.loads(res)
                except Exception:
                    logging.info("Chillicon session might have expired. Re-authenticating...")
                    if self.login():
                        with self.opener.open(req, timeout=15) as retry_response:
                            res = retry_response.read().decode('utf-8')
                            parsed = json.loads(res)
                    else:
                        raise ValueError("Failed to re-authenticate with Chillicon")
                        
                if len(parsed) >= 3:
                    energy_wh = float(parsed[1])
                    power_kw = float(parsed[2])
                    now = datetime.datetime.now()
                    
                    write_csv_row(self.history_file, [now.isoformat(), f"{power_kw:.3f}", f"{energy_wh:.1f}"])
                    return power_kw, energy_wh, now
                else:
                    logging.warning(f"Unexpected Chillicon API response format: {parsed}")
        except Exception as e:
            logging.error(f"Error polling Chillicon API: {e}")
        return None
