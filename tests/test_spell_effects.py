"""Spells with effects of their own (Sleep, Entangle, Web, Hypnotic Pattern, Moonbeam, Call
Lightning, Hunter's Mark, Spiritual Weapon, Magic Weapon, Shield of Faith, Divine Favor,
Protection from Evil and Good, Mirror Image, Mage Armor) and concentration."""
import json
from unittest.mock import patch


from ai.strategy import PartyAIStrategy, combat_spells
from models import concentration, spell_effects
from models.actions import AttackAction
from models.buffs import is_incapacitated, is_spellbound
from models.character import Character
from models.combat import Combat
from models.damage import apply_damage
from models.monster import Monster
from models.rolls import attack_roll, roll_saving_throw
from models.spell_manager import SpellManager
from models.spells import SpellAction, parse_duration_rounds
from utils.paths import data_path

SPELLS = SpellManager()
SCORES = {'str': 10, 'dex': 14, 'con': 14, 'int': 16, 'wis': 16, 'cha': 16}


def weapon(name='Longsword', dice='1d8', kind='melee', damage_type='slashing'):
    return AttackAction(name, '', name, dice, damage_type, weapon_type=kind)


def caster(cls='Druid', spells=(), slots=None, level=5, hp=40, actions=None, ac=12):
    hero = Character('Caster', level, cls, 'Human', SCORES, hp=hp, ac=ac, proficiency_bonus=3,
                     spell_slots=slots or {1: 4, 2: 3, 3: 2}, actions=actions or [weapon()])
    for name in spells:
        hero.add_spell(SPELLS.get_spell(name))
    return hero


def foe(name='Goblin', hp=7, kind=None, immune=(), str_=10, wis=10, ac=10, **kwargs):
    scores = {'str': str_, 'dex': 10, 'con': 10, 'int': 10, 'wis': wis, 'cha': 10}
    return Monster(name, '1/4', hp, ac, scores, actions=[weapon('Claw', '1d6')], creature_type=kind,
                   condition_immunities=list(immune), **kwargs)


def cast(hero, name, target, **kwargs):
    return SpellAction(SPELLS.get_spell(name), spell_slot_level=kwargs.pop('slot', None), **kwargs).execute(hero, target)


def always(d20, other=1):
    return lambda a, b: d20 if b == 20 else other


# Data


def test_every_spell_a_prebuilt_character_knows_is_in_the_data():
    known = set(SPELLS.get_all_spell_names())
    characters = json.load(open(data_path('characters.json')))
    missing = {s for level in characters for c in level['party'] for s in c.get('spell_list', []) if s not in known}
    assert not missing


def test_spells_with_no_use_in_a_fight_are_never_chosen():
    hero = caster(spells=['Prestidigitation', 'Goodberry', 'Revivify', 'Fire Bolt', 'Cure Wounds', 'Moonbeam'])
    assert {s.name for s in combat_spells(hero)} == {'Fire Bolt', 'Cure Wounds'}
    assert not SPELLS.get_spell('Revivify').combat and SPELLS.get_spell('Moonbeam').combat


def test_casting_time_and_duration_come_from_the_data():
    assert SPELLS.get_spell("Hunter's Mark").bonus_action and not SPELLS.get_spell('Moonbeam').bonus_action
    assert SPELLS.get_spell('Spiritual Weapon').bonus_action and not SPELLS.get_spell('Spiritual Weapon').concentration
    assert parse_duration_rounds('1 minute') == 10 and parse_duration_rounds('Up to 10 minutes') == 100
    assert parse_duration_rounds('1 hour') == 600 and parse_duration_rounds('Instantaneous') == -1


# Concentration


def test_a_new_concentration_spell_ends_the_old_one():
    hero = caster(cls='Cleric', spells=['Bless', 'Shield of Faith'])
    friend = caster()
    cast(hero, 'Bless', [hero, friend])
    assert friend.buffs.has_buff('Bless') and concentration.concentrating_on(hero) == 'Bless'
    result = cast(hero, 'Shield of Faith', friend)
    assert result['concentration_ended'] == 'Bless'
    assert not friend.buffs.has_buff('Bless') and friend.buffs.has_buff('Shield of Faith')
    assert concentration.concentrating_on(hero) == 'Shield of Faith'


