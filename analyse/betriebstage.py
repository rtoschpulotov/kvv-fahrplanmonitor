"""
Betriebstage auflösen und Abfahrten auf Kalenderzeit umrechnen.
Autor: Rustam T.

Das ist der Kern von Phase 2. Wenn hier etwas falsch ist, gibt es keine
Fehlermeldung, sondern Taktzahlen, die vernünftig aussehen und falsch sind.
Deshalb ist jeder Schritt einzeln getestet (tests/test_betriebstage.py).

Die Regel nach GTFS (siehe E6 im Entscheidungsprotokoll):
1. calendar: Tag D gehört zu einer service_id, wenn D zwischen start_date und
   end_date liegt und die Wochentagsspalte für D eine 1 hat.
2. calendar_dates, exception_type 1: D kommt dazu.
3. calendar_dates, exception_type 2: D fällt weg.
Ergebnis = (1 vereinigt mit 2) ohne 3.

Danach rechne ich Abfahrten auf Kalenderzeit um. GTFS zählt Uhrzeiten ab
Beginn des Betriebstags und erlaubt Werte über 24 Uhr. Eine Abfahrt um
25:10:00 am Betriebstag D findet am Kalendertag D+1 um 01:10 Uhr statt.
"""

import pandas as pd

WOCHENTAGE = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


def _als_datum(spalte: pd.Series) -> pd.Series:
    """GTFS schreibt Daten als JJJJMMTT, also "20261103"."""
    return pd.to_datetime(spalte, format="%Y%m%d")


def betriebstage(calendar: pd.DataFrame, calendar_dates: pd.DataFrame, von, bis) -> pd.DataFrame:
    """Alle tatsächlichen Betriebstage im Zeitraum [von, bis] als (service_id, datum).

    von und bis sind einschließlich und dürfen Text ("2026-11-10") oder Datum sein.
    """
    von, bis = pd.Timestamp(von), pd.Timestamp(bis)
    tage = pd.DataFrame({"datum": pd.date_range(von, bis, freq="D")})
    # dayofweek: Montag ist 0, Sonntag 6. Das passt zur Reihenfolge in WOCHENTAGE.
    tage["wochentag"] = tage["datum"].dt.dayofweek

    # Schritt 1: regulärer Plan aus calendar.
    # Ich drehe die sieben Wochentagsspalten in Zeilen (service_id, wochentag)
    # und behalte nur die mit einer 1. Dann verbinde ich mit allen Tagen des
    # Zeitraums über den Wochentag und filtere auf start_date bis end_date.
    # Das ist schneller als für jede service_id einzeln eine Datumsreihe zu bauen.
    if len(calendar):
        cal = calendar.copy()
        cal["start"] = _als_datum(cal["start_date"])
        cal["ende"] = _als_datum(cal["end_date"])
        lang = cal.melt(
            id_vars=["service_id", "start", "ende"],
            value_vars=WOCHENTAGE,
            var_name="tagname",
            value_name="faehrt",
        )
        lang = lang[lang["faehrt"].astype(str) == "1"]
        lang["wochentag"] = lang["tagname"].map({n: i for i, n in enumerate(WOCHENTAGE)})
        regulaer = lang.merge(tage, on="wochentag")
        regulaer = regulaer[(regulaer["datum"] >= regulaer["start"]) & (regulaer["datum"] <= regulaer["ende"])]
        regulaer = regulaer[["service_id", "datum"]]
    else:
        regulaer = pd.DataFrame({"service_id": pd.Series(dtype=str), "datum": pd.Series(dtype="datetime64[ns]")})

    # Schritt 2 und 3: Ausnahmen. Wichtig: Ich hole sie aus calendar_dates
    # selbst und nicht über einen Join auf calendar. Sonst gingen service_id
    # verloren, die nur in calendar_dates vorkommen.
    ausn = calendar_dates.copy()
    ausn["datum"] = _als_datum(ausn["date"])
    ausn = ausn[(ausn["datum"] >= von) & (ausn["datum"] <= bis)]
    ausn["exception_type"] = ausn["exception_type"].astype(str)
    dazu = ausn.loc[ausn["exception_type"] == "1", ["service_id", "datum"]]
    weg = ausn.loc[ausn["exception_type"] == "2", ["service_id", "datum"]]

    ergebnis = pd.concat([regulaer, dazu], ignore_index=True).drop_duplicates()
    # "ohne Menge 3": Anti-Join. indicator markiert, welche Zeilen auch in weg stehen.
    ergebnis = ergebnis.merge(weg.drop_duplicates(), on=["service_id", "datum"], how="left", indicator=True)
    ergebnis = ergebnis[ergebnis["_merge"] == "left_only"].drop(columns="_merge")
    return ergebnis.sort_values(["datum", "service_id"]).reset_index(drop=True)


