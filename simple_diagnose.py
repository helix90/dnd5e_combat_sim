"""Simple diagnostic: run combat directly with controller-created characters."""

import json
from models.character import Character
from models.monster import Monster
from models.spell_manager import SpellManager
from models.combat import Combat
from models.db import DatabaseManager

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

print("=" * 70)
print("SIMPLE DIAGNOSTIC: Direct Combat Simulation")
print("=" * 70)

# Create characters EXACTLY like the simulation controller does
characters = []
for char_data in level_5_party:
    full_char_data = char_data  # In real controller, this goes through _load_full_character_data

    char = Character(
        name=full_char_data.get('name', 'Unknown'),
        level=5,
        character_class=full_char_data.get('character_class', 'Fighter'),
        race=full_char_data.get('race', 'Human'),
        ability_scores=full_char_data.get('ability_scores', {}),
        hp=full_char_data.get('hp', 30),
        ac=full_char_data.get('ac', 15),
        proficiency_bonus=full_char_data.get('proficiency_bonus', 3),
        spell_slots=full_char_data.get('spell_slots', {}),
        spell_list=full_char_data.get('spell_list', [])
    )

    # Add spells EXACTLY like the simulation controller does
    for spell_name in full_char_data.get('spell_list', []):
        spell = spell_manager.get_spell(spell_name)
        if spell:
            char.add_spell(spell)

    # Set low HP to trigger healing
    if full_char_data.get('character_class') in ['Fighter', 'Barbarian']:
        char.hp = 5  # Very low!

    characters.append(char)

# Check who has spells
print("\nCharacters created:")
for char in characters:
    has_spells = len(char.spells) > 0
    healing_spells = [s for s in char.spells.values() if hasattr(s, 'healing') and s.healing]
    print(f"  {char.name:15} {char.character_class:10} HP:{char.hp}/{char.max_hp:3} Spells:{len(char.spells):2} Healing:{len(healing_spells)}")
    if healing_spells:
        print(f"      Healing spells: {[s.name for s in healing_spells]}")
        print(f"      Spell slots: {char.spell_slots_remaining}")

# Create tougher monsters to force longer combat and trigger healing
monsters = []
for i in range(3):
    monster = Monster(
        name=f"Tough Goblin {i+1}",
        challenge_rating="1/2",
        hp=50,  # Much tougher to force multiple rounds
        ac=13,
        ability_scores={'str': 10, 'dex': 14, 'con': 12, 'int': 8, 'wis': 8, 'cha': 8},
        actions=[]
    )
    monsters.append(monster)

print(f"\nMonsters: {len(monsters)} Tough Goblins (HP:50 each, AC:13)")
for m in monsters:
    print(f"  - {m.name}")

# Run combat
print("\n" + "=" * 70)
print("RUNNING COMBAT")
print("=" * 70)

participants = characters + monsters
combat = Combat(participants)
result = combat.run()

print(f"\nWinner: {result['winner']}")
print(f"Rounds: {result['rounds']}")

# Save to database
db = DatabaseManager()
sim_id = db.save_simulation_result("diagnostic_simple", result)
print(f"Saved as simulation ID: {sim_id}")

# Check logs
logs = db.get_combat_logs(sim_id)
action_types = {}
for log in logs:
    atype = log.get('action_type', 'unknown')
    action_types[atype] = action_types.get(atype, 0) + 1

print(f"\nTotal actions: {len(logs)}")
print(f"Action breakdown: {action_types}")

spell_actions = [l for l in logs if l.get('action_type') == 'spell']
if spell_actions:
    print(f"\n✓ SUCCESS: {len(spell_actions)} spell actions found!")
    for sa in spell_actions[:5]:
        print(f"  Round {sa.get('round_number')}: {sa.get('character_name')} - {sa.get('result')}")
else:
    print(f"\n✗ FAILURE: NO SPELL ACTIONS!")
    print(f"\nFirst 10 actions:")
    for i, log in enumerate(logs[:10]):
        print(f"  {i+1}. R{log.get('round_number')} {log.get('character_name'):15} [{log.get('action_type'):7}] {log.get('result')[:40]}")

print("=" * 70)
