from flask import Blueprint, render_template, request, redirect, url_for, flash, session, jsonify, current_app
import json
from app.models import db
from app.models.fec_file import FecFile
from app.models.ecriture_bancaire import EcritureBancaire
from app.models.regle_affectation import RegleAffectation
from app.models.societe import Societe

# Blueprint pour les routes de règles
regles_bp = Blueprint('regles', __name__)

@regles_bp.route('/regles/nouvelle')
def nouvelle_regle():
    """Page de création d'une nouvelle règle avec interface avancée"""
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))

    fec_id = request.args.get('fec_id')
    societe_id = request.args.get('societe_id')

    if not fec_id:
        flash('ID du fichier FEC manquant', 'error')
        return redirect(url_for('dashboard'))

    # Récupérer le fichier FEC
    fec_file = FecFile.query.get_or_404(fec_id)

    # Déterminer la société
    if societe_id:
        societe = Societe.query.get_or_404(societe_id)
    else:
        societe = Societe.query.get(fec_file.societe_id)

    # Vérifier que l'utilisateur a accès (même organisation)
    if societe.organization_id != session['organization_id']:
        flash('Accès non autorisé', 'error')
        return redirect(url_for('dashboard'))

    # Récupérer toutes les sociétés de l'organisation pour le sélecteur
    societes = Societe.query.filter_by(organization_id=session['organization_id']).all()

    # Récupérer les écritures bancaires pour la société
    ecritures = EcritureBancaire.query.filter_by(fec_file_id=fec_id).all()

    # Récupérer les règles existantes pour détecter les collisions
    regles_existantes = RegleAffectation.query.filter_by(societe_id=societe.id).all()

    # Calculer les statistiques par compte de contrepartie
    comptes_statistiques = calculer_statistiques_comptes(ecritures, regles_existantes)

    # Calculer l'automatisation globale
    automatisation_globale = calculer_automatisation_globale(ecritures, regles_existantes)

    # Préparer les écritures pour JavaScript avec info de couverture
    ecritures_json = []
    ecritures_couvertes = set()

    # Identifier les écritures couvertes par les règles existantes
    from app.services.regle_tester import RegleTester
    tester = RegleTester()

    for regle in regles_existantes:
        if regle.is_active:
            matches = tester.test_regle_object(regle, ecritures)
            for match in matches:
                ecritures_couvertes.add(match.id)

    for ecriture in ecritures:
        # Calculer le compte de contrepartie (tous les comptes sauf 512*)
        compte_contrepartie = None
        libelle_contrepartie = None

        # Dans le FEC, on doit chercher les autres lignes de la même écriture
        # Pour simplifier, on prend le compte_final si ce n'est pas un 512*
        if not ecriture.compte_final.startswith('512'):
            compte_contrepartie = ecriture.compte_final
            libelle_contrepartie = ecriture.libelle_final
        else:
            # Logique plus complexe pour trouver la contrepartie
            # Pour l'instant, on utilise une logique simplifiée
            autres_ecritures = EcritureBancaire.query.filter_by(
                fec_file_id=fec_id,
                ecriture_num=ecriture.ecriture_num
            ).filter(~EcritureBancaire.compte_num.startswith('512')).first()

            if autres_ecritures:
                compte_contrepartie = autres_ecritures.compte_final
                libelle_contrepartie = autres_ecritures.libelle_final
            else:
                compte_contrepartie = "AUTRE"
                libelle_contrepartie = "Compte non identifié"

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
            'libelle_contrepartie': libelle_contrepartie,
            'couverte_par_regle': ecriture.id in ecritures_couvertes
        })

    # Récupérer la liste des journaux
    journaux = db.session.query(
        EcritureBancaire.journal_code,
        EcritureBancaire.journal_lib
    ).filter_by(fec_file_id=fec_id).distinct().all()

    # Préparer les règles existantes pour JavaScript
    regles_json = []
    for regle in regles_existantes:
        regles_json.append({
            'id': regle.id,
            'nom': regle.nom,
            'mots_cles': regle.mots_cles,
            'journal_code': regle.journal_code,
            'criteres_montant': regle.criteres_montant,
            'compte_destination': regle.compte_destination
        })

    return render_template('create_regle.html',
                           fec_file=fec_file,
                           societe=societe,
                           societes=societes,
                           ecritures_json=json.dumps(ecritures_json),
                           regles_existantes=json.dumps(regles_json),
                           journaux=journaux,
                           comptes_statistiques=comptes_statistiques,
                           automatisation_globale=automatisation_globale)

