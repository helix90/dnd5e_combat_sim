"""Test the complete healing spell flow with real character data."""

from models.character import Character
from models.spell_manager import SpellManager
from models.spells import SpellAction
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

print("=" * 60)
print("TESTING FULL HEALING SPELL FLOW")
print("=" * 60)

# Create Branwen character (simulating what simulation_controller does)
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

print(f"\n1. Character Created: {branwen.name}")
print(f"   Class: {branwen.character_class}")
print(f"   Level: {branwen.level}")
print(f"   HP: {branwen.hp}/{branwen.max_hp}")
print(f"   Spell slots (from JSON): {branwen_data.get('spell_slots', {})}")
print(f"   Spell slots type: {type(list(branwen.spell_slots.keys())[0]) if branwen.spell_slots else 'N/A'}")
print(f"   Spell slots remaining: {branwen.spell_slots_remaining}")
print(f"   Spell slots remaining type: {type(list(branwen.spell_slots_remaining.keys())[0]) if branwen.spell_slots_remaining else 'N/A'}")

# Add spells to character (simulating what simulation_controller does)
print(f"\n2. Adding spells from spell_list: {branwen_data.get('spell_list', [])}")
for spell_name in branwen_data.get('spell_list', []):
    spell = spell_manager.get_spell(spell_name)
    if spell:
        branwen.add_spell(spell)
        print(f"   Added: {spell.name} (level {spell.level}, healing={spell.healing})")

print(f"\n3. Character now has {len(branwen.spells)} spells loaded")
print(f"   Spell names: {list(branwen.spells.keys())}")

# Check healing spells
healing_spells = [
    s for s in branwen.spells.values()
    if hasattr(s, 'healing') and s.healing
]
print(f"\n4. Found {len(healing_spells)} healing spells:")
for spell in healing_spells:
    print(f"   - {spell.name} (level {spell.level})")

if healing_spells:
    cure_wounds = healing_spells[0]
    print(f"\n5. Testing spell slot availability for {cure_wounds.name}")
    print(f"   Spell level: {cure_wounds.level}")

    spell_action = SpellAction(cure_wounds)

    # Check availability
    available = spell_action.check_spell_slot_availability(branwen)
    print(f"   Slot available: {available}")

    # Show the internal logic
    required_level = cure_wounds.level
    slots = branwen.spell_slots_remaining
    print(f"\n6. Debugging spell slot check:")
    print(f"   Required level: {required_level} (type: {type(required_level)})")
    print(f"   Slots dict: {slots}")
    print(f"   slots.get({required_level}, 0) = {slots.get(required_level, 0)}")
    print(f"   slots.get('{required_level}', 0) = {slots.get(str(required_level), 0)}")
    print(f"   Combined (with 'or'): {slots.get(required_level, 0) or slots.get(str(required_level), 0)}")

    # Try to consume a slot
    print(f"\n7. Attempting to consume spell slot...")
    consumed = spell_action.consume_spell_slot(branwen)
    print(f"   Slot consumed: {consumed}")
    print(f"   Remaining slots: {branwen.spell_slots_remaining}")

    # Try again
    print(f"\n8. Checking availability after consumption...")
    available2 = spell_action.check_spell_slot_availability(branwen)
    print(f"   Still available: {available2}")
    print(f"   Remaining slots: {branwen.spell_slots_remaining}")

else:
    print("\n   ERROR: No healing spells found!")

print("\n" + "=" * 60)
print("TEST COMPLETE")
print("=" * 60)
