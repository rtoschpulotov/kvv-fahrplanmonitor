"""
Zwei Fahrplanstände vergleichen: Was ist neu, was entfällt, was hat sich verschoben?
Autor: Rustam T.

Das ist der Kern von Phase 4. Ich schreibe den Vergleich selbst, mit Pandas,
ohne fertiges Diff-Werkzeug. So weiß ich bei jeder gemeldeten Änderung,
warum sie gemeldet wurde.

Begriffe
--------
Fahrt (Instanz): eine Fahrt an einem bestimmten Betriebstag. Fahrt X nach
    Plan Y an fünf Tagen sind fünf Instanzen.
Fahrtmuster: alles, was eine Fahrt fachlich ausmacht, außer dem Tag:
    Linie, Richtung, erste Station, Abfahrt an der ersten Station (E15).
Fahrtschlüssel: Fahrtmuster plus Betriebstag. Damit vergleiche ich.

Warum nicht die trip_id
-----------------------
Die trip_id ist im KVV-Feed eine Planungsnummer mit Version
("1.T0.24-44-E-s26-4.10.R"). Ändert der KVV einen Plan, ersetzt er die
Fahrten durch neue mit neuer trip_id, statt die alten zu ändern. Gemeinsame
trip_ids zweier Stände sind in meinen Daten immer inhaltsgleich. Über die
trip_id verglichen, wäre jede Änderung "entfallen und neu", auch wenn eine
Fahrt nur einen Halt mehr hat. Deshalb der eigene Schlüssel (E15).

Vergleichsfenster (E16)
-----------------------
Verglichen werden nur Fahrten, die nach dem Abruf des neuen Stands beginnen
und an einem Kalendertag liegen, den beide Stände abdecken. Sonst würde das
normale Vorrücken des Gültigkeitszeitraums als Änderung zählen: Gestern
fällt hinten heraus, ein neuer Tag kommt vorn dazu, und keiner hat etwas
geändert.

Änderungsarten
--------------
neu            Fahrtmuster nur im neuen Stand (im Fenster)
entfallen      Fahrtmuster nur im alten Stand (im Fenster)
betriebstage   Fahrtmuster in beiden Ständen, aber an diesem Tag nur in einem
               (detail: "Tag entfällt" oder "Tag kommt dazu")
halteverlauf   gleiche Fahrt, andere Folge von Stationen
zeit           gleiche Fahrt, gleiche Stationen, mindestens eine Zeit um eine
               Minute oder mehr verschoben (verschiebung_min)

Stammdaten (Namen, Lage) kommen nicht von hier, sondern aus den
SCD2-Dimensionen in PostgreSQL.
"""

from dataclasses import dataclass
from datetime import date, datetime

import pandas as pd

from betriebstage import betriebstage, gtfs_zeit_in_sekunden, station_je_halt

MUSTER = ["route_id", "direction_id", "erste_station", "erste_abfahrt_sek"]
SCHLUESSEL = MUSTER + ["betriebstag"]
MINDEST_VERSCHIEBUNG_SEK = 60    # unter einer Minute zählt nicht (Festlegung der Aufgabe)


@dataclass
class Fenster:
    """Welche Fahrten verglichen werden: Beginn nach `ab` (Ortszeit), Kalendertag bis `bis`."""
    ab: datetime      # Abruf des neuen Stands in deutscher Zeit, ohne Zeitzone
    bis: date         # letzter Tag, den beide Stände abdecken


# ---------------------------------------------------------------- Fahrten eines Stands

def fahrtverlaeufe(stop_times: pd.DataFrame, stops: pd.DataFrame) -> pd.DataFrame:
    """Je trip_id: erste Station, Abfahrt dort, Folge der Stationen und Zeiten.

    Als Zeit nehme ich die Abfahrt, am letzten Halt die Ankunft. Stationen
    statt Bahnsteige (E9): Ein Gleiswechsel ist für Fahrgäste keine geänderte
    Fahrt.
    """
    st = stop_times[["trip_id", "stop_sequence", "stop_id", "arrival_time", "departure_time"]].copy()
    st["trip_id"] = st["trip_id"].astype(str)
    st = st.sort_values(["trip_id", "stop_sequence"])
    st["station"] = st["stop_id"].astype(str).map(station_je_halt(stops))
    zeit = st["departure_time"].astype(object).where(st["departure_time"].notna(), st["arrival_time"].astype(object))
    st["sek"] = gtfs_zeit_in_sekunden(pd.Series(zeit, index=st.index).astype(str).replace("nan", pd.NA))

    g = st.groupby("trip_id", sort=False)
    verlauf = pd.DataFrame({
        "erste_station": g["station"].first(),
        "erste_abfahrt_sek": g["sek"].first(),
        "stationen": g["station"].agg(tuple),
        "zeiten": g["sek"].agg(lambda s: tuple(int(x) if pd.notna(x) else -1 for x in s)),
    })
    return verlauf.reset_index()


