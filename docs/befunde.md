# Befunde

Was ich im KVV-Feed gefunden habe, bevor ich damit rechne. Alle Zahlen stammen aus dem Stand vom **2026-11-04T12:08:17Z** (`feed_version` 20261103) und lassen sich mit `make profil STAND=...` nachmessen.

## Profil des Stands

### Zeilen je Datei

| Datei | Zeilen |
|---|---:|
| agency.txt | 21 |
| calendar.txt | 2.591 |
| calendar_dates.txt | 24.260 |
| feed_info.txt | 1 |
| notes.txt | 67 |
| routes.txt | 287 |
| stop_times.txt | 3.033.673 |
| stops.txt | 5.930 |
| ticketing_deep_links.txt | 22 |
| ticketing_identifiers.txt | 5.936 |
| transfers.txt | 56.552 |
| trips.txt | 147.492 |

### Zeitraum

`feed_info` und `calendar` sagen dasselbe: **14.06.2026 bis 12.12.2026**. Der Stand deckt also nicht ein Jahr ab, sondern ein Fahrplanhalbjahr. Am 13.12.2026 beginnt erfahrungsgemäß der neue Jahresfahrplan, den muss ein späterer Stand liefern.

### service_id und Ausnahmen

- 2.591 service_id in `calendar`, 1.629 davon haben zusätzlich Einträge in `calendar_dates`.
- Keine service_id kommt nur in `calendar_dates` vor, und jede service_id aus `trips` ist in `calendar` definiert.
- 24.226 Ausnahmen vom Typ 2 (Tag fällt weg), nur 34 vom Typ 1 (Tag kommt dazu).

**Folgerung (Aufgabe A4):** Der KVV kombiniert beide Dateien. `calendar` gibt den Rahmen vor, `calendar_dates` streicht fast ausschließlich Tage heraus. Ich brauche also die volle Regel aus E6. Dass es im Moment keine Dienste nur über `calendar_dates` gibt, ist eine Beobachtung für diesen einen Stand und kein Versprechen. Die Funktion fängt den Fall trotzdem ab, und ein Test prüft es.

### Linien je Verkehrsmittel

| route_type | Bedeutung | Linien |
|---|---|---:|
| 3 | Bus | 252 |
| 2 | Eisenbahn (S-Bahn, Regionalverkehr) | 21 |
| 0 | Straßen- und Stadtbahn | 14 |

### Haltestellen

- 4.261 Halte (Bahnsteige, Haltepositionen), davon 3.852 mit `parent_station` (90,4 %).
- 1.669 Einträge sind selbst Stationen (`location_type` 1).
- Jede angegebene `parent_station` existiert auch als Eintrag.
- Nach E9 (Station statt Bahnsteig) bleiben **2.078 Haltestellen**: 1.669 Stationen plus 409 Halte ohne übergeordnete Station.

### Uhrzeiten über 24 Uhr (Aufgabe A3)

- 187.630 Halte haben eine Abfahrtszeit ab 24:00:00. Das betrifft 10.337 Fahrten.
- Die späteste Zeit ist **29:25:00**, also 05:25 Uhr am Folgetag, aber noch zum vorherigen Betriebstag gehörend.
- Genau ein Halt hat gar keine Uhrzeit (Fahrt `431.T0.24-24-E-s26-9.45.H`, stop_sequence 2). Er zählt nicht als Abfahrt.

### Einstiegsarten

| pickup_type | Bedeutung | Halte |
|---|---|---:|
| 0 | regulärer Einstieg | 2.953.906 |
| 1 | kein Einstieg | 42.949 |
| 2 | Einstieg nach telefonischer Anmeldung | 36.818 |

Typ 2 sind Rufbus- und Anrufsammeltaxi-Fahrten. Wie ich sie zähle, steht in E9.

Der letzte Halt einer Fahrt hat fast immer `pickup_type` 0 (142.457 von 147.492 Fahrten). Ich kann mich also nicht darauf verlassen, dass der Feed das Fahrtende als "kein Einstieg" markiert, und muss den letzten Halt selbst ausschließen.

## Prüfung der Auflösung

### Feiertag gegen Werktag (Aufgabe C2)

