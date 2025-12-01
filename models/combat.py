"""
Combat system for D&D 5e Combat Simulator.

Defines the Combat and CombatLogger classes for managing turn-based combat.
"""
import random
from typing import List, Dict, Any, Optional, TYPE_CHECKING
from utils.exceptions import SimulationError
from utils.logging import log_exception
from ai.strategy import PartyAIStrategy, MonsterAIStrategy
from ai.tactical import TacticalAnalyzer
import logging
logger = logging.getLogger('dnd5e_combat_sim.combat')

if TYPE_CHECKING:
    from models.character import Character
    from models.monster import Monster

class CombatLogger:
    """
    Optimized combat logging with efficient data structures.
    """
    def __init__(self) -> None:
        self.log: List[Dict[str, Any]] = []
        self._round_cache = {}  # Cache for round-specific data
    
    def log_action(self, actor: Any, action_result: dict, round_number: int = 0) -> None:
        """Log action with optimized data structure."""
        self.log.append({
            'type': 'action',
            'actor': getattr(actor, 'name', str(actor)),
            'result': action_result,
            'round': round_number,
            'timestamp': len(self.log)  # Use index as timestamp for efficiency
        })

    def log_round_start(self, round_num: int) -> None:
        """Log round start with caching."""
        if round_num not in self._round_cache:
            self._round_cache[round_num] = True
            self.log.append({
                'type': 'round_start',
                'round': round_num
            })

    def get_combat_log(self) -> List[Dict]:
        """Get combat log with optional filtering."""
        return self.log

