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

    def execute_simulation(self, party, monsters, session_id=None):
        """
        Execute a combat simulation in a background thread.
        """
        if session_id is None:
            session_id = session.get('session_id', 'default')
        
        def run():
            try:
                # Convert party dictionaries to Character objects
                character_objects = []
                if party:
                    for char_data in party:
                        if isinstance(char_data, dict):
                            # Load full character data from characters.json
                            full_char_data = self._load_full_character_data(char_data)
                            if full_char_data:
                                char = Character(
                                    name=full_char_data.get('name', char_data.get('name', 'Unknown')),
                                    level=full_char_data.get('level', char_data.get('level', 1)),
                                    character_class=full_char_data.get('character_class', char_data.get('class', 'Fighter')),
                                    race=full_char_data.get('race', 'Human'),
                                    ability_scores=full_char_data.get('ability_scores', {'str': 10, 'dex': 10, 'con': 10, 'int': 10, 'wis': 10, 'cha': 10}),
                                    hp=full_char_data.get('hp', 10),
                                    ac=full_char_data.get('ac', 10),
                                    proficiency_bonus=full_char_data.get('proficiency_bonus', 2),
                                    spell_slots=full_char_data.get('spell_slots', {}),
                                    spell_list=full_char_data.get('spell_list', [])
                                )
                                # Add spells to character
                                for spell_name in full_char_data.get('spell_list', []):
                                    spell = self.spell_manager.get_spell(spell_name)
                                    if spell:
                                        char.add_spell(spell)
                                character_objects.append(char)
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
                log = []
                def progress_callback(state):
                    self.simulation_states[session_id] = state
                result = combat.run(progress_callback=progress_callback)
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
        """
        try:
            with open('data/characters.json', 'r') as f:
                characters_data = json.load(f)
            
            char_name = char_data.get('name', '')
            char_class = char_data.get('class', '')
            char_level = char_data.get('level', 1)
            
            # Find matching character data
            for level_data in characters_data:
                if level_data.get('level') == char_level:
                    for char in level_data.get('party', []):
                        if (char.get('name') == char_name and 
                            char.get('character_class') == char_class):
                            return char
            
            return None
        except Exception as e:
            log_exception(e)
            return None 