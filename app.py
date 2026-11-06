"""
D&D 5e Combat Simulator Web Application

A Flask-based web application for simulating D&D 5e combat encounters
between characters and monsters.
"""

# Standard library imports
from collections import Counter
import json
import logging
import os
import re
import time
from datetime import timedelta
from typing import Dict, Any, Tuple, List, Optional
from uuid import uuid4

# Third-party imports
from flask import (
    Flask,
    Response,
    render_template,
    request,
    redirect,
    url_for,
    session,
    jsonify,
    flash,
)
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from werkzeug.exceptions import HTTPException

# Local imports
from controllers.batch_simulation_controller import BatchSimulationController
from controllers.encounter_controller import EncounterController
from controllers.results_controller import ResultsController
from controllers.simulation_controller import SimulationController
from models.arena_library import (
    DEFAULT_MAP,
    ENCOUNTER_MAP,
    arena_choices,
    get_arena,
    resolve_arena_choice,
)
from models.db import DatabaseManager
from utils.exceptions import AppError, ValidationError
from utils.logging import log_exception
from utils.party_loader import PartyLoader

# Constants - Application Configuration
DEFAULT_SECRET_KEY = "dev-secret-key"
SESSION_LIFETIME_HOURS = 24

# Constants - Rate Limiting
RATE_LIMIT_PER_DAY = "100000 per day"
RATE_LIMIT_PER_HOUR = "10000 per hour"
RATE_LIMIT_PARTY = "10 per minute"
RATE_LIMIT_ENCOUNTER = "20 per minute"
RATE_LIMIT_SIMULATE = "10 per minute"
RATE_LIMIT_STATUS = "30 per minute"
RATE_LIMIT_API_MONSTERS = "100 per minute"
RATE_LIMIT_API_BALANCE = "50 per minute"
RATE_LIMIT_RESULTS_EXPORT = "20 per minute"

# Constants - Input Validation
MAX_INPUT_LENGTH_DEFAULT = 1000
MAX_INPUT_LENGTH_JSON = 5000
MIN_BATCH_RUNS = 1
MAX_BATCH_RUNS = 1000

# Constants - Default Values
DEFAULT_PARTY_ID = 1
DEFAULT_PARTY_LEVEL = 5
DEFAULT_PARTY_SIZE = 4

# Initialize logger
logger = logging.getLogger(__name__)

# Initialize Flask application
app = Flask(__name__)


# Configure application
def configure_app(app: Flask) -> None:
    """
    Configure Flask application with security and session settings.

    Args:
        app: Flask application instance
    """
    # Secret key configuration
    # FLASK_SECRET_KEY, or SECRET_KEY as the README, docs and docker-compose.yml set it
    app.secret_key = (
        os.environ.get("FLASK_SECRET_KEY")
        or os.environ.get("SECRET_KEY")
        or DEFAULT_SECRET_KEY
    )

    # Warn if using default secret key
    if app.secret_key == DEFAULT_SECRET_KEY:
        if not app.debug:
            logger.error(
                "CRITICAL SECURITY WARNING: Using default secret key! "
                "Set the SECRET_KEY (or FLASK_SECRET_KEY) environment variable in production!"
            )
        else:
            logger.warning(
                "Using default development secret key - DO NOT use in production!"
            )

    # Session Security
    # Disable SECURE cookie for local development (allows HTTP access from LAN)
    # In production, set FLASK_SESSION_COOKIE_SECURE=true environment variable
    app.config["SESSION_COOKIE_SECURE"] = (
        os.environ.get("FLASK_SESSION_COOKIE_SECURE", "false").lower() == "true"
    )
    app.config["SESSION_COOKIE_HTTPONLY"] = True  # Prevent JavaScript access
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"  # CSRF protection
    app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(hours=SESSION_LIFETIME_HOURS)

    logger.info(
        f"Application configured: debug={app.debug}, testing={app.config.get('TESTING', False)}, session_cookie_secure={app.config['SESSION_COOKIE_SECURE']}"
    )


configure_app(app)

# Initialize rate limiting
limiter = Limiter(
    app=app,
    key_func=get_remote_address,
    default_limits=[RATE_LIMIT_PER_DAY, RATE_LIMIT_PER_HOUR],
    storage_uri="memory://",
)

# Initialize controllers
db = DatabaseManager()
encounter_controller = EncounterController()
simulation_controller = SimulationController()
batch_simulation_controller = BatchSimulationController()
results_controller = ResultsController()

# Helper Functions


