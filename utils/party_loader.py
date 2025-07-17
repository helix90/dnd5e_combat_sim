import json
import os
from typing import List, Dict, Optional
from utils.exceptions import ValidationError
from utils.logging import log_exception

PARTY_JSON_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data', 'parties.json')

class PartyLoader:
    @staticmethod
    def load_parties() -> List[Dict]:
        """Load all parties from the JSON file."""
        try:
            with open(PARTY_JSON_PATH, 'r', encoding='utf-8') as f:
                parties = json.load(f)
            return parties
        except FileNotFoundError as e:
            log_exception(e)
            raise ValidationError(f"Party data file not found: {PARTY_JSON_PATH}")
        except json.JSONDecodeError as e:
            log_exception(e)
            raise ValidationError(f"Invalid JSON in party data file: {e}")
        except Exception as e:
            log_exception(e)
            raise ValidationError(f"Error loading party data: {e}")

    @staticmethod
    def get_party_by_id(party_id: int) -> Optional[Dict]:
        """Get a single party by its ID."""
        parties = PartyLoader.load_parties()
        for party in parties:
            if party.get('id') == party_id:
                return party
        raise ValidationError(f"Party with ID {party_id} not found.")

    @staticmethod
    def get_party_with_level(party_id: int, level: int) -> Optional[Dict]:
        """
        Get a party by ID, replacing each character with the full character data for the given level.
        """
        party = PartyLoader.get_party_by_id(party_id)
        if not party:
            return None
        # Load all character data for the given level
        import json
        import os
        char_json_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data', 'characters.json')
        with open(char_json_path, 'r', encoding='utf-8') as f:
            all_levels = json.load(f)
        level_data = next((lvl for lvl in all_levels if lvl.get('level') == level), None)
        if not level_data:
            return None
        full_party = []
        for c in party['characters']:
            name = c['name'].strip().lower()
            char_class = (c.get('class') or c.get('character_class') or '').strip().lower()
            found = None
            for char in level_data.get('party', []):
                target_name = char.get('name', '').strip().lower()
                target_class = (char.get('class') or char.get('character_class') or '').strip().lower()
                if target_name == name and target_class == char_class:
                    found = char.copy()
                    break
            if found:
                full_party.append(found)
            else:
                # Fallback to original party character if not found
                full_party.append(c)
        party = party.copy()
        party['characters'] = full_party
        return party 