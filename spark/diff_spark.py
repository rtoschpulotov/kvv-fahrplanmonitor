"""
Zwei Fahrplanstände in Spark vergleichen (Phase 5, Aufgabe 4).
Autor: Rustam T.

Die Logik aus analyse/diff.py (E15, E16), übersetzt in Spark. Begriffe,
Änderungsarten und Fenster sind dieselben, deshalb wiederhole ich sie hier
nicht. Kommentiert ist vor allem, wo Spark anders denkt als Pandas:

- Fehlt ein Element, gibt try_element_at NULL zurück. Der einfache Zugriff
  arr[0] bricht in Spark 4 (ANSI-Modus) bei einem leeren Array mit Fehler ab.
- Spark hat keine Reihenfolge. Was in Pandas "die erste Zeile" oder
  "sortieren und durchzählen" ist, braucht in Spark ein Fenster mit einer
  ausdrücklichen Sortierung.
- Spark kennt keine Python-Schleifen über Zeilen. Der Inhaltsvergleich, den
  Pandas in _inhalt() mit einer Schleife macht, läuft hier mit Funktionen auf
  Arrays (transform, filter, arrays_zip), direkt in der JVM.
- Spark rechnet erst, wenn ein Ergebnis gebraucht wird (lazy). Die Funktionen
  hier bauen nur den Rechenplan. Gerechnet wird beim Schreiben oder Zählen.

Ob am Ende exakt dasselbe herauskommt, prüft spark/vergleich.py.
"""

from datetime import timedelta

from pyspark.sql import Column, DataFrame, SparkSession
from pyspark.sql import functions as F
from pyspark.sql.window import Window

from gtfs_spark import TAG, betriebstage, in_sekunden, station_je_halt

MUSTER = ["route_id", "direction_id", "erste_station", "erste_abfahrt_sek"]
SCHLUESSEL = MUSTER + ["betriebstag"]
K = SCHLUESSEL + ["nr"]
MINDEST_VERSCHIEBUNG_SEK = 60


# ---------------------------------------------------------------- Fahrten eines Stands

def fahrtverlaeufe(stop_times: DataFrame, stops: DataFrame) -> DataFrame:
    """Je trip_id: erste Station, erste Abfahrt, Stationen und Zeiten als Arrays.

    collect_list sammelt die Halte einer Fahrt, aber in zufälliger Reihenfolge.
    Deshalb sammle ich (stop_sequence, station, sek) als Struktur und sortiere
    das Array danach. array_sort sortiert Strukturen nach dem ersten Feld.
    """
    halte = (stop_times.join(station_je_halt(stops), "stop_id", "left")
             .select("trip_id", "stop_sequence", F.col("station_id").alias("station"),
                     # Abfahrt, am letzten Halt die Ankunft (wie Pandas)
                     in_sekunden(F.coalesce("departure_time", "arrival_time")).alias("sek")))
    h = F.col("h")
    return (halte.groupBy("trip_id")
            .agg(F.array_sort(F.collect_list(F.struct("stop_sequence", "station", "sek"))).alias("h"))
            .select(
                "trip_id",
                # Pandas nimmt mit first() den ersten Wert, der nicht fehlt.
                F.try_element_at(F.filter(h, lambda x: x.station.isNotNull()), F.lit(1)).station.alias("erste_station"),
                F.try_element_at(F.filter(h, lambda x: x.sek.isNotNull()), F.lit(1)).sek.alias("erste_abfahrt_sek"),
                F.transform(h, lambda x: x.station).alias("stationen"),
                F.transform(h, lambda x: F.coalesce(x.sek, F.lit(-1))).alias("zeiten")))