def validate_input(
    data: Dict[str, Any],
    allowed_fields: Optional[List[str]] = None,
    max_length: int = MAX_INPUT_LENGTH_DEFAULT,
) -> Dict[str, Any]:
    """
    Validate and sanitize input data.

    Args:
        data: Dictionary of input data to validate
        allowed_fields: Optional list of allowed field names
        max_length: Maximum string length for validation

    Returns:
        Validated data dictionary

    Raises:
        ValidationError: If validation fails
    """
    if not isinstance(data, dict):
        raise ValidationError("Invalid input format")

    if allowed_fields:
        for key in data:
            if key not in allowed_fields:
                raise ValidationError(f"Invalid field: {key}")

    for key, value in data.items():
        if isinstance(value, str) and len(value) > max_length:
            raise ValidationError(f"Field {key} too long")
        if isinstance(value, str):
            if key == "cr":
                # Allow numbers, fractions, and slash for CR
                if not re.match(r"^[0-9/]+$", value):
                    raise ValidationError(f"Invalid characters in field {key}")
            elif key in ("template_name", "batch_name"):
                # Allow letters, numbers, spaces, apostrophes, and common punctuation for names
                if not re.match(r"^[a-zA-Z0-9\s\'\-_.,!?()]+$", value):
                    raise ValidationError(f"Invalid characters in field {key}")
            else:
                if not re.match(r"^[a-zA-Z0-9\s\-_.,!?()]+$", value):
                    raise ValidationError(f"Invalid characters in field {key}")

    return data


def load_party_from_session() -> Tuple[List[Any], int]:
    """
    Load party data from session.

    Returns:
        Tuple of (party characters list, party level). The level is the one the character data
        was loaded at, which can be lower than the selected level if there's no data for it.

    Raises:
        ValidationError: If party data cannot be loaded
    """
    selected_party_id = session.get("selected_party_id", DEFAULT_PARTY_ID)
    selected_party_level = session.get("selected_party_level", DEFAULT_PARTY_LEVEL)

    try:
        party_obj = PartyLoader.get_party_with_level(
            selected_party_id, selected_party_level
        )
    except ValidationError as e:
        logger.error(
            f"Error loading party {selected_party_id} at level {selected_party_level}: {e}"
        )
        raise ValidationError(
            f"Could not load the selected party: {e}. Please choose a party again."
        )

    party = party_obj.get("characters", [])
    if not party:
        raise ValidationError(
            f"Party {selected_party_id} has no characters. Please choose a party again."
        )
    return party, party_obj.get("level", selected_party_level)


def load_arena_from_session() -> Optional[str]:
    """
    Name of the map to fight on, from the arena chosen on the encounter page: None for no arena,
    or for "the encounter's own map" the selected pre-built encounter's map.
    """
    name = session.get("selected_encounter")
    template = (
        next((t for t in encounter_controller.templates if t.get("name") == name), None)
        if name
        else None
    )
    return resolve_arena_choice(session.get("arena"), template)


def battlefield_context() -> Dict[str, Any]:
    """What the Battlefield picker (templates/_battlefield_picker.html) needs: the maps and the current choice."""
    return {
        "arenas": arena_choices(),
        "encounter_map": ENCOUNTER_MAP,
        "default_map": DEFAULT_MAP,
        "selected_arena": session.get("arena") or "",
        "battlefield_map": load_arena_from_session() or "",
    }


def render_encounter_page(tab: Optional[str] = None) -> str:
    """The encounter page, with the arena choices and the current one."""
    kwargs = {"tab": tab} if tab else {}
    return render_template(
        "encounter_selection.html", **battlefield_context(), **kwargs
    )


def load_monsters_from_session() -> List[Any]:
    """
    Load monster data from session.

    Returns:
        List of monster dictionaries
    """
    return session.get("encounter_monsters", [])


def describe_monsters(monsters: List[Dict[str, Any]]) -> str:
    """A custom encounter's monsters, e.g. "6× Goblin · 1× Bugbear"."""
    counts = Counter(m.get("name", "Unknown") for m in monsters)
    return " · ".join(f"{count}× {name}" for name, count in counts.items())


def encounter_name_from_session() -> str:
    """The selected pre-built encounter's name, or a custom encounter's monsters."""
    return session.get("selected_encounter") or describe_monsters(
        load_monsters_from_session()
    )


def current_setup() -> Dict[str, Any]:
    """The party and encounter the next fight will use, for the pages that start fights."""
    party_id = session.get("selected_party_id", DEFAULT_PARTY_ID)
    try:
        party_name = PartyLoader.get_party_by_id(party_id).get("name")
    except ValidationError:
        party_name = None
    return {
        "party_name": party_name,
        "party_level": session.get("selected_party_level", DEFAULT_PARTY_LEVEL),
        "encounter_name": encounter_name_from_session(),
    }