def test_damage_calls_for_a_concentration_save_against_half_the_damage():
    hero = caster(cls='Cleric', spells=['Bless'])
    cast(hero, 'Bless', [hero])
    with patch('random.randint', return_value=5):  # CON save 5 + 2
        apply_damage(hero, 30, 'slashing')
    assert concentration.concentrating_on(hero) is None and not hero.buffs.has_buff('Bless')
    entry = hero.pending_log_entries[-1]
    assert 'loses concentration on Bless' in entry['description'] and 'DC 15' in entry['description']


def test_a_made_save_keeps_concentration_and_0_hp_ends_it():
    hero = caster(cls='Cleric', spells=['Bless'])
    cast(hero, 'Bless', [hero])
    with patch('random.randint', return_value=8):  # 8 + 2 meets DC 10
        apply_damage(hero, 6, 'slashing')
    assert concentration.concentrating_on(hero) == 'Bless'
    apply_damage(hero, 100, 'slashing')
    assert concentration.concentrating_on(hero) is None
    assert 'drops to 0 HP' in hero.pending_log_entries[-1]['description']


def test_an_incapacitated_caster_loses_concentration():
    hero = caster(spells=['Entangle'])
    ogre = foe('Ogre', hp=50)
    with patch('random.randint', return_value=1):
        cast(hero, 'Entangle', [ogre])
    hero.buffs.add_buff(spell_effects.create_unconscious_condition('Someone'))
    concentration.check_incapacitated(hero)
    assert not ogre.buffs.has_condition('restrained')


# Sleep


def test_sleep_puts_the_lowest_hit_points_to_sleep_first_while_the_pool_lasts():
    hero = caster(cls='Wizard', spells=['Sleep'])
    goblins = [foe(f'Goblin {i}', hp=hp) for i, hp in enumerate([7, 5, 9, 12])]
    zombie = foe('Zombie', hp=3, kind='undead')
    elf = foe('Fey', hp=2, immune=['charmed'])
    with patch('random.randint', return_value=5):  # pool 25
        result = cast(hero, 'Sleep', goblins + [zombie, elf])
    assert result['hit_point_pool'] == 25
    assert result['conditions_applied'] == ['Goblin 1', 'Goblin 0', 'Goblin 2']  # 5 + 7 + 9; the 12 doesn't fit
    assert is_incapacitated(goblins[1]) and not goblins[3].buffs.has_condition('unconscious')
    assert not zombie.buffs.has_condition('unconscious') and not elf.buffs.has_condition('unconscious')


def test_a_higher_slot_adds_2d8_to_sleeps_pool():
    hero = caster(cls='Wizard', spells=['Sleep'])
    with patch('random.randint', return_value=5):
        assert cast(hero, 'Sleep', [foe()], slot=2)['hit_point_pool'] == 35


def test_a_sleeping_creature_is_easy_to_hit_and_wakes_when_hurt():
    goblin = foe(hp=20)
    goblin.buffs.add_buff(spell_effects.create_unconscious_condition('Wizard'))
    hero = caster()
    assert attack_roll(hero, goblin).advantage
    assert roll_saving_throw(goblin, 'dex', 1)['auto_fail']
    with patch('random.randint', side_effect=always(15, 4)):
        result = weapon().execute(hero, goblin)
    assert result['critical']  # a melee hit from within 5 ft
    assert not goblin.buffs.has_condition('unconscious') and not is_spellbound(goblin)


def test_a_sleeping_monster_loses_its_turn():
    hero = caster(hp=100)
    goblin = foe(hp=20)
    goblin.buffs.add_buff(spell_effects.create_unconscious_condition('Wizard'))
    combat = Combat([hero, goblin])
    combat.initiative_order = [goblin, hero]
    combat.next_turn()
    entry = combat.get_combat_log()[-1]
    assert entry['actor'] == 'Goblin' and entry['result']['condition'] == 'unconscious'
    assert hero.hp == 100


# Entangle, Web and Hypnotic Pattern


