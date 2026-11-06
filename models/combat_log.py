"""
The combat log: CombatLogger records what happens in a fight, and format_log turns its entries
into the lines of text the live view shows. (The saved log on the results page is written by
models/db.py; the two share the text for conditions, drains and healing in models/log_text.py.)
"""
from typing import Any, Dict, List, Optional
from models.arena import describe_area
from models.log_text import rider_text, target_text
from models import class_features as feature_rules


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


def format_log(entries: List[Dict[str, Any]]) -> list:
    """The combat log as lines of text, for the live view."""
    lines = []
    for entry in entries:
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
                        lines.append(f"{actor} casts {spell_name} on {target_text(result)}: heals {result['healing']} HP.")
                    elif result.get('effect_text'):
                        lines.append(f"{actor} casts {spell_name}: {result['effect_text']}.")
                    elif 'damage' in result or 'total_damage' in result:
                        damage = result.get('damage', result.get('total_damage'))
                        hits = f" ({result['hits']} of {result['projectiles']} hit)" if 'hit' in result and \
                            'projectiles' in result else ''
                        lines.append(f"{actor} casts {spell_name} on {target_text(result)}: {damage} damage{hits}.")
                    else:
                        lines.append(f"{actor} casts {spell_name} on {target_text(result)}.")
                elif 'damage' in result:
                    crit = " (critical hit)" if result.get('critical') else ""
                    line = f"{actor} uses {action} on {target_text(result)}: {result['damage']} damage{crit}."
                    lines.append(line + rider_text(actor, result))
                elif result.get('action') == 'Turn Undead':
                    lines.append(f"{actor} {result['description']}.")
                elif 'total_damage' in result:
                    lines.append(f"{actor} uses {action} on {target_text(result)}: {result['total_damage']} damage."
                                 + rider_text(actor, result))
                elif 'healing' in result:
                    lines.append(f"{actor} uses {action} on {target_text(result)}: heals {result['healing']} HP.")
                else:
                    lines.append(f"{actor} uses {action}.")
            else:
                lines.append(f"{actor} takes an action.")
            if len(lines) > start:
                lines[start] = _with_position_notes(lines[start], actor, result)
                notes = feature_rules.feature_notes(result)
                if notes:
                    lines[start] += ' ' + '; '.join(notes) + '.'

                if result.get('reaction'):
                    lines[start] = f"{result['reaction']}: {lines[start]}"
    return lines


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
    if result.get('stood_up'):
        line = f"{actor} stands up. " + line
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
