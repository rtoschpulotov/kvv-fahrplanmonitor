"""
Landing Zone in MongoDB für den KVV-Fahrplanmonitor.
Autor: Rustam T.

Was ich hier mache:
1. Ich liste alle Releases im Repo über die GitHub-API auf und lade ZIPs und
   Manifeste nach data/raw/, die mir lokal noch fehlen.
2. Gibt es zu einem Release kein Manifest (betrifft die Stände vor Phase 1),
   baue ich es aus der ZIP und der passenden Registerzeile nach.
3. Jedes Manifest kommt als Dokument in die Collection "snapshots".
4. Das CSV-Register kommt vollständig in die Collection "abrufe", also auch
   die Tage ohne Änderung und die Fehlschläge.

Warum Upsert:
Das Skript muss beliebig oft laufen können, ohne Dubletten zu erzeugen. Jeder
Stand hat einen festen Schlüssel, und ich schreibe mit update_one(upsert=True).
Läuft es zweimal, ändert der zweite Lauf nichts. Das ist dasselbe Muster wie
der Upsert auf job_id in meiner Stellenmarkt-Pipeline.

Warum der Schlüssel der Stand ist und nicht der Inhalts-Hash:
Wenn der KVV eine Änderung zurücknimmt, kommt ein alter Inhalts-Hash ein
zweites Mal als neuer Stand vor (A, dann B, dann wieder A). Mit dem Hash als
Schlüssel würden die beiden A-Stände zu einem Dokument verschmelzen und die
Rücknahme wäre aus MongoDB verschwunden. Deshalb ist der Schlüssel der
Zeitstempel des Stands, und auf dem Inhalts-Hash liegt nur ein normaler Index.
Begründung ausführlich in docs/entscheidungen.md, E7.

Quelle der Wahrheit bleiben Register und Releases. MongoDB ist abgeleitet und
lässt sich jederzeit mit diesem Skript neu aufbauen.

Aufruf:
    python sammler/lade_landing_zone.py
    python sammler/lade_landing_zone.py --ohne-github     # nur was schon in data/raw liegt
"""

import argparse
import csv
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote_plus

import requests
from dotenv import load_dotenv
from pymongo import ASCENDING, MongoClient, UpdateOne

from manifest import baue_manifest, lies_dateien, manifest_pfad, schreibe_manifest

STANDARD_REPO = "rtoschpulotov/kvv-fahrplanmonitor"
QUELL_URL = "https://projekte.kvv-efa.de/GTFS/google_transit.zip"
ZIP_PRAEFIX = "kvv_gtfs_"


# ---------------------------------------------------------------- GitHub

def github_session() -> requests.Session:
    """Ohne Token erlaubt GitHub nur 60 API-Anfragen pro Stunde. Ein Token mit Leserecht reicht."""
    session = requests.Session()
    session.headers["Accept"] = "application/vnd.github+json"
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if token:
        session.headers["Authorization"] = f"Bearer {token}"
    return session


def liste_releases(session: requests.Session, repo: str) -> list[dict]:
    releases, seite = [], 1
    while True:
        antwort = session.get(f"https://api.github.com/repos/{repo}/releases",
                              params={"per_page": 100, "page": seite}, timeout=60)
        antwort.raise_for_status()
        teil = antwort.json()
        if not teil:
            return releases
        releases.extend(r for r in teil if r["tag_name"].startswith("snapshot-"))
        seite += 1


def lade_asset(session: requests.Session, url: str, ziel: Path) -> None:
    temp = ziel.with_name(ziel.name + ".part")
    with session.get(url, stream=True, timeout=300) as antwort:
        antwort.raise_for_status()
        with temp.open("wb") as f:
            for block in antwort.iter_content(1024 * 1024):
                f.write(block)
    temp.replace(ziel)


