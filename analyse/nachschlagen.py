"""
Einzelne Fahrten und Abfahrtstafeln aus einem Stand nachschlagen.
Autor: Rustam T.

Für die Prüfungen in Phase 2, bei denen ich den Feed mit eigenen Augen und
mit der KVV-Fahrplanauskunft vergleiche (Aufgaben A5 und C3).

Aufrufe:
    # fünf zufällige Fahrten, die am Stichtag fahren (Startwert fest, damit
    # beim nächsten Aufruf dieselben kommen)
    python analyse/nachschlagen.py zufall STAND.zip 2026-11-10 --anzahl 5

    # eine Fahrt im Detail
    python analyse/nachschlagen.py fahrt STAND.zip "1.T0.2-103-C-s26-1.6.R"

    # Abfahrtstafel einer Haltestelle (Name oder Teil davon) für einen Tag
    python analyse/nachschlagen.py tafel STAND.zip "Graben Bahnhof" 2026-11-10
"""

import argparse
from pathlib import Path

import pandas as pd

from bedienqualitaet import abfahrten_am_tag
from betriebstage import betriebstage, gtfs_zeit_in_sekunden
from gtfs import lies_stand

EINSTIEG = {0: "", 1: "kein Einstieg", 2: "nur nach Anmeldung", 3: "nach Absprache"}


def uhr(sek) -> str:
    if pd.isna(sek):
        return "--:--"
    sek = int(sek)
    return f"{sek // 3600:02d}:{sek % 3600 // 60:02d}"


def fahrt(stand: dict, trip_id: str, tag=None) -> str:
    """Steckbrief einer Fahrt: Linie, Ziel, Betriebstage, Halte mit Uhrzeiten."""
    trips = stand["trips"]
    t = trips[trips["trip_id"] == trip_id].iloc[0]
    r = stand["routes"].set_index("route_id").loc[t["route_id"]]
    namen = stand["stops"].set_index("stop_id")["stop_name"]
    st = stand["stop_times"]
    st = st[st["trip_id"] == trip_id].sort_values("stop_sequence")

    tage = betriebstage(stand["calendar"], stand["calendar_dates"],
                        stand["calendar"]["start_date"].min(), stand["calendar"]["end_date"].max())
    tage = tage.loc[tage["service_id"] == t["service_id"], "datum"]

    zeilen = [
        f"Fahrt {trip_id}",
        f"Linie {r['route_short_name']} (route_type {r['route_type']}), Richtung: {t.get('trip_headsign', '')}",
        f"service_id {t['service_id']}: {len(tage)} Betriebstage, "
        f"{tage.min():%d.%m.%Y} bis {tage.max():%d.%m.%Y}" if len(tage) else f"service_id {t['service_id']}: keine Betriebstage",
    ]
    if tag is not None:
        zeilen.append(f"fährt am {pd.Timestamp(tag):%d.%m.%Y}: {'ja' if pd.Timestamp(tag) in set(tage) else 'nein'}")
    zeilen.append("")
    zeilen.append(f"{'Nr':>3}  {'an':>5}  {'ab':>5}  Haltestelle")
    an = gtfs_zeit_in_sekunden(st["arrival_time"])
    ab = gtfs_zeit_in_sekunden(st["departure_time"])
    for (_, h), a, b in zip(st.iterrows(), an, ab):
        hinweis = EINSTIEG.get(int(h["pickup_type"]) if pd.notna(h["pickup_type"]) else 0, "")
        zeilen.append(f"{h['stop_sequence']:>3}  {uhr(a):>5}  {uhr(b):>5}  {namen.get(str(h['stop_id']), h['stop_id'])}"
                      + (f"  [{hinweis}]" if hinweis else ""))
    return "\n".join(zeilen)


def zufall(stand: dict, tag, anzahl: int = 5, startwert: int = 2026) -> list:
    """Zufällige Fahrten, die am Tag fahren, je höchstens eine pro Linie."""
    tage = betriebstage(stand["calendar"], stand["calendar_dates"], tag, tag)
    kandidaten = stand["trips"][stand["trips"]["service_id"].isin(tage["service_id"])]
    je_linie = kandidaten.groupby("route_id").sample(n=1, random_state=startwert)
    return je_linie.sample(n=anzahl, random_state=startwert)["trip_id"].tolist()


def tafel(stand: dict, name: str, tag) -> pd.DataFrame:
    """Alle Abfahrten an Stationen, deren Name `name` enthält, nach Kalenderzeit (E9)."""
    stops = stand["stops"]
    treffer = stops.loc[stops["stop_name"].str.contains(name, case=False, regex=False), "stop_id"]
    ab = abfahrten_am_tag(stand, tag)
    ab = ab[ab["stop_id"].astype(str).isin(set(treffer))]
    r = stand["routes"].set_index("route_id")["route_short_name"]
    ziel = stand["trips"].set_index("trip_id")["trip_headsign"] if "trip_headsign" in stand["trips"] else None
    namen = stops.set_index("stop_id")["stop_name"]
    return pd.DataFrame({
        "zeit": ab["zeitpunkt"].dt.strftime("%H:%M"),
        "linie": ab["route_id"].map(r).values,
        "richtung": ab["trip_id"].map(ziel).values if ziel is not None else "",
        "haltestelle": ab["stop_id"].astype(str).map(namen).values,
    }).sort_values("zeit").reset_index(drop=True)


def main() -> None:
    p = argparse.ArgumentParser(description="Fahrten und Abfahrtstafeln nachschlagen")
    p.add_argument("befehl", choices=["zufall", "fahrt", "tafel"])
    p.add_argument("stand", type=Path)
    p.add_argument("wert", help="Stichtag (zufall), trip_id (fahrt) oder Haltestellenname (tafel)")
    p.add_argument("tag", nargs="?", help="Stichtag für tafel und fahrt")
    p.add_argument("--anzahl", type=int, default=5)
    a = p.parse_args()

    stand = lies_stand(a.stand, trips_spalten=["route_id", "service_id", "trip_id", "trip_headsign"])
    if a.befehl == "zufall":
        for tid in zufall(stand, a.wert, a.anzahl):
            print(fahrt(stand, tid, a.wert), end="\n\n")
    elif a.befehl == "fahrt":
        print(fahrt(stand, a.wert, a.tag))
    else:
        pd.set_option("display.max_rows", None, "display.width", 200)
        print(tafel(stand, a.wert, a.tag).to_string())


if __name__ == "__main__":
    main()
