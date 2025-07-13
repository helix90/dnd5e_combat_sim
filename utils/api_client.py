import requests
import json
import os
import time
from threading import Lock
from utils.exceptions import APIError
from utils.logging import log_exception

class APIClient:
    def __init__(self, config_path="config/api_config.json", fallback_handler=None):
        with open(config_path) as f:
            self.config = json.load(f)
        self.spell_endpoint = self.config["open5e_spell_endpoint"]
        self.monster_endpoint = self.config["open5e_monster_endpoint"]
        self.timeout = self.config.get("timeout", 5)
        self.retry_attempts = self.config.get("retry_attempts", 2)
        self.retry_delay = self.config.get("retry_delay", 1.0)
        self.cache_duration = self.config.get("cache_duration_seconds", 3600)
        self.cache = {"spells": {}, "monsters": {}}
        self.cache_times = {"spells": {}, "monsters": {}}
        self.lock = Lock()
        self.fallback_handler = fallback_handler or LocalDataFallback()

    def fetch_spell_data(self, spell_name):
        return self._fetch_data("spells", spell_name, self.spell_endpoint)

    def fetch_monster_data(self, monster_name):
        return self._fetch_data("monsters", monster_name, self.monster_endpoint)

    def _fetch_data(self, data_type, name, endpoint):
        key = name.lower().replace(" ", "-")
        with self.lock:
            # Check cache
            if key in self.cache[data_type]:
                if time.time() - self.cache_times[data_type][key] < self.cache_duration:
                    return self.cache[data_type][key]
        url = endpoint + key + "/"
        for attempt in range(self.retry_attempts):
            try:
                resp = requests.get(url, timeout=self.timeout)
                if resp.status_code == 200:
                    data = resp.json()
                    with self.lock:
                        self.cache[data_type][key] = data
                        self.cache_times[data_type][key] = time.time()
                    return data
                else:
                    log_exception(f"API {data_type} fetch failed: {resp.status_code} {resp.text}")
            except Exception as e:
                log_exception(e)
            time.sleep(self.retry_delay)
        # Fallback
        fallback_data = self.fallback_handler.get_local_data(data_type, name)
        if fallback_data is not None:
            return fallback_data
        log_exception(f"API and fallback failed for {data_type}: {name}")
        raise APIError(f"Failed to fetch {data_type} data for {name} from API and fallback.")

    def _log_error(self, msg):
        log_exception(msg)

class LocalDataFallback:
    def __init__(self):
        self.local_paths = {
            "spells": "data/spells.json",
            "monsters": "data/monsters.json"
        }
        self.cache = {"spells": {}, "monsters": {}}
        self.lock = Lock()

    def get_local_data(self, data_type, name):
        key = name.lower().replace(" ", "-")
        with self.lock:
            if key in self.cache[data_type]:
                return self.cache[data_type][key]
            path = self.local_paths[data_type]
            if not os.path.exists(path):
                log_exception(f"[LocalDataFallback ERROR] Local file not found: {path}")
                return None
            with open(path) as f:
                try:
                    data_list = json.load(f)
                    for entry in data_list:
                        if entry.get("name", "").lower().replace(" ", "-") == key:
                            self.cache[data_type][key] = entry
                            return entry
                except Exception as e:
                    log_exception(f"[LocalDataFallback ERROR] Failed to load {path}: {e}")
        return None 