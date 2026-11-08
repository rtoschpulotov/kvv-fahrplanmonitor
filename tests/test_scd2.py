"""
Tests für das Sternschema und den SCD2-Schritt (Phase 3).
Autor: Rustam T.

Die SCD2-Logik steht in SQL, also brauchen die Tests eine echte
PostgreSQL-Datenbank. Sie nehmen die aus .env (der Docker-Container). Läuft
keine, werden die Tests übersprungen und nicht als Fehler gezählt. Dann
vorher `docker compose up -d`.

Jeder Test bekommt ein eigenes, leeres Schema, spielt sql/ dort ein und
löscht es danach wieder. Die echten Tabellen im Schema public bleiben
unberührt.
"""

import os
import uuid
from datetime import date, datetime, timezone
from pathlib import Path

import psycopg
import pytest
from dotenv import load_dotenv

from lade_postgres import horizont

REPO = Path(__file__).resolve().parent.parent
load_dotenv(REPO / ".env")


def _verbindung():
    return psycopg.connect(
        autocommit=True,
        host=os.environ.get("POSTGRES_HOST", "127.0.0.1"),
        port=os.environ.get("POSTGRES_PORT", "5433"),
        user=os.environ.get("POSTGRES_USER", "kvv"),
        password=os.environ.get("POSTGRES_PASSWORD", ""),
        dbname=os.environ.get("POSTGRES_DB", "kvv_fahrplan"),
        connect_timeout=3,
    )


@pytest.fixture
def db():
    try:
        conn = _verbindung()
    except psycopg.OperationalError as fehler:
        pytest.skip(f"keine PostgreSQL-Verbindung ({fehler}). Erst `docker compose up -d`.")
    schema = "test_" + uuid.uuid4().hex[:8]
    conn.execute(f"CREATE SCHEMA {schema}")
    conn.execute(f"SET search_path TO {schema}")
    for datei in sorted((REPO / "sql").glob("0*.sql")):
        conn.execute(datei.read_text(encoding="utf-8"))
    yield conn
    conn.execute(f"DROP SCHEMA {schema} CASCADE")
    conn.close()


# ---------------------------------------------------------------- Hilfen

def stand(conn, nr: int, tag: int) -> int:
    """Legt Stand nr mit Abrufzeit 2026-11-<tag> 12:00 UTC an."""
    return conn.execute(
        """INSERT INTO dim_stand (stand_id, abgerufen_utc, inhalts_hash, zip_hash, groesse_bytes,
                                  horizont_von, horizont_bis)
           VALUES (%s, %s, 'h', 'z', 1, %s, %s) RETURNING stand_sk""",
        (f"s{nr}", datetime(2026, 11, tag, 12, tzinfo=timezone.utc), date(2026, 11, tag), date(2026, 11, tag)),
    ).fetchone()[0]


def staging(conn, haltestellen: dict, linien: dict | None = None) -> None:
    """haltestellen: station_id -> (name, lat, lon). Alle liegen in Karlsruhe."""
    conn.execute("TRUNCATE stg_stops, stg_routes, stg_agency, stg_station_gemeinde, stg_abfahrten")
    for sid, (name, lat, lon) in haltestellen.items():
        conn.execute("INSERT INTO stg_stops VALUES (%s, %s, %s, %s, '1', '')", (sid, name, lat, lon))
        conn.execute("INSERT INTO stg_station_gemeinde VALUES (%s, '08212000', 'Karlsruhe')", (sid,))
    conn.execute("INSERT INTO stg_agency VALUES ('02', 'VBK')")
    for rid, kurz in (linien or {"r1": "1"}).items():
        conn.execute("INSERT INTO stg_routes VALUES (%s, '02', %s, '', '0')", (rid, kurz))


def scd2(conn, stand_sk: int) -> None:
    conn.execute("CALL scd2_haltestelle(%s)", (stand_sk,))
    conn.execute("CALL scd2_linie(%s)", (stand_sk,))


def versionen(conn, station_id: str) -> list[tuple]:
    return conn.execute(
        """SELECT name, gueltig_von::date, gueltig_bis::date, ist_aktuell, stand_sk_erstmals
             FROM dim_haltestelle WHERE station_id = %s ORDER BY gueltig_von""",
        (station_id,),
    ).fetchall()


ENDE = date(9999, 12, 31)


# ---------------------------------------------------------------- SCD2: die vier Fälle

def test_vier_faelle(db):
    s1 = stand(db, 1, 3)
    staging(db, {"A": ("Alpha", "49.0", "8.4"), "B": ("Beta", "49.1", "8.4"), "C": ("Gamma", "49.2", "8.4")})
    scd2(db, s1)

    s2 = stand(db, 2, 4)
    # A unverändert, B umbenannt, C verschwunden, D neu
    staging(db, {"A": ("Alpha", "49.0", "8.4"), "B": ("Beta Nord", "49.1", "8.4"), "D": ("Delta", "49.3", "8.4")})
    scd2(db, s2)

    assert versionen(db, "A") == [("Alpha", date(2026, 11, 3), ENDE, True, s1)]
    assert versionen(db, "B") == [
        ("Beta", date(2026, 11, 3), date(2026, 11, 4), False, s1),
        ("Beta Nord", date(2026, 11, 4), ENDE, True, s2),
    ]
    assert versionen(db, "C") == [("Gamma", date(2026, 11, 3), date(2026, 11, 4), False, s1)]
    assert versionen(db, "D") == [("Delta", date(2026, 11, 4), ENDE, True, s2)]


