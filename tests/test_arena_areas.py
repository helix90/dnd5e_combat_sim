"""Arena phase 4: area shapes and aiming, and breath weapon recharge."""

import json
import random
from unittest.mock import patch

import pytest

from ai.aiming import aim_area
from ai.positioning import fit_plan
from ai.strategy import MonsterAIStrategy
from models.actions import AttackAction
from models.arena import (
    COVER_HALF,
    COVER_TOTAL,
    Area,
    Arena,
    Placement,
    Terrain,
    describe_area,
)
from models.character import Character
from models.combat import Combat
from models.db import DatabaseManager
from models.monster import Monster
from models.monster_builder import build_monsters
from models.spell_manager import SpellManager
from models.spells import SpellAction
from utils.paths import data_path

SCORES = {"str": 10, "dex": 10, "con": 10, "int": 10, "wis": 10, "cha": 10}
WIZARD_SCORES = dict(SCORES, int=18)
WALL = Terrain(impassable=True, cover=COVER_TOTAL)
LOW_WALL = Terrain(difficult=True, cover=COVER_HALF)
FIREBALL = SpellManager().get_spell("Fireball")


def wizard(name="Wizard"):
    w = Character(
        name, 5, "Wizard", "Human", WIZARD_SCORES, hp=30, ac=12, proficiency_bonus=3
    )
    w.spells = {"Fireball": FIREBALL}
    w.spell_slots_remaining = {1: 4, 2: 3, 3: 2}
    return w


def fighter(name="Fighter", hp=40):
    return Character(
        name,
        5,
        "Fighter",
        "Human",
        SCORES,
        hp=hp,
        ac=16,
        proficiency_bonus=3,
        actions=[
            AttackAction("Longsword", "", "Longsword", "1d8+3", "slashing", hit_bonus=6)
        ],
    )


def goblin(name, hp=30):
    return Monster(
        name,
        "1/4",
        hp,
        13,
        SCORES,
        actions=[
            AttackAction("Scimitar", "", "Scimitar", "1d6+2", "slashing", hit_bonus=4)
        ],
    )


def breath(recharge=5):
    return AttackAction(
        "Fire Breath",
        "",
        "Fire Breath",
        "16d6",
        "fire",
        area_effect=True,
        save_type="dex",
        save_dc=17,
        area={"shape": "cone", "size": 30},
        recharge=recharge,
    )


def dragon(name="Dragon"):
    return Monster(
        name,
        "6",
        300,
        18,
        SCORES,
        size="large",
        actions=[
            AttackAction("Claw", "", "Claw", "1d4", "slashing", hit_bonus=0),
            breath(),
        ],
    )


def fight(creatures, terrain=None, width=30, height=20):
    return Combat(creatures, arena=Arena(width, height, terrain or {}, name="Test"))


def put(combat, creature, x, y):
    size = combat.battlefield.placements[creature].size
    combat.battlefield.placements[creature] = Placement((x, y), size)


# Geometry


def test_area_shapes():
    arena = Arena(30, 30)
    sphere = arena.area_squares(Area("sphere", 20), (10, 10))
    assert (
        len(sphere) == 64
        and (6, 6) in sphere
        and (13, 13) in sphere
        and (14, 10) not in sphere
    )
    assert arena.area_squares(Area("cube", 20), (3, 4)) == {
        (x, y) for x in range(3, 7) for y in range(4, 8)
    }
    cone = arena.area_squares(Area("cone", 30), (5, 5.5), (10, 5.5))
    # As wide as it is far: at 27.5 ft, 13.75 ft either side of the middle
    assert (
        (5, 5) in cone and (10, 5) in cone and (10, 7) in cone and (10, 8) not in cone
    )
    assert (11, 5) not in cone and (4, 5) not in cone
    line = arena.area_squares(Area("line", 30), (5, 5.5), (10, 5.5))
    assert line == {(x, 5) for x in range(5, 11)}
    # Areas stop at the map's edge
    assert arena.area_squares(Area("sphere", 20), (0, 0)) == {
        (x, y) for x in range(4) for y in range(4)
    }


def test_area_data_validation_and_text():
    assert Area.from_dict({"shape": "cone", "size": 30}) == Area("cone", 30)
    assert Area.from_dict(None) is None
    with pytest.raises(ValueError):
        Area("blob", 20)
    with pytest.raises(ValueError):
        AttackAction("Breath", "", "Breath", "1d6", "fire", recharge=7)
    assert describe_area({"shape": "sphere", "size": 20}) == "20-ft-radius sphere"
    assert describe_area({"shape": "cone", "size": 30}) == "30-ft cone"


