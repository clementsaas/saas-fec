class RegleTester:
    """Service pour tester les règles d'affectation sur les écritures bancaires"""

def test_regle(self, regle_data, ecritures):
    """
    Teste une règle sur une liste d'écritures bancaires (NOUVELLE VERSION)

    Args:
        regle_data (dict): Configuration de la règle avec mot_cle_1 et mot_cle_2
        ecritures (list): Liste des objets EcritureBancaire

    Returns:
        list: Liste des écritures qui matchent la règle
    """
    matching_ecritures = []

    # Extraire les critères de la règle (NOUVEAU FORMAT)
    mot_cle_1 = regle_data.get('mot_cle_1', '').strip()
    mot_cle_2 = regle_data.get('mot_cle_2', '').strip() if regle_data.get('mot_cle_2') else None
    journal_code = regle_data.get('journal_code')
    criteres_montant = regle_data.get('criteres_montant')

    # RÉTROCOMPATIBILITÉ : si pas de mot_cle_1, essayer l'ancien format
    if not mot_cle_1 and regle_data.get('mots_cles'):
        # Conversion de l'ancien format vers le nouveau
        mots_cles = regle_data.get('mots_cles', [])
        if isinstance(mots_cles, list) and len(mots_cles) > 0:
            mot_cle_1 = mots_cles[0]
            if len(mots_cles) > 1:
                mot_cle_2 = mots_cles[1]

    if not mot_cle_1:
        return matching_ecritures

    for ecriture in ecritures:
        if self._ecriture_matches_regle(ecriture, mot_cle_1, mot_cle_2, journal_code, criteres_montant):
            matching_ecritures.append(ecriture)

    return matching_ecritures

def test_regle_object(self, regle, ecritures):
    """
    Teste un objet RegleAffectation sur une liste d'écritures - VERSION CORRIGÉE CHAÎNES COMPLÈTES

    Args:
        regle (RegleAffectation): Objet règle depuis la base de données
        ecritures (list): Liste des objets EcritureBancaire

    Returns:
        list: Liste des écritures qui matchent la règle
    """
    # Conversion de l'ancien format vers le nouveau format chaînes complètes
    mot_cle_1 = ''
    mot_cle_2 = None
    
    if regle.mots_cles:
        if isinstance(regle.mots_cles, list) and len(regle.mots_cles) > 0:
            # Prendre la première chaîne complète (pas de découpage)
            mot_cle_1 = str(regle.mots_cles[0]).strip()
            if len(regle.mots_cles) > 1:
                # Prendre la deuxième chaîne complète (pas de découpage)
                mot_cle_2 = str(regle.mots_cles[1]).strip()
        elif isinstance(regle.mots_cles, str):
            # Si c'est une chaîne, la prendre telle quelle
            mot_cle_1 = regle.mots_cles.strip()
    
    # Utiliser le nouveau format directement
    regle_data = {
        'mot_cle_1': mot_cle_1,
        'mot_cle_2': mot_cle_2,
        'journal_code': regle.journal_code,
        'criteres_montant': regle.criteres_montant
    }
    return self.test_regle(regle_data, ecritures)