def fahrten(spark: SparkSession, stand: dict, verlauf: DataFrame, ab, bis) -> DataFrame:
    """Alle Fahrt-Instanzen im Fenster (E16), eine Zeile je Fahrt und Betriebstag.

    ab ist die Uhrzeit des Abrufs in deutscher Zeit ohne Zeitzone, bis der
    letzte gemeinsame Kalendertag. Statt Zeitstempel zu vergleichen, rechne
    ich den Beginn jeder Fahrt in Sekunden ab Mitternacht des Abruftags:
    (Betriebstag minus Abruftag) mal 86.400 plus Abfahrtssekunden. Eine Fahrt
    liegt im Fenster, wenn dieser Wert größer ist als die Uhrzeit des Abrufs.
    """
    ab_tag = ab.date()
    ab_sek = ab.hour * 3600 + ab.minute * 60 + ab.second
    tage = betriebstage(spark, stand["calendar"], stand["calendar_dates"], ab_tag - timedelta(days=1), bis)
    f = (stand["trips"].select("trip_id", "route_id", "service_id", "direction_id")
         .join(verlauf.select("trip_id", "erste_station", "erste_abfahrt_sek"), "trip_id")
         .join(tage.withColumnRenamed("datum", "betriebstag"), "service_id"))
    beginn = F.datediff("betriebstag", F.lit(ab_tag)) * TAG + F.col("erste_abfahrt_sek")
    kalendertag = F.date_add("betriebstag", F.floor(F.col("erste_abfahrt_sek") / TAG).cast("int"))
    return (f.withColumn("kalendertag", kalendertag)
            .where((beginn > ab_sek) & (F.col("kalendertag") <= F.lit(bis)))
            .drop("service_id"))


def _wie_python(arr: Column, text: bool) -> Column:
    """Ein Array so als Text, wie Python ein Tupel ausgibt: ('a', 'b') oder (1, 2).

    Pandas sortiert gleiche Fahrtschlüssel nach str(stationen) + str(zeiten)
    (diff.eindeutig). Damit die laufende Nummer in Spark exakt dieselbe wird,
    muss der Sortiertext Zeichen für Zeichen gleich sein, einschließlich der
    Python-Eigenheit, dass ein Tupel mit einem Element ein Komma bekommt: ('a',).
    """
    teile = F.transform(arr, lambda x: F.concat(F.lit("'"), x, F.lit("'")) if text else x.cast("string"))
    innen = F.array_join(teile, ", ")
    return (F.when(F.size(arr) == 1, F.concat(F.lit("("), innen, F.lit(",)")))
             .otherwise(F.concat(F.lit("("), innen, F.lit(")"))))


def eindeutig(f: DataFrame, verlauf: DataFrame) -> DataFrame:
    """Laufende Nummer nr für Fahrten mit gleichem Schlüssel (wie diff.eindeutig).

    row_number() über ein Fenster je Schlüssel ist das Gegenstück zu
    sort_values() plus cumcount(). Sortiert wird nach Verlauf und bei
    Gleichstand nach trip_id, genau wie in Pandas.
    """
    sortierung = verlauf.select("trip_id", F.concat(_wie_python(F.col("stationen"), True),
                                                    _wie_python(F.col("zeiten"), False)).alias("sortierung"))
    fenster = Window.partitionBy(*SCHLUESSEL).orderBy("sortierung", "trip_id")
    return (f.join(sortierung, "trip_id")
            .withColumn("nr", F.row_number().over(fenster) - 1)
            .drop("sortierung"))


# ---------------------------------------------------------------- Vergleich

