import logging
import logging.config
import os
from src.config import LOG_DIR


# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------

def setupLogging():
    os.makedirs(LOG_DIR, exist_ok=True)
    log_file = os.path.join("logdir", "main.py.log")
    logging.config.fileConfig('../resources/logging.conf',
                              defaults={'logfile': log_file},
                              disable_existing_loggers=False)