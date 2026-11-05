"""
Haltestellen den Gemeinden zuordnen und je Gemeinde auswerten.
Autor: Rustam T.

Quelle der Gemeindegrenzen und Einwohnerzahlen: VG250-EW des BKG, Stand
31.12.2025, Lizenz dl-de/by-2-0. Die Einwohnerzahlen darin kommen aus dem
Gemeindeverzeichnis von Destatis. Die Datei liegt nicht im Repo (115 MB),
Bezug und Quellenvermerk stehen im README.

Vorgehen:
1. Jede Station (E9) bekommt über ihre Koordinaten die Gemeinde, in deren
   Fläche sie liegt (Punkt in Polygon). Dafür rechne ich die Koordinaten aus
   GTFS (Grad, WGS84) in das Koordinatensystem der Gemeindegrenzen um
   (ETRS89 / UTM 32N, Meter).
2. Stationen ohne Gemeinde verwerfe ich nicht still, sondern gebe sie zurück.
   Im KVV-Feed sind das Haltestellen im Elsass.
3. Ausgewertet wird nur das Kerngebiet (E11): die vier Kreise, die ganz zum
   KVV gehören. In Randgemeinden fahren auch Busse anderer Verbünde, die im
   KVV-Feed fehlen. Pro Kopf sähen sie dadurch schlechter aus, als sie sind.
"""

from pathlib import Path

import geopandas as gpd
import pandas as pd

from betriebstage import abfahrten, betriebstage, station_je_halt

KERNGEBIET = {
    "08211": "Baden-Baden",
    "08212": "Karlsruhe (Stadt)",
    "08215": "Landkreis Karlsruhe",
    "08216": "Landkreis Rastatt",
}


def lies_gemeinden(gpkg: Path) -> gpd.GeoDataFrame:
    """Gemeinden mit Name, Einwohnern und Fläche aus der VG250-EW.

    GF 4 heißt "Landfläche mit Struktur". Daneben gibt es Einträge mit GF 2,
    das sind Gewässerflächen wie der Bodensee. Die brauche ich nicht.
    """
    g = gpd.read_file(gpkg, layer="vg250_gem", columns=["AGS", "GEN", "BEZ", "EWZ", "GF"])
    g = g[g["GF"] == 4].drop(columns="GF")
    g["kreis"] = g["AGS"].str[:5]
    return g.rename(columns={"AGS": "ags", "GEN": "gemeinde", "BEZ": "art", "EWZ": "einwohner"})


def stationen_mit_koordinaten(stops: pd.DataFrame) -> gpd.GeoDataFrame:
    """Je Station (E9) ein Punkt. Die Koordinate ist die des Stationseintrags."""
    ids = station_je_halt(stops).unique()
    s = stops.set_index("stop_id").loc[ids, ["stop_name", "stop_lat", "stop_lon"]]
    s = s.astype({"stop_lat": float, "stop_lon": float})
    punkte = gpd.points_from_xy(s["stop_lon"], s["stop_lat"])
    return gpd.GeoDataFrame(s, geometry=punkte, crs="EPSG:4326").rename_axis("station_id").reset_index()


def ordne_zu(stationen: gpd.GeoDataFrame, gemeinden: gpd.GeoDataFrame):
    """Station -> Gemeinde per Punkt in Polygon.

    Gibt zwei Tabellen zurück: die zugeordneten Stationen und die ohne
    Gemeinde. "within" heißt: der Punkt liegt in der Fläche. Ein Punkt genau
    auf einer Gemeindegrenze würde bei "within" keiner Gemeinde zugeordnet,
    bei "intersects" zweien. Ich prüfe deshalb, ob jede Station höchstens
    einmal vorkommt.
    """
    st = stationen.to_crs(gemeinden.crs)
    j = gpd.sjoin(st, gemeinden[["ags", "gemeinde", "kreis", "einwohner", "geometry"]], how="left", predicate="within")
    assert not j["station_id"].duplicated().any(), "Station liegt in mehr als einer Gemeinde"
    j = pd.DataFrame(j.drop(columns=["geometry", "index_right"]))
    return j[j["ags"].notna()].reset_index(drop=True), j[j["ags"].isna()].reset_index(drop=True)


def abfahrten_im_abendfenster(stand: dict, tag, beginn: str = "04:00") -> pd.DataFrame:
    """Abfahrten von `tag` 04:00 bis zum Folgetag 04:00 (E11).

    Für "letzte Abfahrt am Abend" passt der Kalendertag nicht: Ein Nachtbus um
    00:30 gehört für jeden Fahrgast noch zum Dienstagabend. Der Betriebstag
    passt auch nicht, denn er reicht im KVV-Feed bis 05:25 am nächsten Morgen.
    Ich nehme deshalb ein Fenster von 4 bis 4 Uhr. Um 4 Uhr fährt fast nichts
    (am 10.11.2026 in der Stunde ab 3 Uhr 102 Abfahrten im ganzen Netz).
    """
    tag = pd.Timestamp(tag)
    von = tag + pd.Timedelta(beginn + ":00")
    bis = von + pd.Timedelta(days=1)
    tage = betriebstage(stand["calendar"], stand["calendar_dates"], tag - pd.Timedelta(days=1), tag + pd.Timedelta(days=1))
    ab = abfahrten(stand["stop_times"], stand["trips"], stand["stops"], tage)
    return ab[(ab["zeitpunkt"] >= von) & (ab["zeitpunkt"] < bis)].reset_index(drop=True)


def je_gemeinde(ab_fenster: pd.DataFrame, zuordnung: pd.DataFrame, tag, abend: str = "20:00") -> pd.DataFrame:
    """Abfahrten, Abfahrten je 1.000 Einwohner und letzte Abfahrt je Gemeinde.

    ab_fenster kommt aus abfahrten_im_abendfenster(). Gezählt werden alle
    Abfahrten im Fenster von 4 bis 4 Uhr. "Nach 20 Uhr" heißt: zwischen 20 Uhr
    und 4 Uhr früh.
    """
    grenze = pd.Timestamp(tag) + pd.Timedelta(abend + ":00")
    ab = ab_fenster.merge(zuordnung[["station_id", "ags"]], on="station_id", how="inner")
    erg = ab.groupby("ags").agg(
        abfahrten=("trip_id", "size"),
        letzte_abfahrt=("zeitpunkt", "max"),
    )
    erg["abfahrten_nach_20"] = ab[ab["zeitpunkt"] >= grenze].groupby("ags").size()
    gem = zuordnung.groupby("ags").agg(gemeinde=("gemeinde", "first"), kreis=("kreis", "first"),
                                       einwohner=("einwohner", "first"), stationen=("station_id", "size"))
    erg = gem.join(erg, how="left")
    erg[["abfahrten", "abfahrten_nach_20"]] = erg[["abfahrten", "abfahrten_nach_20"]].fillna(0).astype(int)
    erg["je_1000_einwohner"] = erg["abfahrten"] / erg["einwohner"] * 1000
    return erg.reset_index()
