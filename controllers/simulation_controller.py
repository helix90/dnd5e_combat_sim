import threading
import json
from typing import Dict, List, Any, Optional
from flask import session
from models.combat import Combat
from models.db import DatabaseManager
from models.character import Character
from models.monster import Monster
from models.spell_manager import SpellManager
from utils.exceptions import SimulationError
from utils.logging import log_exception
import logging
from models.actions import AttackAction, Action

class SimulationController:
    def __init__(self):
        self.db = DatabaseManager()
        self.spell_manager = SpellManager()
        self.simulation_threads = {}  # session_id -> thread
        self.simulation_states = {}   # session_id -> state dict

    def _build_actions_from_dicts(self, action_dicts):
        actions = []
        for ad in action_dicts or []:
            if ad.get('type') == 'attack':
                actions.append(AttackAction(
                    name=ad.get('name', 'Attack'),
                    description=ad.get('description', ad.get('name', 'Attack')),
                    weapon_name=ad.get('name', 'Weapon'),
                    damage_dice=ad.get('damage_dice', '1d6'),
                    damage_type=ad.get('damage_type', 'bludgeoning')
                ))
            elif ad.get('type') == 'special':
                actions.append(Action(
                    action_type='special',
                    name=ad.get('name', 'Special'),
                    description=ad.get('description', ad.get('name', 'Special'))
                ))
        return actions

    def execute_simulation(self, party, monsters, session_id=None, party_level=None):
        """
        Execute a combat simulation in a background thread.
        """
        if session_id is None:
            session_id = session.get('session_id', 'default')
        if party_level is None:
            party_level = session.get('selected_party_level', 5)
        def run():
            log = []
            try:
                # Convert party dictionaries to Character objects
                character_objects = []
                if party:
                    for char_data in party:
                        if isinstance(char_data, dict):
                            # Override level with selected party level
                            char_data = char_data.copy()
                            char_data['level'] = party_level
                            # Ensure both 'class' and 'character_class' are set for lookup
                            if 'class' in char_data:
                                char_data['character_class'] = char_data['class']
                            elif 'character_class' in char_data:
                                char_data['class'] = char_data['character_class']
                            # Load full character data from characters.json
                            full_char_data = self._load_full_character_data(char_data)
                            if full_char_data:
                                # Determine the actual level of the matched data
                                actual_level = full_char_data.get('level', party_level)
                                char = Character(
                                    name=full_char_data.get('name', char_data.get('name', 'Unknown')),
                                    level=party_level,  # Still instantiate at requested level for mechanics
                                    character_class=full_char_data.get('character_class', char_data.get('class', 'Fighter')),
                                    race=full_char_data.get('race', 'Human'),
                                    ability_scores=full_char_data.get('ability_scores', {'str': 10, 'dex': 10, 'con': 10, 'int': 10, 'wis': 10, 'cha': 10}),
                                    hp=full_char_data.get('hp', 10),
                                    ac=full_char_data.get('ac', 10),
                                    proficiency_bonus=full_char_data.get('proficiency_bonus', 2),
                                    spell_slots=full_char_data.get('spell_slots', {}),
                                    spell_list=full_char_data.get('spell_list', []),
                                    features=full_char_data.get('features', []),
                                    items=full_char_data.get('items', []),
                                    spells=full_char_data.get('spells', {}),
                                    actions=full_char_data.get('actions', []),
                                    reactions=full_char_data.get('reactions', []),
                                    bonus_actions=full_char_data.get('bonus_actions', []),
                                    initiative_bonus=full_char_data.get('initiative_bonus', 0),
                                    notes=full_char_data.get('notes', ''),
                                )
                                # Add spells to character
                                for spell_name in full_char_data.get('spell_list', []):
                                    spell = self.spell_manager.get_spell(spell_name)
                                    if spell:
                                        char.add_spell(spell)
                                character_objects.append(char)
                                import logging
                                logging.info(f"CHARACTER INSTANTIATED (full data): Name={char.name}, Class={char.character_class}, Level={actual_level}, AC={char.ac}, HP={char.hp}")
                                log.append(f"CHARACTER INSTANTIATED: Name={char.name}, Class={char.character_class}, Level={actual_level}")
                            else:
                                # Fallback to basic character creation
                                char = Character(
                                    name=char_data.get('name', 'Unknown'),
                                    level=char_data.get('level', 1),
                                    character_class=char_data.get('class', 'Fighter'),
                                    race=char_data.get('race', 'Human'),
                                    ability_scores=char_data.get('ability_scores', {'str': 10, 'dex': 10, 'con': 10, 'int': 10, 'wis': 10, 'cha': 10}),
                                    hp=char_data.get('hp', 10),
                                    ac=char_data.get('ac', 10),
                                    proficiency_bonus=char_data.get('proficiency_bonus', 2)
                                )
                                character_objects.append(char)
                                import logging
                                logging.warning(f"CHARACTER INSTANTIATED (FALLBACK): Name={char.name}, Class={char.character_class}, Level={char.level}, AC={char.ac}, HP={char.hp}")
                                log.append(f"CHARACTER INSTANTIATED: Name={char.name}, Class={char.character_class}, Level={char.level}")
                        elif isinstance(char_data, Character):
                            character_objects.append(char_data)
                
                # Convert monster dictionaries to Monster objects
                monster_objects = []
                if monsters:
                    for monster_data in monsters:
                        if isinstance(monster_data, dict):
                            actions = self._build_actions_from_dicts(monster_data.get('actions', []))
                            monster = Monster(
                                name=monster_data.get('name', 'Unknown'),
                                challenge_rating=monster_data.get('cr', '1/4'),
                                hp=monster_data.get('hp', 10),
                                ac=monster_data.get('ac', 10),
                                ability_scores=monster_data.get('ability_scores', {'str': 10, 'dex': 10, 'con': 10, 'int': 10, 'wis': 10, 'cha': 10}),
                                damage_resistances=monster_data.get('damage_resistances', []),
                                damage_immunities=monster_data.get('damage_immunities', []),
                                special_abilities=monster_data.get('special_abilities', []),
                                legendary_actions=monster_data.get('legendary_actions', []),
                                multiattack=monster_data.get('multiattack', False),
                                actions=actions
                            )
                            import logging
                            logging.info(f"INSTANTIATED MONSTER: {repr(monster)}")
                            monster_objects.append(monster)
                        elif isinstance(monster_data, Monster):
                            monster_objects.append(monster_data)
                
                # Create combat with proper objects
                logging.info('MONSTER OBJECTS FOR ENCOUNTER:')
                for m in monster_objects:
                    logging.info(f"Type: {type(m)}, Name: {getattr(m, 'name', None)}")
                combat = Combat(character_objects + monster_objects)
                def progress_callback(state):
                    # Merge our log with the combat log for the test
                    merged_log = log + state.get('log', [])
                    state['log'] = merged_log
                    self.simulation_states[session_id] = state
                self.simulation_states[session_id] = {'progress': 0, 'log': log, 'done': False}
                result = combat.run(progress_callback=progress_callback)
                # After combat, merge logs for final state
                final_log = log + result.get('log', [])
                self.simulation_states[session_id]['log'] = final_log
                self.save_simulation_results(result, session_id)
                self.simulation_states[session_id]['done'] = True
            except Exception as e:
                log_exception(e)
                self.simulation_states[session_id] = {'error': str(e), 'done': True}
                raise SimulationError(f"Simulation execution failed: {e}")
        t = threading.Thread(target=run)
        t.start()
        self.simulation_threads[session_id] = t
        self.simulation_states[session_id] = {'progress': 0, 'log': [], 'done': False}

    def handle_simulation_progress(self):
        """
        Return the current simulation state for this session.
        """
        session_id = session['session_id']
        return self.simulation_states.get(session_id, {'progress': 0, 'log': [], 'done': False})

    def manage_simulation_state(self):
        """
        Manage state for long-running simulations (pause/resume, etc.).
        """
        pass  # For future extension

    def save_simulation_results(self, result, session_id):
        """
        Save simulation results to the database.
        """
        try:
            # Ensure session exists in database before saving simulation results
            self.db.create_session(session_id)
            
            sim_id = self.db.save_simulation_result(session_id, result)
            
            # Store the simulation ID in the session for easy access (only if in request context)
            try:
                session['last_simulation_id'] = sim_id
            except RuntimeError:
                # Working outside of request context, skip session storage
                # The results page will get the simulation ID from the database
                pass
                
            return sim_id
        except Exception as e:
            log_exception(e)
            raise SimulationError(f"Failed to save simulation results: {e}") 

    def _load_full_character_data(self, char_data):
        """
        Load full character data from characters.json based on name and class.
        Updated: Find the highest available level <= requested, or fallback to lowest available.
        """
        try:
            import logging
            with open('data/characters.json', 'r') as f:
                characters_data = json.load(f)
            char_name = char_data.get('name', '').strip().lower()
            char_class = (char_data.get('class') or char_data.get('character_class') or '').strip().lower()
            char_level = char_data.get('level', 1)
            logging.debug(f"LOOKUP: Looking for name='{char_name}', class='{char_class}', level={char_level}")
            # Gather all matching entries for this name/class
            matches = []
            for level_data in characters_data:
                for char in level_data.get('party', []):
                    target_class = (char.get('class') or char.get('character_class') or '').strip().lower()
                    target_name = char.get('name', '').strip().lower()
                    if target_name == char_name and target_class == char_class:
                        matches.append((level_data.get('level'), char))
            if not matches:
                logging.warning(f"NO MATCH for name='{char_name}', class='{char_class}' at any level")
                return None
            # Find the highest level <= requested
            best = None
            best_level = -1
            for lvl, char in matches:
                if lvl is not None and lvl <= char_level and lvl > best_level:
                    best = char
                    best_level = lvl
            if best:
                logging.debug(f"  BEST MATCH for {char_name} at level {best_level}")
                return best
            # Fallback: return the lowest available level
            min_level, min_char = min(matches, key=lambda x: x[0] if x[0] is not None else 999)
            logging.debug(f"  FALLBACK MATCH for {char_name} at level {min_level}")
            return min_char
        except Exception as e:
            log_exception(e)
            return None 