"""
Betriebstage und Abfahrten in Spark (Phase 5, Aufgabe 3).
Autor: Rustam T.

Dieselbe Logik wie analyse/betriebstage.py, Schritt für Schritt übersetzt.
Wo Pandas und Spark sich unterscheiden, steht es im Kommentar. Ob beide
dasselbe rechnen, prüft spark/vergleich.py automatisch.

Grundsatz wie in Phase 2: Uhrzeiten über 24 Uhr werden in Sekunden seit
Beginn des Betriebstags umgerechnet, nie in einen Zeitstempel-Typ. Ein
Zeitpunkt ist bei mir das Paar (Betriebstag, Sekunden). Den Kalendertag
bekomme ich mit Ganzzahl-Division: 90.600 Sekunden (25:10 Uhr) sind ein Tag
und 4.200 Sekunden, also der Folgetag um 01:10.
"""

from datetime import date

from pyspark.sql import Column, DataFrame, SparkSession
from pyspark.sql import functions as F
from pyspark.sql.window import Window

WOCHENTAGE = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
TAG = 86_400


def als_datum(spalte: str) -> Column:
    """GTFS schreibt Daten als JJJJMMTT, also "20261103"."""
    return F.to_date(F.col(spalte), "yyyyMMdd")


def betriebstage(spark: SparkSession, calendar: DataFrame, calendar_dates: DataFrame,
                 von: date, bis: date) -> DataFrame:
    """Alle Betriebstage im Zeitraum [von, bis] als (service_id, datum).

    Wie in Pandas: regulärer Plan aus calendar, dazu exception_type 1,
    abzüglich exception_type 2.
    """
    # Alle Tage des Zeitraums mit Wochentag. weekday() zählt wie Pandas
    # dayofweek: Montag 0 bis Sonntag 6. (dayofweek() in Spark zählt anders,
    # Sonntag 1 bis Samstag 7. Eine typische Stolperfalle beim Übersetzen.)
    tage = (spark.sql(f"SELECT explode(sequence(DATE'{von}', DATE'{bis}')) AS datum")
            .withColumn("wochentag", F.weekday("datum")))

    # Die sieben Wochentagsspalten werden zu Zeilen: posexplode liefert zur
    # Spalte "faehrt" gleich die Position 0 bis 6 mit, also den Wochentag.
    lang = (calendar
            .select("service_id",
                    als_datum("start_date").alias("start"),
                    als_datum("end_date").alias("ende"),
                    F.posexplode(F.array(*WOCHENTAGE)).alias("wochentag", "faehrt"))
            .where(F.col("faehrt") == "1"))
    regulaer = (lang.join(tage, "wochentag")
                .where(F.col("datum").between(F.col("start"), F.col("ende")))
                .select("service_id", "datum"))

    ausn = (calendar_dates
            .select("service_id", als_datum("date").alias("datum"), "exception_type")
            .where(F.col("datum").between(F.lit(von), F.lit(bis))))
    dazu = ausn.where(F.col("exception_type") == "1").select("service_id", "datum")
    weg = ausn.where(F.col("exception_type") == "2").select("service_id", "datum")

    # "ohne Menge 3" ist in Spark ein eigener Join-Typ: left_anti behält die
    # Zeilen links, die rechts keinen Partner haben. In Pandas brauchte ich
    # dafür den Umweg über indicator=True.
    return regulaer.unionByName(dazu).distinct().join(weg.distinct(), ["service_id", "datum"], "left_anti")


def in_sekunden(spalte: Column) -> Column:
    """ "25:10:00" -> 90600. NULL bleibt NULL."""
    teile = F.split(spalte, ":")
    return (teile[0].cast("int") * 3600 + teile[1].cast("int") * 60 + teile[2].cast("int")).cast("int")


def station_je_halt(stops: DataFrame) -> DataFrame:
    """stop_id -> station_id (E9). Ohne parent_station ist der Halt selbst die Station."""
    return stops.select(
        "stop_id",
        F.when(F.coalesce(F.col("parent_station"), F.lit("")) == "", F.col("stop_id"))
         .otherwise(F.col("parent_station")).alias("station_id"))


def abfahrten(stop_times: DataFrame, trips: DataFrame, stops: DataFrame, tage: DataFrame) -> DataFrame:
    """Jede Abfahrt an jedem Betriebstag aus `tage`, mit Kalendertag und Stunde.

    Regeln wie analyse/betriebstage.abfahrten (E9): letzter Halt einer Fahrt
    zählt nicht, kein Einstieg zählt nicht, Halt ohne Uhrzeit zählt nicht,
    mehrere Halte direkt hintereinander an derselben Station sind eine
    Abfahrt (die letzte, an der man einsteigen kann).

    Pandas arbeitet hier mit shift() auf einer sortierten Tabelle. Spark hat
    keine feste Reihenfolge, deshalb nimmt lag() über ein Fenster je Fahrt
    die Rolle von shift() ein.
    """
    je_fahrt = Window.partitionBy("trip_id").orderBy("stop_sequence")
    st = (stop_times.join(station_je_halt(stops), "stop_id", "left")
          .withColumn("neue_folge", (F.lag("station_id").over(je_fahrt).isNull()
                                     | (F.lag("station_id").over(je_fahrt) != F.col("station_id"))).cast("int"))
          # laufende Summe statt cumsum: Nummer der Folge innerhalb der Fahrt
          .withColumn("folge", F.sum("neue_folge").over(je_fahrt.rowsBetween(Window.unboundedPreceding, 0)))
          .withColumn("letzte_seq", F.max("stop_sequence").over(Window.partitionBy("trip_id"))))

    # Folge, die den letzten Halt enthält, ist das Fahrtende und keine Abfahrt
    endfolge = st.where(F.col("stop_sequence") == F.col("letzte_seq")).select("trip_id", F.col("folge").alias("endfolge"))
    st = (st.join(endfolge, "trip_id")
          .where((F.col("folge") != F.col("endfolge"))
                 & (F.coalesce(F.col("pickup_type"), F.lit(0)) != 1)
                 & F.col("departure_time").isNotNull()))
    # Je Folge nur die letzte übrige Zeile
    letzte = Window.partitionBy("trip_id", "folge").orderBy(F.col("stop_sequence").desc())
    st = (st.withColumn("rang", F.row_number().over(letzte)).where(F.col("rang") == 1)
          .select("trip_id", "stop_id", "station_id", "stop_sequence", "pickup_type",
                  in_sekunden(F.col("departure_time")).alias("abfahrt_sek")))

    st = (st.join(trips.select("trip_id", "route_id", "service_id"), "trip_id")
          .join(tage.withColumnRenamed("datum", "betriebstag"), "service_id"))
    return (st.withColumn("kalendertag", F.date_add("betriebstag", F.floor(F.col("abfahrt_sek") / TAG).cast("int")))
              .withColumn("stunde", (F.col("abfahrt_sek") % TAG / 3600).cast("int"))
              .drop("service_id"))