def test_area_data_loaded_for_fireball_web_and_the_dragon():
    spells = SpellManager()
    assert spells.get_spell("Fireball").area == Area("sphere", 20)
    assert spells.get_spell("Web").area == Area("cube", 20)
    monsters = json.load(open(data_path("monsters.json")))["monsters"]
    young = build_monsters([m for m in monsters if m["name"] == "Young Dragon"])[0]
    fire = next(a for a in young.actions if a.name == "Fire Breath")
    assert fire.area == Area("cone", 30) and fire.recharge == 5 and fire.ready


def test_cover_from_a_point_and_edge_points():
    arena = Arena(
        20,
        20,
        {(5, y): WALL for y in range(20)} | {(12, y): LOW_WALL for y in range(20)},
    )
    assert arena.cover_from_point((2, 5), Placement((8, 5))) == COVER_TOTAL
    assert arena.cover_from_point((10, 5), Placement((14, 5))) == COVER_HALF
    assert arena.cover_from_point((10, 5), Placement((8, 5))) == "none"
    assert len(Arena.edge_points(Placement((0, 0), 2))) == 8
    assert arena.distance_to_point(Placement((0, 0), 2), (6, 1)) == 20


# Who an area catches


def test_area_hits_allies_skips_total_cover_and_never_the_cone_user():
    w, f, g1, g2 = wizard(), fighter(), goblin("Goblin 1"), goblin("Goblin 2")
    combat = fight([w, f, g1, g2], {(10, y): WALL for y in range(20)})
    bf = combat.battlefield
    put(combat, w, 0, 0)
    put(combat, f, 7, 5)
    put(combat, g1, 8, 5)
    put(combat, g2, 11, 5)  # inside the sphere, but behind the wall
    hit = [c for c, _ in bf.area_hits(w, Area("sphere", 20), (8, 6))]
    assert hit == [f, g1] or set(hit) == {f, g1}
    d = dragon()
    combat = fight([d, f])
    put(combat, d, 5, 5)
    put(combat, f, 8, 5)
    hit = combat.battlefield.area_hits(d, Area("cone", 30), (7, 6), (8.5, 5.5))
    assert [c for c, _ in hit] == [f]


def test_can_aim_checks_range_and_cone_origins():
    w, d = wizard(), dragon()
    combat = fight([w, d], width=60)
    bf = combat.battlefield
    put(combat, w, 0, 0)
    put(combat, d, 10, 10)
    assert bf.can_aim(w, Area("sphere", 20), 150, (30, 1)) and not bf.can_aim(
        w, Area("sphere", 20), 150, (32, 1)
    )
    assert bf.can_aim(d, Area("cone", 30), 0, (12, 11)) and not bf.can_aim(
        d, Area("cone", 30), 0, (14, 11)
    )


# Aiming


def test_fireball_is_aimed_at_the_group_and_away_from_allies():
    w, f = wizard(), fighter()
    goblins = [goblin(f"Goblin {i}") for i in range(4)]
    combat = fight([w, f] + goblins)
    put(combat, w, 2, 10)
    put(combat, f, 14, 10)  # fighting a lone goblin on its far side
    put(combat, goblins[0], 13, 10)
    for g, (x, y) in zip(goblins[1:], [(20, 3), (21, 3), (20, 4)]):
        put(combat, g, x, y)  # a group well away from the fighter
    plan = fit_plan(
        w,
        {"type": "cast_spell", "spell": SpellAction(FIREBALL), "target": goblins},
        combat._build_combat_state(w),
    )
    assert set(plan["target"]) == set(goblins[1:]) and "aim" in plan
    result = combat._execute_action(w, plan)
    assert result["area"] == {"shape": "sphere", "size": 20}
    assert {r["target"] for r in result["target_results"]} == {
        "Goblin 1",
        "Goblin 2",
        "Goblin 3",
    }
    assert goblins[0].hp == 30 and f.hp == 40


def test_breath_is_pointed_at_the_most_enemies_moving_if_needed():
    d = dragon()
    party = [fighter(f"Hero {i}") for i in range(4)]
    combat = fight([d] + party)
    put(combat, d, 2, 2)
    for hero, (x, y) in zip(party, [(14, 9), (15, 10), (14, 11), (25, 2)]):
        put(combat, hero, x, y)
    plan = fit_plan(
        d,
        {"type": "attack", "action": d.actions[1], "target": party},
        combat._build_combat_state(d),
    )
    assert set(plan["target"]) == set(party[:3]) and "move_to" in plan