def fight_details(party: List[Any], party_level: int) -> Dict[str, Any]:
    """
    What's being fought, saved with each fight and batch: whether the encounter is pre-built or
    custom, its name, the party's name, and the DMG's difficulty rating of the encounter for
    this party (from its XP).
    """
    # The party was loaded from the session already, so it exists
    party_id = session.get("selected_party_id", DEFAULT_PARTY_ID)
    party_name = PartyLoader.get_party_by_id(party_id).get("name")
    monsters = load_monsters_from_session()
    # No rating rather than a wrong one if a monster's CR is missing
    rating = (
        encounter_controller.builder.calculate_encounter_difficulty(
            monsters, party_level, len(party)
        )
        if all("cr" in m for m in monsters)
        else {}
    )
    return {
        "encounter_type": "prebuilt" if session.get("selected_encounter") else "custom",
        "encounter_name": encounter_name_from_session(),
        "party_name": party_name,
        "predicted_difficulty": rating.get("difficulty"),
        "encounter_xp": rating.get("total_xp"),
    }


# Security Headers


@app.after_request
def add_security_headers(response: Response) -> Response:
    """
    Add security headers to all responses.

    Args:
        response: Flask response object

    Returns:
        Response with security headers added
    """
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Strict-Transport-Security"] = (
        "max-age=31536000; includeSubDomains"
    )
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
        "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
        "font-src 'self' https://cdn.jsdelivr.net data:; "
        # Bootstrap draws its menu button, dropdown arrows and checkbox ticks as data: images
        "img-src 'self' data:"
    )
    return response


# Session Management


@app.before_request
def ensure_session() -> None:
    """
    Ensure session ID exists before processing requests.

    Creates a new session ID and database session if one doesn't exist.
    """
    if "session_id" not in session:
        session.permanent = True  # Make session persistent across requests
        session["session_id"] = str(uuid4())
        try:
            db.create_session(session["session_id"])
            logger.info(f"Created new session: {session['session_id']}")
        except Exception as e:
            logger.error(f"Failed to create database session: {e}")
            log_exception(e)
    else:
        session.permanent = True  # Ensure existing sessions are also permanent


def _session_owns(record: Optional[Dict[str, Any]]) -> bool:
    """Return True if a simulation/batch DB record belongs to the current session."""
    return bool(record) and record.get("session_id") == session.get("session_id")


def latest_simulation_id() -> Optional[int]:
    """
    This session's latest simulation: the one the simulation controller just finished, or
    failing that the last one saved in the database.
    """
    session_id = session["session_id"]
    sim_id = simulation_controller.get_simulation_id(session_id)
    if not sim_id:
        try:
            sim_id = db.get_last_simulation_id(session_id)
        except Exception as e:
            logger.error(f"Failed to get simulation ID from database: {e}")
            log_exception(e)
    return sim_id


# Main Routes


@app.route("/")
def index() -> str:
    """
    Render the home page.

    Returns:
        Rendered HTML template
    """
    return render_template("index.html")


@app.route("/favicon.ico")
def favicon() -> Response:
    """Return 204 No Content for favicon requests to prevent 404 errors."""
    return Response(status=204)


@app.route("/party", methods=["GET", "POST"])
def party() -> str:
    """
    Handle party selection.

    GET: Display party selection page
    POST: Process party selection and redirect to encounter selection

    Returns:
        Rendered HTML template or redirect response
    """
    parties = PartyLoader.load_parties()
    available_levels = PartyLoader.get_available_levels()

    if request.method == "POST":
        # Validate party selection: the party must exist and the level must be loadable
        try:
            party_data = validate_input(
                request.form.to_dict(), allowed_fields=["party_id", "party_level"]
            )
            try:
                selected_party_id = int(party_data.get("party_id", DEFAULT_PARTY_ID))
                selected_party_level = int(
                    party_data.get("party_level", DEFAULT_PARTY_LEVEL)
                )
            except (TypeError, ValueError):
                raise ValidationError("party and level must be whole numbers")
            PartyLoader.get_party_with_level(selected_party_id, selected_party_level)
        except ValidationError as e:
            logger.warning(f"Invalid party selection {request.form.to_dict()}: {e}")
            flash(f"Invalid party selection: {e}", "danger")
            return (
                render_template(
                    "party.html", parties=parties, available_levels=available_levels
                ),
                400,
            )

        session["selected_party_id"] = selected_party_id
        session["selected_party_level"] = selected_party_level

        try:
            db.create_session(
                session["session_id"], selected_party_id=selected_party_id
            )
        except Exception as e:
            logger.error(f"Error updating session in database: {e}")
            log_exception(e)

        return redirect(url_for("encounter_selection"))

    return render_template(
        "party.html", parties=parties, available_levels=available_levels
    )


@app.route("/encounter", methods=["GET"])
def encounter_selection() -> str:
    """
    Display encounter selection page.

    Returns:
        Rendered HTML template
    """
    return render_encounter_page()