Im Gültigkeitszeitraum liegen zwei gesetzliche Feiertage in Baden-Württemberg, beide leider am Wochenende:

| Tag | Fahrten | Vergleich |
|---|---:|---|
| Sa 03.10.2026, Tag der Deutschen Einheit | 5.103 | normale Samstage im Oktober: 7.002 bis 7.381 |
| So 04.10.2026 | 4.942 | normaler Sonntag |
| So 01.11.2026, Allerheiligen | 5.114 | normale Sonntage: 4.916 bis 5.270 |

Der 3. Oktober liegt mit 5.103 Fahrten fast genau auf Sonntagsniveau und 27 % unter einem normalen Samstag. Das passt zu einem Sonntagsfahrplan am Feiertag, und die Ausnahmen vom Typ 2 greifen also. Allerheiligen fällt ohnehin auf einen Sonntag und ist deshalb als Prüffall wenig aussagekräftig.

Außerdem sichtbar, ohne dass ich danach gesucht habe:

- **Sommerferien:** Werktage ab Do 30.07. haben rund 10.700 statt 11.300 Fahrten, ab Mo 14.09. wieder das alte Niveau.
- **Herbstferien:** Mo 26.10. bis Fr 30.10. rund 10.650 Fahrten statt 11.350.

Die Schulferien selbst stehen nicht im Feed, aber die wegfallenden Schulbusse sind deutlich zu sehen. [Ferientermine noch mit dem Kultusministerium Baden-Württemberg abgleichen.]

### Abgleich mit der KVV-Fahrplanauskunft (Aufgabe C3)

Am 06.11.2026 habe ich für Dienstag, 10.11.2026, ab 07:00 Uhr den Abfahrtsmonitor auf kvv.de abgerufen und Zeile für Zeile mit meinen Abfahrten aus dem Stand vom 04.11.2026 verglichen (`python analyse/nachschlagen.py tafel`). Zwei Haltestellen kenne ich persönlich, die dritte habe ich wegen der Lücke bei den DB-Zügen gewählt.

| Haltestelle | Zeitfenster | Feed | kvv.de | Ergebnis |
|---|---|---:|---:|---|
| Oberreut Badeniaplatz | 07:00 bis 08:59 | 18 | 18 | alle Abfahrten identisch, Uhrzeit, Linie und Richtung |
| Karlsruhe Yorckstraße | 07:00 bis 07:29 | 35 | 35 | alle Abfahrten identisch, Uhrzeit und Linie |
| Graben-Neudorf | 07:00 bis 08:59 | 14 | 32 | alle 14 Busse identisch, 18 Züge fehlen im Feed |

**Wo der Feed vollständig ist, stimmt er auf die Minute.** Auch die baustellenbedingten Umleitungen (Linie 4 mit "SEV ab Hirtenweg", Linie 2 nach Knielingen Nord) stehen in beiden gleich. Das spricht dafür, dass meine Betriebstag-Logik und die Umrechnung auf Kalenderzeit richtig arbeiten.

**In Graben-Neudorf fehlen mehr als die Hälfte der Abfahrten.** Zwischen 7 und 9 Uhr fahren dort laut kvv.de 15 S-Bahnen (S33, S6, S9) und 3 Regionalexpresse (RE4). Keiner dieser Züge steht im KVV-Feed, und den Bahnhof selbst gibt es dort nicht als Haltestelle. Die Lücke aus E11 ist damit belegt und beziffert: In diesem Fenster sind es 18 von 32 Abfahrten, also 56 %. Für Gemeinden an DB-Strecken unterschätzt meine Auswertung das Angebot deutlich.

Die gespeicherten Seiten von kvv.de liegen nicht im Repo, weil es fremde Inhalte sind. Ich habe sie lokal aufbewahrt.

### Fünf Fahrten von Hand (Aufgabe A5)

Fünf zufällige Fahrten, je eine Linie, die am Di 10.11.2026 fahren, gezogen mit `python analyse/nachschlagen.py zufall` (fester Startwert):