def _inhalt(a_st: Column, a_z: Column, n_st: Column, n_z: Column) -> Column:
    """Vergleich zweier Verläufe derselben Fahrt (wie diff._inhalt), als Spark-Ausdruck.

    Ergebnis ist eine Struktur (art, verschiebung_min, station, stationen),
    oder NULL, wenn beide Verläufe gleich sind.
    """
    # Halteverlauf: Stationen weggefallen oder dazugekommen.
    # array_except liefert wie Pythons set() jede Station nur einmal.
    weg = F.array_except(a_st, n_st)
    dazu = F.array_except(n_st, a_st)
    betroffen_hv = F.array_sort(F.array_union(weg, dazu))
    betroffen_hv = F.when(F.size(betroffen_hv) > 0, betroffen_hv).otherwise(F.array_sort(F.array_union(a_st, n_st)))
    erste_hv = F.coalesce(
        F.try_element_at(F.filter(n_st, lambda s: F.array_contains(dazu, s)), F.lit(1)),
        F.try_element_at(F.filter(a_st, lambda s: F.array_contains(weg, s)), F.lit(1)),
        F.try_element_at(betroffen_hv, F.lit(1)))

    # Zeit: Halt für Halt vergleichen. arrays_zip ist zip() aus Python.
    paare = F.arrays_zip(a_st.alias("s"), a_z.alias("az"), n_z.alias("nz"))
    diffs = F.transform(
        F.filter(paare, lambda p: (p.az >= 0) & (p.nz >= 0) & (F.abs(p.nz - p.az) >= MINDEST_VERSCHIEBUNG_SEK)),
        lambda p: F.struct(p.s.alias("s"), (p.nz - p.az).alias("d")))
    # Python max() nimmt bei Gleichstand das erste Element. Deshalb erst den
    # größten Betrag bestimmen, dann das erste Element mit diesem Betrag.
    groesster = F.array_max(F.transform(diffs, lambda x: F.abs(x.d)))
    groesste = F.try_element_at(F.filter(diffs, lambda x: F.abs(x.d) == groesster), F.lit(1)).d
    # Python round() rundet bei .5 zur geraden Zahl (90 s -> 2 min, 150 s -> 2 min).
    # Sparks round() rundet .5 immer auf, bround() wie Python.
    minuten = F.bround(groesste / 60.0, 0).cast("int")

    return (F.when(a_st != n_st,
                   F.struct(F.lit("halteverlauf").alias("art"), F.lit(None).cast("int").alias("verschiebung_min"),
                            erste_hv.alias("station"), betroffen_hv.alias("stationen")))
             .when(F.size(diffs) > 0,
                   F.struct(F.lit("zeit").alias("art"), minuten.alias("verschiebung_min"),
                            F.try_element_at(diffs, F.lit(1)).s.alias("station"),
                            F.array_sort(F.array_distinct(F.transform(diffs, lambda x: x.s))).alias("stationen"))))


