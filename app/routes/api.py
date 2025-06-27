from flask import Blueprint, jsonify, session, request
from app.models import db
from app.models.societe import Societe
from app.models.fec_file import FecFile
from app.models.ecriture_bancaire import EcritureBancaire
from app.models.regle_affectation import RegleAffectation
import json

api_bp = Blueprint('api', __name__, url_prefix='/api')


@api_bp.route('/societe/<int:societe_id>/dashboard-data')
def get_dashboard_data(societe_id):
    """API pour récupérer les données du dashboard d'une société"""
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Non connecté'}), 401

    try:
        # Vérifier que l'utilisateur a accès à cette société
        societe = Societe.query.get_or_404(societe_id)
        if societe.organization_id != session['organization_id']:
            return jsonify({'success': False, 'error': 'Accès non autorisé'}), 403

        # Récupérer le FEC le plus récent et actif
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
                'automatisation_globale': 0,
                'fec_actif': None
            })

        # Récupérer les écritures bancaires
        ecritures = EcritureBancaire.query.filter_by(fec_file_id=fec_actif.id).all()

        # Récupérer les règles existantes
        regles_existantes = RegleAffectation.query.filter_by(societe_id=societe_id).all()

        # Calculer les statistiques
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
            if not ecriture.compte_final.startswith('512'):
                compte_contrepartie = ecriture.compte_final
            else:
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

        return jsonify({
            'success': True,
            'ecritures': ecritures_json,
            'comptes_statistiques': comptes_statistiques,
            'journaux': journaux_json,
            'automatisation_globale': automatisation_globale,
            'fec_actif': {
                'id': fec_actif.id,
                'nom_original': fec_actif.nom_original,
                'date_import': fec_actif.date_import.strftime('%d/%m/%Y %H:%M'),
                'nb_lignes_bancaires': fec_actif.nb_lignes_bancaires
            }
        })

    except Exception as e:
        print(f"Erreur API dashboard: {e}")
        return jsonify({'success': False, 'error': 'Erreur interne du serveur'}), 500


@api_bp.route('/groupements-intelligents', methods=['POST'])
def groupements_intelligents():
    """API pour récupérer les groupements intelligents d'un compte"""
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Non connecté'}), 401

    try:
        data = request.get_json()
        societe_id = data.get('societe_id')
        compte_selectionne = data.get('compte_selectionne')
        show_covered = data.get('show_covered', False)

        print(f"🧠 API Groupements - Société: {societe_id}, Compte: {compte_selectionne}")

        # Vérifier l'accès à la société
        societe = Societe.query.get_or_404(societe_id)
        if societe.organization_id != session['organization_id']:
            return jsonify({'success': False, 'error': 'Accès non autorisé'}), 403

        # Trouver le FEC actif pour cette société
        fec_actif = FecFile.query.filter_by(
            societe_id=societe_id,
            is_active=True
        ).order_by(FecFile.date_import.desc()).first()

        if not fec_actif:
            return jsonify({'success': False, 'error': 'Aucun FEC actif'})

        # Récupérer toutes les écritures bancaires
        ecritures = EcritureBancaire.query.filter_by(fec_file_id=fec_actif.id).all()
        print(f"📊 Trouvé {len(ecritures)} écritures pour FEC {fec_actif.id}")

        # Récupérer les règles pour déterminer la couverture
        regles_existantes = RegleAffectation.query.filter_by(societe_id=societe_id).all()
        from app.services.regle_tester import RegleTester
        tester = RegleTester()

        ecritures_couvertes = set()
        for regle in regles_existantes:
            if regle.is_active:
                matches = tester.test_regle_object(regle, ecritures)
                for match in matches:
                    ecritures_couvertes.add(match.id)

        # Convertir en format dict et déterminer les comptes de contrepartie
        ecritures_data = []
        ecritures_pour_compte = 0

        for ecriture in ecritures:
            if not ecriture.compte_final.startswith('512'):
                compte_contrepartie = ecriture.compte_final
            else:
                # Trouver la contrepartie
                autres_ecritures = EcritureBancaire.query.filter_by(
                    fec_file_id=fec_actif.id,
                    ecriture_num=ecriture.ecriture_num
                ).filter(~EcritureBancaire.compte_num.startswith('512')).first()

                compte_contrepartie = autres_ecritures.compte_final if autres_ecritures else "AUTRE"

            # Ne garder que les écritures pour le compte sélectionné
            if compte_contrepartie == compte_selectionne:
                ecriture_dict = {
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
                }
                ecritures_data.append(ecriture_dict)
                ecritures_pour_compte += 1

        print(f"📋 Préparé {len(ecritures_data)} écritures pour le compte {compte_selectionne}")
        print(f"📊 Écritures trouvées pour ce compte: {ecritures_pour_compte}")

        # Utiliser le TransactionGrouper Python existant ou fallback simple
        try:
            from app.services.transaction_grouper import TransactionGrouper
            groupeur = TransactionGrouper()
            organized_data_by_compte = groupeur.smart_sort_transactions(ecritures_data)
            groupements_compte = organized_data_by_compte.get(compte_selectionne, [])
            print(f"📊 Groupements trouvés avec TransactionGrouper: {len(groupements_compte)}")

        except ImportError as e:
            print(f"⚠️ TransactionGrouper non disponible: {e}")
            # Fallback : créer des groupes simples
            groupements_compte = []

            if len(ecritures_data) > 0:
                # Analyse simple des mots récurrents
                mots_count = {}
                for ecriture in ecritures_data:
                    mots = ecriture['ecriture_lib'].lower().split()
                    for mot in mots:
                        if len(mot) > 3:  # Ignorer les petits mots
                            mots_count[mot] = mots_count.get(mot, 0) + 1

                # Créer des groupes pour les mots qui apparaissent au moins 3 fois
                for mot, count in mots_count.items():
                    if count >= 3:
                        transactions_groupe = [e for e in ecritures_data if mot in e['ecriture_lib'].lower()]

                        if len(transactions_groupe) >= 3:
                            groupements_compte.append({
                                'type': 'group',
                                'pattern': mot.capitalize(),
                                'count': len(transactions_groupe),
                                'transactions': transactions_groupe
                            })

            print(f"📊 Groupements trouvés avec fallback: {len(groupements_compte)}")

        # Filtrer selon show_covered si nécessaire
        if not show_covered:
            groupements_filtres = []
            for item in groupements_compte:
                if item.get('type') == 'group':
                    # Filtrer les transactions non couvertes dans le groupe
                    transactions_non_couvertes = [t for t in item['transactions'] if
                                                  not t.get('couverte_par_regle', False)]
                    if len(transactions_non_couvertes) >= 3:  # Garder seulement si 3+ transactions non couvertes
                        item_copie = item.copy()
                        item_copie['transactions'] = transactions_non_couvertes
                        item_copie['count'] = len(transactions_non_couvertes)
                        groupements_filtres.append(item_copie)
                else:
                    # Transaction simple non couverte
                    if not item.get('transaction', {}).get('couverte_par_regle', False):
                        groupements_filtres.append(item)
            groupements_compte = groupements_filtres

        print(f"🎯 Groupements finaux: {len(groupements_compte)}")

        return jsonify({
            'success': True,
            'groupements': groupements_compte,
            'compte': compte_selectionne
        })

    except Exception as e:
        print(f"❌ Erreur groupements intelligents: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)})