"""Diagnostic script that runs a simulation EXACTLY like the controller does."""

import sys
import json
from controllers.simulation_controller import SimulationController
from models.db import DatabaseManager

# Create controller
controller = SimulationController()

# Load level 5 characters
with open('data/characters.json', 'r') as f:
    char_data = json.load(f)

# Find level 5
level_5_party = None
for level_obj in char_data:
    if level_obj.get('level') == 5:
        level_5_party = level_obj.get('party', [])
        break

if not level_5_party:
    print("ERROR: No level 5 party found")
    sys.exit(1)

print("=" * 70)
print("DIAGNOSTIC: Simulating Level 5 Party vs Troll")
print("=" * 70)

# Load monsters
with open('data/monsters.json', 'r') as f:
    monster_data = json.load(f)

# Find a troll
troll = None
for monster in monster_data.get('monsters', []):
    if monster.get('name') == 'Troll':
        troll = monster
        break

if not troll:
    print("ERROR: No Troll found")
    sys.exit(1)

print(f"\nParty: {[c['name'] for c in level_5_party]}")
print(f"Monsters: [Troll]")

# Run simulation using the ACTUAL controller
print("\nRunning simulation through SimulationController...")
print("-" * 70)

result = controller.run_simulation(
    party_data=level_5_party,
    monsters_data=[troll],
    session_id="diagnostic_session"
)

print("\n" + "=" * 70)
print("SIMULATION RESULTS")
print("=" * 70)

print(f"Winner: {result.get('winner')}")
print(f"Rounds: {result.get('rounds')}")
print(f"Simulation ID: {result.get('simulation_id')}")

# Get the logs from database
db = DatabaseManager()
sim_id = result.get('simulation_id')

if sim_id:
    logs = db.get_combat_logs(sim_id)

    # Count action types
    action_types = {}
    for log in logs:
        atype = log.get('action_type', 'unknown')
        action_types[atype] = action_types.get(atype, 0) + 1

    print(f"\nTotal actions logged: {len(logs)}")
    print(f"Action type breakdown: {action_types}")

    # Show spell actions
    spell_actions = [l for l in logs if l.get('action_type') == 'spell']
    print(f"\nSpell actions: {len(spell_actions)}")
    if spell_actions:
        print("Spell action details:")
        for sa in spell_actions:
            print(f"  Round {sa.get('round_number')}: {sa.get('character_name')} - {sa.get('result')}")
    else:
        print("  NO SPELL ACTIONS FOUND!")

    # Check for any healing-related text
    healing_mentions = [l for l in logs if 'heal' in str(l.get('result', '')).lower()]
    if healing_mentions:
        print(f"\nHealing mentions: {len(healing_mentions)}")
        for h in healing_mentions[:5]:
            print(f"  {h.get('character_name')}: {h.get('result')}")

    # Show some sample actions
    print(f"\nFirst 10 actions:")
    for i, log in enumerate(logs[:10]):
        print(f"  {i+1}. R{log.get('round_number')} {log.get('character_name'):15} [{log.get('action_type'):7}] {log.get('result')[:50]}")

print("\n" + "=" * 70)