def vergleiche(alt: DataFrame, neu: DataFrame, verlauf_alt: DataFrame, verlauf_neu: DataFrame):
    """Vergleicht die Fahrt-Instanzen zweier Stände im selben Fenster.

    Gibt dieselben drei Tabellen zurück wie diff.vergleiche: aenderungen,
    halte, je_linie.
    """
    a = eindeutig(alt, verlauf_alt).select(*K, F.col("trip_id").alias("trip_id_alt"),
                                           F.col("kalendertag").alias("kalendertag_alt"))
    n = eindeutig(neu, verlauf_neu).select(*K, F.col("trip_id").alias("trip_id_neu"),
                                           F.col("kalendertag").alias("kalendertag_neu"))
    m = a.join(n, K, "full_outer")

    # Gibt es das Muster (ohne Tag) im anderen Stand überhaupt? Ein kleiner
    # Join statt der Python-Menge muster_neu.
    muster_alt = alt.select(*MUSTER).distinct().withColumn("im_alt", F.lit(True))
    muster_neu = neu.select(*MUSTER).distinct().withColumn("im_neu", F.lit(True))
    m = m.join(muster_alt, MUSTER, "left").join(muster_neu, MUSTER, "left")

    nur_alt = m.where(F.col("trip_id_neu").isNull()).select(
        *K, F.col("kalendertag_alt").alias("kalendertag"),
        F.when(F.col("im_neu"), "betriebstage").otherwise("entfallen").alias("art"),
        F.when(F.col("im_neu"), "Tag entfällt").alias("detail"),
        F.lit(None).cast("int").alias("verschiebung_min"), F.lit(None).cast("string").alias("station"),
        "trip_id_alt", F.lit(None).cast("string").alias("trip_id_neu"))
    nur_neu = m.where(F.col("trip_id_alt").isNull()).select(
        *K, F.col("kalendertag_neu").alias("kalendertag"),
        F.when(F.col("im_alt"), "betriebstage").otherwise("neu").alias("art"),
        F.when(F.col("im_alt"), "Tag kommt dazu").alias("detail"),
        F.lit(None).cast("int").alias("verschiebung_min"), F.lit(None).cast("string").alias("station"),
        F.lit(None).cast("string").alias("trip_id_alt"), "trip_id_neu")

    # Gleiche Fahrt in beiden Ständen, aber verschiedene trip_id: Inhalt
    # vergleichen, und zwar je trip_id-Paar nur einmal (wie der cache in Pandas).
    beide = m.where(F.col("trip_id_alt").isNotNull() & F.col("trip_id_neu").isNotNull()
                    & (F.col("trip_id_alt") != F.col("trip_id_neu")))
    va = verlauf_alt.select(F.col("trip_id").alias("trip_id_alt"), F.col("stationen").alias("a_st"),
                            F.col("zeiten").alias("a_z"))
    vn = verlauf_neu.select(F.col("trip_id").alias("trip_id_neu"), F.col("stationen").alias("n_st"),
                            F.col("zeiten").alias("n_z"))
    inhalt = (beide.select("trip_id_alt", "trip_id_neu").distinct()
              .join(va, "trip_id_alt").join(vn, "trip_id_neu")
              .select("trip_id_alt", "trip_id_neu",
                      _inhalt(F.col("a_st"), F.col("a_z"), F.col("n_st"), F.col("n_z")).alias("e"))
              .where(F.col("e").isNotNull()))
    geaendert = beide.join(inhalt, ["trip_id_alt", "trip_id_neu"]).select(
        *K, F.col("kalendertag_alt").alias("kalendertag"), F.col("e.art").alias("art"),
        F.lit(None).cast("string").alias("detail"), F.col("e.verschiebung_min").alias("verschiebung_min"),
        F.col("e.station").alias("station"), "trip_id_alt", "trip_id_neu")

    aend = nur_alt.unionByName(nur_neu).unionByName(geaendert).cache()

    # Betroffene Stationen je Muster und Art, über alle Tage vereinigt (E18).
    stationen_inhalt = inhalt.select("trip_id_alt", "trip_id_neu", F.col("e.stationen").alias("st_inhalt"))
    halte = (aend.join(stationen_inhalt, ["trip_id_alt", "trip_id_neu"], "left")
             .join(va.select("trip_id_alt", "a_st"), "trip_id_alt", "left")
             .join(vn.select("trip_id_neu", "n_st"), "trip_id_neu", "left")
             .select(*MUSTER, "art",
                     F.explode(F.when(F.col("art").isin("halteverlauf", "zeit"), F.col("st_inhalt"))
                                .when(F.col("trip_id_neu").isNotNull(), F.col("n_st"))
                                .otherwise(F.col("a_st"))).alias("station"))
             .distinct())

    # Je Linie: Fahrten alt und neu, geändert (betrifft eine alte Fahrt) und neu
    betrifft_alt = (F.col("art").isin("entfallen", "halteverlauf", "zeit")
                    | ((F.col("art") == "betriebstage") & (F.coalesce(F.col("detail"), F.lit("")) == "Tag entfällt")))
    zaehlung = aend.groupBy("route_id").agg(F.sum(betrifft_alt.cast("int")).alias("geaendert"),
                                            F.sum((~betrifft_alt).cast("int")).alias("neu"))
    je_linie = (alt.groupBy("route_id").count().withColumnRenamed("count", "fahrten_alt")
                .join(neu.groupBy("route_id").count().withColumnRenamed("count", "fahrten_neu"), "route_id", "full_outer")
                .join(zaehlung, "route_id", "left")
                .select("route_id", *[F.coalesce(F.col(c), F.lit(0)).cast("long").alias(c)
                                      for c in ("fahrten_alt", "fahrten_neu", "geaendert", "neu")]))
    return aend, halte, je_linie


def vergleiche_staende(spark: SparkSession, alt: dict, neu: dict, ab, bis):
    """Bequemer Einstieg: zwei Stände (Tabellen aus sitzung.lies_stand) und das Fenster."""
    va = fahrtverlaeufe(alt["stop_times"], alt["stops"]).cache()
    vn = fahrtverlaeufe(neu["stop_times"], neu["stops"]).cache()
    f_alt = fahrten(spark, alt, va, ab, bis).cache()
    f_neu = fahrten(spark, neu, vn, ab, bis).cache()
    return (f_alt, f_neu) + vergleiche(f_alt, f_neu, va, vn)