def test_wiederkehr_bekommt_neue_version_mit_luecke(db):
    """Haltestelle verschwindet und taucht später wieder auf (Frage fürs Gespräch)."""
    halt = {"C": ("Gamma", "49.2", "8.4")}
    s1 = stand(db, 1, 3)
    staging(db, halt)
    scd2(db, s1)
    s2 = stand(db, 2, 4)
    staging(db, {})
    scd2(db, s2)
    s3 = stand(db, 3, 18)
    staging(db, halt)
    scd2(db, s3)

    assert versionen(db, "C") == [
        ("Gamma", date(2026, 11, 3), date(2026, 11, 4), False, s1),
        ("Gamma", date(2026, 11, 18), ENDE, True, s3),
    ]


def test_hin_und_zurueck_sind_drei_versionen(db):
    """A, B, wieder A: Die Rückkehr ist eine eigene Version, nicht die alte (Schwaigern im echten Feed)."""
    for nr, (tag, name) in enumerate([(3, "Alt"), (4, "Neu"), (5, "Alt")], start=1):
        s = stand(db, nr, tag)
        staging(db, {"X": (name, "49.0", "8.4")})
        scd2(db, s)
    assert [v[0] for v in versionen(db, "X")] == ["Alt", "Neu", "Alt"]


def test_gleicher_stand_zweimal_aendert_nichts(db):
    s1 = stand(db, 1, 3)
    staging(db, {"A": ("Alpha", "49.0", "8.4")}, {"r1": "1", "r2": "2"})
    scd2(db, s1)
    vorher = db.execute("SELECT haltestelle_sk, xmin::text FROM dim_haltestelle UNION ALL "
                        "SELECT linie_sk, xmin::text FROM dim_linie ORDER BY 1, 2").fetchall()
    scd2(db, s1)
    nachher = db.execute("SELECT haltestelle_sk, xmin::text FROM dim_haltestelle UNION ALL "
                         "SELECT linie_sk, xmin::text FROM dim_linie ORDER BY 1, 2").fetchall()
    # xmin ist die Transaktion, die eine Zeile zuletzt geschrieben hat.
    # Gleich heißt: keine Zeile wurde angefasst.
    assert vorher == nachher


def test_koordinaten_rauschen_erzeugt_keine_version(db):
    s1 = stand(db, 1, 3)
    staging(db, {"A": ("Alpha", "49.12345678", "8.40000001")})
    scd2(db, s1)
    s2 = stand(db, 2, 4)
    staging(db, {"A": ("Alpha", "49.12345681", "8.40000004")})  # Abweichung in der 8. Stelle
    scd2(db, s2)
    assert len(versionen(db, "A")) == 1

    s3 = stand(db, 3, 5)
    staging(db, {"A": ("Alpha", "49.12360000", "8.40000004")})  # gut 15 m weiter nördlich
    scd2(db, s3)
    assert len(versionen(db, "A")) == 2


def test_linie_neue_version_bei_anderem_betreiber(db):
    s1 = stand(db, 1, 3)
    staging(db, {"A": ("Alpha", "49.0", "8.4")})
    scd2(db, s1)
    s2 = stand(db, 2, 4)
    staging(db, {"A": ("Alpha", "49.0", "8.4")})
    db.execute("UPDATE stg_agency SET agency_name = 'Verkehrsbetriebe Karlsruhe'")
    scd2(db, s2)
    zeilen = db.execute("SELECT betreiber, ist_aktuell FROM dim_linie ORDER BY gueltig_von").fetchall()
    assert zeilen == [("VBK", False), ("Verkehrsbetriebe Karlsruhe", True)]


# ---------------------------------------------------------------- Reihenfolge

def test_aelterer_stand_wird_abgelehnt(db):
    stand(db, 2, 5)
    with pytest.raises(psycopg.errors.RaiseException, match="nicht jünger"):
        stand(db, 1, 4)


def test_gleiche_abrufzeit_wird_abgelehnt(db):
    stand(db, 1, 5)
    with pytest.raises(psycopg.errors.RaiseException):
        stand(db, 2, 5)


# ---------------------------------------------------------------- Fakten

def fakt(db, stand_sk: int, station: str, anzahl: int = 3) -> None:
    db.execute("INSERT INTO stg_abfahrten VALUES ('2026-11-10', 8, %s, 'r1', %s)", (station, anzahl))
    db.execute("CALL lade_fakt(%s)", (stand_sk,))


