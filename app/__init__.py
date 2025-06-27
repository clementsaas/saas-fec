from flask import Flask, render_template, session, redirect, url_for, flash, jsonify
import json
from flask_migrate import Migrate
from config.database import Config
from app.models import db


def create_app():
    # CORRECTION ICI : dire à Flask où sont les templates
    app = Flask(__name__, template_folder='../templates', static_folder='../static')
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
    # Enregistrer les routes API
    from app.routes.api import api_bp
    app.register_blueprint(api_bp)

    @app.route('/')
    def home():
        """Page d'accueil - redirige selon si l'utilisateur est connecté"""
        if 'user_id' in session:
            return redirect(url_for('dashboard'))
        else:
            return redirect(url_for('auth.login'))

    @app.route('/dashboard')
    def dashboard():
        """Page de sélection de société"""
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

        # Si une seule société, redirection automatique
        if len(societes) == 1:
            return redirect(url_for('societe_dashboard', societe_id=societes[0].id))

        # Sinon, afficher la page de sélection
        return render_template('dashboard_selector.html', societes=societes)

    @app.route('/societe/<int:societe_id>')
    def societe_dashboard(societe_id):
        """Dashboard d'une société spécifique avec données dynamiques"""
        if 'user_id' not in session:
            return redirect(url_for('auth.login'))

        try:
            # Vérifier que l'utilisateur a accès à cette société
            organization_id = session['organization_id']
            societe = Societe.query.filter_by(
                id=societe_id,
                organization_id=organization_id
            ).first_or_404()

            # Récupérer toutes les sociétés pour le dropdown
            societes = Societe.query.filter_by(organization_id=organization_id).all()

            # Chercher le FEC le plus récent pour cette société
            fec_actif = FecFile.query.filter_by(
                societe_id=societe.id,
                is_active=True
            ).order_by(FecFile.date_import.desc()).first()

            if not fec_actif:
                # Aucun FEC pour cette société - passer des données vides
                return render_template('societe_dashboard.html',
                                       societe=societe,
                                       societes=societes,
                                       ecritures_json='[]',
                                       comptes_statistiques='[]',
                                       journaux='[]',
                                       automatisation_globale=0)

            # Récupérer les écritures bancaires
            ecritures = EcritureBancaire.query.filter_by(fec_file_id=fec_actif.id).all()

            # Récupérer les règles existantes
            regles_existantes = RegleAffectation.query.filter_by(societe_id=societe.id).all()

            # Calculer les statistiques
            from app.routes.regles import calculer_statistiques_comptes, calculer_automatisation_globale

            comptes_statistiques = calculer_statistiques_comptes(ecritures, regles_existantes)
            automatisation_globale = calculer_automatisation_globale(ecritures, regles_existantes)

            # Trier par "% à faire" décroissant comme demandé
            comptes_statistiques.sort(key=lambda x: x['pourcentage_a_faire'], reverse=True)

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
                # CORRECTION : Utiliser les nouveaux champs compte_contrepartie et libelle_contrepartie
                if hasattr(ecriture, 'compte_contrepartie') and ecriture.compte_contrepartie:
                    compte_contrepartie = ecriture.compte_contrepartie
                else:
                    # Fallback vers l'ancienne logique
                    if not ecriture.compte_final.startswith('512'):
                        compte_contrepartie = ecriture.compte_final
                    else:
                        compte_contrepartie = "AUTRE"

                ecritures_json.append({
                    'id': ecriture.id,
                    'ecriture_lib': ecriture.ecriture_lib,
                    'journal_code': ecriture.journal_code,
                    'journal_lib': ecriture.journal_lib,
                    'ecriture_date': ecriture.ecriture_date.strftime('%d/%m/%Y'),
                    'ecriture_num': ecriture.ecriture_num,
                    'piece_ref': ecriture.piece_ref,
                    'montant': float(ecriture.montant) if ecriture.sens == 'D' else -float(ecriture.montant),
                    'sens': ecriture.sens,
                    'compte_final': ecriture.compte_final,
                    'libelle_final': ecriture.libelle_final,
                    'compte_contrepartie': compte_contrepartie,
                    'couverte_par_regle': ecriture.id in ecritures_couvertes
                })

            # Récupérer les journaux
            journaux = db.session.query(
                EcritureBancaire.journal_code,
                EcritureBancaire.journal_lib
            ).filter_by(fec_file_id=fec_actif.id).distinct().all()

            journaux_json = [
                {
                    'journal_code': j.journal_code,
                    'journal_lib': j.journal_lib
                }
                for j in journaux
            ]

            return render_template('societe_dashboard.html',
                                   societe=societe,
                                   societes=societes,
                                   fec_actif=fec_actif,
                                   comptes_statistiques=json.dumps(comptes_statistiques),
                                   automatisation_globale=automatisation_globale,
                                   ecritures_json=json.dumps(ecritures_json),
                                   journaux=json.dumps(journaux_json))

        except Exception as e:
            print(f"Erreur dashboard société: {e}")
            flash('Erreur lors du chargement du dashboard', 'error')
            return redirect(url_for('dashboard'))


        except Exception as e:
            print(f"Erreur API dashboard: {e}")
            return jsonify({'success': False, 'error': 'Erreur interne'}), 500

    # Fonction pour rendre l'utilisateur disponible dans tous les templates
    @app.context_processor
    def inject_user():
        current_user = None
        if 'user_id' in session:
            from app.models.user import User
            current_user = User.query.get(session['user_id'])
        return dict(current_user=current_user)

    @app.route('/api/societe/<int:societe_id>/dashboard-data')
    def get_dashboard_data(societe_id):
        """API pour récupérer les données du dashboard en AJAX"""
        if 'user_id' not in session:
            return jsonify({'success': False, 'error': 'Non connecté'}), 401

        try:
            # Vérifier les permissions
            organization_id = session['organization_id']
            societe = Societe.query.filter_by(
                id=societe_id,
                organization_id=organization_id
            ).first()

            if not societe:
                return jsonify({'success': False, 'error': 'Société non trouvée'}), 403

            # Récupérer le FEC le plus récent
            fec_actif = FecFile.query.filter_by(
                societe_id=societe_id,
                is_active=True
            ).order_by(FecFile.date_import.desc()).first()

            if not fec_actif:
                return jsonify({
                    'success': True,
                    'ecritures': [],
                    'comptes_statistiques': [],
                    'journaux': [],
                    'automatisation_globale': 0
                })

            # Récupérer les écritures
            ecritures = EcritureBancaire.query.filter_by(fec_file_id=fec_actif.id).all()

            # Récupérer les règles
            regles_existantes = RegleAffectation.query.filter_by(societe_id=societe_id).all()

            # Calculer les statistiques
            from app.routes.regles import calculer_statistiques_comptes, calculer_automatisation_globale
            comptes_statistiques = calculer_statistiques_comptes(ecritures, regles_existantes)
            automatisation_globale = calculer_automatisation_globale(ecritures, regles_existantes)

            # Préparer les écritures pour JavaScript
            ecritures_json = []
            for ecriture in ecritures:
                # CORRECTION : Utiliser les nouveaux champs
                if hasattr(ecriture, 'compte_contrepartie') and ecriture.compte_contrepartie:
                    compte_contrepartie = ecriture.compte_contrepartie
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
                    'couverte_par_regle': False
                })

            # Récupérer les journaux
            journaux = db.session.query(
                EcritureBancaire.journal_code,
                EcritureBancaire.journal_lib
            ).filter_by(fec_file_id=fec_actif.id).distinct().all()

            journaux_json = [{'journal_code': j.journal_code, 'journal_lib': j.journal_lib} for j in journaux]

            return jsonify({
                'success': True,
                'ecritures': ecritures_json,
                'comptes_statistiques': comptes_statistiques,
                'journaux': journaux_json,
                'automatisation_globale': automatisation_globale
            })

        except Exception as e:
            print(f"Erreur API dashboard: {e}")
            return jsonify({'success': False, 'error': 'Erreur interne'}), 500

    return app

    return app