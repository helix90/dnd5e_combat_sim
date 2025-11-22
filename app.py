"""
D&D 5e Combat Simulator Web Application

A Flask-based web application for simulating D&D 5e combat encounters
between characters and monsters.
"""

# Standard library imports
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
    Flask, Response, render_template, request, redirect,
    url_for, session, jsonify, flash
)
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

# Local imports
from controllers.batch_simulation_controller import BatchSimulationController
from controllers.encounter_controller import EncounterController
from controllers.results_controller import ResultsController
from controllers.simulation_controller import SimulationController
from models.db import DatabaseManager
from utils.exceptions import (
    AppError, ValidationError
)
from utils.logging import log_exception
from utils.party_loader import PartyLoader

# Constants - Application Configuration
DEFAULT_SECRET_KEY = 'dev-secret-key'
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
RATE_LIMIT_RESULTS_DETAILED = "50 per minute"
RATE_LIMIT_RESULTS_STATS = "50 per minute"
RATE_LIMIT_RESULTS_EXPORT = "20 per minute"

# Constants - Input Validation
MAX_INPUT_LENGTH_DEFAULT = 1000
MAX_INPUT_LENGTH_JSON = 5000
MIN_BATCH_RUNS = 1
MAX_BATCH_RUNS = 1000

# Constants - File Paths
ENCOUNTER_TEMPLATES_FILE = 'data/encounter_templates.json'

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
    app.secret_key = os.environ.get('FLASK_SECRET_KEY', DEFAULT_SECRET_KEY)

    # Warn if using default secret key
    if app.secret_key == DEFAULT_SECRET_KEY:
        if not app.debug:
            logger.error(
                "CRITICAL SECURITY WARNING: Using default secret key! "
                "Set FLASK_SECRET_KEY environment variable in production!"
            )
        else:
            logger.warning("Using default development secret key - DO NOT use in production!")

    # Session Security
    # Disable SECURE cookie for local development (allows HTTP access from LAN)
    # In production, set FLASK_SESSION_COOKIE_SECURE=true environment variable
    app.config['SESSION_COOKIE_SECURE'] = os.environ.get('FLASK_SESSION_COOKIE_SECURE', 'false').lower() == 'true'
    app.config['SESSION_COOKIE_HTTPONLY'] = True  # Prevent JavaScript access
    app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'  # CSRF protection
    app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(hours=SESSION_LIFETIME_HOURS)

    logger.info(f"Application configured: debug={app.debug}, testing={app.config.get('TESTING', False)}, session_cookie_secure={app.config['SESSION_COOKIE_SECURE']}")

configure_app(app)

