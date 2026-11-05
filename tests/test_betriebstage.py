"""
Tests für die Betriebstag-Logik.
Autor: Rustam T.

Jeder Test baut sich ein winziges Beispiel von Hand, bei dem ich das richtige
Ergebnis ohne Code weiß. Die Fälle stammen aus der Aufgabenstellung von
Phase 2. November 2026 als Kalender:
Mo 2.11., Di 3.11., Mi 4.11., ... Sa 7.11., So 8.11., Mo 9.11.

Aufruf:
    pytest
"""

import pandas as pd
import pytest

from betriebstage import abfahrten, betriebstage, gtfs_zeit_in_sekunden


def kalender(*zeilen):
    """Zeilen als (service_id, "1111100", start, ende), Wochentage Mo bis So."""
    tage = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
    daten = []
    for sid, maske, start, ende in zeilen:
        z = {"service_id": sid, "start_date": start, "end_date": ende}
        z.update({t: m for t, m in zip(tage, maske)})
        daten.append(z)
    return pd.DataFrame(daten, columns=["service_id", *tage, "start_date", "end_date"])


def ausnahmen(*zeilen):
    return pd.DataFrame(zeilen, columns=["service_id", "date", "exception_type"])


def tage_von(ergebnis, sid):
    return sorted(ergebnis.loc[ergebnis["service_id"] == sid, "datum"].dt.strftime("%d.%m.").tolist())


WERKTAGE = kalender(("W", "1111100", "20261102", "20261113"))


def test_normaler_werktag():
    erg = betriebstage(WERKTAGE, ausnahmen(), "2026-11-02", "2026-11-08")
    assert tage_von(erg, "W") == ["02.11.", "03.11.", "04.11.", "05.11.", "06.11."]


def test_feiertag_faellt_weg_typ_2():
    # Mittwoch 4.11. als Feiertag angenommen
    erg = betriebstage(WERKTAGE, ausnahmen(("W", "20261104", "2")), "2026-11-02", "2026-11-08")
    assert "04.11." not in tage_von(erg, "W")
    assert len(tage_von(erg, "W")) == 4


def test_sonderverkehr_kommt_dazu_typ_1():
    # Samstag 7.11. zusätzlich, obwohl calendar Samstag nicht vorsieht
    erg = betriebstage(WERKTAGE, ausnahmen(("W", "20261107", "1")), "2026-11-02", "2026-11-08")
    assert "07.11." in tage_von(erg, "W")
    assert len(tage_von(erg, "W")) == 6


def test_dienst_nur_ueber_calendar_dates():
    # "S" steht nicht in calendar. Ein Join auf calendar würde ihn verlieren.
    erg = betriebstage(WERKTAGE, ausnahmen(("S", "20261108", "1")), "2026-11-02", "2026-11-08")
    assert tage_von(erg, "S") == ["08.11."]


def test_tag_ausserhalb_gueltigkeit():
    # Gültig bis 13.11., gefragt bis 17.11. Montag 16. und Dienstag 17. gehören nicht dazu.
    erg = betriebstage(WERKTAGE, ausnahmen(), "2026-11-12", "2026-11-17")
    assert tage_von(erg, "W") == ["12.11.", "13.11."]


def test_ausnahme_ausserhalb_des_zeitraums_wird_ignoriert():
    erg = betriebstage(WERKTAGE, ausnahmen(("W", "20261201", "1")), "2026-11-02", "2026-11-08")
    assert "01.12." not in tage_von(erg, "W")


def test_typ_1_auf_regulaerem_tag_erzeugt_keine_dublette():
    erg = betriebstage(WERKTAGE, ausnahmen(("W", "20261103", "1")), "2026-11-02", "2026-11-08")
    assert tage_von(erg, "W").count("03.11.") == 1


def test_leerer_calendar():
    leer = kalender()
    erg = betriebstage(leer, ausnahmen(("S", "20261108", "1")), "2026-11-02", "2026-11-08")
    assert tage_von(erg, "S") == ["08.11."]


@pytest.mark.parametrize("text,sekunden", [
    ("00:00:00", 0),
    ("06:02:00", 6 * 3600 + 120),
    ("25:10:00", 25 * 3600 + 600),
    ("29:25:00", 29 * 3600 + 1500),   # späteste Zeit im KVV-Feed vom 04.11.2026
])
def test_zeit_in_sekunden(text, sekunden):
    assert gtfs_zeit_in_sekunden(pd.Series([text])).iloc[0] == sekunden


def test_zeit_in_sekunden_als_kategorie_und_leer():
    s = pd.Series(["25:10:00", None, "06:00:00"], dtype="category")
    erg = gtfs_zeit_in_sekunden(s)
    assert erg.iloc[0] == 90600 and pd.isna(erg.iloc[1]) and erg.iloc[2] == 21600


# Eine Fahrt T über drei Halte, Betriebstag Montag 2.11.
STOPS = pd.DataFrame({
    "stop_id": ["A1", "A2", "B", "C"],
    "parent_station": ["A", "A", "", ""],
})
TRIPS = pd.DataFrame({"trip_id": ["T", "U"], "route_id": ["R", "R"], "service_id": ["W", "W"]})


