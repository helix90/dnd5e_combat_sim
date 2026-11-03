"""
Arena movement for the AI.

The strategies in ai/strategy.py decide what a creature wants to do (heal this ally, cast this
cantrip, attack that enemy) without knowing where anyone is. On an arena, fit_plan turns that
into something the creature can actually do this turn:

- It picks the attack, weapon or spell and the square to use it from. Weapons are chosen by
  distance, so a goblin out of scimitar reach uses its shortbow and a Hill Giant throws rocks.
- It keeps the target the strategy chose when it can reach it this turn, and otherwise switches
  to the best target it can reach.
- Ranged attackers and casters stay out of melee and within normal range, moving as little as
  they need to.
- A creature that has to make do with a weaker attack from where it stands (a fighter's
  crossbow) attacks and then moves toward its target ('move_after').
- If nothing is in reach even after moving, the creature Dashes toward its target.
- Cover counts: the AI avoids shooting at targets behind cover (and can't target one with total
  cover), and creatures attacking from range prefer squares where they have cover themselves.
- Area effects are aimed (ai/aiming.py) to catch the most enemies and spare allies. If the best
  aim is worth less than an ordinary attack, the creature attacks instead and keeps its spell
  slot or breath weapon.
- Leaving an enemy's reach provokes an opportunity attack, so a square is worth less by the
  damage those attacks are expected to do. A creature that can Disengage as a bonus action
  (Cunning Action, Nimble Escape) does so when it moves out of reach, and a rogue can Dash as a
  bonus action to move twice as far and still attack.
"""
from typing import Any, Dict, List, Optional, Tuple

from ai.aiming import aim_area
from models.actions import AttackAction
from models.arena import COVER_AC_BONUS, COVER_NONE, COVER_TOTAL, SQUARE_FEET, Square
from models.buffs import is_paralyzed
from models.battlefield import (Battlefield, Situation, Threatened, area_of, attack_distances, bonus_dash,
                                bonus_disengage, ignores_cover, judge_attack, judge_spell, melee_attacks)
from models.multiattack import parse_multiattack
from models.spells import SpellAction

# A target the strategy chose is worth this much more than another one
PREFERRED_TARGET_WEIGHT = 1.3
# Small tie-breakers: prefer shorter moves, then squares farther from the nearest enemy
MOVE_PENALTY_PER_FT = 0.002
DISTANCE_BONUS_PER_FT = 0.0005
DISTANCE_BONUS_CAP_FT = 60
# Chance a saving-throw spell does its damage, for comparing it with attacks
SAVE_SPELL_SUCCESS = 0.6
# What standing in cover is worth to a creature attacking from range, by the cover it has against
# its nearest enemies (in the same units as expected damage)
SHELTER_VALUE = {COVER_NONE: 0.0, 'half': 0.5, 'three_quarters': 1.0, COVER_TOTAL: 1.5}
SHELTER_ENEMIES = 3
# How many of the best-looking squares are rescored with cover
RESCORED = 12
# Damage taken from an opportunity attack counts this much against damage dealt
OPPORTUNITY_WEIGHT = 1.0


def _average(dice: Optional[str]) -> float:
    try:
        num, die, mod = AttackAction.parse_dice(str(dice))
        return num * (die + 1) / 2 + mod
    except (TypeError, ValueError):
        return 0.0


def _hit_chance(bonus: int, ac: int, disadvantage: bool) -> float:
    chance = min(0.95, max(0.05, (21 + bonus - ac) / 20))
    return chance * chance if disadvantage else chance


def _max_distance(attacks: List[Any]) -> float:
    """The farthest any of these attacks reaches (no limit if one has no reach or range data)."""
    farthest = 0.0
    for attack in attacks:
        reach, attack_range = attack_distances(attack)
        if reach is None and attack_range is None:
            return float('inf')
        farthest = max(farthest, reach or 0, attack_range[1] if attack_range else 0)
    return farthest


