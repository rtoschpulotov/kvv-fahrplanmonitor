"""
Tests für den Standvergleich (Phase 4).
Autor: Rustam T.

Zwei konstruierte Mini-Stände, in denen jede Änderungsart genau einmal
vorkommt. Der Test prüft, dass sie genau einmal erkannt wird, und dass
alles andere nicht als Änderung zählt: eine neue trip_id bei gleichem
Inhalt, eine Verschiebung um 30 Sekunden, Fahrten vor dem Fenster.

Kalender: Mo 16.11. bis Fr 20.11.2026. Das Fenster beginnt am Di 17.11. um
07:00, so als wäre der neue Stand in dem Moment abgerufen worden.
"""

from datetime import date, datetime

import pandas as pd

from diff import Fenster, doppelte_schluessel, fahrten, fahrtverlaeufe, vergleiche

FENSTER = Fenster(ab=datetime(2026, 11, 17, 7, 0), bis=date(2026, 11, 20))

TAGE = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


def kalender(**services):
    """services: Name -> Liste von Tagen (Zahl im November) oder 'W' für Mo bis Fr."""
    cal, dates = [], []
    for name, tage in services.items():
        if tage == "W":
            cal.append({"service_id": name, **{t: "1" if i < 5 else "0" for i, t in enumerate(TAGE)},
                        "start_date": "20261116", "end_date": "20261120"})
        else:
            cal.append({"service_id": name, **{t: "0" for t in TAGE},
                        "start_date": "20261116", "end_date": "20261120"})
            dates += [{"service_id": name, "date": f"202611{d}", "exception_type": "1"} for d in tage]
    return pd.DataFrame(cal), pd.DataFrame(dates, columns=["service_id", "date", "exception_type"])


def stand(fahrten_def, services):
    """fahrten_def: trip_id -> (route, richtung, service, [(stop, "HH:MM:SS"), ...])"""
    trips, st = [], []
    for tid, (route, richtung, service, halte) in fahrten_def.items():
        trips.append({"trip_id": tid, "route_id": route, "service_id": service, "direction_id": str(richtung)})
        for i, (stop, zeit) in enumerate(halte, start=1):
            st.append({"trip_id": tid, "stop_sequence": i, "stop_id": stop,
                       "arrival_time": zeit, "departure_time": zeit, "pickup_type": 0})
    cal, dates = kalender(**services)
    stops = pd.DataFrame({"stop_id": ["S1", "S2", "S3", "S4"], "parent_station": ["", "", "", ""]})
    s = {"calendar": cal, "calendar_dates": dates, "trips": pd.DataFrame(trips),
         "stop_times": pd.DataFrame(st), "stops": stops}
    return s, fahrtverlaeufe(s["stop_times"], s["stops"])


HIN = [("S1", "08:00:00"), ("S2", "08:10:00"), ("S3", "08:20:00")]


def zeiten(stunde, *minuten, halte=("S1", "S2", "S3")):
    return [(h, f"{stunde:02d}:{m}") for h, m in zip(halte, minuten)]


ALT = {
    # unverändert, aber im neuen Stand mit anderer trip_id
    "A":  ("R1", 0, "W",   HIN),
    # entfällt
    "B":  ("R1", 0, "EIN", zeiten(9, "00:00", "10:00", "20:00")),
    # Halteverlauf: im neuen Stand kommt S4 dazu
    "D":  ("R1", 1, "EIN", zeiten(11, "00:00", "10:00", "20:00", halte=("S3", "S2", "S1"))),
    # Zeit: im neuen Stand an S2 drei Minuten später
    "E":  ("R1", 1, "EIN", zeiten(12, "00:00", "10:00", "20:00", halte=("S3", "S2", "S1"))),
    # nur 30 Sekunden verschoben, zählt nicht
    "F":  ("R2", 0, "EIN", zeiten(13, "00:00", "10:00", "20:00")),
    # Betriebstage: alt am 17. und 18., neu am 17. und 19.
    "G":  ("R2", 0, "ZWEI", zeiten(14, "00:00", "10:00", "20:00")),
    # liegt vor dem Fenster (Mo 16.11.), Änderung daran zählt nicht
    "V":  ("R3", 0, "MO",  zeiten(15, "00:00", "10:00", "20:00")),
}
NEU = {
    "A2": ("R1", 0, "W",   HIN),
    "C":  ("R1", 0, "EIN", zeiten(10, "00:00", "10:00", "20:00")),
    "D2": ("R1", 1, "EIN", [("S3", "11:00:00"), ("S4", "11:05:00"), ("S2", "11:10:00"), ("S1", "11:20:00")]),
    "E2": ("R1", 1, "EIN", zeiten(12, "00:00", "13:00", "20:00", halte=("S3", "S2", "S1"))),
    "F2": ("R2", 0, "EIN", zeiten(13, "00:00", "10:30", "20:00")),
    "G2": ("R2", 0, "ZWEIB", zeiten(14, "00:00", "10:00", "20:00")),
}
SERVICES_ALT = {"W": "W", "EIN": [17], "ZWEI": [17, 18], "MO": [16]}
SERVICES_NEU = {"W": "W", "EIN": [17], "ZWEIB": [17, 19]}


def vergleich(alt_def=ALT, neu_def=NEU, s_alt=SERVICES_ALT, s_neu=SERVICES_NEU):
    alt, va = stand(alt_def, s_alt)
    neu, vn = stand(neu_def, s_neu)
    return vergleiche(fahrten(alt, va, FENSTER), fahrten(neu, vn, FENSTER), va, vn)


