"""
What the AI does when one of its decisions raises an error.

In the app a creature falls back to a safe choice (Defend, Wait, a default threat) and the error is
logged with its traceback, so one bug doesn't stop a fight. The tests set RAISE_ERRORS
(tests/conftest.py) so that a bug fails the test instead of looking like a passive creature.
"""

RAISE_ERRORS = False
