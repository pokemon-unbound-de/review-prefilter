# CX-044: konkurrierende Korpusfassungen sichtbar machen

Der Loader behielt bisher pro normalisiertem EN-Schluessel nur den ersten
Eintrag. Bei unterschiedlichen deutschen Fassungen wurde deshalb je nach
Dateireihenfolge eine andere Fassung als exakter Treffer angeboten. Im
synthetischen Beispiel erschien die Karte in beiden Reihenfolgen als pass;
ein Hinweis auf den Korpuskonflikt fehlte.

Jetzt sammelt derselbe Loader unterschiedliche DE-Rohfassungen je vorhandenem
EN-Suchschluessel. Bei mehr als einer Fassung bleibt dieser Suchschluessel im
Index, traegt aber ausschliesslich Mehrdeutigkeitsmetadaten. Der Checker
meldet corpus_ambiguity/warning, behaelt keinen Einzelvorschlag und liefert
corpus_match:null. Das resultierende Verdict ist mindestens review, andere
Fehler koennen weiterhin fix ergeben. Es wird keine Fassung automatisch
verworfen, korrigiert oder uebernommen.

Eindeutige Fassungen und identische DE-Duplikate funktionieren wie zuvor.
Geprueft werden rohe DE-Strings, sodass auch Schreib-/Layoutunterschiede
sichtbar bleiben; sie koennen legitim sein und muessen menschlich bewertet
werden. Die bestehende EN-Normalisierung und Fuzzy-Suche bleiben bestehen.
Auch ein Fuzzy-Treffer auf einen mehrdeutigen Schluessel liefert keinen
DE-Gewinner. Das ist keine vollstaendige Analyse von Gleichstaenden zwischen
verschiedenen Fuzzy-Schluesseln. Keine Szenen-, Versions- oder ROM-Aussage.

Ein Hash aller sortierten DE-Varianten bleibt intern Teil des Korpusindexes
und damit der bestehenden Cacheabhaengigkeiten. Aendert sich der Inhalt bei
gleicher Variantenanzahl, wird neu geprueft. Eine reine Umkehrung der
Quellreihenfolge veraendert die Konfliktmetadaten nicht. Bei identischen
DE-Duplikaten bleibt die bisherige Quellenreferenz-Auswahl erhalten; keine
allgemeine Reihenfolgeunabhaengigkeit dieser Referenzen wird behauptet.

## Pruefungen

`python3 -m unittest discover -s tests -v`:24/24 Tests, davon sechs neue
Konflikttests. Exakt/Fuzzy, umgekehrte Reihenfolge, normalisierte EN-Kollision,
identische Duplikate, positive eindeutige Kontrolle, Varianteninhalt trotz
gleicher Anzahl, Aufloesung des Konflikts und kompletter CLI-Kalt-/Warmlauf.
`corpus_ambiguity_repro.json` enthaelt nur synthetische Vorher/Nachher-Faelle
und Codehashes. Die bisherige Eingabe-/Cachepruefung besteht weiter.

Private Daten-QA am vorhandenen CSV-Stand (17188 Datensaetze, SHA-256
ae7dde0f52a5ff1e37f22e67cd145197421323153ace30003c4585ef8330b718):
CSV-Felder id/en/de wurden nur fuer den Test temporaer in das vorhandene
JSON-Inventarformat id/en_raw/de_raw abgebildet. Nach bestehenden Filtern und
EN-Normalisierung ergeben sich15234Suchschluessel, davon1022mit mehreren
DE-Rohfassungen und14212mit einer Fassung. Alle1022Konfliktschluessel wurden
mit Warnung ohne Einzelvorschlag geprueft; ihre Metadaten blieben bei
umgekehrter Eingabereihenfolge gleich. Keine privaten Texte/IDs/Inventare
oder Kartenreports wurden in diesem oeffentlichen Repo gespeichert.

Die1022sind normalisierte Suchschluessel nach Vorfilterregeln. Sie sind
nicht die821exakten EN-Konfliktgruppen der getrennten Port-Negativmatrix,
keine1022falschen Uebersetzungen und keine echte Portabdeckung. Der echte
1.0.1/2.1.1.1-Export bleibt erforderlich. Eigene lokale Pruefungen, keine
unabhaengige Abnahme. Keine Live-/LLM-/ROM-/Build-/Pflichtgate-/Mergeaenderung.
