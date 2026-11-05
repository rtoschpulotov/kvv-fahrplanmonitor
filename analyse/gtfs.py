"""
GTFS-Dateien aus einem gesammelten Stand einlesen.
Autor: Rustam T.

Ich lese direkt aus der ZIP, ohne sie auszupacken. Ein Stand hat rund
285 MB entpackt, und ausgepackte Kopien würden sich in data/raw/ nur stapeln.

Alle Spalten kommen zunächst als Text herein. GTFS-IDs sehen manchmal wie
Zahlen aus ("02" als agency_id), und Pandas würde daraus 2 machen und die
führende Null verlieren. Zahlen wandle ich erst dort um, wo ich mit ihnen
rechne.

stop_times.txt ist die mit Abstand größte Datei (gut 3 Mio. Zeilen). Dort lese
ich nur die Spalten, die ich brauche, und lege IDs und Uhrzeiten als Kategorie
an. Eine Kategorie speichert jeden unterschiedlichen Text nur einmal und in
der Tabelle selbst nur eine kleine Nummer. Beim Stand vom 04.11.2026 sind das
147.492 Fahrten und 14.465 verschiedene Uhrzeiten auf 3 Mio. Zeilen. Gemessen:
rund 73 MB im Speicher, mit den Uhrzeiten als Text waren es gut 400 MB.
"""

import zipfile
from pathlib import Path

import pandas as pd

STOP_TIMES_SPALTEN = {
    "trip_id": "category",
    "arrival_time": "category",
    "departure_time": "category",
    "stop_id": "category",
    "stop_sequence": "int32",
    "pickup_type": "Int8",     # großes I: ganze Zahl, die auch leer sein darf
    "drop_off_type": "Int8",
}


def lies_tabelle(zip_pfad: Path, name: str, spalten=None, dtype=None) -> pd.DataFrame:
    """Eine Datei wie "trips.txt" aus der ZIP als DataFrame.

    encoding utf-8-sig: Der KVV schreibt ein Byte-Order-Mark an den Dateianfang.
    Mit einfachem utf-8 hieße die erste Spalte sonst "\\ufeffservice_id".
    keep_default_na=False: Leere Felder bleiben leere Texte. Sonst würde Pandas
    zum Beispiel eine Haltestelle namens "NA" zu einem fehlenden Wert machen.
    """
    with zipfile.ZipFile(zip_pfad) as z, z.open(name) as f:
        return pd.read_csv(
            f,
            encoding="utf-8-sig",
            usecols=spalten,
            dtype=dtype if dtype is not None else str,
            keep_default_na=False,
        )


def lies_stop_times(zip_pfad: Path) -> pd.DataFrame:
    """stop_times.txt mit festgelegten Spalten und Datentypen.

    Hier muss keep_default_na an bleiben, sonst kann Pandas leere Felder nicht
    in Int8 umwandeln. Leere Uhrzeiten werden dadurch zu fehlenden Werten, und
    genau so will ich sie auch haben.
    """
    with zipfile.ZipFile(zip_pfad) as z, z.open("stop_times.txt") as f:
        return pd.read_csv(
            f,
            encoding="utf-8-sig",
            usecols=list(STOP_TIMES_SPALTEN),
            dtype=STOP_TIMES_SPALTEN,
        )


def lies_stand(zip_pfad: Path) -> dict:
    """Die Tabellen, die ich für Betriebstage und Abfahrten brauche."""
    return {
        "calendar": lies_tabelle(zip_pfad, "calendar.txt"),
        "calendar_dates": lies_tabelle(zip_pfad, "calendar_dates.txt"),
        "trips": lies_tabelle(zip_pfad, "trips.txt", spalten=["route_id", "service_id", "trip_id"]),
        "routes": lies_tabelle(zip_pfad, "routes.txt"),
        "stops": lies_tabelle(zip_pfad, "stops.txt"),
        "feed_info": lies_tabelle(zip_pfad, "feed_info.txt"),
        "stop_times": lies_stop_times(zip_pfad),
    }