def art_und_detail(aend: pd.DataFrame) -> pd.Series:
    """"betriebstage/Tag entfällt" oder nur "neu", wenn es kein Detail gibt."""
    return aend["art"] + aend["detail"].map(lambda d: f"/{d}" if isinstance(d, str) else "")


def test_jede_aenderungsart_genau_einmal():
    aend, _, _ = vergleich()
    assert art_und_detail(aend).value_counts().to_dict() == {
        "neu": 1,
        "entfallen": 1,
        "halteverlauf": 1,
        "zeit": 1,
        "betriebstage/Tag entfällt": 1,
        "betriebstage/Tag kommt dazu": 1,
    }


def test_details_der_aenderungen():
    aend, _, _ = vergleich()
    zeile = {k: r for k, (_, r) in zip(art_und_detail(aend), aend.iterrows())}
    assert zeile["entfallen"]["trip_id_alt"] == "B"
    assert zeile["neu"]["trip_id_neu"] == "C"
    assert zeile["halteverlauf"]["station"] == "S4"
    assert zeile["zeit"]["verschiebung_min"] == 3 and zeile["zeit"]["station"] == "S2"
    assert zeile["betriebstage/Tag entfällt"]["kalendertag"] == pd.Timestamp("2026-11-18")
    assert zeile["betriebstage/Tag kommt dazu"]["kalendertag"] == pd.Timestamp("2026-11-19")


def test_gleicher_stand_ergibt_keine_aenderung():
    """Gegenprobe aus der Aufgabe: zwei Stände mit gleichem Inhalt, null Änderungen."""
    aend, halte, je_linie = vergleich(ALT, ALT, SERVICES_ALT, SERVICES_ALT)
    assert len(aend) == 0
    assert len(halte) == 0
    assert je_linie["geaendert"].sum() == 0


def test_neue_trip_id_bei_gleichem_inhalt_ist_keine_aenderung():
    aend, _, _ = vergleich()
    assert "A" not in set(aend["trip_id_alt"].dropna())


def test_fahrt_vor_dem_fenster_zaehlt_nicht():
    """V fährt nur am Mo 16.11., vor dem Abruf. Dass sie im neuen Stand fehlt, ist keine Änderung."""
    aend, _, _ = vergleich()
    assert "R3" not in set(aend["route_id"])


def test_fenster_beginnt_mit_der_uhrzeit_des_abrufs():
    """A fährt am 17.11. um 08:00, also nach dem Abruf um 07:00. Eine Fahrt um 06:00 läge davor."""
    alt, va = stand({"X": ("R9", 0, "EIN", zeiten(6, "00:00", "10:00", "20:00"))}, {"EIN": [17]})
    assert len(fahrten(alt, va, FENSTER)) == 0
    alt, va = stand({"X": ("R9", 0, "EIN", zeiten(8, "00:00", "10:00", "20:00"))}, {"EIN": [17]})
    assert len(fahrten(alt, va, FENSTER)) == 1


def test_vorruecken_des_zeitraums_ist_keine_aenderung():
    """Der neue Stand kennt einen Tag mehr (Sa 21.11.). Das Fenster endet trotzdem am 20.11."""
    neu = dict(ALT)
    alt, va = stand(ALT, SERVICES_ALT)
    neu_s, vn = stand(neu, {**SERVICES_ALT, "W": "W", "EIN": [17, 21]})
    aend, _, _ = vergleiche(fahrten(alt, va, FENSTER), fahrten(neu_s, vn, FENSTER), va, vn)
    assert len(aend) == 0


def test_stabilitaet_je_linie():
    _, _, je_linie = vergleich()
    r1 = je_linie.set_index("route_id").loc["R1"]
    # R1 alt im Fenster: A an 4 Tagen (Di bis Fr), B, D, E am 17. = 7 Fahrten.
    # Geändert: B entfallen, D Halteverlauf, E Zeit = 3. Neu (C) zählt nicht als geändert.
    assert (r1["fahrten_alt"], r1["geaendert"], r1["neu"]) == (7, 3, 1)


def test_betroffene_haltestellen():
    _, halte, _ = vergleich()
    # Bei der Zeitänderung ist nur S2 betroffen, beim Halteverlauf nur S4,
    # bei der entfallenen Fahrt alle drei Stationen.
    assert set(halte[halte["art"] == "zeit"]["station"]) == {"S2"}
    assert set(halte[halte["art"] == "halteverlauf"]["station"]) == {"S4"}
    assert set(halte[halte["art"] == "entfallen"]["station"]) == {"S1", "S2", "S3"}


def test_verstaerker_mit_gleichem_schluessel_werden_unterschieden():
    """Zwei Fahrten gleicher Linie, Richtung, erster Station und Minute: kein Fehlalarm."""
    zwei = {"P": ("R5", 0, "EIN", zeiten(7, "30:00", "40:00", "50:00")),
            "Q": ("R5", 0, "EIN", zeiten(7, "30:00", "45:00", "55:00"))}
    alt, va = stand(zwei, {"EIN": [17]})
    assert len(doppelte_schluessel(fahrten(alt, va, FENSTER))) == 2
    aend, _, _ = vergleiche(fahrten(alt, va, FENSTER), fahrten(alt, va, FENSTER), va, va)
    assert len(aend) == 0
