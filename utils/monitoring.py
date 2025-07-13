"""
Monitoring and analytics for D&D 5e Combat Simulator.
"""

import time
import psutil
import threading
from typing import Dict, Any, Optional, List
from collections import defaultdict, deque
from datetime import datetime, timedelta
import json
import os
from utils.logging import log_exception

class PerformanceMonitor:
    """Monitor application performance metrics."""
    
    def __init__(self):
        self.metrics = defaultdict(lambda: deque(maxlen=1000))
        self.start_time = time.time()
        self._lock = threading.Lock()
    
    def record_timing(self, operation: str, duration: float):
        """Record timing for an operation."""
        with self._lock:
            self.metrics[f"timing_{operation}"].append({
                'timestamp': time.time(),
                'duration': duration
            })
    
    def record_counter(self, metric: str, value: int = 1):
        """Record a counter metric."""
        with self._lock:
            self.metrics[f"counter_{metric}"].append({
                'timestamp': time.time(),
                'value': value
            })
    
    def get_metrics(self, metric_type: str = None) -> Dict[str, Any]:
        """Get current metrics."""
        with self._lock:
            if metric_type:
                return {k: list(v) for k, v in self.metrics.items() if k.startswith(metric_type)}
            return {k: list(v) for k, v in self.metrics.items()}
    
    def get_system_stats(self) -> Dict[str, Any]:
        """Get current system statistics."""
        try:
            cpu_percent = psutil.cpu_percent(interval=1)
            memory = psutil.virtual_memory()
            disk = psutil.disk_usage('/')
            
            return {
                'cpu_percent': cpu_percent,
                'memory_percent': memory.percent,
                'memory_available': memory.available,
                'disk_percent': disk.percent,
                'disk_free': disk.free,
                'uptime': time.time() - self.start_time
            }
        except Exception as e:
            log_exception(e)
            return {'error': str(e)}

class ErrorTracker:
    """Track and analyze errors."""
    
    def __init__(self):
        self.errors = deque(maxlen=1000)
        self.error_counts = defaultdict(int)
        self._lock = threading.Lock()
    
    def record_error(self, error: Exception, context: Dict[str, Any] = None):
        """Record an error with context."""
        with self._lock:
            error_info = {
                'timestamp': datetime.now().isoformat(),
                'error_type': type(error).__name__,
                'error_message': str(error),
                'context': context or {}
            }
            self.errors.append(error_info)
            self.error_counts[type(error).__name__] += 1
    
    def get_error_summary(self) -> Dict[str, Any]:
        """Get error summary statistics."""
        with self._lock:
            return {
                'total_errors': len(self.errors),
                'error_counts': dict(self.error_counts),
                'recent_errors': list(self.errors)[-10:]  # Last 10 errors
            }
    
    def get_errors_by_type(self, error_type: str) -> List[Dict[str, Any]]:
        """Get all errors of a specific type."""
        with self._lock:
            return [e for e in self.errors if e['error_type'] == error_type]

class UserAnalytics:
    """Privacy-compliant user analytics."""
    
    def __init__(self):
        self.sessions = defaultdict(lambda: {
            'start_time': None,
            'actions': [],
            'simulations': 0,
            'last_activity': None
        })
        self.aggregate_stats = {
            'total_sessions': 0,
            'total_simulations': 0,
            'popular_parties': defaultdict(int),
            'popular_encounters': defaultdict(int)
        }
        self._lock = threading.Lock()
    
    def track_session_start(self, session_id: str):
        """Track when a session starts."""
        with self._lock:
            if session_id not in self.sessions:
                self.aggregate_stats['total_sessions'] += 1
            self.sessions[session_id]['start_time'] = datetime.now()
            self.sessions[session_id]['last_activity'] = datetime.now()
    
    def track_action(self, session_id: str, action: str, metadata: Dict[str, Any] = None):
        """Track user actions (privacy-compliant)."""
        with self._lock:
            if session_id in self.sessions:
                self.sessions[session_id]['actions'].append({
                    'action': action,
                    'timestamp': datetime.now().isoformat(),
                    'metadata': metadata or {}
                })
                self.sessions[session_id]['last_activity'] = datetime.now()
    
    def track_simulation(self, session_id: str, party_id: int = None, encounter_type: str = None):
        """Track simulation events."""
        with self._lock:
            if session_id in self.sessions:
                self.sessions[session_id]['simulations'] += 1
                self.aggregate_stats['total_simulations'] += 1
                
                if party_id:
                    self.aggregate_stats['popular_parties'][party_id] += 1
                if encounter_type:
                    self.aggregate_stats['popular_encounters'][encounter_type] += 1
    
    def get_analytics_summary(self) -> Dict[str, Any]:
        """Get analytics summary (privacy-compliant)."""
        with self._lock:
            # Clean up old sessions (older than 24 hours)
            cutoff = datetime.now() - timedelta(hours=24)
            active_sessions = {
                k: v for k, v in self.sessions.items() 
                if v['last_activity'] and v['last_activity'] > cutoff
            }
            
            return {
                'active_sessions': len(active_sessions),
                'total_sessions': self.aggregate_stats['total_sessions'],
                'total_simulations': self.aggregate_stats['total_simulations'],
                'popular_parties': dict(self.aggregate_stats['popular_parties']),
                'popular_encounters': dict(self.aggregate_stats['popular_encounters'])
            }
    
    def cleanup_old_sessions(self, hours: int = 24):
        """Clean up old session data."""
        with self._lock:
            cutoff = datetime.now() - timedelta(hours=hours)
            old_sessions = [
                k for k, v in self.sessions.items() 
                if v['last_activity'] and v['last_activity'] <= cutoff
            ]
            for session_id in old_sessions:
                del self.sessions[session_id]

