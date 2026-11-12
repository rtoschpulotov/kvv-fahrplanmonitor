"""
Gemeinsame Grundlage aller Spark-Jobs (Phase 5).
Autor: Rustam T.

Hier steht, wie eine Spark-Sitzung gebaut wird und wo die Parquet-Daten
liegen. Jeder Job holt sich beides von hier, damit die Einstellungen nicht
in fünf Dateien auseinanderlaufen.
"""

import os
import sys
from pathlib import Path

from pyspark.sql import DataFrame, SparkSession

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "analyse"))
sys.path.insert(0, str(REPO / "laden"))

PARQUET = Path(os.environ.get("KVV_PARQUET", REPO / "data" / "parquet"))
ROHDATEN = REPO / "data" / "raw"
REGISTER = REPO / "data" / "snapshot_register.csv"


def sitzung(name: str) -> SparkSession:
    """Spark im lokalen Modus (Festlegung der Aufgabe: kein Cluster).

    local[*] nutzt alle Kerne. Derselbe Code liefe auf einem Cluster, dort
    würde nur der master anders gesetzt.

    - driver.memory: Im lokalen Modus ist der Treiber zugleich der einzige
      Executor, sein Speicher ist also der ganze Spark-Speicher. 4 GB reichen
      für ein Standpaar mit Reserve, einstellbar über KVV_SPARK_SPEICHER.
    - shuffle.partitions: Spark teilt nach jedem Join und jeder Gruppierung
      standardmäßig in 200 Teile. Bei rund 3 Mio. Zeilen je Stand sind das
      winzige Häppchen mit viel Verwaltungsaufwand. 16 passen zu einem
      Laptop mit 4 bis 8 Kernen.
    - session.timeZone UTC: Ich rechne Zeiten als Sekunden und Daten als
      date, nie als Zeitstempel mit Zeitzone. UTC stellt sicher, dass Spark
      beim Umwandeln nicht still eine Zeitzone des Rechners einrechnet.
    """
    return (SparkSession.builder
            .appName(name)
            .master(os.environ.get("KVV_SPARK_MASTER", "local[*]"))
            .config("spark.driver.memory", os.environ.get("KVV_SPARK_SPEICHER", "4g"))
            .config("spark.sql.shuffle.partitions", "16")
            .config("spark.sql.session.timeZone", "UTC")
            .config("spark.ui.showConsoleProgress", "false")
            .getOrCreate())


def pfad(tabelle: str, stand_id: str) -> Path:
    """data/parquet/<tabelle>/stand=<id>, wie in der Aufgabe vorgegeben.

    stand=... ist die Schreibweise, an der Spark (und auch Pandas oder
    DuckDB) eine Partition erkennen. Liest man data/parquet/stop_times als
    Ganzes, bekommt jede Zeile automatisch eine Spalte "stand".
    """
    return PARQUET / tabelle / f"stand={stand_id}"


def fertig(tabelle: str, stand_id: str) -> bool:
    """Spark legt _SUCCESS erst an, wenn alle Dateien geschrieben sind."""
    return (pfad(tabelle, stand_id) / "_SUCCESS").exists()


def lies(spark: SparkSession, tabelle: str, stand_id: str) -> DataFrame:
    return spark.read.parquet(str(pfad(tabelle, stand_id)))


def lies_stand(spark: SparkSession, stand_id: str) -> dict[str, DataFrame]:
    """Die Tabellen eines Stands, die Betriebstage und Vergleich brauchen."""
    return {t: lies(spark, t, stand_id)
            for t in ("calendar", "calendar_dates", "trips", "stops", "stop_times", "feed_info")}


def staende() -> list[dict]:
    """Alle Stände mit Status "neu" aus dem Register, zeitlich sortiert (wie Phase 3)."""
    from lade_postgres import neue_staende
    return neue_staende(REGISTER, ROHDATEN)
