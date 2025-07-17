"""
D&D 5e Combat Simulator Web Application

A Flask-based web application for simulating D&D 5e combat encounters
between characters and monsters.
"""

from flask import Flask, render_template, request, redirect, url_for, session, jsonify
from flask_wtf.csrf import CSRFProtect
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from models.db import DatabaseManager
import os
from uuid import uuid4
from models.encounter_builder import EncounterBuilder
import json
from utils.party_loader import PartyLoader
from controllers.encounter_controller import EncounterController
from controllers.simulation_controller import SimulationController
from controllers.batch_simulation_controller import BatchSimulationController
from controllers.results_controller import ResultsController
from utils.exceptions import AppError, APIError, DatabaseError, ValidationError, SimulationError, BatchSimulationError, SessionError
from utils.logging import log_exception
from flask import make_response
import re
import time
import logging

app = Flask(__name__)
app.secret_key = os.environ.get('FLASK_SECRET_KEY', 'dev-secret-key')

# Security configurations
app.config['WTF_CSRF_ENABLED'] = False  # Disable for development
app.config['WTF_CSRF_TIME_LIMIT'] = 3600  # 1 hour
csrf = CSRFProtect(app)

# Rate limiting - disabled for development and testing
limiter = Limiter(
    app=app,
    key_func=get_remote_address,
    default_limits=["100000 per day", "10000 per hour"],  # Very high limits for development
    storage_uri="memory://"  # Use memory storage for development
)

# Security headers
@app.after_request
def add_security_headers(response):
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['X-XSS-Protection'] = '1; mode=block'
    response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
    response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'"
    return response

db = DatabaseManager()
encounter_controller = EncounterController()
simulation_controller = SimulationController()
batch_simulation_controller = BatchSimulationController()
results_controller = ResultsController()

def validate_input(data, allowed_fields=None, max_length=1000):
    """Validate and sanitize input data."""
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

def sanitize_html(text):
    """Basic HTML sanitization."""
    if not isinstance(text, str):
        return str(text)
    
    # Remove potentially dangerous HTML tags
    dangerous_tags = ['script', 'iframe', 'object', 'embed', 'form', 'input']
    for tag in dangerous_tags:
        text = re.sub(f'<{tag}[^>]*>.*?</{tag}>', '', text, flags=re.IGNORECASE | re.DOTALL)
        text = re.sub(f'<{tag}[^>]*>', '', text, flags=re.IGNORECASE)
    
    return text

@app.before_request
def ensure_session():
    if 'session_id' not in session:
        session['session_id'] = str(uuid4())
        db.create_session(session['session_id'])

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/party', methods=['GET', 'POST'])
# @limiter.limit("10 per minute")  # Disabled for testing
def party():
    parties = PartyLoader.load_parties()
    if request.method == 'POST':
        # Validate party selection
        try:
            party_data = validate_input(request.form.to_dict(), allowed_fields=['party_id', 'party_level'])
            selected_party_id = int(party_data.get('party_id', 1))
            selected_party_level = int(party_data.get('party_level', 5))
        except (TypeError, ValueError):
            selected_party_id = 1
            selected_party_level = 5
        if not PartyLoader.get_party_by_id(selected_party_id):
            selected_party_id = 1
        session['selected_party_id'] = selected_party_id
        session['selected_party_level'] = selected_party_level
        db.create_session(session['session_id'], selected_party_id=selected_party_id)
        return redirect(url_for('encounter_selection'))
    return render_template('party.html', parties=parties)

@app.route('/encounter', methods=['GET'])
def encounter_selection():
    return render_template('encounter_selection.html')