# Initialize rate limiting
limiter = Limiter(
    app=app,
    key_func=get_remote_address,
    default_limits=[RATE_LIMIT_PER_DAY, RATE_LIMIT_PER_HOUR],
    storage_uri="memory://"
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
    max_length: int = MAX_INPUT_LENGTH_DEFAULT
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
            if key == 'cr':
                # Allow numbers, fractions, and slash for CR
                if not re.match(r'^[0-9/]+$', value):
                    raise ValidationError(f"Invalid characters in field {key}")
            elif key == 'template_name':
                # Allow letters, numbers, spaces, apostrophes, and common punctuation for template names
                if not re.match(r'^[a-zA-Z0-9\s\'\-_.,!?()]+$', value):
                    raise ValidationError(f"Invalid characters in field {key}")
            else:
                if not re.match(r'^[a-zA-Z0-9\s\-_.,!?()]+$', value):
                    raise ValidationError(f"Invalid characters in field {key}")

    return data

def sanitize_html(text: Any) -> str:
    """
    Sanitize HTML to prevent XSS attacks.

    Removes dangerous HTML tags and attributes that could execute JavaScript.

    Args:
        text: Text to sanitize

    Returns:
        Sanitized text string
    """
    if not isinstance(text, str):
        return str(text)

    # Remove potentially dangerous HTML tags
    dangerous_tags = ['script', 'iframe', 'object', 'embed', 'form', 'input', 'style', 'link']
    for tag in dangerous_tags:
        text = re.sub(f'<{tag}[^>]*>.*?</{tag}>', '', text, flags=re.IGNORECASE | re.DOTALL)
        text = re.sub(f'<{tag}[^>]*>', '', text, flags=re.IGNORECASE)

    # Remove dangerous attributes (event handlers)
    dangerous_attrs = ['onclick', 'onerror', 'onload', 'onmouseover', 'onfocus', 'onblur']
    for attr in dangerous_attrs:
        text = re.sub(f'{attr}\\s*=\\s*["\'][^"\']*["\']', '', text, flags=re.IGNORECASE)

    # Remove javascript: protocol
    text = re.sub(r'javascript:', '', text, flags=re.IGNORECASE)

    return text

def load_party_from_session() -> Tuple[List[Any], int]:
    """
    Load party data from session.

    Returns:
        Tuple of (party characters list, party level)

    Raises:
        ValidationError: If party data cannot be loaded
    """
    selected_party_id = session.get('selected_party_id', DEFAULT_PARTY_ID)
    selected_party_level = session.get('selected_party_level', DEFAULT_PARTY_LEVEL)

    try:
        party_obj = PartyLoader.get_party_with_level(selected_party_id, selected_party_level)
        if party_obj:
            party = party_obj.get('characters', [])
        else:
            logger.warning(f"Party {selected_party_id} not found, using empty party")
            party = []
    except Exception as e:
        logger.error(f"Error loading party {selected_party_id}: {e}")
        party = []

    return party, selected_party_level

def load_monsters_from_session() -> List[Any]:
    """
    Load monster data from session.

    Returns:
        List of monster dictionaries
    """
    return session.get('encounter_monsters', [])

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
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['X-XSS-Protection'] = '1; mode=block'
    response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
    response.headers['Content-Security-Policy'] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline'; "
        "style-src 'self' 'unsafe-inline'"
    )
    return response

# Session Management

@app.before_request
def ensure_session() -> None:
    """
    Ensure session ID exists before processing requests.

    Creates a new session ID and database session if one doesn't exist.
    """
    if 'session_id' not in session:
        session.permanent = True  # Make session persistent across requests
        session['session_id'] = str(uuid4())
        try:
            db.create_session(session['session_id'])
            logger.info(f"Created new session: {session['session_id']}")
        except Exception as e:
            logger.error(f"Failed to create database session: {e}")
            log_exception(e)
    else:
        session.permanent = True  # Ensure existing sessions are also permanent

# Main Routes

@app.route('/')
def index() -> str:
    """
    Render the home page.

    Returns:
        Rendered HTML template
    """
    return render_template('index.html')

@app.route('/favicon.ico')
def favicon() -> Response:
    """Return 204 No Content for favicon requests to prevent 404 errors."""
    return Response(status=204)

@app.route('/party', methods=['GET', 'POST'])
def party() -> str:
    """
    Handle party selection.

    GET: Display party selection page
    POST: Process party selection and redirect to encounter selection

    Returns:
        Rendered HTML template or redirect response
    """
    parties = PartyLoader.load_parties()

    if request.method == 'POST':
        # Validate party selection
        try:
            party_data = validate_input(
                request.form.to_dict(),
                allowed_fields=['party_id', 'party_level']
            )
            selected_party_id = int(party_data.get('party_id', DEFAULT_PARTY_ID))
            selected_party_level = int(party_data.get('party_level', DEFAULT_PARTY_LEVEL))
        except (TypeError, ValueError) as e:
            logger.warning(f"Invalid party selection data: {e}")
            selected_party_id = DEFAULT_PARTY_ID
            selected_party_level = DEFAULT_PARTY_LEVEL

        # Verify party exists
        try:
            if not PartyLoader.get_party_by_id(selected_party_id):
                logger.warning(f"Party {selected_party_id} not found, using default")
                selected_party_id = DEFAULT_PARTY_ID
        except Exception as e:
            logger.error(f"Error verifying party: {e}")
            selected_party_id = DEFAULT_PARTY_ID

        session['selected_party_id'] = selected_party_id
        session['selected_party_level'] = selected_party_level

        try:
            db.create_session(session['session_id'], selected_party_id=selected_party_id)
        except Exception as e:
            logger.error(f"Error updating session in database: {e}")
            log_exception(e)

        return redirect(url_for('encounter_selection'))

    return render_template('party.html', parties=parties)

