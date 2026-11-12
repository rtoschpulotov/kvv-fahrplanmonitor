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
- **Hält eine Fahrt mehrmals direkt hintereinander an derselben Station, ist das eine Abfahrt.** Das passiert, wenn ein Bus an der Endhaltestelle den Bahnsteig wechselt oder eine Schleife fährt, zum Beispiel Linie 55 am Kühler Krug: erst Bahnsteig 1, dann Bahnsteig 2 ohne Einstieg, dann wieder Bahnsteig 1. Ich zähle nur den letzten Halt der Folge, an dem man einsteigen kann, denn dann fährt der Bus wirklich los. Kommt eine Fahrt dagegen später noch einmal an dieselbe Station zurück (Ringlinie), sind das zwei echte Abfahrten. Gefunden habe ich das erst bei der Handprüfung von fünf Fahrten. Im Stand vom 04.11.2026 stehen gut 55.000 solcher Doppelhalte in 35.000 Fahrten. Am Di 10.11.2026 sinkt die Zahl der Abfahrten dadurch von 163.037 auf 161.790.
- **Halte mit pickup_type 2 (Einstieg nach telefonischer Anmeldung) zählen mit.** Man kann dort einsteigen, und im ländlichen Teil des KVV sind Rufbusse oft das einzige Angebot am Abend. Würde ich sie weglassen, sähen genau diese Gemeinden schlechter versorgt aus, als sie sind. Die Spalte pickup_type bleibt erhalten, damit ich sie in der Auswertung getrennt ausweisen kann. Am Di 10.11.2026 sind das 5.266 von 161.790 Abfahrten.

**Kalenderzeit statt Betriebstagszeit.** Eine Abfahrt um 25:10:00 am Betriebstag D zähle ich am Kalendertag D+1 um 01:10 Uhr, weil Fahrgäste die Uhr sehen und nicht den Betriebstag. Den Betriebstag behalte ich als eigene Spalte, weil Phase 4 ihn für den Vergleich zwischen Ständen braucht.


## E10: Gleichmäßigkeit über die erwartete Wartezeit messen

Die Aufgabenstellung verlangt neben den Abfahrten je Stunde den mittleren Abstand zwischen zwei Abfahrten. Beim Umsetzen ist mir aufgefallen, dass der mittlere Abstand nichts Neues sagt: Sechs Abfahrten in einer Stunde haben immer einen mittleren Abstand von zehn Minuten, egal ob sie im 10-Minuten-Takt kommen oder alle sechs zwischen 08:00 und 08:05. Er ist einfach 60 geteilt durch die Zahl der Abfahrten.

Ich weise ihn trotzdem aus, ergänze aber zwei Kennzahlen, die die Verteilung sehen:

- **Größter Abstand:** das längste Stück der Stunde ohne Abfahrt.
- **Erwartete Wartezeit:** Ein Fahrgast kommt zu einem zufälligen Zeitpunkt in der Stunde und wartet bis zur nächsten Abfahrt, auch wenn die erst in der nächsten Stunde liegt. Im Durchschnitt über die Stunde ist das beim 10-Minuten-Takt 5 Minuten, bei sechs Abfahrten im Pulk und dann 55 Minuten Pause gut 25 Minuten.

Dass das kein theoretischer Unterschied ist, zeigt der Stand vom 04.11.2026: Am Di 10.11. haben 166 Stationen in der Stunde ab 8 Uhr genau sechs Abfahrten. Ihre erwartete Wartezeit liegt zwischen 5,0 und 18,1 Minuten.

**Deckel bei 60 Minuten.** Jede einzelne Wartezeit zähle ich höchstens mit 60 Minuten. Ohne Deckel bekäme eine Station mit einer Abfahrt um 01:04 und der nächsten um 22:27 für die Stunde ab 1 Uhr über 19 Stunden Wartezeit. Das ist keine Wartezeit mehr, sondern kein Angebot, und es würde jeden Mittelwert zerstören. 60 heißt bei mir: in dieser Stunde praktisch keine Verbindung.

**Nach der letzten Abfahrt des Tages** zählt nichts mehr. Wer um 23:30 nach der letzten Bahn kommt, bekommt keine Wartezeit, die Stunde hat dafür weniger abgedeckte Minuten.