@app.route('/encounter/custom', methods=['GET', 'POST'])
# @limiter.limit("20 per minute")  # Disabled for testing
def encounter_custom():
    if request.method == 'POST':
        try:
            data = validate_input(request.get_json() or {}, max_length=5000)
            monsters = data.get('monsters', [])
            party_level = int(data.get('party_level', 3))
            party_size = int(data.get('party_size', 4))
            
            # Validate monster data
            for monster in monsters:
                validate_input(monster, allowed_fields=['name', 'hp', 'ac', 'cr', 'ability_scores'])
            
            result = encounter_controller.handle_custom_encounter(monsters, party_level, party_size)
            return jsonify(result)
        except (ValueError, TypeError) as e:
            raise ValidationError(f"Invalid input data: {e}")
    return render_template('encounter_selection.html', tab='custom')

@app.route('/encounter/prebuilt', methods=['GET', 'POST'])
# @limiter.limit("20 per minute")  # Disabled for testing
def encounter_prebuilt():
    if request.method == 'POST':
        try:
            data = validate_input(request.get_json() or {})
            template_name = data.get('template_name')
            party_level = int(data.get('party_level', 3))
            party_size = int(data.get('party_size', 4))
            
            if not template_name:
                raise ValidationError("Template name is required")
            
            result = encounter_controller.handle_prebuilt_encounter(template_name, party_level, party_size)
            return jsonify(result)
        except (ValueError, TypeError) as e:
            raise ValidationError(f"Invalid input data: {e}")
    return render_template('encounter_selection.html', tab='prebuilt')

@app.route('/encounter/clear', methods=['POST'])
def encounter_clear():
    try:
        # Clear encounter data from session
        session.pop('encounter_monsters', None)
        session.pop('selected_encounter', None)
        return jsonify({'success': True, 'message': 'Encounter selection cleared'})
    except Exception as e:
        log_exception(e)
        return jsonify({'error': 'Failed to clear encounter selection'}), 500

@app.route('/api/monsters', methods=['GET'])
@limiter.limit("100 per minute")
def api_monsters():
    cr = request.args.get('cr')
    if cr and not re.match(r'^[0-9/]+$', cr):
        raise ValidationError("Invalid CR format")
    
    monsters = encounter_controller.builder.monster_data
    if cr:
        monsters = [m for m in monsters if str(m.get('cr')) == str(cr)]
    return jsonify(monsters)

@app.route('/api/encounter/balance', methods=['POST'])
@limiter.limit("50 per minute")
def api_encounter_balance():
    try:
        data = validate_input(request.get_json() or {}, max_length=5000)
        monsters = data.get('monsters', [])
        party_level = int(data.get('party_level', 3))
        party_size = int(data.get('party_size', 4))
        
        # Validate monster data
        for monster in monsters:
            validate_input(monster, allowed_fields=['name', 'hp', 'ac', 'cr', 'ability_scores'])
        
        balance = encounter_controller.validate_encounter_balance(monsters, party_level, party_size)
        warnings = encounter_controller.generate_encounter_warnings(monsters, party_level, party_size)
        return jsonify({'balance': balance, 'warnings': warnings})
    except (ValueError, TypeError) as e:
        raise ValidationError(f"Invalid input data: {e}")

@app.route('/api/encounters/prebuilt', methods=['GET'])
def api_prebuilt_encounters():
    try:
        with open('data/encounter_templates.json') as f:
            templates = json.load(f)["encounters"]
        return jsonify(templates)
    except Exception as e:
        log_exception(e)
        return jsonify({"error": "Failed to load prebuilt encounters"}), 500

@app.route('/api/party/current', methods=['GET'])
def api_current_party():
    try:
        selected_party_id = session.get('selected_party_id', 1)
        selected_party_level = session.get('selected_party_level', 5)
        party = PartyLoader.get_party_by_id(selected_party_id)
        if party:
            characters = party.get('characters', [])
            # Override all character levels with selected_party_level for display
            display_characters = []
            for char in characters:
                char_copy = char.copy()
                char_copy['level'] = selected_party_level
                display_characters.append(char_copy)
            party_level = selected_party_level
            party_size = len(characters)
            return jsonify({
                'party_id': selected_party_id,
                'party_level': party_level,
                'party_size': party_size,
                'characters': display_characters
            })
        else:
            return jsonify({
                'party_id': 1,
                'party_level': 1,
                'party_size': 4,
                'characters': []
            })
    except Exception as e:
        log_exception(e)
        return jsonify({
            'party_id': 1,
            'party_level': 1,
            'party_size': 4,
            'characters': []
        })

