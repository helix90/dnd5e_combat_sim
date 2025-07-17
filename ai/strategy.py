from abc import ABC, abstractmethod
from typing import Any, List
import logging
logger = logging.getLogger()
from models.spells import SpellAction

class AIStrategy(ABC):
    """
    Base class for AI tactical decision-making in combat.
    """
    @abstractmethod
    def choose_action(self, combatant: Any, combat_state: Any) -> Any:
        """
        Decide which action the combatant should take given the combat state.
        """
        pass

    @abstractmethod
    def evaluate_targets(self, combatant: Any, potential_targets: List[Any], combat_state: Any) -> List[Any]:
        """
        Evaluate and rank potential targets for the combatant.
        """
        pass

    @abstractmethod
    def threat_assessment(self, combatant: Any, combat_state: Any) -> float:
        """
        Assess the threat posed by or to the combatant in the current state.
        """
        pass

    @abstractmethod
    def opportunity_cost_analysis(self, combatant: Any, action: Any, combat_state: Any) -> float:
        """
        Analyze the opportunity cost of taking a given action.
        """
        pass 

class PartyAIStrategy(AIStrategy):
    """
    AI strategy for party members (heroes/PCs).
    Prioritizes protecting low-HP allies, healing, focus fire, and spell optimization.
    """
    def choose_action(self, combatant: Any, combat_state: Any) -> Any:
        """
        Decide which action the party member should take.
        - Heal allies below 25% HP if possible
        - Focus fire on most dangerous enemy
        - Use spells optimally based on encounter length
        """
        # Example logic (to be expanded):
        # 1. Heal lowest-HP ally if any below 25%
        allies = [c for c in combat_state['allies'] if c.is_alive()]
        low_hp_allies = [a for a in allies if hasattr(a, 'max_hp') and a.hp / a.max_hp < 0.25]
        if low_hp_allies:
            healer = combatant
            healing_spells = [s for s in getattr(healer, 'spells', {}).values() if hasattr(s, 'healing') and s.healing]
            if healing_spells:
                # Pick the most injured ally
                target = min(low_hp_allies, key=lambda a: a.hp / a.max_hp if hasattr(a, 'max_hp') else a.hp)
                spell = healing_spells[0]  # TODO: pick best spell
                spell_action = SpellAction(spell)
                return {'type': 'cast_spell', 'spell': spell_action, 'target': target}
        # 2. Focus fire on most dangerous enemy
        enemies = [c for c in combat_state['enemies'] if c.is_alive()]
        if enemies:
            dangerous = max(enemies, key=lambda e: self.threat_assessment(e, combat_state))
            # Prefer spell attack if available for spellcasters
            spellcaster_classes = ['Wizard', 'Cleric']
            if getattr(combatant, 'character_class', None) in spellcaster_classes:
                spell_attacks = [a for a in getattr(combatant, 'actions', []) if hasattr(a, 'name') and a.name in ["Fire Bolt", "Sacred Flame"]]
                if spell_attacks:
                    best_spell = max(spell_attacks, key=lambda a: a.hit_bonus(combatant))
                    logger.info(f"[AI] {combatant.name} chooses spell attack: {best_spell.name} vs {dangerous.name}")
                    return {'type': 'attack', 'action': best_spell, 'target': dangerous}
            # Otherwise, prefer attack or damaging spell
            attack_actions = [a for a in getattr(combatant, 'actions', []) if hasattr(a, 'action_type') and a.action_type == 'attack']
            if attack_actions:
                best_action = max(
                    attack_actions,
                    key=lambda a: a.hit_bonus(combatant)
                )
                best_bonus = best_action.hit_bonus(combatant)
                logger.info(f"[AI] {combatant.name} chooses attack: {best_action.name} (bonus {best_bonus}) vs {dangerous.name}")
                return {'type': 'attack', 'action': best_action, 'target': dangerous}
            damaging_spells = [s for s in getattr(combatant, 'spells', {}).values() if hasattr(s, 'damage_dice') and s.damage_dice]
            if damaging_spells:
                spell = damaging_spells[0]
                spell_action = SpellAction(spell)
                logger.info(f"[AI] {combatant.name} chooses spell: {spell.name} vs {dangerous.name}")
                return {'type': 'cast_spell', 'spell': spell_action, 'target': dangerous}
        # 3. Default: Dodge or defend
        return {'type': 'defend'}

    def evaluate_targets(self, combatant: Any, potential_targets: List[Any], combat_state: Any) -> List[Any]:
        """
        Rank targets by threat and vulnerability.
        """
        return sorted(potential_targets, key=lambda t: self.threat_assessment(t, combat_state), reverse=True)

    def threat_assessment(self, combatant: Any, combat_state: Any) -> float:
        """
        Assess threat based on damage output, HP, and special abilities.
        """
        # Example: threat = (damage potential) + (max_hp / 10) + (special ability bonus)
        threat = getattr(combatant, 'level', 1) + getattr(combatant, 'hp', 1) / 10
        if hasattr(combatant, 'special_abilities') and combatant.special_abilities:
            threat += 2
        return threat

    def opportunity_cost_analysis(self, combatant: Any, action: Any, combat_state: Any) -> float:
        """
        Estimate opportunity cost (e.g., spell slot usage vs. encounter length).
        """
        # Placeholder: prefer cantrips if many encounters remain
        if hasattr(action, 'level') and action.level > 0:
            if combat_state.get('encounters_remaining', 1) > 2:
                return 2.0  # High cost
        return 1.0  # Default cost 