**Einschränkung:** Ich rechne über alle Linien und Richtungen einer Station zusammen. Für jemanden, der in eine bestimmte Richtung will, ist das zu optimistisch. Eine Auswertung je Richtung wäre genauer, braucht aber eine Definition von Richtung über Linien hinweg, die GTFS nicht liefert.

## E11: Gemeinden, Kerngebiet und Abendfenster

**Zuordnung.** Jede Station bekommt über ihre Koordinate die Gemeinde, in deren Fläche sie liegt (Punkt in Polygon mit GeoPandas). Quelle ist die VG250-EW des BKG (Stand 31.12.2025, dl-de/by-2-0) mit Einwohnerzahlen von Destatis. Von 2.078 Stationen liegen 13 in keiner deutschen Gemeinde, alle im Elsass (Seltz, Roeschwoog, Soufflenheim und Nachbarorte). Ich zähle und zeige sie, werte sie aber nicht pro Kopf aus, weil mir dafür die französischen Einwohnerzahlen fehlen.

**Kerngebiet statt aller Gemeinden.** Der KVV-Feed enthält auch Haltestellen weit außerhalb, zum Beispiel in Heilbronn, Pforzheim oder im Ortenaukreis, wo nur einzelne KVV-Linien enden. Dort fährt vor allem der Verkehr anderer Verbünde, der im Feed fehlt. Pro Kopf sähen diese Orte absurd schlecht aus. Ich werte deshalb nur die 57 Gemeinden der vier Kreise aus, die ganz zum KVV gehören: Stadt Karlsruhe, Landkreis Karlsruhe, Stadt Baden-Baden und Landkreis Rastatt, zusammen gut 1,05 Millionen Einwohner.

**Was im Feed fehlt.** Auch im Kerngebiet ist der Feed nicht vollständig. Er enthält Stadtbahn, Straßenbahn, die S-Bahn-Linien der AVG und VBK und die Busse, aber keine Züge der DB. Graben-Neudorf zum Beispiel ist ein Bahnknoten der S-Bahn Rhein-Neckar, im Feed gibt es dort aber nur drei Buslinien und keine einzige Bahnsteig-Haltestelle. Gemeinden, die vor allem über DB-Züge angebunden sind, erscheinen deshalb schlechter versorgt, als sie sind. Ich lasse sie trotzdem in der Auswertung und kennzeichne das, statt sie still herauszunehmen. Der Abgleich mit kvv.de bestätigt das: Am Di 10.11.2026 fahren in Graben-Neudorf zwischen 7 und 9 Uhr 32 Fahrzeuge ab, im Feed stehen davon nur die 14 Busse. Die 18 Züge der S-Bahn-Linien S33, S6, S9 und des RE4 fehlen (siehe `docs/befunde.md`). Eine Ergänzung um die landesweiten Daten von MobiData BW wäre möglich, steht aber unter ODbL mit Share-Alike-Pflicht und ist eine eigene Entscheidung.

**Abendfenster von 4 bis 4 Uhr.** Für die Frage nach der letzten Abfahrt passt weder der Kalendertag noch der Betriebstag. Ein Nachtbus um 00:30 gehört für Fahrgäste noch zum Vorabend, steht nach Kalendertag aber am nächsten Tag. Der Betriebstag reicht im KVV-Feed bis 05:25 am Folgemorgen und würde Frühfahrten als "letzte Abfahrt" ausgeben. Ich nehme deshalb ein Fenster von 4 Uhr bis 4 Uhr am Folgetag. In der Stunde ab 3 Uhr gibt es am 10.11.2026 im ganzen Netz nur 102 Abfahrten. "Ohne Abfahrt nach 20 Uhr" heißt: zwischen 20 und 4 Uhr fährt in der Gemeinde nichts ab.

**Pro Kopf** heißt: alle Abfahrten an allen Stationen der Gemeinde im Fenster, geteilt durch die Einwohner, mal 1.000. Eine Abfahrt an einer Station mit mehreren Linien zählt so oft, wie Fahrzeuge abfahren.


## E12: SCD2 mit Beobachtungszeit

