"""
Build Character objects from characters.json data.

Shared by the single and batch simulation controllers so both get the same weapons,
class features and spells.
"""
from typing import Any, Dict, List, Optional

from models.actions import AttackAction
from models.character import Character
from models.weapons import weapon_type_for


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
        ))
    return actions


def build_character(data: Dict[str, Any], spell_manager: Any = None, level: Optional[int] = None) -> Character:
    """
    Build a Character from a full characters.json entry.

    Args:
        data: The character's entry from characters.json
        spell_manager: Looks up Spell objects for the character's spell list
        level: Overrides the level in the data (e.g. the selected party level)
    """
    character_class = data.get('character_class') or data.get('class', 'Fighter')
    spell_list = list(data.get('spell_list', []))
    character = Character(
        name=data.get('name', 'Unknown'),
        level=level if level is not None else data.get('level', 1),
        character_class=character_class,
        race=data.get('race', 'Human'),
        ability_scores=data.get('ability_scores', {'str': 10, 'dex': 10, 'con': 10, 'int': 10, 'wis': 10, 'cha': 10}),
        hp=data.get('hp', 10),
        ac=data.get('ac', 10),
        proficiency_bonus=data.get('proficiency_bonus', 2),
        actions=build_weapon_actions(data.get('actions', []), character_class, spell_list),
        equipment=data.get('equipment', []),
        spell_slots=data.get('spell_slots', {}),
        class_features=data.get('class_features', []),
        spell_list=spell_list,
        saving_throw_proficiencies=data.get('saving_throw_proficiencies', []),
        features=data.get('features', []),
        items=data.get('items', []),
        spells=data.get('spells', {}),
        reactions=data.get('reactions', []),
        bonus_actions=data.get('bonus_actions', []),
        initiative_bonus=data.get('initiative_bonus', 0),
        notes=data.get('notes', ''),
    )
    if spell_manager is not None:
        for spell_name in spell_list:
            spell = spell_manager.get_spell(spell_name)
            if spell:
                character.add_spell(spell)
    return character