def hole_fehlende_dateien(session: requests.Session, repo: str, rohordner: Path) -> dict[str, str]:
    """Lädt fehlende ZIPs und Manifeste. Gibt zurück, welcher ZIP-Name zu welchem Release-Tag gehört."""
    tags = {}
    for release in liste_releases(session, repo):
        for asset in release["assets"]:
            name = asset["name"]
            if not name.startswith(ZIP_PRAEFIX):
                continue
            if name.endswith(".zip"):
                tags[name] = release["tag_name"]
            ziel = rohordner / name
            if ziel.exists() and ziel.stat().st_size == asset["size"]:
                continue
            print(f"Lade {name} ({asset['size'] / 1_000_000:.1f} MB)")
            lade_asset(session, asset["browser_download_url"], ziel)
    return tags


# ---------------------------------------------------------------- Register und Manifeste

def lies_register(register: Path) -> list[dict]:
    if not register.exists():
        return []
    with register.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def manifest_fuer(zip_pfad: Path, registerzeilen: dict[str, dict]) -> dict:
    """Liest das Manifest neben der ZIP. Fehlt es, baue ich es aus ZIP und Registerzeile nach."""
    pfad = manifest_pfad(zip_pfad)
    inhalt = zip_pfad.read_bytes()

    if pfad.exists():
        manifest = json.loads(pfad.read_text(encoding="utf-8"))
    else:
        zeile = registerzeilen.get(zip_pfad.name)
        if zeile is None:
            raise ValueError(f"{zip_pfad.name}: kein Manifest und keine Registerzeile, Herkunft unklar")
        manifest = baue_manifest(
            zip_inhalt=inhalt,
            dateien=lies_dateien(inhalt),
            zip_datei=zip_pfad.name,
            abgerufen_utc=zeile["abgerufen_utc"],
            quelle_url=QUELL_URL,
            http_last_modified=zeile["http_last_modified"],
            http_etag=zeile["http_etag"],
            erzeugt_von="lade_landing_zone.py (nachgebaut aus ZIP und Register)",
        )
        # Der nachgebaute Hash muss zu dem passen, den der Sammler damals ins
        # Register geschrieben hat. Sonst stimmt etwas mit der Datei nicht.
        if manifest["inhalts_hash"] != zeile["inhalts_hash"]:
            raise ValueError(f"{zip_pfad.name}: Inhalts-Hash passt nicht zum Register")
        schreibe_manifest(manifest, pfad)
        print(f"Manifest nachgebaut: {pfad.name}")

    # Prüfsumme gegen die heruntergeladene ZIP. Ein abgebrochener Download fällt hier auf.
    if hashlib.sha256(inhalt).hexdigest() != manifest["zip_hash"]:
        raise ValueError(f"{zip_pfad.name}: ZIP-Hash passt nicht zum Manifest")
    return manifest


def als_zeitpunkt(text: str) -> datetime:
    return datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def stand_id(zip_name: str) -> str:
    """kvv_gtfs_2026-11-03T201359Z.zip -> 2026-11-03T201359Z, derselbe Teil wie im Release-Tag."""
    return zip_name.removeprefix(ZIP_PRAEFIX).removesuffix(".zip")


# ---------------------------------------------------------------- MongoDB

def mongo_client() -> MongoClient:
    uri = os.environ.get("MONGO_URI")
    if not uri:
        benutzer = quote_plus(os.environ["MONGO_INITDB_ROOT_USERNAME"])
        passwort = quote_plus(os.environ["MONGO_INITDB_ROOT_PASSWORD"])
        host = os.environ.get("MONGO_HOST", "127.0.0.1")
        port = os.environ.get("MONGO_PORT", "27017")
        uri = f"mongodb://{benutzer}:{passwort}@{host}:{port}/?authSource=admin"
    return MongoClient(uri, tz_aware=True, serverSelectionTimeoutMS=5000)


