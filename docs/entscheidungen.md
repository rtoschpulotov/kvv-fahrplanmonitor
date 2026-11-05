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

Welche Fahrt an welchem Tag fährt, steht nicht direkt im Feed. Jede Fahrt verweist auf eine service_id, und erst `calendar` und `calendar_dates` zusammen sagen, an welchen Tagen diese service_id gilt. Ich löse das in `analyse/betriebstage.py` nach der GTFS-Regel auf:

1. Aus `calendar`: Tag D gehört dazu, wenn D zwischen start_date und end_date liegt und die Wochentagsspalte für D eine 1 hat.
2. Aus `calendar_dates` mit exception_type 1: D kommt dazu.
3. Aus `calendar_dates` mit exception_type 2: D fällt weg.

Ergebnis ist (1 vereinigt mit 2) ohne 3, als Tabelle (service_id, datum).

**Warum kein Join auf calendar:** Ausnahmen können sich auf service_id beziehen, die in `calendar` gar nicht stehen. Ein Join würde sie still verlieren. Im aktuellen KVV-Feed kommt das nicht vor, die Funktion behandelt es trotzdem richtig, und ein Test sichert das ab.

**Feiertage** behandle ich nicht selbst. Ich verlasse mich auf die Ausnahmen des KVV und prüfe nur, ob sie wirken: Am Samstag, 03.10.2026, fahren 5.103 Fahrten statt rund 7.000 an normalen Samstagen. Das ist Sonntagsniveau (siehe `docs/befunde.md`).

**Abgesichert durch** acht Tests in `tests/test_betriebstage.py`: normaler Werktag, Feiertag als Typ 2, Sonderverkehr als Typ 1, Dienst nur über calendar_dates, Tag außerhalb der Gültigkeit, Ausnahme außerhalb des Zeitraums, keine Dublette bei Typ 1 auf einem regulären Tag, leerer calendar. Weitere Tests in derselben Datei prüfen die Umrechnung von Uhrzeiten über 24 Uhr und die Regeln aus E9.

## E7: Manifest je Stand und Rolle von MongoDB

Das Register sagt mir, ob sich ein Stand geändert hat. Welche der zwölf Dateien sich geändert hat, sagt es nicht. Deshalb lege ich zu jedem neuen Stand ein Manifest als JSON ab: Abrufzeitpunkt, beide Hashes, HTTP-Header und für jede Datei Name, Größe, SHA-256 und Zeilenzahl. Das ist eine verschachtelte Liste. In einer CSV würde daraus entweder ein unlesbarer Textblock in einer Spalte oder eine zweite Tabelle. In einem Dokumentspeicher ist es einfach ein Dokument.

MongoDB ist damit die Landing Zone für die Manifeste (Collection `snapshots`) und für alle Läufe aus dem Register, inklusive Fehlschlägen (Collection `abrufe`). Die Wahrheit liegt aber nicht dort, sondern im Register und in den Releases. MongoDB kann ich jederzeit wegwerfen und mit `sammler/lade_landing_zone.py` neu aufbauen. Das Skript schreibt per Upsert und darf beliebig oft laufen, ohne Dubletten zu erzeugen.

**Schlüssel ist der Stand, nicht der Inhalts-Hash.** Ursprünglich wollte ich auf den Inhalts-Hash upserten. Das geht schief, sobald der KVV eine Änderung zurücknimmt: Dann taucht ein alter Inhalts-Hash ein zweites Mal als neuer Stand auf, und mit dem Hash als Schlüssel würden beide Stände zu einem Dokument verschmelzen. Die Rücknahme wäre aus MongoDB verschwunden, obwohl gerade sie für die Stabilitätsfrage interessant ist. Ich nehme deshalb den Zeitstempel aus dem Dateinamen als `_id` (zum Beispiel `2026-11-03T201359Z`, derselbe Teil wie im Release-Tag). Auf dem Inhalts-Hash liegt nur ein normaler Index. Den Fall A, B, wieder A habe ich mit einer selbst veränderten ZIP durchgespielt.

