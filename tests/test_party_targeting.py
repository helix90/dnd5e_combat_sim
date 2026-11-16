"""The party focuses its fire (the enemy dealing the most damage per hit point it has left), and casts
Hypnotic Pattern, Web or Entangle on the dangerous few as well as on crowds."""

import copy
import json

from ai.strategy import PartyAIStrategy, damage_per_round
from models.character_builder import build_party
from models.monster_builder import build_monster
from models.spell_manager import SpellManager
from utils.party_loader import PartyLoader
from tests.test_spell_effects import caster
from utils.paths import data_path

MONSTERS = {
    m["name"]: m for m in json.load(open(data_path("monsters.json")))["monsters"]
}


def monster(name, number=None, hp=None):
    creature = build_monster(copy.deepcopy(MONSTERS[name]))
    if number:
        creature.name = f"{name} {number}"
    if hp is not None:
        creature.hp = hp
    return creature


def stealth_specialist(name):
    """A member of the Stealth Specialists at 5th level (Kara the bard, Vex the ranger...)."""
    party = build_party(
        copy.deepcopy(PartyLoader.get_party_with_level(4, 5)["characters"]),
        SpellManager(),
    )
    return next(c for c in party if c.name == name), party


def plan_for(hero, party, enemies):
    return PartyAIStrategy().choose_action(
        hero, {"allies": party, "enemies": enemies, "round": 1}
    )


def test_damage_per_round_counts_the_multiattack_and_extra_damage():
    # Claws 2d4+3, and a bite of 1d6+3 plus 2d6 necrotic
    assert damage_per_round(monster("Vampire Spawn")) == 8 + 6.5 + 7
    # No Multiattack: its best attack, the 2d6+2 bite
    assert damage_per_round(monster("Ghoul")) == 9
    assert damage_per_round(object()) == 1


def test_the_party_hits_what_hurts_most_for_its_hit_points():
    vex, party = stealth_specialist("Vex")
    ogre, orc = monster("Ogre"), monster("Orc")
    # The orc's greataxe (9.5 a round) for 15 hit points beats the ogre's greatclub (13) for 59
    assert plan_for(vex, party, [ogre, orc])["target"] is orc
    ogre.hp = 10
    assert plan_for(vex, party, [ogre, orc])["target"] is ogre


def test_the_party_finishes_a_wounded_regenerator_instead_of_spreading_damage():
    vex, party = stealth_specialist("Vex")
    fresh, wounded = monster("Vampire Spawn", 1), monster("Vampire Spawn", 2, hp=50)
    ghouls = [monster("Ghoul", i) for i in range(1, 4)]
    assert plan_for(vex, party, [fresh, wounded] + ghouls)["target"] is wounded
    ranked = PartyAIStrategy().evaluate_targets(
        vex, [fresh, wounded] + ghouls, {"allies": party, "enemies": [], "round": 1}
    )
    assert ranked[0] is wounded and ranked[-1] is fresh


def test_hypnotic_pattern_on_two_vampire_spawn_among_charm_immune_ghouls():
    kara, party = stealth_specialist("Kara")
    spawn = [monster("Vampire Spawn", i) for i in (1, 2)]
    ghouls = [monster("Ghoul", i) for i in range(1, 4)]
    # Barely one spawn expected to fail, but that's a third of the pack's damage
    plan = plan_for(kara, party, ghouls + spawn)
    assert plan["spell"].spell.name == "Hypnotic Pattern"
    assert plan["target"][:2] == spawn  # the most dangerous first


def test_no_hypnotic_pattern_on_a_lone_enemy_or_charm_immune_ones():
    kara, party = stealth_specialist("Kara")
    lone = plan_for(kara, party, [monster("Vampire Spawn")])
    ghouls = plan_for(kara, party, [monster("Ghoul", i) for i in range(1, 4)])
    for plan in (lone, ghouls):
        spell = plan.get("spell")
        assert spell is None or spell.spell.name != "Hypnotic Pattern"


def test_web_catches_the_most_dangerous_enemies_first():
    webber = caster(cls="Wizard", spells=["Web", "Fire Bolt"], slots={2: 2})
    goblins = [monster("Goblin", i) for i in range(1, 4)]
    ogres = [monster("Ogre", i) for i in (1, 2)]
    plan = plan_for(webber, [webber], goblins + ogres)
    assert plan["spell"].spell.name == "Web"
    assert plan["target"][:2] == ogres and len(plan["target"]) == 4