class _Weapon:
    """A single-target attack: a weapon, natural weapon or thrown rock."""

    def __init__(self, creature: Any, action: AttackAction) -> None:
        self.action = action
        self.count = creature.attacks_per_action() if hasattr(creature, 'attacks_per_action') else 1
        self.average = _average(action.damage_dice)
        self.bonus = action.hit_bonus(creature)
        self.max_distance = _max_distance([action])

    def evaluate(self, creature: Any, target: Any, distance: int, threatened: Threatened,
                 ac_bonus: int = 0) -> Optional[float]:
        situation = judge_attack(self.action, distance, threatened)
        if not situation.in_range:
            return None
        return self.count * self.average * _hit_chance(self.bonus, getattr(target, 'ac', 10) + ac_bonus,
                                                       situation.disadvantage)

    def plan(self, target: Any) -> Dict[str, Any]:
        return {'type': 'attack', 'action': self.action, 'target': target}


class _Multiattack:
    """A monster's Multiattack, which can switch routines with distance (e.g. a wight's longbows)."""

    def __init__(self, creature: Any, action: Any) -> None:
        self.action = action
        self.attacks = [a for a in creature.actions
                        if getattr(a, 'action_type', None) == 'attack' and not getattr(a, 'area_effect', False)]
        self.max_distance = _max_distance(self.attacks)

    def evaluate(self, creature: Any, target: Any, distance: int, threatened: Threatened,
                 ac_bonus: int = 0) -> Optional[float]:
        situations: Dict[Any, Situation] = {a: judge_attack(a, distance, threatened) for a in self.attacks}
        attacks = parse_multiattack(getattr(self.action, 'description', ''), self.attacks,
                                    usable=lambda a: situations[a].in_range)
        if not attacks:
            return None
        ac = getattr(target, 'ac', 10) + ac_bonus
        return sum(_average(a.damage_dice) * _hit_chance(a.hit_bonus(creature), ac, situations[a].disadvantage)
                   for a in attacks)

    def plan(self, target: Any) -> Dict[str, Any]:
        return {'type': 'special', 'action': self.action, 'target': target}


class _Spell:
    """A single-target spell. Healing and buffs are worth the same anywhere in range."""

    def __init__(self, creature: Any, spell_action: SpellAction) -> None:
        self.spell_action = spell_action
        spell = spell_action.spell
        self.spell = spell
        self.average = _average(getattr(spell, 'damage_dice', None)) if not spell.healing else 0.0
        self.bonus = creature.spell_attack_bonus() if hasattr(creature, 'spell_attack_bonus') else 0
        range_feet = getattr(spell, 'range_feet', None)
        self.max_distance = float('inf') if range_feet is None else range_feet

    def evaluate(self, creature: Any, target: Any, distance: int, threatened: Threatened,
                 ac_bonus: int = 0) -> Optional[float]:
        situation = judge_spell(self.spell, distance, threatened)
        if not situation.in_range:
            return None
        if not self.average:
            return 1.0
        if ignores_cover(self.spell):
            ac_bonus = 0
        if self.spell.is_attack_spell:
            return self.average * _hit_chance(self.bonus, getattr(target, 'ac', 10) + ac_bonus, situation.disadvantage)
        if getattr(self.spell, 'save_type', None) == 'dex':
            return self.average * max(0.05, SAVE_SPELL_SUCCESS - 0.05 * ac_bonus)
        return self.average * SAVE_SPELL_SUCCESS

    def plan(self, target: Any) -> Dict[str, Any]:
        return {'type': 'cast_spell', 'spell': self.spell_action, 'target': target}


def _attack_options(creature: Any) -> List[Any]:
    options: List[Any] = []
    for action in getattr(creature, 'actions', []):
        if isinstance(action, AttackAction) and action.action_type == 'attack' and not action.area_effect:
            options.append(_Weapon(creature, action))
        elif getattr(action, 'action_type', None) == 'special' and getattr(action, 'name', '').lower() == 'multiattack':
            options.append(_Multiattack(creature, action))
    return options


