#!/usr/bin/env python3

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from models.combat import Combat
from models.character import Character
from models.monster import Monster

def test_combat_ends_when_monsters_defeated():
    """Test that combat ends when all monsters are defeated."""
    
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
        hp=7,  # Low HP so it dies quickly
        ac=13,
        ability_scores={'str': 8, 'dex': 14, 'con': 10, 'int': 10, 'wis': 8, 'cha': 8}
    )
    
    # Create combat
    combat = Combat([hero, goblin])
    
    # Run combat
    result = combat.run()
    
    print(f"Combat result: {result}")
    print(f"Winner: {result['winner']}")
    print(f"Rounds: {result['rounds']}")
    print(f"Party HP remaining: {result['party_hp_remaining']}")
    
    # Verify combat ended in reasonable number of rounds
    assert result['rounds'] < 10, f"Combat took too many rounds: {result['rounds']}"
    assert result['winner'] in ['party', 'monsters'], f"Invalid winner: {result['winner']}"
    
    print("✅ Test passed: Combat ended in reasonable number of rounds")

if __name__ == "__main__":
    test_combat_ends_when_monsters_defeated() 