"""
Rechnet Spark auf den Mini-Ständen dasselbe wie Pandas? (Phase 5)
Autor: Rustam T.

spark/vergleich.py prüft die Gleichheit auf echten Daten, braucht dafür aber
das ganze Archiv und einige Minuten. Diese Tests nehmen die konstruierten
Stände aus test_diff.py, in denen jede Änderungsart und jeder Sonderfall
vorkommt, und vergleichen Pandas und Spark Zeile für Zeile.

Ohne pyspark (also auf dem Windows-Rechner) werden sie übersprungen. Laufen
lassen im Container:
    docker compose run --rm spark python3 -m pytest tests/test_spark.py
"""

import sys
from pathlib import Path

import pandas as pd
import pytest

pytest.importorskip("pyspark")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "spark"))

import test_diff as td  # noqa: E402
from diff import fahrten as fahrten_pd, vergleiche as vergleiche_pd  # noqa: E402
from diff_spark import vergleiche_staende  # noqa: E402
from vergleich import SPALTEN, kanonisch  # noqa: E402

GANZZAHL = {"stop_sequence", "pickup_type", "drop_off_type"}


@pytest.fixture(scope="module")
def spark():
    from sitzung import sitzung
    s = sitzung("kvv-test")
    s.sparkContext.setLogLevel("ERROR")
    yield s
    s.stop()


def als_spark(spark, stand: dict) -> dict:
    """Pandas-Tabellen so nach Spark, wie spark/parquet.py sie ablegt: Text, nur drei Spalten als int."""
    aus = {}
    for name, df in stand.items():
        schema = ", ".join(f"`{c}` {'int' if c in GANZZAHL else 'string'}" for c in df.columns)
        werte = df.astype(object).where(df.notna(), None)
        werte = [tuple(int(v) if c in GANZZAHL and v is not None else (v if c in GANZZAHL else str(v))
                       for c, v in zip(df.columns, z)) for z in werte.itertuples(index=False, name=None)]
        aus[name] = spark.createDataFrame(werte, schema)
    return aus


def beide(spark, alt_def, neu_def, s_alt, s_neu):
    alt, va = td.stand(alt_def, s_alt)
    neu, vn = td.stand(neu_def, s_neu)
    p = vergleiche_pd(fahrten_pd(alt, va, td.FENSTER), fahrten_pd(neu, vn, td.FENSTER), va, vn)
    _, _, *s = vergleiche_staende(spark, als_spark(spark, alt), als_spark(spark, neu),
                                  td.FENSTER.ab, td.FENSTER.bis)
    return p, [x.toPandas() for x in s]


def gleich(p, s):
    for name, a, b in zip(("aenderungen", "halte", "je_linie"), p, s):
        assert kanonisch(a, SPALTEN[name]) == kanonisch(b, SPALTEN[name]), name


ZWEI_TAGE_ALT = {"X": ("R6", 0, "ZWEI", td.zeiten(9, "00:00", "10:00", "20:00"))}
ZWEI_TAGE_NEU = {
    "X1": ("R6", 0, "EINS", [("S1", "09:00:00"), ("S4", "09:05:00"), ("S2", "09:10:00"), ("S3", "09:20:00")]),
    "X2": ("R6", 0, "ACHT", [("S1", "09:00:00"), ("S2", "09:10:00"), ("S5", "09:15:00"), ("S3", "09:20:00")]),
}
VERSTAERKER = {"P": ("R5", 0, "EIN", td.zeiten(7, "30:00", "40:00", "50:00")),
               "Q": ("R5", 0, "EIN", td.zeiten(7, "30:00", "45:00", "55:00"))}


@pytest.mark.parametrize("alt_def, neu_def, s_alt, s_neu", [
    pytest.param(td.ALT, td.NEU, td.SERVICES_ALT, td.SERVICES_NEU, id="jede-aenderungsart"),
    pytest.param(td.ALT, td.ALT, td.SERVICES_ALT, td.SERVICES_ALT, id="gleicher-stand"),
    pytest.param(ZWEI_TAGE_ALT, ZWEI_TAGE_NEU, {"ZWEI": [17, 18]}, {"EINS": [17], "ACHT": [18]}, id="halte-vereinigt"),
    pytest.param(VERSTAERKER, VERSTAERKER, {"EIN": [17]}, {"EIN": [17]}, id="verstaerker"),
])
def test_spark_rechnet_wie_pandas(spark, alt_def, neu_def, s_alt, s_neu):
    p, s = beide(spark, alt_def, neu_def, s_alt, s_neu)
    gleich(p, s)


def test_spark_findet_jede_aenderungsart(spark):
    """Nicht nur gleich, sondern auch nicht leer: Sonst wäre der Vergleich oben wertlos."""
    _, (aend, halte, _) = beide(spark, td.ALT, td.NEU, td.SERVICES_ALT, td.SERVICES_NEU)
    assert sorted(aend["art"]) == sorted(["neu", "entfallen", "halteverlauf", "zeit", "betriebstage", "betriebstage"])
    assert set(halte[halte["art"] == "zeit"]["station"]) == {"S2"}


def test_betriebstage_wie_pandas(spark):
    """Wochentage, Ausnahmen dazu und weg: Spark und Pandas liefern dieselben Tage."""
    from datetime import date
    from betriebstage import betriebstage as bt_pd
    from gtfs_spark import betriebstage as bt_spark
    cal, dates = td.kalender(W="W", EIN=[17, 19])
    dates = pd.concat([dates, pd.DataFrame([{"service_id": "W", "date": "20261118", "exception_type": "2"}])])
    p = bt_pd(cal, dates, date(2026, 11, 15), date(2026, 11, 22))
    st = als_spark(spark, {"c": cal, "d": dates})
    s = bt_spark(spark, st["c"], st["d"], date(2026, 11, 15), date(2026, 11, 22)).toPandas()
    zeilen = lambda df: sorted((r.service_id, str(pd.Timestamp(r.datum).date())) for r in df.itertuples())
    assert zeilen(p) == zeilen(s)
    assert ("W", "2026-11-18") not in zeilen(s)