def _ecriture_matches_regle(self, ecriture, mot_cle_1, mot_cle_2=None, journal_code=None, criteres_montant=None):
    """
    Vérifie si une écriture match une règle (NOUVELLE VERSION - CHAÎNES COMPLÈTES)

    Args:
        ecriture: Objet EcritureBancaire
        mot_cle_1 (str): Première chaîne de mots-clés (obligatoire)
        mot_cle_2 (str): Deuxième chaîne de mots-clés (optionnelle)
        journal_code (str): Code journal à filtrer (optionnel)
        criteres_montant (dict): Critères de montant (optionnel)

    Returns:
        bool: True si l'écriture match la règle
    """
    # 1. Test de la première chaîne de mots-clés (obligatoire)
    if not mot_cle_1 or not mot_cle_1.strip():
        return False

    libelle_lower = ecriture.ecriture_lib.lower()
    chaine_1_lower = mot_cle_1.strip().lower()
    
    # La première chaîne DOIT être présente
    if chaine_1_lower not in libelle_lower:
        return False

    # 2. Test de la deuxième chaîne de mots-clés (optionnelle - ET logique)
    if mot_cle_2 and mot_cle_2.strip():
        chaine_2_lower = mot_cle_2.strip().lower()
        if chaine_2_lower not in libelle_lower:
            return False

    # 3. Test du journal (optionnel)
    if journal_code and ecriture.journal_code != journal_code:
        return False

    # 4. Test du montant (optionnel)
    if criteres_montant:
        if not self._test_critere_montant(ecriture.montant, criteres_montant):
            return False

    return True

    def _test_critere_montant(self, montant, criteres_montant):
        """
        Teste les critères de montant

        Args:
            montant (float): Montant de l'écriture
            criteres_montant (dict): {"operateur": ">=", "valeur": 100.0}

        Returns:
            bool: True si le montant respecte le critère
        """
        operateur = criteres_montant.get('operateur')
        valeur = float(criteres_montant.get('valeur', 0))
        montant = float(montant)

        if operateur == '=':
            return montant == valeur
        elif operateur == '!=':
            return montant != valeur
        elif operateur == '<':
            return montant < valeur
        elif operateur == '>':
            return montant > valeur
        elif operateur == '<=':
            return montant <= valeur
        elif operateur == '>=':
            return montant >= valeur

        return True

    def calculer_statistiques_regle(self, regle, ecritures_total):
        """
        Calcule les statistiques de couverture d'une règle

        Args:
            regle (RegleAffectation): Règle à analyser
            ecritures_total (list): Toutes les écritures de la société

        Returns:
            dict: Statistiques de la règle
        """
        matching_ecritures = self.test_regle_object(regle, ecritures_total)

        nb_matches = len(matching_ecritures)
        total_ecritures = len(ecritures_total)

        # Calcul des pourcentages
        pourcentage_total = (nb_matches / total_ecritures * 100) if total_ecritures > 0 else 0

        # Calcul du montant total couvert
        montant_total = sum(float(e.montant) for e in matching_ecritures)
        montant_total_global = sum(float(e.montant) for e in ecritures_total)
        pourcentage_montant = (montant_total / montant_total_global * 100) if montant_total_global > 0 else 0

        return {
            'nb_transactions_couvertes': nb_matches,
            'total_transactions': total_ecritures,
            'pourcentage_couverture_total': round(pourcentage_total, 2),
            'montant_total_couvert': round(montant_total, 2),
            'montant_total_global': round(montant_total_global, 2),
            'pourcentage_montant_couvert': round(pourcentage_montant, 2),
            'ecritures_matchees': matching_ecritures
        }

    def calculer_collision_pourcentage(self, nouvelle_regle_data, regles_existantes, ecritures, compte_selectionne):
        """
        Calcule le pourcentage de collision selon la formule correcte :
        % collision = (Transactions dans autres comptes / Transactions dans compte sélectionné) × 100

        Args:
            nouvelle_regle_data (dict): Configuration de la nouvelle règle
            regles_existantes (list): Liste des RegleAffectation existantes actives
            ecritures (list): Liste des écritures à tester
            compte_selectionne (str): Le compte pour lequel on calcule le gain potentiel

        Returns:
            dict: {
                'pourcentage_collision': float,
                'transactions_compte_selectionne': int,
                'transactions_autres_comptes': int,
                'detail_collisions': list
            }
        """
        # 1. Identifier les écritures matchées par la nouvelle règle
        nouvelles_matches = self.test_regle(nouvelle_regle_data, ecritures)

        if not nouvelles_matches:
            return {
                'pourcentage_collision': 0.0,
                'transactions_compte_selectionne': 0,
                'transactions_autres_comptes': 0,
                'detail_collisions': []
            }

        # 2. Séparer les matches par compte
        matches_compte_selectionne = []
        matches_autres_comptes = []
        detail_collisions = []

        for ecriture in nouvelles_matches:
            # Déterminer le compte de contrepartie
            compte_contrepartie = self._get_compte_contrepartie(ecriture)

            if compte_contrepartie == compte_selectionne:
                matches_compte_selectionne.append(ecriture)
            else:
                matches_autres_comptes.append(ecriture)
                detail_collisions.append({
                    'compte': compte_contrepartie,
                    'libelle': ecriture.ecriture_lib,
                    'montant': float(ecriture.montant)
                })

        # 3. Calculer le pourcentage selon la formule correcte
        nb_matches_compte = len(matches_compte_selectionne)
        nb_matches_autres = len(matches_autres_comptes)

        if nb_matches_compte == 0:
            # Si aucune transaction ne matche dans le compte sélectionné,
            # on ne peut pas calculer de collision relative
            pourcentage_collision = 0.0
        else:
            pourcentage_collision = (nb_matches_autres / nb_matches_compte) * 100

        return {
            'pourcentage_collision': round(pourcentage_collision, 1),
            'transactions_compte_selectionne': nb_matches_compte,
            'transactions_autres_comptes': nb_matches_autres,
            'detail_collisions': detail_collisions
        }

    def _get_compte_contrepartie(self, ecriture):
        """
        Détermine le compte de contrepartie d'une écriture bancaire
        """
        # Si l'écriture elle-même n'est pas 512*, utiliser son compte final
        if not ecriture.compte_final.startswith('512'):
            return ecriture.compte_final

        # Sinon, cette logique devrait être améliorée pour trouver la vraie contrepartie
        # Pour l'instant, on utilise un placeholder
        return "AUTRE"

    def test_regle_avec_collision(self, regle_data, ecritures, compte_selectionne, regles_existantes):
        """
        Test complet d'une règle avec calcul de collision

        Returns:
            dict: Résultats complets incluant collision
        """
        # Test basique de la règle
        matches = self.test_regle(regle_data, ecritures)

        # Calcul de collision
        collision_info = self.calculer_collision_pourcentage(
            regle_data, regles_existantes, ecritures, compte_selectionne
        )

        # Statistiques globales
        total_ecritures_compte = len([e for e in ecritures
                                      if self._get_compte_contrepartie(e) == compte_selectionne])

        return {
            'nb_matches_total': len(matches),
            'nb_matches_compte': collision_info['transactions_compte_selectionne'],
            'nb_matches_autres': collision_info['transactions_autres_comptes'],
            'pourcentage_collision': collision_info['pourcentage_collision'],
            'pourcentage_couverture': (collision_info['transactions_compte_selectionne'] / total_ecritures_compte * 100)
            if total_ecritures_compte > 0 else 0,
            'detail_collisions': collision_info['detail_collisions']
        }