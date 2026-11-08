"""
Änderungen zwischen aufeinanderfolgenden Ständen nach PostgreSQL (Phase 4).
Autor: Rustam T.

Läuft automatisch am Ende von laden/lade_postgres.py, lässt sich aber auch
allein starten. Ablauf:

1. Das Register vollständig in die Tabelle `abruf` (für die Kennzahl
   "Umpacken gegen Ändern").
2. Alle Paare direkt aufeinanderfolgender Stände aus dim_stand bilden.
   Verglichen werden nur Nachbarn. Längere Abstände ergeben sich durch
   Aufsummieren, ein Vergleich jedes Stands mit jedem brächte nichts Neues.
3. Für jedes Paar, das noch nicht in dim_standpaar steht: beide Stände
   einlesen, Fahrten im Vergleichsfenster bilden, vergleichen
   (analyse/diff.py) und alles in einer Transaktion schreiben.

Idempotent wie Phase 3: Ein Paar, das schon da ist, wird übersprungen.
"""

import sys
import time
from datetime import timezone
from pathlib import Path

import pandas as pd
import psycopg

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "analyse"))

from diff import Fenster, fahrten, fahrtverlaeufe, vergleiche  # noqa: E402
from gtfs import lies_stand  # noqa: E402

BERLIN_TZ = "Europe/Berlin"
GROSSER_WECHSEL_AB = 0.05      # E17: ab 5 % geänderter Fahrten im Fenster

STG = ["stg_aenderung", "stg_aenderung_halt", "stg_vergleich_linie"]


def kopiere(cur, tabelle: str, df: pd.DataFrame) -> None:
    spalten = ", ".join(df.columns)
    with cur.copy(f"COPY {tabelle} ({spalten}) FROM STDIN") as copy:
        for zeile in df.itertuples(index=False, name=None):
            copy.write_row([None if (isinstance(w, float) and pd.isna(w)) or w is pd.NA else w for w in zeile])


def synchronisiere_register(conn: psycopg.Connection, register: Path) -> None:
    """Alle Registerzeilen nach `abruf`. Bestehende Zeilen bleiben unberührt."""
    df = pd.read_csv(register, dtype=str, keep_default_na=False)
    with conn.transaction(), conn.cursor() as cur:
        for z in df.itertuples(index=False):
            cur.execute(
                """INSERT INTO abruf (abgerufen_utc, status, inhalts_hash, zip_hash, groesse_bytes, fehler)
                   VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT (abgerufen_utc) DO NOTHING""",
                (z.abgerufen_utc, z.status, z.inhalts_hash or None, z.zip_hash or None,
                 int(z.groesse_bytes) if z.groesse_bytes else None, z.fehler or None),
            )


def offene_paare(conn: psycopg.Connection) -> list[dict]:
    zeilen = conn.execute(
        """WITH folge AS (
               SELECT stand_sk, stand_id, abgerufen_utc, feed_bis,
                      lag(stand_sk)      OVER w AS alt_sk,
                      lag(stand_id)      OVER w AS alt_id,
                      lag(abgerufen_utc) OVER w AS alt_zeit,
                      lag(feed_bis)      OVER w AS alt_feed_bis
                 FROM dim_stand WINDOW w AS (ORDER BY abgerufen_utc))
           SELECT f.alt_sk, f.alt_id, f.alt_zeit, f.alt_feed_bis, f.stand_sk, f.stand_id, f.abgerufen_utc, f.feed_bis,
                  (SELECT count(*) FROM abruf r
                    WHERE r.status = 'fehler' AND r.abgerufen_utc > f.alt_zeit AND r.abgerufen_utc < f.abgerufen_utc)
             FROM folge f
            WHERE f.alt_sk IS NOT NULL
              AND NOT EXISTS (SELECT 1 FROM dim_standpaar p
                               WHERE p.stand_sk_alt = f.alt_sk AND p.stand_sk_neu = f.stand_sk)
            ORDER BY f.abgerufen_utc""").fetchall()
    namen = ["alt_sk", "alt_id", "alt_zeit", "alt_feed_bis", "neu_sk", "neu_id", "neu_zeit", "neu_feed_bis", "fehler"]
    return [dict(zip(namen, z)) for z in zeilen]


def fenster_fuer(paar: dict) -> Fenster:
    """E16: ab dem Abruf des neuen Stands, bis zum letzten Tag, den beide abdecken."""
    ab = pd.Timestamp(paar["neu_zeit"]).tz_convert(BERLIN_TZ).tz_localize(None).to_pydatetime()
    return Fenster(ab=ab, bis=min(paar["alt_feed_bis"], paar["neu_feed_bis"]))


def lies(rohordner: Path, stand_id: str) -> tuple[dict, pd.DataFrame]:
    zip_pfad = rohordner / f"kvv_gtfs_{stand_id}.zip"
    if not zip_pfad.exists():
        raise SystemExit(f"{zip_pfad.name} fehlt in data/raw. Erst `python sammler/lade_landing_zone.py`.")
    stand = lies_stand(zip_pfad, trips_spalten=("route_id", "service_id", "trip_id", "direction_id"))
    return stand, fahrtverlaeufe(stand["stop_times"], stand["stops"])


