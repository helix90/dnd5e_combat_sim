"""
What happens to a creature at the start and end of its turn in combat: regeneration, effects that
end or deal damage (Moonbeam, an infernal wound, a ghast's Stench), saves to end conditions, and
the turns of a creature that can't act normally (incapacitated, stunned, paralyzed, turned).

TurnEffects is a mixin for Combat, and uses its state: participants, battlefield, logger,
current_round and the regeneration and melee bookkeeping set up in Combat.__init__.
"""
import random
from typing import List, Dict, Any, Optional
from models.rolls import roll_saving_throw
from models.buffs import BuffManager, cannot_move, create_poisoned_condition, create_stood_up_effect, is_prone
from models.actions import AttackAction
from models.arena import SQUARE_FEET
from models.battlefield import melee_attacks
from models.damage import has_ability, regain_hp
from models import concentration, spell_effects
import logging
logger = logging.getLogger('dnd5e_combat_sim.combat')

# A ghast's Stench: the CON save a creature starting its turn next to one makes
STENCH_DC = 10


class TurnEffects:
    """Start- and end-of-turn effects, and the turns of creatures that can't act normally."""

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
                found |= TurnEffects._damage_types(value)
        elif isinstance(result, list):
            for value in result:
                found |= TurnEffects._damage_types(value)
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
            healed = regain_hp(participant, int(regen.get('hp', 0)), magical=False)
            description = f"regenerates {healed} HP" + (" and gets back up" if was_down else "")
        return {
            'action': 'Regeneration',
            'type': 'condition',
            'condition': 'regeneration',
            'target': participant.name,
            'healing': healed,
            'description': description,
        }

    @staticmethod
    def _start_of_turn_effects(participant: Any) -> None:
        """Effects that last until the creature's next turn end now (Reckless Attack)."""
        buffs = getattr(participant, 'buffs', None)
        if buffs is not None and hasattr(buffs, 'active_buffs'):
            buffs.active_buffs = [b for b in buffs.active_buffs if not b.metadata.get('until_turn_start')]

    def _end_of_turn_effects(self, participant: Any) -> None:
        """
        Stunning Strike's stun lasts until the end of the monk's next turn, and effects that last
        until the end of the creature's own next turn (Vicious Mockery) end.
        """
        buffs = getattr(participant, 'buffs', None)
        if buffs is not None and hasattr(buffs, 'active_buffs'):
            buffs.active_buffs = [b for b in buffs.active_buffs if not b.metadata.get('until_own_turn_end')]
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
        return not participant.is_alive()

    def _infernal_wound(self, participant: Any) -> bool:
        """
        A creature with an infernal wound loses hit points at the start of its turn (3d6 for each
        hit from the horned devil's tail). It's hit point loss, not damage: no resistance and no
        concentration save. Returns True if that drops it, which ends its turn.
        """
        buffs = getattr(participant, 'buffs', None)
        wound = buffs.get_condition('infernal_wound') if isinstance(buffs, BuffManager) else None
        if wound is None or not participant.is_alive():
            return False
        lost = 0
        for dice in wound.metadata.get('wound_dice', []):
            num, die, mod = AttackAction.parse_dice(dice)
            lost += sum(random.randint(1, die) for _ in range(num)) + mod
        participant.hp -= lost
        self.logger.log_action(participant, {
            'action': 'Infernal Wound', 'type': 'condition', 'condition': 'infernal_wound', 'hp_lost': lost,
            'description': f"loses {lost} HP to an infernal wound" + ('' if participant.is_alive() else ' and goes down'),
        }, self.current_round)
        return not participant.is_alive()

    def _stench(self, participant: Any) -> None:
        """
        A creature that starts its turn within 5 ft of a ghast makes a DC 10 CON save against its
        Stench, or is poisoned until the start of its next turn. On a success it's immune to that
        ghast's stench for the rest of the fight (24 hours).
        """
        if not participant.is_alive() or 'poisoned' in (getattr(participant, 'condition_immunities', None) or []):
            return
        for ghast in self.participants:
            if ghast is participant or not ghast.is_alive() or not has_ability(ghast, 'Stench') or \
                    (participant, ghast) in self._stench_immune or not self._next_to(participant, ghast):
                continue
            save = roll_saving_throw(participant, 'con', STENCH_DC)
            if save['save_success']:
                self._stench_immune.add((participant, ghast))
                description = f"holds out against {ghast.name}'s stench"
            else:
                if isinstance(participant.buffs, BuffManager) and not participant.buffs.has_condition('poisoned'):
                    participant.buffs.add_buff(create_poisoned_condition(ghast.name))
                description = f"is poisoned by {ghast.name}'s stench"
            self.logger.log_action(participant, {
                'action': 'Stench', 'type': 'condition', 'condition': 'poisoned', 'source': ghast.name,
                'save_type': 'con', 'save_dc': STENCH_DC, **save, 'description': description,
            }, self.current_round)

    def _next_to(self, a: Any, b: Any) -> bool:
        """
        Within 5 ft of each other. Without an arena, that's when either one last attacked the other
        in melee.
        """
        if self.battlefield is not None:
            return (a in self.battlefield.placements and b in self.battlefield.placements
                    and self.battlefield.distance(a, b) <= SQUARE_FEET)
        return self._melee_target.get(a) is b or self._melee_target.get(b) is a

    def _note_melee_target(self, participant: Any, plan: Dict[str, Any]) -> None:
        """Without an arena, remember whom the participant attacked in melee this turn (see _next_to)."""
        if self.battlefield is not None:
            return
        action, target = plan.get('action'), plan.get('target')
        melee = plan.get('type') in ('attack', 'special') and not isinstance(target, list) and target is not None and (
            getattr(action, 'name', '').lower() == 'multiattack'
            or (getattr(action, 'weapon_type', 'ranged') != 'ranged' and not getattr(action, 'area_effect', False)))
        if melee:
            self._melee_target[participant] = target
        else:
            self._melee_target.pop(participant, None)

    @staticmethod
    def _stand_up(participant: Any) -> bool:
        """A prone creature that can move stands up at the start of its turn, using half its speed."""
        buffs = getattr(participant, 'buffs', None)
        if not is_prone(participant) or cannot_move(participant):
            return False
        buffs.remove_buff('Prone')
        buffs.add_buff(create_stood_up_effect())
        return True

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

    def _paralyzed_turn(self, participant: Any) -> Dict[str, Any]:
        """Skip a paralyzed creature's turn and roll its end-of-turn save to end the condition."""
        condition = participant.buffs.get_condition('paralyzed')
        save_type = condition.metadata.get('save_type', 'con')
        save = roll_saving_throw(participant, save_type, condition.metadata.get('save_dc', 10),
                                 magical=bool(condition.metadata.get('magical')))
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
