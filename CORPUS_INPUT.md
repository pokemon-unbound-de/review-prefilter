# CX-043: Korpuseingaben zuverlaessig pruefen

Der bisherige Loader versuchte auch bei einer JSON-Liste `data.get(...)`
aufzurufen. Damit brach die im Code vorgesehene Listenvariante mit einem
AttributeError ab. Eine ausdruecklich angegebene, fehlende Datei wurde dagegen
als leerer Korpus behandelt und konnte einen erfolgreichen Report erzeugen.
Das machte fehlende Pruefgrundlagen leicht uebersehbar.

Jetzt funktionieren beide vorhandenen Varianten gleich:

```json
[{"id":"synthetic-source","en_raw":"Hello friend","de_raw":"Hallo Freund"}]
```

oder

```json
{"entries":[{"id":"synthetic-source","en_raw":"Hello friend","de_raw":"Hallo Freund"}]}
```

Dies sind erfundene Beispieldaten. Zusaetzliche Metadaten auf dem Objekt bzw.
den Eintraegen bleiben erlaubt. Leere Listen sind gueltig. Fehlendes/null/leeres
EN oder DE wird wie bisher uebersprungen; bestehende Escape-Filter,
Normalisierung und Trefferauswahl bleiben erhalten.

Bei expliziter Datei fuehren nicht lesbare Pfade, ungueltiges JSON/UTF-8,
falsche Wurzel-/Eintragsstrukturen oder nicht-textuelle EN-/DE-Felder zu
Exit1 mit kurzer Fehlermeldung ohne Quelldaten/Traceback. Die CLI startet dann
keinen Cache und schreibt keinen neuen Report. Ohne `--corpus` funktioniert
der bisherige optionale Betrieb weiter. Alte Reportdateien werden nicht
geloescht; der Aufrufer muss Exitcodes beachten und frische Ausgabeordner nutzen.

## Gegenprobe

Synthetische Karte und synthetischer Korpus, kein LLM, kein Fuzzy-Lookup:

| Fall | Vorher 5ecbdfd | Korrigiert |
|---|---|---|
| JSON-Liste als Korpus | Exit1, AttributeError/Traceback | Exit0, exakter Korpustreffer |
| Explizit fehlende Korpusdatei | Exit0, Erfolgsreport ohne Korpus | Exit1, kein neuer Report |
| Liste vs. gleichwertiges entries-Objekt | Listenlauf brach ab | Identische Kartenergebnisse |
| Folgelauf mit gleichwertiger anderer Verpackung | Nicht moeglich | Gueltiger Cachetreffer |

```sh
python3 -m unittest discover -s tests -v
```

18/18 Tests bestehen: die bisherigen zwoelf Cachetests sowie sechs neue
Korpustests mit positiven Kontrollen, echtem CLI-Aufruf und Negativfaellen
einschliesslich falschem UTF-8, leeren/fehlenden Daten, falschen Typen und
ausbleibender Quelldaten-Ausgabe bei Fehlern. Liste/Objekt werden zum gleichen
Index geladen, weshalb der zweite Lauf innerhalb derselben Pruefversion den
Cache wiederverwenden kann. Codeupdates invalidieren weiter einmal konservativ.

`corpus_input_repro.json` dokumentiert den Vorher/Nachher-Versuch und Codehashes.
Temporare Karten, Reports und Caches wurden entfernt. Die Tests bestaetigen
das lokale Eingabe-/Reportverhalten, keine echte ROM-/Portabdeckung oder
unabhaengige Projektabnahme. Cachelogik, Matching-/Bewertungsregeln, Live-API,
LLM-Aufrufe, Pflicht-CI/Gates und Merges wurden nicht geaendert.
