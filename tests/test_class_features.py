"""Class features: Rage, Reckless Attack, Divine Smite, Action Surge, Second Wind, Martial Arts,
Flurry of Blows, Stunning Strike, Turn Undead, Lay on Hands and the passive ones."""

from unittest.mock import patch

import pytest

from ai.strategy import PartyAIStrategy
from models import class_features as rules
from models.actions import AttackAction
from models.arena import Arena, Placement
from models.buffs import is_stunned, is_turned
from models.character import Character
from models.character_builder import build_character
from models.combat import Combat
from models.damage import damage_after_save
from models.monster import Monster
from models.rolls import roll_saving_throw
from models.spell_manager import SpellManager
from utils.party_loader import PartyLoader

SCORES = {"str": 16, "dex": 16, "con": 14, "int": 10, "wis": 14, "cha": 14}


def weapon(name="Greataxe", dice="1d12", kind="melee", reach=5, range_=None):
    return AttackAction(
        name,
        "",
        name,
        dice,
        "slashing" if kind != "ranged" else "piercing",
        weapon_type=kind,
        reach=reach if kind != "ranged" else None,
        range=range_,
    )


def pc(
    name="Hero", cls="Barbarian", level=5, features=(), actions=None, hp=50, slots=None
):
    return Character(
        name,
        level,
        cls,
        "Human",
        SCORES,
        hp=hp,
        ac=15,
        proficiency_bonus=3,
        class_features=list(features),
        actions=actions or [weapon()],
        spell_slots=slots or {},
    )


def foe(name="Orc", hp=60, ac=10, kind=None, cr="1/2", **kwargs):
    return Monster(
        name,
        cr,
        hp,
        ac,
        {"str": 10, "dex": 10, "con": 10, "int": 10, "wis": 10, "cha": 10},
        actions=[weapon("Claw", "1d6")],
        creature_type=kind,
        **kwargs,
    )


def rolls(d20, other):
    """random.randint: d20 for d20s, other for every other die."""
    return lambda a, b: d20 if b == 20 else other


def attack_plan(action, target):
    return {"type": "attack", "action": action, "target": target}


def put(combat, creature, x, y):
    combat.battlefield.placements[creature] = Placement(
        (x, y), combat.battlefield.placements[creature].size
    )


# Uses


@pytest.mark.parametrize(
    "features, level, expected",
    [
        (["Rage (3)"], 5, {"rage": 3}),
        (["Ki (5 points)", "Martial Arts (1d6)"], 5, {"ki": 5}),
        (["Ki (4)"], 4, {"ki": 4}),
        (["Lay on Hands"], 3, {"lay_on_hands": 15}),
        (["Lay on Hands (25)"], 5, {"lay_on_hands": 25}),
        (["Action Surge", "Second Wind"], 2, {"action_surge": 1, "second_wind": 1}),
        (["Channel Divinity (0)"], 1, {"channel_divinity": 0}),
        (["Channel Divinity (2)"], 6, {"channel_divinity": 2}),
        (["Divine Sense (4)", "Extra Attack"], 5, {}),
    ],
)
def test_starting_resources(features, level, expected):
    assert pc(level=level, features=features).resources == expected


# Rage and Reckless Attack


def test_rage_adds_damage_and_resistance():
    barbarian = pc(features=["Rage (3)"])
    rules.start_rage(barbarian)
    assert barbarian.resources["rage"] == 2 and rules.is_raging(barbarian)
    with patch("random.randint", side_effect=rolls(15, 6)):
        hit = weapon().execute(barbarian, foe())
        shot = weapon("Shortbow", "1d6", "ranged", range_=(80, 320)).execute(
            barbarian, foe()
        )
    assert hit["damage"] == 6 + 3 + 2  # die, STR, rage
    assert shot["damage"] == 6 + 3  # no rage bonus at range
    with patch("random.randint", side_effect=rolls(15, 6)):
        clawed = weapon("Claw", "2d6").execute(foe(), barbarian)
    assert clawed["damage"] == 6  # 12 slashing halved