class _Planner:
    def __init__(self, bf: Battlefield, creature: Any) -> None:
        self.bf = bf
        self.creature = creature
        self.here = bf.position(creature)
        self._squares: Optional[Dict[Square, int]] = None
        self._threatened: Dict[Square, bool] = {}
        self.size = bf.placements[creature].size
        enemies = bf.enemies_of(creature)
        self._enemy_placements = [bf.placements[e] for e in enemies]
        self._threat_placements = [bf.placements[e] for e in enemies if not is_paralyzed(e)]
        self._enemies = enemies
        self._cover: Dict[Tuple[Square, Any], str] = {}
        self._shelter: Dict[Square, float] = {}
        # Seeking cover only matters on maps with cover terrain; creatures alone move too much
        self.seeks_cover = bf.arena.has_cover
        self.speed = bf.speed(creature)
        self.can_dash = bonus_dash(creature) is not None
        self.can_disengage = bonus_disengage(creature) is not None
        self._threats: Optional[List[Tuple[Any, float]]] = None
        self._opportunity: Dict[Square, float] = {}

    def squares(self) -> Dict[Square, int]:
        """Squares the creature can move to this turn (twice as far with a bonus-action Dash)."""
        if self._squares is None:
            self._squares = self.bf.reachable(self.creature, self.speed * (2 if self.can_dash else 1))
        return self._squares

    def threats(self) -> List[Tuple[Any, float]]:
        """Enemies that would get an opportunity attack if the creature left their reach, each with
        the damage that attack is expected to do."""
        if self._threats is None:
            ac = getattr(self.creature, 'ac', 10)
            self._threats = [(enemy, max(_average(a.damage_dice) * _hit_chance(a.hit_bonus(enemy), ac, False)
                                         for a in melee_attacks(enemy)))
                             for enemy in self.bf.threats(self.creature)]
        return self._threats

    def provokes(self, square: Square) -> List[Tuple[Any, float]]:
        """The threats whose reach the creature leaves by ending its move on this square."""
        if square == self.here:
            return []
        return [(enemy, damage) for enemy, damage in self.threats()
                if not self.bf.in_reach_of(enemy, self.creature, square)]

    def opportunity_cost(self, square: Square, cost: int) -> float:
        """Expected damage from opportunity attacks for moving to this square (none if the creature
        can Disengage as a bonus action without needing that action to Dash)."""
        if square == self.here or not self.threats():
            return 0.0
        if self.can_disengage and cost <= self.speed:
            return 0.0
        if square not in self._opportunity:
            self._opportunity[square] = OPPORTUNITY_WEIGHT * sum(damage for _, damage in self.provokes(square))
        return self._opportunity[square]

    def with_move(self, plan: Dict[str, Any], square: Square) -> Dict[str, Any]:
        """Add the move to the plan, with the bonus action it needs: Dash to go beyond the creature's
        speed, otherwise Disengage if it leaves an enemy's reach and can."""
        if square == self.here:
            return plan
        plan['move_to'] = square
        cost = self.squares().get(square, 0)
        if cost > self.speed:
            plan['bonus_action'] = 'Dash'
        elif self.can_disengage and self.provokes(square):
            plan['bonus_action'] = 'Disengage'
        return plan

    def evaluate(self, option: Any, target: Any, square: Square) -> Optional[float]:
        """
        Value of an option against a target from a square, counting the target's cover (None if
        it can't reach or the target has total cover).
        """
        distance = self.distance(target, square)
        threatened = lambda: self.threatened(square)
        if option.evaluate(self.creature, target, distance, threatened) is None:
            return None
        cover = self.cover(target, square)
        if cover == COVER_TOTAL:
            return None
        return option.evaluate(self.creature, target, distance, threatened, COVER_AC_BONUS[cover])

    def cover(self, target: Any, square: Square) -> str:
        """
        Cover the target has against the creature standing on this square, from terrain. Creatures
        in the way are left out: they can't be cached, and checking them on every square the AI
        considers is too slow (attacks themselves do count them).
        """
        key = (square, target)
        if key not in self._cover:
            self._cover[key] = self.bf.cover(self.creature, target, square, creatures=False)
        return self._cover[key]

    def shelter(self, square: Square) -> float:
        """What this square's terrain cover against the nearest enemies is worth to a ranged attacker."""
        if not self.seeks_cover:
            return 0.0
        if square not in self._shelter:
            here = self.bf.placement(self.creature, square)
            nearest = sorted(self._enemies, key=lambda e: self.bf.arena.distance(here, self.bf.placements[e]))
            values = [SHELTER_VALUE[self.bf.arena.cover(self.bf.placements[enemy], here)]
                      for enemy in nearest[:SHELTER_ENEMIES]]
            self._shelter[square] = sum(values) / len(values) if values else 0.0
        return self._shelter[square]

    def distance(self, target: Any, square: Square) -> int:
        if target is self.creature:
            return 0
        return self.bf.arena.distance_at(square, self.size, self.bf.placements[target])

    def threatened(self, square: Square) -> bool:
        """Is a non-incapacitated enemy within 5 ft of this square? Remembered for the turn."""
        if square not in self._threatened:
            self._threatened[square] = any(self.bf.arena.distance_at(square, self.size, p) <= SQUARE_FEET
                                           for p in self._threat_placements)
        return self._threatened[square]

    def _nearest_enemy_bonus(self, square: Square) -> float:
        distances = [self.bf.arena.distance_at(square, self.size, p) for p in self._enemy_placements]
        return DISTANCE_BONUS_PER_FT * min(min(distances, default=0), DISTANCE_BONUS_CAP_FT)

    def best(self, options: List[Any], targets: List[Any],
             preferred: Optional[Any]) -> Optional[Tuple[Any, Any, Square]]:
        """
        The best (option, target, square) reachable this turn, or None. A first pass scores every
        square without cover; then the most promising are rescored with the target's cover and,
        for attacks from range, the cover the square gives the attacker.
        """
        # Leave out options that can't reach a target even after a full move
        speed = self.speed * (2 if self.can_dash else 1)
        pairs = [(t, [o for o in options if self.distance(t, self.here) <= o.max_distance + speed])
                 for t in targets]
        pairs = [(t, opts) for t, opts in pairs if opts]
        if not pairs:
            return None
        weights = {t: PREFERRED_TARGET_WEIGHT if t is preferred else 1.0 for t, _ in pairs}
        candidates = []
        for square, cost in self.squares().items():
            threatened = lambda square=square: self.threatened(square)
            for target, target_options in pairs:
                distance = self.distance(target, square)
                found = None
                for option in target_options:
                    value = option.evaluate(self.creature, target, distance, threatened)
                    if value is not None and (found is None or value > found[0]):
                        found = (value, option)
                if found:
                    rough = found[0] * weights[target] - MOVE_PENALTY_PER_FT * cost - \
                        self.opportunity_cost(square, cost)
                    candidates.append((rough, cost, square, target, found[1]))
        candidates.sort(key=lambda c: (-c[0], c[1], c[2]))
        # Cover only lowers a value, and only shelter can raise it by more than the small
        # distance tie-breaker, so stop once no later candidate can win by more than that
        # (or after the most promising RESCORED squares that can see their target)
        top_bonus = max(SHELTER_VALUE.values()) if self.seeks_cover else 0.0
        best_score, best, rescored = None, None, 0
        for rough, cost, square, target, option in candidates:
            if best_score is not None and (rough + top_bonus < best_score or rescored >= RESCORED):
                break
            value = self.evaluate(option, target, square)
            if value is None:
                continue
            rescored += 1
            score = value * weights[target] - MOVE_PENALTY_PER_FT * cost + self._nearest_enemy_bonus(square) - \
                self.opportunity_cost(square, cost)
            if self.distance(target, square) > SQUARE_FEET:
                score += self.shelter(square)
            if best_score is None or score > best_score:
                best_score, best = score, (option, target, square)
        return best

    def stay_put(self, options: List[Any], target: Any) -> Optional[Any]:
        """
        The best option that already works on the target from here without disadvantage or cover,
        if it's the best the creature could do against that target from anywhere (and, attacking
        from range on a map with cover, the creature is already in total cover from its nearest
        enemies). Saves searching for a square on most turns once the fight is joined.
        """
        here, ideal = [], []
        for option in options:
            value = self.evaluate(option, target, self.here)
            if value is not None:
                here.append((value, option))
            ideal.append(self._ideal_value(option, target))
        if not here:
            return None
        value, option = max(here, key=lambda pair: pair[0])
        if value < max(ideal) - 1e-9:
            return None
        # Attacking from range out in the open: look for a square with cover first
        if self.seeks_cover and self.distance(target, self.here) > SQUARE_FEET and \
                not self.shelter(self.here):
            return None
        return option

    def _ideal_value(self, option: Any, target: Any) -> float:
        """Value of an option against a target with no distance penalties."""
        if isinstance(option, _Weapon):
            return option.count * option.average * _hit_chance(option.bonus, getattr(target, 'ac', 10), False)
        if isinstance(option, _Multiattack):
            ac = getattr(target, 'ac', 10)
            routine = parse_multiattack(getattr(option.action, 'description', ''), option.attacks)
            return sum(_average(a.damage_dice) * _hit_chance(a.hit_bonus(self.creature), ac, False) for a in routine)
        if isinstance(option, _Spell):
            if not option.average:
                return 1.0
            if option.spell.is_attack_spell:
                return option.average * _hit_chance(option.bonus, getattr(target, 'ac', 10), False)
            return option.average * SAVE_SPELL_SUCCESS
        return 0.0

    def choose(self, options: List[Any], preferred: Optional[Any],
               others: List[Any]) -> Optional[Dict[str, Any]]:
        """Plan for the preferred target if it can be reached this turn, otherwise another target."""
        if not options:
            return None
        if preferred is not None:
            option = self.stay_put(options, preferred)
            if option is not None:
                return option.plan(preferred)
            found = self.best(options, [preferred], preferred)
            if found and self.opportunity_cost(found[2], self.squares().get(found[2], 0)):
                # Getting there provokes: another target may be worth more after all
                rest = [t for t in others if t is not preferred]
                found = self.best(options, [preferred] + rest, preferred) if rest else found
            if found:
                option, target, square = found
                if square == self.here:
                    return self._advance_after(option.plan(target), option, options, target)
                return self.with_move(option.plan(target), square)
        others = sorted((t for t in others if t is not preferred), key=lambda t: self.bf.distance(self.creature, t))
        found = self.best(options, others, None) if others else None
        if found:
            option, target, square = found
            if square == self.here:
                return self._advance_after(option.plan(target), option, options, target)
            return self.with_move(option.plan(target), square)
        return None

    def _advance_after(self, plan: Dict[str, Any], used: Any, options: List[Any], target: Any) -> Dict[str, Any]:
        """
        A creature that had to make do with a weaker attack from where it stands (a fighter's
        crossbow, a giant's rock) then moves toward the target, so it can use its best attack
        next turn. Creatures whose ranged attack is as good as their melee one hold their ground.
        """
        ideal = {option: self._ideal_value(option, target) for option in options}
        best = max(options, key=lambda option: ideal[option])
        if ideal[best] <= ideal.get(used, 0.0) + 1e-9:
            return plan
        route = self._route_toward(target, [best], self.speed)
        if route is not None:
            plan['move_after'] = route[-1]
            plan['path_after'] = route
            if self.can_disengage and self.provokes(route[-1]):
                plan['bonus_action'] = 'Disengage'
        return plan

    def dash_toward(self, target: Any, options: List[Any]) -> Optional[Dict[str, Any]]:
        """
        Dash along the shortest route to a square from which an option reaches the target (with
        Cunning Action, Dash twice).
        """
        route = self._route_toward(target, options, (3 if self.can_dash else 2) * self.speed)
        if route is None:
            return None
        plan = {'type': 'dash', 'move_to': route[-1], 'path': route, 'target': target}
        if self.bf.path_cost(self.creature, route) > 2 * self.speed:
            plan['bonus_action'] = 'Dash'
        elif self.can_disengage and self.provokes(route[-1]):
            plan['bonus_action'] = 'Disengage'
        return plan

    def _route_toward(self, target: Any, options: List[Any], budget: float) -> Optional[List[Square]]:
        """
        The route, within the budget, to the farthest square the creature can end on along the
        shortest route to a square from which one of the options reaches the target. None if it
        can't move closer.
        """
        path = self.bf.path_to_nearest(
            self.creature, lambda square: any(self.evaluate(option, target, square) is not None for option in options))
        if not path:
            return None
        stop = 0
        for i in range(1, len(path)):
            if self.bf.path_cost(self.creature, path[:i + 1]) > budget:
                break
            if self.bf.can_end_at(self.creature, path[i]):
                stop = i
        return path[:stop + 1] if stop else None