def test_entangle_restrains_creatures_that_fail_a_strength_save():
    hero = caster(spells=['Entangle'])
    ogre, wraith = foe('Ogre', hp=50), foe('Wraith', hp=60, immune=['restrained'])
    with patch('random.randint', return_value=2):
        result = cast(hero, 'Entangle', [ogre, wraith])
    assert result['conditions_applied'] == ['Ogre']
    assert attack_roll(hero, ogre).advantage and attack_roll(ogre, hero).disadvantage
    assert roll_saving_throw(ogre, 'dex', 1)['disadvantage']
    assert concentration.held_by(hero) == [ogre]
    concentration.end(hero)
    assert not ogre.buffs.has_condition('restrained')


def test_a_restrained_creature_can_break_free_with_a_strength_check():
    ogre = foe('Ogre', hp=50, str_=18)
    hero = caster(spells=['Web'])
    with patch('random.randint', return_value=2):
        cast(hero, 'Web', [ogre])
    with patch('random.randint', return_value=10):  # 10 + 4 vs DC 14
        result = spell_effects.try_escape(ogre)
    assert result['condition_ended'] and not ogre.buffs.has_condition('restrained')


def test_hypnotic_pattern_takes_creatures_out_until_they_are_hurt():
    hero = caster(cls='Bard', spells=['Hypnotic Pattern'])
    orc, mummy = foe('Orc', hp=15), foe('Mummy', hp=58, immune=['charmed'])
    with patch('random.randint', return_value=3):
        result = cast(hero, 'Hypnotic Pattern', [orc, mummy])
    assert result['conditions_applied'] == ['Orc'] and result['target_results'][1]['immune']
    assert is_incapacitated(orc) and not roll_saving_throw(orc, 'dex', 1)['auto_fail']
    apply_damage(orc, 1, 'fire')
    assert not is_incapacitated(orc)


def test_the_party_leaves_hypnotized_enemies_alone_while_others_fight():
    hero = caster(cls='Fighter', actions=[weapon()])
    awake, dazed = foe('Orc 1', hp=15), foe('Orc 2', hp=30)
    dazed.buffs.add_buff(spell_effects.create_hypnotized_condition('Bard'))
    plan = PartyAIStrategy().choose_action(hero, {'allies': [hero], 'enemies': [dazed, awake], 'round': 3})
    assert plan['target'] is awake


# Moonbeam and Call Lightning


def test_moonbeam_burns_its_creature_at_the_start_of_each_of_its_turns():
    hero = caster(spells=['Moonbeam'])
    ogre = foe('Ogre', hp=50)
    result = cast(hero, 'Moonbeam', ogre)
    assert ogre.hp == 50 and 'moonlight' in result['effect_text']
    with patch('random.randint', return_value=5):  # save 5 fails DC 14; 2d10 = 10
        caster_name, entry = spell_effects.moonbeam_turn_start(ogre)
    assert caster_name == 'Caster' and entry['damage'] == 10 and ogre.hp == 40
    with patch('random.randint', return_value=19):
        _, entry = spell_effects.moonbeam_turn_start(ogre)
    assert entry['damage'] == 19  # half of 2d10 (38)


def test_moonbeam_moves_to_another_creature_without_a_slot_when_its_creature_drops():
    hero = caster(spells=['Moonbeam'], slots={2: 1})
    first, second = foe('Ogre 1', hp=50), foe('Ogre 2', hp=50)
    cast(hero, 'Moonbeam', first)
    first.hp = 0
    plan = PartyAIStrategy().choose_action(hero, {'allies': [hero], 'enemies': [second], 'round': 3})
    assert plan['spell'].free and plan['target'] is second
    plan['spell'].execute(hero, second)
    assert hero.spell_slots_remaining[2] == 0 and concentration.concentrating_on(hero) == 'Moonbeam'
    assert spell_effects.moonbeam_turn_start(second) is not None


def test_moonbeams_start_of_turn_damage_is_logged_as_the_casters():
    hero = caster(spells=['Moonbeam'], hp=100)
    ogre = foe('Ogre', hp=50)
    cast(hero, 'Moonbeam', ogre)
    combat = Combat([hero, ogre])
    combat.initiative_order = [ogre, hero]
    with patch('random.randint', return_value=1):
        combat.next_turn()
    first = next(e for e in combat.get_combat_log() if e['type'] == 'action')
    assert first['actor'] == 'Caster' and first['result']['spell'] == 'Moonbeam' and ogre.hp < 50