def test_barbarian_rages_before_a_melee_attack_and_attacks_recklessly():
    barbarian, orc = pc(features=["Rage (3)", "Reckless Attack", "Extra Attack"]), foe()
    combat = Combat([barbarian, orc])
    with patch("random.randint", side_effect=rolls(12, 4)):
        result = combat._take_turn(barbarian, attack_plan(barbarian.actions[0], orc))
    assert result["features"] == ["Rage", "Reckless Attack"]
    assert all(a["advantage"] for a in result["attacks"])
    assert barbarian.resources["rage"] == 2
    # Attacks against the barbarian have advantage until its next turn
    claw = orc.actions[0]
    with patch("random.randint", side_effect=rolls(12, 4)):
        assert claw.execute(orc, barbarian)["advantage"]
    combat._start_of_turn_effects(barbarian)
    with patch("random.randint", side_effect=rolls(12, 4)):
        assert not claw.execute(orc, barbarian)["advantage"]
    # Already raging: no second rage
    with patch("random.randint", side_effect=rolls(12, 4)):
        combat._take_turn(barbarian, attack_plan(barbarian.actions[0], orc))
    assert barbarian.resources["rage"] == 2


def test_no_rage_for_a_ranged_attack():
    bow = weapon("Shortbow", "1d6", "ranged", range_=(80, 320))
    barbarian, orc = pc(features=["Rage (3)"], actions=[bow]), foe()
    with patch("random.randint", side_effect=rolls(12, 4)):
        result = Combat([barbarian, orc])._take_turn(barbarian, attack_plan(bow, orc))
    assert "features" not in result and barbarian.resources["rage"] == 3


# Fighters


def test_second_wind_below_half_hit_points():
    fighter, orc = pc(cls="Fighter", features=["Second Wind"], hp=40), foe()
    fighter.hp = 15
    with patch("random.randint", side_effect=rolls(2, 6)):
        result = Combat([fighter, orc])._take_turn(
            fighter, attack_plan(fighter.actions[0], orc)
        )
    assert fighter.hp == 15 + 6 + 5 and result["features"] == [
        "Second Wind: regains 11 HP"
    ]
    assert fighter.resources["second_wind"] == 0


def test_action_surge_takes_a_second_attack_action_once():
    fighter, orc = pc(
        cls="Fighter", features=["Action Surge (1)", "Extra Attack"]
    ), foe(hp=200)
    combat = Combat([fighter, orc])
    with patch("random.randint", side_effect=rolls(15, 4)):
        first = combat._take_turn(fighter, attack_plan(fighter.actions[0], orc))
        second = combat._take_turn(fighter, attack_plan(fighter.actions[0], orc))
    assert len(first["attacks"]) == 4 and first["features"] == ["Action Surge"]
    assert len(second["attacks"]) == 2


def test_champion_crits_on_19_and_archery_helps_ranged_attacks():
    champion = pc(
        cls="Fighter",
        level=3,
        features=["Martial Archetype: Champion", "Fighting Style: Archery"],
    )
    assert champion.critical_threshold() == 19 and pc().critical_threshold() == 20
    with patch("random.randint", side_effect=rolls(19, 4)):
        assert weapon().execute(champion, foe())["critical"]
    assert (
        champion.attack_bonus("ranged") == 3 + 3 + 2
        and champion.attack_bonus("melee") == 3 + 3
    )


# Divine Smite


def paladin(**kwargs):
    return pc(
        "Paladin",
        "Paladin",
        features=["Divine Smite", "Extra Attack"],
        actions=[weapon("Longsword", "1d8")],
        slots={1: 2, 2: 1},
        **kwargs,
    )


def test_smite_on_a_critical_hit_doubles_the_dice_and_uses_the_lowest_slot():
    knight, orc = paladin(), foe(hp=200)
    with patch("random.randint", side_effect=rolls(20, 3)):
        result = Combat([knight, orc])._execute_weapon_attacks(
            knight, knight.actions[0], orc, count=1
        )
    assert result["divine_smite"] == {"slot_level": 1, "damage": 4 * 3}
    assert result["damage"] == 2 * 3 + 3 + 12 and knight.spell_slots_remaining[1] == 1


