# KVV-Fahrplanmonitor

*Entwurf, Stand Phase 0. Wird mit jeder Phase weitergeschrieben.*

## Worum es geht

Der Karlsruher Verkehrsverbund veröffentlicht seinen Soll-Fahrplan als GTFS-Datei und aktualisiert sie laut MobiData BW nahezu täglich. Alte Stände hält der KVV nicht vor. Ich lade deshalb seit dem 2026-11-03 jeden Tag den aktuellen Stand herunter und baue daraus ein eigenes Archiv auf. Diesen Datensatz gibt es sonst nirgends.

Zwei Fragen stehen im Mittelpunkt:

1. **Bedienqualität:** Wie gut ist welcher Ort im KVV-Gebiet angebunden, nach Stunde und Wochentag? Wo endet der Takt abends oder am Sonntag?
2. **Fahrplanstabilität:** Was ändert sich von Stand zu Stand, bei welchen Linien und Haltestellen am häufigsten, und wann?

Technisch zeigt das Projekt vor allem eines: wie man Daten, die sich über die Zeit ändern, sauber historisiert (Slowly Changing Dimensions Typ 2). Der ÖPNV ist der Anwendungsfall, die Methode ist übertragbar.

## Stand

| Phase | Inhalt | Status |
|---|---|---|
| 0 | Sammelskript, täglicher Abruf mit Hash | läuft seit 2026-11-03 |
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

## Manifest und Landing Zone

Zu jedem neuen Stand legt der Sammler ein Manifest ab (`kvv_gtfs_..._manifest.json`) und hängt es mit an das Release. Es listet jede GTFS-Datei mit Größe, SHA-256 und Zeilenzahl. Damit sehe ich, *welche* Datei sich geändert hat, ohne 28,7 MB auszupacken.

Lokal lade ich Releases und Register in MongoDB:

```bash
cp .env.example .env          # Passwörter eintragen
make installieren             # pip install -r requirements-analyse.txt
make start                    # PostgreSQL und MongoDB, nur auf 127.0.0.1
make landing                  # Releases holen, Manifeste und Register in MongoDB
make abfrage                  # welche Dateien haben sich je Stand geändert?
```

In MongoDB (Datenbank `kvv_landing`) liegen zwei Collections:

- `snapshots`: ein Dokument je Stand, also das Manifest plus `release_tag` und `verarbeitet_am`
- `abrufe`: jede Zeile aus dem Register, auch Tage ohne Änderung und Fehlschläge

MongoDB ist eine abgeleitete Schicht. Die Wahrheit sind Register und Releases, und `make landing` baut alles jederzeit neu auf. Warum das so ist und warum der Schlüssel der Stand und nicht der Inhalts-Hash ist, steht in E7.

## Projektstruktur

```
sammler/        Sammelskript, Manifest, Laden der Landing Zone
data/raw/       heruntergeladene Stände (nicht im Git, liegen in den Releases)
data/           Snapshot-Register
sql/            Schema und Abfragen für PostgreSQL (ab Phase 3)
spark/          PySpark-Jobs (ab Phase 5)
analyse/        Notebooks und Auswertungen, z. B. geänderte Dateien je Stand
docs/           Entscheidungsprotokoll
```

## Daten und Lizenz

Fahrplandaten: Karlsruher Verkehrsverbund, bereitgestellt über MobiData BW, Lizenz **CC0**. Es besteht keine Pflicht zur Namensnennung, ich nenne die Quelle trotzdem.

Code: MIT, siehe LICENSE

## Entscheidungen

Warum ich etwas so gelöst habe und nicht anders, steht in [docs/entscheidungen.md](docs/entscheidungen.md).
