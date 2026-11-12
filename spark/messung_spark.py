"""
Dieselbe Messung wie analyse/messung.py, diesmal mit Spark (Phase 5, Aufgabe 8).
Autor: Rustam T.

Gemessen wird der komplette Vergleich aller Standpaare aus Parquet, also
genau die Arbeit von spark/aenderungen.py ohne Datenbank. Damit Spark wirklich
rechnet und nicht nur einen Plan aufstellt, zähle ich alle drei Ergebnisse.
Der Speicher zählt den Python-Prozess und die Java-VM (Kindprozess) zusammen.

Getrennt davon zwei Zahlen, die in der Pandas-Messung kein Gegenstück haben:
- der Start der Spark-Sitzung (JVM hochfahren), einmal je Lauf
- eine Abfrage über alle Stände auf einmal: Wie viele trip_id gibt es in
  jedem Stand, wie viele nur in einem Teil? Das ist die Art Frage, für die
  Spark gebaut ist. Pandas müsste dafür alle ZIPs nacheinander öffnen.

Die Umwandlung ZIP -> Parquet (spark/parquet.py) gehört nicht dazu. Sie
passiert einmal je Stand und wird dort gemessen.

Aufruf im Container:
    docker compose run --rm spark python3 spark/messung_spark.py --json data/messung_spark.json
"""

import argparse
import json
import sys
import time
from pathlib import Path

from pyspark.sql import functions as F

from diff_spark import vergleiche_staende
from sitzung import PARQUET, fertig, lies_stand, sitzung, staende


def miss_spark(spark, paare: list[tuple[dict, dict]]) -> list[dict]:
    from lade_aenderungen import fenster_fuer
    from abfahrten import feed_bis

    ergebnis = []
    for a, n in paare:
        t = time.perf_counter()
        alt, neu = lies_stand(spark, a["stand_id"]), lies_stand(spark, n["stand_id"])
        fenster = fenster_fuer({"neu_zeit": n["abgerufen_utc"], "alt_feed_bis": feed_bis(alt),
                                "neu_feed_bis": feed_bis(neu)})
        _, _, aend, halte, je_linie = vergleiche_staende(spark, alt, neu, fenster.ab, fenster.bis)
        anzahl = aend.count()
        halte.count(), je_linie.count()
        ergebnis.append({"paar": f"{a['stand_id']} -> {n['stand_id']}", "aenderungen": anzahl,
                         "sekunden": round(time.perf_counter() - t, 1)})
        spark.catalog.clearCache()
    return ergebnis


def trip_ids_ueber_alle(spark) -> dict:
    """Eine Abfrage über das ganze Archiv: In wie vielen Ständen kommt jede trip_id vor?

    data/parquet/trips als Ganzes gelesen liefert die Spalte "stand" aus den
    Ordnernamen mit (Partitionen). Kein Schleifen über Dateien nötig.
    """
    t = time.perf_counter()
    trips = spark.read.parquet(str(PARQUET / "trips"))
    n_staende = trips.select("stand").distinct().count()
    je_id = trips.groupBy("trip_id").agg(F.countDistinct("stand").alias("staende"))
    z = je_id.agg(F.count("*").alias("ids"),
                  F.sum((F.col("staende") == n_staende).cast("int")).alias("in_allen"),
                  F.sum((F.col("staende") == 1).cast("int")).alias("in_einem")).first()
    return {"staende": n_staende, "trip_ids": z["ids"], "in_allen": z["in_allen"], "nur_in_einem": z["in_einem"],
            "sekunden": round(time.perf_counter() - t, 1)}


def main() -> int:
    from messung import Speicheruhr

    parser = argparse.ArgumentParser(description="Spark-Messung über alle Standpaare")
    parser.add_argument("--json", type=Path, help="Ergebnis zusätzlich als JSON speichern")
    args = parser.parse_args()

    alle = [s for s in staende() if fertig("stop_times", s["stand_id"])]
    if len(alle) < 2:
        raise SystemExit("Mindestens zwei Stände als Parquet nötig. Erst spark/parquet.py laufen lassen.")

    erg = {"staende": len(alle)}
    with Speicheruhr() as uhr:
        t = time.perf_counter()
        spark = sitzung("kvv-messung")
        spark.sparkContext.setLogLevel("ERROR")
        erg["start_sekunden"] = round(time.perf_counter() - t, 1)
        t = time.perf_counter()
        erg["paare"] = miss_spark(spark, list(zip(alle, alle[1:])))
        erg["sekunden_gesamt"] = round(time.perf_counter() - t, 1)
        erg["trip_ids"] = trip_ids_ueber_alle(spark)
        spark.stop()
    erg["spitze_mb"] = uhr.mb

    print(f"Stände als Parquet: {erg['staende']}, Start der Sitzung {erg['start_sekunden']} s")
    for p in erg["paare"]:
        print(f"  {p['paar']}: {p['aenderungen']} Änderungen, {p['sekunden']} s")
    print(f"Spark gesamt: {erg['sekunden_gesamt']} s (ohne Start), Spitze Arbeitsspeicher {erg['spitze_mb']} MB")
    ti = erg["trip_ids"]
    print(f"trip_id über alle {ti['staende']} Stände: {ti['trip_ids']} verschiedene, {ti['in_allen']} in allen, "
          f"{ti['nur_in_einem']} nur in einem, {ti['sekunden']} s")
    if args.json:
        args.json.write_text(json.dumps(erg, indent=2, ensure_ascii=False), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
