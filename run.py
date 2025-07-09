# Dans run.py
from app import create_app
import logging
import sys

# Configuration du logging détaillé
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('affectia_debug.log'),
        logging.StreamHandler(sys.stdout)
    ]
)

app = create_app()

# Handler d'erreur global
@app.errorhandler(Exception)
def handle_exception(e):
    import traceback
    error_msg = f"CRASH DÉTECTÉ: {str(e)}\n{traceback.format_exc()}"
    print(f"🚨 {error_msg}")
    app.logger.error(error_msg)
    return "Erreur interne - voir logs", 500

if __name__ == '__main__':
    app.run(debug=True, use_reloader=False)  # use_reloader=False évite les doubles logs