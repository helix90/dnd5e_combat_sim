"""
Build Character objects from characters.json data.

Shared by the single and batch simulation controllers so both get the same weapons,
class features and spells.
"""
import logging
from typing import Any, Dict, List

from models.actions import AttackAction
from models.character import Character
from models.weapons import weapon_type_for

logger = logging.getLogger(__name__)


def build_weapon_actions(action_dicts: List[Dict[str, Any]], character_class: str,
                         spell_names: List[str]) -> List[AttackAction]:
    """
    Turn a character's action entries into weapon attacks. Entries named after a spell the
    character knows (e.g. 'Fire Bolt') are skipped: those are cast through the spell system,
    which uses the spellcasting ability and scales cantrip damage with level.
    """
    actions = []
    for ad in action_dicts or []:
        if ad.get('type') != 'attack' or ad.get('name') in spell_names:
            continue
        name = ad.get('name', 'Attack')
        actions.append(AttackAction(
            name=name,
            description=ad.get('description', name),
            weapon_name=name,
            damage_dice=ad.get('damage_dice', '1d6'),
            damage_type=ad.get('damage_type', 'bludgeoning'),
            weapon_type=ad.get('weapon_type') or weapon_type_for(name, character_class),
            hit_bonus=ad.get('hit_bonus'),
            on_hit=ad.get('on_hit'),
            reach=ad.get('reach'),
            range=ad.get('range'),
        ))
    return actions


def build_character(data: Dict[str, Any], spell_manager: Any = None) -> Character:
    """
    Build a Character from a characters.json entry, as returned by PartyLoader.

    The character's level comes from the data, so it always matches the HP, spell slots and
    proficiency bonus it was written for. Entries with no 'actions' (e.g. a bare party member
    whose full data wasn't found) get Character's default attacks.

    Args:
        data: The character's entry from characters.json
        spell_manager: Looks up Spell objects for the character's spell list
    """
    character_class = data.get('character_class') or data.get('class', 'Fighter')
    spell_list = list(data.get('spell_list', []))
    spells = [spell_manager.get_spell(name) for name in spell_list] if spell_manager is not None else []
    return Character(
        name=data.get('name', 'Unknown'),
        level=data.get('level', 1),
        character_class=character_class,
        race=data.get('race', 'Human'),
        ability_scores=data.get('ability_scores', {'str': 10, 'dex': 10, 'con': 10, 'int': 10, 'wis': 10, 'cha': 10}),
        hp=data.get('hp', 10),
        ac=data.get('ac', 10),
        proficiency_bonus=data.get('proficiency_bonus', 2),
        actions=(build_weapon_actions(data['actions'], character_class, spell_list)
                 if 'actions' in data else None),
        equipment=data.get('equipment', []),
        spell_slots=data.get('spell_slots', {}),
        class_features=data.get('class_features', []),
        spell_list=spell_list,
        saving_throw_proficiencies=data.get('saving_throw_proficiencies', []),
        features=data.get('features', []),
        items=data.get('items', []),
        spells=[spell for spell in spells if spell],
        reactions=data.get('reactions', []),
        bonus_actions=data.get('bonus_actions', []),
        initiative_bonus=data.get('initiative_bonus', 0),
        notes=data.get('notes', ''),
        size=data.get('size', 'medium'),
        speed=data.get('speed'),
    )


def build_party(party: List[Any], spell_manager: Any = None) -> List[Character]:
    """
    Turn a party from PartyLoader.get_party_with_level (character dicts, or already-built
    Character objects) into Character objects. Anything else is skipped with a warning.
    """
    characters = []
    for member in party or []:
        if isinstance(member, Character):
            characters.append(member)
        elif isinstance(member, dict):
            characters.append(build_character(member, spell_manager))
        else:
            logger.warning(f"Skipping party member with unexpected type: {type(member)}")
    return characters
