"""
Ebene 1: Bedienqualität an einzelnen Stichtagen.
Autor: Rustam T.

Baut auf betriebstage.py auf und beantwortet drei Fragen je Haltestelle
(Station nach E9):
1. Wie viele Abfahrten gibt es an einem Tag?
2. Wie viele je Stunde, und wie gleichmäßig sind sie verteilt?
3. Wann fährt abends der letzte Bus oder die letzte Bahn?

Zur Gleichmäßigkeit (E10): Der mittlere Abstand zwischen zwei Abfahrten
taugt dafür allein nicht. Sechs Abfahrten in einer Stunde haben immer einen
mittleren Abstand von zehn Minuten, egal ob sie im 10-Minuten-Takt fahren
oder alle sechs zwischen :00 und :05. Ich weise deshalb zusätzlich den
größten Abstand und die erwartete Wartezeit aus. Die erwartete Wartezeit ist
die mittlere Wartezeit eines Fahrgasts, der zu einem zufälligen Zeitpunkt an
die Haltestelle kommt. Im perfekten 10-Minuten-Takt sind das 5 Minuten, bei
sechs Abfahrten im Pulk fast 25.
"""

import pandas as pd

from betriebstage import abfahrten, betriebstage

TAGESTYP = {5: "Samstag", 6: "Sonntag"}   # alles andere ist Werktag


def tagestyp(datum) -> str:
    return TAGESTYP.get(pd.Timestamp(datum).dayofweek, "Werktag")


def abfahrten_am_tag(stand: dict, tag) -> pd.DataFrame:
    """Alle Abfahrten, die am Kalendertag `tag` stattfinden.

    Ich hole die Betriebstage ab dem Vortag. Eine Fahrt vom Vortag um 24:30
    fährt an `tag` um 00:30 und gehört nach E9 zu diesem Kalendertag.
    """
    tag = pd.Timestamp(tag)
    tage = betriebstage(stand["calendar"], stand["calendar_dates"], tag - pd.Timedelta(days=1), tag)
    ab = abfahrten(stand["stop_times"], stand["trips"], stand["stops"], tage)
    return ab[ab["kalendertag"] == tag].reset_index(drop=True)


def abfahrten_je_station(ab: pd.DataFrame) -> pd.DataFrame:
    """Abfahrten je Station an einem Tag, Rufbus-Abfahrten getrennt ausgewiesen."""
    rufbus = ab["pickup_type"].fillna(0) == 2
    return (
        ab.assign(rufbus=rufbus)
        .groupby("station_id")
        .agg(abfahrten=("trip_id", "size"), davon_rufbus=("rufbus", "sum"),
             erste=("zeitpunkt", "min"), letzte=("zeitpunkt", "max"))
        .reset_index()
    )


DECKEL_MIN = 60


def gedeckelte_wartezeit(rest_am_anfang: pd.Series, rest_am_ende: pd.Series, deckel: float = DECKEL_MIN) -> pd.Series:
    """Summe der Wartezeiten über ein Stück, jede Wartezeit höchstens `deckel`.

    rest_am_anfang ist n - a, rest_am_ende ist n - b (beides in Minuten, das
    erste ist größer). Wer früher kommt als `deckel` Minuten vor der Abfahrt,
    zählt mit genau `deckel`. Wer später kommt, mit der echten Wartezeit.
    Dazwischen liegt die Grenze bei einer Restzeit von genau `deckel`.
    """
    ra, rb = rest_am_anfang, rest_am_ende
    grenze = ra.clip(upper=deckel).clip(lower=rb)   # Restzeit, ab der nicht mehr gedeckelt wird
    flach = (ra - grenze) * deckel                   # Stück mit Restzeit über dem Deckel
    schraeg = (grenze ** 2 - rb ** 2) / 2            # Stück darunter, wie ohne Deckel
    return flach + schraeg


