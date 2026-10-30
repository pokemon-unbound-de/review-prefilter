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

### Korpuseingaben

`--corpus` akzeptiert eine JSON-Liste von Eintraegen oder ein Objekt mit
`"entries": [...]`. Eintraege sind Objekte mit `en_raw`/`de_raw` als Text
oder `null`; leere oder fehlende Texte werden wie bisher herausgefiltert.
Eine ausdruecklich leere Liste ist gueltig. Ohne `--corpus` bleibt der
Korpusabgleich ausgeschaltet.

Wird eine Datei ausdruecklich angegeben, muss sie lesbar sein und das Format
erfuellen. Fehlende Dateien, ungueltiges JSON/UTF-8, falsche Strukturen oder
nicht-textuelle Textfelder brechen mit Exit1 ab, bevor Cache/Pruefung und
neue Reports entstehen. Ein fehlender Korpus wird nicht mehr stillschweigend
als leerer behandelt. Details und Vorher/Nachher: [CORPUS_INPUT.md](CORPUS_INPUT.md).
Alte Reports werden im Fehlerfall nicht entfernt; Exitcode pruefen und fuer
jeden Lauf einen frischen Ausgabeordner verwenden.

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

- Implementiert: optionaler `--cache` fuer deterministische Layer-1-Ergebnisse.
  Der Schluessel beruecksichtigt die gesamte Karte und alle Pruefabhaengigkeiten;
  `source_sha256` allein genuegt nicht (Details unten).
- Web-App-Integration: `prefilter_results.json` als Input für die
  Dialogwerkstatt (Karten nach Risiko sortieren, AI-Vorschläge anzeigen)

## Versionen

- **v0.1** — alle Layer-1-Checks, Layer-2-Interface, Arbeitslast-Schätzung

## Lizenz

[MIT](LICENSE) — Copyright (c) 2026 pokemon-unbound-de

---

*Teil des Pokémon Unbound DE Projekts. Unoffizielles Fan-Projekt, nicht
mit den Rechteinhabern verbunden. Keine ROMs, Inhalte oder privaten
Daten in diesem Repository.*

## Inkrementelle Layer-1-Prüfung

Mit `--cache /privater/pfad/review.sqlite3` können deterministische
Kartenergebnisse lokal wiederverwendet werden. Ohne diese Option bleibt der
Cache aus. Der Schlüssel berücksichtigt **die gesamte Karte** (auch DE,
Kontext und Layout-Metadaten), Glossar, Korpus, Konsistenzgruppen, Fuzzy-Option
und den Inhalt beider Python-Prüfdateien. `source_sha256` allein reicht nicht.
Änderungen an gemeinsamen Daten invalidieren konservativ alle Einträge.

Der Cache enthält Karteninhalte und Prüfbefunde: ausschließlich lokal/privat
aufbewahren. SQLite-Dateien sind git-ignoriert. Das bestehende Reportformat
bleibt erhalten; `summary.layer1_cache` nennt Treffer und neue Prüfungen.
Beschaedigte Eintragspayloads werden neu berechnet. Auch nicht-textuelle
`payload`-/`digest`-Felder (z.B. SQLite-BLOBs) sind Cache-Misses statt Python-
Abstuerzen; nur der betroffene Eintrag wird neu geschrieben. Bei gleicher
Pruefversion bleiben andere gueltige Eintraege Treffer. Ein beschaedigter oder
nicht zugaenglicher Datenbankcontainer fuehrt weiter zum Fehler statt zu einem
Erfolg. Vorher/Nachher und Grenzen: [CACHE_RECOVERY.md](CACHE_RECOVERY.md).

Der Cache speichert **keine LLM-Antworten**. `--llm` behält sein bisheriges
Verhalten und verursacht bei jedem aktivierten Lauf erneut externe Aufrufe.
Der Cache ersetzt weder menschliches Review noch ROM-/Emulatorprüfungen.

Prüfen: `python3 -m unittest discover -s tests -v`.

Betriebshinweise: Der Cache hat noch keine automatische Größenbegrenzung oder
Bereinigung. Alte Einträge bleiben erhalten, bis die lokale Datei bei
angehaltener Verarbeitung entfernt wird; der nächste Lauf prüft dann neu.
Veränderte Queue-Zusammensetzung kann Konsistenzgruppen ändern und dadurch
alle Cacheeinträge invalidieren. Nichtendliche Zahlen (NaN/Infinity) sind
für Cache-Schlüssel ungültig. Solche Eingaben oder nicht zugängliche
Cachedateien brechen die CLI mit Exitcode 1 und kurzer Fehlermeldung ab.
Vorhandene Reports älterer Läufe werden dabei nicht gelöscht; der aufrufende
Prozess muss den Exitcode prüfen und einen frischen Ausgabeordner verwenden.