**Zeilenzahl** heißt bei mir: Datensätze ohne Kopfzeile, gezählt über Zeilenumbrüche. Das ist deutlich schneller als jede Zeile zu parsen, würde aber Zeilenumbrüche innerhalb von Feldern doppelt zählen. Beim ersten echten Stand stimmen beide Zählweisen für alle zwölf Dateien überein (`stop_times.txt`: 3.033.673 Zeilen, `trips.txt`: 147.492).

**Der Inhalts-Hash bleibt, wie er war.** Ich habe das alte und das neue Skript gegen dieselbe ZIP laufen lassen, beide liefern `2d9ba400c88f...`, genau den Wert im Register.

**Stände ohne Manifest:** Der erste Stand vom 2026-11-03 ist älter als das Manifest. Das Ladeskript baut es aus ZIP und Registerzeile nach und bricht ab, wenn der berechnete Inhalts-Hash nicht zum Register passt.

**`verarbeitet_am`** legt das Ladeskript beim ersten Einfügen leer an und fasst es danach nicht mehr an. Phase 2 und 3 setzen es, damit kein Stand doppelt verarbeitet wird.

## E8: Zeitumstellung wird dokumentiert, nicht gelöst

GTFS zählt Uhrzeiten ab "Mittag minus 12 Stunden". An normalen Tagen ist das Mitternacht. An den beiden Tagen der Zeitumstellung ist es 23 Uhr (Frühjahr) oder 1 Uhr (Herbst). Nachgerechnet heißt das: Abfahrten nach der Umstellung stimmen auch mit meiner einfachen Rechnung (Mitternacht plus Sekunden), aber die wenigen Abfahrten zwischen Mitternacht und der Umstellung um 2 oder 3 Uhr liegen eine Stunde daneben.

Ich rechne trotzdem mit Mitternacht. Es betrifft zwei Tage im Jahr, im aktuellen Stand nur den 25.10.2026, und eine saubere Lösung bräuchte Zeitzonenlogik, die an allen anderen Tagen nichts ändert. Stattdessen nehme ich diese Tage nie als Stichtag. Wer eine Auswertung über alle Tage macht, muss sie gesondert betrachten.

## E9: Was eine Abfahrt und was eine Haltestelle ist

**Haltestelle heißt Station, nicht Bahnsteig.** Hat ein Halt in `stops.txt` eine `parent_station`, zähle ich ihn zu dieser Station. Hat er keine, ist er selbst die Station. Sonst würde ein Halt mit vier Bahnsteigen viermal gezählt. Im Stand vom 04.11.2026 werden so aus 4.261 Halten 2.078 Haltestellen.

**Eine Abfahrt ist ein Halt, an dem man einsteigen kann.** Das heißt:

- Der letzte Halt einer Fahrt ist keine Abfahrt. Ich bestimme ihn über die höchste stop_sequence, weil der KVV ihn fast nie als "kein Einstieg" markiert.
- Halte mit pickup_type 1 (kein Einstieg) zählen nicht.
- Halte ohne Uhrzeit zählen nicht. Das betrifft einen einzigen Halt im ganzen Feed.
- **Halte mit pickup_type 2 (Einstieg nach telefonischer Anmeldung) zählen mit.** Man kann dort einsteigen, und im ländlichen Teil des KVV sind Rufbusse oft das einzige Angebot am Abend. Würde ich sie weglassen, sähen genau diese Gemeinden schlechter versorgt aus, als sie sind. Die Spalte pickup_type bleibt erhalten, damit ich sie in der Auswertung getrennt ausweisen kann. Am Di 10.11.2026 sind das 5.266 von 163.037 Abfahrten.

**Kalenderzeit statt Betriebstagszeit.** Eine Abfahrt um 25:10:00 am Betriebstag D zähle ich am Kalendertag D+1 um 01:10 Uhr, weil Fahrgäste die Uhr sehen und nicht den Betriebstag. Den Betriebstag behalte ich als eigene Spalte, weil Phase 4 ihn für den Vergleich zwischen Ständen braucht.

