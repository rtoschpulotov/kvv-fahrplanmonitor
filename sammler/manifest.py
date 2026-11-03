"""
Manifest je Stand für den KVV-Fahrplanmonitor.
Autor: Rustam T.

Was ich hier mache:
Für jeden neuen Stand schreibe ich neben die ZIP eine JSON-Datei, die sagt,
was drinsteckt: jede GTFS-Datei mit Größe, SHA-256 und Zeilenzahl. Das Register
(CSV) sagt mir nur, DASS sich etwas geändert hat. Das Manifest sagt mir, WELCHE
Datei sich geändert hat, ohne dass ich die 28,7 MB jedes Mal auspacken muss.

Warum ein eigenes Modul:
Der Sammler braucht die Funktionen für neue Stände, das Landing-Zone-Skript
braucht sie, um für ältere Releases ohne Manifest eines nachzubauen. Beide
sollen exakt dieselbe Rechnung verwenden, sonst passen die Hashes nicht.

Nur Standardbibliothek, damit der tägliche Workflow schlank bleibt.
"""

import hashlib
import io
import json
import zipfile
from pathlib import Path

MANIFEST_VERSION = 1

# 1 MB pro Block. stop_times.txt ist entpackt fast 300 MB groß. Blockweise
# lesen hält den Speicherbedarf im GitHub-Runner klein.
BLOCKGROESSE = 1024 * 1024


def lies_dateien(zip_inhalt: bytes) -> list[dict]:
    """Liefert für jede Datei im ZIP Name, Größe, SHA-256 und Zeilenzahl, sortiert nach Name.

    Zeilenzahl heißt bei mir: Datensätze ohne Kopfzeile. Ich zähle dafür die
    Zeilenumbrüche, statt jede Zeile mit dem csv-Modul zu parsen. Das ist bei
    stop_times.txt um ein Vielfaches schneller. Der Haken: Ein Zeilenumbruch
    innerhalb eines Feldes in Anführungszeichen würde doppelt zählen. Für den
    ersten KVV-Stand habe ich beide Varianten verglichen, sie stimmen überein.
    """
    dateien = []
    with zipfile.ZipFile(io.BytesIO(zip_inhalt)) as archiv:
        for name in sorted(n for n in archiv.namelist() if not n.endswith("/")):
            sha = hashlib.sha256()
            groesse = 0
            umbrueche = 0
            letzter_block = b""
            with archiv.open(name) as datei:
                while block := datei.read(BLOCKGROESSE):
                    sha.update(block)
                    groesse += len(block)
                    umbrueche += block.count(b"\n")
                    letzter_block = block
            # Letzte Zeile ohne abschließenden Umbruch zählt trotzdem als Zeile.
            zeilen_gesamt = umbrueche + (1 if letzter_block and not letzter_block.endswith(b"\n") else 0)
            dateien.append({
                "name": name,
                "groesse_bytes": groesse,
                "sha256": sha.hexdigest(),
                "zeilen": max(zeilen_gesamt - 1, 0),
            })
    return dateien


def inhalts_hash(dateien: list[dict]) -> str:
    """Gesamt-Hash über alle Dateien, genau wie seit Phase 0: 'name:sha256' je Zeile, sortiert.

    An dieser Rechnung darf ich nichts ändern. Jeder bisherige Registereintrag
    hängt daran, und ein anderer Hash würde jeden alten Stand als neu erscheinen lassen.
    """
    gesamt = hashlib.sha256()
    for datei in sorted(dateien, key=lambda d: d["name"]):
        gesamt.update(f"{datei['name']}:{datei['sha256']}\n".encode("utf-8"))
    return gesamt.hexdigest()


def baue_manifest(*, zip_inhalt: bytes, dateien: list[dict], zip_datei: str, abgerufen_utc: str,
                  quelle_url: str, http_last_modified: str = "", http_etag: str = "",
                  erzeugt_von: str = "sammle_snapshot.py") -> dict:
    return {
        "manifest_version": MANIFEST_VERSION,
        "zip_datei": zip_datei,
        "abgerufen_utc": abgerufen_utc,
        "quelle_url": quelle_url,
        "inhalts_hash": inhalts_hash(dateien),
        "zip_hash": hashlib.sha256(zip_inhalt).hexdigest(),
        "groesse_bytes": len(zip_inhalt),
        "http": {"last_modified": http_last_modified, "etag": http_etag},
        "anzahl_dateien": len(dateien),
        "dateien": dateien,
        "erzeugt_von": erzeugt_von,
    }


def manifest_pfad(zip_pfad: Path) -> Path:
    """kvv_gtfs_2026-11-03T201359Z.zip -> kvv_gtfs_2026-11-03T201359Z_manifest.json"""
    return zip_pfad.with_name(f"{zip_pfad.stem}_manifest.json")


def schreibe_manifest(manifest: dict, ziel: Path) -> None:
    # Wie bei der ZIP erst temporär schreiben, dann umbenennen. Ein halbes
    # Manifest wäre schlimmer als gar keins.
    temp = ziel.with_suffix(".json.part")
    temp.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(ziel)
