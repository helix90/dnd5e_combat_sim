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