def _enemies(bf: Battlefield, creature: Any) -> List[Any]:
    return [e for e in bf.enemies_of(creature) if e.is_alive()]


def _fit_attack(bf: Battlefield, creature: Any, plan: Dict[str, Any]) -> Dict[str, Any]:
    planner = _Planner(bf, creature)
    target = plan.get('target')
    enemies = _enemies(bf, creature)
    if target is not None and not target.is_alive():
        # A downed regenerator: only the attack the strategy picked (e.g. fire) finishes it
        options = [_Weapon(creature, plan['action'])] if isinstance(plan.get('action'), AttackAction) else []
        fitted = planner.choose(options, target, [])
        if fitted:
            return fitted
        target = None
    options = _attack_options(creature)
    fitted = planner.choose(options, target, enemies)
    if fitted:
        return fitted
    goal = target if target is not None and target.is_alive() else (
        min(enemies, key=lambda e: bf.distance(creature, e)) if enemies else None)
    if goal is not None and options:
        dash = planner.dash_toward(goal, options)
        if dash:
            return dash
    return {'type': 'defend'}


def _cantrip_options(creature: Any) -> List[Any]:
    """Damaging cantrips, to fall back on instead of an area spell that isn't worth its slot."""
    return [_Spell(creature, SpellAction(spell)) for spell in getattr(creature, 'spells', {}).values()
            if spell.level == 0 and spell.damage_dice and not spell.healing and not spell.area_effect]


