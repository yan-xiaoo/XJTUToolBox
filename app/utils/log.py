import logging
import os
import time

from .migrate_data import LOG_DIRECTORY


def get_logger(name, path):
    log = logging.getLogger(name)
    log.setLevel(logging.WARNING)
    formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s: %(message)s")
    ch = logging.StreamHandler()
    ch.setLevel(logging.WARNING)
    ch.setFormatter(formatter)
    file = logging.FileHandler(path)
    file.setFormatter(formatter)
    file.setLevel(logging.WARNING)
    log.addHandler(ch)
    log.addHandler(file)
    return log


logger = get_logger("default", os.path.join(LOG_DIRECTORY,
                                            f"{time.strftime('%Y-%m-%d', time.localtime())}.log"))