@app.route('/encounter', methods=['GET'])
def encounter_selection() -> str:
    """
    Display encounter selection page.

    Returns:
        Rendered HTML template
    """
    return render_template('encounter_selection.html')

@app.route('/encounter/custom', methods=['GET', 'POST'])
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
    if request.method == 'POST':
        try:
            data = validate_input(
                request.get_json() or {},
                max_length=MAX_INPUT_LENGTH_JSON
            )
            monsters = data.get('monsters', [])
            party_level = int(data.get('party_level', 3))
            party_size = int(data.get('party_size', DEFAULT_PARTY_SIZE))

            # Validate monster data (no field restriction - monsters have many varied fields)
            for monster in monsters:
                validate_input(monster, max_length=MAX_INPUT_LENGTH_JSON)

            result = encounter_controller.handle_custom_encounter(
                monsters, party_level, party_size
            )
            return jsonify(result)
        except (ValueError, TypeError) as e:
            raise ValidationError(f"Invalid input data: {e}")

    return render_template('encounter_selection.html', tab='custom')

@app.route('/encounter/prebuilt', methods=['GET', 'POST'])
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
    if request.method == 'POST':
        try:
            data = validate_input(request.get_json() or {})
            template_name = data.get('template_name')
            party_level = int(data.get('party_level', 3))
            party_size = int(data.get('party_size', DEFAULT_PARTY_SIZE))

            if not template_name:
                raise ValidationError("Template name is required")

            result = encounter_controller.handle_prebuilt_encounter(
                template_name, party_level, party_size
            )
            return jsonify(result)
        except (ValueError, TypeError) as e:
            raise ValidationError(f"Invalid input data: {e}")

    return render_template('encounter_selection.html', tab='prebuilt')

@app.route('/encounter/clear', methods=['POST'])
def encounter_clear() -> Tuple[Any, int]:
    """
    Clear encounter selection from session.

    Returns:
        JSON response indicating success or failure
    """
    try:
        session.pop('encounter_monsters', None)
        session.pop('selected_encounter', None)
        logger.info("Cleared encounter selection from session")
        return jsonify({'success': True, 'message': 'Encounter selection cleared'}), 200
    except Exception as e:
        log_exception(e)
        return jsonify({'error': 'Failed to clear encounter selection'}), 500

# API Routes

@app.route('/api/session/clear', methods=['POST'])
def api_session_clear() -> Tuple[Any, int]:
    """
    Clear all session data for troubleshooting.

    Returns:
        JSON response indicating success or failure
    """
    try:
        # Keep only the session_id
        session_id = session.get('session_id')

        # Clear all other session data
        session.clear()

        # Restore the session_id
        session['session_id'] = session_id

        # Create a fresh session in the database
        db.create_session(session_id)

        logger.info(f"Cleared session data for {session_id}")
        return jsonify({'success': True, 'message': 'Session cleared successfully'}), 200
    except Exception as e:
        log_exception(e)
        return jsonify({'error': str(e)}), 500

@app.route('/api/simulation/debug', methods=['GET'])
def api_simulation_debug() -> Tuple[Any, int]:
    """
    Debug endpoint to show current simulation state.

    Note: Only available in debug mode.

    Returns:
        JSON response with debug information
    """
    if not app.debug:
        return jsonify({'error': 'Debug endpoints only available in debug mode'}), 403

    try:
        session_id = session['session_id']
        sim_state = simulation_controller.simulation_states.get(session_id, {})
        sim_id = simulation_controller.get_simulation_id(session_id)

        debug_info = {
            'session_id': session_id,
            'simulation_id': sim_id,
            'simulation_state': sim_state,
            'session_simulation_id': session.get('simulation_id'),
            'session_last_simulation_id': session.get('last_simulation_id')
        }

        return jsonify(debug_info), 200
    except Exception as e:
        log_exception(e)
        return jsonify({'error': str(e)}), 500

