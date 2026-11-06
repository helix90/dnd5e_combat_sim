"""Statistics for the results pages."""

import math
from typing import Tuple

# z for a 95% confidence interval
Z_95 = 1.959964


def wilson_interval(
    successes: int, trials: int, z: float = Z_95
) -> Tuple[float, float]:
    """
    The Wilson score interval for a proportion, as percentages: where the true rate is likely
    to be after `successes` out of `trials` (95% likely by default). Unlike the simple
    "rate ± margin" it stays inside 0-100% and is sound for small samples and rates near 0 or
    100%. (0.0, 100.0) for no trials.
    """
    if trials <= 0:
        return 0.0, 100.0
    p = successes / trials
    denominator = 1 + z * z / trials
    centre = (p + z * z / (2 * trials)) / denominator
    margin = (
        z
        * math.sqrt(p * (1 - p) / trials + z * z / (4 * trials * trials))
        / denominator
    )
    return max(0.0, centre - margin) * 100, min(1.0, centre + margin) * 100
