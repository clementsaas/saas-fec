from collections import defaultdict, Counter
import re
from typing import List, Dict, Optional, Set

class RuleSuggester:
    """Algorithme Affectia pour suggérer des règles d'affectation des transactions bancaires"""

    def __init__(self, debug: bool = False):
        # Mots vides étendus (français + termes financiers génériques)
        self.stop_words = {
            'de', 'du', 'des', 'le', 'la', 'les', 'un', 'une', 'et', 'ou', 'pour', 'par', 'sur', 'avec', 'sans',
            'au', 'aux', 'carte', 'cb', 'vir', 'virement', 'paiement', 'retrait', 'facture', 'fact', 'fac',
            'operation', 'oper', 'transaction', 'trans', 'prelevement', 'prlv', 'echeance', 'ech'
        }
        # Seuil minimal pour considérer un motif comme significatif
        self.min_occurrences = 3
        # Mode débogage (verbose) désactivé par défaut
        self.debug = debug

    def normalize_text(self, text: str) -> str:
        """Normalise un texte (majuscules, suppression des accents)"""
        if not text:
            return ""
        text = text.upper()
        accents = {'À': 'A', 'Á': 'A', 'Â': 'A', 'Ã': 'A', 'Ä': 'A', 'Ç': 'C', 'È': 'E', 'É': 'E', 'Ê': 'E', 'Ë': 'E',
                   'Ì': 'I', 'Í': 'I', 'Î': 'I', 'Ï': 'I', 'Ñ': 'N', 'Ò': 'O', 'Ó': 'O', 'Ô': 'O', 'Õ': 'O', 'Ö': 'O',
                   'Ù': 'U', 'Ú': 'U', 'Û': 'U', 'Ü': 'U', 'Ý': 'Y'}
        for accent, normal in accents.items():
            text = text.replace(accent, normal)
        return text

    def extract_ngrams(self, text: str, max_length: int = 5) -> Set[str]:
        """Extrait tous les n-grams uniques de 1 à max_length mots d'un texte"""
        words = text.split()
        ngrams_set = set()
        for n in range(1, min(len(words) + 1, max_length + 1)):
            for i in range(len(words) - n + 1):
                ngram = ' '.join(words[i:i + n])
                # Ignorer le n-gram s'il est uniquement composé de mots vides (très génériques)
                if all(word.lower() in self.stop_words for word in ngram.split()):
                    continue
                ngrams_set.add(ngram)
        return ngrams_set

    def find_account_specific_patterns(self, compte: str, transactions: List[Dict]) -> List[Dict]:
        """Trouve les motifs spécifiques selon le type de compte"""
        if self.debug:
            print(f"🔍 AFFECTIA : Analyse spécifique pour le compte {compte}")
        # Comptes 164 (Emprunts)
        if compte.startswith('164'):
            return self._analyze_emprunt_account(compte, transactions)
        # Comptes 401/411 (Fournisseurs/Clients)
        elif compte.startswith('401') or compte.startswith('411'):
            return self._analyze_tiers_account(compte, transactions)
        # Comptes 421/42 (Personnel et assimilés)
        elif compte.startswith('421') or compte.startswith('42'):
            return self._analyze_personnel_account(compte, transactions)
        # Compte 431 (URSSAF)
        elif compte.startswith('431'):
            return self._analyze_urssaf_account(compte, transactions)
        # Comptes 43 (Organismes sociaux, hors 431)
        elif compte.startswith('43'):
            return self._analyze_social_account(compte, transactions)
        # Compte 4421 (Prélèvement à la source)
        elif compte.startswith('4421'):
            return self._analyze_pas_account(compte, transactions)
        # Comptes 44551 / 4455* (TVA)
        elif compte.startswith('44551') or compte.startswith('4455'):
            return self._analyze_tva_account(compte, transactions)
        # Compte 63511 (Impôts locaux)
        elif compte.startswith('63511'):
            return self._analyze_impots_locaux_account(compte, transactions)
        # Cas général (autres comptes)
        else:
            return self._analyze_general_account(compte, transactions)

    def _analyze_emprunt_account(self, compte: str, transactions: List[Dict]) -> List[Dict]:
        """Analyse spécifique pour les comptes d'emprunt (164)"""
        if self.debug:
            print(f"💰 AFFECTIA : Analyse compte emprunt {compte}")
        number_patterns = Counter()
        journal_pattern = None
        for trans in transactions:
            libelle = self.normalize_text(trans['ecriture_lib'])
            # Extraire les séquences de chiffres (longueur >= 6) présentes (chaque séquence comptée une fois par libellé)
            for num in set(re.findall(r'\d{6,}', libelle)):
                number_patterns[num] += 1
            # Vérifier si toutes les transactions proviennent du même journal
            if journal_pattern is None:
                journal_pattern = trans['journal_code']
            elif journal_pattern != trans['journal_code']:
                journal_pattern = None
        rules = []
        for number, count in number_patterns.most_common(3):
            if count >= self.min_occurrences:
                rule = {"mot_cle_1": number, "transactions_couvertes": count, "collision": False}
                if journal_pattern:
                    rule["journal"] = journal_pattern
                rules.append(rule)
                if self.debug:
                    print(f"✅ AFFECTIA : Règle emprunt trouvée - {number} ({count} transactions)")
        # Ajouter critères journal/montant si applicables
        return self._add_journal_and_amount_criteria(rules, transactions)

    def _analyze_tiers_account(self, compte: str, transactions: List[Dict]) -> List[Dict]:
        """Analyse spécifique pour les comptes fournisseurs/clients (401/411)"""
        if self.debug:
            print(f"🏢 AFFECTIA : Analyse compte tiers {compte}")

        try:
            from thefuzz import fuzz
            from unidecode import unidecode
            fuzzy_available = True
        except ImportError:
            fuzzy_available = False
            if self.debug:
                print(f"⚠️ AFFECTIA : TheFuzz non disponible, fuzzy matching désactivé")

        all_libelles = [self.normalize_text(t['ecriture_lib']) for t in transactions]
        if all_libelles:
            # Extraire tous les n-grams de 1 à 5 mots du premier libellé
            first_ngrams = self.extract_ngrams(all_libelles[0], max_length=5)
            # Garder seulement ceux présents dans TOUS les libellés
            common_ngrams = set()
            for ngram in first_ngrams:
                if all(ngram in libelle for libelle in all_libelles):
                    # Filtrer les n-grams trop génériques
                    words_in_ngram = ngram.split()
                    if all(len(w) >= 3 and not w.isdigit() and w.lower() not in self.stop_words for w in
                           words_in_ngram):
                        common_ngrams.add(ngram)
                        if self.debug:
                            print(f"🔍 AFFECTIA : N-gram commun trouvé - '{ngram}'")

            if self.debug:
                print(f"🔍 AFFECTIA : {len(common_ngrams)} n-gram(s) commun(s) détecté(s) : {list(common_ngrams)}")

            # Recherche de correspondance avec le nom du compte via fuzzy matching
            if fuzzy_available and len(compte) >= 3:
                compte_clean = unidecode(compte.lower()).replace('-', ' ').replace('_', ' ')
                if self.debug:
                    print(f"🔍 AFFECTIA : Recherche fuzzy pour '{compte}' → '{compte_clean}'")

                fuzzy_matches = []
                for ngram in common_ngrams:
                    ngram_clean = unidecode(ngram.lower()).replace('-', ' ').replace('_', ' ')

                    # Utiliser plusieurs types de scores TheFuzz
                    partial_score = fuzz.partial_ratio(compte_clean, ngram_clean)
                    token_set_score = fuzz.token_set_ratio(compte_clean, ngram_clean)
                    best_score = max(partial_score, token_set_score)

                    if best_score >= 80:  # Seuil de similarité
                        fuzzy_matches.append((ngram, best_score))
                        if self.debug:
                            print(f"🎯 AFFECTIA : Match fuzzy - '{ngram}' (score: {best_score})")

                # Prioriser la meilleure correspondance fuzzy
                if fuzzy_matches:
                    fuzzy_matches.sort(key=lambda x: (-x[1], -len(x[0].split()), -len(x[0])))
                    best_ngram = fuzzy_matches[0][0]
                    if self.debug:
                        print(
                            f"✅ AFFECTIA : Meilleur match fuzzy sélectionné - '{best_ngram}' (score: {fuzzy_matches[0][1]})")
                elif common_ngrams:
                    # Pas de match fuzzy, prendre le n-gram le plus long
                    best_ngram = max(common_ngrams, key=lambda x: (len(x.split()), len(x)))
                    if self.debug:
                        print(f"✅ AFFECTIA : N-gram général sélectionné - '{best_ngram}'")
                else:
                    best_ngram = None
            else:
                # Pas de fuzzy matching, utiliser la logique classique
                if common_ngrams:
                    best_ngram = max(common_ngrams, key=lambda x: (len(x.split()), len(x)))
                    if self.debug:
                        print(f"✅ AFFECTIA : N-gram classique sélectionné - '{best_ngram}'")
                else:
                    best_ngram = None

            if best_ngram:
                rules = [{
                    "mot_cle_1": best_ngram,
                    "transactions_couvertes": len(transactions),
                    "collision": False
                }]
                return self._add_journal_and_amount_criteria(rules, transactions)

        # Aucun n-gram distinctif commun → analyse générale
        if self.debug:
            print(f"⚠️ AFFECTIA : Pas de motif unique de tiers pour {compte}, analyse générale.")
        return self._analyze_general_account(compte, transactions)

    def _analyze_personnel_account(self, compte: str, transactions: List[Dict]) -> List[Dict]:
        """Analyse spécifique pour les comptes de personnel (421/42)"""
        if self.debug:
            print(f"👥 AFFECTIA : Analyse compte personnel {compte}")
        all_libelles = [self.normalize_text(t['ecriture_lib']) for t in transactions]
        # Compte individuel : chercher des n-grams communs à tous les libellés (typiquement prénom + nom)
        if all_libelles:
            # Extraire tous les n-grams de 1 à 3 mots du premier libellé
            first_ngrams = self.extract_ngrams(all_libelles[0], max_length=3)
            # Garder seulement ceux présents dans TOUS les libellés
            common_ngrams = set()
            for ngram in first_ngrams:
                if all(ngram in libelle for libelle in all_libelles):
                    # Filtrer les n-grams trop génériques
                    words_in_ngram = ngram.split()
                    if all(len(w) >= 3 and not w.isdigit() and w.lower() not in self.stop_words for w in
                           words_in_ngram):
                        common_ngrams.add(ngram)
                        if self.debug:
                            print(f"🔍 AFFECTIA : N-gram commun trouvé - '{ngram}'")

            # Priorité spéciale aux n-grams de noms (2 mots de 3+ caractères, pas de mots vides)
            name_ngrams = []
            for ngram in common_ngrams:
                words = ngram.split()
                if (len(words) == 2 and
                        all(len(w) >= 3 and not w.isdigit() and w.lower() not in self.stop_words for w in words) and
                        all(w.isalpha() for w in words)):  # Uniquement des lettres (pas de chiffres ou symboles)
                    name_ngrams.append(ngram)

            if self.debug:
                print(f"🔍 AFFECTIA : N-grams de noms détectés : {name_ngrams}")

            if self.debug:
                print(f"🔍 AFFECTIA : {len(common_ngrams)} n-gram(s) commun(s) détecté(s) : {list(common_ngrams)}")

            if name_ngrams:
                # Privilégier les n-grams de noms (prénom nom)
                best_ngram = max(name_ngrams, key=lambda x: len(x))
                if self.debug:
                    print(f"✅ AFFECTIA : N-gram de nom sélectionné - '{best_ngram}'")
            elif common_ngrams:
                # Sinon, prendre le n-gram le plus long et le plus spécifique
                best_ngram = max(common_ngrams, key=lambda x: (len(x.split()), len(x)))
            else:
                best_ngram = None

            if best_ngram:
                rules = [{
                    "mot_cle_1": best_ngram,
                    "transactions_couvertes": len(transactions),
                    "collision": False
                }]
                if self.debug:
                    print(f"✅ AFFECTIA : Nom complet trouvé - {best_ngram} ({len(transactions)} transactions)")
                return self._add_journal_and_amount_criteria(rules, transactions)
            elif self.debug:
                print(f"⚠️ AFFECTIA : Aucun n-gram commun trouvé, basculement vers analyse collective")
        # Compte collectif : repérer les noms récurrents dans les libellés (prénoms/noms d'employés)
        name_patterns = Counter()
        for trans in transactions:
            libelle = self.normalize_text(trans['ecriture_lib'])
            words = libelle.split()
            # Noms complets (2 mots consécutifs)
            for i in range(len(words) - 1):
                if (len(words[i]) >= 3 and len(words[i+1]) >= 3 and
                        not words[i].isdigit() and not words[i+1].isdigit() and
                        words[i].lower() not in self.stop_words and words[i+1].lower() not in self.stop_words):
                    full_name = f"{words[i]} {words[i+1]}"
                    name_patterns[full_name] += 1
            # Noms ou prénoms seuls
            for w in words:
                if len(w) >= 3 and not w.isdigit() and w.lower() not in self.stop_words:
                    name_patterns[w] += 1
        rules = []
        for name, count in name_patterns.most_common(3):
            if count >= self.min_occurrences:
                rules.append({"mot_cle_1": name, "transactions_couvertes": count, "collision": False})
                if self.debug:
                    print(f"✅ AFFECTIA : Règle personnel trouvée - {name} ({count} transactions)")
        return self._add_journal_and_amount_criteria(rules, transactions)

    def _analyze_social_account(self, compte: str, transactions: List[Dict]) -> List[Dict]:
        """Analyse spécifique pour les comptes d'organismes sociaux (43*, hors 431)"""
        if self.debug:
            print(f"🏛️ AFFECTIA : Analyse compte organisme social {compte}")
        patterns = ['URSSAF', 'MALAKOFF', 'KLESIA', 'AGIRC', 'ARRCO', 'POLE EMPLOI', 'CPAM']
        found_rules = []
        for pattern in patterns:
            count = sum(1 for t in transactions if pattern in self.normalize_text(t['ecriture_lib']))
            if count >= self.min_occurrences:
                found_rules.append({"mot_cle_1": pattern, "transactions_couvertes": count, "collision": False})
                if self.debug:
                    print(f"✅ AFFECTIA : Règle organisme trouvée - {pattern} ({count} transactions)")
        return self._add_journal_and_amount_criteria(found_rules[:3], transactions)

    def _analyze_urssaf_account(self, compte: str, transactions: List[Dict]) -> List[Dict]:
        """Analyse spécifique pour les comptes URSSAF (431)"""
        if self.debug:
            print(f"🏛️ AFFECTIA : Analyse compte URSSAF {compte}")
        ur_patterns = Counter()
        for trans in transactions:
            libelle = self.normalize_text(trans['ecriture_lib'])
            # Codes commençant par "UR" suivis de chiffres
            for code in set(re.findall(r'UR\d+', libelle)):
                ur_patterns[code] += 1
        rules = []
        for code, count in ur_patterns.most_common(3):
            if count >= self.min_occurrences:
                rules.append({"mot_cle_1": code, "transactions_couvertes": count, "collision": False})
                if self.debug:
                    print(f"✅ AFFECTIA : Règle URSSAF trouvée - {code} ({count} transactions)")
        # Si aucun code "URxxxx" récurrent, chercher simplement "URSSAF"
        if not rules:
            urssaf_count = sum(1 for t in transactions if 'URSSAF' in self.normalize_text(t['ecriture_lib']))
            if urssaf_count >= self.min_occurrences:
                rules.append({"mot_cle_1": "URSSAF", "transactions_couvertes": urssaf_count, "collision": False})
                if self.debug:
                    print(f"✅ AFFECTIA : Règle URSSAF générale trouvée ({urssaf_count} transactions)")
        return self._add_journal_and_amount_criteria(rules, transactions)

    def _analyze_pas_account(self, compte: str, transactions: List[Dict]) -> List[Dict]:
        """Analyse spécifique pour le compte Prélèvement À la Source (4421)"""
        if self.debug:
            print(f"📋 AFFECTIA : Analyse compte PAS {compte}")
        pas_count = sum(1 for t in transactions if 'PASDSN' in self.normalize_text(t['ecriture_lib']))
        rules = []
        if pas_count >= self.min_occurrences:
            rules.append({"mot_cle_1": "PASDSN", "transactions_couvertes": pas_count, "collision": False})
            if self.debug:
                print(f"✅ AFFECTIA : Règle PAS trouvée - PASDSN ({pas_count} transactions)")
        return self._add_journal_and_amount_criteria(rules, transactions)

    def _analyze_tva_account(self, compte: str, transactions: List[Dict]) -> List[Dict]:
        """Analyse spécifique pour les comptes de TVA (44551, 4455*)"""
        if self.debug:
            print(f"📊 AFFECTIA : Analyse compte TVA {compte}")
        patterns = ['3517SCA12', '3310CA3', 'TVA']
        found_rules = []
        for pattern in patterns:
            count = sum(1 for t in transactions if pattern in self.normalize_text(t['ecriture_lib']))
            if count >= self.min_occurrences:
                found_rules.append({"mot_cle_1": pattern, "transactions_couvertes": count, "collision": False})
                if self.debug:
                    print(f"✅ AFFECTIA : Règle TVA trouvée - {pattern} ({count} transactions)")
        return self._add_journal_and_amount_criteria(found_rules[:3], transactions)

    def _analyze_impots_locaux_account(self, compte: str, transactions: List[Dict]) -> List[Dict]:
        """Analyse spécifique pour le compte des impôts locaux (63511)"""
        if self.debug:
            print(f"🏛️ AFFECTIA : Analyse compte impôts locaux {compte}")
        patterns = ['CFE', 'CVAE']
        found_rules = []
        for pattern in patterns:
            count = sum(1 for t in transactions if pattern in self.normalize_text(t['ecriture_lib']))
            if count >= self.min_occurrences:
                found_rules.append({"mot_cle_1": pattern, "transactions_couvertes": count, "collision": False})
                if self.debug:
                    print(f"✅ AFFECTIA : Règle impôt local trouvée - {pattern} ({count} transactions)")
        return self._add_journal_and_amount_criteria(found_rules, transactions)

    def _analyze_general_account(self, compte: str, transactions: List[Dict]) -> List[Dict]:
        """Analyse générale par n-grams pour les autres comptes"""
        if self.debug:
            print(f"🔍 AFFECTIA : Analyse générale pour le compte {compte}")
        if len(transactions) < self.min_occurrences:
            if self.debug:
                print(f"⚠️ AFFECTIA : Pas assez de transactions ({len(transactions)} < {self.min_occurrences})")
            return []
        ngram_counter = Counter()
        ngram_transaction_ids = {}
        # Extraire tous les n-grams (1 à 5 mots) de chaque transaction et compter les transactions correspondantes
        for trans in transactions:
            libelle = self.normalize_text(trans['ecriture_lib'])
            trans_id = trans.get('id', None) or id(trans)
            for ngram in self.extract_ngrams(libelle):
                ngram_counter[ngram] += 1
                # Suivre l'ensemble des IDs de transactions contenant ce n-gram
                ngram_transaction_ids.setdefault(ngram, set()).add(trans_id)
        # Ne garder que les n-grams fréquents (min_occurrences) et trier par fréquence puis longueur
        frequent_ngrams = [(ng, cnt) for ng, cnt in ngram_counter.items() if cnt >= self.min_occurrences]
        frequent_ngrams.sort(key=lambda x: (x[1], len(x[0])), reverse=True)
        selected_ngrams = []
        for ngram, count in frequent_ngrams[:10]:  # considérer jusqu'aux 10 motifs les plus fréquents
            trans_ids = ngram_transaction_ids.get(ngram, set())
            # Vérifier si ce motif est redondant avec un motif déjà sélectionné (même couverture de transactions)
            redundant = False
            for sel_ng, _ in selected_ngrams:
                if trans_ids == ngram_transaction_ids.get(sel_ng, set()):
                    # Si même couverture, garder le motif le plus long
                    if len(ngram) > len(sel_ng):
                        selected_ngrams = [(ng, cnt) for ng, cnt in selected_ngrams if ng != sel_ng]
                        selected_ngrams.append((ngram, count))
                    redundant = True
                    break
            if not redundant:
                selected_ngrams.append((ngram, count))
        # Construire les règles à partir des motifs retenus (max 3 règles)
        rules = []
        for ngram, count in selected_ngrams[:3]:
            # Transactions du compte contenant ce n-gram
            matching_transactions = [t for t in transactions if ngram in self.normalize_text(t['ecriture_lib'])]
            if not matching_transactions:
                continue
            journals = {t['journal_code'] for t in matching_transactions}
            montants = [t['montant'] for t in matching_transactions]
            montant_criterion = self._analyze_montant_pattern(montants)
            rule = {
                "mot_cle_1": ngram,
                "transactions_couvertes": len(matching_transactions),
                "collision": False
            }
            if len(journals) == 1:
                rule["journal"] = journals.pop()
            if montant_criterion:
                rule["montant"] = montant_criterion
            rules.append(rule)
            if self.debug:
                print(f"✅ AFFECTIA : Règle générale trouvée - '{ngram}' ({len(matching_transactions)} transactions)")
        return rules

    def _analyze_montant_pattern(self, montants: List[float]) -> Optional[str]:
        """Analyse les montants pour définir un critère de montant (signe ou valeur fixe)"""
        if not montants:
            return None
        # Tous les montants positifs ?
        if all(m > 0 for m in montants):
            return "> 0"
        # Tous les montants négatifs ?
        if all(m < 0 for m in montants):
            return "< 0"
        # Valeur exacte prédominante ?
        montant_counter = Counter(montants)
        most_common_value, count = montant_counter.most_common(1)[0]
        if count / len(montants) >= 0.95:
            # Si une valeur unique représente >= 95% des montants
            return f"= {most_common_value}"
        return None

    def _add_journal_and_amount_criteria(self, rules: List[Dict], transactions: List[Dict]) -> List[Dict]:
        """Ajoute les critères de journal et de montant aux règles quand c'est possible"""
        enhanced_rules = []
        for rule in rules:
            matching_transactions = []
            for trans in transactions:
                libelle = self.normalize_text(trans['ecriture_lib'])
                # Vérifier que le libellé contient mot_cle_1 (et mot_cle_2 le cas échéant)
                if rule["mot_cle_1"] in libelle and ("mot_cle_2" not in rule or rule["mot_cle_2"] in libelle):
                    matching_transactions.append(trans)
            if not matching_transactions:
                continue
            journals = {t['journal_code'] for t in matching_transactions}
            if len(journals) == 1:
                rule["journal"] = list(journals)[0]
            montant_criterion = self._analyze_montant_pattern([t['montant'] for t in matching_transactions])
            if montant_criterion:
                rule["montant"] = montant_criterion
            enhanced_rules.append(rule)
        return enhanced_rules

    def check_collisions(self, rules: List[Dict], compte: str, all_transactions: List[Dict]) -> List[Dict]:
        """Vérifie qu'aucune règle ne s'applique à un autre compte (collisions)"""
        if self.debug:
            print(f"🔍 AFFECTIA : Vérification des collisions pour {len(rules)} règle(s) du compte {compte}")
        validated_rules = []
        for rule in rules:
            collision = False
            for trans in all_transactions:
                if trans['compte_contrepartie'] == compte:
                    continue  # ignorer les transactions du compte cible lui-même
                libelle = self.normalize_text(trans['ecriture_lib'])
                if rule['mot_cle_1'] not in libelle:
                    continue
                if 'mot_cle_2' in rule and rule['mot_cle_2'] not in libelle:
                    continue
                if 'journal' in rule and trans['journal_code'] != rule['journal']:
                    continue
                if 'montant' in rule:
                    crit = rule['montant']
                    m = trans['montant']
                    if crit.startswith('='):
                        expected = float(crit[2:])
                        if m != expected:
                            continue
                    elif crit == '> 0' and m <= 0:
                        continue
                    elif crit == '< 0' and m >= 0:
                        continue
                # Si tous les critères sont remplis, on a une collision
                collision = True
                if self.debug:
                    print(f"❌ AFFECTIA : Collision pour règle '{rule['mot_cle_1']}' avec compte {trans['compte_contrepartie']}")
                break
            rule['collision'] = collision
            validated_rules.append(rule)
            if not collision and self.debug:
                print(f"✅ AFFECTIA : Règle '{rule['mot_cle_1']}' sans collision")
            elif collision and self.debug:
                print(f"❌ AFFECTIA : Règle '{rule['mot_cle_1']}' écartée (collision)")
        return validated_rules

    def enhance_rules_with_second_keyword(self, rules: List[Dict], compte: str, transactions: List[Dict], all_transactions: List[Dict]) -> List[Dict]:
        """Ajoute un mot_cle_2 aux règles en collision pour les rendre plus spécifiques"""
        if self.debug:
            print(f"🔧 AFFECTIA : Amélioration des règles avec second mot-clé pour le compte {compte}")
        improved_rules = []
        for rule in rules:
            if not rule.get('collision', False):
                improved_rules.append(rule)
                continue
            if self.debug:
                print(f"🔧 AFFECTIA : Tentative d'amélioration pour la règle '{rule['mot_cle_1']}'")
            # Transactions du compte cible contenant mot_cle_1
            matching_transactions = [t for t in transactions if rule['mot_cle_1'] in self.normalize_text(t['ecriture_lib'])]
            if not matching_transactions:
                continue
            # Mots communs à tous ces libellés (hors mot_cle_1)
            common_words = set(self.normalize_text(matching_transactions[0]['ecriture_lib']).split())
            for trans in matching_transactions[1:]:
                common_words &= set(self.normalize_text(trans['ecriture_lib']).split())
            motcle1_parts = set(rule['mot_cle_1'].split())
            candidate_words = [w for w in common_words if len(w) >= 3 and not w.isdigit() and w not in motcle1_parts]
            best_rule = None
            # Essayer les candidats par ordre décroissant de longueur (plus le mot est long, plus il est spécifique)
            for candidate in sorted(candidate_words, key=len, reverse=True):
                test_rule = rule.copy()
                test_rule['mot_cle_2'] = candidate
                test_rule['collision'] = False
                # Tester la règle combinée sur toutes les transactions hors compte cible
                collision = False
                for trans in all_transactions:
                    if trans['compte_contrepartie'] == compte:
                        continue
                    libelle = self.normalize_text(trans['ecriture_lib'])
                    if test_rule['mot_cle_1'] in libelle and test_rule['mot_cle_2'] in libelle:
                        # Vérifier aussi les autres critères (journal, montant)
                        if 'journal' in test_rule and trans['journal_code'] != test_rule['journal']:
                            continue
                        if 'montant' in test_rule:
                            crit = test_rule['montant']
                            m = trans['montant']
                            if crit.startswith('='):
                                expected = float(crit[2:])
                                if m != expected:
                                    continue
                            elif crit == '> 0' and m <= 0:
                                continue
                            elif crit == '< 0' and m >= 0:
                                continue
                        # Si trans contient les deux mots-clés (et satisfait journal/montant), collision
                        collision = True
                        break
                if not collision:
                    best_rule = test_rule
                    if self.debug:
                        print(f"✅ AFFECTIA : Collision résolue avec mot_cle_2='{candidate}' pour la règle '{rule['mot_cle_1']}'")
                    break
            if best_rule:
                # Ajouter critères journal/montant pour la nouvelle règle affinée
                best_rule = self._add_journal_and_amount_criteria([best_rule], transactions)[0]
                best_rule['collision'] = False
                improved_rules.append(best_rule)
            else:
                if self.debug:
                    print(f"❌ AFFECTIA : Échec de l'amélioration pour la règle '{rule['mot_cle_1']}'")
        return improved_rules

    def suggest_rules_for_account(self, compte: str, transactions: List[Dict], all_transactions: List[Dict]) -> List[Dict]:
        """Analyse un compte et suggère jusqu'à 3 règles d'affectation basées sur ses transactions"""
        if self.debug:
            print(f"\n🚀 AFFECTIA : Début de l'analyse du compte {compte} ({len(transactions)} transactions)")
        if len(transactions) < self.min_occurrences:
            if self.debug:
                print(f"⚠️ AFFECTIA : Pas assez de transactions pour le compte {compte}")
            return []
        # 1. Motifs spécifiques selon le type de compte
        candidate_rules = self.find_account_specific_patterns(compte, transactions)
        # 2. Ajout des critères journal et montant aux règles candidates
        candidate_rules = self._add_journal_and_amount_criteria(candidate_rules, transactions)
        # 3. Vérification de l'unicité des règles (collisions inter-comptes)
        candidate_rules = self.check_collisions(candidate_rules, compte, all_transactions)
        # 4. Amélioration des règles en collision avec un deuxième mot-clé (si possible)
        candidate_rules = self.enhance_rules_with_second_keyword(candidate_rules, compte, transactions, all_transactions)
        # 5. Ne conserver que les règles sans collision
        valid_rules = [rule for rule in candidate_rules if not rule.get('collision', False)]
        # 6. Tri des règles (couverture desc, nb de mots-clés desc, longueur totale desc)
        valid_rules.sort(key=lambda r: (
            -r['transactions_couvertes'],
            -(1 + (1 if 'mot_cle_2' in r else 0)),
            -(len(r['mot_cle_1']) + (len(r['mot_cle_2']) if 'mot_cle_2' in r else 0))
        ))
        # 7. Limiter à 3 règles max
        final_rules = valid_rules[:3]
        if self.debug:
            print(f"🎯 AFFECTIA : {len(final_rules)} règle(s) suggérée(s) pour le compte {compte}")
        return final_rules
