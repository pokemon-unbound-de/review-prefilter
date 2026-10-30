#!/usr/bin/env python3
"""
Review Pre-Filter
=================
Two-layer pre-filter for localization review queues (Pokémon Unbound DE
format, generic enough for other CFRU-style queues).

Layer 1 — DETERMINISTIC (offline, free, reproducible):
  * textbox_fit      — pixel widths vs. per-line limit / max lines
  * locked_terms     — card-locked canonical terms present in the DE text
  * glossary_leak    — English names from the glossary in the DE text
  * glossary_missing — DE canonical name missing where EN name occurs
  * placeholders     — functional placeholders match between EN and DE
                        (layout codes like \\n/\\p are NOT compared — line
                        break adaptation is legit, textbox_fit covers that)
  * consistency      — identical EN source with different DE translations
  * corpus_match     — exact / fuzzy match against the curated corpus
  * sanity           — empty, untranslated, or extreme-length texts

Layer 2 — LLM language review (optional, provider-agnostic):
  * OpenAI-compatible endpoint via env (LLM_BASE_URL, LLM_API_KEY,
    LLM_MODEL). Risk-based: by default only 'fix'/'review' cards are sent.
  * Sends card content to the configured endpoint — keep data local by
    not using this flag.

Outputs:
  * prefilter_results.json — per-card verdict + flags (machine-readable;
    input for Layer 2 and web-app integration)
  * prefilter_report.md    — human summary with workload estimate

Usage:
  python3 review_prefilter.py --cards cards.json --corpus corpus.json \
      --glossary NAMENSVERZEICHNIS.md --out-dir ./report
  python3 review_prefilter.py ... --llm --llm all   # also LLM-review passes

Safety: read-only. No file is modified. Queue/card content is never
uploaded anywhere (Layer 1). Layer 2 is explicit opt-in.
"""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
from incremental_cache import review_cards
import difflib
import json
import os
import re
import statistics
import sqlite3
import sys
import urllib.error
import urllib.request
from collections import Counter, defaultdict

# --------------------------------------------------------------------------
# Normalization & placeholders
# --------------------------------------------------------------------------

CTRL_RE = re.compile(r"\\[a-zA-Z<.!#]")
PCT_RE = re.compile(r"%[sdnc]")


def norm_text(s: str) -> str:
    """Normalize for comparison: real whitespace -> space, strip control
    codes and trailing backslashes, lowercase."""
    if not s:
        return ""
    s = s.replace("\r\n", " ").replace("\n", " ").replace("\r", " ")
    s = re.sub(r"\\[a-zA-Z<.!#]", " ", s)
    s = re.sub(r"\\+", " ", s)
    s = re.sub(r"\s+", " ", s)
    return s.strip().lower()


BRACKET_RE = re.compile(r"\{[^}]+\}")


def extract_placeholders(s: str) -> Counter:
    """FUNCTIONAL placeholders only (%s/%d/... and {buffer}-style).
    Layout codes (\\n, \\p, \\l, trailing \\.) are deliberately NOT
    compared: translators legitimately adapt line breaks for German
    textbox fit — that is what de_line_widths_px validates separately."""
    if not s:
        return Counter()
    s = s.replace("\r\n", " ").replace("\n", " ").replace("\r", " ")
    c = Counter(PCT_RE.findall(s))
    c.update(BRACKET_RE.findall(s))
    return c


def has_backslash_escape(s: str) -> bool:
    """Detect raw pointer/escape garbage like \\!98F in the data."""
    return "\\!" in s or "\\x" in s.lower() and True or "\x00" in s


# --------------------------------------------------------------------------
# Glossary
# --------------------------------------------------------------------------

