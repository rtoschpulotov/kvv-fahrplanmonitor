"""
Sammelskript für den KVV-Fahrplanmonitor.
Autor: Rustam T.

Was ich hier mache:
Ich lade einmal am Tag die GTFS-Datei des KVV herunter, prüfe, ob sich der
Inhalt seit dem letzten Lauf geändert hat, und lege nur geänderte Stände ab.
Jeder Lauf bekommt eine Zeile im Snapshot-Register, auch wenn sich nichts
geändert hat. So weiß ich später nicht nur, WAS sich geändert hat, sondern
auch, an welchen Tagen nachweislich NICHTS passiert ist.

Warum zwei Hashes:
Der ZIP-Hash allein reicht mir nicht. Wenn der KVV die Datei neu packt, ohne
am Fahrplan etwas zu ändern, ändern sich trotzdem die Bytes (Zeitstempel im
ZIP). Deshalb berechne ich zusätzlich einen Inhalts-Hash über die einzelnen
GTFS-Dateien. Ob ein Stand neu ist, entscheide ich am Inhalts-Hash.

Aufruf:
    python sammler/sammle_snapshot.py
    python sammler/sammle_snapshot.py --ziel data/raw --register data/snapshot_register.csv
"""

import argparse
import csv
import hashlib
import io
import os
import sys
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import requests

QUELL_URL = "https://projekte.kvv-efa.de/GTFS/google_transit.zip"

# Ohne diese Dateien ist ein GTFS-Feed für mich nicht auswertbar.
# calendar.txt und calendar_dates.txt prüfe ich getrennt, weil GTFS erlaubt,
# dass nur eine von beiden vorhanden ist.
PFLICHTDATEIEN = {"agency.txt", "stops.txt", "routes.txt", "trips.txt", "stop_times.txt"}
KALENDERDATEIEN = {"calendar.txt", "calendar_dates.txt"}

REGISTER_SPALTEN = [
    "abgerufen_utc",
    "status",            # neu | unveraendert | fehler
    "inhalts_hash",
    "zip_hash",
    "groesse_bytes",
    "http_last_modified",
    "http_etag",
    "dateiname",
    "anzahl_dateien",
    "fehler",
]


def lade_herunter(url: str, versuche: int = 3) -> requests.Response:
    """Ich versuche es mehrmals, weil ein einzelner Netzwerkfehler sonst einen ganzen Tag kostet."""
    letzter_fehler = None
    for versuch in range(1, versuche + 1):
        try:
            antwort = requests.get(url, timeout=120)
            antwort.raise_for_status()
            return antwort
        except requests.RequestException as fehler:
            letzter_fehler = fehler
            print(f"Versuch {versuch} fehlgeschlagen: {fehler}", file=sys.stderr)
            if versuch < versuche:
                time.sleep(30 * versuch)
    raise RuntimeError(f"Download nach {versuche} Versuchen gescheitert: {letzter_fehler}")


def pruefe_und_hashe(inhalt: bytes) -> tuple[str, int]:
    """Prüft, ob die ZIP ein brauchbarer GTFS-Feed ist, und berechnet den Inhalts-Hash.

    Der Inhalts-Hash entsteht aus Dateiname und SHA-256 jeder enthaltenen Datei,
    alphabetisch sortiert. Reihenfolge im ZIP und Pack-Zeitstempel spielen damit keine Rolle.
    """
    with zipfile.ZipFile(io.BytesIO(inhalt)) as archiv:
        namen = sorted(n for n in archiv.namelist() if not n.endswith("/"))
        vorhanden = {Path(n).name for n in namen}

        fehlend = PFLICHTDATEIEN - vorhanden
        if fehlend:
            raise ValueError(f"Pflichtdateien fehlen: {', '.join(sorted(fehlend))}")
        if not (KALENDERDATEIEN & vorhanden):
            raise ValueError("Weder calendar.txt noch calendar_dates.txt vorhanden")

        gesamt = hashlib.sha256()
        for name in namen:
            datei_hash = hashlib.sha256(archiv.read(name)).hexdigest()
            gesamt.update(f"{name}:{datei_hash}\n".encode("utf-8"))
        return gesamt.hexdigest(), len(namen)