| Linie | Strecke | Auffällig |
|---|---|---|
| 55 | Kühler Krug bis Hauptbahnhof | Kühler Krug dreimal hintereinander, einmal ohne Einstieg |
| 103s | Malsch Hans-Thoma-Schule bis Waldprechtsweier | keine Richtungsangabe |
| S5 | Wörth Badepark bis Pforzheim Hbf | gilt nur vom 03.11. bis 10.11.2026, Lücke in der stop_sequence |
| 70 | Heidehof bis Entenfang | Heidehof zweimal, einmal ohne Einstieg |
| 125s | Spöck bis Bruchsal | Spöck Richard-Hecht-Schule zweimal hintereinander |

**Folge für die Auswertung:** Drei von fünf Fahrten halten mehrmals direkt hintereinander an derselben Station. Mein Code hatte das als mehrere Abfahrten gezählt. Seit der Korrektur (E9) zählt eine solche Folge einmal. Im ganzen Feed betraf das gut 55.000 Zeilen, am Dienstag 10.11. waren es 1.247 Abfahrten zu viel. Die Lücke in der stop_sequence bei der S5 ist erlaubt, GTFS verlangt nur eine aufsteigende Reihenfolge.

Was ich aus den fünf Fahrten mitnehme:

- **Linie 55, Kühler Krug:** Die drei Halte sind die Bussteige A, C und B. Der Bus startet an A, fährt durch die Wendeanlage an C vorbei (dort kein Einstieg) und fährt an B ab. Für Fahrgäste ist das eine Abfahrt.
- **103s und 125s:** Die 125s fährt nie am Wochenende und fällt in den Sommerferien und in den Herbstferien (26. bis 30.10.2026) aus. Das "s" steht deshalb sehr wahrscheinlich für Schülerverkehr. Ungeklärt ist, warum sie auch vom 13. bis 29.07.2026 fehlt, also vor Beginn der Sommerferien.
- **S5 mit einer Woche Gültigkeit:** Der KVV bildet Baustellen über eigene, kurze Fahrplanvarianten ab. Für die S5 gibt es mehrere solcher Pakete. Das passt zum Hinweis "Bauarbeiten im VBK-Netz (Phase 5)" auf kvv.de. Für Phase 4 heißt das: Viele Änderungen zwischen zwei Ständen werden Baustellen sein, nicht dauerhafte Fahrplanänderungen.
- **Linie 70:** Die Fahrzeit von 16 Minuten zwischen Heidehof und Entenfang kann ich aus eigener Ortskenntnis nicht beurteilen.

## Takt und Wartezeit

Mit `analyse/bedienqualitaet.py`, Kennzahlen nach E10.

| Stichtag | Abfahrten | Stationen mit Abfahrt | Erwartete Wartezeit 6 bis 20 Uhr (Median über Station und Stunde) |
|---|---:|---:|---:|
| Di 10.11.2026 | 161.790 | 1.961 | 10,2 min |
| Sa 14.11.2026 | 107.311 | 1.577 | 15,0 min |
| So 15.11.2026 | 79.582 | 1.357 | 15,0 min |

Alle 2.078 Stationen kommen irgendwann im Fahrplanhalbjahr vor. Am Stichtag-Dienstag fährt an 117 von ihnen gar nichts ab, am Sonntag an 721.

**Gleiche Zahl, anderer Takt:** 166 Stationen haben am Dienstag zwischen 8 und 9 Uhr genau sechs Abfahrten. Bei Neureut-Heide oder Knielingen Nord kommen sie im 10-Minuten-Takt (erwartete Wartezeit 5,0 Minuten). In Kürnbach Flehinger Straße liegen sie so ungleich, dass man im Schnitt 18,1 Minuten wartet und die längste Lücke 26 Minuten dauert. Die reine Zahl der Abfahrten hätte beide gleich bewertet.

## Gemeinden

Zuordnung nach E11 mit der VG250-EW (Stand 31.12.2025).

- 2.065 von 2.078 Stationen liegen in einer deutschen Gemeinde. Die übrigen 13 liegen im Elsass.
- Im Kerngebiet (vier Kreise, 57 Gemeinden, 1.052.186 Einwohner) liegen 1.768 Stationen. Jede der 57 Gemeinden hat mindestens eine.