@app.route('/simulate', methods=['GET'])
# @limiter.limit("10 per minute")  # Disabled for testing
def simulate():
    # Start simulation if not already started
    session_id = session['session_id']
    
    # Ensure session exists in database before starting simulation
    db.create_session(session_id, selected_party_id=session.get('selected_party_id'))
    
    if not simulation_controller.simulation_states.get(session_id):
        # Load party and monsters from session
        selected_party_id = session.get('selected_party_id', 1)
        selected_party_level = session.get('selected_party_level', 5)
        party_obj = PartyLoader.get_party_with_level(selected_party_id, selected_party_level)
        if party_obj:
            party = party_obj.get('characters', [])
        else:
            party = []
        monsters = session.get('encounter_monsters', [])
        logging.info(f'/simulate: session_id={session.get("session_id")})')
        logging.info('/simulate: Monsters loaded from session:')
        for m in monsters:
            logging.info(f"Type: {type(m)}, Name: {getattr(m, 'name', None)}, Data: {m}")
        simulation_controller.execute_simulation(party, monsters, session_id, party_level=selected_party_level)
    return render_template('simulation.html')

@app.route('/simulate/status', methods=['GET'])
# @limiter.limit("30 per minute")  # Disabled for testing
def simulate_status():
    return simulation_controller.handle_simulation_progress()

@app.route('/simulate/results', methods=['GET'])
def simulate_results():
    # Redirect to results page (reuse existing logic)
    # You may want to pass sim_id or use last simulation for this session
    return redirect(url_for('results'))

@app.route('/batch', methods=['GET'])
def batch_simulation():
    """Show batch simulation interface."""
    return render_template('batch_simulation.html')

@app.route('/batch/start', methods=['POST'])
def batch_simulation_start():
    """Start a batch simulation."""
    try:
        data = validate_input(request.get_json() or {})
        num_runs = int(data.get('num_runs', 10))
        batch_name = data.get('batch_name', f'Batch {int(time.time())}')
        
        if num_runs < 1 or num_runs > 1000:
            raise ValidationError("Number of runs must be between 1 and 1000")
        
        # Load party and monsters from session
        session_id = session['session_id']
        selected_party_id = session.get('selected_party_id', 1)
        party = PartyLoader.get_party_by_id(selected_party_id)
        if party:
            party = party.get('characters', [])
        else:
            party = []
        monsters = session.get('encounter_monsters', [])
        
        if not party or not monsters:
            raise ValidationError("Party and monsters must be selected before starting batch simulation")
        
        # Start batch simulation
        batch_id = batch_simulation_controller.execute_batch_simulation(party, monsters, num_runs, batch_name, session_id)
        
        return jsonify({'success': True, 'message': 'Batch simulation started', 'batch_id': batch_id})
    except Exception as e:
        log_exception(e)
        return jsonify({'error': str(e)}), 400

@app.route('/batch/progress/<int:batch_id>', methods=['GET'])
def batch_simulation_progress(batch_id):
    """Get batch simulation progress."""
    try:
        progress = batch_simulation_controller.get_batch_progress(batch_id)
        return jsonify(progress)
    except Exception as e:
        log_exception(e)
        return jsonify({'error': str(e)}), 400

@app.route('/batch/results/<int:batch_id>', methods=['GET'])
def batch_simulation_results(batch_id):
    """Show batch simulation results."""
    try:
        results = batch_simulation_controller.get_batch_results(batch_id)
        return render_template('batch_results.html', results=results)
    except Exception as e:
        log_exception(e)
        return render_template('error.html', error=str(e)), 400

