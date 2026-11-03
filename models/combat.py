"""
Combat system for D&D 5e Combat Simulator.

Defines the Combat and CombatLogger classes for managing turn-based combat.
"""
import random
from typing import List, Dict, Any, Optional, Tuple, TYPE_CHECKING
from utils.exceptions import SimulationError
from utils.logging import log_exception
from ai.strategy import PartyAIStrategy, MonsterAIStrategy, lowest_slot
from ai.tactical import TacticalAnalyzer
from ai.aiming import aim_area
from ai.positioning import fit_plan
from models.rolls import roll_saving_throw
from models.buffs import is_incapacitated, is_paralyzed, is_spellbound, is_stunned, is_turned
from models.actions import AttackAction
from models.arena import COVER_AC_BONUS, COVER_NONE, COVER_TOTAL, SQUARE_FEET, describe_area
from models.battlefield import (MONSTERS, PARTY, Battlefield, area_of, area_range, bonus_dash, bonus_disengage,
                                ignores_cover, melee_attacks)
from models.multiattack import parse_multiattack
from models.damage import apply_damage, has_ability
from models import class_features as feature_rules
from models import concentration, spell_effects
from models.spells import SpellAction
import logging
logger = logging.getLogger('dnd5e_combat_sim.combat')

if TYPE_CHECKING:
    from models.character import Character
    from models.monster import Monster

def _ordinal(n: int) -> str:
    return {1: '1st', 2: '2nd', 3: '3rd'}.get(n, f'{n}th')


def _average_damage(action: Any) -> float:
    try:
        num, die, mod = AttackAction.parse_dice(str(action.damage_dice))
        return num * (die + 1) / 2 + mod
    except (TypeError, ValueError):
        return 0.0


class CombatLogger:
    """
    Optimized combat logging with efficient data structures.
    """
    def __init__(self) -> None:
        self.log: List[Dict[str, Any]] = []
        self._round_cache = {}  # Cache for round-specific data
        # Called with each action entry as it's logged (Combat records replay frames with it)
        self.on_action: Optional[Any] = None

    def log_action(self, actor: Any, action_result: dict, round_number: int = 0) -> None:
        """Log action with optimized data structure."""
        entry = {
            'type': 'action',
            'actor': getattr(actor, 'name', str(actor)),
            'result': action_result,
            'round': round_number,
            'timestamp': len(self.log)  # Use index as timestamp for efficiency
        }
        self.log.append(entry)
        if self.on_action is not None:
            self.on_action(entry)

    def log_round_start(self, round_num: int) -> None:
        """Log round start with caching."""
        if round_num not in self._round_cache:
            self._round_cache[round_num] = True
            self.log.append({
                'type': 'round_start',
                'round': round_num
            })

    def get_combat_log(self) -> List[Dict]:
        """Get combat log with optional filtering."""
        return self.log

