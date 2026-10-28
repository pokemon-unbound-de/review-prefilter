# Lokale Messung des Layer-1-Caches

28.10.2026; ein Lauf je Zustand auf diesem Mac, Python 3.9.
Input: 17.188 Karten aus der privaten CSV v0.1.7.2, 258 Glossareinträge
vom lokalen NAMENSVERZEICHNIS. Keine Spieltexte oder Befunde hier abgelegt.
Kein Fuzzy-/Korpus-Lookup, kein LLM, kein Emulator. Temporäre Cachedatei
nach dem Vergleich entfernt. Ergebnislisten vollständig auf Gleichheit geprüft.

| Zustand | Sekunden | Cachetreffer | Neu geprüft |
|---|---:|---:|---:|
| Ohne Cache | 9,686 | 0 | 17.188 |
| Erster Cachelauf | 9,627 | 0 | 17.188 |
| Unveränderter Wiederholungslauf | 0,278 | 17.188 | 0 |

Der warme Lauf war in diesem Versuch etwa 35-mal schneller.
Einzelmessung, kein statistischer Benchmark oder Nachweis für CI-Durchsatz.
Die kleine Abweichung des ersten Cachelaufs ist kein belegter Gewinn.
Globale Daten-/Regeländerungen invalidieren alle Einträge. Ob dieser Cache
in Nevios System benötigt wird, ist noch nicht geklärt. Keine Aussage zu
Tokenersparnis oder Releasequalität allein aus dieser Messung.