def test_smite_against_undead_adds_a_die_and_otherwise_waits_for_a_kill():
    knight = paladin()
    zombie, ogre, weak = (
        foe("Zombie", kind="undead", hp=200),
        foe("Ogre", hp=200),
        foe("Weak", hp=10),
    )
    combat = Combat([knight, zombie, ogre, weak])
    with patch("random.randint", side_effect=rolls(15, 2)):
        on_undead = combat._execute_weapon_attacks(
            knight, knight.actions[0], zombie, count=1
        )
        on_ogre = combat._execute_weapon_attacks(
            knight, knight.actions[0], ogre, count=1
        )
        on_weak = combat._execute_weapon_attacks(
            knight, knight.actions[0], weak, count=1
        )
    assert on_undead["divine_smite"] == {"slot_level": 1, "damage": 3 * 2}
    assert "divine_smite" not in on_ogre  # 195 HP left: not worth a slot
    assert (
        on_weak["divine_smite"]["slot_level"] == 1
    )  # 5 HP left: 2d8 will likely finish it
    assert knight.spell_slots_remaining == {1: 0, 2: 1}


def test_no_smite_with_a_thrown_weapon():
    javelin = AttackAction(
        "Javelin", "", "Javelin", "1d6", "piercing", reach=5, range=(30, 120)
    )
    knight, zombie = paladin(), foe("Zombie", kind="undead", hp=200)
    knight.actions = [javelin]
    combat = Combat([knight, zombie], arena=Arena(20, 5, name="Test"))
    put(combat, knight, 0, 0)
    put(combat, zombie, 4, 0)
    with patch("random.randint", side_effect=rolls(15, 2)):
        result = combat._execute_weapon_attacks(knight, javelin, zombie, count=1)
    assert result["hit"] and "divine_smite" not in result


# Monks


def monk(level=5, ki=5, extra=()):
    staff = AttackAction(
        "Quarterstaff",
        "",
        "Quarterstaff",
        "1d8",
        "bludgeoning",
        weapon_type="finesse",
        reach=5,
    )
    fist = AttackAction(
        "Unarmed Strike",
        "",
        "Unarmed Strike",
        "1d6",
        "bludgeoning",
        weapon_type="finesse",
        reach=5,
    )
    return pc(
        "Monk",
        "Monk",
        level=level,
        features=["Martial Arts (1d6)", f"Ki ({ki} points)", *extra],
        actions=[staff, fist],
    )


def test_flurry_of_blows_after_the_attack_action():
    fighter, orc = monk(), foe(hp=200)
    with patch("random.randint", side_effect=rolls(15, 3)):
        result = Combat([fighter, orc])._take_turn(
            fighter, attack_plan(fighter.actions[0], orc)
        )
    assert [a["action"] for a in result["attacks"]] == [
        "Quarterstaff",
        "Unarmed Strike",
        "Unarmed Strike",
    ]
    assert (
        result["features"] == ["Flurry of Blows (1 ki)"]
        and fighter.resources["ki"] == 4
    )


def test_one_bonus_strike_without_ki():
    fighter, orc = monk(ki=0), foe(hp=200)
    with patch("random.randint", side_effect=rolls(15, 3)):
        result = Combat([fighter, orc])._take_turn(
            fighter, attack_plan(fighter.actions[0], orc)
        )
    assert len(result["attacks"]) == 2 and result["features"] == [
        "Martial Arts: bonus unarmed strike"
    ]


def test_stunning_strike_stuns_until_the_end_of_the_monks_next_turn():
    fighter, orc = monk(extra=["Stunning Strike"]), foe(hp=200, ac=5)
    combat = Combat([fighter, orc])
    with patch(
        "random.randint", side_effect=rolls(2, 3)
    ):  # 2 + 6 hits AC 5; the orc's save of 2 fails DC 13
        result = combat._execute_weapon_attacks(
            fighter, fighter.actions[0], orc, count=1
        )
    assert (
        result["stunning_strike"]["stunned"]
        and is_stunned(orc)
        and fighter.resources["ki"] == 4
    )
    assert roll_saving_throw(orc, "dex", 5)["auto_fail"]
    combat._end_of_turn_effects(fighter)  # the monk's current turn ends
    assert is_stunned(orc)
    assert combat._stunned_turn(orc)["description"] == "is stunned and loses its turn"
    combat._end_of_turn_effects(orc)
    assert is_stunned(orc)
    combat._end_of_turn_effects(fighter)  # the monk's next turn ends
    assert not is_stunned(orc)