@app.route('/api/encounter/debug', methods=['GET'])
def api_encounter_debug() -> Tuple[Any, int]:
    """
    Debug endpoint to show current encounter monsters in session.

    Note: Only available in debug mode.

    Returns:
        JSON response with debug information
    """
    if not app.debug:
        return jsonify({'error': 'Debug endpoints only available in debug mode'}), 403

    try:
        monsters = session.get('encounter_monsters', [])
        selected_encounter = session.get('selected_encounter', None)

        debug_info = {
            'selected_encounter': selected_encounter,
            'monster_count': len(monsters),
            'monsters': []
        }

        for i, monster in enumerate(monsters):
            if isinstance(monster, dict):
                debug_info['monsters'].append({
                    'index': i,
                    'type': 'dict',
                    'name': monster.get('name', 'Unknown'),
                    'cr': monster.get('cr', 'Unknown'),
                    'hp': monster.get('hp', 'Unknown'),
                    'ac': monster.get('ac', 'Unknown')
                })
            else:
                debug_info['monsters'].append({
                    'index': i,
                    'type': str(type(monster)),
                    'name': getattr(monster, 'name', 'Unknown'),
                    'cr': getattr(monster, 'challenge_rating', 'Unknown'),
                    'hp': getattr(monster, 'hp', 'Unknown'),
                    'ac': getattr(monster, 'ac', 'Unknown')
                })

        return jsonify(debug_info), 200
    except Exception as e:
        log_exception(e)
        return jsonify({'error': str(e)}), 500

@app.route('/api/monsters', methods=['GET'])
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
    cr = request.args.get('cr')
    if cr and not re.match(r'^[0-9/]+$', cr):
        raise ValidationError("Invalid CR format")

    monsters = encounter_controller.builder.monster_data
    if cr:
        monsters = [m for m in monsters if str(m.get('cr')) == str(cr)]
    return jsonify(monsters)

@app.route('/api/encounter/balance', methods=['POST'])
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
            request.get_json() or {},
            max_length=MAX_INPUT_LENGTH_JSON
        )
        monsters = data.get('monsters', [])
        party_level = int(data.get('party_level', 3))
        party_size = int(data.get('party_size', DEFAULT_PARTY_SIZE))

        # Validate monster data (no field restriction - monsters have many varied fields)
        for monster in monsters:
            validate_input(monster, max_length=MAX_INPUT_LENGTH_JSON)

        balance = encounter_controller.validate_encounter_balance(
            monsters, party_level, party_size
        )
        warnings = encounter_controller.generate_encounter_warnings(
            monsters, party_level, party_size
        )
        return jsonify({'balance': balance, 'warnings': warnings})
    except (ValueError, TypeError) as e:
        raise ValidationError(f"Invalid input data: {e}")

@app.route('/api/encounters/prebuilt', methods=['GET'])
def api_prebuilt_encounters() -> Tuple[Any, int]:
    """
    Get list of prebuilt encounter templates.

    Returns:
        JSON response with template list
    """
    try:
        with open(ENCOUNTER_TEMPLATES_FILE, 'r', encoding='utf-8') as f:
            templates = json.load(f)["encounters"]
        return jsonify(templates), 200
    except FileNotFoundError as e:
        log_exception(e)
        return jsonify({"error": f"Encounter templates file not found: {ENCOUNTER_TEMPLATES_FILE}"}), 500
    except json.JSONDecodeError as e:
        log_exception(e)
        return jsonify({"error": "Invalid JSON in encounter templates file"}), 500
    except Exception as e:
        log_exception(e)
        return jsonify({"error": "Failed to load prebuilt encounters"}), 500

