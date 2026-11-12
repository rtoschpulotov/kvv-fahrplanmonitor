"""
Änderungen zwischen Ständen mit Spark nach PostgreSQL (Phase 5, Aufgabe 6).
Autor: Rustam T.

Das Gegenstück zu laden/lade_aenderungen.py: dieselben offenen Standpaare,
dieselben Tabellen, dieselbe Ladeprozedur lade_aenderung() aus Phase 4. Nur
gerechnet wird mit Spark aus Parquet, und die Ergebnisse gehen über JDBC in
die Staging-Tabellen.

Ablauf je Standpaar:
1. Staging leeren (psycopg).
2. Spark rechnet und schreibt die drei Ergebnisse über JDBC in stg_aenderung,
   stg_aenderung_halt und stg_vergleich_linie.
3. In einer Transaktion (psycopg): Zeile in dim_standpaar anlegen und
   lade_aenderung() aufrufen. Erst hier entstehen die Fakten.

Warum nicht alles über JDBC? Spark schreibt jede Partition in einer eigenen
Datenbankverbindung und Transaktion. Würde Spark direkt in die Faktentabellen
schreiben, könnte ein Abbruch einen halben Vergleich hinterlassen. Über
Staging bleibt die Regel aus Phase 4 bestehen: ein Standpaar, eine Transaktion.

Aufruf im Container (Postgres muss laufen, Parquet muss da sein):
    docker compose run --rm spark python3 spark/aenderungen.py
    docker compose run --rm spark python3 spark/aenderungen.py --alle-neu
"""

import argparse
import os
import sys
import time

from pyspark.sql import DataFrame
from pyspark.sql import functions as F

from diff_spark import vergleiche_staende
from sitzung import REGISTER, fertig, lies_stand, sitzung


def jdbc_url() -> str:
    host = os.environ.get("POSTGRES_HOST", "127.0.0.1")
    port = os.environ.get("POSTGRES_PORT", "5433")
    return f"jdbc:postgresql://{host}:{port}/{os.environ['POSTGRES_DB']}"


def schreibe_jdbc(df: DataFrame, tabelle: str) -> None:
    """Anhängen an eine Staging-Tabelle. Die Tabelle existiert (sql/08), Spark legt nichts an.

    batchsize: so viele Zeilen schickt der Treiber auf einmal. Mit dem
    Standardwert 1.000 wären es bei 2.400 Zeilen drei Runden, das passt.
    """
    (df.write.format("jdbc")
       .option("url", jdbc_url())
       .option("dbtable", tabelle)
       .option("user", os.environ["POSTGRES_USER"])
       .option("password", os.environ.get("POSTGRES_PASSWORD", ""))
       .option("driver", "org.postgresql.Driver")
       .mode("append")
       .save())


def lade_paar(spark, conn, paar: dict) -> tuple[int, dict]:
    from lade_aenderungen import STG, fenster_fuer, trage_standpaar_ein

    for sid in (paar["alt_id"], paar["neu_id"]):
        if not fertig("stop_times", sid):
            raise SystemExit(f"Stand {sid} fehlt als Parquet. Erst spark/parquet.py laufen lassen.")
    fenster = fenster_fuer(paar)
    f_alt, f_neu, aend, halte, je_linie = vergleiche_staende(
        spark, lies_stand(spark, paar["alt_id"]), lies_stand(spark, paar["neu_id"]), fenster.ab, fenster.bis)

    n_alt, n_neu = f_alt.count(), f_neu.count()
    ids_alt, ids_neu = f_alt.select("trip_id").distinct(), f_neu.select("trip_id").distinct()
    trip_ids = (ids_alt.exceptAll(ids_neu).count(), ids_neu.exceptAll(ids_alt).count())
    geaendert = je_linie.agg(F.sum("geaendert")).first()[0] or 0

    conn.execute("TRUNCATE " + ", ".join(STG))
    schreibe_jdbc(aend.select("kalendertag", "route_id", F.col("direction_id").cast("int").alias("richtung"),
                              "erste_station", "erste_abfahrt_sek", "betriebstag", "nr", "art", "detail",
                              "station", "verschiebung_min", "trip_id_alt", "trip_id_neu"), "stg_aenderung")
    schreibe_jdbc(halte.select("route_id", F.col("direction_id").cast("int").alias("richtung"), "erste_station",
                               "erste_abfahrt_sek", "art", "station"), "stg_aenderung_halt")
    schreibe_jdbc(je_linie.select("route_id", "fahrten_alt", "fahrten_neu", "geaendert",
                                  F.col("neu").alias("hinzu")), "stg_vergleich_linie")

    with conn.transaction(), conn.cursor() as cur:
        sk = trage_standpaar_ein(cur, paar, fenster, n_alt, n_neu, int(geaendert), trip_ids)
        cur.execute("CALL lade_aenderung(%s)", (sk,))
    arten = {r["art"]: r["count"] for r in aend.groupBy("art").count().collect()}
    return n_alt, arten


def main() -> int:
    from dotenv import load_dotenv
    from lade_aenderungen import offene_paare, synchronisiere_register, verwerfe_alle
    from lade_postgres import REPO, verbinde

    parser = argparse.ArgumentParser(description="Änderungen mit Spark nach PostgreSQL")
    parser.add_argument("--alle-neu", action="store_true", help="alle Standpaare verwerfen und neu rechnen")
    args = parser.parse_args()
    load_dotenv(REPO / ".env")

    with verbinde() as conn:
        if args.alle_neu:
            verwerfe_alle(conn)
        synchronisiere_register(conn, REGISTER)
        paare = offene_paare(conn)
        print(f"Änderungen (Spark): {len(paare)} Standpaare offen")
        if not paare:
            return 0
        spark = sitzung("kvv-aenderungen")
        spark.sparkContext.setLogLevel("ERROR")
        for paar in paare:
            start = time.perf_counter()
            n_alt, arten = lade_paar(spark, conn, paar)
            anzahl = f"{n_alt:,}".replace(",", ".")
            print(f"  {paar['alt_id']} -> {paar['neu_id']}: {anzahl} Fahrten im Fenster, "
                  f"{sum(arten.values())} Änderungen {arten}, {time.perf_counter() - start:.0f} s")
            spark.catalog.clearCache()
        spark.stop()
        print("Prüfabfragen:")
        for name, treffer in conn.execute("SELECT pruefung, treffer FROM v_pruefung").fetchall():
            print(f"  {'ok' if treffer == 0 else 'FEHLER':6} {name}: {treffer}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