class MonsterAIStrategy(AIStrategy):
    """
    AI strategy for monsters.
    Targets based on threat, uses special abilities, and spreads damage.
    """
    def choose_action(self, combatant: Any, combat_state: Any) -> Any:
        """
        Decide which action the monster should take.
        - Target high-threat enemies
        - Use special abilities when advantageous
        - Spread damage if possible
        """
        enemies = [c for c in combat_state['enemies'] if c.is_alive()]
        if not enemies:
            return {'type': 'wait'}
        
        # 1. Use special ability if available and advantageous
        specials = [a for a in getattr(combatant, 'actions', []) if hasattr(a, 'action_type') and a.action_type == 'special']
        if specials:
            # TODO: Add logic to determine advantage
            target = self.evaluate_targets(combatant, enemies, combat_state)[0]
            return {'type': 'special', 'action': specials[0], 'target': target}
        
        # 2. Improved randomization for better target distribution
        import random
        
        if len(enemies) > 1:
            # Create a more robust randomization based on monster name and round
            monster_name = getattr(combatant, 'name', 'Unknown')
            round_num = combat_state.get('round', 1)
            
            # Create a deterministic but varied seed for each monster
            monster_seed = sum(ord(c) for c in monster_name) + round_num * 13
            random.seed(monster_seed)
            
            # Use different targeting strategies based on the pseudo-random number
            strategy_roll = random.random()
            
            if strategy_roll < 0.4:
                # 40% chance: Target the least damaged enemy (spread damage)
                target = min(enemies, key=lambda e: e.hp / e.max_hp if hasattr(e, 'max_hp') else e.hp)
            elif strategy_roll < 0.7:
                # 30% chance: Target the most threatening enemy (focus fire)
                target = max(enemies, key=lambda e: self.threat_assessment(e, combat_state))
            elif strategy_roll < 0.85:
                # 15% chance: Target the lowest HP enemy (finish off weak targets)
                target = min(enemies, key=lambda e: e.hp)
            else:
                # 15% chance: Random target
                target = random.choice(enemies)
            
            # Reset random seed to avoid affecting other parts of the system
            random.seed()
        else:
            # Only one enemy, target them
            target = enemies[0]
        
        attack_actions = [a for a in getattr(combatant, 'actions', []) if hasattr(a, 'action_type') and a.action_type == 'attack']
        if attack_actions:
            return {'type': 'attack', 'action': attack_actions[0], 'target': target}
        
        # 3. Default: wait if no attack actions available
        return {'type': 'wait'}

    def evaluate_targets(self, combatant: Any, potential_targets: List[Any], combat_state: Any) -> List[Any]:
        """
        Rank targets by threat level (descending).
        """
        return sorted(potential_targets, key=lambda t: self.threat_assessment(t, combat_state), reverse=True)

    def threat_assessment(self, combatant: Any, combat_state: Any) -> float:
        """
        Assess threat based on damage output, HP, and class features.
        """
        threat = getattr(combatant, 'level', 1) + getattr(combatant, 'hp', 1) / 10
        if hasattr(combatant, 'class_features') and combatant.class_features:
            threat += 2
        return threat

    def opportunity_cost_analysis(self, combatant: Any, action: Any, combat_state: Any) -> float:
        """
        Estimate opportunity cost for monsters (e.g., recharge abilities).
        """
        # Placeholder: prefer basic attacks unless special is available
        if getattr(action, 'action_type', '') == 'special':
            return 0.5  # Lower cost if special is available
        return 1.0 