def vergleiche_paar(paar: dict, alt: tuple, neu: tuple):
    fenster = fenster_fuer(paar)
    f_alt = fahrten(alt[0], alt[1], fenster)
    f_neu = fahrten(neu[0], neu[1], fenster)
    aend, halte, je_linie = vergleiche(f_alt, f_neu, alt[1], neu[1])
    # Gegenprobe zu E15: so viele trip_ids gäbe es nur auf einer Seite.
    ids_alt, ids_neu = set(f_alt["trip_id"]), set(f_neu["trip_id"])
    trip_ids = (len(ids_alt - ids_neu), len(ids_neu - ids_alt))
    return fenster, len(f_alt), len(f_neu), aend, halte, je_linie, trip_ids


def schreibe_paar(conn, paar, fenster, n_alt, n_neu, aend, halte, je_linie, trip_ids) -> int:
    geaendert = int(je_linie["geaendert"].sum())
    anteil = geaendert / n_alt if n_alt else 0.0
    stunden = (paar["neu_zeit"] - paar["alt_zeit"]).total_seconds() / 3600
    fenster_ab = pd.Timestamp(fenster.ab).tz_localize(BERLIN_TZ).tz_convert(timezone.utc).to_pydatetime()

    a = aend.rename(columns={"direction_id": "richtung"}).copy()
    a["kalendertag"] = pd.to_datetime(a["kalendertag"]).dt.date
    a["betriebstag"] = pd.to_datetime(a["betriebstag"]).dt.date
    a["richtung"] = a["richtung"].astype(int)
    a["erste_abfahrt_sek"] = a["erste_abfahrt_sek"].astype(int)
    a["verschiebung_min"] = a["verschiebung_min"].astype("Int64")
    a = a[["kalendertag", "route_id", "richtung", "erste_station", "erste_abfahrt_sek", "betriebstag", "nr",
           "art", "detail", "station", "verschiebung_min", "trip_id_alt", "trip_id_neu"]] if len(a) else a

    h = halte.rename(columns={"direction_id": "richtung"}).copy()
    if len(h):
        h["richtung"] = h["richtung"].astype(int)
        h["erste_abfahrt_sek"] = h["erste_abfahrt_sek"].astype(int)

    with conn.transaction(), conn.cursor() as cur:
        cur.execute(
            """INSERT INTO dim_standpaar (stand_sk_alt, stand_sk_neu, fenster_ab, fenster_bis, stunden_dazwischen,
                                         fehler_dazwischen, fahrten_alt, fahrten_neu, geaendert, anteil_geaendert,
                                         ist_grosser_wechsel, trip_id_nur_alt, trip_id_nur_neu)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING standpaar_sk""",
            (paar["alt_sk"], paar["neu_sk"], fenster_ab, fenster.bis, round(stunden, 1), paar["fehler"],
             n_alt, n_neu, geaendert, round(anteil, 5), anteil >= GROSSER_WECHSEL_AB, *trip_ids))
        sk = cur.fetchone()[0]
        cur.execute("TRUNCATE " + ", ".join(STG))
        if len(a):
            kopiere(cur, "stg_aenderung", a)
        if len(h):
            kopiere(cur, "stg_aenderung_halt", h)
        kopiere(cur, "stg_vergleich_linie", je_linie.rename(columns={"neu": "hinzu"}))
        cur.execute("CALL lade_aenderung(%s)", (sk,))
    return sk


def lade_alle(conn: psycopg.Connection, rohordner: Path, register: Path) -> None:
    synchronisiere_register(conn, register)
    paare = offene_paare(conn)
    print(f"Änderungen: {len(paare)} Standpaare offen")
    cache = {}
    for paar in paare:
        start = time.time()
        for sid in (paar["alt_id"], paar["neu_id"]):
            if sid not in cache:
                cache[sid] = lies(rohordner, sid)
        fenster, n_alt, n_neu, aend, halte, je_linie, trip_ids = vergleiche_paar(
            paar, cache[paar["alt_id"]], cache[paar["neu_id"]])
        schreibe_paar(conn, paar, fenster, n_alt, n_neu, aend, halte, je_linie, trip_ids)
        arten = aend["art"].value_counts().to_dict() if len(aend) else {}
        print(f"  {paar['alt_id']} -> {paar['neu_id']}: {n_alt:_} Fahrten im Fenster, "
              f"{len(aend):_} Änderungen {arten}, {time.time() - start:.0f} s".replace("_", "."))
        cache.pop(paar["alt_id"], None)   # der alte wird nicht mehr gebraucht, der neue ist der nächste alte


if __name__ == "__main__":
    from dotenv import load_dotenv
    from lade_postgres import verbinde
    load_dotenv(REPO / ".env")
    with verbinde() as c:
        lade_alle(c, REPO / "data" / "raw", REPO / "data" / "snapshot_register.csv")
