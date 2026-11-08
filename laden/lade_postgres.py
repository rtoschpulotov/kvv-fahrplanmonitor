"""
Gesammelte Stände in das Sternschema in PostgreSQL laden (Phase 3).
Autor: Rustam T.

Ablauf je Stand, alles in einer Transaktion:
1. Zeile in dim_stand. Die Datenbank lehnt sie ab, wenn der Stand älter ist
   als ein schon geladener (sql/04_reihenfolge.sql).
2. stops, routes und agency roh nach stg_* kopieren.
3. Stationen den Gemeinden zuordnen (GeoPandas) und nach stg_station_gemeinde.
4. CALL scd2_haltestelle und scd2_linie. Die eigentliche SCD2-Logik steht in
   SQL (sql/05_scd2.sql), nicht hier.
5. Abfahrten nach der Logik aus Phase 2 für den Horizont des Stands
   berechnen, je Tag, Stunde, Station und Linie zählen, nach stg_abfahrten.
6. CALL lade_fakt. Bricht ab, wenn eine Zeile keine Dimensionsversion findet.
7. COMMIT. Erst dann gilt der Stand als geladen.

Geht unterwegs etwas schief, rollt Postgres alles zurück. Es gibt keinen
halb geladenen Stand.

Idempotent: Ein Stand, der schon in dim_stand steht, wird übersprungen. Ein
zweiter Lauf ohne neue Stände ändert keine Zeile.

Welche Stände es gibt, sagt das Register (data/snapshot_register.csv, nur
Status "neu"). Die ZIPs müssen in data/raw liegen. Fehlt eine, hole ich sie
nicht selbst, sondern breche ab: Eine Lücke mitten in der Reihenfolge ließe
sich später nicht mehr schließen (siehe 04_reihenfolge.sql). Fehlende ZIPs
lädt `python sammler/lade_landing_zone.py`.

Aufruf:
    python laden/lade_postgres.py                  # alle neuen Stände
    python laden/lade_postgres.py --bis 2026-11-05 # nur bis zu diesem Tag
    python laden/lade_postgres.py --nur-pruefen    # nur die Prüfabfragen
"""

import argparse
import csv
import io
import os
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import psycopg
from dotenv import load_dotenv

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "analyse"))

from betriebstage import abfahrten, betriebstage  # noqa: E402
from gtfs import lies_stand, lies_tabelle  # noqa: E402

SQL_ORDNER = REPO / "sql"
ZIP_PRAEFIX = "kvv_gtfs_"
BERLIN = ZoneInfo("Europe/Berlin")
HORIZONT_TAGE = 14          # E13
STANDARD_GEODATEN = REPO.parent / "geodaten" / "vg250-ew_12-31.utm32s.gpkg.ebenen"

STG_SPALTEN = {
    "stg_stops": ("stops.txt", ["stop_id", "stop_name", "stop_lat", "stop_lon", "location_type", "parent_station"]),
    "stg_routes": ("routes.txt", ["route_id", "agency_id", "route_short_name", "route_long_name", "route_type"]),
    "stg_agency": ("agency.txt", ["agency_id", "agency_name"]),
}


# ---------------------------------------------------------------- Verbindung und Schema

def verbinde() -> psycopg.Connection:
    """Verbindung aus .env. Port 5433, weil docker-compose.yml Postgres dorthin legt.

    autocommit=True heißt nicht, dass jede Zeile einzeln gespeichert wird.
    Es heißt, dass ich Transaktionen selbst und ausdrücklich öffne, mit
    conn.transaction() je Stand. Ohne autocommit würde psycopg schon beim
    ersten SELECT still eine Transaktion beginnen, und mein conn.transaction()
    wäre nur ein Sicherungspunkt darin. Ein Fehler beim dritten Stand würde
    dann auch die ersten beiden zurückrollen.
    """
    return psycopg.connect(
        autocommit=True,
        host=os.environ.get("POSTGRES_HOST", "127.0.0.1"),
        port=os.environ.get("POSTGRES_PORT", "5433"),
        user=os.environ["POSTGRES_USER"],
        password=os.environ.get("POSTGRES_PASSWORD", ""),
        dbname=os.environ["POSTGRES_DB"],
    )


