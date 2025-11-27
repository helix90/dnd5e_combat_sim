"""Test creating a simulation through the Flask app to verify fixes work end-to-end."""

import sys
import json

# Add the app to the path
sys.path.insert(0, '/home/helix/dnd5e_combat_sim')

from app import app
from models.db import DatabaseManager

print("=" * 70)
print("FLASK APP END-TO-END TEST")
print("=" * 70)

# Create a test client
client = app.test_client()

# Load level 5 party
with open('data/characters.json', 'r') as f:
    char_data = json.load(f)

level_5_party = None
for level_obj in char_data:
    if level_obj.get('level') == 5:
        level_5_party = level_obj.get('party', [])
        break

# Damage some characters to trigger healing
for char in level_5_party:
    if char.get('character_class') in ['Fighter', 'Barbarian']:
        char['hp'] = 5  # Set to critical HP

# Load a troll
with open('data/monsters.json', 'r') as f:
    monster_data = json.load(f)

troll = None
for monster in monster_data.get('monsters', []):
    if monster.get('name') == 'Troll':
        troll = monster
        break

print("\nTest setup:")
print(f"  Party: Level 5, {len(level_5_party)} characters")
print(f"  Monster: {troll.get('name')}")
print(f"  Some fighters/barbarians set to 5 HP to trigger healing")

# Make request to run simulation
print("\n" + "-" * 70)
print("CALLING /api/run_simulation")
print("-" * 70)

response = client.post('/api/run_simulation', json={
    'party_level': 5,
    'party_data': level_5_party,
    'monsters_data': [troll]
})

if response.status_code != 200:
    print(f"ERROR: Request failed with status {response.status_code}")
    print(f"Response: {response.data}")
    sys.exit(1)

result = response.get_json()
sim_id = result.get('simulation_id')

if not sim_id:
    print(f"ERROR: No simulation_id in response")
    print(f"Response: {result}")
    sys.exit(1)

print(f"\n✓ Simulation created successfully")
print(f"  Simulation ID: {sim_id}")
print(f"  Winner: {result.get('winner')}")
print(f"  Rounds: {result.get('rounds')}")

# Check the combat logs
print("\n" + "=" * 70)
print("CHECKING COMBAT LOGS IN DATABASE")
print("=" * 70)

db = DatabaseManager()
logs = db.get_combat_logs(sim_id)

# Count action types
action_types = {}
for log in logs:
    atype = log.get('action_type', 'unknown')
    action_types[atype] = action_types.get(atype, 0) + 1

print(f"\nTotal actions: {len(logs)}")
print(f"Action type breakdown:")
for atype, count in sorted(action_types.items()):
    print(f"  {atype}: {count}")

# Check for spell actions
spell_actions = [l for l in logs if l.get('action_type') == 'spell']

if spell_actions:
    print(f"\n✓ SUCCESS: {len(spell_actions)} SPELL ACTIONS FOUND!")
    print("\nSpell action details:")
    for sa in spell_actions[:10]:
        round_num = sa.get('round_number', 0)
        char_name = sa.get('character_name', 'Unknown')
        result_text = sa.get('result', '')
        print(f"  Round {round_num}: {char_name} - {result_text[:80]}")
else:
    print(f"\n✗ FAILURE: NO SPELL ACTIONS IN DATABASE")
    print("\nFirst 10 actions:")
    for i, log in enumerate(logs[:10]):
        print(f"  {i+1}. R{log.get('round_number')} {log.get('character_name'):15} [{log.get('action_type'):7}] {log.get('result')[:40]}")

print("\n" + "=" * 70)
print("TEST COMPLETE")
print("=" * 70)

if spell_actions:
    print("\n✓✓✓ FIXES VERIFIED WORKING END-TO-END! ✓✓✓")
    print(f"Simulation {sim_id} contains {len(spell_actions)} spell actions.")
else:
    print("\n✗✗✗ FIXES NOT WORKING IN FLASK APP ✗✗✗")
    sys.exit(1)
