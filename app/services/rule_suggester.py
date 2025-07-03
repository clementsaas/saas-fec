import re
from collections import Counter
from typing import List, Dict, Optional, Set, Counter as TypingCounter


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

    def extract_ngrams_all(self, libelles: List[str], n_max: int = 4, min_df: int = 3, max_set: int = 50) -> tuple[
        dict[str, set[int] | tuple[int, int]], TypingCounter]:
        """
        Extrait tous les n-grams de tous les libellés avec optimisation mémoire

        Args:
            libelles: Liste des libellés à analyser
            n_max: Nombre maximum de mots par n-gram
            min_df: Fréquence documentaire minimale pour retenir un n-gram
            max_set: Seuil au-dessus duquel on ne stocke que le compteur (pas les indices)

        Returns:
            tuple: (ngram_indices_dict, df_counter)
                - ngram_indices_dict: {ngram: set(indices) ou tuple(sample_idx, count)}
                - df_counter: Counter des fréquences documentaires
        """
        # Cache de normalisation pour éviter les appels redondants
        normalized_libelles = [self.normalize_text(libelle) for libelle in libelles]

        ngram_indices = {}
        df_counter = Counter()

        for doc_idx, libelle_norm in enumerate(normalized_libelles):
            words = libelle_norm.split()

            # Extraire n-grams de ce document
            doc_ngrams = set()
            for n in range(1, min(len(words) + 1, n_max + 1)):
                for i in range(len(words) - n + 1):
                    ngram_words = words[i:i + n]

                    # Filtrer uniquement les tokens courts ou numériques
                    if any(len(w) < 3 or w.isdigit() for w in ngram_words):
                        continue

                    # Ignorer n-grams entièrement composés de mots vides
                    if all(w.lower() in self.stop_words for w in ngram_words):
                        continue

                    # Filtrer n-grams commençant ou finissant par un stop-word
                    if ngram_words[0].lower() in self.stop_words or ngram_words[-1].lower() in self.stop_words:
                        continue

                    ngram = ' '.join(ngram_words)
                    doc_ngrams.add(ngram)

            # Mettre à jour les compteurs pour ce document
            for ngram in doc_ngrams:
                df_counter[ngram] += 1

                # Gestion optimisée des indices
                if ngram not in ngram_indices:
                    ngram_indices[ngram] = {doc_idx}
                elif isinstance(ngram_indices[ngram], set):
                    ngram_indices[ngram].add(doc_idx)
                    # Conversion en compteur si trop fréquent, mais conserver un échantillon
                    if len(ngram_indices[ngram]) > max_set:
                        sample_idx = next(iter(ngram_indices[ngram]))
                        ngram_indices[ngram] = (sample_idx, len(ngram_indices[ngram]))  # (échantillon, count)
                else:
                    # Déjà un compteur, incrémenter
                    ngram_indices[ngram] = (ngram_indices[ngram][0], ngram_indices[ngram][1] + 1)

        # Filtrer par fréquence documentaire minimale
        filtered_ngrams = {}
        filtered_df = Counter()

        for ngram, df in df_counter.items():
            if df >= min_df:
                filtered_ngrams[ngram] = ngram_indices[ngram]
                filtered_df[ngram] = df

        return filtered_ngrams, filtered_df

    def find_account_specific_patterns(self, compte: str, transactions: List[Dict],
                                       all_transactions: List[Dict] = None) -> List[Dict]:
        """Trouve les motifs spécifiques selon le type de compte"""
        if self.debug:
            print(f"🔍 AFFECTIA : Analyse spécifique pour le compte {compte}")
        # Comptes 164 (Emprunts)
        if compte.startswith('164'):
            return self._analyze_emprunt_account(compte, transactions)
            # Comptes 401/411 (Fournisseurs/Clients)
        elif compte.startswith('401') or compte.startswith('411'):
            return self._analyze_tiers_account(compte, transactions, all_transactions)
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

    def _analyze_tiers_account(self, compte: str, transactions: List[Dict], all_transactions: List[Dict] = None,
                               compte_libelle=None) -> \
    List[Dict]:
        """Analyse spécifique pour les comptes fournisseurs/clients (401/411)"""
        import logging
        logger = logging.getLogger(__name__)

        if self.debug:
            logger.debug(f"🏢 AFFECTIA : Analyse compte tiers {compte}")

        try:
            from rapidfuzz import fuzz, process
            fuzzy_available = True
        except ImportError:
            fuzzy_available = False
            if self.debug:
                logger.debug(f"⚠️ AFFECTIA : RapidFuzz non disponible, fuzzy matching désactivé")

        # Dictionnaire pour éviter les doublons (clé = mot_cle_1)
        candidates_dict = {}

        # Racines génériques étendues avec pluriels et variantes
        generic_roots = {
            'factur', 'factur', 'paiement', 'paie', 'virement', 'vir', 'cheque', 'chq',
            'prelevement', 'prlv', 'remboursement', 'remb', 'achat', 'achats', 'vente', 'ventes',
            'commerce', 'commerc', 'electronique', 'operation', 'oper', 'transaction', 'trans',
            'carte', 'cartes', 'commande', 'commandes', 'cmd', 'livraison', 'livraisons',
            'frais', 'service', 'services', 'prestation', 'prestations',
            'societe', 'societes', 'entreprise', 'entreprises', 'company', 'companies',
            'corp', 'corporation', 'sarl', 'sas', 'eurl', 'sa', 'ltd', 'inc', 'co', 'cie'
        }

        def normalize_for_comparison(text):
            """Normalisation unifiée pour comparaisons (collision, fuzzy)"""
            if not text:
                return ""
            try:
                from unidecode import unidecode
                normalized = unidecode(text.upper()).strip()
            except ImportError:
                normalized = text.upper().strip()
            # Supprimer caractères spéciaux mais garder espaces et tirets
            normalized = re.sub(r'[^\w\s-]', ' ', normalized)
            normalized = re.sub(r'\s+', ' ', normalized).strip()
            return normalized

        def is_generic_word(mot_cle):
            """Vérifie si un mot est générique (avec variantes et pluriels)"""
            mot_clean = normalize_for_comparison(mot_cle).lower()
            return any(mot_clean.startswith(root) for root in generic_roots)

        def calculate_specificity_score(mot_cle, coverage_ratio):
            """Calcule un score de spécificité équilibré avec pénalité généricité"""
            # Pénalité très forte pour mots génériques
            if is_generic_word(mot_cle):
                return 0.1

            # Score basé sur longueur mais modéré
            length = len(mot_cle)
            if length <= 2:
                return 0.05
            elif length == 3:
                return 0.4
            elif length == 4:
                return 0.7
            elif length <= 6:
                return 1.0
            else:
                # Bonus modéré pour mots longs mais seulement si couverture forte
                bonus = min(0.05, coverage_ratio * 0.1)  # Max +0.05, proportionnel à la couverture
                return 1.0 + bonus

        # PRÉ-CALCULS OPTIMISÉS pour éviter O(W × N)

        # 1. Index inverse des libellés normalisés pour les transactions courantes
        current_libelles_norm = []
        libelle_to_transactions = {}

        for i, trans in enumerate(transactions):
            libelle_norm = normalize_for_comparison(trans['ecriture_lib'])
            current_libelles_norm.append(libelle_norm)

            # Index inverse : chaque mot → liste des indices de transactions
            for word in libelle_norm.split():
                if len(word) >= 3:
                    if word not in libelle_to_transactions:
                        libelle_to_transactions[word] = []
                    libelle_to_transactions[word].append(i)

        # 2. Pré-calcul pour détection collision (autres comptes)
        other_libelles_norm = []
        if all_transactions:
            for trans in all_transactions:
                trans_compte = None

                # Identifier le compte de la transaction
                if trans.get('compte_contrepartie'):
                    trans_compte = trans['compte_contrepartie']
                elif trans.get('compte_final') and not trans['compte_final'].startswith('512'):
                    trans_compte = trans['compte_final']
                elif trans.get('compte_num') and not trans['compte_num'].startswith('512'):
                    trans_compte = trans['compte_num']

                # Ne garder que les autres comptes
                if trans_compte and trans_compte != compte:
                    other_libelles_norm.append(normalize_for_comparison(trans['ecriture_lib']))

        def find_matching_transactions_fast(mot_cle_norm):
            """Trouve rapidement les transactions contenant le mot-clé (via index)"""
            matching_indices = set()

            # Chercher dans l'index inverse
            if mot_cle_norm in libelle_to_transactions:
                matching_indices.update(libelle_to_transactions[mot_cle_norm])

            # Recherche par inclusion (fallback pour mots composés)
            for word, indices in libelle_to_transactions.items():
                if mot_cle_norm in word or word in mot_cle_norm:
                    matching_indices.update(indices)

            return [transactions[i] for i in matching_indices]

        def check_collision_optimized(mot_cle):
            """Détection collision optimisée avec normalisation uniforme"""
            if not other_libelles_norm:
                return False, 0, 0.0

            # Normaliser le mot-clé pour comparaison
            mot_cle_norm = normalize_for_comparison(mot_cle)

            # Compter collisions avec normalisation
            collision_count = sum(1 for libelle in other_libelles_norm if mot_cle_norm in libelle)
            total_other = len(other_libelles_norm)
            collision_ratio = collision_count / total_other if total_other > 0 else 0.0

            # Seuils adaptatifs
            has_significant_collision = (
                                                collision_count >= 5 and collision_ratio >= 0.03  # Seuil plus strict
                                        ) or (
                                                collision_count >= 15  # Seuil absolu réduit
                                        )

            return has_significant_collision, collision_count, collision_ratio

        def calculate_collision_penalty(has_collision, collision_ratio, coverage_ratio):
            """Pénalité collision pondérée par la couverture du compte"""
            if not has_collision:
                return 1.0

            # Pénalité de base selon le ratio de collision
            if collision_ratio >= 0.4:
                base_penalty = 0.1
            elif collision_ratio >= 0.2:
                base_penalty = 0.3
            elif collision_ratio >= 0.1:
                base_penalty = 0.5
            elif collision_ratio >= 0.05:
                base_penalty = 0.7
            else:
                base_penalty = 0.85

            # Ajustement selon la couverture : plus la couverture est forte, moins on pénalise
            coverage_bonus = min(0.3, coverage_ratio * 0.4)  # Max +30% si couverture parfaite
            final_penalty = min(1.0, base_penalty + coverage_bonus)

            return final_penalty

        def add_candidate(mot_cle, trans_count, trans_matched, match_type, source_desc):
            """Ajoute un candidat avec scoring optimisé"""
            coverage = trans_count / len(transactions)
            specificity_score = calculate_specificity_score(mot_cle, coverage)

            # Détection collision
            has_collision, collision_count, collision_ratio = check_collision_optimized(mot_cle)
            collision_penalty = calculate_collision_penalty(has_collision, collision_ratio, coverage)

            # Score composite final
            composite_score = specificity_score * coverage * collision_penalty

            # Log collision significative seulement
            if self.debug and has_collision and collision_ratio >= 0.05:
                logger.debug(
                    f"⚠️ AFFECTIA : Collision '{mot_cle}' - {collision_count}/{len(other_libelles_norm)} ({collision_ratio:.1%}) - Pénalité: {collision_penalty:.2f}")

            if mot_cle not in candidates_dict or candidates_dict[mot_cle]["composite_score"] < composite_score:
                candidates_dict[mot_cle] = {
                    "mot_cle_1": mot_cle,
                    "transactions_couvertes": trans_count,
                    "transactions_matched": trans_matched,
                    "coverage_score": coverage,
                    "specificity_score": specificity_score,
                    "composite_score": composite_score,
                    "collision": has_collision,
                    "collision_count": collision_count,
                    "collision_ratio": collision_ratio,
                    "collision_penalty": collision_penalty,
                    "match_type": match_type,
                    "source": source_desc
                }

        # ÉTAPE 1 : Analyser le libellé du compte
        compte_libelle = transactions[0].get('compte_libelle', '') if transactions else ''
        if compte_libelle:
            compte_words = self.normalize_text(compte_libelle).split()
            significant_compte_words = [w for w in compte_words
                                        if len(w) >= 3 and w.lower() not in self.stop_words and not w.isdigit()]

            if self.debug:
                logger.debug(f"🔍 AFFECTIA : Libellé '{compte_libelle}' → mots: {significant_compte_words}")

            for word in significant_compte_words:
                # Test exact optimisé
                word_norm = normalize_for_comparison(word)
                exact_matches = find_matching_transactions_fast(word_norm)

                # Pour les comptes 401/411, accepter même avec moins de min_occurrences si c'est le libellé du compte
                min_required = 1 if (compte.startswith('401') or compte.startswith('411')) else self.min_occurrences

                if len(exact_matches) >= min_required:
                    # Bonus spécial pour les mots du libellé de compte : score forcé à 100% si couverture parfaite
                    coverage = len(exact_matches) / len(transactions)
                    if coverage == 1.0:  # Couverture parfaite = 100%
                        # Score maximum garanti pour éviter la pénalisation
                        candidates_dict[word] = {
                            "mot_cle_1": word,
                            "transactions_couvertes": len(exact_matches),
                            "transactions_matched": exact_matches,
                            "coverage_score": 1.0,
                            "specificity_score": 2.0,  # Score artificiellement élevé
                            "composite_score": 2.0,  # Score composite maximum
                            "collision": False,  # Pas de collision forcée
                            "collision_count": 0,
                            "collision_ratio": 0.0,
                            "collision_penalty": 1.0,
                            "match_type": "exact_from_compte_perfect",
                            "source": "libellé compte (couverture parfaite)"
                        }
                        if self.debug:
                            logger.debug(
                                f"🎯 AFFECTIA : Mot du compte '{word}' avec couverture parfaite - score maximum garanti")
                    else:
                        add_candidate(word, len(exact_matches), exact_matches, "exact_from_compte",
                                      "libellé compte")

                # Test fuzzy optimisé avec RapidFuzz
                if fuzzy_available and len(exact_matches) < len(
                        transactions) * 0.8:  # Fuzzy seulement si exact insuffisant
                    choices = [(libelle, i) for i, libelle in enumerate(current_libelles_norm)]
                    word_norm_clean = normalize_for_comparison(word)

                    # Utiliser RapidFuzz.process pour optimiser
                    fuzzy_results = process.extract(
                        word_norm_clean,
                        [choice[0] for choice in choices],
                        scorer=fuzz.partial_ratio,
                        limit=len(choices),
                        score_cutoff=max(70, 100 - len(word) * 3)
                    )

                    fuzzy_matches = []
                    for result, score, idx in fuzzy_results:
                        original_idx = choices[idx][1]
                        fuzzy_matches.append(transactions[original_idx])

                    if len(fuzzy_matches) >= self.min_occurrences and len(fuzzy_matches) > len(exact_matches):
                        add_candidate(word, len(fuzzy_matches), fuzzy_matches, "fuzzy_from_compte",
                                      "libellé compte (fuzzy)")

        # ÉTAPE 2 : Patterns spéciaux (domaines, tirets)
        domain_patterns = Counter()
        company_names = Counter()

        for trans in transactions:
            original_text = trans['ecriture_lib'].upper()

            # Domaines web
            domains = re.findall(r'\b(\w{3,})\.(COM|FR|US|NET|ORG|CO|BE|DE|IT|ES)\b', original_text)
            for domain_name, extension in domains:
                domain_patterns[domain_name] += 1

            # Noms avec tirets
            words_with_hyphens = re.findall(r'\b\w{3,}(?:-\w{2,})+\b', original_text)
            for word in words_with_hyphens:
                if not word.replace('-', '').isdigit():
                    company_names[word] += 1

        # Ajouter patterns aux candidats
        for pattern, count in domain_patterns.items():
            if count >= self.min_occurrences:
                matching_transactions = [t for t in transactions if pattern in t['ecriture_lib'].upper()]
                add_candidate(pattern, count, matching_transactions, "domain_pattern", "domaine web")

        for pattern, count in company_names.items():
            if count >= self.min_occurrences:
                matching_transactions = [t for t in transactions if pattern in t['ecriture_lib'].upper()]
                add_candidate(pattern, count, matching_transactions, "hyphenated_name", "nom avec tirets")

                # ÉTAPE 3 : N-grams avec fuzzy
                all_libelles = [t['ecriture_lib'] for t in transactions]
                if all_libelles:
                    # Utiliser la nouvelle méthode extract_ngrams_all
                    ngrams_dict, df_counter = self.extract_ngrams_all(
                        all_libelles,
                        n_max=4,
                        min_df=len(transactions),  # N-grams présents dans TOUTES les transactions
                        max_set=50
                    )

                    # Les n-grams sont déjà filtrés par min_df=len(transactions)
                    common_ngrams = set(ngrams_dict.keys())

                    # Ajouter n-grams
                    for ngram in common_ngrams:
                        add_candidate(ngram, len(transactions), transactions, "ngram_exact", "n-gram commun")

            # Fuzzy n-grams avec compte
            if fuzzy_available and len(compte_libelle) >= 3 and common_ngrams:
                compte_norm = normalize_for_comparison(compte_libelle)
                ngrams_list = list(common_ngrams)

                # Utiliser RapidFuzz pour optimiser
                fuzzy_ngram_results = process.extract(
                    compte_norm,
                    ngrams_list,
                    scorer=fuzz.token_set_ratio,
                    limit=3,
                    score_cutoff=70
                )

                for ngram, score, _ in fuzzy_ngram_results:
                    add_candidate(ngram, len(transactions), transactions, "ngram_fuzzy", f"n-gram fuzzy ({score})")

        # SÉLECTION DU MEILLEUR CANDIDAT
        all_candidates = list(candidates_dict.values())

        if not all_candidates:
            if self.debug:
                logger.debug(f"⚠️ AFFECTIA : Aucun candidat pour {compte}")
            return self._analyze_general_account(compte, transactions)

        # Tri optimisé
        all_candidates.sort(key=lambda x: (
            -x["composite_score"],
            -x["coverage_score"],
            -len(x["mot_cle_1"])
        ))

        # Logging intelligent et concis
        if self.debug and all_candidates:
            best = all_candidates[0]
            collision_info = f"collision {best['collision_count']} ({best['collision_ratio']:.1%})" if best[
                'collision'] else "✓"
            logger.debug(
                f"✅ AFFECTIA : '{best['mot_cle_1']}' - Score: {best['composite_score']:.2f} - {collision_info}")

        # Retourner le meilleur candidat
        best_candidate = all_candidates[0]
        rules = [{
            "mot_cle_1": best_candidate["mot_cle_1"],
            "transactions_couvertes": best_candidate["transactions_couvertes"],
            "collision": best_candidate["collision"]
        }]

        return self._add_journal_and_amount_criteria(rules, transactions)

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
            # Extraire les codes UR avec ou sans espace : "UR123456" ou "UR 123456"
            for code in set(re.findall(r'UR\s*\d{6,}', libelle)):
                ur_patterns[code] += 1

        rules = []
        if ur_patterns:
            # Garder seulement le code UR le plus long avec couverture maximale
            codes_by_coverage = {}
            for code, count in ur_patterns.items():
                if count >= self.min_occurrences:
                    codes_by_coverage[count] = codes_by_coverage.get(count, []) + [code]

            if codes_by_coverage:
                # Prendre la couverture maximale
                max_coverage = max(codes_by_coverage.keys())
                best_codes = codes_by_coverage[max_coverage]

                # Parmi les codes à couverture maximale, prendre le plus long
                best_code = max(best_codes, key=len)

                rules.append({"mot_cle_1": best_code, "transactions_couvertes": max_coverage, "collision": False})
                if self.debug:
                    print(f"✅ AFFECTIA : Règle URSSAF trouvée - {best_code} ({max_coverage} transactions)")

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

        # Utiliser la nouvelle méthode extract_ngrams_all
        all_libelles = [t['ecriture_lib'] for t in transactions]
        ngrams_dict, df_counter = self.extract_ngrams_all(
            all_libelles,
            n_max=5,
            min_df=self.min_occurrences,
            max_set=50
        )

        def _get_signature_for_dedup(indices_data):
            """
            Retourne un hashable représentant l'ensemble exact de transactions ou,
            à défaut, un tuple (count, hash_sample) qui réduit les collisions.
            """
            if isinstance(indices_data, set):
                # Utiliser frozenset pour hashing fiable
                return frozenset(indices_data)
            elif isinstance(indices_data, tuple):
                sample_idx, total = indices_data
                # Hash léger, réduit les collisions 'même count'
                return (total, sample_idx % 97)
            else:
                # int simple
                return (indices_data, None)

        # Trier par fréquence puis longueur avec ordre stable
        frequent_ngrams = list(df_counter.most_common())
        frequent_ngrams.sort(key=lambda x: (x[1], len(x[0]), x[0]), reverse=True)

        selected_ngrams = []
        for ngram, count in frequent_ngrams[:10]:  # considérer jusqu'aux 10 motifs les plus fréquents
            # Obtenir signature pour déduplication
            indices_data = ngrams_dict.get(ngram)
            trans_signature = _get_signature_for_dedup(indices_data)

            # Vérifier si ce motif est redondant avec un motif déjà sélectionné
            redundant = False
            for sel_ng, _ in selected_ngrams:
                sel_indices_data = ngrams_dict.get(sel_ng)
                sel_signature = _get_signature_for_dedup(sel_indices_data)

                # Comparaison de signatures (set complet ou count)
                if trans_signature == sel_signature:
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

    def suggest_rules_for_account(self, compte: str, transactions: List[Dict], all_transactions: List[Dict]) -> List[
        Dict]:
        """Analyse un compte et suggère jusqu'à 3 règles d'affectation basées sur ses transactions"""
        if self.debug:
            print(f"\n🚀 AFFECTIA : Début de l'analyse du compte {compte} ({len(transactions)} transactions)")

        # Pour les comptes 401/411, accepter même avec moins de transactions (analyse du libellé)
        if len(transactions) < self.min_occurrences and not (compte.startswith('401') or compte.startswith('411')):
            if self.debug:
                print(f"⚠️ AFFECTIA : Pas assez de transactions pour le compte {compte}")
            return []

        # 1. Motifs spécifiques selon le type de compte
        candidate_rules = self.find_account_specific_patterns(compte, transactions, all_transactions)
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