def test_no_stunning_strike_on_a_target_about_to_drop():
    fighter, orc = monk(extra=["Stunning Strike"]), foe(hp=12)
    with patch("random.randint", side_effect=rolls(15, 2)):
        result = Combat([fighter, orc])._execute_weapon_attacks(
            fighter, fighter.actions[0], orc, count=1
        )
    assert "stunning_strike" not in result and fighter.resources["ki"] == 5


def test_ki_empowered_strikes_get_past_resistance_to_nonmagical_weapons():
    party = PartyLoader.get_party_with_level(4, 6)["characters"]
    nyssa = build_character(
        next(c for c in party if c["name"] == "Nyssa"), SpellManager()
    )
    fist = next(a for a in nyssa.actions if a.name == "Unarmed Strike")
    staff = next(a for a in nyssa.actions if a.name == "Quarterstaff")
    assert fist.magical and not staff.magical
    wraith = foe("Wraith", damage_resistances=["bludgeoning", "piercing", "slashing"])
    with patch("random.randint", side_effect=rolls(15, 4)):
        assert fist.execute(nyssa, wraith)["damage"] == 4 + 4
        assert staff.execute(nyssa, wraith)["damage"] == (4 + 4) // 2


# Turn Undead


def cleric(level=5, uses=1, destroy="Destroy Undead (CR 1/2)"):
    return pc(
        "Cleric",
        "Cleric",
        level=level,
        features=[f"Channel Divinity ({uses})", destroy],
        actions=[weapon("Mace", "1d6")],
    )


def test_turn_undead_turns_or_destroys_undead_that_fail():
    priest = cleric()
    ghoul, zombie = foe("Ghoul", kind="undead", cr="1"), foe(
        "Zombie", kind="undead", cr="1/4"
    )
    with patch("random.randint", return_value=2):
        result = rules.turn_undead(priest, [ghoul, zombie])
    assert result["turned"] == ["Ghoul"] and result["destroyed"] == ["Zombie"]
    assert (
        is_turned(ghoul)
        and zombie.hp == 0
        and priest.resources["channel_divinity"] == 0
    )
    assert (
        result["description"]
        == "presents a holy symbol and turns Ghoul and destroys Zombie"
    )


def test_turned_undead_flee_until_damaged():
    priest, ghoul = cleric(), foe("Ghoul", kind="undead", cr="1")
    with patch("random.randint", return_value=2):
        rules.turn_undead(priest, [ghoul])
    combat = Combat([priest, ghoul])
    assert combat._turned_turn(ghoul)["description"] == "is turned and flees"
    with patch("random.randint", side_effect=rolls(15, 3)):
        weapon("Mace", "1d6").execute(priest, ghoul)
    assert not is_turned(ghoul)


def test_turned_undead_dash_away_from_the_cleric_without_opportunity_attacks():
    priest, ghoul = cleric(), foe("Ghoul", kind="undead", cr="1")
    combat = Combat([priest, ghoul], arena=Arena(30, 5, name="Test"))
    put(combat, priest, 10, 2)
    put(combat, ghoul, 11, 2)
    with patch("random.randint", return_value=2):
        rules.turn_undead(priest, [ghoul])
    result = combat._turned_turn(ghoul)
    assert result["movement"]["feet"] == 60 and "provoked" not in result["movement"]
    assert combat.battlefield.distance(priest, ghoul) == 65


def test_ai_turns_two_undead_but_not_a_lone_one():
    ai, priest = PartyAIStrategy(), cleric()
    ghouls = [foe(f"Ghoul {i}", kind="undead", cr="1") for i in range(2)]
    plan = ai.choose_action(priest, {"allies": [priest], "enemies": ghouls, "round": 3})
    assert plan["type"] == "turn_undead" and plan["target"] == ghouls
    plan = ai.choose_action(
        priest, {"allies": [priest], "enemies": ghouls[:1], "round": 3}
    )
    assert plan["type"] != "turn_undead"
    # One undead with an orc beside it is worth turning
    orc = foe()
    plan = ai.choose_action(
        priest, {"allies": [priest], "enemies": [ghouls[0], orc], "round": 3}
    )
    assert plan["type"] == "turn_undead" and plan["target"] == [ghouls[0]]


