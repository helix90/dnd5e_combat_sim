import pytest
import json
from utils.api_client import APIClient, LocalDataFallback

class DummyResponse:
    def __init__(self, status_code, json_data=None, text=""):
        self.status_code = status_code
        self._json = json_data or {}
        self.text = text
    def json(self):
        return self._json

def test_api_client_fetch_success(monkeypatch):
    # Simulate successful API response
    def dummy_get(url, timeout):
        return DummyResponse(200, {"name": "Fireball", "level": 3})
    monkeypatch.setattr("requests.get", dummy_get)
    client = APIClient()
    data = client.fetch_spell_data("Fireball")
    assert data["name"] == "Fireball"
    assert data["level"] == 3

def test_api_client_fetch_failure_and_fallback(monkeypatch, tmp_path):
    # Simulate API failure, fallback to local
    def dummy_get(url, timeout):
        raise Exception("API down")
    monkeypatch.setattr("requests.get", dummy_get)
    # Create a local spells.json
    spells = [{"name": "Magic Missile", "level": 1}]
    spells_path = tmp_path / "spells.json"
    with open(spells_path, "w") as f:
        json.dump(spells, f)
    # Patch LocalDataFallback to use tmp_path
    fallback = LocalDataFallback()
    fallback.local_paths["spells"] = str(spells_path)
    monkeypatch.setattr("utils.api_client.LocalDataFallback", lambda: fallback)
    client = APIClient()
    data = client.fetch_spell_data("Magic Missile")
    assert data["name"] == "Magic Missile"
    assert data["level"] == 1

def test_api_client_cache(monkeypatch):
    # Simulate API response, then test cache
    call_count = {"count": 0}
    def dummy_get(url, timeout):
        call_count["count"] += 1
        return DummyResponse(200, {"name": "Cure Wounds", "level": 1})
    monkeypatch.setattr("requests.get", dummy_get)
    client = APIClient()
    data1 = client.fetch_spell_data("Cure Wounds")
    data2 = client.fetch_spell_data("Cure Wounds")
    assert data1["name"] == "Cure Wounds"
    assert call_count["count"] == 1  # Only one API call due to cache

def test_local_data_fallback_missing_file(tmp_path):
    fallback = LocalDataFallback()
    fallback.local_paths["spells"] = str(tmp_path / "missing.json")
    data = fallback.get_local_data("spells", "Nonexistent")
    assert data is None

def test_local_data_fallback_invalid_json(tmp_path):
    path = tmp_path / "bad.json"
    with open(path, "w") as f:
        f.write("not json")
    fallback = LocalDataFallback()
    fallback.local_paths["spells"] = str(path)
    data = fallback.get_local_data("spells", "Anything")
    assert data is None 