### Abfahrten je 1.000 Einwohner, Di 10.11.2026

| | Gemeinde | Einwohner | Abfahrten | je 1.000 EW |
|---|---|---:|---:|---:|
| meiste | Baden-Baden | 56.952 | 13.184 | 231,5 |
| | Karlsruhe | 309.247 | 65.740 | 212,6 |
| | Ettlingen | 38.557 | 7.418 | 192,4 |
| wenigste | Muggensturm | 6.103 | 58 | 9,5 |
| | Ötigheim | 5.004 | 75 | 15,0 |
| | Bietigheim | 6.473 | 138 | 21,3 |

Das untere Ende ist nicht so eindeutig, wie es aussieht:

- **Ötigheim und Bietigheim** haben je 34 Abfahrten der S7 und S8 am Tag, dazu Busse. Das ist wenig im Verhältnis zur Einwohnerzahl, aber plausibel.
- **Muggensturm** hat nur 6 Abfahrten der S71 und S81 und dazu Busse mit dem Namen "SEV S7/S71". SEV heißt Schienenersatzverkehr. Vermutlich ist die Strecke am Stichtag wegen einer Baustelle gesperrt oder eingeschränkt. Dann wäre der Wert eine Momentaufnahme und kein Dauerzustand. [Mit der Fahrplanauskunft und den Baustellenmeldungen des KVV prüfen.]
- **Bad Schönborn (38,5) und Philippsburg (41,6)** haben im Feed gar keine Zugabfahrt. Beide liegen nach meinem Kenntnisstand an Strecken der S-Bahn Rhein-Neckar, die die DB fährt (E11).

22 der 57 Gemeinden im Kerngebiet haben im Feed keine einzige Abfahrt einer Bahn. Bei manchen stimmt das einfach, Bühlertal oder Loffenau haben keinen Bahnanschluss. Bei anderen wie Graben-Neudorf, Waghäusel oder Karlsdorf-Neuthard fehlen die DB-Züge im Datensatz.

### Ohne Abfahrt nach 20 Uhr

Am Werktag gibt es im Kerngebiet nur eine Gemeinde ohne Abfahrt zwischen 20 und 4 Uhr: **Graben-Neudorf**, letzte Abfahrt 19:40. Am Sonntag sind es acht: Philippsburg, Bad Schönborn, Graben-Neudorf, Oberhausen-Rheinhausen, Dettenheim, Kronau, Au am Rhein und Steinmauern. Sieben davon haben am Sonntag im KVV-Feed überhaupt keine Abfahrt, nur Bad Schönborn hat welche bis 19:15.

Bis auf Steinmauern und Au am Rhein liegen alle in der Hardt nördlich von Karlsruhe. Für Graben-Neudorf ist das sicher ein Datenbefund und kein Ortsbefund: Laut kvv.de fahren dort zwischen 7 und 9 Uhr 18 Züge, die im Feed fehlen (siehe Abgleich oben). [Für die übrigen Gemeinden beim Abgleich klären, ob sonntags DB-Züge oder Rufbusse anderer Anbieter fahren.]

## Stichtage für die erste Auswertung

Vorschlag, noch zu bestätigen:

| Tagestyp | Datum | Fahrten |
|---|---|---:|
| Werktag | Di 10.11.2026 | 11.311 |
| Samstag | Sa 14.11.2026 | 6.972 |
| Sonntag | So 15.11.2026 | 4.881 |

Begründung: kein Feiertag, keine Schulferien, weit weg von der Zeitumstellung am 25.10.2026 (E8), und alle drei liegen nach dem Abruf des Stands. Es wird also der Plan ausgewertet, den der KVV zu diesem Zeitpunkt für die Zukunft veröffentlicht hat.

Am Di 10.11.2026 gibt es 161.790 Abfahrten nach Kalenderzeit. 3.192 davon gehören noch zum Betriebstag 09.11., fahren also nach Mitternacht. Ohne die Umrechnung würden sie dem falschen Tag zugeschlagen.

## Phase 3: Fünf Stände im Sternschema

Geladen sind die fünf Stände mit Status "neu" vom 03. bis 07.11.2026 (am 05., 06. und 07.11. lief das Sammeln zusätzlich abends, ohne Änderung). Alle vier Prüfabfragen sind leer.

