"""
Test script to verify multiattack implementation works correctly.
"""
from models.character import Character
from models.monster import Monster
from models.combat import Combat
from models.db import DatabaseManager
import json

# Create a simple party
party = [
    Character(
        name="Tank",
        level=5,
        character_class="Fighter",
        race="Human",
        ability_scores={'str': 16, 'dex': 14, 'con': 16, 'int': 10, 'wis': 12, 'cha': 10},
        hp=45,
        ac=18,
        proficiency_bonus=3
    ),
    Character(
        name="Healer",
        level=5,
        character_class="Cleric",
        race="Human",
        ability_scores={'str': 12, 'dex': 10, 'con': 14, 'int': 13, 'wis': 16, 'cha': 14},
        hp=35,
        ac=16,
        proficiency_bonus=3
    )
]

# Load monsters
with open('/home/helix/dnd5e_combat_sim/data/monsters.json', 'r') as f:
    monster_data = json.load(f)

# Find Young Dragon
young_dragon_data = next((m for m in monster_data['monsters'] if m['name'] == 'Young Dragon'), None)
if not young_dragon_data:
    print("ERROR: Young Dragon not found in monsters.json!")
    exit(1)

print("=" * 80)
print("YOUNG DRAGON DATA")
print("=" * 80)
print(f"Name: {young_dragon_data['name']}")
print(f"HP: {young_dragon_data['hp']}")
print(f"AC: {young_dragon_data['ac']}")
print("\nActions:")
for action in young_dragon_data['actions']:
    print(f"  - {action['name']} ({action['type']})")
    if 'description' in action:
        print(f"    Description: {action['description'][:80]}...")
print()

# Create Young Dragon
young_dragon = Monster.from_dict(young_dragon_data)

# Create combat with party vs Young Dragon
participants = party + [young_dragon]
combat = Combat(participants)

print("=" * 80)
print("STARTING COMBAT SIMULATION")
print("=" * 80)
print(f"Party: {[p.name for p in party]}")
print(f"Monsters: {[young_dragon.name]}")
print()

# Run combat
result = combat.run()

print("=" * 80)
print("COMBAT RESULTS")
print("=" * 80)
print(f"Winner: {result['winner']}")
print(f"Rounds: {result['rounds']}")
print(f"Party HP Remaining: {result['party_hp_remaining']}")
print()

# Print combat log
print("=" * 80)
print("COMBAT LOG")
print("=" * 80)
for line in combat.format_log_for_web():
    print(line)
print()

# Check for multiattack usage
print("=" * 80)
print("MULTIATTACK ANALYSIS")
print("=" * 80)
logs = combat.get_combat_log()
multiattack_count = 0
multiattack_damage = 0

for entry in logs:
    if entry['type'] == 'action':
        result = entry['result']
        if result.get('action') == 'Multiattack':
            multiattack_count += 1
            total_damage = result.get('total_damage', 0)
            multiattack_damage += total_damage
            individual_attacks = result.get('individual_attacks', [])
            attacks_performed = result.get('attacks_performed', [])

            print(f"\nRound {entry['round']}: {entry['actor']} uses Multiattack")
            print(f"  Target: {result.get('target')}")
            print(f"  Attacks performed: {attacks_performed}")
            print(f"  Total damage: {total_damage}")
            print(f"  Individual results:")
            for i, attack_result in enumerate(individual_attacks):
                attack_name = attack_result.get('action', 'Unknown')
                damage = attack_result.get('damage', 0)
                hit = attack_result.get('hit', False)
                print(f"    {i+1}. {attack_name}: {'HIT' if hit else 'MISS'} - {damage} damage")

print(f"\n{'='*80}")
print(f"SUMMARY")
print(f"{'='*80}")
print(f"Multiattack used: {multiattack_count} times")
print(f"Total damage from multiattacks: {multiattack_damage}")

if multiattack_count > 0 and multiattack_damage > 0:
    print("\n✅ SUCCESS: Multiattack is working correctly!")
else:
    print("\n❌ FAILURE: Multiattack did not deal damage!")
