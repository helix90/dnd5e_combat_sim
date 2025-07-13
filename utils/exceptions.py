class AppError(Exception):
    """Base class for all application-specific errors."""
    pass

class APIError(AppError):
    """Raised when an API call fails or returns invalid data."""
    pass

class DatabaseError(AppError):
    """Raised for database connection or query errors."""
    pass

class ValidationError(AppError):
    """Raised for input or data validation errors."""
    pass

class SimulationError(Exception):
    """Raised when a simulation fails to execute properly."""
    pass

class BatchSimulationError(Exception):
    """Raised when a batch simulation fails to execute properly."""
    pass

class SessionError(Exception):
    """Raised for session management errors."""
    pass 