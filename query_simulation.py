"""
Quick script to query simulation data
"""
from models.db import DatabaseManager

db = DatabaseManager()

sim_id = 3987

# Get simulation details
sim = db.get_simulation(sim_id)
print("=" * 80)
print(f"SIMULATION {sim_id}")
print("=" * 80)
if sim:
    print(f"Result: {sim.get('result')}")
    print(f"Rounds: {sim.get('rounds')}")
    print(f"Party Level: {sim.get('party_level')}")
    print(f"Encounter Type: {sim.get('encounter_type')}")
    print(f"Party HP Remaining: {sim.get('party_hp_remaining')}")
    print(f"Created: {sim.get('created_at')}")
else:
    print("Simulation not found!")
    exit(1)

print("\n" + "=" * 80)
print("COMBAT LOGS")
print("=" * 80)

# Get combat logs
logs = db.get_combat_logs(sim_id)

print(f"\nFound {len(logs)} total actions:")
print("-" * 80)
for log in logs:
    print(f"Round {log['round_number']}: {log['character_name']} -> {log['target']}")
    print(f"  Action: {log['action_type']}, Result: {log['result']}, Damage: {log['damage']}")
    print()
