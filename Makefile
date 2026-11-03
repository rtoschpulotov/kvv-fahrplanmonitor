# Die Befehle, die ich am häufigsten brauche.
# Autor: Rustam T.

.PHONY: start stopp status installieren landing abfrage

start:
	docker compose up -d

stopp:
	docker compose down

status:
	docker compose ps

installieren:
	pip install -r requirements-analyse.txt

# Releases holen, fehlende Manifeste nachbauen, alles in MongoDB schreiben.
# Darf beliebig oft laufen.
landing:
	python sammler/lade_landing_zone.py

# Welche GTFS-Dateien haben sich je Stand geändert?
abfrage:
	python analyse/geaenderte_dateien.py
