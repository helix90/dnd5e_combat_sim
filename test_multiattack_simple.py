"""
Simplified test script to verify multiattack implementation works correctly.
"""
from models.character import Character
from models.monster import Monster
from models.combat import Combat
from models.actions import AttackAction, Action

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

# Create Young Dragon manually with all actions
bite_attack = AttackAction(
    name="Bite",
    description="Melee Weapon Attack",
    weapon_name="Bite",
    damage_dice="2d10+4",
    damage_type="piercing",
    hit_bonus=7
)

claw_attack = AttackAction(
    name="Claw",
    description="Melee Weapon Attack",
    weapon_name="Claw",
    damage_dice="2d6+4",
    damage_type="slashing",
    hit_bonus=7
)

tail_attack = AttackAction(
    name="Tail",
    description="Melee Weapon Attack",
    weapon_name="Tail",
    damage_dice="2d8+4",
    damage_type="bludgeoning",
    hit_bonus=7
)

# Create multiattack action
multiattack = Action(
    action_type="special",
    name="Multiattack",
    description="The dragon makes three attacks: one with its bite and two with its claws."
)

# Create Young Dragon
young_dragon = Monster(
    name="Young Dragon",
    challenge_rating="10",
    hp=178,
    ac=18,
    ability_scores={'str': 23, 'dex': 10, 'con': 21, 'int': 14, 'wis': 11, 'cha': 19},
    actions=[multiattack, bite_attack, claw_attack, tail_attack]
)

print("=" * 80)
print("YOUNG DRAGON DATA")
print("=" * 80)
print(f"Name: {young_dragon.name}")
print(f"HP: {young_dragon.hp}")
print(f"AC: {young_dragon.ac}")
print("\nActions:")
for action in young_dragon.actions:
    print(f"  - {action.name} ({action.action_type})")
    print(f"    Description: {action.description[:80]}...")
print()

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
        result_data = entry['result']
        if result_data.get('action') == 'Multiattack':
            multiattack_count += 1
            total_damage = result_data.get('total_damage', 0)
            multiattack_damage += total_damage
            individual_attacks = result_data.get('individual_attacks', [])
            attacks_performed = result_data.get('attacks_performed', [])

            print(f"\nRound {entry['round']}: {entry['actor']} uses Multiattack")
            print(f"  Target: {result_data.get('target')}")
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