@regles_bp.route('/regles/create', methods=['POST'])
def create_regle():
    """API pour créer une nouvelle règle (AJAX)"""
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Non connecté'}), 401

    try:
        data = request.get_json()

        # Validation des données
        if not all([data.get('nom'), data.get('mots_cles'),
                    data.get('compte_destination'), data.get('libelle_destination'),
                    data.get('fec_id')]):
            return jsonify({'success': False, 'error': 'Champs obligatoires manquants'})

        # Récupérer le fichier FEC et vérifier les permissions
        fec_file = FecFile.query.get(data['fec_id'])
        if not fec_file:
            return jsonify({'success': False, 'error': 'Fichier FEC introuvable'})

        societe = Societe.query.get(fec_file.societe_id)
        if societe.organization_id != session['organization_id']:
            return jsonify({'success': False, 'error': 'Accès non autorisé'})

        # Vérifier qu'une règle avec ce nom n'existe pas déjà
        existing_regle = RegleAffectation.query.filter_by(
            nom=data['nom'],
            societe_id=societe.id
        ).first()

        if existing_regle:
            return jsonify({'success': False, 'error': 'Une règle avec ce nom existe déjà'})

        # Calculer les statistiques de couverture
        from app.services.regle_tester import RegleTester
        tester = RegleTester()

        ecritures = EcritureBancaire.query.filter_by(fec_file_id=data['fec_id']).all()
        matching_ecritures = tester.test_regle(data, ecritures)

        nb_transactions_couvertes = len(matching_ecritures)
        total_ecritures = len(ecritures)
        pourcentage_couverture_total = (nb_transactions_couvertes / total_ecritures * 100) if total_ecritures > 0 else 0

        # Créer la règle
        regle = RegleAffectation(
            nom=data['nom'],
            mots_cles=data['mots_cles'],
            criteres_montant=data.get('criteres_montant'),
            journal_code=data.get('journal_code'),
            compte_destination=data['compte_destination'],
            libelle_destination=data['libelle_destination'],
            nb_transactions_couvertes=nb_transactions_couvertes,
            pourcentage_couverture_total=round(pourcentage_couverture_total, 2),
            societe_id=societe.id
        )

        db.session.add(regle)
        db.session.commit()

        return jsonify({
            'success': True,
            'regle_id': regle.id,
            'stats': {
                'nb_transactions_couvertes': nb_transactions_couvertes,
                'pourcentage_couverture_total': round(pourcentage_couverture_total, 2)
            }
        })

    except Exception as e:
        db.session.rollback()
        print(f"Erreur création règle: {e}")
        return jsonify({'success': False, 'error': 'Erreur interne du serveur'})


