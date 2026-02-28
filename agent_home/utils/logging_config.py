import logging
import os
from logging.handlers import RotatingFileHandler

def setup_logging(log_dir="agent/logs", log_file="events.log"):
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)

    log_path = os.path.join(log_dir, log_file)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[
            RotatingFileHandler(log_path, maxBytes=10*1024*1024, backupCount=5),
            logging.StreamHandler()
        ]
    )

    # Set libraries to warning to avoid noise
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)

    return logging.getLogger("HomeAgent")