def spiele_schema_ein(conn: psycopg.Connection, ordner: Path = SQL_ORDNER) -> None:
    """Führt sql/01_*.sql bis sql/99_*.sql in Reihenfolge aus.

    Der Container macht das nur beim allerersten Start mit leerem Volume.
    Mein Volume stammt aus Phase 1, also spiele ich die Dateien hier ein.
    Jede Datei darf beliebig oft laufen.
    """
    for datei in sorted(ordner.glob("[0-9][0-9]_*.sql")):
        conn.execute(datei.read_text(encoding="utf-8"))


def schema_fehlt(conn: psycopg.Connection) -> bool:
    # Die zuletzt angelegte Sicht. Fehlt sie, ist mindestens eine Datei neu.
    return conn.execute("SELECT to_regclass('v_pruefung_standfolge') IS NULL").fetchone()[0]


# ---------------------------------------------------------------- Stände finden

def stand_id(zip_name: str) -> str:
    return zip_name.removeprefix(ZIP_PRAEFIX).removesuffix(".zip")


def neue_staende(register: Path, rohordner: Path) -> list[dict]:
    """Alle Stände mit Status "neu", aufsteigend nach Abrufzeit."""
    with register.open(newline="", encoding="utf-8") as f:
        zeilen = [z for z in csv.DictReader(f) if z["status"] == "neu"]
    staende = []
    for z in zeilen:
        staende.append({
            "stand_id": stand_id(z["dateiname"]),
            "abgerufen_utc": datetime.strptime(z["abgerufen_utc"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc),
            "inhalts_hash": z["inhalts_hash"],
            "zip_hash": z["zip_hash"],
            "groesse_bytes": int(z["groesse_bytes"]),
            "zip": rohordner / z["dateiname"],
        })
    return sorted(staende, key=lambda s: s["abgerufen_utc"])


def horizont(abgerufen_utc: datetime, feed_bis: date | None, tage: int = HORIZONT_TAGE) -> tuple[date, date]:
    """Welche Kalendertage dieser Stand in fakt_abfahrten bekommt (E13).

    Ab dem Tag des Abrufs, deutsche Zeit. Ein Abruf um 23:30 UTC ist in
    Karlsruhe schon der nächste Tag. Höchstens `tage` Tage, und nicht über
    das Ende des Fahrplans hinaus.
    """
    von = abgerufen_utc.astimezone(BERLIN).date()
    bis = von + timedelta(days=tage - 1)
    if feed_bis is not None and feed_bis < bis:
        bis = feed_bis
    return von, bis


# ---------------------------------------------------------------- Daten vorbereiten

def kopiere(cur: psycopg.Cursor, tabelle: str, df: pd.DataFrame) -> None:
    """DataFrame per COPY in eine Tabelle. COPY ist bei Hunderttausenden Zeilen
    um ein Vielfaches schneller als INSERT Zeile für Zeile."""
    spalten = ", ".join(df.columns)
    with cur.copy(f"COPY {tabelle} ({spalten}) FROM STDIN") as copy:
        for zeile in df.itertuples(index=False, name=None):
            copy.write_row(zeile)


def rohdaten(zip_pfad: Path) -> dict[str, pd.DataFrame]:
    """stops, routes, agency mit festen Spalten. Fehlt eine Spalte im Feed
    (optionale GTFS-Felder), steht dort ein leerer Text."""
    erg = {}
    for tabelle, (datei, spalten) in STG_SPALTEN.items():
        df = lies_tabelle(zip_pfad, datei)
        for s in spalten:
            if s not in df.columns:
                df[s] = ""
        erg[tabelle] = df[spalten]
    return erg


def gemeinde_je_station(stops: pd.DataFrame, gemeinden) -> pd.DataFrame:
    """station_id, ags, gemeinde für alle Stationen, die in einer deutschen Gemeinde liegen."""
    from gemeinden import ordne_zu, stationen_mit_koordinaten
    drin, _ = ordne_zu(stationen_mit_koordinaten(stops), gemeinden)
    return drin[["station_id", "ags", "gemeinde"]]


def abfahrten_je_stunde(stand: dict, von: date, bis: date) -> pd.DataFrame:
    """Phase-2-Logik für jeden Tag des Horizonts, gezählt je Stunde, Station und Linie.

    Tag für Tag statt alles auf einmal: Zwei Wochen am Stück wären gut
    2 Millionen Einzelabfahrten und über 1 GB im Speicher. So bleibt es bei
    einem Tag. Wie in Phase 2 hole ich je Tag die Betriebstage ab dem Vortag,
    damit eine Fahrt um 24:30 am richtigen Kalendertag landet.
    """
    teile = []
    tag = pd.Timestamp(von)
    while tag <= pd.Timestamp(bis):
        tage = betriebstage(stand["calendar"], stand["calendar_dates"], tag - pd.Timedelta(days=1), tag)
        ab = abfahrten(stand["stop_times"], stand["trips"], stand["stops"], tage)
        ab = ab[ab["kalendertag"] == tag]
        teile.append(
            ab.groupby(["kalendertag", "stunde", "station_id", "route_id"], observed=True)
              .size().rename("anzahl").reset_index()
        )
        tag += pd.Timedelta(days=1)
    erg = pd.concat(teile, ignore_index=True)
    erg["datum"] = erg["kalendertag"].dt.date
    return erg[["datum", "stunde", "station_id", "route_id", "anzahl"]].astype({"stunde": int, "anzahl": int})


def feed_info(stand: dict) -> tuple[str | None, date | None, date | None]:
    fi = stand["feed_info"]
    if fi.empty:
        return None, None, None

    def d(text):
        return datetime.strptime(text, "%Y%m%d").date() if text else None

    zeile = fi.iloc[0]
    return zeile.get("feed_version") or None, d(zeile.get("feed_start_date", "")), d(zeile.get("feed_end_date", ""))


# ---------------------------------------------------------------- Einen Stand laden

def ist_geladen(conn: psycopg.Connection, sid: str) -> bool:
    return conn.execute("SELECT 1 FROM dim_stand WHERE stand_id = %s", (sid,)).fetchone() is not None


def lade_stand(conn: psycopg.Connection, s: dict, gemeinden, horizont_tage: int = HORIZONT_TAGE) -> dict:
    """Lädt einen Stand in einer Transaktion. Gibt ein paar Zahlen fürs Protokoll zurück."""
    stand = lies_stand(s["zip"])
    version, feed_von, feed_bis = feed_info(stand)
    von, bis = horizont(s["abgerufen_utc"], feed_bis, horizont_tage)
    if bis < von:
        raise ValueError(f"{s['stand_id']}: Fahrplan endet am {feed_bis}, vor dem Abruftag {von}")

    roh = rohdaten(s["zip"])
    zuordnung = gemeinde_je_station(roh["stg_stops"], gemeinden)
    fakten = abfahrten_je_stunde(stand, von, bis)

    with conn.transaction(), conn.cursor() as cur:
        cur.execute(
            """INSERT INTO dim_stand (stand_id, abgerufen_utc, inhalts_hash, zip_hash, groesse_bytes,
                                      feed_version, feed_von, feed_bis, horizont_von, horizont_bis)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING stand_sk""",
            (s["stand_id"], s["abgerufen_utc"], s["inhalts_hash"], s["zip_hash"], s["groesse_bytes"],
             version, feed_von, feed_bis, von, bis),
        )
        stand_sk = cur.fetchone()[0]

        cur.execute("TRUNCATE stg_stops, stg_routes, stg_agency, stg_station_gemeinde, stg_abfahrten")
        for tabelle, df in roh.items():
            kopiere(cur, tabelle, df)
        kopiere(cur, "stg_station_gemeinde", zuordnung)

        cur.execute("CALL scd2_haltestelle(%s)", (stand_sk,))
        cur.execute("CALL scd2_linie(%s)", (stand_sk,))

        kopiere(cur, "stg_abfahrten", fakten)
        cur.execute("CALL lade_fakt(%s)", (stand_sk,))

    return {"stand_sk": stand_sk, "von": von, "bis": bis, "faktzeilen": len(fakten)}


# ---------------------------------------------------------------- Prüfen und Protokoll

def pruefe(conn: psycopg.Connection) -> bool:
    ok = True
    for pruefung, treffer in conn.execute("SELECT pruefung, treffer FROM v_pruefung"):
        zeichen = "ok" if treffer == 0 else "FEHLER"
        print(f"  {zeichen:6} {pruefung}: {treffer}")
        ok = ok and treffer == 0
    return ok


def versionen(conn: psycopg.Connection) -> None:
    for tabelle in ("dim_haltestelle", "dim_linie"):
        gesamt, aktuell = conn.execute(f"SELECT count(*), count(*) FILTER (WHERE ist_aktuell) FROM {tabelle}").fetchone()
        print(f"  {tabelle}: {gesamt} Versionen, davon {aktuell} aktuell")


def markiere_in_mongo(conn: psycopg.Connection) -> None:
    """verarbeitet_am in der Landing Zone nachziehen (Phase 1, Aufgabe 5).

    Postgres ist hier die Quelle: Jeder Stand in dim_stand gilt als
    verarbeitet. Ich gleiche bei jedem Lauf alle ab, nicht nur die neuen.
    War MongoDB beim letzten Mal nicht erreichbar, holt der nächste Lauf das
    nach. Läuft MongoDB nicht, ist das kein Grund, den Lauf scheitern zu
    lassen, die Daten in Postgres sind ja richtig.
    """
    sys.path.insert(0, str(REPO / "sammler"))
    try:
        from lade_landing_zone import mongo_client
        db = mongo_client()[os.environ.get("MONGO_DB", "kvv_landing")]
        geaendert = 0
        for sid, geladen_am in conn.execute("SELECT stand_id, geladen_am FROM dim_stand"):
            r = db.snapshots.update_one({"_id": sid, "verarbeitet_am": None}, {"$set": {"verarbeitet_am": geladen_am}})
            geaendert += r.modified_count
        print(f"MongoDB: verarbeitet_am bei {geaendert} Ständen gesetzt")
    except Exception as fehler:  # noqa: BLE001
        print(f"Hinweis: MongoDB nicht aktualisiert ({type(fehler).__name__}: {fehler}). "
              "Der nächste Lauf holt das nach.")


def lies_gemeinden_datei():
    from gemeinden import lies_gemeinden
    pfad = Path(os.environ.get("KVV_GEODATEN", STANDARD_GEODATEN))
    gpkg = pfad if pfad.suffix == ".gpkg" else next(pfad.rglob("*.gpkg"), None)
    if gpkg is None or not gpkg.exists():
        raise SystemExit(f"Gemeindegrenzen nicht gefunden unter {pfad}. Siehe README, Abschnitt Daten und Lizenz.")
    return lies_gemeinden(gpkg)


def main() -> int:
    load_dotenv(REPO / ".env")
    parser = argparse.ArgumentParser(description="Lädt gesammelte Stände in das Sternschema.")
    parser.add_argument("--register", default=REPO / "data" / "snapshot_register.csv", type=Path)
    parser.add_argument("--rohdaten", default=REPO / "data" / "raw", type=Path)
    parser.add_argument("--bis", help="nur Stände bis zu diesem Tag (JJJJ-MM-TT)")
    parser.add_argument("--horizont", type=int, default=HORIZONT_TAGE, help="Tage je Stand in fakt_abfahrten")
    parser.add_argument("--schema", action="store_true", help="sql/ auch dann einspielen, wenn das Schema schon da ist")
    parser.add_argument("--nur-pruefen", action="store_true")
    parser.add_argument("--ohne-mongo", action="store_true")
    parser.add_argument("--ohne-aenderungen", action="store_true", help="Phase 4 (Standvergleich) auslassen")
    args = parser.parse_args()

    with verbinde() as conn:
        if args.schema or schema_fehlt(conn):
            print("Spiele sql/ ein")
            spiele_schema_ein(conn)

        if not args.nur_pruefen:
            staende = neue_staende(args.register, args.rohdaten)
            if args.bis:
                grenze = date.fromisoformat(args.bis)
                staende = [s for s in staende if s["abgerufen_utc"].date() <= grenze]
            offen = [s for s in staende if not ist_geladen(conn, s["stand_id"])]
            fehlend = [s["zip"].name for s in offen if not s["zip"].exists()]
            if fehlend:
                raise SystemExit("Diese ZIPs fehlen in data/raw, bitte erst `python sammler/lade_landing_zone.py`:\n  "
                                 + "\n  ".join(fehlend))

            print(f"{len(staende) - len(offen)} Stände schon geladen, {len(offen)} offen")
            gemeinden = lies_gemeinden_datei() if offen else None
            for s in offen:
                start = time.time()
                info = lade_stand(conn, s, gemeinden, args.horizont)
                print(f"{s['stand_id']}: Tage {info['von']} bis {info['bis']}, "
                      f"{info['faktzeilen']:_} Faktzeilen, {time.time() - start:.0f} s".replace("_", "."))

            if not args.ohne_aenderungen:
                from lade_aenderungen import lade_alle
                lade_alle(conn, args.rohdaten, args.register)

        versionen(conn)
        print("Prüfabfragen:")
        ok = pruefe(conn)
        if not args.ohne_mongo and not args.nur_pruefen:
            markiere_in_mongo(conn)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