@regles_bp.route('/regles/liste')
def liste_regles():
    """Page de gestion des règles existantes"""
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))

    fec_id = request.args.get('fec_id')
    if not fec_id:
        # Afficher toutes les règles de l'organisation
        societes = Societe.query.filter_by(organization_id=session['organization_id']).all()
        societe_ids = [s.id for s in societes]
        regles = RegleAffectation.query.filter(RegleAffectation.societe_id.in_(societe_ids)).all()
        fec_file = None
    else:
        # Afficher les règles pour un FEC spécifique
        fec_file = FecFile.query.get_or_404(fec_id)
        societe = Societe.query.get(fec_file.societe_id)
        if societe.organization_id != session['organization_id']:
            flash('Accès non autorisé', 'error')
            return redirect(url_for('dashboard'))
        regles = RegleAffectation.query.filter_by(societe_id=societe.id).all()

    # Préparer les données JSON pour JavaScript
    regles_json = []
    for regle in regles:
        # Récupérer le libellé du compte depuis la table societes
        societe = Societe.query.get(regle.societe_id)

        regles_json.append({
            'id': regle.id,
            'nom': regle.nom,
            'compte': regle.compte_destination,
            'libelle_compte': regle.libelle_destination,
            'mots_cles': regle.mots_cles or [],
            'banque': regle.journal_code or '',
            'critere_montant': regle.criteres_montant or {},
            'impact': float(regle.pourcentage_couverture_total or 0),
            'collision': 0.0,
            'nb_transactions': regle.nb_transactions_couvertes or 0,
            'nb_collisions': 0,
            'active': bool(regle.is_active),
            'created_at': regle.created_at.isoformat() if regle.created_at else ''
        })

    # Ligne supprimée - pas de remplacement
    # Assurer que regles_json est bien défini même si vide
    if not regles_json:
        regles_json = []

    # Log pour debug
    current_app.logger.info(f"Nombre de regles trouvees: {len(regles)}")
    current_app.logger.info(f"Nombre de regles JSON: {len(regles_json)}")

    # Convertir en JSON valide
    regles_json_string = json.dumps(regles_json, ensure_ascii=False, default=str)

    return render_template('liste_regles.html',
                           regles=regles,
                           fec_file=fec_file,
                           regles_json=regles_json_string)

@regles_bp.route('/regles/<int:regle_id>/delete', methods=['POST'])
def delete_regle(regle_id):
    """Supprimer une règle"""
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Non connecté'}), 401

    try:
        regle = RegleAffectation.query.get_or_404(regle_id)

        # Vérifier les permissions
        societe = Societe.query.get(regle.societe_id)
        if societe.organization_id != session['organization_id']:
            return jsonify({'success': False, 'error': 'Accès non autorisé'})

        db.session.delete(regle)
        db.session.commit()

        return jsonify({'success': True})

    except Exception as e:
        db.session.rollback()
        print(f"Erreur suppression règle: {e}")
        return jsonify({'success': False, 'error': 'Erreur interne du serveur'})


@regles_bp.route('/regles/test-collision', methods=['POST'])
def test_collision():
    """API pour tester une règle et calculer la collision en temps réel"""
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Non connecté'}), 401

    try:
        data = request.get_json()

        # Validation des données
        if not all([data.get('mots_cles'), data.get('fec_id'), data.get('compte_selectionne')]):
            return jsonify({'success': False, 'error': 'Paramètres manquants'})

        # Récupérer les écritures
        fec_id = data['fec_id']
        compte_selectionne = data['compte_selectionne']

        ecritures = EcritureBancaire.query.filter_by(fec_file_id=fec_id).all()

        # Récupérer les règles existantes actives
        fec_file = FecFile.query.get(fec_id)
        societe = Societe.query.get(fec_file.societe_id)

        regles_existantes = RegleAffectation.query.filter_by(
            societe_id=societe.id,
            is_active=True
        ).all()

        # Tester la règle avec collision
        from app.services.regle_tester import RegleTester
        tester = RegleTester()

        # Préparer les données de la règle
        regle_data = {
            'mots_cles': [mot.strip() for mot in data['mots_cles'].split(',') if mot.strip()],
            'journal_code': data.get('journal_code'),
            'criteres_montant': data.get('criteres_montant')
        }

        # Test complet avec collision
        resultats = tester.test_regle_avec_collision(
            regle_data, ecritures, compte_selectionne, regles_existantes
        )

        return jsonify({
            'success': True,
            'resultats': resultats
        })

    except Exception as e:
        print(f"Erreur test collision: {e}")
        return jsonify({'success': False, 'error': 'Erreur interne du serveur'})