def test_call_lightning_keeps_calling_bolts_without_slots():
    hero = caster(spells=['Call Lightning'], slots={3: 1})
    ogres = [foe(f'Ogre {i}', hp=60) for i in range(2)]
    with patch('random.randint', return_value=1):
        first = cast(hero, 'Call Lightning', ogres, slot=3)
    assert first['total_damage'] > 0 and hero.spell_slots_remaining[3] == 0
    plan = PartyAIStrategy().choose_action(hero, {'allies': [hero], 'enemies': ogres, 'round': 3})
    assert plan['spell'].spell.name == 'Call Lightning' and plan['spell'].free
    with patch('random.randint', return_value=1):
        again = plan['spell'].execute(hero, plan['target'])
    assert again['success'] and again['total_damage'] > 0 and concentration.concentrating_on(hero) == 'Call Lightning'


# Weapon riders and bonus-action spells


def test_hunters_mark_adds_a_d6_to_hits_on_its_mark_only():
    ranger = caster(cls='Ranger', spells=["Hunter's Mark"], actions=[weapon('Longbow', '1d8', 'ranged', 'piercing')])
    marked, other = foe('Orc 1', hp=50), foe('Orc 2', hp=50)
    cast(ranger, "Hunter's Mark", marked)
    hit = {'hit': True, 'critical': True, 'damage': 5, 'damage_type': 'piercing'}
    with patch('random.randint', return_value=4):
        notes = spell_effects.weapon_riders(ranger, hit, marked)
    assert hit['damage'] == 5 + 8 and notes == ["Hunter's Mark: +8"]  # two d6s on a critical hit
    assert spell_effects.weapon_riders(ranger, {'hit': True, 'damage': 5}, other) == []


def test_a_ranger_marks_its_target_as_a_bonus_action_and_moves_the_mark_for_free():
    bow = weapon('Longbow', '1d8', 'ranged', 'piercing')
    ranger = caster(cls='Ranger', spells=["Hunter's Mark"], actions=[bow], slots={1: 2})
    first, second = foe('Orc 1', hp=60), foe('Orc 2', hp=60)
    combat = Combat([ranger, first, second])
    with patch('random.randint', return_value=1):
        combat._take_turn(ranger, {'type': 'attack', 'action': bow, 'target': first})
    assert first.buffs.has_buff("Hunter's Mark") and ranger.spell_slots_remaining[1] == 1
    first.hp = 0
    with patch('random.randint', return_value=1):
        combat._take_turn(ranger, {'type': 'attack', 'action': bow, 'target': second})
    assert second.buffs.has_buff("Hunter's Mark") and ranger.spell_slots_remaining[1] == 1


def test_no_leveled_bonus_spell_when_the_action_casts_a_leveled_spell():
    ranger = caster(cls='Ranger', spells=["Hunter's Mark", 'Cure Wounds'], slots={1: 2})
    orc = foe('Orc', hp=60)
    combat = Combat([ranger, orc])
    combat._take_turn(ranger, {'type': 'cast_spell', 'spell': SpellAction(SPELLS.get_spell('Cure Wounds')),
                               'target': ranger})
    assert not orc.buffs.has_buff("Hunter's Mark")


def test_spiritual_weapon_attacks_when_cast_and_on_later_turns_without_a_slot():
    cleric = caster(cls='Cleric', spells=['Spiritual Weapon', 'Sacred Flame'], slots={2: 1})
    orc = foe('Orc', hp=60)
    combat = Combat([cleric, orc])
    plan = {'type': 'cast_spell', 'spell': SpellAction(SPELLS.get_spell('Sacred Flame')), 'target': orc}
    with patch('random.randint', side_effect=always(15, 4)):
        combat._take_turn(cleric, plan)
        combat._take_turn(cleric, plan)
    weapon_hits = [e['result'] for e in combat.get_combat_log() if e['result'].get('spell') == 'Spiritual Weapon']
    assert len(weapon_hits) == 2 and all(r['damage'] == 4 + 3 for r in weapon_hits)  # 1d8 + WIS
    assert cleric.spell_slots_remaining[2] == 0 and concentration.concentrating_on(cleric) is None


