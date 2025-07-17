#!/usr/bin/env python3

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from models.combat import Combat
from models.character import Character
from models.monster import Monster

def debug_combat():
    """Debug combat logic step by step."""
    
    # Create a simple party and monster
    hero = Character(
        name="Hero",
        level=3,
        character_class="Fighter",
        race="Human",
        ability_scores={'str': 16, 'dex': 14, 'con': 12, 'int': 10, 'wis': 10, 'cha': 10},
        hp=20,
        ac=16,
        proficiency_bonus=2
    )
    
    goblin = Monster(
        name="Goblin",
        challenge_rating="1/4",
        hp=7,
        ac=13,
        ability_scores={'str': 8, 'dex': 14, 'con': 10, 'int': 10, 'wis': 8, 'cha': 8}
    )
    
    print(f"Initial state:")
    print(f"Hero HP: {hero.hp}, Alive: {hero.is_alive()}")
    print(f"Goblin HP: {goblin.hp}, Alive: {goblin.is_alive()}")
    
    # Create combat
    combat = Combat([hero, goblin])
    combat.roll_initiative()
    
    print(f"\nInitiative order: {[p.name for p in combat.get_initiative_order()]}")
    
    # Test a few turns
    for i in range(10):
        print(f"\n--- Turn {i+1} ---")
        print(f"Current round: {combat.current_round}")
        print(f"Combat over: {combat.is_combat_over()}")
        
        alive_participants = combat._get_alive_participants()
        print(f"Alive participants: {[p.name for p in alive_participants]}")
        
        participant = combat.next_turn()
        if participant is None:
            print("No participant returned - combat should be over")
            break
        
        print(f"Active participant: {participant.name}")
        print(f"Hero HP: {hero.hp}, Alive: {hero.is_alive()}")
        print(f"Goblin HP: {goblin.hp}, Alive: {goblin.is_alive()}")
        # Print debug after each turn
        print(f"[DEBUG] After turn: Hero HP = {hero.hp}, Goblin HP = {goblin.hp}")
        
        if combat.is_combat_over():
            print("Combat ended!")
            break

def batch_kobold_vs_party(n=100):
    from models.character import Character
    from models.monster import Monster
    from models.combat import Combat
    import random
    party_template = [
        Character(
            name="Borin",
            level=1,
            character_class="Fighter",
            race="Dwarf",
            ability_scores={"str": 16, "dex": 14, "con": 14, "int": 10, "wis": 10, "cha": 10},
            hp=12,
            ac=17,
            proficiency_bonus=2
        ),
        Character(
            name="Lia",
            level=1,
            character_class="Cleric",
            race="Human",
            ability_scores={"str": 14, "dex": 10, "con": 16, "int": 10, "wis": 16, "cha": 8},
            hp=10,
            ac=18,
            proficiency_bonus=2
        ),
        Character(
            name="Tess",
            level=1,
            character_class="Rogue",
            race="Halfling",
            ability_scores={"str": 10, "dex": 16, "con": 14, "int": 12, "wis": 10, "cha": 14},
            hp=10,
            ac=15,
            proficiency_bonus=2
        )
    ]
    kobold_template = lambda i: Monster(
        name=f"Kobold {i+1}",
        challenge_rating="1/8",
        hp=5,
        ac=12,
        ability_scores={"str": 7, "dex": 15, "con": 9, "int": 8, "wis": 7, "cha": 8},
        actions=None
    )
    party_wins = 0
    kobold_wins = 0
    draws = 0
    for trial in range(n):
        # Deep copy party and kobolds for each run
        import copy
        party = [copy.deepcopy(c) for c in party_template]
        kobolds = [kobold_template(i) for i in range(8)]
        combat = Combat(party + kobolds)
        result = combat.run()
        if result['winner'] == 'party':
            party_wins += 1
        elif result['winner'] == 'monsters':
            kobold_wins += 1
        else:
            draws += 1
    print(f"Batch results for 100 runs (3 L1 party vs 8 kobolds):")
    print(f"Party wins: {party_wins}")
    print(f"Kobold wins: {kobold_wins}")
    print(f"Draws: {draws}")

if __name__ == "__main__":
    debug_combat()
    batch_kobold_vs_party(100) 