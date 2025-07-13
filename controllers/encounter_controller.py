from models.encounter_builder import EncounterBuilder
from flask import session
import json
from utils.exceptions import ValidationError, APIError
from utils.logging import log_exception

class EncounterController:
    def __init__(self, monsters_file="data/monsters.json", templates_file="data/encounter_templates.json"):
        self.builder = EncounterBuilder(monsters_file=monsters_file)
        self.templates_file = templates_file

    def handle_custom_encounter(self, monster_list, party_level, party_size):
        try:
            balance = self.validate_encounter_balance(monster_list, party_level, party_size)
            warnings = self.generate_encounter_warnings(monster_list, party_level, party_size)
            session['encounter_monsters'] = monster_list
            import logging
            logging.info(f'handle_custom_encounter: session_id={session.get("session_id")}')
            logging.info('handle_custom_encounter: Saving monsters to session:')
            for m in monster_list:
                logging.info(f"Type: {type(m)}, Name: {getattr(m, 'name', None)}, Data: {m}")
            return {"balance": balance, "warnings": warnings, "monsters": monster_list}
        except Exception as e:
            log_exception(e)
            raise ValidationError(f"Failed to handle custom encounter: {e}")

    def handle_prebuilt_encounter(self, template_name, party_level, party_size):
        try:
            # Clear any existing encounter data first
            session.pop('encounter_monsters', None)
            session.pop('selected_encounter', None)
            
            with open(self.templates_file) as f:
                templates = json.load(f)["encounters"]
            template = next((t for t in templates if t["name"] == template_name), None)
            if not template:
                raise ValidationError(f"Template '{template_name}' not found")
            monsters = self.builder.create_encounter_from_template(template)
            balance = self.validate_encounter_balance(monsters, party_level, party_size)
            warnings = self.generate_encounter_warnings(monsters, party_level, party_size)
            session['encounter_monsters'] = monsters
            session['selected_encounter'] = template_name
            import logging
            logging.info(f'handle_prebuilt_encounter: session_id={session.get("session_id")}')
            logging.info('handle_prebuilt_encounter: Saving monsters to session:')
            for m in monsters:
                logging.info(f"Type: {type(m)}, Name: {getattr(m, 'name', None)}, Data: {m}")
            return {"balance": balance, "warnings": warnings, "monsters": monsters, "template": template}
        except FileNotFoundError as e:
            log_exception(e)
            raise APIError(f"Encounter templates file not found: {self.templates_file}")
        except json.JSONDecodeError as e:
            log_exception(e)
            raise ValidationError(f"Invalid JSON in encounter templates file: {e}")
        except ValueError as e:
            log_exception(e)
            raise ValidationError(f"Encounter creation failed: {e}")
        except Exception as e:
            log_exception(e)
            raise ValidationError(f"Failed to handle prebuilt encounter: {e}")

    def validate_encounter_balance(self, monsters, party_level, party_size):
        try:
            return self.builder.calculate_encounter_difficulty(monsters, party_level, party_size)
        except Exception as e:
            log_exception(e)
            raise ValidationError(f"Failed to validate encounter balance: {e}")

    def generate_encounter_warnings(self, monsters, party_level, party_size):
        try:
            warning = self.builder.generate_encounter_warning(monsters, party_level, party_size)
            # Return as a list for consistency with the frontend
            return [warning] if warning and warning != "Encounter is balanced." else []
        except Exception as e:
            log_exception(e)
            raise ValidationError(f"Failed to generate encounter warnings: {e}") 