def test_magic_weapon_adds_one_and_gets_past_nonmagical_resistance():
    paladin = caster(cls='Paladin', spells=['Magic Weapon'])
    sword = weapon()
    before = paladin.attack_bonus('melee')
    cast(paladin, 'Magic Weapon', paladin, slot=2)
    assert paladin.attack_bonus('melee') == before + 1
    spawn = foe('Vampire Spawn', hp=80, damage_resistances=['slashing'])
    with patch('random.randint', side_effect=always(15, 4)):
        result = sword.execute(paladin, spawn)
    assert result['damage'] == 4 + 0 + 1  # 1d8 + STR 0 + 1, not halved


def test_a_paladin_casts_magic_weapon_against_resistant_enemies_and_shield_of_faith_otherwise():
    sword = weapon()
    for resist, expected in ((['slashing'], 'Magic Weapon'), ([], 'Shield of Faith')):
        paladin = caster(cls='Paladin', spells=['Magic Weapon', 'Shield of Faith'], slots={1: 2, 2: 1}, actions=[sword])
        enemy = foe('Spawn', hp=80, damage_resistances=resist)
        combat = Combat([paladin, enemy])
        with patch('random.randint', return_value=1):
            combat._take_turn(paladin, {'type': 'attack', 'action': sword, 'target': enemy})
        assert concentration.concentrating_on(paladin) == expected


def test_shield_of_faith_and_mage_armor_change_ac():
    wizard = caster(cls='Wizard', spells=['Mage Armor'], ac=12)
    entry = spell_effects.prepare(wizard)
    assert wizard.ac == 13 + 2 and wizard.spell_slots_remaining[1] == 3 and entry['spell'] == 'Mage Armor'
    assert spell_effects.prepare(wizard) is None  # already on
    cleric = caster(cls='Cleric', spells=['Shield of Faith'], ac=18)
    cast(cleric, 'Shield of Faith', cleric)
    assert cleric.ac == 20
    concentration.end(cleric)
    assert cleric.ac == 18


def test_mage_armor_isnt_cast_over_better_armor():
    knight = caster(cls='Wizard', spells=['Mage Armor'], ac=16)
    assert spell_effects.prepare(knight) is None and knight.spell_slots_remaining[1] == 4


def test_divine_favor_adds_radiant_damage_to_weapon_hits():
    paladin = caster(cls='Paladin', spells=['Divine Favor'])
    cast(paladin, 'Divine Favor', paladin)
    hit = {'hit': True, 'damage': 6, 'damage_type': 'slashing'}
    with patch('random.randint', return_value=3):
        notes = spell_effects.weapon_riders(paladin, hit, foe(hp=30))
    assert hit['damage'] == 9 and notes == ['Divine Favor: +3 radiant']


def test_protection_from_evil_and_good_gives_undead_disadvantage():
    paladin = caster(cls='Paladin', spells=['Protection from Evil and Good'])
    cast(paladin, 'Protection from Evil and Good', paladin)
    assert attack_roll(foe('Ghoul', kind='undead'), paladin).disadvantage
    assert not attack_roll(foe('Orc', kind='humanoid'), paladin).disadvantage


def test_mirror_image_duplicates_take_attacks_and_vanish_when_hit():
    wizard = caster(cls='Wizard', spells=['Mirror Image'], hp=30)
    cast(wizard, 'Mirror Image', wizard, slot=2)
    orc = foe('Orc', hp=30)
    combat = Combat([wizard, orc])
    with patch('random.randint', side_effect=always(15, 4)):  # 15 beats 6: a duplicate; 15 hits AC 12
        result = combat._attack(orc, orc.actions[0], wizard, {})
    assert result['mirror_image'] and result['damage'] == 0 and wizard.hp == 30
    images = next(b for b in wizard.buffs.active_buffs if b.metadata.get('mirror_images'))
    assert images.metadata['mirror_images'] == 2
    with patch('random.randint', side_effect=always(7, 4)):  # 7 doesn't reach 8 with two left
        result = combat._attack(orc, orc.actions[0], wizard, {})
    assert not result.get('mirror_image')


def test_condition_immunities_come_from_the_monster_data():
    from models.monster_builder import build_monsters
    data = {m['name']: m for m in json.load(open(data_path('monsters.json')))['monsters']}
    wraith, goblin = build_monsters([data['Wraith'], data['Goblin']])
    assert 'restrained' in wraith.condition_immunities and 'charmed' in wraith.condition_immunities
    assert goblin.condition_immunities == []