class Combat:
    """
    Optimized D&D 5e combat encounter management with efficient data structures and caching.
    """
    def __init__(self, participants: List[Any]) -> None:
        self.participants: List[Any] = participants[:]
        self.initiative_order: List[Any] = []
        self.current_round: int = 1
        self.current_turn: int = 0
        self.logger = CombatLogger()
        # Pre-calculate participant types for efficiency
        from models.character import Character
        from models.monster import Monster
        self._original_characters = [p for p in participants if isinstance(p, Character)]
        self._original_monsters = [p for p in participants if isinstance(p, Monster)]
        # Pre-allocate AI strategies
        self.ai_strategy_map = {}
        for p in participants:
            if isinstance(p, Character):
                self.ai_strategy_map[p] = PartyAIStrategy()
            elif isinstance(p, Monster):
                self.ai_strategy_map[p] = MonsterAIStrategy()
        # Cache for initiative rolls and other calculations
        self._initiative_cache = {}
        self._alive_participants_cache = None
        self._last_alive_check = 0
        self.tactical = TacticalAnalyzer()

    def _get_alive_participants(self) -> List[Any]:
        """Get alive participants with caching for efficiency."""
        if self._alive_participants_cache is None or self._last_alive_check != self.current_round:
            self._alive_participants_cache = [p for p in self.participants if p.is_alive()]
            self._last_alive_check = self.current_round
        return self._alive_participants_cache

    def roll_initiative(self) -> None:
        """
        Optimized initiative rolling with caching and efficient sorting.
        """
        rolls = []
        for p in self.participants:
            # Use cached initiative if available
            if p in self._initiative_cache:
                roll = self._initiative_cache[p]
            else:
                roll = p.roll_initiative()
                self._initiative_cache[p] = roll
            
            # Pre-calculate dex modifier for sorting efficiency
            dex_mod = getattr(p, 'ability_modifier', lambda x: 0)('dex')
            rolls.append((roll, dex_mod, random.random(), p))
        
        # Sort once with all criteria
        rolls.sort(key=lambda x: (-x[0], -x[1], x[2]))
        self.initiative_order = [x[3] for x in rolls]
        self.current_turn = 0
        self.current_round = 1
        # Clear alive cache since initiative order changed
        self._alive_participants_cache = None

    def next_turn(self) -> Optional[Any]:
        """
        Optimized turn advancement with efficient alive participant checking.
        """
        if self.is_combat_over():
            return None
        start = self.current_turn
        n = len(self.initiative_order)
        alive_participants = self._get_alive_participants()
        alive_set = set(alive_participants)
        
        for i in range(n):
            idx = (start + i) % n
            participant = self.initiative_order[idx]
            if participant in alive_set:
                self.current_turn = (idx + 1) % n
                if self.current_turn == 0:
                    self.current_round += 1
                    self.logger.log_round_start(self.current_round)
                    self._alive_participants_cache = None
                    # Tick buffs on all alive participants at the start of each round
                    for p in alive_set:
                        if hasattr(p, 'buffs'):
                            p.buffs.tick_round()
                ai = self.ai_strategy_map.get(participant)
                if ai:
                    combat_state = self._build_combat_state(participant)
                    action_plan = ai.choose_action(participant, combat_state)
                    result = self._execute_action(participant, action_plan)
                    self.logger.log_action(participant, result, self.current_round)
                    if self.is_combat_over():
                        return participant
                return participant
        return None

    def _build_combat_state(self, participant: Any) -> Dict[str, Any]:
        """Build combat state efficiently with participant type checking."""
        is_character = participant in self._original_characters
        # Include ALL allies of the same type (including the participant itself)
        # This allows characters to heal themselves, which is valid in D&D 5e
        allies = [p for p in self.participants if
                 (p in self._original_characters) == is_character and p.is_alive()]
        enemies = [p for p in self.participants if
                   (p in self._original_characters) != is_character and p.is_alive()]

        return {
            'allies': allies,
            'enemies': enemies,
            'round': self.current_round
        }

    def _execute_action(self, participant: Any, action_plan: Dict[str, Any]) -> Dict[str, Any]:
        """Execute action with optimized result handling."""
        action_type = action_plan['type']
        
        if action_type == 'attack':
            action = action_plan['action']
            target = action_plan['target']
            result = action.execute(participant, target)
            # Clear alive cache after damage-dealing action
            if result.get('damage', 0) > 0:
                self._alive_participants_cache = None
            return result
        elif action_type == 'cast_spell':
            spell = action_plan['spell']
            target = action_plan['target']
            result = spell.execute(participant, target)
            # Clear alive cache after spell action
            if result.get('damage', 0) > 0 or result.get('healing', 0) > 0:
                self._alive_participants_cache = None
            return result
        elif action_type == 'special':
            # Handle special actions
            action = action_plan.get('action')
            target = action_plan.get('target')
            action_name = getattr(action, 'name', 'Unknown Action')

            # Check if this is a multiattack
            if action_name.lower() == 'multiattack' and hasattr(participant, 'actions'):
                # Execute multiattack: perform multiple individual attacks
                result = self._execute_multiattack(participant, target, action)
                # Clear alive cache after damage-dealing action
                if result.get('total_damage', 0) > 0:
                    self._alive_participants_cache = None
                return result
            else:
                # Other special actions (not yet implemented)
                result = {'action': action_name, 'target': target, 'type': 'special'}
                return result
        elif action_type == 'defend':
            return {
                'action': 'Defend',
                'type': 'defend',
                'description': 'Takes defensive stance'
            }
        elif action_type == 'wait':
            return {
                'action': 'Wait',
                'type': 'wait',
                'description': 'Takes no action'
            }
        else:
            # Default action
            result = {'action': 'Unknown Action', 'type': 'unknown'}
            return result

    def _execute_multiattack(self, participant: Any, target: Any, multiattack_action: Any) -> Dict[str, Any]:
        """
        Execute a multiattack action by performing multiple individual attacks.

        Parses the multiattack description to determine which attacks to make,
        or uses common patterns (e.g., 1 Bite + 2 Claws for dragons/trolls).

        Args:
            participant: The creature performing multiattack
            target: The target(s) of the attacks
            multiattack_action: The multiattack action object

        Returns:
            Combined result dictionary with all attack results
        """
        description = getattr(multiattack_action, 'description', '').lower()
        attack_actions = [
            a for a in participant.actions
            if hasattr(a, 'action_type') and a.action_type == 'attack'
        ]

        # Map attack names to action objects
        attacks_by_name = {a.name.lower(): a for a in attack_actions}

        # Determine which attacks to perform based on description
        attacks_to_perform = []

        # Common pattern: parse description for attack counts
        # E.g., "one with its bite and two with its claws"
        import re

        # Try to find patterns like "one with its bite", "two with its claws"
        attack_patterns = re.findall(r'(one|two|three|four|1|2|3|4)\s+(?:attack\s+)?with\s+(?:its\s+)?(\w+)', description)

        number_map = {'one': 1, 'two': 2, 'three': 3, 'four': 4, '1': 1, '2': 2, '3': 3, '4': 4}

        for count_str, attack_name in attack_patterns:
            count = number_map.get(count_str.lower(), 1)
            # Find matching attack action (e.g., "bite" matches "Bite", "claws" matches "Claw")
            # Remove trailing 's' to handle plural forms
            attack_name_singular = attack_name.rstrip('s')
            for map_name, action in attacks_by_name.items():
                # Check if either the exact name or singular form matches
                if attack_name in map_name or attack_name_singular in map_name:
                    attacks_to_perform.extend([action] * count)
                    break

        # Fallback: if no pattern matched, use a default (1x first attack + 2x second attack)
        if not attacks_to_perform and len(attack_actions) >= 2:
            attacks_to_perform = [attack_actions[0], attack_actions[1], attack_actions[1]]
        elif not attacks_to_perform and len(attack_actions) == 1:
            attacks_to_perform = [attack_actions[0]] * 2

        # Execute each attack
        attack_results = []
        total_damage = 0
        target_name = getattr(target, 'name', str(target)) if not isinstance(target, list) else ', '.join([getattr(t, 'name', str(t)) for t in target])

        for attack_action in attacks_to_perform:
            attack_result = attack_action.execute(participant, target)
            attack_results.append(attack_result)
            total_damage += attack_result.get('damage', 0)

        # Build combined result
        result = {
            'action': 'Multiattack',
            'target': target_name,
            'type': 'special',
            'multiattack': True,
            'individual_attacks': attack_results,
            'total_damage': total_damage,
            'attacks_performed': [getattr(a, 'name', 'Unknown') for a in attacks_to_perform]
        }

        return result

    def is_combat_over(self) -> bool:
        """
        Check if combat is over efficiently.
        """
        # Use cached alive participants
        alive_participants = self._get_alive_participants()
        alive_set = set(alive_participants)
        all_characters_down = all(p not in alive_set for p in self._original_characters)
        all_monsters_down = all(p not in alive_set for p in self._original_monsters)
        return all_characters_down or all_monsters_down

    def get_current_participant(self) -> Optional[Any]:
        """Get current participant efficiently."""
        if not self.initiative_order:
            return None
        idx = (self.current_turn - 1) % len(self.initiative_order)
        return self.initiative_order[idx]

    def get_initiative_order(self) -> List[Any]:
        """Get initiative order (already cached)."""
        return self.initiative_order[:]

    def get_combat_log(self) -> List[Dict]:
        """Get combat log efficiently."""
        return self.logger.get_combat_log()

    def run(self, progress_callback=None) -> dict:
        """
        Optimized combat simulation with efficient progress tracking.
        """
        try:
            self.roll_initiative()
            max_rounds = 50  # Prevent infinite loops
            
            while not self.is_combat_over() and self.current_round <= max_rounds:
                participant = self.next_turn()
                
                # If no participant returned, combat is over
                if participant is None:
                    break
                
                # Update progress efficiently (only every 5 rounds)
                if progress_callback and self.current_round % 5 == 0:
                    progress = min(100, int((self.current_round / 20) * 100))
                    progress_callback({
                        'progress': progress,
                        'log': self.format_log_for_web(),
                        'done': False
                    })
                
                # Safety check for infinite loops
                if self.current_round > max_rounds:
                    break
            
            # Final callback
            if progress_callback:
                progress_callback({
                    'progress': 100,
                    'log': self.format_log_for_web(),
                    'done': True
                })
            
            # Determine winner efficiently
            alive_participants = self._get_alive_participants()
            alive_set = set(alive_participants)
            
            if all(p not in alive_set for p in self._original_characters):
                winner = 'monsters'
            elif all(p not in alive_set for p in self._original_monsters):
                winner = 'party'
            else:
                winner = 'unknown'
            
            # Calculate party HP remaining
            party_hp_remaining = 0
            for participant in self._original_characters:
                if participant in alive_set:
                    party_hp_remaining += participant.hp
            # Add party_level to result
            party_level = max((getattr(p, 'level', 1) for p in self._original_characters), default=1)
            return {
                'winner': winner,
                'rounds': self.current_round,
                'party_hp_remaining': party_hp_remaining,
                'log': self.logger.get_combat_log(),
                'party_level': party_level
            }
            
        except Exception as e:
            log_exception(e)
            if progress_callback:
                progress_callback({
                    'progress': 100,
                    'log': self.format_log_for_web(),
                    'done': True,
                    'error': str(e)
                })
            raise SimulationError(f"Combat simulation failed: {e}")

    def format_log_for_web(self) -> list:
        """
        Optimized log formatting for web display.
        """
        lines = []
        for entry in self.logger.get_combat_log():
            if entry['type'] == 'round_start':
                lines.append(f"-- Round {entry['round']} --")
            elif entry['type'] == 'action':
                actor = entry['actor']
                result = entry['result']
                if 'action' in result:
                    action = result['action']
                    # Log spell name if present
                    if 'spell' in result:
                        spell_name = result['spell']
                        if 'healing' in result and result['healing'] > 0:
                            lines.append(f"{actor} casts {spell_name} on {result.get('target', '')}: heals {result['healing']} HP.")
                        elif 'damage' in result:
                            lines.append(f"{actor} casts {spell_name} on {result.get('target', '')}: {result['damage']} damage.")
                        else:
                            lines.append(f"{actor} casts {spell_name} on {result.get('target', '')}.")
                    elif 'damage' in result:
                        lines.append(f"{actor} uses {action} on {result.get('target', '')}: {result['damage']} damage.")
                    elif 'healing' in result:
                        lines.append(f"{actor} uses {action} on {result.get('target', '')}: heals {result['healing']} HP.")
                    else:
                        lines.append(f"{actor} uses {action}.")
                else:
                    lines.append(f"{actor} takes an action.")
        return lines

    def pause(self):
        """Stub for future pause functionality."""
        pass

    def resume(self):
        """Stub for future resume functionality."""
        pass 