# Fonctions utilitaires
def calculer_statistiques_comptes(ecritures, regles_existantes):
    """Calcule les statistiques par compte de contrepartie"""
    from collections import defaultdict
    from app.services.regle_tester import RegleTester

    tester = RegleTester()

    # Grouper par compte de contrepartie
    comptes_stats = defaultdict(lambda: {
        'compte': '',
        'libelle': '',
        'nb_transactions': 0,
        'transactions': [],
        'pourcentage_total': 0,
        'pourcentage_traite': 0,
        'pourcentage_a_faire': 0
    })

    total_ecritures = len(ecritures)

    # Identifier les écritures couvertes
    ecritures_couvertes = set()
    for regle in regles_existantes:
        if regle.is_active:
            matches = tester.test_regle_object(regle, ecritures)
            for match in matches:
                ecritures_couvertes.add(match.id)

    # Analyser chaque écriture
    for ecriture in ecritures:
        # CORRECTION : Utiliser les nouveaux champs compte_contrepartie et libelle_contrepartie
        if hasattr(ecriture, 'compte_contrepartie') and ecriture.compte_contrepartie:
            compte_contrepartie = ecriture.compte_contrepartie
            libelle_contrepartie = ecriture.libelle_contrepartie or "Libellé non défini"
        else:
            # Fallback vers l'ancienne logique si les champs n'existent pas
            if not ecriture.compte_final.startswith('512'):
                compte_contrepartie = ecriture.compte_final
                libelle_contrepartie = ecriture.libelle_final
            else:
                compte_contrepartie = "AUTRE"
                libelle_contrepartie = "Compte non identifié"

        comptes_stats[compte_contrepartie]['compte'] = compte_contrepartie
        comptes_stats[compte_contrepartie]['libelle'] = libelle_contrepartie
        comptes_stats[compte_contrepartie]['nb_transactions'] += 1
        comptes_stats[compte_contrepartie]['transactions'].append(ecriture)

    # Fonction pour formater les pourcentages avec précision adaptative
    def format_pourcentage_precis(valeur):
        if valeur == 0:
            return 0
        elif valeur < 0.1:
            return round(valeur, 2)
        else:
            return round(valeur, 1)

    # Calculer les pourcentages
    result = []
    for compte, stats in comptes_stats.items():
        nb_transactions = stats['nb_transactions']
        pourcentage_total_brut = (nb_transactions / total_ecritures * 100) if total_ecritures > 0 else 0

        # Calculer le pourcentage traité (écritures couvertes)
        nb_couvertes = sum(1 for t in stats['transactions'] if t.id in ecritures_couvertes)
        pourcentage_traite_brut = (nb_couvertes / nb_transactions * 100) if nb_transactions > 0 else 0

        # À faire = Total - Traité (en valeurs brutes)
        pourcentage_a_faire_brut = pourcentage_total_brut - (
                    nb_couvertes / total_ecritures * 100) if total_ecritures > 0 else 0

        # Appliquer le formatage précis
        pourcentage_total = format_pourcentage_precis(pourcentage_total_brut)
        pourcentage_traite = format_pourcentage_precis(pourcentage_traite_brut)
        pourcentage_a_faire = format_pourcentage_precis(max(0, pourcentage_a_faire_brut))

        result.append({
            'compte': compte,
            'libelle': stats['libelle'],
            'nb_transactions': nb_transactions,
            'pourcentage_total': pourcentage_total,
            'pourcentage_traite': pourcentage_traite,
            'pourcentage_a_faire': pourcentage_a_faire,
            'pourcentage_impact': 0  # Sera calculé en temps réel côté client
        })

    # Trier par nombre de transactions décroissant
    return sorted(result, key=lambda x: x['nb_transactions'], reverse=True)

def calculer_automatisation_globale(ecritures, regles_existantes):
    """Calcule le pourcentage global d'automatisation"""
    if not ecritures:
        return 0

    from app.services.regle_tester import RegleTester
    tester = RegleTester()

    ecritures_couvertes = set()
    for regle in regles_existantes:
        if regle.is_active:
            matches = tester.test_regle_object(regle, ecritures)
            for match in matches:
                ecritures_couvertes.add(match.id)

    return round((len(ecritures_couvertes) / len(ecritures) * 100), 1)