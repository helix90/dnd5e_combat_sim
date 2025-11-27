"""Debug script to test healing spell selection in combat."""

from models.character import Character
from models.spell_manager import SpellManager
from ai.strategy import PartyAIStrategy
import json

# Load spell manager
spell_manager = SpellManager()

# Load level 5 character data
with open('data/characters.json', 'r') as f:
    char_data = json.load(f)

# Find Branwen level 5
branwen_data = None
for level_obj in char_data:
    if level_obj.get('level') == 5:
        for char in level_obj.get('party', []):
            if char['name'] == 'Branwen':
                branwen_data = char
                break
    if branwen_data:
        break

# Create Branwen character
branwen = Character(
    name=branwen_data['name'],
    level=5,
    character_class=branwen_data.get('character_class', 'Cleric'),
    race=branwen_data.get('race', 'Dwarf'),
    ability_scores=branwen_data.get('ability_scores', {}),
    hp=branwen_data.get('hp', 40),
    ac=branwen_data.get('ac', 18),
    proficiency_bonus=branwen_data.get('proficiency_bonus', 3),
    spell_slots=branwen_data.get('spell_slots', {}),
    spell_list=branwen_data.get('spell_list', [])
)

print(f"Character: {branwen.name}")
print(f"HP: {branwen.hp}/{branwen.max_hp}")
print(f"Spell slots: {branwen.spell_slots}")
print(f"Spell slots remaining: {branwen.spell_slots_remaining}")
print(f"Spell list: {branwen.spell_list}")
print()

# Add spells to character
print("Adding spells to character...")
spell_manager.add_spells_to_character(branwen, branwen_data.get('spell_list', []))
print(f"Spells in character.spells dict: {list(branwen.spells.keys())}")
print()

# Check healing spells
print("Checking for healing spells...")
healing_spells = [
    s for s in getattr(branwen, 'spells', {}).values()
    if hasattr(s, 'healing') and s.healing
]
print(f"Found {len(healing_spells)} healing spells:")
for spell in healing_spells:
    print(f"  - {spell.name} (level {spell.level})")
print()

# Create a mock injured ally
injured_ally = Character(
    name="InjuredAlly",
    level=5,
    character_class="Fighter",
    race="Human",
    ability_scores={'str': 16, 'dex': 14, 'con': 14, 'int': 10, 'wis': 10, 'cha': 10},
    hp=5,  # Low HP!
    ac=16,
    proficiency_bonus=3
)
injured_ally.max_hp = 50  # Very low HP percentage

print(f"Injured ally: {injured_ally.name}")
print(f"HP: {injured_ally.hp}/{injured_ally.max_hp} ({injured_ally.hp/injured_ally.max_hp:.1%})")
print()

# Test AI strategy
print("Testing AI strategy...")
ai = PartyAIStrategy()

# Create combat state with injured ally
combat_state = {
    'allies': [branwen, injured_ally],
    'enemies': [],  # No enemies to focus on attacks
    'round': 1
}

print(f"Combat state:")
print(f"  Allies: {[a.name for a in combat_state['allies']]}")
print(f"  Low HP allies: {[a.name for a in combat_state['allies'] if (a.hp / a.max_hp) < 0.25]}")
print()

# Try _try_heal_ally directly
print("Testing _try_heal_ally method...")
result = ai._try_heal_ally(branwen, [injured_ally], is_critical=True)
print(f"Result: {result}")
print()

# Try choose_action
print("Testing choose_action method...")
action = ai.choose_action(branwen, combat_state)
print(f"Action chosen: {action}")
