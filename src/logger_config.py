import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

# Creamos la carpeta de logs si no existe
LOG_DIR = Path(__file__).resolve().parent.parent / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

def setup_logger(name="centinela"):
    logger = logging.getLogger(name)
    
    # Si el logger ya tiene manejadores, no los dupliques (evita que se escriba doble)
    if logger.handlers:
        return logger

    logger.setLevel(logging.DEBUG)

    # 1. Formato del log (Fecha - Nivel - Mensaje)
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')

    # 2. Manejador para guardar en archivo (todo se guarda en logs/centinela.log)
    file_handler = RotatingFileHandler(LOG_DIR / "centinela.log", maxBytes=1_000_000,
                                       backupCount=3, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)

    # 3. Manejador para ver en la consola (solo INFO, WARNING y ERROR)
    # La consola de Windows usa cp1252 por defecto y no soporta emojis
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)

    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

    return logger