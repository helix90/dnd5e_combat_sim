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

if __name__ == "__main__":
    debug_combat() 