def letzter_inhalts_hash(register: Path) -> str | None:
    """Der Hash des letzten erfolgreich abgelegten Stands, also der letzten Zeile mit Status 'neu'."""
    if not register.exists():
        return None
    letzter = None
    with register.open(newline="", encoding="utf-8") as f:
        for zeile in csv.DictReader(f):
            if zeile["status"] == "neu":
                letzter = zeile["inhalts_hash"]
    return letzter


def schreibe_registerzeile(register: Path, zeile: dict) -> None:
    neu_anlegen = not register.exists()
    register.parent.mkdir(parents=True, exist_ok=True)
    with register.open("a", newline="", encoding="utf-8") as f:
        schreiber = csv.DictWriter(f, fieldnames=REGISTER_SPALTEN)
        if neu_anlegen:
            schreiber.writeheader()
        schreiber.writerow({spalte: zeile.get(spalte, "") for spalte in REGISTER_SPALTEN})


def melde_an_github(status: str, dateipfad: str) -> None:
    """Wenn das Skript in GitHub Actions läuft, gebe ich dem Workflow Status und Pfad weiter."""
    ausgabe = os.environ.get("GITHUB_OUTPUT")
    if ausgabe:
        with open(ausgabe, "a", encoding="utf-8") as f:
            f.write(f"status={status}\n")
            f.write(f"datei={dateipfad}\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Lädt den aktuellen KVV-GTFS-Stand und archiviert ihn bei Änderung.")
    parser.add_argument("--url", default=QUELL_URL)
    parser.add_argument("--ziel", default="data/raw", help="Ordner für die ZIP-Dateien")
    parser.add_argument("--register", default="data/snapshot_register.csv")
    args = parser.parse_args()

    zielordner = Path(args.ziel)
    register = Path(args.register)
    jetzt = datetime.now(timezone.utc)
    zeile = {"abgerufen_utc": jetzt.strftime("%Y-%m-%dT%H:%M:%SZ")}

    try:
        antwort = lade_herunter(args.url)
        inhalt = antwort.content
        inhalts_hash, anzahl = pruefe_und_hashe(inhalt)
    except (RuntimeError, ValueError, zipfile.BadZipFile) as fehler:
        # Auch ein Fehlschlag kommt ins Register. Eine Lücke im Archiv soll später erklärbar sein.
        zeile.update(status="fehler", fehler=str(fehler)[:300])
        schreibe_registerzeile(register, zeile)
        melde_an_github("fehler", "")
        print(f"FEHLER: {fehler}", file=sys.stderr)
        return 1

    zeile.update(
        inhalts_hash=inhalts_hash,
        zip_hash=hashlib.sha256(inhalt).hexdigest(),
        groesse_bytes=len(inhalt),
        http_last_modified=antwort.headers.get("Last-Modified", ""),
        http_etag=antwort.headers.get("ETag", ""),
        anzahl_dateien=anzahl,
    )

    if inhalts_hash == letzter_inhalts_hash(register):
        zeile["status"] = "unveraendert"
        schreibe_registerzeile(register, zeile)
        melde_an_github("unveraendert", "")
        print(f"Unverändert seit letztem Stand ({inhalts_hash[:12]})")
        return 0

    # Dateiname mit Uhrzeit, falls ich an einem Tag zweimal einen neuen Stand erwische.
    dateiname = f"kvv_gtfs_{jetzt.strftime('%Y-%m-%dT%H%M%SZ')}.zip"
    zielordner.mkdir(parents=True, exist_ok=True)
    zieldatei = zielordner / dateiname
    # Erst in eine temporäre Datei schreiben und dann umbenennen. Ein abgebrochener
    # Lauf hinterlässt so keine halbe ZIP, die später wie ein echter Stand aussieht.
    temp = zieldatei.with_suffix(".zip.part")
    temp.write_bytes(inhalt)
    temp.replace(zieldatei)

    zeile.update(status="neu", dateiname=dateiname)
    schreibe_registerzeile(register, zeile)
    melde_an_github("neu", str(zieldatei))
    print(f"Neuer Stand abgelegt: {zieldatei} ({len(inhalt) / 1_000_000:.1f} MB, {inhalts_hash[:12]})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
