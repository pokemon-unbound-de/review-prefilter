# 🔍 Review Pre-Filter

**Zwei-Schicht-Pre-Filter für Übersetzungs-Review-Queues.**

Bevor ein Mensch eine Karte prüft, prüft der Pre-Filter sie automatisch:

```
Layer 1  DETERMINISTISCH  → offline, kostenlos, 100% reproduzierbar
Layer 2  LLM-SPRACHPRÜFUNG → Sprachgefühl, Kontext, Tonfall (optional,
                               provider-unabhängig, explizit --llm)
Layer 3  MENSCH           → bestätigt/verbessert in der Dialogwerkstatt
```

> **Designprinzip: AI orchestriert, Menschen entscheiden.**
> Der Pre-Filter markiert und schlägt vor — Menschen prüfen nur das,
> was wirklich Aufmerksamkeit braucht.

## Checks (Layer 1)

| Check | Was | Schwere |
|---|---|---|
| `textbox_fit` | Zeilenbreite (px, echte Font-Metriken) vs. Limit / Max-Zeilen | ❌ error |
| `locked_terms` | Gesperrte Kanon-Begriffe der Karte fehlen im DE-Text | ❌ error |
| `locked_exact_tokens` | Explizit gesperrter Token fehlt oder wurde in Schreibweise/Endung verändert | ❌ error |
| `glossary_leak` | Englischer Glossar-Name direkt im deutschen Text | ❌ error |
| `glossary_missing` | EN-Name in Quelle, aber DE-Kanonname fehlt in Ziel | ⚠️ warning |
| `placeholders` | **Funktionale** Platzhalter (`%s`, `%d`, `{buffer}`) weichen EN↔DE ab. Layout-Codes (`\n`, `\p`, …) werden bewusst *nicht* verglichen — Umbruch-Adaption ist legitim und wird stattdessen von `textbox_fit` geprüft | ❌ error |
| `consistency` | Gleiche EN-Quelle, verschiedene DE-Übersetzungen | ⚠️ warning |
| `corpus_match` | Exakter/Naht-Treffer im Korpus → bestehende Übersetzung prüfen | ℹ️ info |
| `sanity` | Leere, nicht übersetzte, extreme Längenverhältnisse | ❌/⚠️ |

### Verdicts

- ✅ **pass** — keine Flags, Spot-Check reicht
- ⚠️ **review** — Warnungen, menschlich prüfen
- ❌ **fix** — Fehler, muss korrigiert werden

## Nutzung

Reines Python 3.10+ (nur Standardbibliothek), läuft komplett offline:

```sh
python3 review_prefilter.py \
    --cards review/cards_stage_extended.json \
    --corpus review/corpus_inventory.json \
    --glossary docs/NAMENSVERZEICHNIS.md \
    --out-dir ./report
```

### Optionen

| Option | Bedeutung |
|---|---|
| `--cards` | Queue-JSON (Pflicht) |
| `--corpus` | Korpus-Inventory-JSON (Fuzzy-Matching-Basis) |
| `--glossary` | Namensverzeichnis-Markdown |
| `--out-dir` | Ausgabeverzeichnis (Default `report/`) |
| `--no-fuzzy` | Fuzzy-Matching abschalten (schneller) |
| `--llm` | Layer 2: LLM-Review der geflagten Karten |
| `--llm-scope` | `flagged` (Default) oder `all` |

### Layer 2 (LLM)

OpenAI-kompatible Endpunkte via Umgebungsvariablen:

```sh
export LLM_BASE_URL=https://api.example.com/v1   # z. B. beliebiger Provider
export LLM_API_KEY=...
export LLM_MODEL=...
python3 review_prefilter.py ... --llm
```

Standardmäßig werden **nur geflagte Karten** an den LLM gesendet
(riskobasiert). Achtung: `--llm` überträgt Karteninhalte an den
konfigurierten Endpunkt. Ohne `--llm` bleibt alles lokal.

## Ausgabe

- `prefilter_results.json` — pro Karte: Verdict, Flags, Korpus-Treffer
  (maschinenlesbar; Input für Layer 2 und Web-App-Integration)
- `prefilter_report.md` — Zusammenfassung, Top-Karten, **Arbeitslast
  vorher/nachher** (Schätzung)

## Sicherheit & Datenhaltung

- **Lese-only** — wird nichts im Projekt geändert.
- **Layer 1 ist offline** — keine Karteninhalte verlassen den Rechner.
- **Layer 2 ist explizit opt-in** (`--llm`).
- **Niemals committen:** Queue-/Karteninhalte, Reports mit Texten, Tokens.
  Dieses Repo enthält nur Code und Doku.

## Batch-Fähigkeit (v0.2+)

- Cache-Plan: `source_sha256` als Cache-Key → neue Karten (z. B. der
  Rest des Korpus) laufen inkrementell durch, bereits geprüfte nicht erneut
- Web-App-Integration: `prefilter_results.json` als Input für die
  Dialogwerkstatt (Karten nach Risiko sortieren, AI-Vorschläge anzeigen)

## Versionen

- **v0.1** — alle Layer-1-Checks, Layer-2-Interface, Arbeitslast-Schätzung

## Lizenz

### Namens- und Tokenschutz

`locked_terms` erkennt Namen auch nach den textuellen Layoutcodes `\n`, `\p`
und `\l`. Mehrteilige Namen duerfen an Wortgrenzen umbrechen; Teilwoerter
werden nicht zusammengesetzt. Originaltexte und andere Steuerzeichen bleiben
unveraendert. Die bisherigen deutschen Beugungsendungen und der Vergleich ohne
Gross-/Kleinschreibung gelten weiter fuer Namen.

Fuer belegte unveraenderbare Tokens kann eine Karte zusaetzlich
`"locked_exact_tokens": ["III"]` enthalten. Diese Tokens werden gross-/
kleinschreibungsgenau und ohne Beugungsendungen als ganze Tokens geprueft:
`III.` erfuellt `III`, `3`, `II`, `IIIs` und `iii` nicht. Es wird keine
roemische Zahl aus jedem englischen `I` oder jedem `IV` geraten. Die Zuordnung
muss die Datenquelle liefern. Ohne dieses optionale Feld gibt es keinen neuen
Tokencheck. Andere bestehende Warnungen/Fehler bleiben wirksam.

Beide vorhandenen Karten-JSON-Formen (`[...]` und `{"cards": [...]}`) werden
von der CLI unterstuetzt. Pruefen: `python3 -m unittest discover -s tests -v`.
Die neun Tests verwenden ausschliesslich erfundene Texte; keine ROM-/Pixel-/
Szenen-/Kanonfreigabe. Diese Aenderung ist ein isolierter Draft und setzt keine
Namensliste oder globale Umbenennung im Projekt um.

[MIT](LICENSE) — Copyright (c) 2026 pokemon-unbound-de

---

*Teil des Pokémon Unbound DE Projekts. Unoffizielles Fan-Projekt, nicht
mit den Rechteinhabern verbunden. Keine ROMs, Inhalte oder privaten
Daten in diesem Repository.*
