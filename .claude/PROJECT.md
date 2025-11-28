# Project Setup & Reminders

## Virtual Environment

**IMPORTANT**: This project has a Python virtual environment located at `./venv`

**Always activate the virtual environment before running Python commands:**

```bash
source venv/bin/activate && python [command]
```

**Examples:**
- Running tests: `source venv/bin/activate && python -m pytest tests/`
- Running the app: `source venv/bin/activate && python app.py`
- Installing packages: `source venv/bin/activate && pip install [package]`

## Project Structure

- `models/` - Core game models (Character, Monster, Combat, Spells, Actions, Buffs)
- `ai/` - AI strategy for combat decision-making
- `controllers/` - Flask route controllers
- `data/` - JSON data files (spells, monsters, encounters)
- `tests/` - Pytest test suite
- `templates/` - Jinja2 HTML templates

## Key Features

- D&D 5e combat simulation
- Area effect spell support (Fireball, etc.)
- Multi-target buff spells (Bless targets up to 3)
- Concentration tracking for spells
- Comprehensive buff system with duration tracking
- AI-driven combat for both party and monsters

## Testing

Run all tests:
```bash
source venv/bin/activate && python -m pytest tests/ -v
```

Run specific test:
```bash
source venv/bin/activate && python -m pytest tests/test_combat.py -v
```

## Database

- SQLite database: `dnd5e_sim.db`
- Schema includes: combats, participants, encounters, encounter_monsters, sessions

## Notes

- All Python commands should use the virtual environment interpreter
- The project uses Flask for the web interface
- Combat simulation is handled by the `Combat` class in `models/combat.py`
- AI strategy is implemented in `ai/strategy.py` with separate PartyAI and MonsterAI classes
