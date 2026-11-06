"""
Combat log text shared by the live log (Combat.format_log_for_web) and the log saved for the
results page (DatabaseManager._convert_combat_log_format), so both say the same thing.
"""

from typing import Any, Dict

# How the log says an attack's condition took hold, e.g. "Calyra is knocked prone!"
CONDITION_TEXT = {
    "Paralyzed": "is paralyzed",
    "Prone": "is knocked prone",
    "Infernal Wound": "has an infernal wound",
    "Mummy Rot": "is cursed with mummy rot",
}


def target_text(result: Dict[str, Any]) -> str:
    """The target(s) of a result, as text."""
    target = result.get("target", "")
    return (
        ", ".join(str(t) for t in target) if isinstance(target, list) else str(target)
    )


def rider_text(actor: str, result: Dict[str, Any]) -> str:
    """
    What a hit did besides damage, as sentences that follow the damage: a condition, a drained
    hit point maximum, the attacker healing. A Multiattack's attacks each contribute theirs.
    Empty if there was nothing.
    """
    text = "".join(
        rider_text(actor, attack) for attack in result.get("individual_attacks", [])
    )
    target = target_text(result)
    if result.get("condition_applied"):
        condition = result["condition_applied"]
        text += f" {target} {CONDITION_TEXT.get(condition, 'is ' + condition.lower())}!"
    if result.get("hp_drained"):
        text += f" {target}'s hit point maximum drops by {result['hp_drained']} (to {result['target_max_hp_after']})."
    if result.get("attacker_healed"):
        text += f" {actor} regains {result['attacker_healed']} HP."
    return text
