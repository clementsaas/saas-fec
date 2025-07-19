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
                from app.services.rule_suggester import RuleSuggester

                print(f"🚀 AFFECTIA : Utilisation du système de suggestion de règles")

                suggester = RuleSuggester(debug=True)

                # Récupérer TOUTES les écritures pour la vérification des collisions
                toutes_ecritures_compte = []
                for ecriture in ecritures:
                    if hasattr(ecriture, 'compte_contrepartie') and ecriture.compte_contrepartie:
                        compte_contrepartie = ecriture.compte_contrepartie
                    else:
                        compte_contrepartie = "AUTRE"

                    toutes_ecritures_compte.append({
                        'id': ecriture.id,
                        'ecriture_lib': ecriture.ecriture_lib,
                        'journal_code': ecriture.journal_code,
                        'montant': float(ecriture.montant) if ecriture.sens == 'D' else -float(ecriture.montant),
                        'compte_contrepartie': compte_contrepartie
                    })

                # Suggérer des règles pour le compte sélectionné
                suggested_rules = suggester.suggest_rules_for_account(
                    compte_selectionne,
                    ecritures_data,
                    toutes_ecritures_compte
                )

                # Convertir les règles en format compatible avec l'interface
                groupements_compte = []
                for rule in suggested_rules:
                    # Créer un "groupe" virtuel représentant la règle suggérée
                    pattern_parts = [rule['mot_cle_1']]
                    if 'mot_cle_2' in rule:
                        pattern_parts.append(rule['mot_cle_2'])

                    pattern = ' & '.join(pattern_parts)

                    # Trouver les transactions correspondantes
                    matching_transactions = []
                    for trans in ecritures_data:
                        libelle_norm = suggester.normalize_text(trans['ecriture_lib'])
                        if all(part in libelle_norm for part in pattern_parts):
                            matching_transactions.append(trans)

                    if matching_transactions:
                        groupements_compte.append({
                            'type': 'rule_suggestion',
                            'pattern': pattern,
                            'count': len(matching_transactions),
                            'transactions': matching_transactions,
                            'rule_data': rule,  # Données complètes de la règle
                            'suggested_keywords': pattern_parts
                        })

                print(f"🎯 AFFECTIA : {len(groupements_compte)} suggestions de règles générées")

            except ImportError as e:
                print(f"⚠️ RuleSuggester non disponible: {e}")
                groupements_compte = []
            except Exception as e:
                print(f"❌ Erreur RuleSuggester: {e}")
                import traceback
                traceback.print_exc()
                groupements_compte = []
        else:
            print("⚠️ Aucune écriture à analyser")
            groupements_compte = []

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
    
@api_bp.route('/societes', methods=['POST'])
def create_societe():
    """Créer une nouvelle société"""
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Non connecté'}), 401

    try:
        data = request.get_json()
        nom_societe = data.get('nom', '').strip()
        
        if not nom_societe:
            return jsonify({'success': False, 'error': 'Le nom de la société est obligatoire'}), 400

        # Vérifier que le nom n'existe pas déjà dans l'organisation
        organization_id = session['organization_id']
        societe_existante = Societe.query.filter_by(
            nom=nom_societe, 
            organization_id=organization_id
        ).first()
        
        if societe_existante:
            return jsonify({'success': False, 'error': 'Une société avec ce nom existe déjà'}), 400

        # Créer la nouvelle société
        nouvelle_societe = Societe(
            nom=nom_societe,
            organization_id=organization_id
        )
        
        db.session.add(nouvelle_societe)
        db.session.commit()

        return jsonify({
            'success': True, 
            'societe': {
                'id': nouvelle_societe.id,
                'nom': nouvelle_societe.nom,
                'created_at': nouvelle_societe.created_at.strftime('%d/%m/%Y')
            }
        })

    except Exception as e:
        db.session.rollback()
        print(f"Erreur création société: {e}")
        return jsonify({'success': False, 'error': 'Erreur interne du serveur'}), 500
    
@api_bp.route('/societe/<int:societe_id>/statistiques')
def get_societe_statistiques(societe_id):
    """API pour récupérer les statistiques d'une société (automatisation + collisions)"""
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
                'automatisation': 0,
                'collisions': 0,
                'dernier_import': None
            })

        # Récupérer les écritures bancaires
        ecritures = EcritureBancaire.query.filter_by(fec_file_id=fec_actif.id).all()
        
        # Récupérer les règles existantes
        regles_existantes = RegleAffectation.query.filter_by(
            societe_id=societe_id,
            is_active=True
        ).all()

        # Calculer l'automatisation globale
        automatisation = calculer_automatisation_globale(ecritures, regles_existantes)
        
        # Calculer les collisions
        collisions_totales = calculer_collisions_totales(regles_existantes, ecritures)
        
        return jsonify({
            'success': True,
            'automatisation': round(automatisation, 1),
            'collisions': collisions_totales,
            'dernier_import': fec_actif.date_import.isoformat() if fec_actif else None
        })

    except Exception as e:
        print(f"Erreur API statistiques société {societe_id}: {e}")
        return jsonify({'success': False, 'error': 'Erreur interne'}), 500



def calculer_automatisation_globale(ecritures, regles_existantes):
    """Calcule le pourcentage d'automatisation global"""
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
    
    total_ecritures = len(ecritures)
    ecritures_automatisees = len(ecritures_couvertes)
    
    return (ecritures_automatisees / total_ecritures * 100) if total_ecritures > 0 else 0


def calculer_collisions_totales(regles_existantes, ecritures):
    """Calcule le nombre total de collisions entre toutes les règles actives"""
    if not regles_existantes or len(regles_existantes) < 2:
        return 0
    
    from app.services.regle_tester import RegleTester
    tester = RegleTester()
    
    # Grouper les écritures par compte pour chaque règle
    regles_matches = {}
    
    for regle in regles_existantes:
        if regle.is_active:
            matches = tester.test_regle_object(regle, ecritures)
            regles_matches[regle.id] = {}
            
            for match in matches:
                # Déterminer le compte de contrepartie (compatible avec l'ancien format)
                if hasattr(match, 'compte_contrepartie') and match.compte_contrepartie:
                    compte = match.compte_contrepartie
                elif not match.compte_final.startswith('512'):
                    compte = match.compte_final
                else:
                    compte = "AUTRE"
                
                if compte not in regles_matches[regle.id]:
                    regles_matches[regle.id][compte] = []
                regles_matches[regle.id][compte].append(match)
    
    # Détecter les collisions : même compte touché par plusieurs règles
    comptes_avec_collisions = {}
    
    for regle_id, comptes_matches in regles_matches.items():
        for compte, matches in comptes_matches.items():
            if compte not in comptes_avec_collisions:
                comptes_avec_collisions[compte] = []
            comptes_avec_collisions[compte].append({
                'regle_id': regle_id,
                'nb_matches': len(matches)
            })
    
    # Compter les collisions : comptes touchés par plus d'une règle
    nb_collisions = 0
    for compte, regles_impliquees in comptes_avec_collisions.items():
        if len(regles_impliquees) > 1:
            # Une collision = le nombre de comptes en conflit (plus simple)
            nb_collisions += 1
    
    return nb_collisions