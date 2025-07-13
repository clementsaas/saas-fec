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


# Handlers d'erreur spécifiques pour identifier les crashes
@app.errorhandler(404)
def not_found_error(e):
    from flask import request
    error_msg = f"PAGE INTROUVABLE: {request.url} - Référent: {request.referrer}"
    print(f"🔍 {error_msg}")
    app.logger.warning(error_msg)
    return "Page non trouvée", 404


@app.errorhandler(MemoryError)
def memory_error(e):
    try:
        import psutil
        memory_percent = psutil.virtual_memory().percent
    except:
        memory_percent = "N/A"
    error_msg = f"CRASH MÉMOIRE: {str(e)} - Utilisation: {memory_percent}%"
    print(f"🧠 {error_msg}")
    app.logger.critical(error_msg)
    return "Mémoire insuffisante - FEC trop volumineux", 500


@app.errorhandler(KeyError)
def key_error(e):
    import traceback
    from flask import request
    error_msg = f"VARIABLE MANQUANTE: {str(e)} - Route: {request.endpoint} - Données: {request.form.to_dict()}"
    print(f"🔑 {error_msg}")
    app.logger.error(f"{error_msg}\n{traceback.format_exc()}")
    return f"Données manquantes: {str(e)}", 400


@app.errorhandler(ValueError)
def value_error(e):
    import traceback
    from flask import request
    error_msg = f"DONNÉES INVALIDES: {str(e)} - Route: {request.endpoint}"
    print(f"📊 {error_msg}")
    app.logger.error(f"{error_msg}\n{traceback.format_exc()}")
    return f"Format de données incorrect: {str(e)}", 400


@app.errorhandler(Exception)
def handle_exception(e):
    import traceback
    from flask import request
    from datetime import datetime

    # Informations contextuelles détaillées
    crash_id = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    try:
        import psutil
        memory_percent = psutil.virtual_memory().percent
        cpu_percent = psutil.cpu_percent()
    except:
        memory_percent = "N/A"
        cpu_percent = "N/A"

    error_msg = f"""
🚨 CRASH GÉNÉRAL - ID: {crash_id}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
❌ Type: {type(e).__name__}
📝 Message: {str(e)}
🌐 Route: {request.endpoint}
📍 URL: {request.url}
🔧 Méthode: {request.method}
💻 Mémoire: {memory_percent}% | CPU: {cpu_percent}%
📊 Données POST: {request.form.to_dict() if request.method == 'POST' else 'N/A'}
🔍 Stack trace:
{traceback.format_exc()}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    """

    print(error_msg)
    app.logger.critical(error_msg)

    # Message utilisateur selon le type d'erreur
    if 'societe' in str(e).lower() or 'society' in str(e).lower():
        return f"Erreur société - ID: {crash_id}", 500
    elif 'fec' in str(e).lower():
        return f"Erreur traitement FEC - ID: {crash_id}", 500
    else:
        return f"Erreur système - ID: {crash_id}", 500

if __name__ == '__main__':
    app.run(debug=True, use_reloader=False)  # use_reloader=False évite les doubles logs