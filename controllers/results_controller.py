from models.db import DatabaseManager
from collections import defaultdict
from utils.exceptions import DatabaseError, ValidationError
from utils.logging import log_exception

class ResultsController:
    def __init__(self):
        self.db = DatabaseManager()

    def format_simulation_results(self, sim_id):
        try:
            sim = self.db.get_simulation(sim_id)
            logs = self.db.get_combat_logs(sim_id)
            
            # Format simulation data for template
            if sim:
                formatted_sim = {
                    'win_loss': sim.get('result', 'Unknown'),
                    'party_status': f"Rounds: {sim.get('rounds', 0)}, HP Remaining: {sim.get('party_hp_remaining', 0)}",
                    'encounter_type': sim.get('encounter_type', 'Unknown'),
                    'party_level': sim.get('party_level', 0),
                    'created_at': sim.get('created_at', ''),
                    'id': sim.get('id', 0)
                }
            else:
                formatted_sim = {
                    'win_loss': 'No data',
                    'party_status': 'No data',
                    'encounter_type': 'Unknown',
                    'party_level': 0,
                    'created_at': '',
                    'id': 0
                }
            
            return {'simulation': formatted_sim, 'logs': logs}
        except Exception as e:
            log_exception(e)
            raise DatabaseError(f"Failed to format simulation results: {e}")

    def generate_combat_statistics(self, sim_id):
        try:
            logs = self.db.get_combat_logs(sim_id)
            
            stats = defaultdict(lambda: {
                'name': '',
                'damage_dealt': 0,
                'damage_taken': 0,
                'spells_cast': 0,
                'crits': 0,
                'misses': 0,
                'healing': 0,
                'rounds': defaultdict(dict),
            })
            
            for log in logs:
                actor = log['character_name']
                target = log['target']
                action_type = log['action_type']
                result = log['result']
                damage = log['damage'] or 0
                round_num = log['round_number']
                
                # Keep individual monsters separate (e.g., "Kobold 1", "Kobold 2" stay distinct)
                actor_key = actor
                target_key = target if target else None
                
                # Set name
                stats[actor_key]['name'] = actor_key
                
                # Damage dealt
                if action_type in ('attack', 'spell', 'special') and damage > 0:
                    stats[actor_key]['damage_dealt'] += damage
                    stats[actor_key]['rounds'][round_num]['damage_dealt'] = stats[actor_key]['rounds'][round_num].get('damage_dealt', 0) + damage
                
                # Damage taken
                if target_key and damage > 0:
                    # Handle AoE spells with multiple targets (comma-separated)
                    if ', ' in target_key:
                        # Split targets and distribute damage evenly
                        targets = [t.strip() for t in target_key.split(',')]
                        damage_per_target = damage // len(targets) if len(targets) > 0 else damage
                        for individual_target in targets:
                            stats[individual_target]['name'] = individual_target
                            stats[individual_target]['damage_taken'] += damage_per_target
                            stats[individual_target]['rounds'][round_num]['damage_taken'] = stats[individual_target]['rounds'][round_num].get('damage_taken', 0) + damage_per_target
                    else:
                        # Single target
                        stats[target_key]['name'] = target_key  # Set target name
                        stats[target_key]['damage_taken'] += damage
                        stats[target_key]['rounds'][round_num]['damage_taken'] = stats[target_key]['rounds'][round_num].get('damage_taken', 0) + damage
                
                # Spells cast
                if action_type == 'spell':
                    stats[actor_key]['spells_cast'] += 1
                
                # Crits/misses
                if 'crit' in (result or '').lower():
                    stats[actor_key]['crits'] += 1
                if 'miss' in (result or '').lower():
                    stats[actor_key]['misses'] += 1
                
                # Healing
                if action_type == 'spell' and 'heal' in (result or '').lower():
                    stats[actor_key]['healing'] += abs(damage)
                    stats[actor_key]['rounds'][round_num]['healing'] = stats[actor_key]['rounds'][round_num].get('healing', 0) + abs(damage)
            
            # Flatten stats for table
            result_stats = list(stats.values())
            return result_stats
        except Exception as e:
            log_exception(e)
            raise ValidationError(f"Failed to generate combat statistics: {e}")

    def _get_base_name(self, name):
        """
        Extract the base name from a character/monster name.
        For example: "Kobold 1" -> "Kobold", "Goblin 2" -> "Goblin", "Arannis" -> "Arannis"
        """
        if not name:
            return name
        
        # Check if the name ends with a number (e.g., "Kobold 1", "Goblin 2", "Wolf 3")
        import re
        match = re.match(r'^(.+?)\s+\d+$', name)
        if match:
            return match.group(1)
        
        return name

    def handle_detailed_log_display(self, sim_id, filters=None):
        try:
            logs = self.db.get_combat_logs(sim_id)
            # TODO: Apply filters if provided
            return logs
        except Exception as e:
            log_exception(e)
            raise DatabaseError(f"Failed to get detailed log: {e}")

    def manage_result_navigation(self, action):
        try:
            # TODO: Implement navigation logic
            return {}
        except Exception as e:
            log_exception(e)
            raise ValidationError(f"Failed to manage result navigation: {e}") 