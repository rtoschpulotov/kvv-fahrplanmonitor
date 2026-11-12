"""
Jeden gesammelten Stand einmal von ZIP nach Parquet (Phase 5, Aufgabe 2).
Autor: Rustam T.

Spark kann keine ZIP-Archive lesen. Dieser Job packt jeden Stand in ein
temporäres Verzeichnis aus, liest jede GTFS-Datei als CSV und schreibt sie als
Parquet nach data/parquet/<datei>/stand=<stand_id>/.

Warum Parquet (Festlegung der Aufgabe): Eine CSV muss bei jedem Lesen Zeichen
für Zeichen zerlegt werden, ohne Datentypen. Parquet speichert spaltenweise,
komprimiert und mit Schema. Ein Job, der aus stop_times nur trip_id und
departure_time braucht, liest auch nur diese zwei Spalten von der Platte.
Geparst wird jeder Stand genau einmal, hier.

Idempotent: Ein Stand, dessen Tabellen alle schon eine _SUCCESS-Datei haben,
wird übersprungen (E18, warum nicht über verarbeitet_am in MongoDB).

Aufruf im Container:
    docker compose run --rm spark python3 spark/parquet.py
"""

import shutil
import sys
import tempfile
import time
import zipfile

from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F

from sitzung import fertig, pfad, sitzung, staende

# Datentypen für stop_times, wie in analyse/gtfs.py (STOP_TIMES_SPALTEN).
# Alle anderen Spalten und Dateien bleiben Text.
ZAHLEN = {"stop_sequence": "int", "pickup_type": "int", "drop_off_type": "int"}


def lies_csv(spark: SparkSession, datei: str) -> DataFrame:
    """Eine GTFS-Datei als DataFrame, alle Spalten zunächst als Text.

    - escape '"': GTFS schreibt ein Anführungszeichen im Text als "" (wie
      RFC 4180). Spark nimmt ohne diese Angabe einen Backslash an.
    - Das Byte-Order-Mark am Dateianfang entfernt Spark selbst (geprüft).
    """
    return (spark.read
            .option("header", True)
            .option("encoding", "UTF-8")
            .option("escape", '"')
            .option("inferSchema", False)
            .csv(datei))


def wie_pandas(df: DataFrame, tabelle: str) -> DataFrame:
    """Leere Felder so ablegen, wie die Pandas-Variante sie liest.

    Pandas liest alle Dateien außer stop_times mit keep_default_na=False:
    leer bleibt "" (analyse/gtfs.py). Spark macht aus einem leeren Feld
    dagegen immer NULL. Damit beide Varianten mit denselben Daten rechnen,
    wird das hier angeglichen. In stop_times ist leer bei Pandas fehlend
    (NaN), dort bleibt NULL richtig, und die Zahlenspalten bekommen ihren Typ.
    """
    if tabelle == "stop_times":
        for spalte, typ in ZAHLEN.items():
            if spalte in df.columns:
                df = df.withColumn(spalte, F.col(spalte).cast(typ))
        return df
    return df.select([F.coalesce(F.col(c), F.lit("")).alias(c) for c in df.columns])


def wandle_um(spark: SparkSession, stand: dict) -> list[str]:
    """Alle Dateien eines Stands nach Parquet. Gibt die Tabellennamen zurück."""
    tmp = tempfile.mkdtemp(prefix="kvv_")
    try:
        with zipfile.ZipFile(stand["zip"]) as z:
            dateien = [n for n in z.namelist() if n.endswith(".txt")]
            z.extractall(tmp, members=dateien)
        tabellen = []
        for datei in sorted(dateien):
            tabelle = datei.removesuffix(".txt")
            df = wie_pandas(lies_csv(spark, f"{tmp}/{datei}"), tabelle)
            # Wenige große Dateien statt vieler kleiner (Fallstrick der Aufgabe).
            # stop_times hat rund 3 Mio. Zeilen, als Parquet gut 20 MB. Das
            # passt bequem in eine Datei, alle anderen Tabellen sowieso.
            df.coalesce(1).write.mode("overwrite").parquet(str(pfad(tabelle, stand["stand_id"])))
            tabellen.append(tabelle)
        return tabellen
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def offen(stand: dict) -> bool:
    """Fehlt für diesen Stand noch mindestens eine Tabelle?"""
    with zipfile.ZipFile(stand["zip"]) as z:
        tabellen = [n.removesuffix(".txt") for n in z.namelist() if n.endswith(".txt")]
    return not all(fertig(t, stand["stand_id"]) for t in tabellen)


def main() -> int:
    alle = [s for s in staende() if s["zip"].exists()]
    todo = [s for s in alle if offen(s)]
    print(f"Parquet: {len(alle)} Stände in data/raw, davon {len(todo)} noch nicht umgewandelt")
    if not todo:
        return 0
    spark = sitzung("kvv-parquet")
    spark.sparkContext.setLogLevel("ERROR")
    for s in todo:
        start = time.perf_counter()
        tabellen = wandle_um(spark, s)
        print(f"  {s['stand_id']}: {len(tabellen)} Tabellen, {time.perf_counter() - start:.0f} s")
    spark.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