**Warum SCD2 und nicht ein Zeitstempel je Zeile.** Mit einem Zeitstempel je Zeile müsste ich für jede Frage nach einem früheren Zustand die ganze Historie lesen und selbst herausfinden, welche Zeile damals galt. Mit SCD2 hat jede Version einen Gültigkeitszeitraum, und "Wie hieß diese Haltestelle am 5. November?" ist eine einfache Bereichsabfrage. Die Fakten zeigen über den Surrogatschlüssel fest auf die Version, die zu ihrem Stand galt. Ändert sich später ein Name, bleibt eine alte Faktzeile bei ihrem alten Namen.

**Beobachtungszeit, nicht fachliche Gültigkeit.** gueltig_von und gueltig_bis sind die Abrufzeitpunkte der Stände, in denen ich eine Version zuerst und nicht mehr gesehen habe. Wann der KVV eine Haltestelle wirklich umbenannt hat, weiß ich nicht. Ich weiß nur, dass sie im einen Stand noch alt und im nächsten neu hieß. Das Datum, ab dem eine Änderung laut Fahrplan gilt, ist eine zweite, andere Zeitachse (fachliche Gültigkeit). Wer beide in einer Tabelle führt, modelliert bitemporal. Das brauche ich hier nicht, aber ich muss wissen, welche der beiden Achsen meine Spalten meinen: Es ist die Systemzeit meines Archivs.

**gueltig_bis ist ausschließlich.** Eine Version gilt für Zeitpunkte t mit gueltig_von <= t < gueltig_bis. Die alte Version endet genau dort, wo die neue beginnt, ohne dass beide an der Grenze gleichzeitig gelten. Mit einem einschließlichen Ende müsste ich eine Sekunde abziehen, und die Prüfung auf Überlappung würde unnötig kompliziert.

**9999-12-31 statt NULL.** Die aktuelle Version endet am 9999-12-31. So funktioniert die Bereichsabfrage ohne Sonderfall, und Power BI kommt mit festen Daten besser zurecht als mit NULL. ist_aktuell gibt es trotzdem, weil `WHERE ist_aktuell` lesbarer ist. Eine CHECK-Bedingung sorgt dafür, dass beide Spalten nie auseinanderlaufen.

**Kein SCD Typ 1.** Auch eine korrigierte Schreibweise wird eine neue Version. Ob eine Änderung inhaltlich bedeutend war, entscheidet die Auswertung, nicht der Ladeprozess.

**Wiederkehr.** Verschwindet eine Haltestelle und taucht später wieder auf, bekommt sie eine neue Version. Zwischen dem Ende der alten und dem Beginn der neuen liegt eine Lücke, in der es sie im Feed nicht gab. Ich öffne die alte Version nicht wieder, denn dann würde die Lücke aus der Historie verschwinden. Dasselbe gilt für A, B, wieder A: Das sind drei Versionen.

**SCD2 in SQL.** Der Schritt steht als zwei Anweisungen in `sql/05_scd2.sql`: ein UPDATE schließt jede aktuelle Version, zu der es im neuen Stand keine Zeile mit demselben Schlüssel und demselben Hash gibt, ein INSERT fügt jede Zeile ein, deren Schlüssel danach keine aktuelle Version hat. Damit sind alle vier Fälle abgedeckt (neu, unverändert, geändert, verschwunden). Beides läuft in der Transaktion des Stands.

**Reihenfolge.** Ein älterer Stand nach einem neueren würde Versionen rückwärts schließen. Das verhindert ein Trigger auf dim_stand (`sql/04_reihenfolge.sql`), nicht meine Aufmerksamkeit.

## E13: Körnung der Faktentabelle und Horizont

**Körnung.** Eine Zeile je Stand, Kalendertag, Stunde, Station und Linie, mit der Zahl der Abfahrten. Das reicht für alle Fragen der Ebene 1 (Takt je Stunde, Gemeinden, Tagestypen) und für den Vergleich zweier Stände. Eine Zeile je einzelner Abfahrt wäre etwa dreimal so groß und bringt für diese Fragen nichts. Die einzelnen Fahrten braucht erst die Diff-Logik in Phase 4, und die liest sie aus den ZIPs bzw. später aus Parquet.

**Kalendertag, nicht Betriebstag.** Wie in Phase 2 zählt, wann der Bus wirklich fährt (E9). Eine Fahrt um 24:30 steht am Folgetag in der Stunde 0.

