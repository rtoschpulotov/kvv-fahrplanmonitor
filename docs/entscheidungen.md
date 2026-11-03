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

## E7: Manifest je Stand und Rolle von MongoDB

Das Register sagt mir, ob sich ein Stand geändert hat. Welche der zwölf Dateien sich geändert hat, sagt es nicht. Deshalb lege ich zu jedem neuen Stand ein Manifest als JSON ab: Abrufzeitpunkt, beide Hashes, HTTP-Header und für jede Datei Name, Größe, SHA-256 und Zeilenzahl. Das ist eine verschachtelte Liste. In einer CSV würde daraus entweder ein unlesbarer Textblock in einer Spalte oder eine zweite Tabelle. In einem Dokumentspeicher ist es einfach ein Dokument.

MongoDB ist damit die Landing Zone für die Manifeste (Collection `snapshots`) und für alle Läufe aus dem Register, inklusive Fehlschlägen (Collection `abrufe`). Die Wahrheit liegt aber nicht dort, sondern im Register und in den Releases. MongoDB kann ich jederzeit wegwerfen und mit `sammler/lade_landing_zone.py` neu aufbauen. Das Skript schreibt per Upsert und darf beliebig oft laufen, ohne Dubletten zu erzeugen.

**Schlüssel ist der Stand, nicht der Inhalts-Hash.** Ursprünglich wollte ich auf den Inhalts-Hash upserten. Das geht schief, sobald der KVV eine Änderung zurücknimmt: Dann taucht ein alter Inhalts-Hash ein zweites Mal als neuer Stand auf, und mit dem Hash als Schlüssel würden beide Stände zu einem Dokument verschmelzen. Die Rücknahme wäre aus MongoDB verschwunden, obwohl gerade sie für die Stabilitätsfrage interessant ist. Ich nehme deshalb den Zeitstempel aus dem Dateinamen als `_id` (zum Beispiel `2026-11-03T201359Z`, derselbe Teil wie im Release-Tag). Auf dem Inhalts-Hash liegt nur ein normaler Index. Den Fall A, B, wieder A habe ich mit einer selbst veränderten ZIP durchgespielt.

**Zeilenzahl** heißt bei mir: Datensätze ohne Kopfzeile, gezählt über Zeilenumbrüche. Das ist deutlich schneller als jede Zeile zu parsen, würde aber Zeilenumbrüche innerhalb von Feldern doppelt zählen. Beim ersten echten Stand stimmen beide Zählweisen für alle zwölf Dateien überein (`stop_times.txt`: 3.033.673 Zeilen, `trips.txt`: 147.492).

**Der Inhalts-Hash bleibt, wie er war.** Ich habe das alte und das neue Skript gegen dieselbe ZIP laufen lassen, beide liefern `2d9ba400c88f...`, genau den Wert im Register.

**Stände ohne Manifest:** Der erste Stand vom 2026-11-03 ist älter als das Manifest. Das Ladeskript baut es aus ZIP und Registerzeile nach und bricht ab, wenn der berechnete Inhalts-Hash nicht zum Register passt.

**`verarbeitet_am`** legt das Ladeskript beim ersten Einfügen leer an und fasst es danach nicht mehr an. Phase 2 und 3 setzen es, damit kein Stand doppelt verarbeitet wird.
