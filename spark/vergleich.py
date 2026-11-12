"""
Rechnen Pandas und Spark exakt dasselbe? (Phase 5, Aufgabe 5)
Autor: Rustam T.

Für ausgewählte Standpaare rechne ich den Vergleich zweimal, einmal mit
analyse/diff.py (Pandas, aus den ZIPs) und einmal mit spark/diff_spark.py
(Spark, aus Parquet). Dann vergleiche ich die drei Ergebnistabellen Zeile für
Zeile: Änderungen, betroffene Haltestellen, Zählung je Linie. Dazu für einen
Stand die Abfahrten je Stunde, Station und Linie.

"Exakt" heißt: Jeder Wert wird in einen einheitlichen Text umgewandelt
(Datum als JJJJ-MM-TT, Zahl ohne Nachkommastellen, fehlend als leerer Text),
dann werden beide Tabellen sortiert und als Ganzes verglichen. Kein Runden,
keine Toleranz, kein "ungefähr gleich viele Zeilen".

Standard sind die Paare 2 bis 4 (04.11. bis 07.11.2026). Zusammen enthalten
sie jede Änderungsart, auch die seltenen Zeitänderungen.

Aufruf im Container:
    docker compose run --rm spark python3 spark/vergleich.py
    docker compose run --rm spark python3 spark/vergleich.py --alle
Exit-Code 0 heißt gleich, 1 heißt Unterschied gefunden.
"""

import argparse
import math
import sys
import time
from datetime import date, datetime

import pandas as pd

from diff_spark import vergleiche_staende
from sitzung import lies, lies_stand, sitzung, staende

SPALTEN = {
    "aenderungen": ["route_id", "direction_id", "erste_station", "erste_abfahrt_sek", "betriebstag", "nr",
                    "kalendertag", "art", "detail", "verschiebung_min", "station", "trip_id_alt", "trip_id_neu"],
    "halte": ["route_id", "direction_id", "erste_station", "erste_abfahrt_sek", "art", "station"],
    "je_linie": ["route_id", "fahrten_alt", "fahrten_neu", "geaendert", "neu"],
    "abfahrten": ["datum", "stunde", "station_id", "route_id", "anzahl"],
}


def _text(w) -> str:
    """Ein Wert als einheitlicher Text, egal ob er aus Pandas oder Spark kommt."""
    if w is None or w is pd.NA or w is pd.NaT or (isinstance(w, float) and math.isnan(w)):
        return ""
    if isinstance(w, (pd.Timestamp, datetime)):
        return w.date().isoformat()
    if isinstance(w, date):
        return w.isoformat()
    if isinstance(w, float) and w.is_integer():
        return str(int(w))
    return str(w)


def kanonisch(df: pd.DataFrame, spalten: list[str]) -> list[tuple]:
    """Sortierte Liste von Zeilen, jede Zeile ein Tupel aus Texten."""
    return sorted(tuple(_text(w) for w in z) for z in df[spalten].itertuples(index=False, name=None))


def gleich(name: str, pandas_df: pd.DataFrame, spark_df: pd.DataFrame) -> bool:
    p, s = kanonisch(pandas_df, SPALTEN[name]), kanonisch(spark_df, SPALTEN[name])
    if p == s:
        print(f"    gleich   {name}: {len(p)} Zeilen")
        return True
    nur_p = sorted(set(p) - set(s))
    nur_s = sorted(set(s) - set(p))
    print(f"    ANDERS   {name}: Pandas {len(p)}, Spark {len(s)} Zeilen, "
          f"nur Pandas {len(nur_p)}, nur Spark {len(nur_s)}")
    for z in nur_p[:3]:
        print(f"             nur Pandas: {z}")
    for z in nur_s[:3]:
        print(f"             nur Spark:  {z}")
    return False


def pruefe_paar(spark, a: dict, n: dict, pandas_staende: dict) -> bool:
    from diff import fahrten, vergleiche
    from lade_aenderungen import fenster_fuer, lies
    from lade_postgres import feed_info
    from sitzung import ROHDATEN

    for s in (a, n):
        if s["stand_id"] not in pandas_staende:
            pandas_staende[s["stand_id"]] = lies(ROHDATEN, s["stand_id"])
    pa, pn = pandas_staende[a["stand_id"]], pandas_staende[n["stand_id"]]
    fenster = fenster_fuer({"neu_zeit": n["abgerufen_utc"], "alt_feed_bis": feed_info(pa[0])[2],
                            "neu_feed_bis": feed_info(pn[0])[2]})
    print(f"  {a['stand_id']} -> {n['stand_id']} (Fenster ab {fenster.ab}, bis {fenster.bis})")

    t = time.perf_counter()
    p_aend, p_halte, p_linie = vergleiche(fahrten(pa[0], pa[1], fenster), fahrten(pn[0], pn[1], fenster), pa[1], pn[1])
    t_pandas = time.perf_counter() - t

    t = time.perf_counter()
    _, _, s_aend, s_halte, s_linie = vergleiche_staende(spark, lies_stand(spark, a["stand_id"]),
                                                        lies_stand(spark, n["stand_id"]), fenster.ab, fenster.bis)
    s_aend, s_halte, s_linie = s_aend.toPandas(), s_halte.toPandas(), s_linie.toPandas()
    t_spark = time.perf_counter() - t
    print(f"    Pandas {t_pandas:.0f} s, Spark {t_spark:.0f} s")

    # Pandas nennt die Spalte in je_linie "neu" und hat route_id als Spalte
    return all([gleich("aenderungen", p_aend, s_aend), gleich("halte", p_halte, s_halte),
                gleich("je_linie", p_linie, s_linie)])


def pruefe_abfahrten(spark, s: dict) -> bool:
    """Abfahrten je Stunde: Pandas (wie Phase 3) gegen das Parquet aus spark/abfahrten.py."""
    from pyspark.sql import functions as F
    from gtfs import lies_stand as lies_zip
    from lade_postgres import abfahrten_je_stunde, feed_info, horizont

    stand = lies_zip(s["zip"])
    von, bis = horizont(s["abgerufen_utc"], feed_info(stand)[2])
    print(f"  Abfahrten {s['stand_id']} ({von} bis {bis})")
    p = abfahrten_je_stunde(stand, von, bis)
    sp = (lies(spark, "abfahrten", s["stand_id"])
          .groupBy(F.col("kalendertag").alias("datum"), "stunde", "station_id", "route_id")
          .agg(F.count("*").alias("anzahl")).toPandas())
    return gleich("abfahrten", p, sp)


def main() -> int:
    parser = argparse.ArgumentParser(description="Pandas gegen Spark, Zeile für Zeile")
    parser.add_argument("--alle", action="store_true", help="alle Standpaare statt der Paare 2 bis 4")
    parser.add_argument("--ohne-abfahrten", action="store_true")
    args = parser.parse_args()

    alle = staende()
    paare = list(zip(alle, alle[1:]))
    if not args.alle:
        paare = paare[1:4]
    spark = sitzung("kvv-vergleich")
    spark.sparkContext.setLogLevel("ERROR")

    print(f"Vergleich Pandas gegen Spark, {len(paare)} Standpaare")
    ok, cache = True, {}
    for a, n in paare:
        ok &= pruefe_paar(spark, a, n, cache)
        cache.pop(a["stand_id"], None)
    if not args.ohne_abfahrten:
        ok &= pruefe_abfahrten(spark, alle[-1])
    spark.stop()
    print("Ergebnis: GLEICH" if ok else "Ergebnis: UNTERSCHIEDE GEFUNDEN")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