def fahrten(stand: dict, verlauf: pd.DataFrame, fenster: Fenster) -> pd.DataFrame:
    """Alle Fahrt-Instanzen eines Stands im Fenster, eine Zeile je Fahrt und Betriebstag.

    Betriebstage ab dem Vortag des Fensters: Eine Fahrt um 24:30 am Vortag
    beginnt erst nach Mitternacht und kann im Fenster liegen.
    """
    beginn = pd.Timestamp(fenster.ab).normalize()
    tage = betriebstage(stand["calendar"], stand["calendar_dates"], beginn - pd.Timedelta(days=1), pd.Timestamp(fenster.bis))
    trips = stand["trips"][["trip_id", "route_id", "service_id", "direction_id"]].astype(str)
    f = trips.merge(verlauf[["trip_id", "erste_station", "erste_abfahrt_sek"]], on="trip_id", how="inner")
    f = f.merge(tage.rename(columns={"datum": "betriebstag"}), on="service_id", how="inner")
    f["start"] = f["betriebstag"] + pd.to_timedelta(f["erste_abfahrt_sek"].astype("int64"), unit="s")
    f["kalendertag"] = f["start"].dt.normalize()
    imfenster = (f["start"] > pd.Timestamp(fenster.ab)) & (f["kalendertag"] <= pd.Timestamp(fenster.bis))
    return f.loc[imfenster].drop(columns="service_id").reset_index(drop=True)


def doppelte_schluessel(f: pd.DataFrame) -> pd.DataFrame:
    """Instanzen, deren Fahrtschlüssel im selben Stand mehrfach vorkommt.

    Dann wäre unklar, welche Fahrt im alten Stand zu welcher im neuen gehört.
    """
    return f[f.duplicated(SCHLUESSEL, keep=False)]


def eindeutig(f: pd.DataFrame) -> pd.DataFrame:
    """Macht den Schlüssel eindeutig, indem gleiche Fahrten durchnummeriert werden.

    Zwei Fahrten mit gleicher Linie, Richtung, erster Station und Minute am
    selben Tag (zum Beispiel ein Verstärkerbus) unterscheide ich über eine
    laufende Nummer, sortiert nach ihrem Halteverlauf. So ist die Zuordnung
    in beiden Ständen gleich, solange sich die Fahrten nicht ändern.
    """
    f = f.sort_values(SCHLUESSEL + ["sortierung"]).copy()
    f["nr"] = f.groupby(SCHLUESSEL, sort=False).cumcount()
    return f


# ---------------------------------------------------------------- Vergleich

def _inhalt(a_st: tuple, a_z: tuple, n_st: tuple, n_z: tuple):
    """Vergleich zweier Verläufe derselben Fahrt.

    Gibt (art, verschiebung_min, erste_betroffene_station, betroffene_stationen) zurück,
    oder None, wenn gleich.
    """
    if a_st != n_st:
        weg = set(a_st) - set(n_st)
        dazu = set(n_st) - set(a_st)
        betroffen = sorted(weg | dazu) or sorted(set(a_st) | set(n_st))
        erste = next((s for s in n_st if s in dazu), None) or next((s for s in a_st if s in weg), None) or betroffen[0]
        return "halteverlauf", None, erste, betroffen
    diffs = [(s, nz - az) for s, az, nz in zip(a_st, a_z, n_z) if az >= 0 and nz >= 0 and abs(nz - az) >= MINDEST_VERSCHIEBUNG_SEK]
    if not diffs:
        return None
    groesste = max(diffs, key=lambda d: abs(d[1]))[1]
    return "zeit", round(groesste / 60), diffs[0][0], sorted({s for s, _ in diffs})