def stop_times(*zeilen):
    df = pd.DataFrame(zeilen, columns=["trip_id", "stop_id", "stop_sequence", "departure_time", "pickup_type"])
    df["trip_id"] = df["trip_id"].astype("category")
    df["stop_id"] = df["stop_id"].astype("category")
    df["departure_time"] = df["departure_time"].astype("category")
    df["stop_sequence"] = df["stop_sequence"].astype("int32")
    df["pickup_type"] = df["pickup_type"].astype("Int8")
    return df


def test_abfahrt_nach_mitternacht_landet_am_folgetag():
    st = stop_times(("T", "A1", 1, "24:50:00", 0), ("T", "B", 2, "25:10:00", 0), ("T", "C", 3, "25:20:00", 0))
    tage = betriebstage(WERKTAGE, ausnahmen(), "2026-11-02", "2026-11-02")
    erg = abfahrten(st, TRIPS, STOPS, tage)
    b = erg[erg["stop_id"] == "B"].iloc[0]
    assert b["betriebstag"] == pd.Timestamp("2026-11-02")
    assert b["zeitpunkt"] == pd.Timestamp("2026-11-03 01:10")
    assert b["kalendertag"] == pd.Timestamp("2026-11-03")
    assert b["stunde"] == 1


def test_letzter_halt_und_kein_einstieg_zaehlen_nicht():
    st = stop_times(("T", "A1", 1, "08:00:00", 0), ("T", "B", 2, "08:05:00", 1), ("T", "C", 3, "08:10:00", 0))
    tage = betriebstage(WERKTAGE, ausnahmen(), "2026-11-02", "2026-11-02")
    erg = abfahrten(st, TRIPS, STOPS, tage)
    assert erg["stop_id"].astype(str).tolist() == ["A1"]


def test_bahnsteige_zaehlen_zur_station():
    st = stop_times(
        ("T", "A1", 1, "08:00:00", 0), ("T", "C", 2, "08:10:00", 0),
        ("U", "A2", 1, "09:00:00", 0), ("U", "C", 2, "09:10:00", 0),
    )
    tage = betriebstage(WERKTAGE, ausnahmen(), "2026-11-02", "2026-11-02")
    erg = abfahrten(st, TRIPS, STOPS, tage)
    assert erg.groupby("station_id").size().to_dict() == {"A": 2}


def test_fahrt_ohne_betriebstag_erzeugt_keine_abfahrt():
    st = stop_times(("T", "A1", 1, "08:00:00", 0), ("T", "C", 2, "08:10:00", 0))
    tage = betriebstage(WERKTAGE, ausnahmen(), "2026-11-07", "2026-11-08")  # Wochenende
    assert len(abfahrten(st, TRIPS, STOPS, tage)) == 0


def test_mehrere_halte_an_derselben_station_sind_eine_abfahrt():
    # Wie Linie 55 am Kühler Krug: Bahnsteig A1, dann "kein Einstieg" an A2,
    # dann wieder A1. Für Fahrgäste ist das eine Abfahrt, um 08:01.
    st = stop_times(("T", "A1", 1, "08:00:00", 0), ("T", "A2", 2, "08:00:00", 1),
                    ("T", "A1", 3, "08:01:00", 0), ("T", "B", 4, "08:05:00", 0), ("T", "C", 5, "08:10:00", 0))
    tage = betriebstage(WERKTAGE, ausnahmen(), "2026-11-02", "2026-11-02")
    erg = abfahrten(st, TRIPS, STOPS, tage)
    assert erg["station_id"].tolist() == ["A", "B"]
    assert erg.loc[erg["station_id"] == "A", "zeitpunkt"].iloc[0] == pd.Timestamp("2026-11-02 08:01")


def test_ringlinie_zaehlt_beide_besuche():
    # A, B, wieder A, dann C: A wird zweimal angefahren, mit B dazwischen
    st = stop_times(("T", "A1", 1, "08:00:00", 0), ("T", "B", 2, "08:05:00", 0),
                    ("T", "A2", 3, "08:10:00", 0), ("T", "C", 4, "08:15:00", 0))
    tage = betriebstage(WERKTAGE, ausnahmen(), "2026-11-02", "2026-11-02")
    erg = abfahrten(st, TRIPS, STOPS, tage)
    assert erg["station_id"].tolist() == ["A", "B", "A"]


def test_doppelhalt_am_fahrtende_ist_keine_abfahrt():
    st = stop_times(("T", "B", 1, "08:00:00", 0), ("T", "A1", 2, "08:05:00", 0), ("T", "A2", 3, "08:06:00", 0))
    tage = betriebstage(WERKTAGE, ausnahmen(), "2026-11-02", "2026-11-02")
    erg = abfahrten(st, TRIPS, STOPS, tage)
    assert erg["station_id"].tolist() == ["B"]
