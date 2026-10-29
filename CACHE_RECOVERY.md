# CX-039: ungueltigen Cache-Eintrag gezielt reparieren

## Beobachteter Fehler

Am Stand 1f91e58 konnte eine nicht-textuelle SQLite-Payload den gesamten
Wiederholungslauf abbrechen: Ein als BLOB gespeichertes Feld erreichte
`payload.encode()` und verursachte einen AttributeError mit Traceback.
Die damalige Eintrags-Reparatur behandelte nur Textwerte.

Jetzt werden Payload und gespeicherter Digest zuerst auf String-Typ geprueft.
Abweichende Typen gelten als Miss und werden durch das normale deterministische
Pruefergebnis ersetzt. Es werden keine Tabellen/Datenbanken entfernt und keine
anderen Cache-Eintraege geloescht. LLM-Antworten werden weiterhin nicht gecacht;
Cacheoption bleibt standardmaessig aus.

## Synthetischer CLI-Vergleich

Zwei erfundene Karten, kein Korpus, kein Fuzzy-Lookup und kein LLM. Je Codeversion
wurde ein eigener Cache erzeugt, dann nur die Payload der Karte A in einen BLOB
geaendert und dieselbe CLI erneut gestartet. Keine privaten Texte gespeichert.

| Zustand | Vorher 1f91e58 | Korrigierter Stand |
|---|---|---|
| Lauf nach einem kaputten Eintrag | Exit1, AttributeError/Traceback | Exit0, kein Traceback |
| Wiederverwendete gueltige Nachbarkarte | Gesamtlauf abgebrochen | 1 Treffer |
| Neu geprueft | Kein erfolgreicher Report | 1 Karte |
| Ergebnisliste | Kein neuer Erfolg | Identisch zum ersten gueltigen Lauf |
| Naechster unveraenderter Lauf | Nicht als Erfolg gewertet | 2 Treffer, 0 neue Pruefungen |

Vorheriger Cachecode-SHA256:
`085b14716853ff30eee621d7300fbb2f692bd3c05f9591c028f17e49918d5247`.
Korrigierter Cachecode-SHA256:
`e495404668b1a74a8b86f27203dca254b656f4f3e2fed1dc0bdc5e9f4ae3000b`.
Temporare Queues, Reports und SQLite-Dateien wurden nach dem Versuch entfernt.
Die Tabellenwerte enthalten keine echte Pipeline-Laufzeitmessung.

## Reproduktion und Aussagegrenzen

```sh
python3 -m unittest discover -s tests -v
```

12/12 Tests bestehen (vorher 8). Vier neue Tests sichern BLOB-Payloads
(einschliesslich ungueltigem UTF8 und gueltigen JSON-Bytes im falschen Speichertyp),
BLOB-Digests, korrekt gehashte aber ungueltige JSON-/Ergebnisformen und den
vollstaendigen CLI-Reparaturfall ab. Die Nachbarkarte bleibt jeweils ein Treffer;
die Reparatur wird als Text gespeichert und der folgende Lauf ist wieder warm.

Dies ist lokale Fehlerbehandlung fuer lesbare Cachezeilen. Eine defekte SQLite-
Datei, unlesbare Textkodierung oder Zugriffsfehler koennen weiterhin sauber mit
Exit1 abbrechen. Der Aufrufer muss den Exitcode beachten; alte Reports werden
bei einem Fehler nicht entfernt. Ein Cachehash attestiert keinen vertrauens-
wuerdigen Fremdprozess. Es ist kein neuer Schutz gegen absichtliche Manipulation.

Der CLI-Schluessel enthaelt den Pruefcode. Ein Update dieses Codes invalidiert
bestehende Eintraege bewusst einmal; selektive Reparatur gilt innerhalb einer
stabilen Pruefversion, nicht als Behauptung ueber Trefferraten beim Versionswechsel.
Keine LLM-/API-, Live-Werkstatt-, CI-/Gate- oder Merge-Aenderung. Der bestehende
Draft bleibt zur Projektabnahme offen; eigene Tests sind kein unabhaengiges Review.
