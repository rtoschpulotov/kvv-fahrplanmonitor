"""
Tests für die Ablage der Änderungen in PostgreSQL (Phase 4).
Autor: Rustam T.

Die Erkennung selbst testet tests/test_diff.py ohne Datenbank. Hier geht es
darum, dass die Ergebnisse richtig in fakt_aenderung landen und die Sichten
richtig rechnen. Fixture `db` aus tests/conftest.py.
"""

import psycopg
import pytest

from test_scd2 import scd2, stand, staging


def standpaar(db, alt: int, neu: int) -> int:
    return db.execute(
        """INSERT INTO dim_standpaar (stand_sk_alt, stand_sk_neu, fenster_ab, fenster_bis, stunden_dazwischen,
                                      fehler_dazwischen, fahrten_alt, fahrten_neu, geaendert, anteil_geaendert,
                                      ist_grosser_wechsel, trip_id_nur_alt, trip_id_nur_neu)
           VALUES (%s, %s, (SELECT abgerufen_utc FROM dim_stand WHERE stand_sk = %s), '2026-11-20',
                   24, 0, 100, 100, 1, 0.01, false, 0, 0) RETURNING standpaar_sk""", (alt, neu, neu)).fetchone()[0]


def aenderung(db, kalendertag: str, art: str, station: str | None = None, erste: str = "A") -> None:
    db.execute(
        """INSERT INTO stg_aenderung (kalendertag, route_id, richtung, erste_station, erste_abfahrt_sek,
                                      betriebstag, nr, art, station, verschiebung_min)
           VALUES (%s, 'r1', 0, %s, 28800, %s, 0, %s, %s, %s)""",
        (kalendertag, erste, kalendertag, art, station, 3 if art == "zeit" else None))


@pytest.fixture
def zwei_staende(db):
    s1 = stand(db, 1, 3)
    staging(db, {"A": ("Alpha", "49.0", "8.4"), "B": ("Beta", "49.1", "8.4")})
    scd2(db, s1)
    s2 = stand(db, 2, 4)
    staging(db, {"A": ("Alpha", "49.0", "8.4"), "B": ("Beta Nord", "49.1", "8.4")})
    scd2(db, s2)
    db.execute("TRUNCATE stg_aenderung, stg_aenderung_halt, stg_vergleich_linie")
    return db, standpaar(db, s1, s2)


def test_vorlauf_und_versionen(zwei_staende):
    db, sp = zwei_staende
    aenderung(db, "2026-11-04", "neu")                 # am selben Tag wie der Abruf
    aenderung(db, "2026-11-12", "zeit", station="B")   # 8 Tage vorher
    db.execute("CALL lade_aenderung(%s)", (sp,))
    zeilen = db.execute("""SELECT a.art, a.vorlauf_tage, h.name
                             FROM fakt_aenderung a LEFT JOIN dim_haltestelle h ON h.haltestelle_sk = a.haltestelle_sk
                            ORDER BY a.kalendertag""").fetchall()
    # Die Haltestelle ist die Version zum neuen Stand: "Beta Nord", nicht "Beta".
    assert zeilen == [("neu", 0, None), ("zeit", 8, "Beta Nord")]


def test_unbekannte_haltestelle_bricht_ab(zwei_staende):
    db, sp = zwei_staende
    aenderung(db, "2026-11-12", "neu", erste="GIBTESNICHT")
    with pytest.raises(psycopg.errors.NotNullViolation):
        db.execute("CALL lade_aenderung(%s)", (sp,))


def test_pruefung_findet_aenderung_vor_dem_fenster(zwei_staende):
    db, sp = zwei_staende
    aenderung(db, "2026-11-03", "neu")    # vor dem Abruf des neuen Stands am 04.11.
    db.execute("ALTER TABLE fakt_aenderung DROP CONSTRAINT fakt_aenderung_vorlauf_tage_check")
    db.execute("CALL lade_aenderung(%s)", (sp,))
    treffer = dict(db.execute("SELECT pruefung, treffer FROM v_pruefung").fetchall())
    assert treffer["Änderung außerhalb des Fensters"] == 1


def test_umpacken_gegen_aendern(db):
    db.execute("""INSERT INTO abruf (abgerufen_utc, status, inhalts_hash, zip_hash) VALUES
                  ('2026-11-01 04:00+00', 'neu',          'A', 'z1'),
                  ('2026-11-02 04:00+00', 'unveraendert', 'A', 'z1'),
                  ('2026-11-03 04:00+00', 'unveraendert', 'A', 'z2'),
                  ('2026-11-04 04:00+00', 'fehler',       NULL, NULL),
                  ('2026-11-05 04:00+00', 'neu',          'B', 'z3')""")
    ergebnis = [e for _, e in db.execute("SELECT abgerufen_utc, ergebnis FROM v_umpacken ORDER BY 1")]
    # Der Fehlschlag am 04.11. wird übersprungen, verglichen wird mit dem letzten erfolgreichen Abruf.
    assert ergebnis == ["erster Abruf", "unverändert", "nur neu gepackt", "Inhalt geändert"]


def test_standfolge_ohne_paar_wird_gemeldet(db):
    stand(db, 1, 3)
    stand(db, 2, 4)
    treffer = dict(db.execute("SELECT pruefung, treffer FROM v_pruefung").fetchall())
    assert treffer["Standpaar fehlt oder falsch"] == 1
