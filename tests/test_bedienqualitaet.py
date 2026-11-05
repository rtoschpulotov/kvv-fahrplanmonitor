"""Tests für die Kennzahlen zur Gleichmäßigkeit (E10). Autor: Rustam T."""

import pandas as pd
import pytest

from bedienqualitaet import gedeckelte_wartezeit, tagestyp, takt_je_stunde


def abfahrten_um(*uhrzeiten, station="A"):
    """Abfahrten an einer Station am 10.11.2026, Uhrzeiten als "08:10"."""
    zp = pd.to_datetime([f"2026-11-10 {u}" for u in uhrzeiten])
    ab = pd.DataFrame({"station_id": station, "trip_id": [str(i) for i in range(len(zp))], "zeitpunkt": zp})
    ab["stunde"] = ab["zeitpunkt"].dt.hour
    ab["kalendertag"] = ab["zeitpunkt"].dt.normalize()
    return ab


def stunde(ab, h):
    return takt_je_stunde(ab).set_index("stunde").loc[h]


def test_regelmaessiger_10_minuten_takt():
    # 07:50 sorgt dafür, dass auch die Zeit von 08:00 bis 08:10 versorgt ist
    s = stunde(abfahrten_um("07:50", "08:00", "08:10", "08:20", "08:30", "08:40", "08:50", "09:00"), 8)
    assert s["abfahrten"] == 6
    assert s["mittlerer_abstand_min"] == 10
    assert s["groesster_abstand_min"] == 10
    assert s["erwartete_wartezeit_min"] == pytest.approx(5)


def test_pulk_hat_gleichen_mittelwert_aber_viel_laengere_wartezeit():
    # Sechs Abfahrten, aber alle zwischen 08:00 und 08:05, dann erst wieder 09:00
    s = stunde(abfahrten_um("07:59", "08:00", "08:01", "08:02", "08:03", "08:04", "08:05", "09:00"), 8)
    assert s["mittlerer_abstand_min"] == 10            # sieht aus wie ein Takt
    assert s["groesster_abstand_min"] == 55
    # Wartezeit: fünf Lücken à 1 Minute und eine von 55 Minuten
    assert s["erwartete_wartezeit_min"] == pytest.approx((5 * 0.5 + 55 ** 2 / 2) / 60)


def test_lange_luecke_wird_an_der_stundengrenze_abgeschnitten():
    # Von 05:00 bis 08:20 nichts. In der Stunde 8 wartet man im Schnitt
    # nur bis 08:20, nicht die ganzen 200 Minuten.
    s = stunde(abfahrten_um("05:00", "08:20", "08:40", "09:00"), 8)
    assert s["groesster_abstand_min"] == 20
    assert s["erwartete_wartezeit_min"] == pytest.approx(10)


def test_nach_der_letzten_abfahrt_zaehlt_nichts():
    s = stunde(abfahrten_um("22:00", "23:10"), 23)
    assert s["groesster_abstand_min"] == 10            # 23:00 bis 23:10, danach nichts mehr
    assert s["erwartete_wartezeit_min"] == pytest.approx(5)


def test_stationen_werden_getrennt_gerechnet():
    ab = pd.concat([abfahrten_um("08:00", "08:30", station="A"), abfahrten_um("08:15", station="B")])
    t = takt_je_stunde(ab).set_index(["station_id", "stunde"])
    assert t.loc[("A", 8), "abfahrten"] == 2 and t.loc[("B", 8), "abfahrten"] == 1


def test_tagestyp():
    assert [tagestyp(d) for d in ["2026-11-10", "2026-11-14", "2026-11-15"]] == ["Werktag", "Samstag", "Sonntag"]


def test_wartezeit_wird_bei_60_minuten_gedeckelt():
    # Letzte Abfahrt 01:04, nächste erst 22:27: in der Stunde 1 heißt das "kein Angebot"
    s = stunde(abfahrten_um("00:47", "01:04", "22:27"), 1)
    assert s["erwartete_wartezeit_min"] <= 60
    # 01:00 bis 01:04: im Schnitt 2 Minuten, 01:04 bis 02:00: jede Wartezeit gedeckelt
    assert s["erwartete_wartezeit_min"] == pytest.approx((4 * 2 + 56 * 60) / 60)


def test_deckel_mitten_im_stueck():
    # Stück von 90 bis 30 Minuten vor der Abfahrt: 30 Minuten gedeckelt, 30 Minuten echt
    erg = gedeckelte_wartezeit(pd.Series([90.0]), pd.Series([30.0]))
    assert erg.iloc[0] == pytest.approx(30 * 60 + (60 ** 2 - 30 ** 2) / 2)
