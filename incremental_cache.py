"""Optional local cache for deterministic review results, never LLM calls."""
import hashlib
import json
import sqlite3


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     allow_nan=False, separators=(',', ':')).encode()).hexdigest()


def review_cards(cards, glossary, corpus, groups, run_fuzzy, checker,
                 cache_path=None, rules_version=''):
    if not cache_path:
        return ([checker(c, glossary, corpus, groups, run_fuzzy) for c in cards],
                {'enabled': False, 'hits': 0, 'misses': len(cards)})
    # Global dependencies are hashed once, not once per card.
    environment = fingerprint([rules_version, glossary, corpus, run_fuzzy, groups])
    connection = sqlite3.connect(cache_path)
    try:
        connection.execute('CREATE TABLE IF NOT EXISTS results (key TEXT PRIMARY KEY, payload TEXT NOT NULL, digest TEXT NOT NULL)')
        results, hits = [], 0
        for card in cards:
            key = fingerprint([environment, card])
            row = connection.execute('SELECT payload,digest FROM results WHERE key=?', (key,)).fetchone()
            result = None
            if (row and isinstance(row[0], str) and isinstance(row[1], str)
                    and hashlib.sha256(row[0].encode()).hexdigest() == row[1]):
                try:
                    candidate = json.loads(row[0])
                    if isinstance(candidate, dict) and candidate.get('id') == card.get('id') and candidate.get('verdict') in ('pass', 'review', 'fix') and isinstance(candidate.get('flags'), list):
                        result = candidate
                except ValueError:
                    pass
            if result is None:
                result = checker(card, glossary, corpus, groups, run_fuzzy)
                payload = json.dumps(result, ensure_ascii=False, allow_nan=False)
                connection.execute('INSERT OR REPLACE INTO results VALUES (?,?,?)',
                                   (key, payload, hashlib.sha256(payload.encode()).hexdigest()))
            else:
                hits += 1
            results.append(result)
        connection.commit()
        return results, {'enabled': True, 'hits': hits, 'misses': len(cards)-hits}
    finally:
        connection.close()