**Horizont von 14 Tagen.** Jeder Stand bekommt Fakten ab dem Tag seines Abrufs (deutsche Zeit) für 14 Tage, höchstens bis zum Ende des Fahrplans. Ohne Grenze hätte jeder Stand Fakten bis zum Fahrplanende. Im November sind das gut 5 Wochen, nach dem Fahrplanwechsel im Dezember ein halbes Jahr. Gemessen mit den ersten fünf Ständen:

- rund 47.800 Faktzeilen je Tag,
- 14 Tage sind rund 663.000 Zeilen und gut 60 MB je Stand (Tabelle plus Primärschlüssel),
- ein halbes Jahr wären über 8 Millionen Zeilen und rund 800 MB je Stand.

14 Tage decken zwei volle Wochen mit je einem Samstag und Sonntag ab und reichen, um für denselben Tag die Pläne mehrerer aufeinanderfolgender Stände zu vergleichen. Der Wert ist ein Parameter (`--horizont`).

**Die Redundanz ist gewollt, aber groß.** Bei den ersten fünf Ständen sind von 3,3 Millionen Faktzeilen nur gut 870.000 verschiedene Kombinationen aus Tag, Stunde, Station, Linie und Anzahl. Der Rest ist derselbe Plan, nur aus einem anderen Stand. Das liegt an der Aufgabe: Ich will wissen, was jeder Stand für einen Tag gesagt hat, auch wenn es meistens dasselbe ist. Bei einem neuen Stand an vier von fünf Tagen sind das grob 1,5 GB im Monat. Für die Laufzeit dieses Projekts ist das vertretbar. Wird es zu viel, gibt es zwei Wege: einen kürzeren Horizont oder Faktzeilen mit eigenem Gültigkeitszeitraum über Stände hinweg (eine Zeile gilt von Stand a bis Stand b). Der zweite Weg spart fast alles, macht aber jede Abfrage komplizierter. Ich bleibe vorerst beim einfachen Modell.

**Ein Stand, eine Transaktion.** Dimensionen und Fakten eines Stands werden zusammen festgeschrieben. Bricht das Laden der Fakten ab, sind auch die neuen Dimensionsversionen nicht da. Es gibt keinen halb geladenen Stand.

## E14: Fachlicher Schlüssel und Rundung

**stop_id und route_id sind stabil.** Die Aufgabenstellung hielt es für offen, ob der KVV seine IDs zwischen zwei Exporten beibehält. Geprüft mit den ersten fünf Ständen (03. bis 07.11.2026): Keine einzige stop_id und keine route_id ist verschwunden oder hat ihre Bedeutung gewechselt. Die stop_id ist im KVV-Feed die bundesweite Haltestellen-ID (DHID, zum Beispiel `de:08212:89:34:D`), die von der Haltestelle selbst kommt und nicht vom Export. Ich nehme deshalb die IDs aus dem Feed als fachliche Schlüssel und brauche keinen eigenen Schlüssel aus Name und Koordinaten. Sollte sich das ändern, zeigt es sich sofort: Alle Stationen würden in einem Stand geschlossen und neu eingefügt.

**Warum trotzdem ein Surrogatschlüssel.** station_id identifiziert die Haltestelle, aber nicht ihre Version. Eine Faktzeile muss auf "Karlsruhe Hbf, wie er am 5. November hieß" zeigen können. Dafür braucht jede Version einen eigenen Schlüssel. Nebenbei ist eine Ganzzahl als Fremdschlüssel kleiner und schneller als ein Text wie `Pde:08212:89`.

**Körnung der Dimension = Körnung der Fakten.** dim_haltestelle führt Stationen nach E9, keine Bahnsteige. Das hat eine Folge, die ich bewusst in Kauf nehme: Änderungen an einzelnen Bahnsteigen sieht die Dimension nicht. In den ersten fünf Ständen gab es drei solche Änderungen (verschobene Koordinaten bei zwei Ersatzhaltestellen, ein umbenannter Bussteig am Hauptbahnhof), alle unterhalb der Station. Auf Stationsebene kam nur eine Haltestelle neu dazu (Ruit Lerchenweg in Bretten, ab 06.11.2026). Wer Bahnsteige historisieren will, bräuchte eine eigene Dimension. Für meine Fragen reicht die Station.