class Combat:
    """
    Optimized D&D 5e combat encounter management with efficient data structures and caching.
    """
    def __init__(self, participants: List[Any], arena: Optional[Any] = None) -> None:
        """
        Args:
            participants: Characters and monsters
            arena: An Arena to fight on, or None to fight without positions (everyone can reach
                everyone, as before arenas existed)
        """
        self.participants: List[Any] = participants[:]
        self.initiative_order: List[Any] = []
        self.current_round: int = 1
        self.current_turn: int = 0
        self.logger = CombatLogger()
        # Pre-calculate participant types for efficiency
        from models.character import Character
        from models.monster import Monster
        self._original_characters = [p for p in participants if isinstance(p, Character)]
        self._original_monsters = [p for p in participants if isinstance(p, Monster)]
        # Pre-allocate AI strategies
        self.ai_strategy_map = {}
        for p in participants:
            if isinstance(p, Character):
                self.ai_strategy_map[p] = PartyAIStrategy()
            elif isinstance(p, Monster):
                self.ai_strategy_map[p] = MonsterAIStrategy()
        # Cache for initiative rolls and other calculations
        self._initiative_cache = {}
        self._alive_participants_cache = None
        self._last_alive_check = 0
        self.tactical = TacticalAnalyzer()
        # True while the creature taking its turn has Disengaged (no opportunity attacks)
        self._disengaged = False
        # The turn being taken: Sneak Attack dice still unused, class features used (for the log)
        self._turn: Dict[str, Any] = {}
        # Without an arena, creatures that have used their reaction since their last turn
        self._reacted: set = set()
        # Regeneration (e.g. trolls): damage types that stopped it since the creature's last turn,
        # and creatures that started a turn at 0 HP without regenerating, which are dead for good
        self._regenerators = [p for p in participants if isinstance(getattr(p, 'regeneration', None), dict)]
        self._regen_suppressed: Dict[Any, set] = {}
        self._regen_dead: set = set()
        # Positions on the arena, if there is one. Creatures that are down for good leave the map;
        # a downed troll that will get back up stays on it.
        self.battlefield: Optional[Battlefield] = None
        if arena is not None:
            sides = {p: PARTY if isinstance(p, Character) else MONSTERS for p in participants}
            self.battlefield = Battlefield(arena, sides,
                                           present=lambda c: c.is_alive() or self._will_regenerate(c))
            self.battlefield.place_all()
        self.start_positions = self.battlefield.snapshot() if self.battlefield else None
        # On an arena, where everyone stands and their HP after each logged action, for the replay
        self.frames: List[Dict[str, Any]] = []
        if self.battlefield is not None:
            self.logger.on_action = self._record_frame
        self._start_hp = self._hit_points()
        # Spells cast before the fight (Mage Armor)
        for character in self._original_characters:
            prepared = spell_effects.prepare(character)
            if prepared:
                self.logger.log_action(character, prepared, 1)

    def _positions(self) -> Dict[str, List[int]]:
        bf = self.battlefield
        return {getattr(c, 'name', str(c)): list(p.position) for c, p in bf.placements.items() if bf.present(c)}

    def _hit_points(self) -> Dict[str, int]:
        return {getattr(p, 'name', str(p)): p.hp for p in self.participants}

    def _record_frame(self, entry: Dict[str, Any]) -> None:
        """
        One replay frame per logged action: positions and HP after it, the moves it made and
        the squares of an area effect. Frame i goes with the i-th action entry of the log.
        """
        result = entry['result']
        frame: Dict[str, Any] = {'round': entry['round'], 'actor': entry['actor'],
                                 'positions': self._positions(), 'hp': self._hit_points()}
        moves = [[m['from'], m['to']] for m in (result.get('movement'), result.get('movement_after'))
                 if m and m.get('from') != m.get('to')]
        if moves:
            frame['moves'] = moves
        if result.get('area_squares'):
            frame['area'] = result['area_squares']
        targets = result.get('target')
        if targets:
            frame['targets'] = [str(t) for t in targets] if isinstance(targets, list) else \
                [t.strip() for t in str(targets).split(',')]
        self.frames.append(frame)

    def replay(self) -> Optional[Dict[str, Any]]:
        """Everything needed to draw the fight round by round, or None without an arena."""
        bf = self.battlefield
        if bf is None:
            return None
        return {
            'arena': bf.arena.drawing(),
            'creatures': [{'name': getattr(c, 'name', str(c)), 'side': bf.sides[c], 'size': p.size,
                           'max_hp': getattr(c, 'max_hp', c.hp)} for c, p in bf.placements.items()],
            'start': {'positions': self.start_positions, 'hp': self._start_hp},
            'frames': self.frames,
        }

    def _get_alive_participants(self) -> List[Any]:
        """Get alive participants with caching for efficiency."""
        if self._alive_participants_cache is None or self._last_alive_check != self.current_round:
            self._alive_participants_cache = [
                p for p in self.participants if p.is_alive() or self._will_regenerate(p)
            ]
            self._last_alive_check = self.current_round
        return self._alive_participants_cache

    def _will_regenerate(self, participant: Any) -> bool:
        """True for a creature at 0 HP that will get back up at the start of its next turn."""
        regen = getattr(participant, 'regeneration', None)
        return (isinstance(regen, dict) and regen.get('revives_at_zero', False)
                and participant.hp <= 0
                and participant not in self._regen_dead
                and participant not in self._regen_suppressed)

    @staticmethod
    def _damage_types(result: Any) -> set:
        """Collect every damage type mentioned in an action result, including nested attacks."""
        found = set()
        if isinstance(result, dict):
            if isinstance(result.get('damage_type'), str):
                found.add(result['damage_type'].lower())
            for value in result.values():
                found |= Combat._damage_types(value)
        elif isinstance(result, list):
            for value in result:
                found |= Combat._damage_types(value)
        return found

    def _note_regeneration_damage(self, hp_before: Dict[Any, int], result: Dict[str, Any]) -> None:
        """Record damage types that stop regeneration on creatures this action hurt."""
        types = None
        for creature, hp in hp_before.items():
            # HP can't go below 0, so a creature that is already down is hurt if the action hit it
            if creature.hp < hp or (hp == 0 and self._damage_dealt_to(result, creature) > 0):
                types = self._damage_types(result) if types is None else types
                stopped = types & {t.lower() for t in creature.regeneration.get('suppressed_by', [])}
                if stopped:
                    self._regen_suppressed.setdefault(creature, set()).update(stopped)
                    self._alive_participants_cache = None

    @staticmethod
    def _damage_dealt_to(result: Dict[str, Any], creature: Any) -> int:
        """Damage a single-target action result (or each attack of an Extra Attack) dealt to the creature."""
        name = getattr(creature, 'name', None)
        attacks = result.get('attacks') or [result]
        return sum(a.get('damage', 0) or 0 for a in attacks if a.get('target') == name)

    def _regeneration_turn_start(self, participant: Any) -> Optional[Dict[str, Any]]:
        """
        Apply regeneration at the start of the creature's turn. Returns a log entry, or None
        if nothing happened (already at full HP).
        """
        regen = participant.regeneration
        stopped = self._regen_suppressed.pop(participant, None)
        was_down = participant.hp <= 0
        healed = 0
        if stopped:
            types = ' or '.join(sorted(stopped))
            if was_down:
                self._regen_dead.add(participant)
                description = f"took {types} damage, so it doesn't regenerate and dies"
            else:
                description = f"took {types} damage, so it doesn't regenerate this turn"
        elif was_down and not regen.get('revives_at_zero', False):
            return None
        elif participant.hp >= participant.max_hp:
            return None
        else:
            healed = min(int(regen.get('hp', 0)), participant.max_hp - participant.hp)
            participant.hp += healed
            description = f"regenerates {healed} HP" + (" and gets back up" if was_down else "")
        self._alive_participants_cache = None
        return {
            'action': 'Regeneration',
            'type': 'condition',
            'condition': 'regeneration',
            'target': participant.name,
            'healing': healed,
            'description': description,
        }

    def roll_initiative(self) -> None:
        """
        Optimized initiative rolling with caching and efficient sorting.
        """
        rolls = []
        for p in self.participants:
            # Use cached initiative if available
            if p in self._initiative_cache:
                roll = self._initiative_cache[p]
            else:
                roll = p.roll_initiative()
                self._initiative_cache[p] = roll
            
            # Pre-calculate dex modifier for sorting efficiency
            dex_mod = getattr(p, 'ability_modifier', lambda x: 0)('dex')
            rolls.append((roll, dex_mod, random.random(), p))
        
        # Sort once with all criteria
        rolls.sort(key=lambda x: (-x[0], -x[1], x[2]))
        self.initiative_order = [x[3] for x in rolls]
        self.current_turn = 0
        self.current_round = 1
        # Clear alive cache since initiative order changed
        self._alive_participants_cache = None

    def next_turn(self) -> Optional[Any]:
        """
        Optimized turn advancement with efficient alive participant checking.
        """
        if self.is_combat_over():
            return None
        start = self.current_turn
        n = len(self.initiative_order)
        alive_participants = self._get_alive_participants()
        alive_set = set(alive_participants)
        
        for i in range(n):
            idx = (start + i) % n
            participant = self.initiative_order[idx]
            if participant in alive_set:
                self.current_turn = idx + 1
                if self.battlefield is not None:
                    self.battlefield.reacted.discard(participant)  # its reaction is back
                self._reacted.discard(participant)
                self._start_of_turn_effects(participant)
                self._check_concentration()
                # Wrapping past the end of the initiative order starts a new round. (Checking for
                # the last slot instead would stall the round count once that creature is dead.)
                if start + i >= n:
                    self.current_round += 1
                    self.logger.log_round_start(self.current_round)
                    self._alive_participants_cache = None
                    # Tick buffs on all alive participants at the start of each round
                    for p in alive_set:
                        if hasattr(p, 'buffs'):
                            p.buffs.tick_round()
                if participant in self._regenerators:
                    regen_result = self._regeneration_turn_start(participant)
                    if regen_result:
                        self.logger.log_action(participant, regen_result, self.current_round)
                    if participant.hp <= 0:
                        return participant
                if self._moonbeam(participant):
                    return participant
                if is_paralyzed(participant):
                    # Incapacitated: no action this turn, then repeat the save at the end of it
                    result = self._paralyzed_turn(participant)
                    self.logger.log_action(participant, result, self.current_round)
                    self._end_of_turn_effects(participant)
                    return participant
                if is_incapacitated(participant) or is_turned(participant) or self._wants_to_escape(participant):
                    if is_stunned(participant):
                        result = self._stunned_turn(participant)
                    elif is_incapacitated(participant):
                        result = self._incapacitated_turn(participant)
                    elif is_turned(participant):
                        result = self._turned_turn(participant)
                    else:
                        result = spell_effects.try_escape(participant)
                    self.logger.log_action(participant, result, self.current_round)
                    self._log_pending_entries()
                    self._end_of_turn_effects(participant)
                    return participant
                recharged = self._roll_recharges(participant)
                ai = self.ai_strategy_map.get(participant)
                if ai:
                    combat_state = self._build_combat_state(participant)
                    action_plan = ai.choose_action(participant, combat_state)
                    if self.battlefield is not None:
                        action_plan = fit_plan(participant, action_plan, combat_state)
                    hp_before = {c: c.hp for c in self._regenerators}
                    result = self._take_turn(participant, action_plan)
                    if recharged:
                        result['recharged'] = recharged
                    self._note_regeneration_damage(hp_before, result)
                    self.logger.log_action(participant, result, self.current_round)
                    self._log_pending_entries()
                    self._end_of_turn_effects(participant)
                    if self.is_combat_over():
                        return participant
                return participant
        return None

    @staticmethod
    def _start_of_turn_effects(participant: Any) -> None:
        """Effects that last until the creature's next turn end now (Reckless Attack)."""
        buffs = getattr(participant, 'buffs', None)
        if buffs is not None and hasattr(buffs, 'active_buffs'):
            buffs.active_buffs = [b for b in buffs.active_buffs if not b.metadata.get('until_turn_start')]

    def _end_of_turn_effects(self, participant: Any) -> None:
        """Stunning Strike's stun lasts until the end of the monk's next turn."""
        for creature in self.participants:
            buffs = getattr(creature, 'buffs', None)
            stun = buffs.get_condition('stunned') if buffs is not None and hasattr(buffs, 'get_condition') else None
            if stun is not None and stun.metadata.get('ends_after_turn_of') == participant.name:
                stun.metadata['turns_left'] -= 1
                if stun.metadata['turns_left'] <= 0:
                    buffs.remove_buff(stun.name)

    def _check_concentration(self) -> None:
        """Casters who are incapacitated (stunned, paralyzed, asleep) lose concentration."""
        for creature in self.participants:
            concentration.check_incapacitated(creature)
        self._log_pending_entries()

    def _moonbeam(self, participant: Any) -> bool:
        """
        A creature that starts its turn in a Moonbeam takes its damage (logged as the caster's).
        Returns True if that drops it, which ends its turn.
        """
        hp_before = {c: c.hp for c in self._regenerators}
        found = spell_effects.moonbeam_turn_start(participant)
        if found is None:
            return False
        caster, result = found
        self._note_regeneration_damage(hp_before, result)
        self.logger.log_action(caster, result, self.current_round)
        self._log_pending_entries()
        self._alive_participants_cache = None
        return not participant.is_alive()

    def _wants_to_escape(self, participant: Any) -> bool:
        """
        A restrained creature (Entangle, Web) uses its action to try to break free when, on an
        arena, no enemy is within reach of where it's stuck. Otherwise it fights on, with
        disadvantage.
        """
        buffs = getattr(participant, 'buffs', None)
        if self.battlefield is None or not hasattr(buffs, 'has_condition') or not buffs.has_condition('restrained'):
            return False
        reach = max([getattr(a, 'reach', SQUARE_FEET) for a in melee_attacks(participant)] or [SQUARE_FEET])
        ranged = any(getattr(a, 'range', None) for a in getattr(participant, 'actions', []))
        enemies = self._build_combat_state(participant)['enemies']
        return not ranged and not any(self.battlefield.distance(participant, e) <= reach for e in enemies)

    def _incapacitated_turn(self, participant: Any) -> Dict[str, Any]:
        """Asleep (Sleep) or hypnotized (Hypnotic Pattern): the creature does nothing."""
        if participant.buffs.has_condition('unconscious'):
            return {'action': 'Asleep', 'type': 'condition', 'condition': 'unconscious',
                    'description': 'is magically asleep'}
        return {'action': 'Hypnotized', 'type': 'condition', 'condition': 'hypnotized',
                'description': 'is hypnotized and does nothing'}

    def _stunned_turn(self, participant: Any) -> Dict[str, Any]:
        return {'action': 'Stunned', 'type': 'condition', 'condition': 'stunned',
                'description': 'is stunned and loses its turn'}

    def _turned_turn(self, participant: Any) -> Dict[str, Any]:
        """
        A turned creature Dashes as far as it can from the cleric who turned it (on an arena),
        and does nothing else. The party lets it go: no opportunity attacks, which would end it.
        """
        result = {'action': 'Turned', 'type': 'condition', 'condition': 'turned',
                  'description': 'is turned and flees'}
        if self.battlefield is None:
            return result
        source = participant.buffs.get_condition('turned').source
        cleric = next((c for c in self.participants if c.name == source and self.battlefield.present(c)), None)
        if cleric is None:
            return result
        budget = 2 * self.battlefield.speed(participant)
        theirs = self.battlefield.placements[cleric]
        reachable = self.battlefield.reachable(participant, budget)
        if not reachable:
            return result
        here = self.battlefield.position(participant)
        best = max(reachable, key=lambda s: (self.battlefield.arena.distance(self.battlefield.placement(participant, s),
                                                                             theirs), -reachable[s], s == here))
        self._disengaged = True  # the party doesn't attack it as it leaves
        movement = self._move(participant, best, budget)
        self._disengaged = False
        if movement:
            result['movement'] = movement
        return result

    @staticmethod
    def _roll_recharges(participant: Any) -> List[str]:
        """At the start of its turn, roll a d6 for each used recharge action (e.g. a breath weapon);
        it can be used again on its recharge number or higher. Returns the ones that recharged."""
        recharged = []
        for action in getattr(participant, 'actions', []):
            if getattr(action, 'recharge', None) and not action.ready and random.randint(1, 6) >= action.recharge:
                action.ready = True
                recharged.append(action.name)
        return recharged

    def _area_hits(self, participant: Any, action: Any, plan: Dict[str, Any]) -> Any:
        """
        On an arena, who an area effect catches where the plan aims it (aimed here if the plan
        isn't), each with its cover from the origin: (hits, aim). Hits is empty if the aim can't
        be used from where the participant stands.
        """
        area = area_of(action)
        aim = plan.get('aim')
        if aim is None:
            found = aim_area(self.battlefield, participant, action, {})
            aim = found.plan_fields()['aim'] if found else None
        if aim is None:
            return [], None
        origin = tuple(aim['origin'])
        toward = tuple(aim['toward']) if aim.get('toward') is not None else None
        if not self.battlefield.can_aim(participant, area, area_range(action), origin):
            return [], aim
        return self.battlefield.area_hits(participant, area, origin, toward), aim

    def _execute_area(self, participant: Any, action: Any, plan: Dict[str, Any], execute: Any) -> Dict[str, Any]:
        """
        Use an area action or spell on an arena: it affects every creature in the area, allies
        included, and DEX saves get the target's cover from the origin. `execute(targets,
        save_bonuses)` carries it out.
        """
        hits, aim = self._area_hits(participant, action, plan)
        area = area_of(action)
        source = getattr(action, 'spell', action)
        if not hits:
            return {
                'action': action.name,
                'type': 'wait',
                'success': False,
                'reason': 'no one in the area',
                'description': f"holds back {source.name} (no one in the area)",
                'target': [],
            }
        dex = getattr(source, 'save_type', None) == 'dex'
        bonuses = {target: COVER_AC_BONUS[cover] if dex else 0 for target, cover in hits}
        result = execute([target for target, _ in hits], bonuses)
        result['aim'] = aim
        result['area'] = {'shape': area.shape, 'size': area.size}
        toward = tuple(aim['toward']) if aim.get('toward') is not None else None
        result['area_squares'] = sorted([list(s) for s in
                                         self.battlefield.arena.area_squares(area, tuple(aim['origin']), toward)])
        covered = {getattr(t, 'name', str(t)): cover for t, cover in hits if cover != COVER_NONE}
        if covered:
            result['cover_by_target'] = covered
        return result

    def _log_pending_entries(self) -> None:
        """Log abilities that creatures used in response to the last action (e.g. Undead Fortitude)."""
        for creature in self.participants:
            entries = getattr(creature, 'pending_log_entries', None)
            if isinstance(entries, list) and entries:
                for entry in entries:
                    self.logger.log_action(creature, entry, self.current_round)
                entries.clear()
                self._alive_participants_cache = None

    def _has_active_ally(self, participant: Any, target: Any = None) -> bool:
        """
        "An ally is within 5 feet of the target and isn't incapacitated" (Sneak Attack, Pack
        Tactics). On an arena that's checked; without one, any other member of the participant's
        side who is up and not incapacitated counts.
        """
        if self.battlefield is not None and target is not None and not isinstance(target, list):
            return self.battlefield.ally_next_to(target, participant)
        return any(a is not participant and not is_incapacitated(a)
                   for a in self._build_combat_state(participant)['allies'])

    def _pack_tactics(self, participant: Any, target: Any = None) -> bool:
        """Pack Tactics: advantage on attacks while an ally is next to the target."""
        return has_ability(participant, 'Pack Tactics') and self._has_active_ally(participant, target)

    def _paralyzed_turn(self, participant: Any) -> Dict[str, Any]:
        """Skip a paralyzed creature's turn and roll its end-of-turn save to end the condition."""
        condition = participant.buffs.get_condition('paralyzed')
        save_type = condition.metadata.get('save_type', 'con')
        save = roll_saving_throw(participant, save_type, condition.metadata.get('save_dc', 10))
        if save['save_success']:
            participant.buffs.remove_buff(condition.name)
            outcome = f"succeeds on a {save_type.upper()} save ({save['total_save']}) and is no longer paralyzed"
        else:
            outcome = f"fails a {save_type.upper()} save ({save['total_save']}) and remains paralyzed"
        return {
            'action': 'Paralyzed',
            'type': 'condition',
            'condition': 'paralyzed',
            'condition_ended': save['save_success'],
            'description': f"is paralyzed and loses its turn; {outcome}",
            **save,
        }

    def _build_combat_state(self, participant: Any) -> Dict[str, Any]:
        """Build combat state efficiently with participant type checking."""
        is_character = participant in self._original_characters
        # Include ALL allies of the same type (including the participant itself)
        # This allows characters to heal themselves, which is valid in D&D 5e
        allies = [p for p in self.participants if
                 (p in self._original_characters) == is_character and p.is_alive()]
        enemies = [p for p in self.participants if
                   (p in self._original_characters) != is_character and p.is_alive()]
        # Enemies at 0 HP that will get back up unless burned (e.g. a troll hit by fire or acid)
        downed_regenerators = [p for p in self._regenerators if
                               (p in self._original_characters) != is_character and self._will_regenerate(p)]

        state = {
            'allies': allies,
            'enemies': enemies,
            'downed_regenerators': downed_regenerators,
            'round': self.current_round
        }
        if self.battlefield is not None:
            state['battlefield'] = self.battlefield
        return state

    # Arena turns

    def _take_turn(self, participant: Any, action_plan: Dict[str, Any]) -> Dict[str, Any]:
        """
        Move first if the plan says so (on an arena), then act, then move again if the plan says
        so. A bonus action (Cunning Action, Nimble Escape) can Disengage or Dash for the turn.
        Class features that take a bonus action or add to the Attack action are used here too
        (see _feature_bonus_action and _after_attack).
        """
        movement = None
        kind = action_plan.get('type')
        self._turn = self._new_turn(participant)
        bonus, feature = self._bonus_action(participant, action_plan)
        feature_bonus = None if bonus else self._feature_bonus_action(participant, action_plan)
        if not (bonus or feature_bonus):
            feature_bonus = self._spell_bonus_action(participant, action_plan)
        self._disengaged = kind == 'disengage' or bonus == 'Disengage'
        budget = 0
        if self.battlefield is not None:
            budget = self.battlefield.speed(participant) * (1 + (kind == 'dash') + (bonus == 'Dash'))
            if action_plan.get('move_to') is not None:
                movement = self._move(participant, tuple(action_plan['move_to']), budget,
                                      path=action_plan.get('path'))
        if not participant.is_alive():
            result = {
                'action': 'Move',
                'type': 'wait',
                'success': False,
                'reason': 'downed',
                'description': 'is dropped by an opportunity attack',
            }
        elif kind == 'dash':
            target = action_plan.get('target')
            result = {
                'action': 'Dash',
                'type': 'dash',
                'target': getattr(target, 'name', '') if target is not None else '',
                'description': 'Dashes' + (f" toward {target.name}" if target is not None else ''),
            }
        elif kind == 'disengage':
            result = {'action': 'Disengage', 'type': 'disengage', 'description': 'Disengages'}
        else:
            result = self._execute_action(participant, action_plan)
            if kind == 'attack':
                result = self._after_attack(participant, action_plan, result, bonus_free=not (bonus or feature_bonus))
        if movement:
            result['movement'] = movement
        if bonus:
            result['bonus_action'] = {'action': bonus, 'feature': feature}
        if self.battlefield is not None and action_plan.get('move_after') is not None and participant.is_alive():
            used = movement['feet'] if movement else 0
            after = self._move(participant, tuple(action_plan['move_after']), budget - used,
                               path=action_plan.get('path_after'))
            if after:
                result['movement_after'] = after
        self._disengaged = False
        if self._turn.get('features'):
            result['features'] = self._turn['features']
        self._turn = {}
        return result

    @staticmethod
    def _new_turn(participant: Any) -> Dict[str, Any]:
        return {'in_turn': True,
                'sneak': participant.sneak_attack_dice() if hasattr(participant, 'sneak_attack_dice') else None}

    def _feature_bonus_action(self, participant: Any, plan: Dict[str, Any]) -> Optional[str]:
        """
        A class feature's bonus action at the start of the turn: a barbarian rages before a melee
        attack, and a fighter below half its hit points uses Second Wind. Returns the feature used.
        """
        if participant not in self._original_characters:
            return None
        action = plan.get('action')
        if plan.get('type') == 'attack' and feature_rules.is_melee_weapon(action) and feature_rules.can_rage(participant):
            feature_rules.start_rage(participant)
            self._note_feature('Rage')
            return 'Rage'
        if feature_rules.wants_second_wind(participant):
            healed = feature_rules.second_wind(participant)['healing']
            self._note_feature(f"Second Wind: regains {healed} HP")
            return 'Second Wind'
        return None

    def _after_attack(self, participant: Any, plan: Dict[str, Any], result: Dict[str, Any],
                      bonus_free: bool) -> Dict[str, Any]:
        """
        After a character's Attack action: Action Surge for a second one (the first time the
        fighter attacks), then a monk's bonus unarmed strike, or two with Flurry of Blows.
        """
        action, target = plan.get('action'), plan.get('target')
        if not self._is_character_weapon_attack(participant, action, target) or result.get('reason') or \
                not participant.is_alive() or self.is_combat_over():
            return result
        parts = [result]
        if feature_rules.resource(participant, 'action_surge') > 0:
            feature_rules.spend(participant, 'action_surge')
            self._note_feature('Action Surge')
            parts.append(self._execute_weapon_attacks(participant, action, target, first_where_aimed=False))
        strike = feature_rules.martial_arts_strike(participant)
        if bonus_free and strike is not None and feature_rules.allows_martial_arts(action) and not self.is_combat_over():
            count = feature_rules.flurry_strikes(participant)
            if count == 2:
                feature_rules.spend(participant, 'ki')
            self._note_feature('Flurry of Blows (1 ki)' if count == 2 else 'Martial Arts: bonus unarmed strike')
            parts.append(self._execute_weapon_attacks(participant, strike, target, count=count, first_where_aimed=False))
        attacks = [a for part in parts if not part.get('reason') for a in (part.get('attacks') or [part])]
        return self._combine_attacks(action, attacks) if len(parts) > 1 else result

    def _spell_bonus_action(self, participant: Any, plan: Dict[str, Any]) -> Optional[str]:
        """
        A spell's bonus action at the start of the turn, logged on its own: Spiritual Weapon's
        attack, or casting Spiritual Weapon, Hunter's Mark (or moving it) or a paladin's Magic
        Weapon, Shield of Faith or Divine Favor. A creature casting a spell with its action can only
        use its bonus action on a cantrip, so it casts none then, and none if its action is a
        bonus-action spell (Healing Word). Returns the spell used.
        """
        spells = getattr(participant, 'spells', None)
        if participant not in self._original_characters or not isinstance(spells, dict):
            return None
        planned = plan.get('spell') if plan.get('type') == 'cast_spell' else None
        if planned is not None and getattr(planned.spell, 'bonus_action', False):
            return None
        enemies = [e for e in self._build_combat_state(participant)['enemies'] if not is_spellbound(e)]
        target = plan.get('target')
        target = target if target in enemies else None
        if spell_effects.has_spiritual_weapon(participant):
            choice = self._spell_target(participant, spells.get('Spiritual Weapon'), target, enemies)
            if choice is None:
                return None
            return self._cast_bonus(participant, 'Spiritual Weapon', choice,
                                    lambda: spell_effects.spiritual_weapon_attack(participant, choice))
        if planned is not None and planned.spell.level > 0:
            return None
        attacking = plan.get('type') == 'attack' and target is not None
        holding = concentration.concentrating_on(participant)
        if holding == "Hunter's Mark" and attacking and spell_effects.marked_by(participant, enemies) is None:
            return self._cast_spell_bonus(participant, spells["Hunter's Mark"], target, free=True)
        choice = self._spell_target(participant, spells.get('Spiritual Weapon'), target, enemies)
        if choice is not None and lowest_slot(participant, 2):
            return self._cast_spell_bonus(participant, spells['Spiritual Weapon'], choice)
        if holding or not attacking:
            return None
        if "Hunter's Mark" in spells and lowest_slot(participant, 1) and \
                self._spell_target(participant, spells["Hunter's Mark"], target, [target]) is not None:
            return self._cast_spell_bonus(participant, spells["Hunter's Mark"], target)
        if not feature_rules.is_melee_weapon(plan.get('action')):
            return None
        slots = sum(getattr(participant, 'spell_slots_remaining', {}).values())
        if 'Magic Weapon' in spells and lowest_slot(participant, 2) and any(
                plan['action'].damage_type in [str(t).lower() for t in getattr(e, 'damage_resistances', [])]
                for e in enemies) and not plan['action'].magical:
            return self._cast_spell_bonus(participant, spells['Magic Weapon'], participant)
        for name in ('Shield of Faith', 'Divine Favor'):
            if name in spells and slots >= 3 and lowest_slot(participant, 1):
                return self._cast_spell_bonus(participant, spells[name], participant)
        return None

    def _spell_target(self, participant: Any, spell: Any, target: Any, enemies: List[Any]) -> Any:
        """The planned target if the spell reaches it, otherwise the nearest enemy it reaches, or None."""
        if spell is None:
            return None
        options = [target] + [e for e in enemies if e is not target] if target is not None else list(enemies)
        if self.battlefield is None:
            return options[0] if options else None
        in_range = [e for e in options if self.battlefield.spell_situation(participant, e, spell).in_range]
        if target in in_range:
            return target
        return min(in_range, key=lambda e: self.battlefield.distance(participant, e)) if in_range else None

    def _cast_spell_bonus(self, participant: Any, spell: Any, target: Any, free: bool = False) -> str:
        action = SpellAction(spell, spell_slot_level=None if free else lowest_slot(participant, spell.level), free=free)
        return self._cast_bonus(participant, spell.name, target, lambda: action.execute(participant, target))

    def _cast_bonus(self, participant: Any, name: str, target: Any, cast: Any) -> str:
        """Carry out a bonus-action spell and log it before the turn's action."""
        hp_before = {c: c.hp for c in self._regenerators}
        result = cast()
        result.update({'action': f"Cast {name}", 'spell': name, 'type': 'spell',
                       'target': getattr(target, 'name', str(target)), 'bonus_action_spell': True})
        self._note_regeneration_damage(hp_before, result)
        if result.get('damage', 0) > 0:
            self._alive_participants_cache = None
        self.logger.log_action(participant, result, self.current_round)
        self._log_pending_entries()
        return name

    @staticmethod
    def _bonus_action(participant: Any, plan: Dict[str, Any]) -> Any:
        """The bonus action the plan asks for, if the participant has a feature allowing it:
        (action, feature) or (None, None)."""
        wanted = plan.get('bonus_action')
        feature = {'Disengage': bonus_disengage, 'Dash': bonus_dash}.get(wanted, lambda c: None)(participant)
        return (wanted, feature) if feature else (None, None)

    def _move(self, participant: Any, destination: Any, budget: int,
              path: Optional[List[Any]] = None) -> Optional[Dict[str, Any]]:
        """
        Move if the participant's movement allows it, along the planned path if it's still clear,
        otherwise the cheapest one. Leaving an enemy's reach provokes an opportunity attack
        (unless the participant Disengaged); one that drops it ends the move there.
        """
        bf = self.battlefield
        start = bf.position(participant)
        if destination == start:
            return None
        try:
            route = bf.route(participant, destination, budget,
                             path=[tuple(step) for step in path] if path else None)
        except ValueError as e:
            logger.warning(f"Move refused: {e}")
            return None
        stop = len(route) - 1
        provoked = []
        if not self._disengaged:
            for step, enemy in bf.provoked(participant, route):
                if not bf.can_react(enemy):
                    continue
                bf.set_position(participant, route[step])
                if self._opportunity_attack(enemy, participant):
                    provoked.append(enemy.name)
                if not participant.is_alive():
                    stop = bf.last_stop(participant, route, step)
                    break
        bf.set_position(participant, route[stop])
        feet = bf.path_cost(participant, route[:stop + 1])
        if not feet and not provoked:
            return None
        movement = {'from': list(start), 'to': list(route[stop]), 'feet': feet}
        if provoked:
            movement['provoked'] = provoked
        if stop < len(route) - 1:
            movement['stopped'] = True
        return movement

    def _opportunity_attack(self, attacker: Any, target: Any) -> bool:
        """
        The attacker uses its reaction for one melee attack on the target (its best one that
        reaches), which is logged as the attacker's. Returns False if no attack reaches.
        """
        choices = []
        for action in melee_attacks(attacker):
            notes: Dict[str, Any] = {}
            options = self._attack_options(attacker, target, action, notes)
            if options is not None and notes.get('distance', 0) <= action.reach:
                choices.append((action, options, notes))
        if not choices:
            return False
        action, options, notes = max(choices, key=lambda c: (_average_damage(c[0]), c[0].hit_bonus(attacker)))
        self.battlefield.reacted.add(attacker)
        hp_before = {c: c.hp for c in self._regenerators}
        if self._is_character_weapon_attack(attacker, action, target):
            options.pop('advantage', None)  # Pack Tactics is a monster trait
        result = self._attack(attacker, action, target, options)
        result.update(notes)
        sneak_dice = attacker.sneak_attack_dice() if hasattr(attacker, 'sneak_attack_dice') else None
        if sneak_dice and self._can_sneak_attack(attacker, action, result, target):
            self._add_sneak_attack(result, target, sneak_dice)
        result['reaction'] = 'Opportunity Attack'
        if result.get('damage', 0) > 0:
            self._alive_participants_cache = None
        self._note_regeneration_damage(hp_before, result)
        self.logger.log_action(attacker, result, self.current_round)
        self._log_pending_entries()
        return True

    def _attack(self, attacker: Any, action: Any, target: Any, options: Dict[str, Any]) -> Dict[str, Any]:
        """
        One attack by a monster (or an opportunity attack). A rogue it hits can use Uncanny Dodge,
        its reaction, to halve the damage. Against a caster with Mirror Image, it may target a
        duplicate instead.
        """
        decoy = None if isinstance(target, list) else spell_effects.mirror_image_decoy(target)
        if decoy is not None:
            result = action.execute(attacker, decoy, **options)
            left = spell_effects.mirror_image_hit(target) if result.get('hit') else None
            result.update({'target': target.name, 'damage': 0, 'mirror_image': True})
            result.setdefault('features', []).append(
                f"Mirror Image: the attack {'destroys' if left is not None else 'misses'} a duplicate"
                + (f" ({left} left)" if left is not None else ''))
            return result
        hp_before = getattr(target, 'hp', None)
        result = action.execute(attacker, target, **options)
        damage = result.get('damage', 0)
        if (not isinstance(target, list) and damage > 0 and result.get('hit')
                and feature_rules.has_feature(target, 'Uncanny Dodge') and self._can_react(target)):
            self._use_reaction(target)
            halved = damage // 2
            target.hp = max(0, hp_before - halved)
            result['damage'] = halved
            result['uncanny_dodge'] = damage - halved
            result.setdefault('features', []).append(f"{target.name} uses Uncanny Dodge: halves the damage")
        return result

    def _can_react(self, creature: Any) -> bool:
        if self.battlefield is not None:
            return self.battlefield.can_react(creature)
        return creature.is_alive() and not is_incapacitated(creature) and creature not in self._reacted

    def _use_reaction(self, creature: Any) -> None:
        if self.battlefield is not None:
            self.battlefield.reacted.add(creature)
        else:
            self._reacted.add(creature)

    def _attack_options(self, participant: Any, target: Any, action: Any,
                        result_notes: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
        """
        Keyword arguments for AttackAction.execute: Pack Tactics advantage, and on an arena,
        disadvantage from long range or an adjacent enemy and whether the attacker is within
        5 ft (paralysis crits). Returns None if the target is out of reach and range. Distance
        and reasons for disadvantage are added to result_notes.
        """
        if self.battlefield is None:
            return {'advantage': self._pack_tactics(participant)}
        if isinstance(target, list):
            return {}
        situation = self.battlefield.attack_situation(participant, target, action)
        if result_notes is not None:
            self._note_situation(result_notes, situation)
        if not situation.in_range:
            return None
        options = {'advantage': self._pack_tactics(participant, target),
                   'disadvantage': situation.disadvantage,
                   'within_5ft': situation.distance <= SQUARE_FEET}
        if situation.ac_bonus:
            options['ac_bonus'] = situation.ac_bonus
        return options

    @staticmethod
    def _note_situation(notes: Dict[str, Any], situation: Any) -> None:
        """Distance, reasons for disadvantage and the target's cover, for the log."""
        notes['distance'] = situation.distance
        if situation.disadvantage_reasons:
            notes['disadvantage_reasons'] = situation.disadvantage_reasons
        if situation.cover != COVER_NONE:
            notes['cover'] = situation.cover

    @staticmethod
    def _out_of_range(name: str, target: Any, distance: Optional[int], cover: str = COVER_NONE) -> Dict[str, Any]:
        target_name = getattr(target, 'name', str(target))
        if cover == COVER_TOTAL:
            description = f"can't see {target_name} (total cover)"
        else:
            description = f"can't reach {target_name}" + (f" ({distance} ft away)" if distance is not None else '')
        result = {
            'action': name,
            'type': 'wait',
            'target': target_name,
            'success': False,
            'reason': 'out of range',
            'distance': distance,
            'description': description,
        }
        if cover != COVER_NONE:
            result['cover'] = cover
        return result

    def _execute_action(self, participant: Any, action_plan: Dict[str, Any]) -> Dict[str, Any]:
        """Execute action with optimized result handling."""
        action_type = action_plan['type']
        
        if action_type == 'attack':
            action = action_plan['action']
            target = action_plan['target']
            if getattr(action, 'recharge', None):
                if not action.ready:
                    return {'action': action.name, 'type': 'wait', 'success': False,
                            'reason': 'not recharged', 'description': f"{action.name} hasn't recharged"}
                action.ready = False
            if self.battlefield is not None and area_of(action) is not None:
                result = self._execute_area(participant, action, action_plan,
                                            lambda targets, bonuses: action.execute(participant, targets,
                                                                                    save_bonuses=bonuses))
                if result.get('reason') == 'no one in the area' and getattr(action, 'recharge', None):
                    action.ready = True
            elif self._is_character_weapon_attack(participant, action, target):
                result = self._execute_weapon_attacks(participant, action, target)
            elif isinstance(action, AttackAction):
                notes: Dict[str, Any] = {}
                options = self._attack_options(participant, target, action, notes)
                if options is None:
                    return self._out_of_range(action.name, target, notes.get('distance'), notes.get('cover', COVER_NONE))
                result = self._attack(participant, action, target, options)
                result.update(notes)
            else:
                result = self._attack(participant, action, target, {})
            # Clear alive cache after damage-dealing action
            # Check both 'damage' (single-target) and 'total_damage' (AoE like dragon breath)
            damage = result.get('total_damage', result.get('damage', 0))
            if damage > 0:
                self._alive_participants_cache = None
            return result
        elif action_type == 'cast_spell':
            spell = action_plan['spell']
            target = action_plan['target']
            notes = {}
            options: Dict[str, Any] = {}
            if self.battlefield is not None and area_of(spell) is not None:
                # No slot is spent if the area would catch no one
                result = self._execute_area(participant, spell, action_plan,
                                            lambda targets, bonuses: spell.execute(participant, targets,
                                                                                   save_bonuses=bonuses))
                if result.get('total_damage', result.get('damage', 0)) > 0:
                    self._alive_participants_cache = None
                return result
            if self.battlefield is not None and not getattr(spell.spell, 'area_effect', False):
                if isinstance(target, list):
                    target = self.battlefield.spell_targets_in_range(participant, target, spell.spell)
                    if not target:
                        return self._out_of_range(spell.name, action_plan['target'][0], None)
                    target = target if len(target) > 1 else target[0]
                else:
                    situation = self.battlefield.spell_situation(participant, target, spell.spell)
                    if not situation.in_range:
                        return self._out_of_range(spell.name, target, situation.distance, situation.cover)
                    self._note_situation(notes, situation)
                    if situation.disadvantage:
                        options['disadvantage'] = True
                    if situation.ac_bonus and not ignores_cover(spell.spell):
                        if getattr(spell.spell, 'is_attack_spell', False):
                            options['ac_bonus'] = situation.ac_bonus
                        elif getattr(spell.spell, 'save_type', None) == 'dex':
                            options['save_bonus'] = situation.ac_bonus
                    if ignores_cover(spell.spell):
                        notes.pop('cover', None)
            if not isinstance(target, list) and spell.spell.projectile_count(
                    getattr(participant, 'level', 1), spell.spell_slot_level) > 1:
                options['other_targets'] = self._projectile_targets(participant, spell.spell, target)
            result = spell.execute(participant, target, **options)
            result.update(notes)
            # Clear alive cache after spell action
            # Check both 'damage' (single-target) and 'total_damage' (AoE)
            damage = result.get('total_damage', result.get('damage', 0))
            healing = result.get('healing', 0)
            if damage > 0 or healing > 0:
                self._alive_participants_cache = None
            return result
        elif action_type == 'special':
            # Handle special actions
            action = action_plan.get('action')
            target = action_plan.get('target')
            action_name = getattr(action, 'name', 'Unknown Action')

            # Check if this is a multiattack
            if action_name.lower() == 'multiattack' and hasattr(participant, 'actions'):
                # Execute multiattack: perform multiple individual attacks
                result = self._execute_multiattack(participant, target, action)
                # Clear alive cache after damage-dealing action
                if result.get('total_damage', 0) > 0:
                    self._alive_participants_cache = None
                return result
            else:
                # Other special actions (not yet implemented)
                result = {'action': action_name, 'target': target, 'type': 'special'}
                return result
        elif action_type == 'turn_undead':
            undead = feature_rules.turnable(action_plan.get('target') or [])
            if self.battlefield is not None:
                undead = [u for u in undead
                          if self.battlefield.distance(participant, u) <= feature_rules.TURN_UNDEAD_RANGE_FEET]
            if not undead or not feature_rules.can_turn_undead(participant):
                return {'action': 'Turn Undead', 'type': 'wait', 'success': False, 'reason': 'out of range',
                        'description': 'has no undead within 30 ft to turn'}
            result = feature_rules.turn_undead(participant, undead)
            if result['destroyed']:
                self._alive_participants_cache = None
            return result
        elif action_type == 'defend':
            return {
                'action': 'Defend',
                'type': 'defend',
                'description': 'Takes defensive stance'
            }
        elif action_type == 'wait':
            return {
                'action': 'Wait',
                'type': 'wait',
                'description': 'Takes no action'
            }
        else:
            # Default action
            result = {'action': 'Unknown Action', 'type': 'unknown'}
            return result

    @staticmethod
    def _is_character_weapon_attack(participant: Any, action: Any, target: Any) -> bool:
        """A party member's single-target weapon attack (not a spell entered as an action)."""
        from models.character import Character
        return (isinstance(participant, Character) and isinstance(action, AttackAction)
                and not action.area_effect and not isinstance(target, list)
                and action.name not in participant.spells)

    def _execute_weapon_attacks(self, participant: Any, action: Any, target: Any,
                                count: Optional[int] = None, first_where_aimed: bool = True) -> Dict[str, Any]:
        """
        Make every attack the character's Attack action allows (Extra Attack), moving on to
        another enemy if the target drops. Sneak Attack goes on the first eligible hit, and class
        features apply to each hit (see _weapon_attack). count overrides the number of attacks
        (a monk's bonus unarmed strikes). The first attack goes where the AI aimed it, even at a
        downed troll it means to burn, unless first_where_aimed is False.
        """
        if not self._turn.get('in_turn'):
            self._turn = self._new_turn(participant)  # called on its own, outside _take_turn
        attacks = []
        count = participant.attacks_per_action() if count is None else count
        for i in range(count):
            if (i > 0 or not first_where_aimed) and not target.is_alive():
                enemies = [e for e in self._build_combat_state(participant)['enemies'] if not is_spellbound(e)]
                if self.battlefield is not None:
                    enemies = self._enemies_in_range(participant, action, enemies)
                if not enemies:
                    break
                target = enemies[0]
            attack = self._weapon_attack(participant, action, target)
            if attack is None:
                if attacks:
                    break
                notes: Dict[str, Any] = {}
                self._attack_options(participant, target, action, notes)
                return self._out_of_range(action.name, target, notes.get('distance'), notes.get('cover', COVER_NONE))
            attacks.append(attack)
        if not attacks:
            return {'action': action.name, 'type': 'wait', 'success': False, 'reason': 'out of range',
                    'target': getattr(target, 'name', ''), 'description': 'has no one left to attack'}
        return self._combine_attacks(action, attacks)

    def _combine_attacks(self, action: Any, attacks: List[Dict[str, Any]]) -> Dict[str, Any]:
        """One result for several attacks (Extra Attack, Action Surge, Flurry of Blows)."""
        if len(attacks) == 1:
            return attacks[0]
        targets = list(dict.fromkeys(a['target'] for a in attacks))
        result = {
            'action': action.name,
            'type': 'attack',
            'weapon': action.weapon_name,
            'damage_type': action.damage_type,
            'target': ', '.join(targets),
            'hit': any(a.get('hit') for a in attacks),
            'critical': any(a.get('critical') for a in attacks),
            'damage': sum(a.get('damage', 0) for a in attacks),
            'attacks': attacks,
            'extra_attack': True,
        }
        sneak = sum(a.get('sneak_attack', 0) for a in attacks)
        if sneak:
            result['sneak_attack'] = sneak
        result.update(self._combined_position_notes(attacks))
        return result

    def _weapon_attack(self, participant: Any, action: Any, target: Any) -> Optional[Dict[str, Any]]:
        """
        One weapon attack by a character, with what its class features add: Reckless Attack's
        advantage, Sneak Attack (once a turn), Divine Smite and Stunning Strike, plus spells that
        add to weapon hits (Hunter's Mark, Divine Favor). None if the target is out of reach and range.
        """
        notes: Dict[str, Any] = {}
        if self.battlefield is None:
            options: Dict[str, Any] = {}
        else:
            options = self._attack_options(participant, target, action, notes)
            if options is None:
                return None
            options.pop('advantage', None)  # Pack Tactics is a monster trait
        if feature_rules.reckless(participant, action, notes.get('distance')):
            options['advantage'] = True
            feature_rules.be_reckless(participant)
            self._note_feature('Reckless Attack', once=True)
        attack = action.execute(participant, target, **options)
        attack.update(notes)
        if self._turn.get('sneak') and self._can_sneak_attack(participant, action, attack, target):
            self._add_sneak_attack(attack, target, self._turn['sneak'])
            self._turn['sneak'] = None  # once per turn
        for note in spell_effects.weapon_riders(participant, attack, target):
            self._note_feature(note)
        if feature_rules.is_melee_attack(action, notes.get('distance')) and attack.get('hit'):
            slot = feature_rules.wants_smite(participant, attack, target)
            if slot is not None:
                feature_rules.divine_smite(participant, attack, target, slot)
                self._note_feature(f"Divine Smite ({_ordinal(slot)}-level slot): {attack['divine_smite']['damage']} radiant")
            if feature_rules.wants_stunning_strike(participant, attack, target, self._typical_hit(participant, action)):
                feature_rules.stunning_strike(participant, attack, target)
                stunned = attack['stunning_strike']['stunned']
                self._note_feature(f"Stunning Strike: {target.name} " + ('is stunned' if stunned else 'resists'))
        if attack.get('damage', 0) > 0:
            self._alive_participants_cache = None
        return attack

    @staticmethod
    def _typical_hit(participant: Any, action: Any) -> float:
        """Average damage of one hit with the weapon, ability modifier included."""
        modifier = participant.attack_bonus(action.weapon_type) - participant.proficiency_bonus
        return _average_damage(action) + modifier

    def _note_feature(self, note: str, once: bool = False) -> None:
        """A class feature used this turn, for the log (see _take_turn); once: only note it once."""
        notes = self._turn.setdefault('features', [])
        if not (once and note in notes):
            notes.append(note)

    @staticmethod
    def _combined_position_notes(attacks: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Distance of the first attack and every reason for disadvantage, for a set of attacks."""
        notes: Dict[str, Any] = {}
        if attacks and attacks[0].get('distance') is not None:
            notes['distance'] = attacks[0]['distance']
        if attacks and attacks[0].get('cover'):
            notes['cover'] = attacks[0]['cover']
        reasons = list(dict.fromkeys(r for a in attacks for r in a.get('disadvantage_reasons', [])))
        if reasons:
            notes['disadvantage_reasons'] = reasons
        return notes

    def _projectile_targets(self, participant: Any, spell: Any, target: Any) -> List[Tuple[Any, Dict[str, Any]]]:
        """
        Other enemies a spell's darts, rays or beams can go to, with each one's cover and
        disadvantage: those in range, without disadvantage and nearest first.
        """
        enemies = [e for e in self._build_combat_state(participant)['enemies'] if e is not target and e.is_alive()]
        if self.battlefield is None:
            return [(e, {}) for e in enemies]
        found = []
        for enemy in enemies:
            situation = self.battlefield.spell_situation(participant, enemy, spell)
            if not situation.in_range:
                continue
            options = {'disadvantage': situation.disadvantage}
            if spell.is_attack_spell and not ignores_cover(spell):
                options['ac_bonus'] = situation.ac_bonus
            found.append((situation.disadvantage, situation.distance, enemy, options))
        found.sort(key=lambda f: (f[0], f[1]))
        return [(enemy, options) for _, _, enemy, options in found]

    def _enemies_in_range(self, participant: Any, action: Any, enemies: List[Any]) -> List[Any]:
        """Enemies the action can reach from where the participant stands, those without disadvantage first."""
        situations = [(self.battlefield.attack_situation(participant, e, action), e) for e in enemies]
        return [e for s, e in sorted(((s, e) for s, e in situations if s.in_range),
                                     key=lambda pair: (pair[0].disadvantage, pair[0].distance))]

    def _can_sneak_attack(self, participant: Any, action: Any, attack: Dict[str, Any], target: Any = None) -> bool:
        """
        Sneak Attack needs a hit with a finesse or ranged weapon, plus advantage or an ally next to
        the target (see _has_active_ally).
        """
        if not attack.get('hit') or action.weapon_type not in ('finesse', 'ranged'):
            return False
        if attack.get('advantage'):
            return True
        if attack.get('disadvantage'):
            return False
        return self._has_active_ally(participant, target)

    @staticmethod
    def _add_sneak_attack(attack: Dict[str, Any], target: Any, dice: str) -> None:
        """Roll Sneak Attack (dice doubled on a critical hit) and apply it to the target."""
        num, die, _ = AttackAction.parse_dice(dice)
        if attack.get('critical'):
            num *= 2
        damage = apply_damage(target, sum(random.randint(1, die) for _ in range(num)), attack.get('damage_type'),
                              attack.get('critical', False))
        attack['damage'] = attack.get('damage', 0) + damage
        attack['sneak_attack'] = damage

    @staticmethod
    def _parse_multiattack(description: str, attack_actions: List[Any]) -> List[Any]:
        """The attacks a Multiattack makes; see models.multiattack.parse_multiattack."""
        return parse_multiattack(description, attack_actions)

    def _execute_multiattack(self, participant: Any, target: Any, multiattack_action: Any) -> Dict[str, Any]:
        """
        Execute a multiattack action by performing multiple individual attacks.

        Parses the multiattack description to determine which attacks to make,
        or uses common patterns (e.g., 1 Bite + 2 Claws for dragons/trolls).

        Args:
            participant: The creature performing multiattack
            target: The target(s) of the attacks
            multiattack_action: The multiattack action object

        Returns:
            Combined result dictionary with all attack results
        """
        description = getattr(multiattack_action, 'description', '').lower()
        attack_actions = [
            a for a in participant.actions
            if hasattr(a, 'action_type') and a.action_type == 'attack'
        ]

        # Map attack names to action objects
        attacks_by_name = {a.name.lower(): a for a in attack_actions}

        # Execute each attack
        attack_results = []
        total_damage = 0
        target_name = getattr(target, 'name', str(target)) if not isinstance(target, list) else ', '.join([getattr(t, 'name', str(t)) for t in target])

        if self.battlefield is None or isinstance(target, list):
            attacks_to_perform = self._parse_multiattack(description, attack_actions)
            options = {a: {'advantage': self._pack_tactics(participant)} for a in attacks_to_perform}
            notes = {}
        else:
            # On an arena, use the routine whose attacks reach the target (a wight's longbows)
            notes, options = {}, {}
            for a in attack_actions:
                options[a] = self._attack_options(participant, target, a, notes.setdefault(a, {}))
            attacks_to_perform = parse_multiattack(description, attack_actions,
                                                   usable=lambda a: options[a] is not None)
            if not attacks_to_perform:
                first = next(iter(notes.values()), {})
                return self._out_of_range('Multiattack', target, first.get('distance'), first.get('cover', COVER_NONE))

        for attack_action in attacks_to_perform:
            attack_result = self._attack(participant, attack_action, target, options[attack_action])
            attack_result.update(notes.get(attack_action, {}))
            attack_results.append(attack_result)
            total_damage += attack_result.get('damage', 0)

        # Build combined result
        result = {
            'action': 'Multiattack',
            'target': target_name,
            'type': 'special',
            'multiattack': True,
            'individual_attacks': attack_results,
            'total_damage': total_damage,
            'attacks_performed': [getattr(a, 'name', 'Unknown') for a in attacks_to_perform]
        }
        if self.battlefield is not None:
            result.update(self._combined_position_notes(attack_results))

        return result

    def is_combat_over(self) -> bool:
        """
        Check if combat is over efficiently.
        """
        # Use cached alive participants
        alive_participants = self._get_alive_participants()
        alive_set = set(alive_participants)
        all_characters_down = all(p not in alive_set for p in self._original_characters)
        all_monsters_down = all(p not in alive_set for p in self._original_monsters)
        return all_characters_down or all_monsters_down

    def get_current_participant(self) -> Optional[Any]:
        """Get current participant efficiently."""
        if not self.initiative_order:
            return None
        idx = (self.current_turn - 1) % len(self.initiative_order)
        return self.initiative_order[idx]

    def get_initiative_order(self) -> List[Any]:
        """Get initiative order (already cached)."""
        return self.initiative_order[:]

    def get_combat_log(self) -> List[Dict]:
        """Get combat log efficiently."""
        return self.logger.get_combat_log()

    def run(self, progress_callback=None) -> dict:
        """
        Optimized combat simulation with efficient progress tracking.
        """
        try:
            self.roll_initiative()
            max_rounds = 50  # Prevent infinite loops
            
            while not self.is_combat_over() and self.current_round <= max_rounds:
                participant = self.next_turn()
                
                # If no participant returned, combat is over
                if participant is None:
                    break
                
                # Update progress efficiently (only every 5 rounds)
                if progress_callback and self.current_round % 5 == 0:
                    progress = min(100, int((self.current_round / 20) * 100))
                    progress_callback({
                        'progress': progress,
                        'log': self.format_log_for_web(),
                        'done': False
                    })
                
                # Safety check for infinite loops
                if self.current_round > max_rounds:
                    break
            
            # Final callback
            if progress_callback:
                progress_callback({
                    'progress': 100,
                    'log': self.format_log_for_web(),
                    'done': True
                })
            
            # Determine winner efficiently
            alive_participants = self._get_alive_participants()
            alive_set = set(alive_participants)
            
            if all(p not in alive_set for p in self._original_characters):
                winner = 'monsters'
            elif all(p not in alive_set for p in self._original_monsters):
                winner = 'party'
            else:
                winner = 'unknown'
            
            # Calculate party HP remaining
            party_hp_remaining = 0
            for participant in self._original_characters:
                if participant in alive_set:
                    party_hp_remaining += participant.hp
            # Add party_level to result
            party_level = max((getattr(p, 'level', 1) for p in self._original_characters), default=1)
            result = {
                'winner': winner,
                'rounds': self.current_round,
                'party_hp_remaining': party_hp_remaining,
                'log': self.logger.get_combat_log(),
                'party_level': party_level
            }
            if self.battlefield is not None:
                result['arena'] = self.battlefield.arena.name
                result['start_positions'] = self.start_positions
                result['replay'] = self.replay()
            return result
            
        except Exception as e:
            log_exception(e)
            if progress_callback:
                progress_callback({
                    'progress': 100,
                    'log': self.format_log_for_web(),
                    'done': True,
                    'error': str(e)
                })
            raise SimulationError(f"Combat simulation failed: {e}")

    def format_log_for_web(self) -> list:
        """
        Optimized log formatting for web display.
        """
        lines = []
        for entry in self.logger.get_combat_log():
            if entry['type'] == 'round_start':
                lines.append(f"-- Round {entry['round']} --")
            elif entry['type'] == 'action':
                actor = entry['actor']
                result = entry['result']
                start = len(lines)
                if result.get('type') == 'dash':
                    feet = result.get('movement', {}).get('feet', 0)
                    toward = f" toward {result['target']}" if result.get('target') else ''
                    lines.append(f"{actor} dashes {feet} ft{toward}.")
                    continue
                if result.get('type') == 'disengage':
                    lines.append(f"{actor} disengages.")
                elif result.get('reason') in ('out of range', 'no one in the area', 'not recharged', 'downed'):
                    lines.append(f"{actor} {result.get('description', 'is out of range')}.")
                elif result.get('type') == 'condition':
                    lines.append(f"{actor} {result.get('description', '')}.")
                elif 'action' in result:
                    action = result['action']
                    # Log spell name if present
                    if 'spell' in result:
                        spell_name = result['spell']
                        if 'healing' in result and result['healing'] > 0:
                            lines.append(f"{actor} casts {spell_name} on {self._target_text(result)}: heals {result['healing']} HP.")
                        elif result.get('effect_text'):
                            lines.append(f"{actor} casts {spell_name}: {result['effect_text']}.")
                        elif 'damage' in result or 'total_damage' in result:
                            damage = result.get('damage', result.get('total_damage'))
                            hits = f" ({result['hits']} of {result['projectiles']} hit)" if 'hit' in result and \
                                'projectiles' in result else ''
                            lines.append(f"{actor} casts {spell_name} on {self._target_text(result)}: {damage} damage{hits}.")
                        else:
                            lines.append(f"{actor} casts {spell_name} on {self._target_text(result)}.")
                    elif 'damage' in result:
                        crit = " (critical hit)" if result.get('critical') else ""
                        line = f"{actor} uses {action} on {self._target_text(result)}: {result['damage']} damage{crit}."
                        if result.get('condition_applied'):
                            line += f" {self._target_text(result)} is {result['condition_applied'].lower()}!"
                        lines.append(line)
                    elif result.get('action') == 'Turn Undead':
                        lines.append(f"{actor} {result['description']}.")
                    elif 'total_damage' in result:
                        lines.append(f"{actor} uses {action} on {self._target_text(result)}: {result['total_damage']} damage.")
                    elif 'healing' in result:
                        lines.append(f"{actor} uses {action} on {self._target_text(result)}: heals {result['healing']} HP.")
                    else:
                        lines.append(f"{actor} uses {action}.")
                else:
                    lines.append(f"{actor} takes an action.")
                if len(lines) > start:
                    lines[start] = self._with_position_notes(lines[start], actor, result)
                    notes = feature_rules.feature_notes(result)
                    if notes:
                        lines[start] += ' ' + '; '.join(notes) + '.'

                    if result.get('reaction'):
                        lines[start] = f"{result['reaction']}: {lines[start]}"
        return lines

    @staticmethod
    def _target_text(result: Dict[str, Any]) -> str:
        target = result.get('target', '')
        return ', '.join(str(t) for t in target) if isinstance(target, list) else str(target)

    @staticmethod
    def _with_position_notes(line: str, actor: str, result: Dict[str, Any]) -> str:
        """On an arena, say how far the actor moved and the distance and penalties of the attack."""
        movement = result.get('movement')
        if movement:
            line = f"{actor} moves {movement['feet']} ft. " + line
        bonus = result.get('bonus_action')
        if bonus:
            line = f"{actor} uses {bonus['feature']} to {bonus['action']}. " + line
        if result.get('recharged'):
            line = f"{actor}'s {', '.join(result['recharged'])} recharges. " + line
        if result.get('area'):
            area = describe_area(result['area'])
            line = line[:-1] + f" ({area})." if line.endswith('.') else line + f" ({area})"
        if result.get('distance') and result.get('reason') != 'out of range':
            note = f"{result['distance']} ft"
            if result.get('cover'):
                note += f", {result['cover'].replace('_', '-')} cover"
            if result.get('disadvantage_reasons'):
                note += ", disadvantage: " + ', '.join(result['disadvantage_reasons'])
            line = line[:-1] + f" ({note})." if line.endswith('.') else line + f" ({note})"
        after = result.get('movement_after')
        if after:
            line += f" Then moves {after['feet']} ft."
        return line

    def pause(self):
        """Stub for future pause functionality."""
        pass

    def resume(self):
        """Stub for future resume functionality."""
        pass 