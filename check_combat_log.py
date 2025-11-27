"""Check what's actually in the combat log before database save."""

import json
from models.character import Character
from models.monster import Monster
from models.spell_manager import SpellManager
from models.combat import Combat

# Create spell manager
spell_manager = SpellManager()

# Load level 5 character data
with open('data/characters.json', 'r') as f:
    char_data = json.load(f)

level_5_party = None
for level_obj in char_data:
    if level_obj.get('level') == 5:
        level_5_party = level_obj.get('party', [])
        break

# Create characters
characters = []
for char_data in level_5_party:
    char = Character(
        name=char_data.get('name', 'Unknown'),
        level=5,
        character_class=char_data.get('character_class', 'Fighter'),
        race=char_data.get('race', 'Human'),
        ability_scores=char_data.get('ability_scores', {}),
        hp=char_data.get('hp', 30),
        ac=char_data.get('ac', 15),
        proficiency_bonus=char_data.get('proficiency_bonus', 3),
        spell_slots=char_data.get('spell_slots', {}),
        spell_list=char_data.get('spell_list', [])
    )

    # Add spells
    for spell_name in char_data.get('spell_list', []):
        spell = spell_manager.get_spell(spell_name)
        if spell:
            char.add_spell(spell)

    # Set low HP to trigger healing
    if char_data.get('character_class') in ['Fighter', 'Barbarian']:
        char.hp = 5

    characters.append(char)

# Create monsters
monsters = []
for i in range(3):
    monster = Monster(
        name=f"Tough Goblin {i+1}",
        challenge_rating="1/2",
        hp=50,
        ac=13,
        ability_scores={'str': 10, 'dex': 14, 'con': 12, 'int': 8, 'wis': 8, 'cha': 8},
        actions=[]
    )
    monsters.append(monster)

# Run combat
participants = characters + monsters
combat = Combat(participants)
result = combat.run()

print("=" * 70)
print("COMBAT LOG ANALYSIS")
print("=" * 70)

# Get the raw log
log = result.get('log', [])
print(f"\nTotal log entries: {len(log)}")

# Count action types in the RAW log
action_entries = [e for e in log if e.get('type') == 'action']
print(f"Action entries: {len(action_entries)}")

action_type_counts = {}
spell_actions = []
for entry in action_entries:
    result_dict = entry.get('result', {})
    action_type = result_dict.get('type', 'unknown')
    action_type_counts[action_type] = action_type_counts.get(action_type, 0) + 1

    if action_type == 'spell':
        spell_actions.append(entry)

print(f"\nAction type breakdown in RAW log:")
for atype, count in sorted(action_type_counts.items()):
    print(f"  {atype}: {count}")

if spell_actions:
    print(f"\n✓ SUCCESS: {len(spell_actions)} spell actions in RAW log!")
    print("\nSpell action details:")
    for sa in spell_actions[:10]:
        result_dict = sa.get('result', {})
        round_num = sa.get('round', 0)
        char_name = result_dict.get('caster', 'Unknown')
        spell_name = result_dict.get('spell', 'Unknown')
        target = result_dict.get('target', 'Unknown')
        healing = result_dict.get('healing', 0)
        print(f"  Round {round_num}: {char_name} cast {spell_name} on {target} (healed: {healing})")
else:
    print(f"\n✗ FAILURE: NO SPELL ACTIONS in raw log")
    print("\nFirst 10 action entries:")
    for i, entry in enumerate(action_entries[:10]):
        result_dict = entry.get('result', {})
        print(f"  {i+1}. Round {entry.get('round')}: {result_dict}")

print("=" * 70)