def test_turn_undead_in_combat_and_the_log():
    priest, ghouls = cleric(), [
        foe(f"Ghoul {i}", kind="undead", cr="1") for i in range(2)
    ]
    combat = Combat([priest, *ghouls])
    with patch("random.randint", return_value=2):
        result = combat._take_turn(priest, {"type": "turn_undead", "target": ghouls})
    combat.logger.log_action(priest, result, 1)
    assert result["turned"] == ["Ghoul 0", "Ghoul 1"]
    assert (
        "Cleric presents a holy symbol and turns Ghoul 0, Ghoul 1."
        in combat.format_log_for_web()
    )


# Lay on Hands


def test_lay_on_hands_heals_from_the_pool():
    knight, friend = paladin(), pc("Friend", hp=40)
    knight.class_features.append("Lay on Hands (25)")
    knight.resources = rules.starting_resources(knight)
    friend.hp = 0
    result = rules.LayOnHandsAction().execute(knight, friend)
    assert (
        result["healing"] == 25
        and friend.hp == 25
        and knight.resources["lay_on_hands"] == 0
    )


def test_paladin_ai_uses_lay_on_hands_first():
    knight, friend = paladin(), pc("Friend", hp=40)
    knight.class_features.append("Lay on Hands (10)")
    knight.resources = rules.starting_resources(knight)
    friend.hp = 4
    plan = PartyAIStrategy().choose_action(
        knight, {"allies": [knight, friend], "enemies": [foe()], "round": 3}
    )
    assert (
        plan["type"] == "cast_spell"
        and plan["spell"].name == "Lay on Hands"
        and plan["target"] is friend
    )
    combat = Combat([knight, friend, foe()])
    result = combat._take_turn(knight, plan)
    combat.logger.log_action(knight, result, 1)
    assert friend.hp == 14
    assert (
        "Paladin uses Lay on Hands on Friend: heals 10 HP."
        in combat.format_log_for_web()
    )


# Rogues and barbarians: reactions and saves


def test_uncanny_dodge_halves_one_hit_a_round():
    rogue, ogre = pc("Rogue", "Rogue", features=["Uncanny Dodge"], hp=50), foe("Ogre")
    combat = Combat([rogue, ogre])
    club = weapon("Club", "2d8")
    with patch("random.randint", side_effect=rolls(15, 5)):
        first = combat._attack(ogre, club, rogue, {})
        second = combat._attack(ogre, club, rogue, {})
    assert first["damage"] == 5 and first["uncanny_dodge"] == 5
    assert second["damage"] == 10 and "uncanny_dodge" not in second
    assert rogue.hp == 50 - 5 - 10
    combat._reacted.discard(rogue)  # its next turn
    with patch("random.randint", side_effect=rolls(15, 5)):
        assert combat._attack(ogre, club, rogue, {})["uncanny_dodge"] == 5


def test_evasion_and_danger_sense():
    rogue = pc("Rogue", "Rogue", features=["Evasion"])
    assert damage_after_save(rogue, 20, "dex", True, True) == 0
    assert damage_after_save(rogue, 20, "dex", False, True) == 10
    assert damage_after_save(rogue, 20, "con", False, True) == 20
    assert damage_after_save(pc(), 20, "dex", True, True) == 10
    assert damage_after_save(pc(), 20, "dex", True, False) == 0  # Sacred Flame
    barbarian = pc(features=["Danger Sense"])
    with patch("random.randint", side_effect=[3, 17]):
        assert roll_saving_throw(barbarian, "dex", 15)["save_success"]


def test_sacred_flame_does_nothing_on_a_successful_save():
    caster = pc("Cleric", "Cleric", features=[])
    caster.add_spell(SpellManager().get_spell("Sacred Flame"))
    orc = foe()
    with patch("random.randint", return_value=20):
        result = caster.cast_spell("Sacred Flame", orc)
    assert result["save_success"] and result["damage"] == 0 and orc.hp == 60
