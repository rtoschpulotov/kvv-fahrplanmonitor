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

[Offen. Drei Haltestellen, die ich persönlich kenne, für einen Stichtag mit kvv.de vergleichen und Abweichungen hier eintragen.]

### Fünf Fahrten von Hand (Aufgabe A5)

[Offen. Fünf zufällige trip_id mit Linie, Haltestellenfolge und Uhrzeiten nachvollziehen.]

## Stichtage für die erste Auswertung

Vorschlag, noch zu bestätigen:

| Tagestyp | Datum | Fahrten |
|---|---|---:|
| Werktag | Di 10.11.2026 | 11.311 |
| Samstag | Sa 14.11.2026 | 6.972 |
| Sonntag | So 15.11.2026 | 4.881 |

Begründung: kein Feiertag, keine Schulferien, weit weg von der Zeitumstellung am 25.10.2026 (E8), und alle drei liegen nach dem Abruf des Stands. Es wird also der Plan ausgewertet, den der KVV zu diesem Zeitpunkt für die Zukunft veröffentlicht hat.

Am Di 10.11.2026 gibt es 163.037 Abfahrten nach Kalenderzeit. 3.228 davon gehören noch zum Betriebstag 09.11., fahren also nach Mitternacht. Ohne die Umrechnung würden sie dem falschen Tag zugeschlagen.