def vergleiche(alt: pd.DataFrame, neu: pd.DataFrame, verlauf_alt: pd.DataFrame, verlauf_neu: pd.DataFrame):
    """Vergleicht die Fahrt-Instanzen zweier Stände im selben Fenster.

    Gibt drei Tabellen zurück:
    - aenderungen: eine Zeile je geänderter Fahrt-Instanz
    - halte: je Fahrtmuster und Änderungsart die betroffenen Stationen
    - je_linie: je Linie, wie viele Instanzen es alt/neu gab und wie viele unverändert sind
    """
    va = verlauf_alt.set_index("trip_id")
    vn = verlauf_neu.set_index("trip_id")
    for f, v in ((alt, va), (neu, vn)):
        f["sortierung"] = f["trip_id"].map(v["stationen"].astype(str) + v["zeiten"].astype(str))
    alt, neu = eindeutig(alt), eindeutig(neu)
    k = SCHLUESSEL + ["nr"]

    m = alt.merge(neu, on=k, how="outer", suffixes=("_alt", "_neu"), indicator=True)
    nur_alt = m[m["_merge"] == "left_only"]
    nur_neu = m[m["_merge"] == "right_only"]
    beide = m[m["_merge"] == "both"]

    zeilen, halte = [], []

    # Muster, die es im jeweils anderen Stand im Fenster überhaupt gibt
    muster_alt = set(map(tuple, alt[MUSTER].itertuples(index=False, name=None)))
    muster_neu = set(map(tuple, neu[MUSTER].itertuples(index=False, name=None)))

    def muster(r):
        return tuple(r[c] for c in MUSTER)

    for _, r in nur_alt.iterrows():
        mu = muster(r)
        if mu in muster_neu:
            zeilen.append({**{c: r[c] for c in k}, "kalendertag": r["kalendertag_alt"], "art": "betriebstage",
                           "detail": "Tag entfällt", "trip_id_alt": r["trip_id_alt"], "trip_id_neu": None})
        else:
            zeilen.append({**{c: r[c] for c in k}, "kalendertag": r["kalendertag_alt"], "art": "entfallen",
                           "detail": None, "trip_id_alt": r["trip_id_alt"], "trip_id_neu": None})
    for _, r in nur_neu.iterrows():
        mu = muster(r)
        if mu in muster_alt:
            zeilen.append({**{c: r[c] for c in k}, "kalendertag": r["kalendertag_neu"], "art": "betriebstage",
                           "detail": "Tag kommt dazu", "trip_id_alt": None, "trip_id_neu": r["trip_id_neu"]})
        else:
            zeilen.append({**{c: r[c] for c in k}, "kalendertag": r["kalendertag_neu"], "art": "neu",
                           "detail": None, "trip_id_alt": None, "trip_id_neu": r["trip_id_neu"]})

    # Gleiche Fahrt in beiden Ständen: Inhalt vergleichen. Gleiche trip_id
    # heißt gleicher Verlauf, das muss ich nicht Tag für Tag prüfen.
    verschieden = beide[beide["trip_id_alt"] != beide["trip_id_neu"]]
    cache = {}
    for _, r in verschieden.iterrows():
        paar = (r["trip_id_alt"], r["trip_id_neu"])
        if paar not in cache:
            a, n = va.loc[paar[0]], vn.loc[paar[1]]
            cache[paar] = _inhalt(a["stationen"], a["zeiten"], n["stationen"], n["zeiten"])
        erg = cache[paar]
        if erg is None:
            continue
        art, minuten, station, _ = erg
        zeilen.append({**{c: r[c] for c in k}, "kalendertag": r["kalendertag_alt"], "art": art,
                       "detail": None, "verschiebung_min": minuten, "station": station,
                       "trip_id_alt": paar[0], "trip_id_neu": paar[1]})

    aend = pd.DataFrame(zeilen, columns=k + ["kalendertag", "art", "detail", "verschiebung_min", "station",
                                              "trip_id_alt", "trip_id_neu"])

    # Betroffene Stationen je Muster und Art. Bei neu/entfallen/betriebstage
    # ist jede Station der Fahrt betroffen, bei Inhaltsänderungen nur die,
    # an denen sich etwas geändert hat.
    for (mu, art), gruppe in aend.groupby([aend[MUSTER].apply(tuple, axis=1), "art"]) if len(aend) else []:
        r = gruppe.iloc[0]
        if art in ("halteverlauf", "zeit"):
            stationen = cache[(r["trip_id_alt"], r["trip_id_neu"])][3]
        else:
            tid = r["trip_id_neu"] if pd.notna(r["trip_id_neu"]) else r["trip_id_alt"]
            v = vn if pd.notna(r["trip_id_neu"]) else va
            stationen = sorted(set(v.loc[tid, "stationen"]))
        for s in stationen:
            halte.append({"route_id": mu[0], "direction_id": mu[1], "erste_station": mu[2],
                          "erste_abfahrt_sek": mu[3], "art": art, "station": s})
    halte = pd.DataFrame(halte, columns=MUSTER + ["art", "station"]).drop_duplicates()

    # Je Linie: Grundlage für die Stabilitätsquote
    # Geändert heißt hier: Eine Fahrt des alten Stands gibt es so nicht mehr.
    # "neu" und "Tag kommt dazu" betreffen keine alte Fahrt und zählen nicht.
    betrifft_alt = (aend["art"].isin(["entfallen", "halteverlauf", "zeit"])
                    | ((aend["art"] == "betriebstage") & (aend["detail"] == "Tag entfällt")))
    geaendert = aend[betrifft_alt].groupby("route_id").size()
    je_linie = pd.DataFrame({
        "fahrten_alt": alt.groupby("route_id").size(),
        "fahrten_neu": neu.groupby("route_id").size(),
    }).fillna(0).astype(int)
    je_linie["geaendert"] = geaendert.reindex(je_linie.index).fillna(0).astype(int)
    je_linie["neu"] = aend[~betrifft_alt].groupby("route_id").size().reindex(je_linie.index).fillna(0).astype(int)
    je_linie = je_linie.rename_axis("route_id").reset_index()
    return aend, halte, je_linie