def _fit_area(bf: Battlefield, creature: Any, plan: Dict[str, Any]) -> Dict[str, Any]:
    """
    Aim an area action or spell. If the best aim does less than the creature's best ordinary
    attack or cantrip would against any enemy, use that instead (keeping the slot or breath).
    """
    action = plan.get('spell') or plan.get('action')
    planner = _Planner(bf, creature)
    aim = aim_area(bf, creature, action, planner.squares(),
                   penalty=lambda square: planner.opportunity_cost(square, planner.squares().get(square, 0)))
    options = _attack_options(creature) + _cantrip_options(creature)
    enemies = _enemies(bf, creature)
    alternative = max((planner._ideal_value(option, enemy) for option in options for enemy in enemies), default=0.0)
    if aim is None or aim.value <= alternative:
        fitted = planner.choose(options, None, enemies)
        if fitted:
            return fitted
        return _fit_attack(bf, creature, {'type': 'attack', 'target': None})
    return planner.with_move(dict(plan, **aim.plan_fields()), aim.square)


def _fit_spell(bf: Battlefield, creature: Any, plan: Dict[str, Any]) -> Dict[str, Any]:
    spell_action: SpellAction = plan['spell']
    spell = spell_action.spell
    target = plan['target']
    planner = _Planner(bf, creature)

    if area_of(spell) is not None:
        return _fit_area(bf, creature, plan)
    if isinstance(target, list):
        # Several targets (e.g. Bless): stand where the most of them are in range
        best = None
        for square, cost in sorted(planner.squares().items()):
            in_range = bf.spell_targets_in_range(creature, target, spell, square)
            if in_range and (best is None or (len(in_range), -cost) > (len(best[1]), -best[2])):
                best = (square, in_range, cost)
        if best is None:
            return _fit_attack(bf, creature, {'type': 'attack', 'target': None})
        square, in_range, _ = best
        fitted = dict(plan, target=in_range if len(in_range) > 1 else in_range[0])
        return planner.with_move(fitted, square)

    if target is creature:
        return plan
    option = _Spell(creature, spell_action)
    enemies = _enemies(bf, creature)
    if spell.healing or getattr(spell, 'is_buff_spell', False):
        fitted = planner.choose([option], target, [])
        if fitted:
            return fitted
        if spell.healing:
            dash = planner.dash_toward(target, [option])
            if dash:
                return dash
        return _fit_attack(bf, creature, {'type': 'attack', 'target': None})
    fitted = planner.choose([option], target, enemies)
    if fitted:
        return fitted
    return _fit_attack(bf, creature, {'type': 'attack', 'target': target})


def fit_plan(creature: Any, plan: Dict[str, Any], combat_state: Dict[str, Any]) -> Dict[str, Any]:
    """
    Turn the strategy's plan into one the creature can carry out on the battlefield, adding a
    'move_to' square when it needs to move first and a 'move_after' square when it should
    advance after acting, and aiming area effects ('aim'). Plans that don't involve a target
    (defend, wait) are returned unchanged.
    """
    bf: Optional[Battlefield] = combat_state.get('battlefield')
    if bf is None or creature not in bf.placements:
        return plan
    kind = plan.get('type')
    action = plan.get('action')
    if kind in ('attack', 'special') and area_of(action) is not None:
        return _fit_area(bf, creature, plan)
    if kind == 'attack' and not getattr(action, 'area_effect', False) and not isinstance(plan.get('target'), list):
        return _fit_attack(bf, creature, plan)
    if kind == 'special' and getattr(action, 'name', '').lower() == 'multiattack':
        return _fit_attack(bf, creature, plan)
    if kind == 'cast_spell':
        return _fit_spell(bf, creature, plan)
    return plan