@app.route("/encounter/custom", methods=["GET", "POST"])
def encounter_custom() -> Any:
    """
    Handle custom encounter creation.

    GET: Display custom encounter creation page
    POST: Process custom encounter data

    Returns:
        JSON response with encounter data or rendered HTML template

    Raises:
        ValidationError: If encounter data is invalid
    """
    if request.method == "POST":
        try:
            data = validate_input(
                request.get_json() or {}, max_length=MAX_INPUT_LENGTH_JSON
            )
            monsters = data.get("monsters", [])
            party_level = int(
                data.get(
                    "party_level",
                    session.get("selected_party_level", DEFAULT_PARTY_LEVEL),
                )
            )
            party_size = int(data.get("party_size", DEFAULT_PARTY_SIZE))

            # Validate monster data (no field restriction - monsters have many varied fields)
            for monster in monsters:
                validate_input(monster, max_length=MAX_INPUT_LENGTH_JSON)

            result = encounter_controller.handle_custom_encounter(
                monsters, party_level, party_size
            )
            return jsonify(result)
        except (ValueError, TypeError) as e:
            raise ValidationError(f"Invalid input data: {e}")

    return render_encounter_page("custom")


@app.route("/encounter/prebuilt", methods=["GET", "POST"])
def encounter_prebuilt() -> Any:
    """
    Handle prebuilt encounter selection.

    GET: Display prebuilt encounter selection page
    POST: Process prebuilt encounter selection

    Returns:
        JSON response with encounter data or rendered HTML template

    Raises:
        ValidationError: If encounter data is invalid
    """
    if request.method == "POST":
        try:
            data = validate_input(request.get_json() or {})
            template_name = data.get("template_name")
            party_level = int(
                data.get(
                    "party_level",
                    session.get("selected_party_level", DEFAULT_PARTY_LEVEL),
                )
            )
            party_size = int(data.get("party_size", DEFAULT_PARTY_SIZE))

            if not template_name:
                raise ValidationError("Template name is required")

            result = encounter_controller.handle_prebuilt_encounter(
                template_name, party_level, party_size
            )
            return jsonify(result)
        except (ValueError, TypeError) as e:
            raise ValidationError(f"Invalid input data: {e}")

    return render_encounter_page("prebuilt")


@app.route("/encounter/arena", methods=["GET", "POST"])
def encounter_arena() -> Tuple[Any, int]:
    """
    Choose the arena (battle map) for the next simulations: a map name, ENCOUNTER_MAP for each
    pre-built encounter's own map, or an empty name for no arena. GET returns the current choice
    and the map the next fight would use with the selected encounter.

    Returns:
        JSON response with the chosen arena, or an error for an unknown map
    """
    if request.method == "GET":
        return (
            jsonify(
                {
                    "arena": session.get("arena") or None,
                    "map": load_arena_from_session(),
                    "encounter": session.get("selected_encounter"),
                }
            ),
            200,
        )
    data = request.get_json(silent=True)
    name = (data.get("arena") if isinstance(data, dict) else None) or ""
    if not isinstance(name, str):
        return jsonify({"error": "arena must be a map name"}), 400
    # The name must be one of the maps, which also rules out anything unsafe
    if (
        name
        and name != ENCOUNTER_MAP
        and name not in {a["name"] for a in arena_choices()}
    ):
        return jsonify({"error": f"Unknown arena: {name}"}), 400
    if name:
        session["arena"] = name
    else:
        session.pop("arena", None)
    logger.info(f"Arena set to {name or 'none'}")
    return (
        jsonify(
            {"success": True, "arena": name or None, "map": load_arena_from_session()}
        ),
        200,
    )


@app.route("/api/arenas/<path:name>", methods=["GET"])
def api_arena_drawing(name: str) -> Tuple[Any, int]:
    """A map's terrain and start zones, for drawing a preview of it."""
    if name not in {a["name"] for a in arena_choices()}:
        return jsonify({"error": f"Unknown arena: {name}"}), 404
    arena = get_arena(name)
    description = next(a["description"] for a in arena_choices() if a["name"] == name)
    return (
        jsonify(
            {
                **arena.drawing(),
                "description": description,
                "start_zones": {
                    side: [list(sq) for sq in squares]
                    for side, squares in arena.start_zones.items()
                },
            }
        ),
        200,
    )


@app.route("/encounter/clear", methods=["POST"])
def encounter_clear() -> Tuple[Any, int]:
    """
    Clear encounter selection from session.

    Returns:
        JSON response indicating success or failure
    """
    try:
        session.pop("encounter_monsters", None)
        session.pop("selected_encounter", None)
        logger.info("Cleared encounter selection from session")
        return jsonify({"success": True, "message": "Encounter selection cleared"}), 200
    except Exception as e:
        log_exception(e)
        return jsonify({"error": "Failed to clear encounter selection"}), 500


# API Routes


