import re
from typing import List, Dict, Optional
from collections import Counter


class RuleSuggester:
    """Service de suggestion automatique de règles basé sur l'analyse des transactions"""

    def suggest_rules(self, compte_num: str, libelle_compte: str,
                      transactions: List[Dict], all_transactions: List[Dict]) -> List[Dict]:
        """
        Moteur avec n-grams progressifs et gestion intelligente du code journal.
        """

        if len(transactions) < 5:
            return []

        # 1. Générer candidats selon le type de compte
        candidates = self.generate_candidates_smart(compte_num, libelle_compte, transactions)

        # 2. Tester chaque candidat (avec et sans journal)
        suggestions = []
        compte_cible = transactions[0]['compte_contrepartie']

        for candidate in candidates:
            # Test sans journal
            result = self.test_candidate_with_journal(candidate, None, transactions, all_transactions, compte_cible)

            # Si collision, tester avec journal dominant
            if result and result['collision'] > 5:
                dominant_journal = self.get_dominant_journal(candidate, transactions)
                if dominant_journal:
                    result_with_journal = self.test_candidate_with_journal(
                        candidate, dominant_journal, transactions, all_transactions, compte_cible
                    )
                    if result_with_journal and result_with_journal['collision'] < result['collision']:
                        result = result_with_journal

            # Garder si acceptable
            if result and result['coverage'] > 50 and result['collision'] < 10:
                suggestions.append(result)

        # 3. Trier par score et retourner top 3
        suggestions.sort(key=lambda x: x['score'], reverse=True)
        return suggestions[:3]

    def generate_candidates_smart(self, compte_num: str, libelle_compte: str, transactions: List[Dict]) -> List[
        List[str]]:
        """Génère candidats avec n-grams progressifs selon le type de compte."""

        if compte_num.startswith('164'):
            # Emprunts : chercher suite de chiffres présente dans >60% des transactions
            return self.extract_loan_numbers(transactions)

        elif compte_num.startswith('4421'):
            # PAS : uniquement PASDSN
            return [['PASDSN']]

        elif compte_num.startswith('63511'):
            # CFE/CVAE : uniquement ces mots
            return [['CFE'], ['CVAE']]

        elif compte_num.startswith(('401', '411', '421', '43')):
            # Comptes tiers : d'abord libellé, puis n-grams progressifs
            candidates = []

            # Mots du libellé
            words = re.findall(r'\b[A-Za-z0-9]{3,}\b', libelle_compte.upper())
            words = [w for w in words if w not in ['SARL', 'SAS', 'FRANCE', 'ENTREPRISE']]

            for word in words[:2]:
                candidates.append([word])

            # Compléter avec n-grams progressifs
            candidates.extend(self.extract_ngrams_progressive(transactions))
            return candidates

        else:
            # Autres comptes : n-grams progressifs uniquement
            return self.extract_ngrams_progressive(transactions)

    def extract_loan_numbers(self, transactions: List[Dict]) -> List[List[str]]:
        """Extrait les numéros d'emprunt présents dans >60% des transactions."""

        # Extraire toutes les suites de chiffres de 8+ digits
        number_counts = Counter()

        for trans in transactions:
            numbers = re.findall(r'\b\d{8,}\b', trans['ecriture_lib'])
            for number in numbers:
                number_counts[number] += 1

        # Garder ceux présents dans >60% des transactions
        candidates = []
        threshold = len(transactions) * 0.6

        for number, count in number_counts.most_common():
            if count >= threshold:
                candidates.append([number])

        return candidates

    def extract_ngrams_progressive(self, transactions: List[Dict]) -> List[List[str]]:
        """N-grams progressifs : teste du plus précis au moins précis."""

        all_ngrams = []

        # Extraire tous les n-grams possibles
        for trans in transactions:
            words = re.findall(r'\b[A-Za-z0-9]{3,}\b', trans['ecriture_lib'].upper())

            # Générer 1-grams, 2-grams, 3-grams
            for n in range(1, 4):
                for i in range(len(words) - n + 1):
                    ngram = tuple(words[i:i + n])
                    all_ngrams.append(ngram)

        # Compter fréquences
        ngram_counts = Counter(all_ngrams)

        # Trier par longueur (plus précis d'abord) puis par fréquence
        candidates = []
        threshold_base = len(transactions) * 0.6

        # Commencer par les 3-grams, puis 2-grams, puis 1-grams
        for n in [3, 2, 1]:
            threshold = threshold_base if n == 1 else threshold_base * 0.8  # Seuil plus bas pour n-grams longs

            n_grams_of_length = [(ng, count) for ng, count in ngram_counts.items() if len(ng) == n]
            n_grams_of_length.sort(key=lambda x: x[1], reverse=True)

            for ngram, count in n_grams_of_length:
                if count >= threshold and len(candidates) < 10:
                    candidates.append(list(ngram))

        return candidates

    def test_candidate_with_journal(self, candidate: List[str],
                                    journal_code: Optional[str],
                                    transactions: List[Dict],
                                    all_transactions: List[Dict],
                                    compte_cible: str) -> Optional[Dict]:
        """Teste un candidat avec ou sans code journal."""

        # Compter matches dans le compte
        matches = []
        for trans in transactions:
            if (all(word.upper() in trans['ecriture_lib'].upper() for word in candidate) and
                    (journal_code is None or trans.get('journal_code') == journal_code)):
                matches.append(trans)

        if not matches:
            return None

        coverage_count = len(matches)
        coverage_percent = (coverage_count / len(transactions)) * 100

        # Compter collisions dans autres comptes
        collision_count = 0
        for trans in all_transactions:
            if (trans['compte_contrepartie'] != compte_cible and
                    all(word.upper() in trans['ecriture_lib'].upper() for word in candidate) and
                    (journal_code is None or trans.get('journal_code') == journal_code)):
                collision_count += 1

        collision_percent = (collision_count / coverage_count) * 100 if coverage_count > 0 else 0

        # Score avec bonus pour journal spécifique
        base_score = self.calculate_base_score(coverage_percent, len(candidate))
        collision_penalty = collision_percent * 2
        journal_bonus = 5 if journal_code else 0  # Bonus pour spécificité journal

        score = max(0, min(100, base_score - collision_penalty + journal_bonus))

        # Description claire
        if journal_code:
            description = f"'{' '.join(candidate)}' sur journal {journal_code}"
            rule_mots_cles = candidate + [f"Journal:{journal_code}"]
        else:
            description = f"'{' '.join(candidate)}' (tous journaux)"
            rule_mots_cles = candidate

        return {
            'mots_cles': rule_mots_cles,
            'mots_cles_clean': candidate,  # Sans le journal pour l'affichage
            'journal_code': journal_code,
            'coverage': round(coverage_percent, 1),
            'collision': round(collision_percent, 1),
            'coverage_count': coverage_count,
            'collision_count': collision_count,
            'score': round(score, 1),
            'description': description
        }

    def get_dominant_journal(self, candidate: List[str], transactions: List[Dict]) -> Optional[str]:
        """Retourne le journal dominant pour un pattern donné."""

        matching_transactions = []
        for trans in transactions:
            if all(word.upper() in trans['ecriture_lib'].upper() for word in candidate):
                matching_transactions.append(trans)

        if not matching_transactions:
            return None

        journal_counts = Counter(trans.get('journal_code') for trans in matching_transactions)

        # Si un journal couvre >70% des matches, c'est le dominant
        for journal, count in journal_counts.most_common(1):
            if count / len(matching_transactions) > 0.7:
                return journal

        return None

    def calculate_base_score(self, coverage_percent: float, pattern_length: int) -> float:
        """Calcule le score de base."""
        if coverage_percent >= 95:
            base = 95
        elif coverage_percent >= 80:
            base = 85
        elif coverage_percent >= 60:
            base = 75
        else:
            base = 50

        # Bonus pour patterns plus longs (plus précis)
        precision_bonus = min(pattern_length * 3, 15)

        return base + precision_bonus