import json
from typing import List, Dict, Any

from utils.paths import data_path

MONSTERS_FILE = data_path('monsters.json')

# Standard 5e XP thresholds for 4 characters (per character: easy/med/hard/deadly)
XP_THRESHOLDS = {
    1: [25, 50, 75, 100],
    2: [50, 100, 150, 200],
    3: [75, 150, 225, 400],
    4: [125, 250, 375, 500],
    5: [250, 500, 750, 1100],
    6: [300, 600, 900, 1400],
    7: [350, 750, 1100, 1700],
    8: [450, 900, 1400, 2100],
    9: [550, 1100, 1600, 2400],
    10: [600, 1200, 1900, 2800],
    11: [800, 1600, 2400, 3600],
    12: [1000, 2000, 3000, 4500],
    13: [1100, 2200, 3400, 5100],
    14: [1250, 2500, 3800, 5700],
    15: [1400, 2800, 4300, 6400],
    16: [1600, 3200, 4800, 7200],
    17: [2000, 3900, 5900, 8800],
    18: [2100, 4200, 6300, 9500],
    19: [2400, 4900, 7300, 10900],
    20: [2800, 5700, 8500, 12700],
}

# XP by challenge rating (SRD)
CR_XP = {
    "0": 10, "1/8": 25, "1/4": 50, "1/2": 100, "1": 200, "2": 450, "3": 700, "4": 1100, "5": 1800,
    "6": 2300, "7": 2900, "8": 3900, "9": 5000, "10": 5900, "11": 7200, "12": 8400, "13": 10000,
    "14": 11500, "15": 13000, "16": 15000, "17": 18000, "18": 20000, "19": 22000, "20": 25000,
    "21": 33000, "22": 41000, "23": 50000, "24": 62000, "25": 75000, "26": 90000, "27": 105000,
    "28": 120000, "29": 135000, "30": 155000,
}

# Encounter multipliers by number of monsters
ENCOUNTER_MULTIPLIERS = [1, 1.5, 2, 2.5, 3, 4]

class EncounterBuilder:
    """
    Builds and validates combat encounters using monster data and party info.
    """
    def __init__(self, monsters_file: str = MONSTERS_FILE):
        with open(monsters_file) as f:
            self.monster_data = json.load(f)["monsters"]
        self.monsters_by_cr = self._group_by_cr()

    def _group_by_cr(self) -> Dict[str, List[Dict[str, Any]]]:
        cr_dict = {}
        for m in self.monster_data:
            cr_dict.setdefault(m["cr"], []).append(m)
        return cr_dict

    def calculate_encounter_difficulty(self, monsters: List[Dict[str, Any]], party_level: int, party_size: int = 4) -> Dict[str, Any]:
        """
        Calculate total XP, apply multipliers, and compare to party thresholds.
        """
        base_xp = sum(CR_XP.get(str(m["cr"]), 0) for m in monsters)
        n = len(monsters)
        if n == 1:
            multiplier = 1
        elif n == 2:
            multiplier = 1.5
        elif 3 <= n <= 6:
            multiplier = 2
        elif 7 <= n <= 10:
            multiplier = 2.5
        elif 11 <= n <= 14:
            multiplier = 3
        else:
            multiplier = 4
        total_xp = int(base_xp * multiplier)
        thresholds = XP_THRESHOLDS.get(party_level, [0, 0, 0, 0])
        difficulty = "trivial"
        if total_xp >= thresholds[3] * party_size:
            difficulty = "deadly"
        elif total_xp >= thresholds[2] * party_size:
            difficulty = "hard"
        elif total_xp >= thresholds[1] * party_size:
            difficulty = "medium"
        elif total_xp >= thresholds[0] * party_size:
            difficulty = "easy"
        return {"base_xp": base_xp, "total_xp": total_xp, "difficulty": difficulty, "thresholds": thresholds}

    def validate_encounter_balance(self, monsters: List[Dict[str, Any]], party_level: int, party_size: int = 4) -> bool:
        """
        Return True if encounter is not deadly or trivial.
        """
        result = self.calculate_encounter_difficulty(monsters, party_level, party_size)
        return result["difficulty"] in ("easy", "medium", "hard")

    def generate_encounter_warning(self, monsters: List[Dict[str, Any]], party_level: int, party_size: int = 4) -> str:
        """
        Return a warning string if the encounter is imbalanced.
        """
        result = self.calculate_encounter_difficulty(monsters, party_level, party_size)
        if result["difficulty"] == "deadly":
            return "Warning: This encounter is deadly for the party."
        elif result["difficulty"] == "trivial":
            return "Warning: This encounter is trivial for the party."
        return "Encounter is balanced."

    def create_encounter_from_template(self, template: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Create an encounter from a template (list of monster names/CRs).
        """
        encounter = []
        missing_monsters = []
        for entry in template.get("monsters", []):
            # Support both exact name matches and base-name matching for numbered instances
            name = entry["name"]
            count = entry.get("count", 1)
            matches = [m for m in self.monster_data if m.get("name") == name]
            if not matches:
                # Try base-name match (e.g., template says "Skeleton" and DB has "Skeleton" entries)
                base_name = name.replace("\u00a0", " ").strip()
                matches = [m for m in self.monster_data if (m.get("name") or "").strip() == base_name]
            if not matches:
                missing_monsters.append(name)
                continue
            for i in range(count):
                monster_copy = matches[0].copy()
                # Give unique names to multiple monsters of the same type
                if count > 1:
                    monster_copy["name"] = f"{name} {i+1}"
                encounter.append(monster_copy)
        
        if missing_monsters:
            raise ValueError(f"Monsters not found in database: {', '.join(missing_monsters)}")
        
        if not encounter:
            raise ValueError("No valid monsters found in template")
            
        return encounter 