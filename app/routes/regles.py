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

    # Récupérer la société active depuis l'URL ou la session
    societe_id = request.args.get('societe_id')

    # DEBUG: Afficher les informations de session et URL
    print(f"🔍 DEBUG Liste règles - URL args: {dict(request.args)}")
    print(f"🔍 DEBUG Liste règles - session organization_id: {session.get('organization_id')}")
    print(f"🔍 DEBUG Liste règles - societe_id depuis URL: {societe_id}")

    if societe_id:
        # Société spécifiée dans l'URL
        try:
            societe_id = int(societe_id)
            societe_active = Societe.query.get_or_404(societe_id)
            if societe_active.organization_id != session['organization_id']:
                flash('Accès non autorisé', 'error')
                return redirect(url_for('dashboard'))
        except (ValueError, TypeError):
            flash('ID de société invalide', 'error')
            return redirect(url_for('dashboard'))
    else:
        # Pas de société spécifiée - prendre la première société de l'organisation
        print("🔍 DEBUG Liste règles - Aucune société spécifiée, recherche de la première...")
        societe_active = Societe.query.filter_by(organization_id=session['organization_id']).first()
        if not societe_active:
            flash('Aucune société trouvée', 'error')
            return redirect(url_for('dashboard'))

        # REDIRECTION avec societe_id dans l'URL
        print(f"🔍 DEBUG Liste règles - Redirection vers societe_id: {societe_active.id}")
        return redirect(url_for('regles.liste_regles', societe_id=societe_active.id))
    print(f"🔍 DEBUG Import - societe_id reçu: {societe_id}")
    print(f"🔍 DEBUG Import - session organization_id: {session.get('organization_id')}")

    if not societe_id:
        print("❌ DEBUG Import - societe_id manquant dans le formulaire")
        return jsonify({'success': False, 'error': 'ID de société manquant'}), 400

    # Vérifier les permissions avec debug
    societe = Societe.query.get_or_404(societe_id)
    print(f"🔍 DEBUG Import - Société trouvée: {societe.nom} (org_id: {societe.organization_id})")

    if societe.organization_id != session['organization_id']:
        print(f"❌ DEBUG Import - Mismatch organisation: {societe.organization_id} != {session['organization_id']}")
        return jsonify({'success': False, 'error': 'Accès non autorisé'}), 403

    print(f"✅ DEBUG Import - Permissions OK, import vers société {societe.nom}")

    if societe_id:
        # Société spécifiée dans l'URL
        try:
            societe_id = int(societe_id)
            societe_active = Societe.query.get_or_404(societe_id)
            if societe_active.organization_id != session['organization_id']:
                flash('Accès non autorisé', 'error')
                return redirect(url_for('dashboard'))
        except (ValueError, TypeError):
            flash('ID de société invalide', 'error')
            return redirect(url_for('dashboard'))
    else:
        # Prendre la première société de l'organisation
        societe_active = Societe.query.filter_by(organization_id=session['organization_id']).first()
        if not societe_active:
            flash('Aucune société trouvée', 'error')
            return redirect(url_for('dashboard'))
        societe_id = societe_active.id

    # Récupérer le FEC le plus récent et actif pour cette société
    fec_file = FecFile.query.filter_by(
        societe_id=societe_id,
        is_active=True
    ).order_by(FecFile.date_import.desc()).first()

    # Récupérer toutes les sociétés pour le dropdown
    societes = Societe.query.filter_by(organization_id=session['organization_id']).all()

    # Récupérer les règles pour cette société
    regles = RegleAffectation.query.filter_by(societe_id=societe_id).all()

    # NOUVELLES DONNÉES pour le panneau gauche (comme dans le dashboard)
    ecritures = []
    comptes_statistiques = []
    journaux = []
    automatisation_globale = 0
    ecritures_json = []

    if fec_file:
        # Récupérer les écritures bancaires
        ecritures = EcritureBancaire.query.filter_by(fec_file_id=fec_file.id).all()

        # Calculer les statistiques par compte
        comptes_statistiques = calculer_statistiques_comptes(ecritures, regles)

        # Calculer l'automatisation globale
        automatisation_globale = calculer_automatisation_globale(ecritures, regles)

        # Récupérer les journaux
        journaux_query = db.session.query(
            EcritureBancaire.journal_code,
            EcritureBancaire.journal_lib
        ).filter_by(fec_file_id=fec_file.id).distinct().all()

        journaux = [{'journal_code': j.journal_code, 'journal_lib': j.journal_lib} for j in journaux_query]

        # Préparer les écritures pour JavaScript (comme dans le dashboard)
        from app.services.regle_tester import RegleTester
        tester = RegleTester()
        ecritures_couvertes = set()

        for regle in regles:
            if regle.is_active:
                matches = tester.test_regle_object(regle, ecritures)
                for match in matches:
                    ecritures_couvertes.add(match.id)

        for ecriture in ecritures:
            # Calculer le compte de contrepartie
            compte_contrepartie = None
            libelle_contrepartie = None

            if hasattr(ecriture, 'compte_contrepartie') and ecriture.compte_contrepartie:
                compte_contrepartie = ecriture.compte_contrepartie
                libelle_contrepartie = ecriture.libelle_contrepartie
            elif not ecriture.compte_final.startswith('512'):
                compte_contrepartie = ecriture.compte_final
                libelle_contrepartie = ecriture.libelle_final
            else:
                # Trouver la contrepartie dans la même écriture
                autres_ecritures = EcritureBancaire.query.filter_by(
                    fec_file_id=fec_file.id,
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

        # CALCULS RÉELS : Impact et Collision pour chaque règle
        regles_json = []

        # Import du tester une seule fois
        from app.services.regle_tester import RegleTester
        tester = RegleTester()

        for regle in regles:
            print(f"🔍 Calcul pour règle: {regle.nom}")

            # Assurer que mots_cles est toujours une liste
            mots_cles_list = []
            if regle.mots_cles:
                if isinstance(regle.mots_cles, str):
                    try:
                        import json as json_module
                        mots_cles_list = json_module.loads(regle.mots_cles)
                        if not isinstance(mots_cles_list, list):
                            mots_cles_list = [mots_cles_list] if mots_cles_list else []
                    except json_module.JSONDecodeError:
                        mots_cles_list = [mot.strip() for mot in regle.mots_cles.split(',') if mot.strip()]
                elif isinstance(regle.mots_cles, list):
                    mots_cles_list = regle.mots_cles
                else:
                    try:
                        if hasattr(regle.mots_cles, '__iter__'):
                            mots_cles_list = list(regle.mots_cles)
                    except:
                        mots_cles_list = []

            # CALCUL RÉEL DE L'IMPACT ET DE LA COLLISION
            impact_reel = 0.0
            collision_reelle = 0.0
            nb_transactions_reel = 0
            nb_collisions_reel = 0

            if ecritures and len(ecritures) > 0:
                try:
                    # Tester la règle contre toutes les écritures
                    ecritures_matchees = tester.test_regle_object(regle, ecritures)
                    print(f"   Écritures matchées total: {len(ecritures_matchees)}")

                    if len(ecritures_matchees) > 0:
                        # Séparer les matches par compte de contrepartie
                        matches_compte_regle = []
                        matches_autres_comptes = []

                        for ecriture in ecritures_matchees:
                            # Déterminer le compte de contrepartie
                            if hasattr(ecriture, 'compte_contrepartie') and ecriture.compte_contrepartie:
                                compte_contrepartie = ecriture.compte_contrepartie
                            elif not ecriture.compte_final.startswith('512'):
                                compte_contrepartie = ecriture.compte_final
                            else:
                                # Logique pour trouver la contrepartie
                                autres_ecritures = EcritureBancaire.query.filter_by(
                                    fec_file_id=fec_file.id,
                                    ecriture_num=ecriture.ecriture_num
                                ).filter(~EcritureBancaire.compte_num.startswith('512')).first()

                                if autres_ecritures:
                                    compte_contrepartie = autres_ecritures.compte_final
                                else:
                                    compte_contrepartie = "AUTRE"

                            # Classer l'écriture
                            if compte_contrepartie == regle.compte_destination:
                                matches_compte_regle.append(ecriture)
                            else:
                                matches_autres_comptes.append(ecriture)

                        print(f"   Matches compte règle: {len(matches_compte_regle)}")
                        print(f"   Matches autres comptes: {len(matches_autres_comptes)}")

                        # CALCUL DE L'IMPACT
                        # Impact = (matches dans le compte / total transactions du compte) × 100
                        total_transactions_compte = len([e for e in ecritures
                                                         if (hasattr(e,
                                                                     'compte_contrepartie') and e.compte_contrepartie == regle.compte_destination)
                                                         or (not e.compte_final.startswith(
                                '512') and e.compte_final == regle.compte_destination)])

                        if total_transactions_compte > 0:
                            impact_reel = (len(matches_compte_regle) / total_transactions_compte) * 100

                        # CALCUL DE LA COLLISION
                        # Collision = (matches autres comptes / matches compte règle) × 100
                        if len(matches_compte_regle) > 0:
                            collision_reelle = (len(matches_autres_comptes) / len(matches_compte_regle)) * 100

                        nb_transactions_reel = len(matches_compte_regle)
                        nb_collisions_reel = len(matches_autres_comptes)

                        print(f"   Impact calculé: {impact_reel:.1f}%")
                        print(f"   Collision calculée: {collision_reelle:.1f}%")

                except Exception as e:
                    print(f"❌ Erreur calcul règle {regle.nom}: {e}")
                    # Garder les valeurs par défaut (0)

            # Parser les critères de montant
            criteres_montant = None
            if regle.criteres_montant:
                try:
                    import json as json_module
                    if isinstance(regle.criteres_montant, str):
                        criteres_montant = json_module.loads(regle.criteres_montant)
                    else:
                        criteres_montant = regle.criteres_montant
                except (json_module.JSONDecodeError, TypeError):
                    criteres_montant = None

            # Construire l'objet règle avec les VRAIS calculs
            regle_data = {
                'id': regle.id,
                'nom': regle.nom or f"Règle {regle.compte_destination}",
                'compte': regle.compte_destination,
                'libelle_compte': regle.libelle_destination or '',
                'mots_cles': mots_cles_list,
                'banque': regle.journal_code or '',
                'criteres_montant': criteres_montant,
                'impact': round(impact_reel, 1),  # VRAI calcul
                'collision': round(collision_reelle, 1),  # VRAI calcul
                'nb_transactions': nb_transactions_reel,  # VRAI nombre
                'nb_collisions': nb_collisions_reel,  # VRAI nombre
                'active': bool(regle.is_active),
                'created_at': regle.created_at.isoformat() if regle.created_at else ''
            }

            regles_json.append(regle_data)
            print(f"✅ Règle {regle.nom}: Impact={impact_reel:.1f}%, Collision={collision_reelle:.1f}%")

        print(f"📊 {len(regles_json)} règles calculées avec impact/collision réels")

    # Ligne supprimée - pas de remplacement
    # Assurer que regles_json est bien défini même si vide
    if not regles_json:
        regles_json = []

    # Log pour debug
    current_app.logger.info(f"Nombre de regles trouvees: {len(regles)}")
    current_app.logger.info(f"Nombre de regles JSON: {len(regles_json)}")

    # Convertir en JSON valide avec échappement sécurisé
    def json_encoder(obj):
        """Encodeur JSON personnalisé pour éviter les caractères problématiques"""
        if hasattr(obj, 'isoformat'):
            return obj.isoformat()
        elif isinstance(obj, str):
            # Échapper les caractères problématiques
            return obj.replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n').replace('\r', '\\r')
        return str(obj)

    try:
        regles_json_string = json.dumps(regles_json, ensure_ascii=True, default=json_encoder)
        print(f"🔍 DEBUG - JSON généré avec succès: {len(regles_json_string)} caractères")
    except Exception as e:
        print(f"❌ DEBUG - Erreur génération JSON: {e}")
        regles_json_string = "[]"

    # Déterminer la société active pour la header_bar
    if fec_file:
        societe_active = Societe.query.get(fec_file.societe_id)
    else:
        # Prendre la première société de l'organisation
        societe_active = Societe.query.filter_by(organization_id=session['organization_id']).first()

    # Récupérer toutes les sociétés pour le dropdown de la header_bar
    if 'societes' not in locals():
        societes = Societe.query.filter_by(organization_id=session['organization_id']).all()

    return render_template('liste_regles.html',
                           regles=regles,
                           fec_file=fec_file,
                           fec_actif=fec_file,
                           regles_json=regles_json_string,
                           societe=societe_active,
                           societes=societes,
                           ecritures_json=json.dumps(ecritures_json),
                           comptes_statistiques=comptes_statistiques,
                           journaux=journaux,
                           automatisation_globale=automatisation_globale,
                           current_page='regles')


@regles_bp.route('/regles/<int:regle_id>/delete', methods=['POST', 'DELETE'])
def delete_regle(regle_id):
    """Supprimer une règle avec vérification stricte"""
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Non connecté'}), 401

    try:
        # Récupérer la règle avec vérification d'existence
        regle = RegleAffectation.query.get(regle_id)
        if not regle:
            return jsonify({'success': False, 'error': 'Règle introuvable'}), 404

        # Vérifier les permissions strictement
        societe = Societe.query.get(regle.societe_id)
        if not societe or societe.organization_id != session['organization_id']:
            return jsonify({'success': False, 'error': 'Accès non autorisé'}), 403

        # Log pour debug
        print(f"🗑️ DEBUG Suppression - Règle ID {regle_id}: {regle.nom}")
        print(f"🗑️ DEBUG Suppression - Société: {societe.nom} (ID: {societe.id})")

        # Suppression effective
        db.session.delete(regle)
        db.session.commit()

        print(f"✅ DEBUG Suppression - Règle {regle_id} supprimée avec succès")
        return jsonify({'success': True, 'message': 'Règle supprimée avec succès'})

    except Exception as e:
        db.session.rollback()
        print(f"❌ Erreur suppression règle {regle_id}: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': 'Erreur interne du serveur'}), 500


# NOUVELLE ROUTE : API pour mettre à jour le statut d'une règle
@regles_bp.route('/regles/<int:regle_id>/toggle', methods=['POST'])
def toggle_regle_active(regle_id):
    """Activer/désactiver une règle"""
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Non connecté'}), 401

    try:
        regle = RegleAffectation.query.get(regle_id)
        if not regle:
            return jsonify({'success': False, 'error': 'Règle introuvable'}), 404

        # Vérifier les permissions
        societe = Societe.query.get(regle.societe_id)
        if not societe or societe.organization_id != session['organization_id']:
            return jsonify({'success': False, 'error': 'Accès non autorisé'}), 403

        # Inverser le statut
        regle.is_active = not regle.is_active
        db.session.commit()

        print(f"🔄 Règle {regle_id} {'activée' if regle.is_active else 'désactivée'}")

        return jsonify({
            'success': True,
            'is_active': regle.is_active,
            'message': f"Règle {'activée' if regle.is_active else 'désactivée'}"
        })

    except Exception as e:
        db.session.rollback()
        print(f"❌ Erreur toggle règle {regle_id}: {e}")
        return jsonify({'success': False, 'error': 'Erreur interne du serveur'}), 500


# CORRECTION MAJEURE : Fonction de calcul des statistiques comptes
def calculer_statistiques_comptes(ecritures, regles_existantes):
    """Calcule les statistiques par compte de contrepartie - VERSION CORRIGÉE"""
    from collections import defaultdict
    from app.services.regle_tester import RegleTester

    print(f"📊 DEBUG Stats - Début calcul avec {len(ecritures)} écritures et {len(regles_existantes)} règles")

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
    if total_ecritures == 0:
        return []

    # Identifier TOUTES les écritures couvertes par TOUTES les règles actives
    ecritures_couvertes_globales = set()
    for regle in regles_existantes:
        if regle.is_active:
            try:
                matches = tester.test_regle_object(regle, ecritures)
                for match in matches:
                    ecritures_couvertes_globales.add(match.id)
                print(f"📋 Règle '{regle.nom}' couvre {len(matches)} écritures")
            except Exception as e:
                print(f"❌ Erreur test règle {regle.nom}: {e}")

    print(f"🎯 Total écritures couvertes: {len(ecritures_couvertes_globales)}/{total_ecritures}")

    # Analyser chaque écriture
    for ecriture in ecritures:
        # Utiliser les champs compte_contrepartie et libelle_contrepartie
        if hasattr(ecriture, 'compte_contrepartie') and ecriture.compte_contrepartie:
            compte_contrepartie = ecriture.compte_contrepartie
            libelle_contrepartie = ecriture.libelle_contrepartie or "Libellé non défini"
        else:
            # Fallback vers l'ancienne logique
            if not ecriture.compte_final.startswith('512'):
                compte_contrepartie = ecriture.compte_final
                libelle_contrepartie = ecriture.libelle_final
            else:
                continue  # Ignorer les comptes 512

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

    # Calculer les pourcentages POUR CHAQUE COMPTE
    result = []
    for compte, stats in comptes_stats.items():
        nb_transactions = stats['nb_transactions']

        # % total = part de ce compte dans toutes les écritures
        pourcentage_total_brut = (nb_transactions / total_ecritures * 100) if total_ecritures > 0 else 0

        # % traité = écritures de ce compte qui sont couvertes par des règles
        ecritures_compte_couvertes = [t for t in stats['transactions'] if t.id in ecritures_couvertes_globales]
        nb_couvertes = len(ecritures_compte_couvertes)
        pourcentage_traite_brut = (nb_couvertes / nb_transactions * 100) if nb_transactions > 0 else 0

        # % à faire = 100% - % traité pour ce compte spécifiquement
        pourcentage_a_faire_brut = 100 - pourcentage_traite_brut

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

        print(
            f"📊 Compte {compte}: {nb_transactions} trans, {pourcentage_traite}% traité, {pourcentage_a_faire}% à faire")

    # Trier par nombre de transactions décroissant
    result_sorted = sorted(result, key=lambda x: x['nb_transactions'], reverse=True)
    print(f"✅ Statistiques calculées pour {len(result_sorted)} comptes")

    return result_sorted


def calculer_automatisation_globale(ecritures, regles_existantes):
    """Calcule le pourcentage global d'automatisation - VERSION CORRIGÉE"""
    if not ecritures:
        return 0

    from app.services.regle_tester import RegleTester
    tester = RegleTester()

    ecritures_couvertes = set()
    for regle in regles_existantes:
        if regle.is_active:  # Seulement les règles ACTIVES
            try:
                matches = tester.test_regle_object(regle, ecritures)
                for match in matches:
                    ecritures_couvertes.add(match.id)
            except Exception as e:
                print(f"❌ Erreur calcul automatisation pour règle {regle.nom}: {e}")

    automatisation = round((len(ecritures_couvertes) / len(ecritures) * 100), 1)
    print(f"🎯 Automatisation globale: {automatisation}% ({len(ecritures_couvertes)}/{len(ecritures)})")

    return automatisation


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


@regles_bp.route('/regles/import', methods=['POST'])
def import_regles():
    """Endpoint pour importer des règles depuis un fichier Excel/CSV"""
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Non connecté'}), 401

    try:
        # Vérifier qu'un fichier a été uploadé
        if 'file' not in request.files:
            return jsonify({'success': False, 'error': 'Aucun fichier fourni'}), 400

        file = request.files['file']
        if file.filename == '':
            return jsonify({'success': False, 'error': 'Aucun fichier sélectionné'}), 400

        # Récupérer la société
        societe_id = request.form.get('societe_id')
        print(f"🔍 DEBUG Import - societe_id reçu: '{societe_id}'")

        if not societe_id:
            # Fallback: récupérer la première société de l'organisation
            premiere_societe = Societe.query.filter_by(organization_id=session['organization_id']).first()
            if premiere_societe:
                societe_id = str(premiere_societe.id)
                print(f"🔍 DEBUG Import - Utilisation fallback: {societe_id}")
            else:
                return jsonify({'success': False, 'error': 'Aucune société disponible'}), 400

        try:
            societe_id = int(societe_id)
        except (ValueError, TypeError):
            return jsonify({'success': False, 'error': 'Format ID société invalide'}), 400

        # Vérifier les permissions
        societe = Societe.query.get_or_404(societe_id)
        if societe.organization_id != session['organization_id']:
            return jsonify({'success': False, 'error': 'Accès non autorisé'}), 403

        print(f"✅ DEBUG Import - Société validée: {societe.nom}")

        # Traitement selon le type de fichier
        import pandas as pd
        from io import BytesIO
        import re

        filename = file.filename.lower()

        try:
            print(f"🔍 DEBUG Import - Lecture du fichier: {filename}")

            if filename.endswith('.xlsx'):
                # Lire le fichier Excel
                file_content = file.read()
                print(f"🔍 DEBUG Import - Taille fichier Excel: {len(file_content)} bytes")
                df = pd.read_excel(BytesIO(file_content), sheet_name=0)
            elif filename.endswith('.csv'):
                # Lire le fichier CSV
                file_content = file.read()
                print(f"🔍 DEBUG Import - Taille fichier CSV: {len(file_content)} bytes")
                df = pd.read_csv(BytesIO(file_content))
            else:
                return jsonify({'success': False, 'error': 'Format de fichier non supporté'}), 400

            print(f"🔍 DEBUG Import - DataFrame créé: {len(df)} lignes, {len(df.columns)} colonnes")
            print(f"🔍 DEBUG Import - Colonnes trouvées: {list(df.columns)}")

            # Afficher les 3 premières lignes pour debug
            print(f"🔍 DEBUG Import - Premières lignes:")
            for i in range(min(3, len(df))):
                print(f"   Ligne {i + 1}: {dict(df.iloc[i])}")

            # Vérifier les colonnes minimales requises
            required_columns = ['Nom', 'Mots-clés']
            missing_columns = [col for col in required_columns if col not in df.columns]

            if missing_columns:
                return jsonify({
                    'success': False,
                    'error': f'Colonnes manquantes: {", ".join(missing_columns)}'
                }), 400

            # Fonction pour parser les regex Pennylane
            def parse_pennylane_regex(regex_str):
                """Parse une regex Pennylane et extrait les mots-clés"""
                if not regex_str or pd.isna(regex_str):
                    return []

                regex_str = str(regex_str).strip()
                if not regex_str:
                    return []

                # Pattern pour extraire les mots-clés des regex Pennylane
                # (?=.*(TEXTE)) ou ^(?=(TEXTE)) ou (?=.*^(TEXTE)$) etc.
                patterns = [
                    r'\(\?\=\.\*\(([^)]+)\)\)',  # (?=.*(TEXTE))
                    r'\^\(\?\=\(([^)]+)\)\)',  # ^(?=(TEXTE))
                    r'\(\?\=\.\*\^\(([^)]+)\)\$\)'  # (?=.*^(TEXTE)$)
                ]

                mots_cles = []
                for pattern in patterns:
                    matches = re.findall(pattern, regex_str)
                    mots_cles.extend(matches)

                # Nettoyer les mots-clés
                mots_cles = [mot.strip().upper() for mot in mots_cles if mot.strip()]
                return mots_cles

            # Fonction pour parser les montants Pennylane
            def parse_pennylane_montant(montant_val):
                """Parse un critère de montant Pennylane"""
                if pd.isna(montant_val) or not montant_val:
                    return None

                # Si c'est un nombre, c'est une égalité
                if isinstance(montant_val, (int, float)):
                    return {
                        'operateur': '=',
                        'valeur': float(montant_val)
                    }

                montant_str = str(montant_val).strip()
                if not montant_str:
                    return None

                # Patterns pour différents opérateurs
                patterns = [
                    (r'^≥\s*(\d+\.?\d*)$', '>='),
                    (r'^≤\s*(\d+\.?\d*)$', '<='),
                    (r'^>\s*(\d+\.?\d*)$', '>'),
                    (r'^<\s*(\d+\.?\d*)$', '<'),
                    (r'^≠\s*(\d+\.?\d*)$', '!='),
                    (r'^=\s*(\d+\.?\d*)$', '='),
                    (r'^De\s*(\d+\.?\d*)\s*à\s*(\d+\.?\d*)$', 'between'),
                ]

                for pattern, operateur in patterns:
                    match = re.match(pattern, montant_str)
                    if match:
                        if operateur == 'between':
                            return {
                                'operateur': 'between',
                                'valeur': float(match.group(1)),
                                'valeur_max': float(match.group(2))
                            }
                        else:
                            return {
                                'operateur': operateur,
                                'valeur': float(match.group(1))
                            }

                return None

            # Traiter chaque ligne
            imported_count = 0
            errors = []

            for index, row in df.iterrows():
                try:
                    # Vérifier les champs obligatoires
                    nom = str(row['Nom']).strip() if pd.notna(row['Nom']) else ''
                    mots_cles_str = str(row['Mots-clés']).strip() if pd.notna(row['Mots-clés']) else ''

                    if not nom or not mots_cles_str:
                        errors.append(f"Ligne {index + 2}: Nom ou Mots-clés manquant")
                        continue

                    # Vérifier si une règle avec ce nom existe déjà
                    existing_regle = RegleAffectation.query.filter_by(
                        nom=nom,
                        societe_id=societe_id
                    ).first()

                    if existing_regle:
                        errors.append(f"Ligne {index + 2}: Règle '{nom}' existe déjà")
                        continue

                    # Parser les mots-clés depuis la regex Pennylane
                    mots_cles = parse_pennylane_regex(mots_cles_str)

                    if not mots_cles:
                        errors.append(f"Ligne {index + 2}: Format de mots-clés non reconnu")
                        continue

                    # Récupérer les autres champs optionnels
                    compte_destination = str(row.get('Num. de compte', '')).strip() if pd.notna(
                        row.get('Num. de compte')) else None
                    libelle_destination = str(row.get('Libellé du compte', '')).strip() if pd.notna(
                        row.get('Libellé du compte')) else None

                    # Parser les critères de montant si présents
                    criteres_montant = None
                    if 'Montant' in df.columns and pd.notna(row['Montant']):
                        criteres_montant = parse_pennylane_montant(row['Montant'])

                    # Créer la règle
                    regle = RegleAffectation(
                        nom=nom,
                        mots_cles=mots_cles,
                        criteres_montant=criteres_montant,
                        compte_destination=compte_destination,
                        libelle_destination=libelle_destination,
                        nb_transactions_couvertes=0,  # Sera calculé plus tard
                        pourcentage_couverture_total=0.0,
                        societe_id=societe_id,
                        is_active=True
                    )

                    db.session.add(regle)
                    imported_count += 1
                    print(f"✅ DEBUG Import - Règle ajoutée: {nom} (mots-clés: {mots_cles})")
                except Exception as e:
                    error_msg = f"Ligne {index + 2}: Erreur de traitement - {str(e)}"
                    errors.append(error_msg)
                    print(f"❌ DEBUG Import - {error_msg}")
                    continue

                print(f"🔍 DEBUG Import - Fin du traitement: {imported_count} règles à sauvegarder")

                # Sauvegarder en base
                if imported_count > 0:
                    print("💾 DEBUG Import - Sauvegarde en base de données...")
                    db.session.commit()
                    print("✅ DEBUG Import - Sauvegarde réussie")
                else:
                    print("⚠️ DEBUG Import - Aucune règle à sauvegarder")

                print(f"🎯 DEBUG Import - Résultat final: {imported_count} importées, {len(errors)} erreurs")

                # Préparer la réponse
                response_data = {
                    'success': True,
                    'imported_count': imported_count,
                    'total_rows': len(df),
                    'errors': errors[:10]  # Limiter à 10 erreurs pour l'affichage
                }

                if errors:
                    response_data['warning'] = f"{len(errors)} ligne(s) ignorée(s)"

                return jsonify(response_data)

        except Exception as e:
            return jsonify({'success': False, 'error': f'Erreur de lecture du fichier: {str(e)}'}), 400

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Erreur import règles: {e}")
        return jsonify({'success': False, 'error': 'Erreur interne du serveur'}), 500