### Sind die Schlüssel stabil?

Ja. Zwischen je zwei aufeinanderfolgenden Ständen ist keine stop_id und keine route_id verschwunden. Was sich geändert hat:

| Stand | Ebene | Änderung |
|---|---|---|
| 05.11. | Bahnsteig | Memprechtshofen B36, Bussteig um rund 12 m verschoben |
| 06.11. | Station | Ruit Lerchenweg (Bretten) neu, mit einem Bussteig |
| 06.11. | Bahnsteig | Schwaigern Heilbronner Str. (Ersatz) um rund 12 m verschoben |
| 07.11. | Bahnsteig | Schwaigern wieder auf der alten Koordinate, also A, B, wieder A |
| 07.11. | Bahnsteig | `de:08212:89:34:D` umbenannt von "KA Hauptbahnhof (Vorplatz)" in "Karlsruhe Hauptbahnhof (Vorplatz)" |

Linien, Betreiber und Linienfarben sind in allen fünf Ständen gleich. Die Umbenennung am Hauptbahnhof betrifft nur einen Bussteig. Die Station darüber heißt weiterhin "KA Hauptbahnhof (Vorplatz)", der Feed ist an dieser Stelle jetzt uneinheitlich.

Die Dimensionen haben deshalb nach fünf Ständen 2.079 Haltestellen- und 287 Linienversionen, alle aktuell. Die einzige neue Version ist Ruit Lerchenweg. Dass es nicht mehr sind, ist ein echter Befund und kein Fehler: Die übrigen Änderungen liegen unterhalb der Station (E14). Die Fälle "geändert", "verschwunden" und "Wiederkehr" sind mit eigenen Testdaten geprüft (`tests/test_scd2.py`), bis der echte Feed sie liefert.

### Derselbe Tag in fünf Ständen

Abfahrten am Di 10.11.2026 laut jedem Stand:

| Stand | Abfahrten |
|---|---:|
| 03.11. | 161.790 |
| 04.11. | 161.790 |
| 05.11. | 161.790 |
| 06.11. | 161.804 |
| 07.11. | 161.804 |

Die 161.790 sind dieselbe Zahl wie in Phase 2 (Stichtage oben), dort direkt mit Pandas gerechnet. Der Weg über Postgres verliert also nichts. Am 06.11. kamen für diesen Dienstag 14 Abfahrten dazu, alle auf der Linie SEV S7/S71 in der Stunde ab 5 Uhr an acht Stationen zwischen Rastatt und Bühl. Der KVV hat also frühe Ersatzbusfahrten nachgetragen. Genau diese Art Änderung soll Phase 4 systematisch finden.

### Größe

Ein Stand mit 14 Tagen Horizont sind rund 663.000 Faktzeilen und gut 60 MB (E13). Laden dauert je Stand etwa 45 Sekunden, fast alles davon ist die Abfahrten-Logik aus Phase 2.

## Phase 4: Änderungen zwischen den Ständen

Verglichen sind die vier Paare aus den fünf Ständen vom 03. bis 07.11.2026. Alle sechs Prüfabfragen (vier aus Phase 3, zwei neue) sind leer. Die Zahlen sind vorläufig, weil vier Paare für Aussagen über Linien und Wochentage nicht reichen.

### Überblick

| Paar | Fahrten im Fenster (alt) | Änderungen | davon geändert | Anteil | trip_ids nur alt | trip_ids nur neu |
|---|---:|---:|---:|---:|---:|---:|
| 03.11. → 04.11. | 372.559 | 0 | 0 | 0,00 % | 0 | 0 |
| 04.11. → 05.11. | 360.925 | 305 | 173 | 0,05 % | 73 | 2.742 |
| 05.11. → 06.11. | 349.694 | 1.083 | 918 | 0,26 % | 70 | 186 |
| 06.11. → 07.11. | 341.503 | 497 | 419 | 0,12 % | 319 | 48 |

"Änderungen" zählt alle Zeilen in `fakt_aenderung`, also auch neue Fahrten und Tage, die dazukommen. "Davon geändert" zählt nur alte Fahrten, die nicht mehr so fahren wie vorher (E17). Die trip_id-Spalten zählen verschiedene trip_ids, keine Instanzen.

