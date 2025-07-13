import logging
import os
import sys
from datetime import datetime

LOG_DIR = os.path.join(os.path.dirname(__file__), '..', 'logs')
os.makedirs(LOG_DIR, exist_ok=True)
LOG_FILE = os.path.join(LOG_DIR, f'app_{datetime.now().strftime("%Y%m%d")}.log')

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(name)s %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler(sys.stdout)
    ]
)

logger = logging.getLogger('dnd5e_combat_sim')

def log_exception(exc, extra_info=None):
    import traceback
    logger.error('Exception occurred: %s', exc)
    logger.error('Traceback:\n%s', traceback.format_exc())
    if extra_info:
        logger.error('Context: %s', extra_info) 