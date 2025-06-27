from collections import defaultdict, deque
import re
# Utilisation de rapidfuzz pour les comparaisons floues
from rapidfuzz import fuzz


class TransactionGrouper:
    """Groupe intelligemment les transactions pour faciliter la détection de patterns (version améliorée)"""

    def __init__(self):
        # Liste étendue de mots vides (communs ou peu informatifs) en français + termes financiers génériques
        self.stop_words = {
            'de', 'du', 'des', 'le', 'la', 'les', 'un', 'une', 'et', 'ou',
            'pour', 'par', 'sur', 'avec', 'sans',
            'au', 'aux', 'carte', 'cb', 'vir', 'virement', 'paiement', 'retrait'
        }

    def normalize_libelle(self, libelle):
        """Nettoie un libellé de transaction pour la comparaison"""
        text = libelle.upper()
        # Remplacer les nombres par un token générique "0"
        text = re.sub(r'\d+', '0', text)
        # Remplacer la ponctuation par des espaces
        text = re.sub(r'[^\w\s]', ' ', text)
        # Réduire les espaces multiples
        text = re.sub(r'\s+', ' ', text).strip()
        return text

    def extract_keywords(self, libelle):
        """Extrait les mots-clés significatifs d'un libellé (après normalisation)"""
        text = self.normalize_libelle(libelle)
        words = text.split()
        # Garder les mots avec au moins 3 lettres et non présents dans les stop_words
        keywords = [w for w in words if len(w) >= 3 and w.lower() not in self.stop_words]
        return keywords

    def similarity_score(self, text1, text2):
        """Calcule un score de similarité entre deux libellés (basé sur tokens)"""
        # Normalisation des deux textes
        t1 = self.normalize_libelle(text1)
        t2 = self.normalize_libelle(text2)
        # Score de similarité basé sur l'ensemble des tokens (on utilise token_set_ratio de rapidfuzz)
        return fuzz.token_set_ratio(t1, t2) / 100.0  # renvoie un score entre 0 et 1

    def group_by_similarity(self, transactions, threshold=0.7):
        """Groupe les transactions par similarité de libellé en utilisant un clustering transitif"""
        n = len(transactions)
        visited = [False] * n
        groups = []

        for i in range(n):
            if visited[i]:
                continue
            # Créer un nouveau groupe avec la transaction i
            visited[i] = True
            group = [transactions[i]]
            lib_i = transactions[i]['ecriture_lib']
            # File pour parcourir les voisins similaires (BFS)
            queue = deque([i])

            while queue:
                idx = queue.popleft()
                lib_ref = transactions[idx]['ecriture_lib']
                # Comparer avec toutes les transactions non encore visitées
                for j in range(n):
                    if not visited[j]:
                        lib_j = transactions[j]['ecriture_lib']
                        if self.similarity_score(lib_ref, lib_j) >= threshold:
                            visited[j] = True
                            group.append(transactions[j])
                            queue.append(j)
            groups.append(group)

        # Trier les groupes par taille décroissante
        groups.sort(key=len, reverse=True)
        return groups

    def find_common_patterns(self, libelles):
        """Trouve les patterns communs (mots ou phrases) dans une liste de libellés"""
        # Extraire les ensembles de mots clés pour chaque libellé
        list_keywords = [set(self.extract_keywords(lib)) for lib in libelles]
        if not list_keywords:
            return []
        # Trouver les mots communs à tous les libellés du groupe
        common_words = set.intersection(*list_keywords)

        patterns = []
        # S'il y a des mots communs à tous, les considérer comme patterns potentiels
        for word in common_words:
            patterns.append(word)
        # Sinon, prendre les mots apparaissant dans au moins la moitié des libellés
        if not patterns:
            # Compter la fréquence de chaque mot tous libellés confondus
            freq = defaultdict(int)
            for keywords in list_keywords:
                for w in keywords:
                    freq[w] += 1
            # Trier par fréquence
            sorted_keywords = sorted(freq.items(), key=lambda x: x[1], reverse=True)
            # Prendre les mots qui apparaissent dans au moins la moitié des descriptions du groupe
            for w, count in sorted_keywords:
                if count >= len(libelles) / 2:
                    patterns.append(w)
                    if len(patterns) >= 3:
                        break  # on limite à 3 patterns clés
        return patterns

    def smart_sort_transactions(self, transactions):
        """Tri intelligent des transactions en groupes similaires PAR COMPTE, avec patterns descriptifs"""
        # 1. D'abord segmenter par compte
        transactions_by_compte = defaultdict(list)
        for t in transactions:
            compte = t.get('compte_contrepartie', 'INCONNU')
            transactions_by_compte[compte].append(t)

        # 2. Pour chaque compte, appliquer le groupement intelligent
        organized_data_by_compte = {}

        for compte, compte_transactions in transactions_by_compte.items():
            # Grouper par similarité (clustering transitif) pour ce compte
            similarity_groups = self.group_by_similarity(compte_transactions)

            organized_data = []
            for group in similarity_groups:
                if len(group) >= 3:
                    # Extraire les libellés normalisés du groupe
                    libelles = [t['ecriture_lib'] for t in group]
                    # Trouver les patterns communs significatifs du groupe
                    patterns = self.find_common_patterns(libelles)
                    # Déterminer un intitulé de groupe (pattern principal lisible)
                    if patterns:
                        # Si plusieurs patterns, on les combine pour le titre (par ex. les deux premiers)
                        main_pattern = " & ".join(patterns[:2]) if len(patterns) >= 2 else patterns[0]
                    else:
                        main_pattern = "GROUPE"
                    organized_data.append({
                        'type': 'group',
                        'pattern': main_pattern,
                        'count': len(group),
                        'transactions': sorted(group, key=lambda x: x['montant'], reverse=True),
                        'suggested_keywords': patterns[:3]  # suggérer jusqu'à 3 mots/phrases clés
                    })
                else:
                    # Transactions isolées ou paires non significatives
                    for transaction in group:
                        organized_data.append({
                            'type': 'single',
                            'transaction': transaction
                        })

            organized_data_by_compte[compte] = organized_data

        return organized_data_by_compte


# Exemple d'utilisation (adapté pour la segmentation par compte)
def format_for_display(organized_data_by_compte):
    """Formate les données pour l'affichage dans l'interface, organisées par compte"""
    display_by_compte = {}

    for compte, organized_data in organized_data_by_compte.items():
        display_sections = []

        for item in organized_data:
            if item['type'] == 'group':
                display_sections.append({
                    'section_type': 'group',
                    'title': f"📊 {item['pattern']} ({item['count']} transactions)",
                    'suggested_keywords': item['suggested_keywords'],
                    'transactions': item['transactions'],
                    'highlight_pattern': item['pattern']
                })
            else:
                # Regrouper toutes les transactions orphelines dans une section "diverses"
                if not display_sections or display_sections[-1]['section_type'] != 'singles':
                    display_sections.append({
                        'section_type': 'singles',
                        'title': "📋 Transactions diverses",
                        'transactions': []
                    })
                display_sections[-1]['transactions'].append(item['transaction'])

        display_by_compte[compte] = display_sections

    return display_by_compte