def gtfs_zeit_in_sekunden(zeiten: pd.Series) -> pd.Series:
    """ "25:10:00" -> 90600. Leere Werte bleiben leer.

    Ein Zeittyp kann 25 Uhr nicht darstellen. Deshalb rechne ich immer in
    Sekunden seit Beginn des Betriebstags. Bei Kategorien zerlege ich nur die
    verschiedenen Werte (rund 14.500) und nicht jede der 3 Mio. Zeilen.
    """
    if isinstance(zeiten.dtype, pd.CategoricalDtype):
        werte = pd.Series(zeiten.cat.categories)
        sek = gtfs_zeit_in_sekunden(werte)
        zuordnung = dict(zip(werte, sek))
        return zeiten.map(zuordnung).astype("Int32")
    teile = zeiten.astype("string").str.split(":", expand=True)
    if teile.shape[1] != 3:
        return pd.Series(pd.NA, index=zeiten.index, dtype="Int32")
    teile = teile.astype("Int32")
    return (teile[0] * 3600 + teile[1] * 60 + teile[2]).astype("Int32")


def station_je_halt(stops: pd.DataFrame) -> pd.Series:
    """stop_id -> Station (E9).

    Eine Haltestelle ist bei mir die Station, nicht der Bahnsteig. Hat ein Halt
    eine parent_station, zählt er zu ihr. Hat er keine, ist er selbst die
    Station. Sonst würde ein Halt mit vier Bahnsteigen viermal gezählt.
    """
    eltern = stops["parent_station"].fillna("").astype(str)
    station = eltern.where(eltern != "", stops["stop_id"])
    return pd.Series(station.values, index=stops["stop_id"].values, name="station_id")


def abfahrten(stop_times: pd.DataFrame, trips: pd.DataFrame, stops: pd.DataFrame, tage: pd.DataFrame) -> pd.DataFrame:
    """Jede Abfahrt an jedem Betriebstag aus `tage`, mit Kalenderzeit.

    tage kommt aus betriebstage(). Eine Abfahrt ist ein Halt, an dem man
    einsteigen kann (E9):
    - der letzte Halt einer Fahrt zählt nicht, dort steigt man nur aus,
    - pickup_type 1 (kein Einstieg) zählt nicht,
    - ein Halt ohne Uhrzeit zählt nicht (kommt im KVV-Feed einmal vor).
    """
    st = stop_times
    # Letzter Halt je Fahrt: höchste stop_sequence. transform gibt den Wert an
    # jede Zeile der Fahrt zurück, so kann ich direkt vergleichen.
    letzter = st.groupby("trip_id", observed=True)["stop_sequence"].transform("max")
    pickup = st["pickup_type"].fillna(0)
    behalten = (st["stop_sequence"] != letzter) & (pickup != 1) & st["departure_time"].notna()
    st = st.loc[behalten, ["trip_id", "stop_id", "stop_sequence", "departure_time", "pickup_type"]].copy()
    st["abfahrt_sek"] = gtfs_zeit_in_sekunden(st["departure_time"])
    st = st.drop(columns="departure_time")

    # Halt -> Station
    stationen = station_je_halt(stops)
    st["station_id"] = st["stop_id"].astype(str).map(stationen)

    # Fahrt -> service_id -> Betriebstage. Erst hier wird aus "Fahrt X fährt
    # nach Plan Y" eine Zeile pro tatsächlichem Tag.
    st["trip_id"] = st["trip_id"].astype(str)
    st = st.merge(trips[["trip_id", "route_id", "service_id"]], on="trip_id", how="inner")
    st = st.merge(tage.rename(columns={"datum": "betriebstag"}), on="service_id", how="inner")

    # Kalenderzeit = Mitternacht des Betriebstags + Sekunden. 25:10 landet so
    # automatisch am Folgetag um 01:10. An den Tagen der Zeitumstellung liegen
    # Abfahrten vor 2 bzw. 3 Uhr eine Stunde daneben (E8). Diese Tage nutze ich
    # nicht als Stichtage.
    st["zeitpunkt"] = st["betriebstag"] + pd.to_timedelta(st["abfahrt_sek"].astype("int64"), unit="s")
    st["kalendertag"] = st["zeitpunkt"].dt.normalize()
    st["stunde"] = st["zeitpunkt"].dt.hour.astype("int8")
    return st.drop(columns=["service_id"])