@app.route('/api/party/current', methods=['GET'])
def api_current_party() -> Any:
    """
    Get current party information from session.

    Returns:
        JSON response with party data
    """
    try:
        selected_party_id = session.get('selected_party_id', DEFAULT_PARTY_ID)
        selected_party_level = session.get('selected_party_level', DEFAULT_PARTY_LEVEL)
        party = PartyLoader.get_party_by_id(selected_party_id)

        if party:
            characters = party.get('characters', [])
            # Override all character levels with selected_party_level for display
            display_characters = []
            for char in characters:
                char_copy = char.copy()
                char_copy['level'] = selected_party_level
                display_characters.append(char_copy)

            return jsonify({
                'party_id': selected_party_id,
                'party_level': selected_party_level,
                'party_size': len(characters),
                'characters': display_characters
            })
        else:
            logger.warning(f"Party {selected_party_id} not found, returning defaults")
            return jsonify({
                'party_id': DEFAULT_PARTY_ID,
                'party_level': DEFAULT_PARTY_LEVEL,
                'party_size': DEFAULT_PARTY_SIZE,
                'characters': []
            })
    except Exception as e:
        log_exception(e)
        return jsonify({
            'party_id': DEFAULT_PARTY_ID,
            'party_level': DEFAULT_PARTY_LEVEL,
            'party_size': DEFAULT_PARTY_SIZE,
            'characters': []
        })

# Simulation Routes

@app.route('/simulate', methods=['GET'])
def simulate() -> Any:
    """
    Start or display combat simulation.

    Returns:
        Rendered HTML template or redirect on error
    """
    session_id = session['session_id']

    # Ensure session exists in database before starting simulation
    try:
        db.create_session(session_id, selected_party_id=session.get('selected_party_id'))
    except Exception as e:
        logger.error(f"Failed to create database session: {e}")
        log_exception(e)

    # Check if we need to start a new simulation
    # (either no state exists, or the previous simulation is done)
    existing_state = simulation_controller.simulation_states.get(session_id)
    if not existing_state or existing_state.get('done', False):
        # Load party and monsters from session
        party, party_level = load_party_from_session()
        monsters = load_monsters_from_session()

        try:
            simulation_controller.execute_simulation(
                party, monsters, session_id, party_level=party_level
            )
        except ValidationError as e:
            flash(f'Validation error: {str(e)}', 'danger')
            return redirect(url_for('encounter_selection'))
        except Exception as e:
            logger.error(f"Failed to execute simulation: {e}")
            log_exception(e)
            flash('Failed to start simulation', 'danger')
            return redirect(url_for('encounter_selection'))

    return render_template('simulation.html')

@app.route('/simulate/status', methods=['GET'])
def simulate_status() -> Any:
    """
    Get simulation progress status.

    Returns:
        JSON response with simulation status
    """
    session_id = session.get('session_id', 'NO_SESSION_ID')
    logger.info(f"Status endpoint called for session_id: {session_id}")
    status = simulation_controller.handle_simulation_progress()
    logger.info(f"Status endpoint returning: {status}")
    return jsonify(status)

@app.route('/simulate/results', methods=['GET'])
def simulate_results() -> Response:
    """
    Redirect to results page with simulation ID.

    Returns:
        Redirect response
    """
    # Get the simulation ID from the session or simulation controller
    sim_id = session.get('simulation_id')

    if not sim_id:
        # Try to get from simulation controller state
        session_id = session['session_id']
        sim_id = simulation_controller.get_simulation_id(session_id)

        # If still no sim_id, try database
        if not sim_id:
            try:
                sim_id = db.get_last_simulation_id(session_id)
            except Exception as e:
                logger.error(f"Failed to get simulation ID from database: {e}")
                log_exception(e)

    if sim_id:
        return redirect(url_for('results', sim_id=sim_id))
    else:
        # No simulation found, redirect to results page which will handle the error
        logger.warning("No simulation ID found for results redirect")
        return redirect(url_for('results'))

# Batch Simulation Routes

@app.route('/batch', methods=['GET'])
def batch_simulation() -> str:
    """
    Display batch simulation interface.

    Returns:
        Rendered HTML template
    """
    return render_template('batch_simulation.html')