def test_the_party_casts_sleep_on_a_crowd_of_small_enemies():
    wizard = caster(cls='Wizard', spells=['Sleep', 'Fire Bolt'], slots={1: 2})
    goblins = [foe(f'Goblin {i}', hp=7) for i in range(4)]
    plan = PartyAIStrategy().choose_action(wizard, {'allies': [wizard], 'enemies': goblins, 'round': 1})
    assert plan['spell'].spell.name == 'Sleep'
    lone = PartyAIStrategy().choose_action(wizard, {'allies': [wizard], 'enemies': [foe('Ogre', hp=59)], 'round': 1})
    assert lone['spell'].spell.name != 'Sleep'


def test_a_caster_with_fireball_doesnt_web_the_crowd_and_no_one_webs_the_webbed():
    ogres = [foe(f'Ogre {i}', hp=59) for i in range(3)]
    blaster = caster(cls='Wizard', spells=['Web', 'Fireball'], slots={2: 1, 3: 1})
    plan = PartyAIStrategy().choose_action(blaster, {'allies': [blaster], 'enemies': ogres, 'round': 1})
    assert plan['spell'].spell.name == 'Fireball'
    webber = caster(cls='Wizard', spells=['Web', 'Fire Bolt'], slots={2: 2})
    plan = PartyAIStrategy().choose_action(webber, {'allies': [webber], 'enemies': ogres, 'round': 1})
    assert plan['spell'].spell.name == 'Web'
    for ogre in ogres:
        ogre.buffs.add_buff(spell_effects.create_restrained_condition('Someone', 'Web', 13))
    plan = PartyAIStrategy().choose_action(caster(cls='Wizard', spells=['Web', 'Fire Bolt'], slots={2: 2}),
                                           {'allies': [webber], 'enemies': ogres, 'round': 1})
    assert plan['spell'].spell.name != 'Web'


# Class spell lists and spell levels (SRD)

# The SRD class lists, limited to the spells in data/spells.json; a Fiend warlock adds its expanded
# spells, and a Lore bard's Additional Magical Secrets (6th level) and Magical Secrets (10th) can come
# from any class
CLASS_SPELLS = {
    'Bard': {'Mage Hand', 'Minor Illusion', 'Prestidigitation', 'Vicious Mockery', 'Cure Wounds', 'Healing Word',
             'Sleep', 'Lesser Restoration', 'Dispel Magic', 'Hypnotic Pattern', 'Greater Invisibility',
             'Mass Cure Wounds', 'Hold Monster'},
    'Cleric': {'Sacred Flame', 'Spare the Dying', 'Bless', 'Cure Wounds', 'Guiding Bolt', 'Healing Word',
               'Protection from Evil and Good', 'Shield of Faith', 'Lesser Restoration', 'Prayer of Healing',
               'Spiritual Weapon', 'Dispel Magic', 'Revivify', 'Flame Strike', 'Mass Cure Wounds', 'Heal'},
    'Druid': {'Produce Flame', 'Cure Wounds', 'Entangle', 'Goodberry', 'Healing Word', 'Lesser Restoration',
              'Moonbeam', 'Pass Without Trace', 'Call Lightning', 'Dispel Magic', 'Blight', 'Ice Storm',
              'Mass Cure Wounds', 'Heal'},
    'Paladin': {'Bless', 'Cure Wounds', 'Divine Favor', 'Protection from Evil and Good', 'Shield of Faith',
                'Lesser Restoration', 'Magic Weapon', 'Dispel Magic', 'Revivify'},
    'Ranger': {'Cure Wounds', 'Goodberry', "Hunter's Mark", 'Lesser Restoration', 'Pass Without Trace'},
    'Sorcerer': {'Fire Bolt', 'Mage Hand', 'Minor Illusion', 'Prestidigitation', 'Burning Hands', 'Mage Armor',
                 'Magic Missile', 'Shield', 'Sleep', 'Mirror Image', 'Scorching Ray', 'Web', 'Counterspell',
                 'Dispel Magic', 'Fireball', 'Hypnotic Pattern', 'Blight', 'Greater Invisibility', 'Ice Storm',
                 'Cone of Cold', 'Hold Monster'},
    'Warlock': {'Eldritch Blast', 'Mage Hand', 'Minor Illusion', 'Prestidigitation', 'Protection from Evil and Good',
                'Mirror Image', 'Counterspell', 'Dispel Magic', 'Hypnotic Pattern', 'Blight', 'Hold Monster'},
    'Wizard': {'Fire Bolt', 'Mage Hand', 'Minor Illusion', 'Prestidigitation', 'Burning Hands', 'Mage Armor',
               'Magic Missile', 'Protection from Evil and Good', 'Shield', 'Sleep', 'Magic Weapon', 'Mirror Image',
               'Scorching Ray', 'Web', 'Counterspell', 'Dispel Magic', 'Fireball', 'Hypnotic Pattern', 'Blight',
               'Greater Invisibility', 'Ice Storm', 'Cone of Cold', 'Hold Monster'},
}
FIEND_SPELLS = {'Burning Hands', 'Scorching Ray', 'Fireball', 'Flame Strike'}


