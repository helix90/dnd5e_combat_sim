"""
Weapon properties for D&D 5e Combat Simulator.

Character data lists weapons by name; these tables decide which ability a weapon
attack uses ('melee' = STR, 'ranged' = DEX, 'finesse' = the higher of the two).
"""

FINESSE_WEAPONS = {'Dagger', 'Rapier', 'Scimitar', 'Shortsword', 'Whip', 'Dart'}
RANGED_WEAPONS = {'Shortbow', 'Longbow', 'Light Crossbow', 'Hand Crossbow', 'Heavy Crossbow', 'Sling', 'Blowgun'}

# Two-handed weapons, and weapons the party throws as well as swings (Dueling is for one-handed melee attacks)
TWO_HANDED_WEAPONS = {'Greataxe', 'Greatsword', 'Maul', 'Glaive', 'Halberd', 'Pike', 'Greatclub', 'Longbow',
                      'Heavy Crossbow', 'Light Crossbow', 'Shortbow'}
THROWN_WEAPONS = {'Javelin', 'Handaxe', 'Dagger', 'Light Hammer', 'Spear', 'Dart', 'Trident'}

# Martial Arts lets monks use DEX with unarmed strikes and simple melee weapons
MONK_WEAPONS = {'Unarmed Strike', 'Quarterstaff', 'Shortsword', 'Spear', 'Club', 'Dagger',
                'Handaxe', 'Javelin', 'Mace', 'Sickle', 'Light Hammer'}


def weapon_type_for(weapon_name: str, character_class: str = '') -> str:
    """Return 'ranged', 'finesse' or 'melee' for a weapon wielded by a character of the given class."""
    if weapon_name in RANGED_WEAPONS:
        return 'ranged'
    if weapon_name in FINESSE_WEAPONS or (character_class == 'Monk' and weapon_name in MONK_WEAPONS):
        return 'finesse'
    return 'melee'