def parse_glossary(path: str) -> list[dict]:
    """Parse markdown tables with | DE | EN | Art | columns."""
    entries: list[dict] = []
    if not os.path.exists(path):
        return entries
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line.startswith("|"):
                continue
            cells = [c.strip() for c in line.strip("|").split("|")]
            if len(cells) < 2:
                continue
            de, en = cells[0], cells[1]
            if de in ("DE", "---", "") or en in ("EN", "---", ""):
                continue
            if set(de) <= {"-"} or set(en) <= {"-"}:
                continue
            tentative = "*" in de or "*" in en
            de = de.replace("*", "").strip()
            en = en.replace("*", "").strip()
            if de and en:
                entries.append({"de": de, "en": en, "tentative": tentative})
    return entries


def name_in_text(name: str, text: str) -> bool:
    """Case-insensitive word-boundary match (multi-word names supported).
    Allows German possessive/inflection suffixes (Lärchs, Loges) while
    the trailing boundary still rejects longer words (Lärchstein)."""
    if not name or not text:
        return False
    esc = re.escape(name)
    return re.search(rf"(?<!\w){esc}(?:s|es)?(?!\w)", text,
                     re.IGNORECASE) is not None


# --------------------------------------------------------------------------
# Corpus
# --------------------------------------------------------------------------

def load_corpus(path: str) -> dict:
    """Normalized EN -> unique suggestion or explicit ambiguity metadata.

    Only clean entries with DE are considered. Different raw DE strings
    under the same normalized EN key never produce a selected winner.
    """
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    if isinstance(data, list):
        entries = data
    elif isinstance(data, dict) and isinstance(data.get("entries"), list):
        entries = data["entries"]
    else:
        raise ValueError("corpus must be a list or an object with an entries list")
    index: dict[str, dict] = {}
    variants: dict[str, set[str]] = defaultdict(set)
    for e in entries:
        if not isinstance(e, dict):
            raise ValueError("corpus entries must be objects")
        if any(e.get(field) is not None and not isinstance(e[field], str)
               for field in ("en_raw", "de_raw")):
            raise ValueError("corpus text fields must be strings or null")
        en_raw = e.get("en_raw") or ""
        de_raw = e.get("de_raw") or ""
        if not en_raw or not de_raw:
            continue
        if has_backslash_escape(en_raw) or has_backslash_escape(de_raw):
            continue
        key = norm_text(en_raw)
        if key:
            variants[key].add(de_raw)
        if key and key not in index:
            index[key] = {"de_raw": de_raw, "id": e.get("id"),
                          "pointer": e.get("pointer"),
                          "status": e.get("status")}
    for key, values in variants.items():
        if len(values) > 1:
            # Keep the key in the index so exact/fuzzy hits remain visible.
            # Pin variant content for cache invalidation, without exposing
            # private source text or choosing an order-dependent reference.
            index[key] = {
                "ambiguous": True,
                "variant_count": len(values),
                "variants_sha256": hashlib.sha256(json.dumps(
                    sorted(values), ensure_ascii=False).encode()).hexdigest(),
            }
    return index


def corpus_lookup(key: str, index: dict, min_ratio: float = 0.90):
    """Exact match, else best fuzzy match with length pre-filter."""
    if key in index:
        return {"match": "exact", "ratio": 1.0,
                **index[key]}
    if not key:
        return None
    best, best_ratio = None, 0.0
    lo, hi = int(len(key) * 0.6), int(len(key) * 1.6) + 1
    for k, v in index.items():
        if lo < len(k) < hi:
            r = difflib.SequenceMatcher(None, key, k, autojunk=False).ratio()
            if r > best_ratio:
                best, best_ratio = v, r
                if r > 0.98:
                    break
    if best and best_ratio >= min_ratio:
        return {"match": "fuzzy", "ratio": round(best_ratio, 3),
                "fuzzy_key": best, **best}
    return None


# --------------------------------------------------------------------------
# Card checks (Layer 1)
# --------------------------------------------------------------------------