@app.route("/api/simulation/debug", methods=["GET"])
def api_simulation_debug() -> Tuple[Any, int]:
    """
    Debug endpoint to show current simulation state.

    Note: Only available in debug mode.

    Returns:
        JSON response with debug information
    """
    if not app.debug:
        return jsonify({"error": "Debug endpoints only available in debug mode"}), 403

    try:
        session_id = session["session_id"]
        sim_state = simulation_controller.simulation_states.get(session_id, {})
        sim_id = simulation_controller.get_simulation_id(session_id)

        debug_info = {
            "session_id": session_id,
            "simulation_id": sim_id,
            "simulation_state": sim_state,
        }

        return jsonify(debug_info), 200
    except Exception as e:
        log_exception(e)
        return jsonify({"error": str(e)}), 500


@app.route("/api/encounter/debug", methods=["GET"])
def api_encounter_debug() -> Tuple[Any, int]:
    """
    Debug endpoint to show current encounter monsters in session.

    Note: Only available in debug mode.

    Returns:
        JSON response with debug information
    """
    if not app.debug:
        return jsonify({"error": "Debug endpoints only available in debug mode"}), 403

    try:
        monsters = session.get("encounter_monsters", [])
        selected_encounter = session.get("selected_encounter", None)

        debug_info = {
            "selected_encounter": selected_encounter,
            "monster_count": len(monsters),
            "monsters": [],
        }

        for i, monster in enumerate(monsters):
            if isinstance(monster, dict):
                debug_info["monsters"].append(
                    {
                        "index": i,
                        "type": "dict",
                        "name": monster.get("name", "Unknown"),
                        "cr": monster.get("cr", "Unknown"),
                        "hp": monster.get("hp", "Unknown"),
                        "ac": monster.get("ac", "Unknown"),
                    }
                )
            else:
                debug_info["monsters"].append(
                    {
                        "index": i,
                        "type": str(type(monster)),
                        "name": getattr(monster, "name", "Unknown"),
                        "cr": getattr(monster, "challenge_rating", "Unknown"),
                        "hp": getattr(monster, "hp", "Unknown"),
                        "ac": getattr(monster, "ac", "Unknown"),
                    }
                )

        return jsonify(debug_info), 200
    except Exception as e:
        log_exception(e)
        return jsonify({"error": str(e)}), 500


@app.route("/api/monsters", methods=["GET"])
@limiter.limit(RATE_LIMIT_API_MONSTERS)
def api_monsters() -> Any:
    """
    Get list of available monsters, optionally filtered by CR.

    Query Parameters:
        cr: Optional challenge rating filter

    Returns:
        JSON response with monster list

    Raises:
        ValidationError: If CR format is invalid
    """
    cr = request.args.get("cr")
    if cr and not re.match(r"^[0-9/]+$", cr):
        raise ValidationError("Invalid CR format")

    monsters = encounter_controller.builder.monster_data
    if cr:
        monsters = [m for m in monsters if str(m.get("cr")) == str(cr)]
    return jsonify(monsters)


@app.route("/api/encounter/balance", methods=["POST"])
@limiter.limit(RATE_LIMIT_API_BALANCE)
def api_encounter_balance() -> Any:
    """
    Calculate encounter balance and warnings.

    Returns:
        JSON response with balance and warnings

    Raises:
        ValidationError: If encounter data is invalid
    """
    try:
        data = validate_input(
            request.get_json() or {}, max_length=MAX_INPUT_LENGTH_JSON
        )
        monsters = data.get("monsters", [])
        party_level = int(
            data.get(
                "party_level", session.get("selected_party_level", DEFAULT_PARTY_LEVEL)
            )
        )
        party_size = int(data.get("party_size", DEFAULT_PARTY_SIZE))

        # Validate monster data (no field restriction - monsters have many varied fields)
        for monster in monsters:
            validate_input(monster, max_length=MAX_INPUT_LENGTH_JSON)

        balance = encounter_controller.validate_encounter_balance(
            monsters, party_level, party_size
        )
        warnings = encounter_controller.generate_encounter_warnings(
            monsters, party_level, party_size
        )
        return jsonify({"balance": balance, "warnings": warnings})
    except (ValueError, TypeError) as e:
        raise ValidationError(f"Invalid input data: {e}")


@app.route("/api/encounters/prebuilt", methods=["GET"])
def api_prebuilt_encounters() -> Tuple[Any, int]:
    """
    Get list of prebuilt encounter templates.

    Returns:
        JSON response with template list
    """
    return jsonify(encounter_controller.templates), 200