**Koordinaten auf 5 Nachkommastellen.** Der Feed liefert 8 Nachkommastellen, das ist rund ein Millimeter. Würde ein Export einmal anders runden, gäbe es für jede Station eine neue Version, obwohl sich nichts bewegt hat. Ich runde deshalb vor dem Hashen auf 5 Stellen, in Karlsruhe gut 1 m in Nord-Süd- und 0,7 m in Ost-West-Richtung. Die kleinste echte Verschiebung in den ersten Ständen war eine Ersatzhaltestelle in Schwaigern um etwa 12 m, die bleibt damit sichtbar.

**Hash statt Spaltenvergleich.** Ob sich eine Version geändert hat, vergleiche ich über einen md5-Hash aller fachlichen Attribute. Kommt ein Attribut dazu, ändert sich nur die Hash-Formel, nicht jede Vergleichsbedingung. Fehlende Werte bekommen vor dem Hashen einen festen Platzhalter, sonst wären zwei verschiedene Zeilen mit vertauschtem NULL gleich.

## E15: Fahrten über einen eigenen Schlüssel verbinden, nicht über die trip_id

**Das Problem.** Um zu sagen, dass sich eine Fahrt geändert hat, muss ich wissen, welche Fahrt im neuen Stand dieselbe ist wie im alten. Die naheliegende Antwort wäre die trip_id. Im KVV-Feed ist sie aber eine Planungsnummer mit Version (`1.T0.24-44-E-s26-4.10.R`). Ändert der KVV einen Plan, ersetzt er die Fahrten durch neue mit neuer trip_id, statt die alten zu ändern. In den ersten fünf Ständen sind gemeinsame trip_ids zweier Stände ausnahmslos inhaltsgleich. Über die trip_id verglichen, wäre jede Änderung "entfallen und neu", auch wenn eine Fahrt nur einen Halt mehr hat.

**Der Schlüssel.** Ich verbinde Fahrten über das Fahrtmuster: Linie, Richtung, erste Station und Abfahrt an der ersten Station, auf die Sekunde. Dazu kommt der Betriebstag. Das ist der Fahrtschlüssel. Was sonst an der Fahrt hängt (die übrigen Halte und Zeiten), ist der Inhalt, den ich vergleiche.

**Was der trip_id-Abgleich gemeldet hätte.** dim_standpaar führt zur Kontrolle mit, wie viele trip_ids im Fenster nur im alten bzw. nur im neuen Stand vorkommen. Am 05.11. bekamen 2.742 Fahrten eine neue trip_id, ganz überwiegend bei gleichem Inhalt. Mein Vergleich findet 305 geänderte Fahrt-Instanzen. Am 07.11. ist es umgekehrt: Eine angekündigte Umleitung der Linien 44 und 47 wurde zurückgenommen, indem die schon vorhandenen normalen Fahrten wieder an diesen Tagen fahren. Alle 110 trip_ids dieser Fahrten gab es schon im alten Stand. Ein Abgleich über trip_id sieht dort nichts, obwohl sich für Fahrgäste an 389 Fahrten der Halteverlauf ändert. Er liegt also in beide Richtungen daneben.

**Doppelte Schlüssel.** Je Stand haben rund 1.000 Fahrt-Instanzen (0,3 %) denselben Schlüssel wie eine andere, meist Verstärkerfahrten oder Schulbusse, die zur selben Minute an derselben Station beginnen. Ich nummeriere sie durch (`nr`), sortiert nach Halteverlauf und Zeiten. Solange sich die Fahrten nicht ändern, bekommen sie in beiden Ständen dieselbe Nummer.

**Grenze.** Verschiebt sich die erste Abfahrt selbst, ist es ein anderer Schlüssel. Die Fahrt erscheint dann als "entfallen" und "neu" statt als "zeit". In den ersten vier Standpaaren kam das einmal vor. Ich nehme das in Kauf, weil jeder weichere Schlüssel (zum Beispiel "nächste Fahrt innerhalb von fünf Minuten") falsche Paare bilden kann, und ein falsches Paar ist schwerer zu erkennen als ein ehrliches "entfallen und neu".