def check_card(card: dict, glossary: list[dict], corpus: dict,
               consistency_groups: dict, run_fuzzy: bool) -> dict:
    en = card.get("en") or ""
    de = card.get("de") or ""
    flags: list[dict] = []

    def add(check: str, severity: str, detail: str):
        flags.append({"check": check, "severity": severity,
                      "detail": detail})

    # -- sanity
    if not en.strip():
        add("sanity", "error", "EN-Text leer")
    if not de.strip():
        add("sanity", "error", "DE-Text leer")
    elif norm_text(en) == norm_text(de):
        add("sanity", "error", "DE-Text identisch mit EN (nicht übersetzt?)")
    if en and de:
        ratio = len(de) / max(1, len(en))
        if ratio > 3.0 or ratio < 0.3:
            add("sanity", "warning",
                f"Längenverhältnis DE/EN = {ratio:.2f} (ungewöhnlich)")

    # -- textbox fit (pixel data is pre-computed with real font metrics)
    widths = card.get("de_line_widths_px") or []
    limit = card.get("limit_px_per_line")
    max_lines = card.get("max_lines_preview")
    if limit and isinstance(widths, list):
        for i, w in enumerate(widths, 1):
            if isinstance(w, (int, float)) and w > limit:
                add("textbox_fit", "error",
                    f"Zeile {i} überläuft: {int(w)}px > Limit {limit}px")
    if max_lines and isinstance(widths, list) and len(widths) > max_lines:
        add("textbox_fit", "error",
            f"{len(widths)} Zeilen > Maximal-{max_lines}-Zeilen-Preview")

    # -- locked terms
    for term in card.get("locked_terms") or []:
        if term and not name_in_text(term, de):
            add("locked_terms", "error",
                f"Gesperrter Begriff '{term}' fehlt im DE-Text")

    # -- glossary: EN leak into DE + missing DE canonical name
    for g in glossary:
        if name_in_text(g["en"], en):
            if g["de"].lower() != g["en"].lower():
                if name_in_text(g["en"], de):
                    add("glossary_leak", "error",
                        f"Englischer Name '{g['en']}' im DE-Text "
                        f"(Glossar: '{g['de']}'")
                    continue
                if not name_in_text(g["de"], de):
                    add("glossary_missing",
                        "info" if g.get("tentative") else "warning",
                        f"Glossar: '{g['en']}' → erwartet '{g['de']}'"
                        + (" (vorläufig)" if g.get("tentative") else ""))

    # -- placeholders / control codes
    pen, pd = extract_placeholders(en), extract_placeholders(de)
    if pen != pd:
        missing = (pd - pen) or (pen - pd)
        add("placeholders", "error",
            f"Platzhalter/Steuerzeichen weichen ab: EN {dict(pen) or '{}'} "
            f"vs. DE {dict(pd) or '{}'} (Unterschied: {dict(missing) or '{}'})")

    # -- consistency (identical EN, different DE)
    gkey = norm_text(en)
    grp = consistency_groups.get(gkey)
    if grp and len(grp) > 1:
        add("consistency", "warning",
            f"Gleiche EN-Quelle mit {len(grp)} verschiedenen DE-"
            f"Übersetzungen (Gruppe {grp[0]}…)")

    # -- corpus match (exact + optional fuzzy)
    cmatch = None
    if gkey:
        if run_fuzzy:
            cmatch = corpus_lookup(gkey, corpus, min_ratio=0.90)
        elif gkey in corpus:
            cmatch = {"match": "exact", "ratio": 1.0, **corpus[gkey]}
        if cmatch and cmatch.get("ambiguous"):
            add("corpus_ambiguity", "warning",
                f"Korpus-Treffer mit {cmatch['variant_count']} verschiedenen "
                "DE-Fassungen; keine Fassung vorgeschlagen. Kontext und "
                "Quellen menschlich prüfen.")
            cmatch = None
        if cmatch:
            cur = norm_text(de)
            sug = norm_text(cmatch["de_raw"])
            if cur and cur != sug:
                kind = "exakter" if cmatch["match"] == "exact" \
                    else f"Naht- (Ratio {cmatch['ratio']})"
                add("corpus_match", "info",
                    f"{kind} Korpus-Treffer {cmatch['id']}: "
                    f"'{cmatch['de_raw'][:80]}' vs. Karte "
                    f"'{de[:80]}' → Diff prüfen/übernehmen")

    # -- verdict
    sevs = {f["severity"] for f in flags}
    verdict = "fix" if "error" in sevs else (
        "review" if "warning" in sevs else "pass")
    return {"id": card.get("id"), "pointer": card.get("pointer"),
            "unit": card.get("unit"), "en": en[:200], "de": de[:200],
            "source_sha256": card.get("source_sha256"),
            "verdict": verdict, "flags": flags,
            "corpus_match": {k: cmatch[k] for k in
                             ("match", "ratio", "id", "de_raw")}
            if cmatch else None}