@app.route("/api/party/current", methods=["GET"])
def api_current_party() -> Any:
    """
    Get current party information from session.

    Returns:
        JSON response with party data
    """
    try:
        selected_party_id = session.get("selected_party_id", DEFAULT_PARTY_ID)
        selected_party_level = session.get("selected_party_level", DEFAULT_PARTY_LEVEL)
        party = PartyLoader.get_party_by_id(selected_party_id)

        if party:
            characters = party.get("characters", [])
            # Report the level the simulation will actually use, which falls back to the
            # closest level with character data
            party_level = PartyLoader.resolve_level(selected_party_level)
            display_characters = []
            for char in characters:
                char_copy = char.copy()
                char_copy["level"] = party_level
                display_characters.append(char_copy)

            return jsonify(
                {
                    "party_id": selected_party_id,
                    "party_level": party_level,
                    "party_size": len(characters),
                    "characters": display_characters,
                }
            )
        else:
            logger.warning(f"Party {selected_party_id} not found, returning defaults")
            return jsonify(
                {
                    "party_id": DEFAULT_PARTY_ID,
                    "party_level": DEFAULT_PARTY_LEVEL,
                    "party_size": DEFAULT_PARTY_SIZE,
                    "characters": [],
                }
            )
    except Exception as e:
        log_exception(e)
        return jsonify(
            {
                "party_id": DEFAULT_PARTY_ID,
                "party_level": DEFAULT_PARTY_LEVEL,
                "party_size": DEFAULT_PARTY_SIZE,
                "characters": [],
            }
        )


# Simulation Routes


@app.route("/simulate", methods=["GET"])
def simulate() -> Any:
    """
    Start or display combat simulation.

    Returns:
        Rendered HTML template or redirect on error
    """
    session_id = session["session_id"]

    # Ensure session exists in database before starting simulation
    try:
        db.create_session(
            session_id, selected_party_id=session.get("selected_party_id")
        )
    except Exception as e:
        logger.error(f"Failed to create database session: {e}")
        log_exception(e)

    # Check if we need to start a new simulation
    # (either no state exists, or the previous simulation is done)
    existing_state = simulation_controller.simulation_states.get(session_id)
    if not existing_state or existing_state.get("done", False):
        # Load party and monsters from session
        try:
            party, party_level = load_party_from_session()
        except ValidationError as e:
            flash(str(e), "danger")
            return redirect(url_for("party"))
        monsters = load_monsters_from_session()

        try:
            simulation_controller.execute_simulation(
                party,
                monsters,
                session_id,
                party_level=party_level,
                arena_name=load_arena_from_session(),
                details=fight_details(party, party_level),
            )
        except ValidationError as e:
            flash(f"Validation error: {str(e)}", "danger")
            return redirect(url_for("encounter_selection"))
        except Exception as e:
            logger.error(f"Failed to execute simulation: {e}")
            log_exception(e)
            flash("Failed to start simulation", "danger")
            return redirect(url_for("encounter_selection"))

    return render_template("simulation.html", arena=load_arena_from_session())


@app.route("/simulate/status", methods=["GET"])
def simulate_status() -> Any:
    """
    Get simulation progress status.

    Returns:
        JSON response with simulation status
    """
    session_id = session.get("session_id", "NO_SESSION_ID")
    logger.debug(f"Status endpoint called for session_id: {session_id}")
    status = simulation_controller.handle_simulation_progress()
    logger.debug(f"Status endpoint returning: {status}")
    return jsonify(status)


@app.route("/simulate/results", methods=["GET"])
def simulate_results() -> Response:
    """
    Redirect to results page with simulation ID.

    Returns:
        Redirect response
    """
    sim_id = latest_simulation_id()
    if sim_id:
        return redirect(url_for("results", sim_id=sim_id))
    else:
        # No simulation found, redirect to results page which will handle the error
        logger.warning("No simulation ID found for results redirect")
        return redirect(url_for("results"))


# Batch Simulation Routes


@app.route("/batch", methods=["GET"])
def batch_simulation() -> str:
    """
    Display batch simulation interface.

    Returns:
        Rendered HTML template
    """
    return render_template(
        "batch_simulation.html",
        arena=load_arena_from_session(),
        setup=current_setup(),
        **battlefield_context(),
    )