**Was als Änderung zählt.**

- Halteverlauf: andere Folge von Stationen (nach E9, ein Gleiswechsel zählt nicht).
- Zeit: gleiche Stationen, mindestens eine Zeit um 60 Sekunden oder mehr verschoben. In den Ständen haben rund 730.000 von 3,1 Millionen Zeiten Sekunden ungleich null, ohne die Schwelle würde eine Rundung als Änderung zählen.
- Betriebstage: das Muster gibt es in beiden Ständen, an einem bestimmten Tag aber nur in einem.
- Neu und entfallen: das Muster gibt es im Fenster nur in einem Stand.

## E16: Vergleichsfenster

**Problem.** Zwei Stände decken nie denselben Zeitraum ab. Der neue fängt später an und hört unter Umständen später auf. Würde ich einfach alles vergleichen, zählte jeder Tag, der vorn herausfällt, als "entfallen" und jeder neue Tag hinten als "neu". Das ist das normale Vorrücken des Fahrplans und keine Änderung.

**Festlegung.** Verglichen werden nur Fahrten, die nach dem Abruf des neuen Stands beginnen (deutsche Zeit, auf die Minute), und nur an Kalendertagen bis zum letzten Tag, den beide Stände abdecken. Was vor dem Abruf lag, konnte der neue Stand nicht mehr ändern. Was nur einer der beiden kennt, ist nicht vergleichbar.

**Nur Nachbarn.** Verglichen wird jeder Stand mit seinem direkten Vorgänger. Was sich über eine Woche ändert, ergibt sich aus der Summe der Tagesvergleiche, ein Vergleich jedes Stands mit jedem brächte nichts Neues und wüchse quadratisch.

**Fehlgeschlagene Abrufe.** Lag zwischen zwei Ständen ein Abruf, der fehlgeschlagen ist, steht das in `fehler_dazwischen`. Die Kurzfristigkeit für dieses Paar ist dann auf mehr als einen Tag ungenau und wird in `v_kurzfristigkeit` so markiert.

**Vorlauf.** Für jede Änderung halte ich fest, wie viele Tage zwischen dem Abruf des neuen Stands (deutsches Datum) und dem Kalendertag der Fahrt liegen. Das ist die frühestmögliche Zeit, zu der jemand mit meinem Archiv die Änderung hätte sehen können. Eine Prüfabfrage meldet jede Änderung mit negativem Vorlauf, die dürfte es nach dem Fenster nicht geben.

## E17: Große Fahrplanwechsel getrennt auswerten

**Problem.** Mitte Dezember wechselt der Fahrplan europaweit. Dann ändern sich auf einen Schlag Tausende Fahrten. Würde dieser eine Tag in die Stabilitätsquote eingehen, wäre jede Linie, die zum Fahrplanwechsel angepasst wird, für Monate "instabil", obwohl sich ein Fahrgast darauf lange vorbereiten konnte.

**Festlegung.** Ein Standpaar gilt als großer Wechsel, wenn sich mindestens 5 % der Fahrten im Fenster ändern (`ist_grosser_wechsel`). Die Sicht `v_stabilitaet_linie_gesamt` gibt die Quote je Linie einmal mit und einmal ohne diese Paare aus. Ich lösche nichts, ich trenne nur.

**Warum 5 %.** In den ersten vier Paaren lag der Anteil zwischen 0 und 0,26 %. Ein normaler Tag mit einer größeren Baustelle bleibt also weit darunter. Ob 5 % zum Fahrplanwechsel passt, zeigt sich am 13.12.2026. Ist die Schwelle zu hoch oder zu niedrig, ändere ich die Konstante `GROSSER_WECHSEL_AB` und lade die Standpaare neu. Weil der Vergleich aus den ZIPs gerechnet wird, geht dabei nichts verloren.

**Neue Fahrten zählen nicht als geändert.** Die Stabilitätsquote ist der Anteil der alten Fahrten, die im neuen Stand unverändert bleiben. Bekommt eine Linie zusätzliche Fahrten, wird sie dadurch nicht instabiler. Neue Fahrten stehen getrennt in `hinzu`.

## E18: Spark für das Archiv, obwohl Pandas heute noch reicht