def richte_indizes_ein(db) -> None:
    db.snapshots.create_index([("inhalts_hash", ASCENDING)])
    db.snapshots.create_index([("abgerufen_utc", ASCENDING)])
    db.snapshots.create_index([("verarbeitet_am", ASCENDING)])
    db.abrufe.create_index([("abgerufen_utc", ASCENDING)])
    db.abrufe.create_index([("status", ASCENDING)])


def snapshot_operation(manifest: dict, release_tag: str | None, zip_pfad: Path) -> UpdateOne:
    dokument = dict(manifest)
    dokument["abgerufen_utc"] = als_zeitpunkt(manifest["abgerufen_utc"])
    dokument["release_tag"] = release_tag
    dokument["lokale_zip"] = zip_pfad.as_posix()
    return UpdateOne(
        {"_id": stand_id(manifest["zip_datei"])},
        {
            "$set": dokument,
            # verarbeitet_am setzen erst Phase 2 und 3. Hier lege ich das Feld
            # nur beim ersten Einfügen an und fasse es danach nie wieder an,
            # sonst würde ein erneuter Lauf einen verarbeiteten Stand zurücksetzen.
            "$setOnInsert": {"verarbeitet_am": None},
        },
        upsert=True,
    )


def abruf_operation(zeile: dict) -> UpdateOne:
    def als_zahl(text: str) -> int | None:
        return int(text) if text else None

    dokument = {
        "abgerufen_utc": als_zeitpunkt(zeile["abgerufen_utc"]),
        "status": zeile["status"],
        "inhalts_hash": zeile["inhalts_hash"] or None,
        "zip_hash": zeile["zip_hash"] or None,
        "groesse_bytes": als_zahl(zeile["groesse_bytes"]),
        "http": {"last_modified": zeile["http_last_modified"], "etag": zeile["http_etag"]},
        "dateiname": zeile["dateiname"] or None,
        "anzahl_dateien": als_zahl(zeile["anzahl_dateien"]),
        "fehler": zeile["fehler"] or None,
    }
    return UpdateOne({"_id": zeile["abgerufen_utc"]}, {"$set": dokument}, upsert=True)


def main() -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(description="Lädt Releases und Register in die MongoDB-Landing-Zone.")
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPO", STANDARD_REPO))
    parser.add_argument("--rohdaten", default="data/raw")
    parser.add_argument("--register", default="data/snapshot_register.csv")
    parser.add_argument("--datenbank", default=os.environ.get("MONGO_DB", "kvv_landing"))
    parser.add_argument("--ohne-github", action="store_true", help="keine Downloads, nur data/raw verwenden")
    args = parser.parse_args()

    rohordner = Path(args.rohdaten)
    rohordner.mkdir(parents=True, exist_ok=True)
    registerzeilen = lies_register(Path(args.register))
    zeilen_nach_datei = {z["dateiname"]: z for z in registerzeilen if z["status"] == "neu"}

    tags = {}
    if not args.ohne_github:
        tags = hole_fehlende_dateien(github_session(), args.repo, rohordner)

    operationen = []
    for zip_pfad in sorted(rohordner.glob(f"{ZIP_PRAEFIX}*.zip")):
        manifest = manifest_fuer(zip_pfad, zeilen_nach_datei)
        tag = tags.get(zip_pfad.name, f"snapshot-{stand_id(zip_pfad.name)}")
        operationen.append(snapshot_operation(manifest, tag, zip_pfad))

    db = mongo_client()[args.datenbank]
    richte_indizes_ein(db)

    for name, ops in (("snapshots", operationen), ("abrufe", [abruf_operation(z) for z in registerzeilen])):
        if not ops:
            print(f"{name}: nichts zu laden")
            continue
        ergebnis = db[name].bulk_write(ops, ordered=False)
        print(f"{name}: {ergebnis.upserted_count} neu, {ergebnis.modified_count} geändert, "
              f"{db[name].count_documents({})} Dokumente insgesamt")
    return 0


if __name__ == "__main__":
    sys.exit(main())