@app.route("/batch/start", methods=["POST"])
def batch_simulation_start() -> Tuple[Any, int]:
    """
    Start a batch simulation.

    Returns:
        JSON response with batch ID, or an error: 400 for bad input, 500 for anything else
    """
    try:
        data = validate_input(request.get_json() or {})
        try:
            num_runs = int(data.get("num_runs", 10))
        except (TypeError, ValueError):
            raise ValidationError("Number of runs must be a whole number")
        # Named after the encounter unless given a name
        batch_name = (
            data.get("batch_name")
            or encounter_name_from_session()
            or f"Batch {int(time.time())}"
        )

        if num_runs < MIN_BATCH_RUNS or num_runs > MAX_BATCH_RUNS:
            raise ValidationError(
                f"Number of runs must be between {MIN_BATCH_RUNS} and {MAX_BATCH_RUNS}"
            )

        # Load party and monsters from session
        session_id = session["session_id"]
        party, party_level = load_party_from_session()
        monsters = load_monsters_from_session()

        if not party or not monsters:
            raise ValidationError(
                "Party and monsters must be selected before starting batch simulation"
            )

        # Start batch simulation
        logger.info(
            f"Starting batch simulation: {num_runs} runs, {len(party)} party members, {len(monsters)} monsters"
        )
        try:
            batch_id = batch_simulation_controller.execute_batch_simulation(
                party,
                monsters,
                num_runs,
                batch_name,
                session_id,
                arena_name=load_arena_from_session(),
                compare_without_arena=bool(data.get("compare_without_arena")),
                details=fight_details(party, party_level),
            )
        except ValueError as e:  # the controller's input checks, e.g. an unknown map
            raise ValidationError(str(e))

        logger.info(f"Started batch simulation {batch_id} with {num_runs} runs")
        return (
            jsonify(
                {
                    "success": True,
                    "message": "Batch simulation started",
                    "batch_id": batch_id,
                }
            ),
            200,
        )
    except ValidationError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        return _json_server_error(e)


def _json_server_error(error: Exception) -> Tuple[Any, int]:
    """A 500 for the batch pages' fetch calls, without the exception's text."""
    log_exception(error)
    return (
        jsonify(
            {"error": "An unexpected error occurred.", "type": error.__class__.__name__}
        ),
        500,
    )


@app.route("/batch/progress/<int:batch_id>", methods=["GET"])
def batch_simulation_progress(batch_id: int) -> Tuple[Any, int]:
    """
    Get batch simulation progress. 404 unless the batch belongs to this session.

    Args:
        batch_id: Batch simulation ID

    Returns:
        JSON response with progress information
    """
    try:
        batch = db.get_batch_simulation(batch_id)
        if not _session_owns(batch):
            return jsonify({"error": f"Batch simulation {batch_id} not found"}), 404
        progress = batch_simulation_controller.get_batch_progress(batch_id)
        if progress is None:
            progress = _finished_batch_progress(batch)
        logger.debug(
            f"Batch {batch_id} progress: {progress.get('completed_runs', 0)}/{progress.get('total_runs', 0)} runs, {progress.get('progress', 0):.1f}% complete"
        )
        return jsonify(progress), 200
    except Exception as e:
        return _json_server_error(e)


def _finished_batch_progress(batch: Dict[str, Any]) -> Dict[str, Any]:
    """
    Progress for a batch the controller no longer holds, because the server restarted. Its
    statistics are only saved once it finishes, so without them it was cut off part way.
    """
    progress = {
        "progress": 100,
        "completed_runs": batch["total_runs"],
        "failed_runs": 0,
        "total_runs": batch["total_runs"],
        "party_wins": batch["party_wins"],
        "monster_wins": batch["monster_wins"],
        "done": True,
        "error": None,
    }
    if not batch["total_runs"]:
        progress["error"] = (
            "This batch stopped before it finished, because the server was restarted."
        )
    return progress


@app.route("/batch/results/<int:batch_id>", methods=["GET"])
def batch_simulation_results(batch_id: int) -> Tuple[str, int]:
    """
    Display batch simulation results.

    Args:
        batch_id: Batch simulation ID

    Returns:
        Rendered HTML template or error page
    """
    if not _session_owns(db.get_batch_simulation(batch_id)):
        return (
            render_template(
                "error.html", error=f"Batch simulation {batch_id} not found"
            ),
            404,
        )
    results = batch_simulation_controller.get_batch_results(batch_id)
    return render_template("batch_results.html", results=results), 200


@app.route("/batch/history", methods=["GET"])
def batch_simulation_history() -> Tuple[str, int]:
    """
    Display batch simulation history.

    Returns:
        Rendered HTML template or error page
    """
    history = batch_simulation_controller.get_batch_history(session["session_id"])
    return render_template("batch_history.html", batches=history), 200


@app.route("/api/batch/history", methods=["GET"])
def api_batch_history() -> Tuple[Any, int]:
    """
    API endpoint for batch simulation history.

    Returns:
        JSON response with batch history
    """
    try:
        history = batch_simulation_controller.get_batch_history(session["session_id"])
        return jsonify(history), 200
    except Exception as e:
        return _json_server_error(e)


# Results Routes