**03.11. → 04.11. ohne Änderung.** Der Inhalts-Hash unterscheidet sich, die Fahrten nicht. Geändert waren nur Felder ohne Bedeutung für Fahrgäste, unter anderem `block_id`. Das ist die Gegenprobe aus der Aufgabe, im echten Archiv: zwei Stände, die sich unterscheiden, und null Änderungen im Fahrplan.

### Was sich geändert hat

| Paar | Was | Wo |
|---|---|---|
| 04.11. → 05.11. | Umplanung der S41, S42, S31 und S8 vom 11. bis 21.11., verteilt auf alle Arten | Kraichgau und Neckartal (Bad Wimpfen, Bad Rappenau, Bad Friedrichshall) |
| 04.11. → 05.11. | 23 neue Ersatzbusfahrten SEV S31/S32 am 22. und 23.11. | |
| 05.11. → 06.11. | Linie 164 fährt ab 16.11. über die neue Station Ruit Lerchenweg, 871 Fahrten mit anderem Halteverlauf | Bretten |
| 05.11. → 06.11. | 114 neue Fahrten der Linie M am Wochenende 14./15.11. | |
| 05.11. → 06.11. | zwei frühe SEV S7/S71 am 10.11. um 5:05 und 5:18 | Rastatt bis Bühl |
| 06.11. → 07.11. | Umleitung der Linien 44 und 47 ab 30.11. zurückgenommen, 389 Fahrten wieder mit dem normalen Halteverlauf | Karlsruhe |
| 06.11. → 07.11. | 48 neue Ersatzbusfahrten SEV S41/S42 vom 11. bis 16.11. | |

Die zwei SEV-Fahrten am 10.11. sind dieselben 14 Abfahrten, die in Phase 3 beim Vergleich der Faktentabelle aufgefallen waren (zwei Fahrten mit je sieben Abfahrten, am letzten Halt nur Ankunft). Zwei unabhängige Wege, ein Ergebnis.

### trip_id gegen Fahrtschlüssel

Am 05.11. bekamen 2.742 Fahrten eine neue trip_id. Echte Änderungen gab es 305, der Rest war neu nummeriert. Am 07.11. ist es umgekehrt: Alle 110 trip_ids, mit denen die Linien 44 und 47 wieder normal fahren, gab es schon im alten Stand, sie fuhren dort nur an anderen Tagen. Ein Abgleich über trip_id hätte die 389 Änderungen nicht gesehen. Begründung des eigenen Schlüssels in E15.

### Kurzfristigkeit

| Vorlauf | Änderungen |
|---|---:|
| am selben Tag | 0 |
| am Vortag | 0 |
| 2 bis 7 Tage | 37 |
| 8 bis 14 Tage | 576 |
| 15 bis 28 Tage | 792 |
| mehr als 28 Tage | 480 |

Kein Abruf ist bisher fehlgeschlagen, die Messung ist also auf einen Tag genau.

### Was sonst auffiel

- **Doppelte Schlüssel.** Je Stand rund 1.000 Fahrt-Instanzen (0,3 %) mit gleichem Schlüssel, aufgelöst über eine laufende Nummer (E15).
- **Sekunden.** Rund 730.000 von 3,1 Millionen Zeiten haben Sekunden ungleich null. Die Schwelle von 60 Sekunden ist deshalb nötig. Es gab bisher nur drei echte Zeitänderungen, alle am 05.11.
- **Erste Abfahrt verschoben.** Einmal erschien eine Fahrt als "entfallen" und "neu", weil sich ihre erste Abfahrt verschoben hatte. Das ist die bekannte Grenze des Schlüssels (E15).
- **Umpacken.** Bisher hat der KVV die ZIP nie neu gepackt, ohne dass sich der Inhalt geändert hat. Von neun erfolgreichen Abrufen hatten vier neuen Inhalt, fünf waren unverändert.
- **Laufzeit.** Je Standpaar etwa 20 Sekunden, fast alles davon ist Einlesen und Auflösen der Betriebstage.