def test_area_worth_less_than_an_attack_falls_back_and_keeps_the_breath():
    d = dragon()
    d.actions[0] = AttackAction("Bite", "", "Bite", "10d10", "piercing", hit_bonus=10)
    hero = fighter(hp=5)  # the breath can only do 5 damage to it
    combat = fight([d, hero])
    put(combat, d, 5, 5)
    put(combat, hero, 7, 5)
    plan = fit_plan(
        d,
        {"type": "attack", "action": d.actions[1], "target": [hero]},
        combat._build_combat_state(d),
    )
    assert plan["action"].name == "Bite"
    assert d.actions[1].ready


def test_no_aim_when_nothing_can_be_caught():
    d, hero = dragon(), fighter()
    combat = fight([d, hero], width=40)
    put(combat, d, 0, 0)
    put(combat, hero, 35, 15)
    assert (
        aim_area(
            combat.battlefield, d, d.actions[1], combat.battlefield.reachable(d, 40)
        )
        is None
    )


# Combat


def test_area_save_gets_cover_from_the_origin():
    w, g = wizard(), goblin("Goblin", hp=500)
    combat = fight([w, g], {(12, y): LOW_WALL for y in range(20)})
    put(combat, w, 0, 5)
    put(combat, g, 13, 5)
    with patch("random.randint", return_value=10):
        result = combat._execute_action(
            w,
            {
                "type": "cast_spell",
                "spell": SpellAction(FIREBALL),
                "target": [g],
                "aim": {"origin": [10, 6]},
            },
        )
    assert result["target_results"][0]["cover_bonus"] == 2
    assert result["cover_by_target"] == {"Goblin": COVER_HALF}


def test_no_slot_spent_when_the_area_catches_no_one():
    w, g = wizard(), goblin("Goblin")
    combat = fight([w, g])
    put(combat, w, 0, 0)
    put(combat, g, 20, 10)
    result = combat._execute_action(
        w,
        {
            "type": "cast_spell",
            "spell": SpellAction(FIREBALL),
            "target": [g],
            "aim": {"origin": [5, 5]},
        },
    )
    assert result["reason"] == "no one in the area" and w.spell_slots_remaining[3] == 2
    combat.logger.log_action(w, result, 1)
    assert (
        combat.format_log_for_web()[-1]
        == "Wizard holds back Fireball (no one in the area)."
    )


def test_an_area_catching_one_creature_still_calls_for_a_save():
    d, hero = dragon(), fighter(hp=500)
    result = d.actions[1].execute(d, [hero])
    assert "save_dc" in result and "attack_roll" not in result


def test_breath_recharges_on_a_5_or_6():
    d, hero = dragon(), fighter(hp=1000)
    combat = Combat([d, hero])
    fire = d.actions[1]
    combat._execute_action(d, {"type": "attack", "action": fire, "target": [hero]})
    assert not fire.ready
    blocked = combat._execute_action(
        d, {"type": "attack", "action": fire, "target": [hero]}
    )
    assert blocked["reason"] == "not recharged"
    with patch("random.randint", return_value=4):
        assert combat._roll_recharges(d) == [] and not fire.ready
    with patch("random.randint", return_value=5):
        assert combat._roll_recharges(d) == ["Fire Breath"] and fire.ready


def test_monster_ai_breathes_when_ready_and_attacks_otherwise():
    d, hero = dragon(), fighter()
    ai = MonsterAIStrategy()
    state = {"enemies": [hero], "allies": [], "round": 1}
    plan = ai.choose_action(d, state)
    assert plan["action"].name == "Fire Breath" and plan["target"] == [hero]
    d.actions[1].ready = False
    assert ai.choose_action(d, state)["action"].name == "Claw"


def test_without_an_arena_the_breath_hits_every_enemy():
    d = dragon()
    party = [fighter(f"Hero {i}", hp=1000) for i in range(3)]
    combat = Combat([d] + party)
    result = combat._execute_action(
        d,
        ai_plan := MonsterAIStrategy().choose_action(
            d, {"enemies": party, "allies": [], "round": 1}
        ),
    )
    assert (
        ai_plan["action"].name == "Fire Breath" and len(result["target_results"]) == 3
    )


def test_dragon_fight_log_and_storage():
    random.seed(3)
    d = dragon()
    party = [fighter(f"Hero {i}") for i in range(3)]
    combat = fight([d] + party)
    combat.run()
    lines = combat.format_log_for_web()
    assert any(
        "uses Fire Breath on" in line and "(30-ft cone)" in line for line in lines
    )
    result = next(
        e["result"]
        for e in combat.logger.log
        if e["type"] == "action"
        and e["result"].get("action") == "Fire Breath"
        and e["result"].get("aim")
    )
    text = DatabaseManager._with_position_notes("Fire Breath on Hero 0", result)
    assert "(30-ft cone)" in text
