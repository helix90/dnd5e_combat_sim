"""
Load testing for D&D 5e Combat Simulator using Locust.
"""

import time
import random
from locust import HttpUser, task, between
from typing import Dict, Any

class CombatSimulatorUser(HttpUser):
    """Simulates a user interacting with the combat simulator."""
    
    wait_time = between(1, 3)  # Wait 1-3 seconds between requests
    
    def on_start(self):
        """Initialize user session."""
        # Get available parties and encounters
        self.parties = self._get_parties()
        self.encounters = self._get_encounters()
        self.monsters = self._get_monsters()
    
    def _get_parties(self) -> list:
        """Get available parties."""
        try:
            response = self.client.get("/party")
            # Parse parties from HTML response (simplified)
            return [1, 2, 3, 4, 5, 6]  # Party IDs
        except:
            return [1, 2, 3]
    
    def _get_encounters(self) -> list:
        """Get available encounters."""
        return [
            "Kobold Mob", "Goblin Ambush", "Wolf Pack", "Orc Raiders",
            "Hobgoblin Patrol", "Bear Encounter", "Owlbear Lair"
        ]
    
    def _get_monsters(self) -> list:
        """Get available monsters."""
        try:
            response = self.client.get("/api/monsters")
            if response.status_code == 200:
                data = response.json()
                return data.get('monsters', [])[:10]  # First 10 monsters
        except:
            pass
        return []
    
    @task(3)
    def view_home_page(self):
        """View the home page."""
        self.client.get("/")
    
    @task(2)
    def view_party_selection(self):
        """View party selection page."""
        self.client.get("/party")
    
    @task(2)
    def select_party(self):
        """Select a random party."""
        if self.parties:
            party_id = random.choice(self.parties)
            self.client.post("/party", data={"party_id": party_id})
    
    @task(2)
    def view_encounter_selection(self):
        """View encounter selection page."""
        self.client.get("/encounter")
    
    @task(2)
    def create_custom_encounter(self):
        """Create a custom encounter."""
        if self.monsters:
            monster = random.choice(self.monsters)
            encounter_data = {
                "monsters": [monster],
                "party_level": random.randint(1, 10),
                "party_size": random.randint(3, 6)
            }
            self.client.post("/encounter/custom", json=encounter_data)
    
    @task(2)
    def select_prebuilt_encounter(self):
        """Select a prebuilt encounter."""
        if self.encounters:
            encounter = random.choice(self.encounters)
            encounter_data = {
                "template_name": encounter,
                "party_level": random.randint(1, 10),
                "party_size": random.randint(3, 6)
            }
            self.client.post("/encounter/prebuilt", json=encounter_data)
    
    @task(1)
    def get_monsters_api(self):
        """Get monsters from API."""
        self.client.get("/api/monsters")
    
    @task(1)
    def get_monsters_with_cr_filter(self):
        """Get monsters filtered by CR."""
        cr_options = ["1/4", "1/2", "1", "2", "3"]
        cr = random.choice(cr_options)
        self.client.get(f"/api/monsters?cr={cr}")
    
    @task(1)
    def check_encounter_balance(self):
        """Check encounter balance."""
        if self.monsters:
            monster = random.choice(self.monsters)
            balance_data = {
                "monsters": [monster],
                "party_level": random.randint(1, 10),
                "party_size": random.randint(3, 6)
            }
            self.client.post("/api/encounter/balance", json=balance_data)
    
    @task(1)
    def start_simulation(self):
        """Start a combat simulation."""
        self.client.get("/simulate")
    
    @task(3)
    def check_simulation_status(self):
        """Check simulation status."""
        self.client.get("/simulate/status")
    
    @task(1)
    def view_results(self):
        """View simulation results."""
        self.client.get("/results")
    
    @task(1)
    def view_history(self):
        """View simulation history."""
        self.client.get("/history")
    
    @task(5)
    def health_check(self):
        """Health check endpoint."""
        self.client.get("/healthz")

class HeavyUser(CombatSimulatorUser):
    """Simulates a heavy user who runs many simulations."""
    
    wait_time = between(0.5, 1.5)  # Faster requests
    
    @task(5)
    def run_full_simulation_workflow(self):
        """Run a complete simulation workflow."""
        # Select party
        party_id = random.choice(self.parties)
        self.client.post("/party", data={"party_id": party_id})
        
        # Create encounter
        if random.choice([True, False]):
            # Custom encounter
            monster = random.choice(self.monsters)
            encounter_data = {
                "monsters": [monster],
                "party_level": random.randint(1, 10),
                "party_size": random.randint(3, 6)
            }
            self.client.post("/encounter/custom", json=encounter_data)
        else:
            # Prebuilt encounter
            encounter = random.choice(self.encounters)
            encounter_data = {
                "template_name": encounter,
                "party_level": random.randint(1, 10),
                "party_size": random.randint(3, 6)
            }
            self.client.post("/encounter/prebuilt", json=encounter_data)
        
        # Start simulation
        self.client.get("/simulate")
        
        # Poll for completion
        for _ in range(10):
            response = self.client.get("/simulate/status")
            if response.status_code == 200:
                try:
                    data = response.json()
                    if data.get('done', False):
                        break
                except:
                    pass
            time.sleep(0.5)
        
        # View results
        self.client.get("/results")

class APIUser(CombatSimulatorUser):
    """Simulates API-only usage."""
    
    wait_time = between(0.1, 0.5)  # Very fast API requests
    
    @task(10)
    def api_monsters_request(self):
        """Frequent monster API requests."""
        self.client.get("/api/monsters")
    
    @task(5)
    def api_balance_check(self):
        """Frequent balance checks."""
        if self.monsters:
            monster = random.choice(self.monsters)
            balance_data = {
                "monsters": [monster],
                "party_level": random.randint(1, 10),
                "party_size": random.randint(3, 6)
            }
            self.client.post("/api/encounter/balance", json=balance_data)
    
    @task(3)
    def api_encounter_creation(self):
        """Create encounters via API."""
        if self.monsters:
            monster = random.choice(self.monsters)
            encounter_data = {
                "monsters": [monster],
                "party_level": random.randint(1, 10),
                "party_size": random.randint(3, 6)
            }
            self.client.post("/encounter/custom", json=encounter_data)

# Locust configuration
# Run with: locust -f tests/test_load.py --host=http://localhost:5000 