@app.route('/batch/start', methods=['POST'])
def batch_simulation_start() -> Tuple[Any, int]:
    """
    Start a batch simulation.

    Returns:
        JSON response with batch ID or error

    Raises:
        ValidationError: If batch parameters are invalid
    """
    try:
        data = validate_input(request.get_json() or {})
        num_runs = int(data.get('num_runs', 10))
        batch_name = data.get('batch_name', f'Batch {int(time.time())}')

        if num_runs < MIN_BATCH_RUNS or num_runs > MAX_BATCH_RUNS:
            raise ValidationError(
                f"Number of runs must be between {MIN_BATCH_RUNS} and {MAX_BATCH_RUNS}"
            )

        # Load party and monsters from session
        session_id = session['session_id']
        party, _ = load_party_from_session()
        monsters = load_monsters_from_session()

        if not party or not monsters:
            raise ValidationError(
                "Party and monsters must be selected before starting batch simulation"
            )

        # Start batch simulation
        batch_id = batch_simulation_controller.execute_batch_simulation(
            party, monsters, num_runs, batch_name, session_id
        )

        logger.info(f"Started batch simulation {batch_id} with {num_runs} runs")
        return jsonify({
            'success': True,
            'message': 'Batch simulation started',
            'batch_id': batch_id
        }), 200
    except Exception as e:
        log_exception(e)
        return jsonify({'error': str(e)}), 400

@app.route('/batch/progress/<int:batch_id>', methods=['GET'])
def batch_simulation_progress(batch_id: int) -> Tuple[Any, int]:
    """
    Get batch simulation progress.

    Args:
        batch_id: Batch simulation ID

    Returns:
        JSON response with progress information
    """
    try:
        progress = batch_simulation_controller.get_batch_progress(batch_id)
        return jsonify(progress), 200
    except Exception as e:
        log_exception(e)
        return jsonify({'error': str(e)}), 400

@app.route('/batch/results/<int:batch_id>', methods=['GET'])
def batch_simulation_results(batch_id: int) -> Tuple[str, int]:
    """
    Display batch simulation results.

    Args:
        batch_id: Batch simulation ID

    Returns:
        Rendered HTML template or error page
    """
    try:
        results = batch_simulation_controller.get_batch_results(batch_id)
        return render_template('batch_results.html', results=results), 200
    except Exception as e:
        log_exception(e)
        return render_template('error.html', error=str(e)), 400

@app.route('/batch/history', methods=['GET'])
def batch_simulation_history() -> Tuple[str, int]:
    """
    Display batch simulation history.

    Returns:
        Rendered HTML template or error page
    """
    try:
        history = batch_simulation_controller.get_batch_history(session['session_id'])
        return render_template('batch_history.html', batches=history), 200
    except Exception as e:
        log_exception(e)
        return render_template('error.html', error=str(e)), 400

@app.route('/api/batch/history', methods=['GET'])
def api_batch_history() -> Tuple[Any, int]:
    """
    API endpoint for batch simulation history.

    Returns:
        JSON response with batch history
    """
    try:
        history = batch_simulation_controller.get_batch_history(session['session_id'])
        return jsonify(history), 200
    except Exception as e:
        log_exception(e)
        return jsonify({'error': str(e)}), 400

# Results Routes

@app.route('/results')
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
    # Prefer explicit sim_id from query string when provided; fall back to session
    sim_id = request.args.get('sim_id', type=int) or session.get('simulation_id')

    if sim_id and sim_id < 0:
        raise ValidationError("Invalid simulation ID")

    # If no sim_id provided, use the last simulation from the database for this session
    if not sim_id:
        logger.info('/results: sim_id missing from query params and session')
        session_id = session['session_id']

        # First try to get from simulation controller state
        sim_id = simulation_controller.get_simulation_id(session_id)

        # If still no sim_id, try database
        if not sim_id:
            logger.info('/results: trying to get from database')
            try:
                sim_id = db.get_last_simulation_id(session_id)
            except Exception as e:
                logger.error(f"Failed to get simulation ID from database: {e}")
                log_exception(e)

        if not sim_id:
            # No simulation found, return empty results
            logger.warning("No simulation found for results display")
            return render_template(
                'results.html',
                summary={'win_loss': 'No simulation found', 'party_status': 'No data'},
                statistics=[],
                log=[],
                sim_id=None
            )

    # Build page data
    try:
        summary = results_controller.format_simulation_results(sim_id)
        statistics = results_controller.generate_combat_statistics(sim_id)
        log = [sanitize_html(str(entry)) for entry in summary['logs']]

        return render_template(
            'results.html',
            summary=summary.get('simulation', {}),
            statistics=statistics,
            log=log,
            sim_id=sim_id
        )
    except AppError as e:
        # Application errors (validation, database, etc.) should return 400
        logger.error(f"Failed to load results for simulation {sim_id}: {e}")
        log_exception(e)
        return render_template('error.html', error=str(e)), 400
    except Exception as e:
        # Unexpected errors should return 500
        logger.error(f"Unexpected error loading results for simulation {sim_id}: {e}")
        log_exception(e)
        return render_template('error.html', error='An unexpected error occurred while loading results.'), 500