class HealthMonitor:
    """Monitor system health and generate alerts."""
    
    def __init__(self, performance_monitor: PerformanceMonitor, error_tracker: ErrorTracker):
        self.performance_monitor = performance_monitor
        self.error_tracker = error_tracker
        self.alerts = deque(maxlen=100)
        self.thresholds = {
            'cpu_percent': 80,
            'memory_percent': 85,
            'error_rate': 10,  # errors per minute
            'response_time': 2.0  # seconds
        }
    
    def check_health(self) -> Dict[str, Any]:
        """Perform health check and return status."""
        health_status = {
            'status': 'healthy',
            'checks': {},
            'alerts': []
        }
        
        # Check system resources
        system_stats = self.performance_monitor.get_system_stats()
        if 'error' not in system_stats:
            if system_stats['cpu_percent'] > self.thresholds['cpu_percent']:
                health_status['checks']['cpu'] = 'warning'
                health_status['alerts'].append(f"High CPU usage: {system_stats['cpu_percent']}%")
            
            if system_stats['memory_percent'] > self.thresholds['memory_percent']:
                health_status['checks']['memory'] = 'warning'
                health_status['alerts'].append(f"High memory usage: {system_stats['memory_percent']}%")
        
        # Check error rate
        error_summary = self.error_tracker.get_error_summary()
        if error_summary['total_errors'] > self.thresholds['error_rate']:
            health_status['checks']['errors'] = 'warning'
            health_status['alerts'].append(f"High error rate: {error_summary['total_errors']} errors")
        
        # Check response times
        timing_metrics = self.performance_monitor.get_metrics('timing_')
        for operation, timings in timing_metrics.items():
            if timings:
                avg_time = sum(t['duration'] for t in timings[-10:]) / len(timings[-10:])
                if avg_time > self.thresholds['response_time']:
                    health_status['checks'][operation] = 'warning'
                    health_status['alerts'].append(f"Slow {operation}: {avg_time:.2f}s average")
        
        # Update overall status
        if any(check == 'warning' for check in health_status['checks'].values()):
            health_status['status'] = 'degraded'
        
        return health_status
    
    def generate_alert(self, message: str, severity: str = 'warning'):
        """Generate an alert."""
        alert = {
            'timestamp': datetime.now().isoformat(),
            'message': message,
            'severity': severity
        }
        self.alerts.append(alert)
        log_exception(f"ALERT [{severity.upper()}]: {message}")

# Global monitoring instances
performance_monitor = PerformanceMonitor()
error_tracker = ErrorTracker()
user_analytics = UserAnalytics()
health_monitor = HealthMonitor(performance_monitor, error_tracker)

def track_performance(operation: str):
    """Decorator to track performance of functions."""
    def decorator(func):
        def wrapper(*args, **kwargs):
            start_time = time.time()
            try:
                result = func(*args, **kwargs)
                duration = time.time() - start_time
                performance_monitor.record_timing(operation, duration)
                return result
            except Exception as e:
                error_tracker.record_error(e, {'operation': operation})
                raise
        return wrapper
    return decorator

def track_user_action(session_id: str, action: str, metadata: Dict[str, Any] = None):
    """Track a user action."""
    user_analytics.track_action(session_id, action, metadata) 