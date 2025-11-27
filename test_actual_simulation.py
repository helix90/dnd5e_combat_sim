"""Test actual simulation flow to find where spells are lost."""

from models.character import Character
from models.monster import Monster
from models.spell_manager import SpellManager
from models.combat import Combat
import json

# Load spell manager
spell_manager = SpellManager()

# Load level 5 character data (same as simulation controller does)
with open('data/characters.json', 'r') as f:
    char_data = json.load(f)

# Find level 5 party
level_5_data = None
for level_obj in char_data:
    if level_obj.get('level') == 5:
        level_5_data = level_obj
        break

print("=" * 70)
print("TESTING ACTUAL SIMULATION FLOW")
print("=" * 70)

# Create characters exactly as simulation_controller does
characters = []
for char_data in level_5_data['party']:
    print(f"\nCreating {char_data['name']}...")

    char = Character(
        name=char_data['name'],
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

    # Set HP to low to trigger healing
    char.hp = 5  # Very low!

    print(f"  Class: {char.character_class}")
    print(f"  HP: {char.hp}/{char.max_hp}")
    print(f"  Spell slots: {char.spell_slots}")
    print(f"  Spell list from data: {char_data.get('spell_list', [])}")

    # Add spells exactly as simulation_controller does
    print(f"  Adding spells...")
    for spell_name in char_data.get('spell_list', []):
        spell = spell_manager.get_spell(spell_name)
        if spell:
            char.add_spell(spell)
            print(f"    - Added {spell.name} (level {spell.level}, healing={spell.healing})")

    print(f"  Character.spells dict has {len(char.spells)} spells: {list(char.spells.keys())}")

    # Check if healing spells are present
    healing_spells = [s for s in char.spells.values() if hasattr(s, 'healing') and s.healing]
    if healing_spells:
        print(f"  ✓ Has {len(healing_spells)} healing spell(s): {[s.name for s in healing_spells]}")
    else:
        print(f"  ✗ NO HEALING SPELLS")

    characters.append(char)

# Create a simple monster
print(f"\nCreating monster...")
monster = Monster(
    name="Test Goblin",
    challenge_rating="1/4",
    hp=20,
    ac=12,
    ability_scores={'str': 8, 'dex': 14, 'con': 10, 'int': 10, 'wis': 8, 'cha': 8},
    actions=[]
)
print(f"  {monster.name}: HP={monster.hp}, AC={monster.ac}")

# Create combat
print(f"\n" + "=" * 70)
print("STARTING COMBAT SIMULATION")
print("=" * 70)

participants = characters + [monster]
combat = Combat(participants)
combat.roll_initiative()

print(f"\nInitiative order:")
for i, p in enumerate(combat.initiative_order):
    print(f"  {i+1}. {p.name} (HP: {p.hp}/{getattr(p, 'max_hp', p.hp)})")

# Run a few turns
print(f"\n" + "-" * 70)
print("RUNNING 5 TURNS")
print("-" * 70)

for turn in range(5):
    participant = combat.next_turn()
    if participant:
        print(f"\nTurn {turn+1}: {participant.name}'s turn")

        # Check if this character has spells
        if hasattr(participant, 'spells'):
            print(f"  Has {len(participant.spells)} spells: {list(participant.spells.keys())}")
            healing_spells = [s for s in participant.spells.values() if hasattr(s, 'healing') and s.healing]
            if healing_spells:
                print(f"  Has healing spells: {[s.name for s in healing_spells]}")

        # Get last action from log
        log = combat.get_combat_log()
        if log:
            last_action = log[-1]
            if last_action.get('type') == 'action':
                result = last_action.get('result', {})
                action = result.get('action', 'Unknown')
                action_type = result.get('type', 'unknown')
                print(f"  Action taken: {action} (type: {action_type})")

                if 'spell' in result:
                    print(f"  ✓ SPELL CAST: {result.get('spell')}")
    else:
        print(f"\nCombat ended after {turn} turns")
        break

# Check final log
print(f"\n" + "=" * 70)
print("COMBAT LOG SUMMARY")
print("=" * 70)

log = combat.get_combat_log()
action_types = {}
for entry in log:
    if entry.get('type') == 'action':
        result = entry.get('result', {})
        atype = result.get('type', 'unknown')
        action_types[atype] = action_types.get(atype, 0) + 1

print(f"Total actions: {len([e for e in log if e.get('type') == 'action'])}")
print(f"Action type breakdown: {action_types}")

spell_count = action_types.get('spell', 0)
if spell_count > 0:
    print(f"\n✓ SUCCESS: {spell_count} spell(s) were cast!")
else:
    print(f"\n✗ FAILURE: NO SPELLS WERE CAST")

print("=" * 70)