# --------------------------------------------------------------------------
# Layer 2: LLM language review (optional)
# --------------------------------------------------------------------------

LLM_PROMPT = """Du bist ein muttersprachliches Lektorat für eine deutsche
Pokémon-Fanübersetzung (FireRed-Romhack). Prüfe die KUNDE aus Sicht von
Sprachgefühl, Kontext und Tonfall.

Regeln:
- Natürliche, idiomatische Deutsch (keine Übersetzer-Deutsche).
- Tonfall passend zum Sprecher und zur Szene.
- Offizielle Pokémon-Terminologie (PokéWiki) beibehalten.
- Platzhalter und Steuerzeichen EXAKT erhalten.
- Keine Lore erfinden; keine neuen Namen.

Karte:
EN-Quelle: {en}
DE-Übersetzung: {de}
Sprecher: {speaker} (Genre: {gender})
Szene-Hinweis: {scene}
Kontext vorher: {before}
Kontext nachher: {after}
Gesperrte Begriffe: {locked}

Antworte NUR mit JSON:
{{"score": 1-10, "issues": ["..."], "suggestion_de": "verbessert oder leer"}}"""


def llm_review(result: dict, card: dict, base_url: str, api_key: str,
               model: str) -> dict | None:
    if not api_key:
        return None
    prompt = LLM_PROMPT.format(
        en=card.get("en", ""), de=card.get("de", ""),
        speaker=card.get("speaker") or "—",
        gender=card.get("speaker_gender") or "—",
        scene=card.get("scene_hint") or "—",
        before=(card.get("context_before") or "—")[:300],
        after=(card.get("context_after") or "—")[:300],
        locked=", ".join(card.get("locked_terms") or []) or "—")
    body = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.2,
    }).encode()
    req = urllib.request.Request(
        base_url.rstrip("/") + "/chat/completions",
        data=body,
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {api_key}"})
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read().decode())
        text = data["choices"][0]["message"]["content"].strip()
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if m:
            return json.loads(m.group(0))
        return {"raw": text[:500]}
    except (urllib.error.URLError, json.JSONDecodeError, KeyError,
            IndexError) as exc:
        return {"error": str(exc)[:200]}


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------