@app.route('/batch/history', methods=['GET'])
def batch_simulation_history():
    """Show batch simulation history."""
    try:
        history = batch_simulation_controller.get_batch_history(session['session_id'])
        return render_template('batch_history.html', batches=history)
    except Exception as e:
        log_exception(e)
        return render_template('error.html', error=str(e)), 400

@app.route('/api/batch/history', methods=['GET'])
def api_batch_history():
    """API endpoint for batch simulation history."""
    try:
        history = batch_simulation_controller.get_batch_history(session['session_id'])
        return jsonify(history)
    except Exception as e:
        log_exception(e)
        return jsonify({'error': str(e)}), 400

@app.route('/results')
def results():
    sim_id = request.args.get('sim_id', type=int)
    if sim_id and sim_id < 0:
        raise ValidationError("Invalid simulation ID")
    
    # If no sim_id provided, use the last simulation from the session or database
    if not sim_id:
        sim_id = session.get('last_simulation_id')
        if not sim_id:
            # Try to get the last simulation ID from the database
            session_id = session['session_id']
            sim_id = db.get_last_simulation_id(session_id)
        if not sim_id:
            # No simulation found, return empty results
            return render_template('results.html', 
                                 summary={'win_loss': 'No simulation found', 'party_status': 'No data'}, 
                                 statistics=[], 
                                 log=[], 
                                 sim_id=None)
    
    summary = results_controller.format_simulation_results(sim_id)
    statistics = results_controller.generate_combat_statistics(sim_id)
    log = [sanitize_html(str(entry)) for entry in summary['logs']]
    
    return render_template('results.html', summary=summary.get('simulation', {}), statistics=statistics, log=log, sim_id=sim_id)

@app.route('/results/detailed')
@limiter.limit("50 per minute")
def results_detailed():
    sim_id = request.args.get('sim_id', type=int)
    if sim_id and sim_id < 0:
        raise ValidationError("Invalid simulation ID")
    
    log = results_controller.handle_detailed_log_display(sim_id)
    return {'log': [sanitize_html(entry) for entry in log]}

@app.route('/results/statistics')
@limiter.limit("50 per minute")
def results_statistics():
    sim_id = request.args.get('sim_id', type=int)
    if sim_id and sim_id < 0:
        raise ValidationError("Invalid simulation ID")
    
    stats = results_controller.generate_combat_statistics(sim_id)
    return {'statistics': stats}

@app.route('/results/export')
@limiter.limit("20 per minute")
def results_export():
    sim_id = request.args.get('sim_id', type=int)
    if sim_id and sim_id < 0:
        raise ValidationError("Invalid simulation ID")
    
    # For now, export as JSON
    import json
    summary = results_controller.format_simulation_results(sim_id)
    return json.dumps(summary), 200, {'Content-Type': 'application/json'}

@app.route('/history')
def history():
    sims = db.get_simulation_history(session['session_id'])
    return render_template('history.html', simulations=sims)

@app.route('/healthz')
def healthz():
    return 'ok', 200

@app.errorhandler(AppError)
def handle_app_error(error):
    log_exception(error)
    # Render a user-friendly error page or JSON
    if request.accept_mimetypes.accept_json and not request.accept_mimetypes.accept_html:
        response = jsonify({'error': str(error), 'type': error.__class__.__name__})
        response.status_code = 400
        return response
    return render_template('error.html', error=error), 400

@app.errorhandler(Exception)
def handle_unexpected_error(error):
    log_exception(error)
    # Render a generic error page or JSON
    if request.accept_mimetypes.accept_json and not request.accept_mimetypes.accept_html:
        response = jsonify({'error': 'An unexpected error occurred.', 'type': error.__class__.__name__})
        response.status_code = 500
        return response
    return render_template('error.html', error='An unexpected error occurred.'), 500

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000) 