def takt_je_stunde(ab: pd.DataFrame) -> pd.DataFrame:
    """Je Station und Stunde: Abfahrten, mittlerer und größter Abstand, erwartete Wartezeit.

    So rechne ich (E10): Ich stelle mir einen Fahrgast vor, der zu einem
    zufälligen Zeitpunkt t innerhalb der Stunde an die Station kommt. Er wartet
    bis zur nächsten Abfahrt n, also n - t Minuten, auch wenn n schon in der
    nächsten Stunde liegt. Die erwartete Wartezeit ist der Durchschnitt davon
    über die Stunde.

    Dafür zerlege ich den Tag in Lücken: von Mitternacht bis zur ersten
    Abfahrt, dann von Abfahrt zu Abfahrt. Jede Lücke schneide ich an den
    Stundengrenzen auf. Für ein Stück von a bis b, das vor der Abfahrt n endet,
    ist die Summe der Wartezeiten das Integral von (n - t) über [a, b]:
    ((n - a)² - (n - b)²) / 2. Nach der letzten Abfahrt des Tages kommt nichts
    mehr. Diese Zeit zählt nicht mit, sonst bekäme die Stunde ab 23 Uhr eine
    Wartezeit bis zum Morgen.

    Jede einzelne Wartezeit deckle ich bei 60 Minuten. Ohne Deckel bekommt
    eine Station mit einer Abfahrt um 01:04 und der nächsten um 22:27 für die
    Stunde ab 1 Uhr eine erwartete Wartezeit von über 19 Stunden. Das stimmt
    zwar, ist aber keine Wartezeit mehr, sondern "kein Angebot", und es würde
    jeden Durchschnitt zerstören. Mit dem Deckel heißt 60: in dieser Stunde
    praktisch keine Verbindung.

    Der größte Abstand ist das längste Stück ohne Abfahrt innerhalb der Stunde.
    Der mittlere Abstand ist 60 / Abfahrten. Er steht nur der Vollständigkeit
    halber da: Er sagt dasselbe wie die Zahl der Abfahrten und verrät nichts
    darüber, ob sie gleichmäßig kommen. Genau deshalb gibt es die anderen beiden.

    Ich rechne über alle Linien und Richtungen einer Station zusammen. Für
    jemanden, der in eine bestimmte Richtung will, ist das zu optimistisch.
    """
    ab = ab.sort_values(["station_id", "zeitpunkt"])
    anzahl = ab.groupby(["station_id", "stunde"]).size().rename("abfahrten")

    # Lücken: Ende ist jede Abfahrt, Anfang die vorherige (oder Mitternacht)
    tag = ab["kalendertag"] if "kalendertag" in ab else ab["zeitpunkt"].dt.normalize()
    luecken = pd.DataFrame({
        "station_id": ab["station_id"].values,
        "ende": ab["zeitpunkt"].values,
        "anfang": ab.groupby("station_id")["zeitpunkt"].shift().fillna(tag).values,
    })
    luecken = luecken[luecken["ende"] > luecken["anfang"]]

    # Jede Lücke auf die Stunden verteilen, die sie berührt
    luecken["h0"] = luecken["anfang"].dt.floor("h")
    luecken["n"] = ((luecken["ende"] - pd.Timedelta(seconds=1)).dt.floor("h") - luecken["h0"]) // pd.Timedelta(hours=1) + 1
    stuecke = luecken.loc[luecken.index.repeat(luecken["n"])].copy()
    stuecke["h"] = stuecke["h0"] + pd.to_timedelta(stuecke.groupby(level=0).cumcount(), unit="h")
    a = stuecke[["anfang", "h"]].max(axis=1)
    b = stuecke[["ende"]].assign(h1=stuecke["h"] + pd.Timedelta(hours=1)).min(axis=1)
    n = stuecke["ende"]
    min_ = lambda x: x.dt.total_seconds() / 60
    stuecke["laenge"] = min_(b - a)
    stuecke["warte_summe"] = gedeckelte_wartezeit(min_(n - a), min_(n - b))
    stuecke["stunde"] = stuecke["h"].dt.hour

    g = stuecke.groupby(["station_id", "stunde"])
    erg = pd.DataFrame({
        "groesster_abstand_min": g["laenge"].max(),
        "erwartete_wartezeit_min": g["warte_summe"].sum() / g["laenge"].sum(),
    })
    erg = anzahl.to_frame().join(erg, how="left")
    erg.insert(1, "mittlerer_abstand_min", 60 / erg["abfahrten"])
    return erg.reset_index()


def letzte_abfahrt(ab: pd.DataFrame, nach_spalte: str = "station_id") -> pd.DataFrame:
    """Letzte Abfahrt je Station (oder je Gemeinde) am Abend.

    Abfahrten nach Mitternacht gehören zum nächsten Kalendertag (E9) und
    stehen deshalb nicht in `ab`. "Letzte Abfahrt" heißt also: letzte vor
    Mitternacht dieses Kalendertags.
    """
    return ab.groupby(nach_spalte)["zeitpunkt"].max().rename("letzte_abfahrt").reset_index()
