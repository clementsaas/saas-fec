class RegleTester:
    """Service pour tester les règles d'affectation sur les écritures bancaires"""

    def test_regle(self, regle_data, ecritures):
        """
        Teste une règle sur une liste d'écritures bancaires

        Args:
            regle_data (dict): Configuration de la règle
            ecritures (list): Liste des objets EcritureBancaire

        Returns:
            list: Liste des écritures qui matchent la règle
        """
        matching_ecritures = []

        # Extraire les critères de la règle
        mots_cles = [mot.strip().lower() for mot in regle_data.get('mots_cles', [])]
        journal_code = regle_data.get('journal_code')
        criteres_montant = regle_data.get('criteres_montant')

        for ecriture in ecritures:
            if self._ecriture_matches_regle(ecriture, mots_cles, journal_code, criteres_montant):
                matching_ecritures.append(ecriture)

        return matching_ecritures

    def test_regle_object(self, regle, ecritures):
        """
        Teste un objet RegleAffectation sur une liste d'écritures

        Args:
            regle (RegleAffectation): Objet règle depuis la base de données
            ecritures (list): Liste des objets EcritureBancaire

        Returns:
            list: Liste des écritures qui matchent la règle
        """
        regle_data = {
            'mots_cles': regle.mots_cles,
            'journal_code': regle.journal_code,
            'criteres_montant': regle.criteres_montant
        }

        return self.test_regle(regle_data, ecritures)

    def _ecriture_matches_regle(self, ecriture, mots_cles, journal_code, criteres_montant):
        """
        Vérifie si une écriture match une règle

        Args:
            ecriture: Objet EcritureBancaire
            mots_cles (list): Liste des mots-clés à chercher
            journal_code (str): Code journal à filtrer (optionnel)
            criteres_montant (dict): Critères de montant (optionnel)

        Returns:
            bool: True si l'écriture match la règle
        """
        # 1. Test des mots-clés (obligatoire)
        if not mots_cles:
            return False

        libelle_lower = ecriture.ecriture_lib.lower()
        mot_cle_match = any(mot_cle in libelle_lower for mot_cle in mots_cles)

        if not mot_cle_match:
            return False

        # 2. Test du journal (optionnel)
        if journal_code and ecriture.journal_code != journal_code:
            return False

        # 3. Test du montant (optionnel)
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

    def detecter_collisions(self, nouvelle_regle_data, regles_existantes, ecritures):
        """
        Détecte les collisions entre une nouvelle règle et les règles existantes

        Args:
            nouvelle_regle_data (dict): Configuration de la nouvelle règle
            regles_existantes (list): Liste des RegleAffectation existantes
            ecritures (list): Liste des écritures à tester

        Returns:
            dict: Informations sur les collisions détectées
        """
        # Écritures matchées par la nouvelle règle
        nouvelles_matches = self.test_regle(nouvelle_regle_data, ecritures)

        collisions = []

        for regle_existante in regles_existantes:
            # Écritures matchées par la règle existante
            matches_existantes = self.test_regle_object(regle_existante, ecritures)

            # Intersection entre les deux
            ecritures_communes = []
            nouvelles_ids = {e.id for e in nouvelles_matches}

            for ecriture in matches_existantes:
                if ecriture.id in nouvelles_ids:
                    ecritures_communes.append(ecriture)

            if ecritures_communes:
                collisions.append({
                    'regle_existante': regle_existante,
                    'nb_collisions': len(ecritures_communes),
                    'ecritures_communes': ecritures_communes[:5]  # Limiter à 5 exemples
                })

        return {
            'has_collisions': len(collisions) > 0,
            'collisions': collisions
        }