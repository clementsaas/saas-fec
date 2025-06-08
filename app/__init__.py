from flask import Flask, render_template, session, redirect, url_for, flash
import json
from flask_migrate import Migrate
from config.database import Config
from app.models import db

def create_app():
    # CORRECTION ICI : dire à Flask où sont les templates
    app = Flask(__name__, template_folder='../templates')
    app.config.from_object(Config)
    # Création du dossier uploads s'il n'existe pas
    import os
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    # Initialiser la base de données
    db.init_app(app)

    # Initialiser les migrations
    migrate = Migrate(app, db)

    # Importer TOUS nos modèles
    from app.models.organization import Organization
    from app.models.user import User
    from app.models.societe import Societe
    from app.models.fec_file import FecFile
    from app.models.ecriture_bancaire import EcritureBancaire
    from app.models.regle_affectation import RegleAffectation

    # Enregistrer les routes d'authentification
    from app.routes.auth import auth_bp
    app.register_blueprint(auth_bp)
    # Enregistrer les routes FEC
    from app.routes.fec_import import fec_bp
    app.register_blueprint(fec_bp)
    # Enregistrer les routes règles
    from app.routes.regles import regles_bp
    app.register_blueprint(regles_bp)

    @app.route('/')
    def home():
        """Page d'accueil - redirige selon si l'utilisateur est connecté"""
        if 'user_id' in session:
            return redirect(url_for('dashboard'))
        else:
            return redirect(url_for('auth.login'))

    @app.route('/dashboard')
    def dashboard():
        """Nouveau tableau de bord avancé - Page d'accueil après connexion"""
        if 'user_id' not in session:
            return redirect(url_for('auth.login'))

        # Récupérer l'organisation de l'utilisateur
        organization_id = session['organization_id']

        # Récupérer toutes les sociétés de l'organisation
        societes = Societe.query.filter_by(organization_id=organization_id).all()

        if not societes:
            # Aucune société - rediriger vers l'import FEC
            flash('Créez d\'abord une société en important un fichier FEC', 'info')
            return redirect(url_for('fec.import_fec'))

        # Prendre la première société ou celle avec le FEC le plus récent
        societe_active = societes[0]
        fec_actif = None

        # Chercher le FEC le plus récent pour cette société
        fec_actif = FecFile.query.filter_by(
            societe_id=societe_active.id,
            is_active=True
        ).order_by(FecFile.date_import.desc()).first()

        if not fec_actif:
            # Aucun FEC - rediriger vers l'import
            flash(f'Importez un fichier FEC pour la société {societe_active.nom}', 'info')
            return redirect(url_for('fec.import_fec'))

        # Récupérer les écritures bancaires
        ecritures = EcritureBancaire.query.filter_by(fec_file_id=fec_actif.id).all()

        # Récupérer les règles existantes
        regles_existantes = RegleAffectation.query.filter_by(societe_id=societe_active.id).all()

        # Calculer les statistiques (utiliser les fonctions du module regles)
        from app.routes.regles import calculer_statistiques_comptes, calculer_automatisation_globale

        comptes_statistiques = calculer_statistiques_comptes(ecritures, regles_existantes)
        automatisation_globale = calculer_automatisation_globale(ecritures, regles_existantes)

        # Préparer les écritures pour JavaScript
        from app.services.regle_tester import RegleTester
        tester = RegleTester()

        ecritures_couvertes = set()
        for regle in regles_existantes:
            if regle.is_active:
                matches = tester.test_regle_object(regle, ecritures)
                for match in matches:
                    ecritures_couvertes.add(match.id)

        ecritures_json = []
        for ecriture in ecritures:
            # Déterminer le compte de contrepartie
            if not ecriture.compte_final.startswith('512'):
                compte_contrepartie = ecriture.compte_final
            else:
                # Logique simplifiée pour trouver la contrepartie
                autres_ecritures = EcritureBancaire.query.filter_by(
                    fec_file_id=fec_actif.id,
                    ecriture_num=ecriture.ecriture_num
                ).filter(~EcritureBancaire.compte_num.startswith('512')).first()

                if autres_ecritures:
                    compte_contrepartie = autres_ecritures.compte_final
                else:
                    compte_contrepartie = "AUTRE"

            ecritures_json.append({
                'id': ecriture.id,
                'ecriture_lib': ecriture.ecriture_lib,
                'journal_code': ecriture.journal_code,
                'ecriture_date': ecriture.ecriture_date.strftime('%d/%m/%Y'),
                'ecriture_num': ecriture.ecriture_num,
                'piece_ref': ecriture.piece_ref,
                'montant': float(ecriture.montant) if ecriture.sens == 'D' else -float(ecriture.montant),
                'compte_contrepartie': compte_contrepartie,
                'couverte_par_regle': ecriture.id in ecritures_couvertes
            })

        # Récupérer les journaux
        journaux = db.session.query(
            EcritureBancaire.journal_code,
            EcritureBancaire.journal_lib
        ).filter_by(fec_file_id=fec_actif.id).distinct().all()

        return render_template('dashboard_advanced.html',
                               societe_active=societe_active,
                               societes=societes,
                               fec_actif=fec_actif,
                               comptes_statistiques=comptes_statistiques,
                               automatisation_globale=automatisation_globale,
                               ecritures_json=json.dumps(ecritures_json),
                               journaux=journaux)

    # Fonction pour rendre l'utilisateur disponible dans tous les templates
    @app.context_processor
    def inject_user():
        current_user = None
        if 'user_id' in session:
            from app.models.user import User
            current_user = User.query.get(session['user_id'])
        return dict(current_user=current_user)

    return app