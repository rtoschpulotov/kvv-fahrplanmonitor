"""
Welche GTFS-Dateien ändern sich von Stand zu Stand, und wie oft?
Autor: Rustam T.

Das ist die erste Frage, die ich MongoDB stelle und die eine CSV nicht gut
beantworten kann. Je Stand vergleiche ich die Dateiliste aus dem Manifest mit
der des Vorgängers und gebe nur die Dateien aus, deren SHA-256 sich geändert
hat, die neu dazugekommen sind oder die fehlen.

Wie die Abfrage arbeitet:
1. $setWindowFields mit $shift holt mir an jeden Stand die Dateiliste des
   zeitlich vorherigen Stands. Das ist dasselbe wie LAG() in SQL.
2. Zu jeder Datei suche ich über den Namen ihren Eintrag beim Vorgänger.
3. $filter behält nur die Dateien, deren Hash nicht mehr passt.

Aufruf:
    python analyse/geaenderte_dateien.py
"""

import os
import sys
from pathlib import Path
from urllib.parse import quote_plus

from dotenv import load_dotenv
from pymongo import MongoClient

# Je Stand: welche Dateien haben sich gegenüber dem Vorgänger geändert?
GEAENDERTE_DATEIEN_JE_STAND = [
    {"$setWindowFields": {
        "sortBy": {"abgerufen_utc": 1},
        "output": {"vorgaenger": {"$shift": {
            "output": {"stand": "$_id", "dateien": "$dateien"},
            "by": -1,
            "default": None,
        }}},
    }},
    # Der allererste Stand hat keinen Vorgänger, mit ihm vergleiche ich nichts.
    {"$match": {"vorgaenger": {"$ne": None}}},
    # An jede Datei hänge ich ihren Eintrag aus dem Vorgänger, gefunden über den Namen.
    {"$set": {"vergleich": {"$map": {
        "input": "$dateien",
        "as": "d",
        "in": {
            "name": "$$d.name",
            "sha256": "$$d.sha256",
            "zeilen_nachher": "$$d.zeilen",
            "alt": {"$first": {"$filter": {
                "input": "$vorgaenger.dateien",
                "as": "v",
                "cond": {"$eq": ["$$v.name", "$$d.name"]},
            }}},
        },
    }}}},
    {"$project": {
        "_id": 0,
        "stand": "$_id",
        "vorgaenger": "$vorgaenger.stand",
        "abgerufen_utc": 1,
        # Geändert ist eine Datei, wenn ihr Hash nicht mehr passt. Fehlt sie im
        # Vorgänger ganz, ist alt.sha256 leer und sie zählt ebenfalls.
        "geaendert": {"$map": {
            "input": {"$filter": {
                "input": "$vergleich",
                "as": "d",
                "cond": {"$ne": ["$$d.sha256", "$$d.alt.sha256"]},
            }},
            "as": "d",
            "in": {"name": "$$d.name", "zeilen_vorher": "$$d.alt.zeilen", "zeilen_nachher": "$$d.zeilen_nachher"},
        }},
        "entfernt": {"$setDifference": ["$vorgaenger.dateien.name", "$dateien.name"]},
    }},
    {"$sort": {"abgerufen_utc": 1}},
]

# Über alle Stände: wie oft hat sich welche Datei geändert?
HAEUFIGKEIT_JE_DATEI = GEAENDERTE_DATEIEN_JE_STAND[:-1] + [
    {"$unwind": "$geaendert"},
    {"$group": {"_id": "$geaendert.name", "aenderungen": {"$sum": 1}}},
    {"$sort": {"aenderungen": -1, "_id": 1}},
]


def mongo_db():
    uri = os.environ.get("MONGO_URI")
    if not uri:
        benutzer = quote_plus(os.environ["MONGO_INITDB_ROOT_USERNAME"])
        passwort = quote_plus(os.environ["MONGO_INITDB_ROOT_PASSWORD"])
        host = os.environ.get("MONGO_HOST", "127.0.0.1")
        port = os.environ.get("MONGO_PORT", "27017")
        uri = f"mongodb://{benutzer}:{passwort}@{host}:{port}/?authSource=admin"
    return MongoClient(uri, tz_aware=True, serverSelectionTimeoutMS=5000)[os.environ.get("MONGO_DB", "kvv_landing")]


def main() -> int:
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
    db = mongo_db()
    anzahl = db.snapshots.count_documents({})
    print(f"{anzahl} Stände in der Landing Zone\n")

    for zeile in db.snapshots.aggregate(GEAENDERTE_DATEIEN_JE_STAND):
        print(f"{zeile['stand']} (Vorgänger {zeile['vorgaenger']})")
        for datei in zeile["geaendert"]:
            vorher = datei.get("zeilen_vorher")
            if vorher is None:
                print(f"  + {datei['name']:28} neu, {datei['zeilen_nachher']} Zeilen")
            else:
                diff = datei["zeilen_nachher"] - vorher
                print(f"  ~ {datei['name']:28} {vorher} -> {datei['zeilen_nachher']} Zeilen ({diff:+d})")
        for name in zeile["entfernt"]:
            print(f"  - {name:28} nicht mehr enthalten")
        if not zeile["geaendert"] and not zeile["entfernt"]:
            # Kann vorkommen, wenn ein Stand nur Dateien umbenennt. Sollte selten sein.
            print("  keine Datei geändert")

    print("\nÄnderungen je Datei über alle Stände:")
    for zeile in db.snapshots.aggregate(HAEUFIGKEIT_JE_DATEI):
        print(f"  {zeile['_id']:28} {zeile['aenderungen']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
