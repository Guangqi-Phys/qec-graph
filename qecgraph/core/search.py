"""Deterministic lexical discovery, independent of optional vector indexes."""
from collections import Counter, defaultdict
import math
import re

STOPWORDS = set('a an the is are was were be been being what which who how why does do did '
                'of for to in on at by from with and or under that this it its as can we our'.split())


def normalized(text: str) -> str:
    text = text.casefold().replace(r'\llbracket', '[[').replace(r'\rrbracket', ']]')
    text = text.replace(r'[\![', '[[').replace(r']\!]', ']]')
    text = re.sub(r'\\[,;!]|~', ' ', text)
    return ' '.join(text.split())


def terms(text: str) -> list[str]:
    text = normalized(text)
    result = []
    for token in re.findall(r'[^\W_]+', text):
        if token in STOPWORDS:
            continue
        if token in {'decoder', 'decoders', 'decoding', 'decoded'}:
            token = 'decode'
        elif len(token) > 4 and token.endswith('s') and not token.endswith(('ss', 'us', 'is')):
            token = token[:-1]
        result.append(token)
    return result


class LexicalIndex:
    """Cache postings and BM25 statistics once for a pinned set of search units."""

    def __init__(self, texts: dict[str, str]):
        self.counts = {key: Counter(terms(text)) for key, text in texts.items()}
        self.postings: dict[str, set[str]] = defaultdict(set)
        for key, counts in self.counts.items():
            for term in counts:
                self.postings[term].add(key)
        self.lengths = {key: sum(counts.values()) for key, counts in self.counts.items()}
        self.average = sum(self.lengths.values()) / max(len(texts), 1)

    def rank(self, query: str, allowed: set[str]) -> tuple[list[str], dict[str, str]]:
        query_terms = set(terms(query))
        candidates = set().union(*(self.postings.get(t, set()) for t in query_terms)) & allowed
        scores = {}
        matches = {}
        count = len(self.counts)
        for key in candidates:
            counts = self.counts[key]
            matches[key] = 'all_terms' if query_terms <= counts.keys() else 'some_terms'
            score = 0.0
            for term in query_terms & counts.keys():
                df, frequency = len(self.postings[term]), counts[term]
                score += math.log(1 + (count - df + .5) / (df + .5)) * frequency * 2.2 / (
                    frequency + 1.2 * (.25 + .75 * self.lengths[key] / max(self.average, 1)))
            scores[key] = score
        return sorted(candidates, key=lambda k: (matches[k] != 'all_terms', -scores[k], k)), matches
