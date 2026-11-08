# Die Befehle, die ich am häufigsten brauche.
# Autor: Rustam T.

.PHONY: start stopp status installieren landing abfrage test profil laden pruefen aenderungen

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

# Tests für die Betriebstag-Logik (Phase 2)
test:
	python -m pytest

# Profil eines Stands, zum Beispiel: make profil STAND=data/raw/kvv_gtfs_2026-11-04T120817Z.zip
profil:
	python analyse/profil.py $(STAND)

# Alle noch nicht geladenen Stände ins Sternschema (Phase 3), danach die
# Änderungen zwischen den Ständen (Phase 4). Darf beliebig oft laufen.
laden:
	python laden/lade_postgres.py

# Nur die Prüfabfragen auf das Sternschema
pruefen:
	python laden/lade_postgres.py --nur-pruefen

# Nur die Änderungen zwischen Ständen nachladen (Phase 4)
aenderungen:
	python laden/lade_aenderungen.py
