"""Tests für Gemeindezuordnung und Abendfenster (E11). Autor: Rustam T."""

import geopandas as gpd
import pandas as pd
from shapely.geometry import box

from gemeinden import je_gemeinde, ordne_zu

# Zwei quadratische Gemeinden nebeneinander, Koordinaten in Grad
GEMEINDEN = gpd.GeoDataFrame(
    {"ags": ["08212000", "08215001"], "gemeinde": ["Links", "Rechts"], "kreis": ["08212", "08215"],
     "einwohner": [1000, 2000]},
    geometry=[box(8.0, 49.0, 8.1, 49.1), box(8.1, 49.0, 8.2, 49.1)], crs="EPSG:4326",
)


def stationen(*punkte):
    ids = [f"S{i}" for i in range(len(punkte))]
    return gpd.GeoDataFrame({"station_id": ids, "stop_name": ids},
                            geometry=gpd.points_from_xy([p[0] for p in punkte], [p[1] for p in punkte]), crs="EPSG:4326")


def test_punkt_in_polygon_und_ausserhalb():
    drin, draussen = ordne_zu(stationen((8.05, 49.05), (8.15, 49.05), (7.9, 49.05)), GEMEINDEN)
    assert dict(zip(drin["station_id"], drin["gemeinde"])) == {"S0": "Links", "S1": "Rechts"}
    assert draussen["station_id"].tolist() == ["S2"]       # wird gemeldet, nicht verworfen


def test_je_gemeinde_letzte_abfahrt_und_pro_kopf():
    drin, _ = ordne_zu(stationen((8.05, 49.05), (8.15, 49.05)), GEMEINDEN)
    ab = pd.DataFrame({
        "station_id": ["S0", "S0", "S0", "S1"],
        "trip_id": ["a", "b", "c", "d"],
        "zeitpunkt": pd.to_datetime(["2026-11-10 07:00", "2026-11-10 21:00", "2026-11-11 00:30", "2026-11-10 18:00"]),
    })
    g = je_gemeinde(ab, drin, "2026-11-10").set_index("gemeinde")
    assert g.loc["Links", "abfahrten"] == 3
    assert g.loc["Links", "letzte_abfahrt"] == pd.Timestamp("2026-11-11 00:30")   # Nachtbus zählt zum Abend
    assert g.loc["Links", "abfahrten_nach_20"] == 2
    assert g.loc["Rechts", "abfahrten_nach_20"] == 0
    assert g.loc["Rechts", "je_1000_einwohner"] == 0.5
