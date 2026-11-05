"""
Profil eines gesammelten Stands: die Zahlen für docs/befunde.md.
Autor: Rustam T.

Bevor ich irgendetwas auswerte, will ich wissen, was im Feed steht. Das Skript
gibt die Kennzahlen aus Phase 2, Aufgabe A aus und dazu die Zahl der Fahrten je
Kalendertag. An der Tagesreihe sehe ich auf einen Blick, ob Feiertage und
Ferien so aussehen, wie ich es erwarte (Aufgabe C2).

Aufruf:
    python analyse/profil.py data/raw/kvv_gtfs_2026-11-04T120817Z.zip
"""

import argparse
import zipfile
from pathlib import Path

import pandas as pd

from betriebstage import abfahrten, betriebstage, gtfs_zeit_in_sekunden, station_je_halt
from gtfs import lies_stand

ROUTE_TYPEN = {"0": "Straßen-/Stadtbahn", "1": "U-Bahn", "2": "Eisenbahn", "3": "Bus"}


def zeilen_je_datei(zip_pfad: Path) -> dict:
    """Datensätze ohne Kopfzeile, gezählt wie im Manifest (E7)."""
    ergebnis = {}
    with zipfile.ZipFile(zip_pfad) as z:
        for name in sorted(z.namelist()):
            with z.open(name) as f:
                ergebnis[name] = sum(1 for _ in f) - 1
    return ergebnis


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    parser.add_argument("zip", type=Path)
    args = parser.parse_args()

    d = lies_stand(args.zip)
    print(f"# Profil {args.zip.name}\n")

    print("## Zeilen je Datei")
    for name, n in zeilen_je_datei(args.zip).items():
        print(f"{name:28} {n:>12,}".replace(",", "."))

    fi = d["feed_info"].iloc[0]
    cal = d["calendar"]
    print("\n## Zeitraum")
    print(f"feed_info:  {fi['feed_start_date']} bis {fi['feed_end_date']}, Version {fi['feed_version']}")
    print(f"calendar:   {cal['start_date'].min()} bis {cal['end_date'].max()}")

    cd = d["calendar_dates"]
    sid_cal, sid_cd = set(cal["service_id"]), set(cd["service_id"])
    sid_trips = set(d["trips"]["service_id"])
    print("\n## service_id")
    print(f"in calendar:                    {len(sid_cal)}")
    print(f"in calendar_dates:              {len(sid_cd)}")
    print(f"nur in calendar_dates:          {len(sid_cd - sid_cal)}")
    print(f"in trips, aber in keiner Datei: {len(sid_trips - sid_cal - sid_cd)}")
    typen = cd["exception_type"].value_counts().to_dict()
    print(f"Ausnahmen Typ 1 (dazu): {typen.get('1', 0)}, Typ 2 (weg): {typen.get('2', 0)}")

    print("\n## Linien je route_type")
    for typ, n in d["routes"]["route_type"].value_counts().items():
        print(f"{typ} {ROUTE_TYPEN.get(typ, '?'):20} {n}")

    stops = d["stops"]
    halte = stops[stops["location_type"].isin(["", "0"])]
    mit_eltern = (halte["parent_station"] != "").sum()
    print("\n## Haltestellen")
    print(f"Halte (location_type leer/0):  {len(halte)}")
    print(f"davon mit parent_station:      {mit_eltern} ({mit_eltern / len(halte):.1%})")
    print(f"Stationen (location_type 1):   {(stops['location_type'] == '1').sum()}")
    print(f"Stationen nach E9 insgesamt:   {station_je_halt(halte).nunique()}")

    st = d["stop_times"]
    sek = gtfs_zeit_in_sekunden(st["departure_time"])
    ueber = sek >= 24 * 3600
    print("\n## Uhrzeiten über 24 Uhr")
    print(f"Halte mit departure_time >= 24:00:00: {int(ueber.sum()):,}".replace(",", "."))
    print(f"betroffene Fahrten:                   {st.loc[ueber.fillna(False), 'trip_id'].nunique():,}".replace(",", "."))
    print(f"späteste Zeit:                        {int(sek.max()) // 3600}:{int(sek.max()) % 3600 // 60:02d}")
    print(f"Halte ohne Uhrzeit:                   {int(sek.isna().sum())}")
    print(f"pickup_type: {st['pickup_type'].value_counts(dropna=False).to_dict()}")

    print("\n## Fahrten je Tag (nach Betriebstag)")
    tage = betriebstage(cal, cd, cal["start_date"].min(), cal["end_date"].max())
    je_tag = d["trips"].merge(tage, on="service_id").groupby("datum").size()
    for datum, n in je_tag.items():
        print(f"{datum:%a %d.%m.%Y}  {n:>6}")


if __name__ == "__main__":
    main()
