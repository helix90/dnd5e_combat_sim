"""
Test to verify that the dragon's actions are being loaded correctly in both simulation types.
"""
import json
from controllers.simulation_controller import SimulationController
from controllers.batch_simulation_controller import BatchSimulationController

# Load dragon from JSON
with open('data/monsters.json', 'r') as f:
    monster_data = json.load(f)

dragon_data = next((m for m in monster_data['monsters'] if m['name'] == 'Young Dragon'), None)

print("=" * 80)
print("YOUNG DRAGON DATA FROM JSON")
print("=" * 80)
print(f"Name: {dragon_data['name']}")
print(f"HP: {dragon_data['hp']}")
print(f"AC: {dragon_data['ac']}")
print(f"\nActions in JSON ({len(dragon_data['actions'])}):")
for action in dragon_data['actions']:
    print(f"  - {action['name']} ({action['type']})")
    if 'description' in action:
        print(f"    Description: {action['description'][:80]}")

# Test how single simulation controller creates monster
print("\n" + "=" * 80)
print("SINGLE SIMULATION CONTROLLER")
print("=" * 80)
sim_controller = SimulationController()
monster_objects = sim_controller._convert_monsters_to_objects([dragon_data])
dragon = monster_objects[0]

print(f"\nMonster created: {dragon.name}")
print(f"Number of actions: {len(dragon.actions)}")
print(f"Actions:")
for action in dragon.actions:
    print(f"  - {action.name} ({action.action_type})")
    print(f"    Has description: {hasattr(action, 'description')}")
    print(f"    Has area_effect: {hasattr(action, 'area_effect')}")
    print(f"    Has save_dc: {hasattr(action, 'save_dc')}")
    print(f"    Has damage_dice: {hasattr(action, 'damage_dice')}")

# Test how batch simulation controller creates monster
print("\n" + "=" * 80)
print("BATCH SIMULATION CONTROLLER")
print("=" * 80)

batch_controller = BatchSimulationController()
actions_from_batch = batch_controller._build_actions_from_dicts(dragon_data.get('actions', []))

from models.monster import Monster

monster = Monster(
    name=dragon_data.get('name', 'Unknown'),
    challenge_rating=dragon_data.get('cr', '1/4'),
    hp=dragon_data.get('hp', 10),
    ac=dragon_data.get('ac', 10),
    ability_scores=dragon_data.get('ability_scores', {'str': 10, 'dex': 10, 'con': 10, 'int': 10, 'wis': 10, 'cha': 10}),
    actions=actions_from_batch
)

print(f"\nMonster created: {monster.name}")
print(f"Number of actions: {len(monster.actions)}")
print(f"Actions:")
for action in monster.actions:
    action_type = getattr(action, 'action_type', 'unknown')
    print(f"  - {action.name} ({action_type})")
    print(f"    Has description: {hasattr(action, 'description')}")
    print(f"    Has area_effect: {hasattr(action, 'area_effect')}")
    print(f"    Has save_dc: {hasattr(action, 'save_dc')}")
    print(f"    Has damage_dice: {hasattr(action, 'damage_dice')}")
    if hasattr(action, 'area_effect'):
        print(f"    area_effect value: {action.area_effect}")
        if action.area_effect:
            print(f"    save_dc value: {getattr(action, 'save_dc', 'N/A')}")
            print(f"    save_type value: {getattr(action, 'save_type', 'N/A')}")
            print(f"    damage_dice value: {getattr(action, 'damage_dice', 'N/A')}")

if len(monster.actions) == 5 and any(a.name == 'Fire Breath' for a in monster.actions):
    print("\n✅ SUCCESS: Batch controller now properly loads all actions from JSON!")