@app.route("/results")
def results() -> str:
    """
    Display simulation results.

    Query Parameters:
        sim_id: Optional simulation ID

    Returns:
        Rendered HTML template with results

    Raises:
        ValidationError: If simulation ID is invalid
    """
    # Prefer explicit sim_id from query string when provided; fall back to this session's latest
    sim_id = request.args.get("sim_id", type=int)
    if sim_id is not None and sim_id < 0:
        raise ValidationError("Invalid simulation ID")
    if not sim_id:
        sim_id = latest_simulation_id()
        if not sim_id:
            # No simulation found, return empty results
            logger.warning("No simulation found for results display")
            return render_template(
                "results.html",
                summary={"win_loss": "No simulation found", "party_status": "No data"},
                statistics=[],
                log=[],
                sim_id=None,
            )

    # sim_id can come from the query string, so only show simulations owned by this session
    record = db.get_simulation(sim_id)
    if not _session_owns(record):
        logger.warning(
            f"/results: simulation {sim_id} not found for session {session['session_id']}"
        )
        return (
            render_template(
                "results.html",
                summary={"win_loss": "No simulation found", "party_status": "No data"},
                statistics=[],
                log=[],
                sim_id=None,
            ),
            404,
        )

    # Build page data
    try:
        summary = results_controller.format_simulation_results(sim_id)
        statistics = results_controller.generate_combat_statistics(sim_id)
        log = [str(entry) for entry in summary["logs"]]  # the template escapes it
        replay = db.get_replay(sim_id) if record.get("arena") else None
        # One line per action, in the order of the replay's frames (escaped by the page's script)
        replay_log = (
            [
                {
                    "round": entry.get("round_number"),
                    "name": entry.get("character_name"),
                    "target": entry.get("target"),
                    "text": entry.get("result"),
                }
                for entry in summary["logs"]
            ]
            if replay
            else None
        )

        return render_template(
            "results.html",
            summary=summary.get("simulation", {}),
            statistics=statistics,
            log=log,
            sim_id=sim_id,
            arena=record.get("arena"),
            replay=replay,
            replay_log=replay_log,
        )
    except AppError as e:
        # Application errors (validation, database, etc.) should return 400
        logger.error(f"Failed to load results for simulation {sim_id}: {e}")
        log_exception(e)
        return render_template("error.html", error=str(e)), 400
    except Exception as e:
        # Unexpected errors should return 500
        logger.error(f"Unexpected error loading results for simulation {sim_id}: {e}")
        log_exception(e)
        return (
            render_template(
                "error.html",
                error="An unexpected error occurred while loading results.",
            ),
            500,
        )


@app.route("/results/export")
@limiter.limit(RATE_LIMIT_RESULTS_EXPORT)
def results_export() -> Any:
    """
    Export a simulation's results as JSON: the one in the sim_id query parameter, or this
    session's latest. Only simulations belonging to this session can be exported.
    """
    sim_id = request.args.get("sim_id", type=int) or latest_simulation_id()
    if not sim_id or not _session_owns(db.get_simulation(sim_id)):
        return jsonify({"error": "Simulation not found"}), 404
    summary = results_controller.format_simulation_results(sim_id)
    return Response(json.dumps(summary), mimetype="application/json")


@app.route("/history")
def history() -> str:
    """
    Display simulation history.

    Returns:
        Rendered HTML template with simulation history
    """
    try:
        sims = db.get_simulation_history(session["session_id"])
        return render_template("history.html", simulations=sims)
    except Exception as e:
        logger.error(f"Failed to load simulation history: {e}")
        log_exception(e)
        return render_template("history.html", simulations=[])


# Health Check


@app.route("/healthz")
def healthz() -> Tuple[str, int]:
    """
    Health check endpoint for deployment monitoring.

    Returns:
        Simple 'ok' response with 200 status
    """
    return "ok", 200


# Error Handlers


def _wants_json() -> bool:
    """True for a fetch/AJAX request, which gets a JSON error rather than the error page."""
    return (
        request.is_json
        or request.content_type == "application/json"
        or (
            request.accept_mimetypes.accept_json
            and not request.accept_mimetypes.accept_html
        )
    )


@app.errorhandler(AppError)
def handle_app_error(error: AppError) -> Tuple[Any, int]:
    """
    Handle application errors.

    Args:
        error: Application error instance

    Returns:
        JSON response or rendered error page
    """
    log_exception(error)
    if _wants_json():
        return jsonify({"error": str(error), "type": error.__class__.__name__}), 400
    return render_template("error.html", error=error), 400


@app.errorhandler(Exception)
def handle_unexpected_error(error: Exception) -> Any:
    """
    Handle unexpected errors. HTTP errors (404, 405, 429 from the rate limiter) keep their own
    status and response.

    Args:
        error: Exception instance

    Returns:
        JSON response or rendered error page
    """
    if isinstance(error, HTTPException):
        return error
    log_exception(error)
    if _wants_json():
        return (
            jsonify(
                {
                    "error": "An unexpected error occurred.",
                    "type": error.__class__.__name__,
                }
            ),
            500,
        )
    return render_template("error.html", error="An unexpected error occurred."), 500


# Application Entry Point

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
