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

        print(f"🔍 Recherche d'écritures pour le compte: '{compte_selectionne}'")
        print(f"🔍 Total écritures à analyser: {len(ecritures)}")

        debug_count = 0
        for ecriture in ecritures:
            # Essayer d'utiliser le champ compte_contrepartie s'il existe, sinon recalculer
            if hasattr(ecriture, 'compte_contrepartie') and ecriture.compte_contrepartie:
                compte_contrepartie = ecriture.compte_contrepartie
                print(f"✅ Utilisation contrepartie sauvegardée: {compte_contrepartie}")
            else:
                # Fallback : recalculer la contrepartie
                if not ecriture.compte_final.startswith('512'):
                    compte_contrepartie = ecriture.compte_final
                else:
                    # Trouver la contrepartie (ligne non 512*)
                    autres_ecritures = EcritureBancaire.query.filter_by(
                        fec_file_id=fec_actif.id,
                        ecriture_num=ecriture.ecriture_num
                    ).filter(~EcritureBancaire.compte_num.startswith('512')).first()

                    if autres_ecritures:
                        compte_contrepartie = autres_ecritures.compte_final
                    else:
                        compte_contrepartie = "AUTRE"

            # Debug : afficher quelques exemples
            if debug_count < 10:
                print(
                    f"🔍 Écriture {ecriture.id}: compte_final={ecriture.compte_final}, contrepartie={compte_contrepartie}")
                debug_count += 1

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

        # Utiliser le TransactionGrouper professionnel
        print(f"📋 Création des groupements avec {len(ecritures_data)} écritures")

        groupements_compte = []

        if len(ecritures_data) > 0:
            try:
                from app.services.transaction_grouper import TransactionGrouper

                print(f"🧠 Utilisation du TransactionGrouper professionnel")
                groupeur = TransactionGrouper()

                # Le TransactionGrouper retourne des données organisées par compte
                organized_data_by_compte = groupeur.smart_sort_transactions(ecritures_data)

                # Debug : afficher tous les comptes trouvés
                print(f"🔍 Comptes trouvés par TransactionGrouper: {list(organized_data_by_compte.keys())}")
                print(f"🔍 Compte recherché: '{compte_selectionne}'")

                # Récupérer les groupements pour le compte sélectionné
                groupements_compte = organized_data_by_compte.get(compte_selectionne, [])

                print(f"📊 Groupements trouvés avec TransactionGrouper: {len(groupements_compte)}")

                # Si pas de groupements pour ce compte, essayer le premier compte disponible
                if len(groupements_compte) == 0 and organized_data_by_compte:
                    premier_compte = list(organized_data_by_compte.keys())[0]
                    print(f"⚠️ Pas de groupements pour '{compte_selectionne}', essai avec '{premier_compte}'")
                    groupements_compte = organized_data_by_compte.get(premier_compte, [])
                    print(f"📊 Groupements trouvés pour '{premier_compte}': {len(groupements_compte)}")

                # Debug : afficher les groupes trouvés
                for i, groupe in enumerate(groupements_compte):
                    if groupe.get('type') == 'group':
                        print(f"🔍 Groupe {i}: '{groupe['pattern']}' - {groupe['count']} transactions")
                        if 'suggested_keywords' in groupe:
                            print(f"   Mots-clés suggérés: {groupe['suggested_keywords']}")

            except ImportError as e:
                print(f"⚠️ TransactionGrouper non disponible: {e}")
                groupements_compte = []
            except Exception as e:
                print(f"❌ Erreur TransactionGrouper: {e}")
                groupements_compte = []
        else:
            print("⚠️ Aucune écriture à analyser")

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

        # Debug : afficher les groupements trouvés
        for i, groupe in enumerate(groupements_compte):
            if groupe.get('type') == 'group':
                print(f"📋 Groupe {i}: {groupe['pattern']} - {groupe['count']} transactions")

        return jsonify({
            'success': True,
            'groupements': groupements_compte,
            'compte': compte_selectionne,
            'total_transactions_compte': ecritures_pour_compte,
            'debug_info': {
                'ecritures_total': len(ecritures),
                'ecritures_pour_compte': ecritures_pour_compte,
                'groupements_count': len(groupements_compte)
            }
        })

    except Exception as e:
        print(f"❌ Erreur groupements intelligents: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)})