def main() -> int:
    p = argparse.ArgumentParser(description="Review Pre-Filter")
    p.add_argument("--cards", required=True,
                   help="queue JSON (cards_stage_extended.json)")
    p.add_argument("--corpus", default=None,
                   help="corpus inventory JSON")
    p.add_argument("--glossary", default=None,
                   help="Namensverzeichnis markdown")
    p.add_argument("--out-dir", default="report")
    p.add_argument("--no-fuzzy", action="store_true",
                   help="skip fuzzy corpus matching (faster)")
    p.add_argument("--llm", action="store_true",
                   help="run Layer 2 LLM review on flagged cards")
    p.add_argument("--llm-scope", choices=["flagged", "all"],
                   default="flagged")
    p.add_argument("--cache", default=None, help="optional private SQLite cache for Layer 1")
    args = p.parse_args()

    os.makedirs(args.out_dir, exist_ok=True)

    with open(args.cards, encoding="utf-8") as fh:
        cdata = json.load(fh)
    cards = cdata if isinstance(cdata, list) else cdata.get("cards", [])
    print(f"→ {len(cards)} Karten geladen", file=sys.stderr)

    glossary = parse_glossary(args.glossary) if args.glossary else []
    print(f"→ {len(glossary)} Glossar-Einträge", file=sys.stderr)

    try:
        corpus = load_corpus(args.corpus) if args.corpus else {}
    except (ValueError, OSError):
        print("Korpus konnte nicht geladen werden: Datei, JSON-Struktur und "
              "Textfelder prüfen; kein Ergebnis erzeugt.", file=sys.stderr)
        return 1
    print(f"→ {len(corpus)} saubere Korpus-Paare", file=sys.stderr)

    # consistency groups: normalized en -> distinct normalized de
    groups: dict[str, set] = defaultdict(set)
    for c in cards:
        groups[norm_text(c.get("en") or "")].add(
            norm_text(c.get("de") or ""))
    consistency_groups = {
        k: sorted(v) for k, v in groups.items() if len(v) > 1}

    print("→ Layer 1: deterministische Checks …", file=sys.stderr)
    rules_version = hashlib.sha256(
        Path(__file__).read_bytes() + Path(__file__).with_name("incremental_cache.py").read_bytes()).hexdigest()
    try:
        results, cache_stats = review_cards(
            cards, glossary, corpus, consistency_groups, not args.no_fuzzy,
            check_card, cache_path=args.cache, rules_version=rules_version)
    except (ValueError, sqlite3.Error, OSError) as error:
        print(f"Layer-1-Prüfung abgebrochen ({type(error).__name__}): "
              "Eingabedaten und Cache-Zugriff prüfen; kein Ergebnis erzeugt.",
              file=sys.stderr)
        return 1
    if args.cache:
        print(f"→ Layer-1-Cache: {cache_stats['hits']} Treffer, "
              f"{cache_stats['misses']} neu geprüft", file=sys.stderr)

    # -- Layer 2
    if args.llm:
        base = os.environ.get("LLM_BASE_URL", "")
        key = os.environ.get("LLM_API_KEY", "")
        model = os.environ.get("LLM_MODEL", "gpt-4o-mini")
        if not (base and key):
            print("⚠ LLM: LLM_BASE_URL/LLM_API_KEY nicht gesetzt — "
                  "Layer 2 übersprungen", file=sys.stderr)
        else:
            scope = [r for r in results
                     if args.llm_scope == "all" or
                     r["verdict"] != "pass"]
            print(f"→ Layer 2: LLM-Review für {len(scope)} Karten …",
                  file=sys.stderr)
            for i, r in enumerate(scope, 1):
                card = next((c for c in cards if c.get("id") == r["id"]),
                           {})
                r["llm"] = llm_review(r, card, base, key, model)
                if i % 50 == 0:
                    print(f"  … {i}/{len(scope)}", file=sys.stderr)

    verdicts = Counter(r["verdict"] for r in results)
    check_counts: Counter = Counter()
    for r in results:
        for f in r["flags"]:
            check_counts[f["check"]] += 1

    # -- workload estimate
    per_card_pass_s = 10      # spot-check
    per_card_work_s = 180     # review a flagged card
    spot_rate = 0.10
    before_h = len(cards) * 30 / 3600
    flagged = sum(1 for r in results if r["verdict"] != "pass")
    after_h = (flagged * per_card_work_s +
               verdicts.get("pass", 0) * spot_rate * per_card_pass_s) / 3600

    out = {
        "generated_at": __import__("datetime").datetime.now().isoformat(),
        "summary": {
            "cards": len(cards),
            "layer1_cache": cache_stats,
            "verdicts": dict(verdicts),
            "flags_by_check": dict(check_counts),
            "workload_hours_before": round(before_h, 1),
            "workload_hours_after": round(after_h, 1),
            "spot_check_rate": spot_rate,
        },
        "results": results,
    }

    jpath = os.path.join(args.out_dir, "prefilter_results.json")
    with open(jpath, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1)

    # -- markdown report
    L: list[str] = []
    add = L.append
    add("# 🔍 Review Pre-Filter — Report")
    add("")
    add(f"> Karten: **{len(cards)}** · "
        f"Korpus-Paare: {len(corpus)} · Glossar-Einträge: {len(glossary)}")
    add("")
    add("## 📊 Ergebnis")
    add("")
    add("| Verdict | Anzahl | Bedeutung |")
    add("|---------|--------|-----------|")
    add(f"| ✅ pass | {verdicts.get('pass', 0)} | "
        f"keine Flags — Spot-Check reicht "
        f"({spot_rate:.0%}-Rate) |")
    add(f"| ⚠️ review | {verdicts.get('review', 0)} | Warnungen — "
        f"menschlich prüfen |")
    add(f"| ❌ fix | {verdicts.get('fix', 0)} | Fehler — "
        f"muss korrigiert werden |")
    add("")
    if check_counts:
        add("**Flags nach Check:** "
            + " · ".join(f"`{k}` ({v})"
                         for k, v in check_counts.most_common()))
        add("")

    add(f"## ⏱️ Arbeitslast")
    add("")
    add(f"- Vorher (manuell, alle Karten): **≈ {before_h:.1f} h** "
        f"({len(cards)} × 30 s)")
    add(f"- Nachher (Pre-Filter): **≈ {after_h:.1f} h** "
        f"({flagged} flags × 3 min + "
        f"{spot_rate:.0%}-Spot-Check der pass-Karten)")
    add("")

    add("## 🚨 Top-10 Karten mit Fehlern")
    add("")
    errors = [r for r in results if r["verdict"] == "fix"]
    if not errors:
        add("_Keine Fehler-Karten._")
    for n, r in enumerate(errors[:10], 1):
        add(f"{n}. **{r['id']}** — {r['de'][:70]}")
        for f in r["flags"]:
            if f["severity"] == "error":
                add(f"   - ❌ {f['check']}: {f['detail']}")
    add("")

    warns = [r for r in results if r["verdict"] == "review"]
    add("## ⚠️ Top-10 Karten mit Warnungen")
    add("")
    if not warns:
        add("_Keine Warnungs-Karten._")
    for n, r in enumerate(warns[:10], 1):
        add(f"{n}. **{r['id']}** — {r['de'][:70]}")
        for f in r["flags"]:
            if f["severity"] in ("warning", "info"):
                add(f"   - {f['check']}: {f['detail']}")
    add("")
    add("---")
    add("*Review Pre-Filter — Layer 1 deterministisch (offline), "
        "Layer 2 LLM optional (explizit `--llm`). AI orchestriert, "
        "Menschen entscheiden. Keine Karteninhalte wurden übertragen.*")
    mpath = os.path.join(args.out_dir, "prefilter_report.md")
    with open(mpath, "w", encoding="utf-8") as fh:
        fh.write("\n".join(L))

    print(f"\n→ {jpath}", file=sys.stderr)
    print(f"→ {mpath}", file=sys.stderr)
    print(f"\n=== ZUSAMMENFASSUNG ===", file=sys.stderr)
    print(f"Karten: {len(cards)} | "
          f"pass: {verdicts.get('pass', 0)} | "
          f"review: {verdicts.get('review', 0)} | "
          f"fix: {verdicts.get('fix', 0)}", file=sys.stderr)
    print(f"Arbeitslast: {before_h:.1f} h → {after_h:.1f} h",
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
