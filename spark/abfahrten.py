"""
Alle Abfahrten in Kalenderzeit je Stand als Parquet (Phase 5, Aufgabe 3).
Autor: Rustam T.

Für jeden Stand, der schon als Parquet vorliegt, dieselben Abfahrten wie in
Phase 3 (laden/lade_postgres.py): ab dem Tag des Abrufs, 14 Tage, höchstens bis
zum Ende des Fahrplans (E13). Phase 3 zählt sie für PostgreSQL je Stunde zusammen,
hier bleibt jede einzelne Abfahrt erhalten. Darauf lassen sich später Fragen
stellen, für die die Stundenzählung zu grob ist, zum Beispiel Umsteigezeiten.

Ergebnis: data/parquet/abfahrten/stand=<id>/, rund 2 Mio. Zeilen je Stand.

Aufruf im Container:
    docker compose run --rm spark python3 spark/abfahrten.py
"""

import sys
import time
from datetime import date, datetime, timedelta

from pyspark.sql import functions as F

from gtfs_spark import abfahrten, betriebstage
from sitzung import fertig, lies_stand, pfad, sitzung, staende


def feed_bis(stand: dict) -> date | None:
    """Letzter Tag des Fahrplans laut feed_info (wie lade_postgres.feed_info)."""
    zeile = stand["feed_info"].select("feed_end_date").first()
    return datetime.strptime(zeile[0], "%Y%m%d").date() if zeile and zeile[0] else None


def main() -> int:
    from lade_postgres import horizont
    alle = [s for s in staende() if fertig("stop_times", s["stand_id"])]
    todo = [s for s in alle if not fertig("abfahrten", s["stand_id"])]
    print(f"Abfahrten: {len(alle)} Stände als Parquet, davon {len(todo)} noch ohne Abfahrten")
    if not todo:
        return 0
    spark = sitzung("kvv-abfahrten")
    spark.sparkContext.setLogLevel("ERROR")
    for s in todo:
        start = time.perf_counter()
        st = lies_stand(spark, s["stand_id"])
        von, bis = horizont(s["abgerufen_utc"], feed_bis(st))
        # Betriebstage ab dem Vortag: Eine Fahrt um 24:30 am Vortag liegt
        # schon im Horizont (wie in Phase 2 und 3).
        tage = betriebstage(spark, st["calendar"], st["calendar_dates"], von - timedelta(days=1), bis)
        ab = (abfahrten(st["stop_times"], st["trips"], st["stops"], tage)
              .where(F.col("kalendertag").between(F.lit(von), F.lit(bis))))
        # Sortiert schreiben: Parquet komprimiert sortierte Spalten besser, und
        # wer später nur einen Tag liest, findet ihn schneller.
        (ab.repartition(1).sortWithinPartitions("kalendertag", "stunde", "station_id")
           .write.mode("overwrite").parquet(str(pfad("abfahrten", s["stand_id"]))))
        n = spark.read.parquet(str(pfad("abfahrten", s["stand_id"]))).count()
        anzahl = f"{n:,}".replace(",", ".")
        print(f"  {s['stand_id']}: {von} bis {bis}, {anzahl} Abfahrten, {time.perf_counter() - start:.0f} s")
    spark.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
