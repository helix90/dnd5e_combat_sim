"""
Build Monster objects from monsters.json data.

Shared by the single and batch simulation controllers so both get the same actions, defenses,
size and speed.
"""
import logging
from typing import Any, Dict, List, Optional

from models.actions import Action, AttackAction
from models.monster import Monster

logger = logging.getLogger(__name__)

DEFAULT_ABILITY_SCORES = {'str': 10, 'dex': 10, 'con': 10, 'int': 10, 'wis': 10, 'cha': 10}
DEFAULT_DAMAGE_DICE = '1d6'
DEFAULT_DAMAGE_TYPE = 'bludgeoning'


def build_monster_actions(action_dicts: Optional[List[Dict[str, Any]]]) -> List[Action]:
    """
    Turn a monster's action entries into actions: attacks become AttackActions, a special
    action with damage dice and a save DC (a breath weapon) becomes an area AttackAction, and
    other specials (e.g. Multiattack) become plain special Actions.
    """
    actions: List[Action] = []
    for ad in action_dicts or []:
        name = ad.get('name', 'Attack' if ad.get('type') == 'attack' else 'Special')
        if ad.get('type') == 'attack':
            actions.append(AttackAction(
                name=name,
                description=ad.get('description', name),
                weapon_name=name,
                damage_dice=ad.get('damage_dice', DEFAULT_DAMAGE_DICE),
                damage_type=ad.get('damage_type', DEFAULT_DAMAGE_TYPE),
                weapon_type=ad.get('weapon_type', 'melee'),
                hit_bonus=ad.get('hit_bonus'),
                area_effect=ad.get('area_effect', False),
                save_type=ad.get('save_type'),
                save_dc=ad.get('save_dc'),
                on_hit=ad.get('on_hit'),
                reach=ad.get('reach'),
                range=ad.get('range'),
                area=ad.get('area'),
                recharge=ad.get('recharge'),
            ))
        elif ad.get('type') == 'special':
            if 'damage_dice' in ad and 'save_dc' in ad:
                actions.append(AttackAction(
                    name=name,
                    description=ad.get('description', name),
                    weapon_name=name,
                    damage_dice=ad.get('damage_dice', DEFAULT_DAMAGE_DICE),
                    damage_type=ad.get('damage_type', 'fire'),
                    weapon_type='melee',  # Not used for save-based attacks
                    hit_bonus=ad.get('hit_bonus'),
                    area_effect=True,
                    save_type=ad.get('save_type', 'dex'),
                    save_dc=ad.get('save_dc', 10),
                    area=ad.get('area'),
                    recharge=ad.get('recharge'),
                ))
            else:
                actions.append(Action(action_type='special', name=name,
                                      description=ad.get('description', name)))
    return actions


def build_monster(data: Dict[str, Any]) -> Monster:
    """Build a Monster from a monsters.json entry (as stored in the encounter)."""
    return Monster(
        name=data.get('name', 'Unknown'),
        challenge_rating=data.get('cr', '1/4'),
        hp=data.get('hp', 10),
        ac=data.get('ac', 10),
        ability_scores=data.get('ability_scores', DEFAULT_ABILITY_SCORES),
        damage_resistances=data.get('damage_resistances', []),
        damage_immunities=data.get('damage_immunities', []),
        damage_vulnerabilities=data.get('damage_vulnerabilities', []),
        special_abilities=data.get('special_abilities', []),
        legendary_actions=data.get('legendary_actions', []),
        multiattack=data.get('multiattack', False),
        regeneration=data.get('regeneration'),
        actions=build_monster_actions(data.get('actions', [])),
        size=data.get('size', 'medium'),
        speed=data.get('speed'),
    )


def build_monsters(monsters: List[Any]) -> List[Monster]:
    """
    Turn an encounter's monsters (dicts, or already-built Monster objects) into Monster objects.
    Anything else is skipped with a warning.
    """
    built = []
    for member in monsters or []:
        if isinstance(member, Monster):
            built.append(member)
        elif isinstance(member, dict):
            built.append(build_monster(member))
        else:
            logger.warning(f"Skipping monster with unexpected type: {type(member)}")
    return built