def test_prebuilt_characters_only_know_spells_from_their_class_list():
    wrong = []
    for level in json.load(open(data_path('characters.json'))):
        for c in level['party']:
            allowed = set(CLASS_SPELLS.get(c['character_class'], ()))
            if any('The Fiend' in f for f in c['class_features']):
                allowed |= FIEND_SPELLS
            lore = any('Lore' in f for f in c['class_features'])
            secrets = (2 * (level['level'] >= 6) + 2 * (level['level'] >= 10)) if lore else 0
            off = [s for s in c.get('spell_list', []) if s not in allowed]
            if len(off) > secrets:
                wrong.append((level['level'], c['name'], off))
    assert not wrong


def test_spell_levels_match_the_srd():
    assert SPELLS.get_spell('Healing Word').level == 1
    assert SPELLS.get_spell('Spare the Dying').level == 0
    assert SPELLS.get_spell('Heal').level == 6


def test_vicious_mockery_gives_disadvantage_on_the_next_attack_only():
    bard = caster(cls='Bard', spells=['Vicious Mockery'])
    orc = foe('Orc', hp=30)
    with patch('random.randint', return_value=2):  # fails the WIS save; 2d4 = 4 psychic at level 5
        result = cast(bard, 'Vicious Mockery', orc)
    assert result['damage'] == 4 and orc.buffs.has_buff('Vicious Mockery')
    assert attack_roll(orc, bard).disadvantage
    assert not attack_roll(orc, bard).disadvantage  # the second attack is normal


def test_vicious_mockery_ends_at_the_end_of_its_targets_turn():
    bard = caster(cls='Bard', spells=['Vicious Mockery'], hp=100)
    orc = foe('Orc', hp=30)
    with patch('random.randint', return_value=2):
        cast(bard, 'Vicious Mockery', orc)
    combat = Combat([bard, orc])
    combat._end_of_turn_effects(bard)
    assert orc.buffs.has_buff('Vicious Mockery')
    combat._end_of_turn_effects(orc)
    assert not orc.buffs.has_buff('Vicious Mockery')


def test_burning_hands_does_half_on_a_save_and_produce_flame_is_a_spell_attack():
    mage = caster(cls='Wizard', spells=['Burning Hands', 'Produce Flame'])
    goblins = [foe(f'Goblin {i}', hp=30) for i in range(2)]
    with patch('random.randint', side_effect=lambda a, b: 20 if b == 20 else 4):  # both save; 3d6 = 12
        result = cast(mage, 'Burning Hands', goblins)
    assert [t['damage'] for t in result['target_results']] == [6, 6]  # 12 halved
    with patch('random.randint', side_effect=lambda a, b: 15 if b == 20 else 3):
        flame = cast(mage, 'Produce Flame', goblins[0])
    assert flame['hit'] and flame['damage'] == 6 and flame['damage_type'] == 'fire'  # 2d8 at level 5


def test_monster_saving_throws_come_from_the_data():
    from models.monster_builder import build_monsters
    data = {m['name']: m for m in json.load(open(data_path('monsters.json')))['monsters']}
    zombie, spawn, goblin = build_monsters([data['Zombie'], data['Vampire Spawn'], data['Goblin']])
    assert zombie.saving_throw_bonus('wis') == 0 and zombie.saving_throw_bonus('dex') == -2
    assert spawn.saving_throw_bonus('dex') == 6 and spawn.saving_throw_bonus('wis') == 3
    assert spawn.saving_throw_bonus('con') == 3
    assert goblin.saving_throws == {}