**Erst gemessen.** Bevor ich etwas umgebaut habe, habe ich die Pandas-Variante über das ganze Archiv gemessen (`analyse/messung.py`). Am 12.11.2026 waren es 8 Stände, 222 MB ZIPs und zusammen 24,7 Millionen Zeilen stop_times. Der Vergleich aller 7 Standpaare dauerte 201 Sekunden, der Arbeitsspeicher lag nie über 2 GB. Dieselbe Arbeit mit Spark im lokalen Modus aus Parquet: 390 Sekunden plus 6 Sekunden für den Start, Spitze 5,7 GB (Python und Java-VM zusammen, gemessen auf 4 Kernen und 15 GB).

**Das ehrliche Ergebnis: Pandas reicht.** Der Vergleich arbeitet paarweise. Es liegen nie mehr als zwei Stände im Speicher, egal wie groß das Archiv wird. Ein Paar braucht mit Pandas rund 25 Sekunden und 2 GB, heute wie in einem Jahr. Das Archiv wächst, die Arbeit je Schritt nicht. Spark ist auf einem Rechner sogar langsamer, weil es für viele Rechner gebaut ist: Es plant, verteilt auf Partitionen, sortiert für jedes Fenster und schickt Daten zwischen Python und Java hin und her. Bei 3 Millionen Zeilen je Stand kostet das mehr, als die Verteilung auf vier Kerne bringt.

**Warum Spark trotzdem.** Aus zwei Gründen, beide vorbereitend und nicht "weil es schneller ist":

- *Abfragen über alle Stände auf einmal.* Pandas kann nur Stand für Stand. Die Frage "In wie vielen Ständen kommt jede trip_id vor?" ist mit Spark eine Abfrage über `data/parquet/trips` (3 Sekunden), mit Pandas eine Schleife über alle ZIPs. Solche Fragen werden mit dem Archiv mehr, nicht weniger.
- *Ganz Baden-Württemberg.* MobiData BW bietet die Soll-Fahrplandaten für das ganze Land als GTFS an. Damit läge ein einzelner Stand um ein Vielfaches über dem KVV, und ein Paar passt irgendwann nicht mehr in den Speicher eines Laptops. Dann zahlt sich aus, dass derselbe Code auf einem Cluster laufen kann. Achtung bei diesem Schritt: Der landesweite Datensatz steht laut MobiData BW unter der Open Database License (ODbL), nicht unter CC0 wie der KVV-Feed. Die ODbL verlangt Namensnennung, und eine abgeleitete Datenbank, die ich weitergebe, muss wieder unter der ODbL stehen. Ein öffentliches Archiv der Landesdaten wäre also eine eigene Lizenzfrage.

**Lokal, kein Cluster.** Spark läuft mit `local[*]` in einem Container. Treiber und Executor sind ein Prozess, sein Speicher (`spark.driver.memory`, Standard 4 GB, einstellbar über `KVV_SPARK_SPEICHER`) ist der ganze Spark-Speicher. Nach jedem Join teilt Spark standardmäßig in 200 Teile, ich nehme 16, weil 200 Häppchen bei dieser Datenmenge mehr Verwaltung als Arbeit sind.

**Image und Versionen.** Offizielles Image `apache/spark:4.2.1-scala2.13-java21-python3-ubuntu`. 4.3.0 war beim Bau gerade eine Woche alt, für ein Projekt, das funktionieren soll, nehme ich die Version davor. Java ist im Image, auf dem Windows-Rechner muss nichts installiert werden. Das Image bringt Python 3.10 mit, pandas 3 braucht aber 3.11. Im Container läuft deshalb pandas 2.3.3. Alle Pandas-Tests laufen mit beiden Versionen grün. Der JDBC-Treiber für PostgreSQL (42.7.14) wird beim Bauen in `/opt/spark/jars` gelegt, damit Spark ohne Internetzugriff zur Laufzeit auskommt.

**Parquet als Zwischenformat.** Die CSVs im ZIP haben keine Typen, keine Kompression je Spalte und lassen sich nicht in Teilen lesen. Parquet speichert spaltenweise mit Typen. Wer nur `trip_id` braucht, liest nur diese Spalte. Die 8 Stände sind als Parquet 157 MB statt 222 MB ZIP, obwohl ZIP ebenfalls komprimiert. Abgelegt wird nach der Vorgabe `data/parquet/<datei>/stand=<id>/`. An diesem Ordnernamen erkennt Spark die Partition und liefert beim Lesen des ganzen Ordners die Spalte `stand` mit.