@app.route('/results/detailed')
@limiter.limit(RATE_LIMIT_RESULTS_DETAILED)
def results_detailed() -> Dict[str, List[str]]:
    """
    Get detailed combat log.

    Returns:
        JSON-compatible dictionary with detailed log

    Raises:
        ValidationError: If simulation ID is invalid
    """
    sim_id = session.get('simulation_id')
    if sim_id and sim_id < 0:
        raise ValidationError("Invalid simulation ID")

    log = results_controller.handle_detailed_log_display(sim_id)
    return {'log': [sanitize_html(entry) for entry in log]}

@app.route('/results/statistics')
@limiter.limit(RATE_LIMIT_RESULTS_STATS)
def results_statistics() -> Dict[str, Any]:
    """
    Get combat statistics.

    Returns:
        JSON-compatible dictionary with statistics

    Raises:
        ValidationError: If simulation ID is invalid
    """
    sim_id = session.get('simulation_id')
    if sim_id and sim_id < 0:
        raise ValidationError("Invalid simulation ID")

    stats = results_controller.generate_combat_statistics(sim_id)
    return {'statistics': stats}

@app.route('/results/export')
@limiter.limit(RATE_LIMIT_RESULTS_EXPORT)
def results_export() -> Tuple[str, int, Dict[str, str]]:
    """
    Export simulation results as JSON.

    Returns:
        JSON string with results and content-type header

    Raises:
        ValidationError: If simulation ID is invalid
    """
    sim_id = session.get('simulation_id')
    if sim_id and sim_id < 0:
        raise ValidationError("Invalid simulation ID")

    summary = results_controller.format_simulation_results(sim_id)
    return json.dumps(summary), 200, {'Content-Type': 'application/json'}

@app.route('/history')
def history() -> str:
    """
    Display simulation history.

    Returns:
        Rendered HTML template with simulation history
    """
    try:
        sims = db.get_simulation_history(session['session_id'])
        return render_template('history.html', simulations=sims)
    except Exception as e:
        logger.error(f"Failed to load simulation history: {e}")
        log_exception(e)
        return render_template('history.html', simulations=[])

# Health Check

@app.route('/healthz')
def healthz() -> Tuple[str, int]:
    """
    Health check endpoint for deployment monitoring.

    Returns:
        Simple 'ok' response with 200 status
    """
    return 'ok', 200

# Error Handlers

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

    # Check if this is a JSON request (from fetch/AJAX)
    is_json_request = (
        request.is_json or
        request.content_type == 'application/json' or
        request.headers.get('Content-Type') == 'application/json' or
        (request.accept_mimetypes.accept_json and not request.accept_mimetypes.accept_html)
    )

    if is_json_request:
        response = jsonify({
            'error': str(error),
            'type': error.__class__.__name__
        })
        return response, 400

    return render_template('error.html', error=error), 400

@app.errorhandler(Exception)
def handle_unexpected_error(error: Exception) -> Tuple[Any, int]:
    """
    Handle unexpected errors.

    Args:
        error: Exception instance

    Returns:
        JSON response or rendered error page
    """
    log_exception(error)

    # Check if this is a JSON request (from fetch/AJAX)
    is_json_request = (
        request.is_json or
        request.content_type == 'application/json' or
        request.headers.get('Content-Type') == 'application/json' or
        (request.accept_mimetypes.accept_json and not request.accept_mimetypes.accept_html)
    )

    if is_json_request:
        response = jsonify({
            'error': 'An unexpected error occurred.',
            'type': error.__class__.__name__
        })
        return response, 500

    return render_template('error.html', error='An unexpected error occurred.'), 500

# Application Entry Point

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
