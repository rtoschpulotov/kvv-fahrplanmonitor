# Entscheidungsprotokoll

Hier halte ich fest, was ich wie entschieden habe und warum. Jede Entscheidung soll ich im Gespräch begründen können.

## E1: Sammeln vor allem anderen

Der KVV hält alte Fahrplanstände nicht vor. Jeder Tag ohne Abruf fehlt dauerhaft im Archiv. Deshalb lief das Sammelskript, bevor irgendetwas anderes stand.

## E2: Inhalts-Hash statt nur ZIP-Hash

Eine ZIP-Datei enthält Zeitstempel der gepackten Dateien. Packt der KVV unveränderte Daten neu, ändert sich der Datei-Hash trotzdem. Ich hashe deshalb jede enthaltene Datei einzeln und bilde daraus einen Gesamt-Hash, sortiert nach Dateiname. Nur wenn sich dieser ändert, lege ich einen neuen Stand ab. Den ZIP-Hash schreibe ich zusätzlich ins Register, um später sehen zu können, wie oft der KVV nur neu packt.

## E3: Jeder Lauf ins Register, auch ohne Änderung

Für die Stabilitätsauswertung ist "an diesem Tag hat sich nichts geändert" eine echte Information. Ohne Zeile für unveränderte Tage könnte ich das nicht von "an diesem Tag lief das Skript nicht" unterscheiden. Fehlgeschlagene Abrufe kommen aus demselben Grund mit Status `fehler` ins Register.

## E4: GitHub Actions statt lokalem Zeitplan

Mein Rechner ist nicht jeden Tag an. Ein lokaler Cronjob oder ein Scheduler-Container in Docker würde Lücken produzieren. GitHub Actions läuft unabhängig davon.

## E5: Release-Anhänge statt ZIPs im Git

Ein Stand ist rund 28,7 MB groß (erster echter Abruf am 2026-11-03: 28.714.561 Bytes, 12 Dateien). Ursprünglich hatte ich mit 7 MB gerechnet. Bei fast täglichen Änderungen wüchse das Repo damit um grob 850 MB im Monat. Git ist für große Binärdateien nicht gemacht, und jeder Klon würde das gesamte Archiv mitziehen. Release-Anhänge liegen am Repo, aber außerhalb des Verlaufs.

## E6: Betriebstage aus calendar und calendar_dates

[Offen, Phase 2. Hier dokumentiere ich, wie ich reguläre Betriebstage und Ausnahmen für Feiertage und Sonderverkehre zusammenführe. Fehler an dieser Stelle machen alle Taktzahlen plausibel falsch.]
