import json
from typing import List, Dict, Any

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
    # ...
}

# Encounter multipliers by number of monsters
ENCOUNTER_MULTIPLIERS = [1, 1.5, 2, 2.5, 3, 4]

class EncounterBuilder:
    """
    Builds and validates combat encounters using monster data and party info.
    """
    def __init__(self, monsters_file: str = "data/monsters.json"):
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
        xp_lookup = {
            "1/8": 25, "1/4": 50, "1/2": 100, "1": 200, "2": 450, "3": 700, "4": 1100, "5": 1800, "6": 2300
        }
        base_xp = sum(xp_lookup.get(m["cr"], 0) for m in monsters)
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
            name = entry["name"]
            count = entry.get("count", 1)
            matches = [m for m in self.monster_data if m["name"] == name]
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