**Eine Datei je Stand und Tabelle.** Spark schreibt sonst je Partition eine Datei. Bei 16 Partitionen und 12 Tabellen wären das bei 8 Ständen über 1.500 kleine Dateien, die jede für sich geöffnet werden müssen. Ein Stand ist klein genug für eine Datei.

**Idempotenz über `_SUCCESS`, nicht über MongoDB.** Spark legt `_SUCCESS` erst an, wenn alle Dateien einer Tabelle geschrieben sind. Fehlt die Datei, war der Lauf unvollständig, und die Tabelle wird überschrieben. Das Feld `verarbeitet_am` in MongoDB (E7) habe ich bewusst nicht genommen: Es hieße, dass Parquet nur entsteht, wenn MongoDB läuft, und dass beide auseinanderlaufen können, wenn jemand `data/parquet` löscht. So gilt: Was auf der Platte liegt, ist die Wahrheit.

**CSV lesen wie Pandas.** Zwei Unterschiede musste ich ausgleichen. Pandas liest leere Felder bei mir als leeren Text (`keep_default_na=False`), Spark als NULL. In allen Tabellen außer stop_times ersetze ich NULL deshalb durch `""`. In stop_times werden `stop_sequence`, `pickup_type` und `drop_off_type` zu Zahlen, und dort bleibt NULL erhalten, weil "keine Angabe" bei pickup_type etwas anderes ist als 0.

**Zeiten über 24 Uhr.** Wie in Phase 2: Sekunden seit Beginn des Betriebstags, nie Zeitstempel. Die Sitzung läuft zusätzlich in UTC, damit Spark beim Umwandeln von Daten keine Zeitzone des Rechners einrechnet.

**Ins selbe Sternschema, über Staging.** Spark schreibt die Ergebnisse über JDBC in die Staging-Tabellen aus Phase 4. Die Fakten entstehen danach in einer einzigen Transaktion durch dieselbe Prozedur `lade_aenderung()`. Würde Spark direkt in die Faktentabellen schreiben, wäre jede Partition eine eigene Transaktion, und ein Abbruch hinterließe ein halbes Standpaar.

**Gleichheit beweisen, nicht annehmen.** `spark/vergleich.py` rechnet drei Standpaare (zusammen jede Änderungsart) mit beiden Varianten und vergleicht die Ergebnisse Zeile für Zeile, ohne Rundung und Toleranz. Dazu die Abfahrten je Stunde eines Stands. `tests/test_spark.py` macht dasselbe auf den Mini-Ständen aus den Tests. Am Ende habe ich beide Varianten in die Datenbank geladen und die Fakten je Standpaar über einen md5-Hash verglichen: identisch.

**Was der Vergleich an Pandas gefunden hat.** Beim Übersetzen sind zwei Schwächen der Phase-4-Logik aufgefallen, die ich in `analyse/diff.py` behoben habe:

- *Gleichstand bei der Nummerierung (E15).* Haben zwei Fahrten denselben Schlüssel und denselben Inhalt, entschied bisher die zufällige Reihenfolge der Zeilen, welche `nr` 0 und welche 1 bekommt. Das betraf rund 50 Fahrten je Stand. Am Ergebnis änderte es nichts, weil beide Fahrten gleich sind, aber die trip_id an der Änderung hätte je nach Lauf wechseln können. Jetzt entscheidet bei Gleichstand die trip_id.
- *Betroffene Haltestellen.* Hatte dasselbe Fahrtmuster an verschiedenen Tagen verschiedene Änderungen, kam nur die erste in `fakt_aenderung_halt`. Am 05.11. fehlten dadurch 55, am 06.11. 106 Haltestellen. Jetzt ist es die Vereinigung über alle Tage. Die Standpaare aus Phase 4 müssen deshalb einmal neu geladen werden (`--alle-neu`).

Beides hätte ich ohne die Pflicht, ein exakt gleiches Ergebnis zu zeigen, nicht bemerkt.