def test_fakt_zeigt_auf_version_seines_stands(db):
    s1 = stand(db, 1, 3)
    staging(db, {"B": ("Beta", "49.1", "8.4")})
    scd2(db, s1)
    fakt(db, s1, "B")

    s2 = stand(db, 2, 4)
    staging(db, {"B": ("Beta Nord", "49.1", "8.4")})
    scd2(db, s2)
    fakt(db, s2, "B")

    namen = db.execute("""SELECT f.stand_sk, h.name FROM fakt_abfahrten f
                          JOIN dim_haltestelle h USING (haltestelle_sk) ORDER BY 1""").fetchall()
    assert namen == [(s1, "Beta"), (s2, "Beta Nord")]


def test_fakt_ohne_haltestelle_bricht_ab(db):
    s1 = stand(db, 1, 3)
    staging(db, {"A": ("Alpha", "49.0", "8.4")})
    scd2(db, s1)
    with pytest.raises(psycopg.errors.RaiseException, match="Abfahrtszeilen erwartet"):
        fakt(db, s1, "UNBEKANNT")


def test_pruefungen_ohne_treffer(db):
    s1 = stand(db, 1, 3)
    staging(db, {"A": ("Alpha", "49.0", "8.4"), "B": ("Beta", "49.1", "8.4")})
    scd2(db, s1)
    fakt(db, s1, "A")
    db.execute("UPDATE dim_stand SET horizont_bis = '2026-11-10'")
    s2 = stand(db, 2, 4)
    staging(db, {"A": ("Alpha neu", "49.0", "8.4")})
    scd2(db, s2)
    db.execute("UPDATE dim_stand SET horizont_von = '2026-11-04', horizont_bis = '2026-11-10' WHERE stand_sk = %s", (s2,))
    fakt(db, s2, "A")
    assert db.execute("SELECT sum(treffer) FROM v_pruefung").fetchone()[0] == 0


def test_pruefung_findet_doppelt_aktuelle_version(db):
    """Die Prüfabfrage muss selbst funktionieren: Ich baue absichtlich einen Fehler ein."""
    s1 = stand(db, 1, 3)
    staging(db, {"A": ("Alpha", "49.0", "8.4")})
    scd2(db, s1)
    db.execute("DROP INDEX ux_haltestelle_aktuell")
    db.execute("""INSERT INTO dim_haltestelle (station_id, name, lat, lon, attr_hash, gueltig_von, stand_sk_erstmals)
                  VALUES ('A', 'Alpha 2', 49, 8.4, 'x', '2026-11-03 13:00+00', %s)""", (s1,))
    treffer = dict(db.execute("SELECT pruefung, treffer FROM v_pruefung").fetchall())
    assert treffer["mehrfach aktuell"] == 1
    assert treffer["überlappende Zeiträume"] == 1


# ---------------------------------------------------------------- dim_datum

def test_feiertage_2026(db):
    feiertage = dict(db.execute("SELECT datum, feiertag FROM dim_datum WHERE ist_feiertag AND jahr = 2026").fetchall())
    assert len(feiertage) == 12          # elf gesetzliche Feiertage, Weihnachten zählt doppelt
    assert feiertage[date(2026, 4, 3)] == "Karfreitag"
    assert feiertage[date(2026, 5, 14)] == "Christi Himmelfahrt"
    assert feiertage[date(2026, 6, 4)] == "Fronleichnam"
    assert date(2026, 10, 31) not in feiertage   # Reformationstag ist in BW kein gesetzlicher Feiertag


def test_tagestyp_und_ferien(db):
    zeilen = {d: (t, f) for d, t, f in db.execute(
        "SELECT datum, tagestyp, ist_schulferien FROM dim_datum WHERE datum IN "
        "('2026-11-10', '2026-11-14', '2026-11-15', '2026-10-03', '2026-10-27', '2026-12-24')")}
    assert zeilen[date(2026, 11, 10)] == ("Werktag", False)
    assert zeilen[date(2026, 11, 14)] == ("Samstag", False)
    assert zeilen[date(2026, 11, 15)] == ("Sonn- und Feiertag", False)
    assert zeilen[date(2026, 10, 3)] == ("Sonn- und Feiertag", False)   # Feiertag an einem Samstag
    assert zeilen[date(2026, 10, 27)] == ("Werktag", True)              # Herbstferien
    assert zeilen[date(2026, 12, 24)] == ("Werktag", True)              # Weihnachtsferien ab 23.12.


# ---------------------------------------------------------------- Horizont (ohne Datenbank)

def test_horizont_rechnet_in_deutscher_zeit():
    # 23:30 UTC am 09.11. ist in Karlsruhe schon der 10.11.
    von, bis = horizont(datetime(2026, 11, 9, 23, 30, tzinfo=timezone.utc), date(2026, 12, 12), 14)
    assert (von, bis) == (date(2026, 11, 10), date(2026, 11, 23))


def test_horizont_endet_mit_dem_fahrplan():
    von, bis = horizont(datetime(2026, 12, 5, 12, tzinfo=timezone.utc), date(2026, 12, 12), 14)
    assert (von, bis) == (date(2026, 12, 5), date(2026, 12, 12))
