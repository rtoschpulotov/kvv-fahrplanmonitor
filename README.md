# KVV-Fahrplanmonitor

*Entwurf, Stand Phase 0. Wird mit jeder Phase weitergeschrieben.*

## Worum es geht

Der Karlsruher Verkehrsverbund veröffentlicht seinen Soll-Fahrplan als GTFS-Datei und aktualisiert sie laut MobiData BW nahezu täglich. Alte Stände hält der KVV nicht vor. Ich lade deshalb seit dem [Startdatum eintragen] jeden Tag den aktuellen Stand herunter und baue daraus ein eigenes Archiv auf. Diesen Datensatz gibt es sonst nirgends.

Zwei Fragen stehen im Mittelpunkt:

1. **Bedienqualität:** Wie gut ist welcher Ort im KVV-Gebiet angebunden, nach Stunde und Wochentag? Wo endet der Takt abends oder am Sonntag?
2. **Fahrplanstabilität:** Was ändert sich von Stand zu Stand, bei welchen Linien und Haltestellen am häufigsten, und wann?

Technisch zeigt das Projekt vor allem eines: wie man Daten, die sich über die Zeit ändern, sauber historisiert (Slowly Changing Dimensions Typ 2). Der ÖPNV ist der Anwendungsfall, die Methode ist übertragbar.

## Stand

| Phase | Inhalt | Status |
|---|---|---|
| 0 | Sammelskript, täglicher Abruf mit Hash | läuft seit [Startdatum] |
| 1 | Repo-Gerüst, Docker Compose, README-Entwurf | in Arbeit |
| 2 | GTFS einlesen, Betriebstage auflösen, Bedienqualität | offen |
| 3 | PostgreSQL-Modell mit SCD2-Dimensionen | offen |
| 4 | Diff-Logik zwischen Ständen, Fahrplanstabilität | offen |
| 5 | PySpark für das wachsende Archiv | offen |
| 6 | Power-BI-Dashboard | offen |

## Wie das Sammeln funktioniert

`sammler/sammle_snapshot.py` lädt die ZIP von `projekte.kvv-efa.de/GTFS/google_transit.zip`, prüft, ob alle nötigen GTFS-Dateien drin sind, und berechnet zwei Hashes:

- den **ZIP-Hash** über die Datei als Ganzes,
- den **Inhalts-Hash** über die einzelnen GTFS-Dateien.

Ob ein Stand neu ist, entscheide ich am Inhalts-Hash. Wird die ZIP nur neu gepackt, ändert sich der ZIP-Hash, der Fahrplan aber nicht. Das würde sonst als Änderung zählen und die Stabilitätsauswertung verfälschen.

Jeder Lauf schreibt eine Zeile in `data/snapshot_register.csv`, mit Status `neu`, `unveraendert` oder `fehler`. Auch Tage ohne Änderung sind damit belegt.

Der Abruf läuft täglich über GitHub Actions (`.github/workflows/sammeln.yml`). Neue Stände hängen als Release an diesem Repo, damit der Git-Verlauf klein bleibt.

Lokal geht es genauso:

```bash
pip install -r requirements.txt
python sammler/sammle_snapshot.py
```

## Projektstruktur

```
sammler/        Sammelskript
data/raw/       heruntergeladene Stände (nicht im Git, liegen in den Releases)
data/           Snapshot-Register
sql/            Schema und Abfragen für PostgreSQL (ab Phase 3)
spark/          PySpark-Jobs (ab Phase 5)
analyse/        Notebooks und Auswertungen
docs/           Entscheidungsprotokoll
```

## Daten und Lizenz

Fahrplandaten: Karlsruher Verkehrsverbund, bereitgestellt über MobiData BW, Lizenz **CC0**. Es besteht keine Pflicht zur Namensnennung, ich nenne die Quelle trotzdem.

Code: [Lizenz festlegen, z. B. MIT]

## Entscheidungen

Warum ich etwas so gelöst habe und nicht anders, steht in [docs/entscheidungen.md](docs/entscheidungen.md).
