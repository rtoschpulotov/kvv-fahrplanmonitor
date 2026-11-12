"""
Messen, bevor ich umbaue (Phase 5, Aufgabe 1).
Autor: Rustam T.

Wie groß ist das Archiv, und wie lange braucht die Pandas-Variante für den
kompletten Vergleich aller Standpaare? Wie viel Arbeitsspeicher braucht sie
dabei höchstens? Ohne diese Zahlen wäre jede Begründung für Spark eine
Behauptung.

Gemessen wird genau das, was laden/lade_aenderungen.py rechnet, nur ohne
Datenbank: jeden Stand einmal einlesen, Fahrten im Fenster bilden, jedes Paar
direkter Nachbarn vergleichen. Der Speicher wird alle 50 ms abgelesen (RSS
des Prozesses), das Maximum ist der Spitzenwert.

Aufruf:
    python analyse/messung.py               # alle Stände in data/raw
    python analyse/messung.py --staende 4   # nur die ersten vier
"""

import argparse
import json
import sys
import threading
import time
from pathlib import Path

import psutil

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "analyse"))
sys.path.insert(0, str(REPO / "laden"))

from diff import fahrten, fahrtverlaeufe, vergleiche  # noqa: E402
from gtfs import lies_stand  # noqa: E402
from lade_aenderungen import fenster_fuer  # noqa: E402
from lade_postgres import feed_info, neue_staende  # noqa: E402


class Speicheruhr:
    """Liest im Hintergrund den Arbeitsspeicher ab und merkt sich das Maximum.

    psutil statt resource.getrusage, weil das auch unter Windows geht.
    Gezählt werden der Prozess und alle Kindprozesse (bei Spark die Java-VM).
    """

    def __init__(self, takt: float = 0.05):
        self.takt, self.spitze, self._stop = takt, 0, threading.Event()
        self._p = psutil.Process()

    def _miss(self) -> int:
        summe = self._p.memory_info().rss
        for kind in self._p.children(recursive=True):
            try:
                summe += kind.memory_info().rss
            except psutil.NoSuchProcess:
                pass
        return summe

    def _lauf(self):
        while not self._stop.is_set():
            self.spitze = max(self.spitze, self._miss())
            time.sleep(self.takt)

    def __enter__(self):
        self._t = threading.Thread(target=self._lauf, daemon=True)
        self._t.start()
        return self

    def __exit__(self, *_):
        self._stop.set()
        self._t.join()
        self.spitze = max(self.spitze, self._miss())

    @property
    def mb(self) -> int:
        return round(self.spitze / 1024 / 1024)


def miss_pandas(staende: list[dict]) -> dict:
    """Vergleicht alle direkten Nachbarn, wie lade_aenderungen.lade_alle, nur ohne Datenbank.

    Jeder Stand wird genau einmal eingelesen und bleibt im Speicher, bis er als
    "alter" Stand verglichen ist. So liegen höchstens zwei Stände gleichzeitig
    im Speicher, egal wie groß das Archiv ist.
    """
    ergebnis = {"paare": []}
    cache = {}

    def lies(s: dict):
        if s["stand_id"] not in cache:
            st = lies_stand(s["zip"], trips_spalten=("route_id", "service_id", "trip_id", "direction_id"))
            cache[s["stand_id"]] = (st, fahrtverlaeufe(st["stop_times"], st["stops"]))
            s["stop_times"] = len(st["stop_times"])
            s["feed_bis"] = feed_info(st)[2]
        return cache[s["stand_id"]]

    start = time.perf_counter()
    with Speicheruhr() as uhr:
        for a, n in zip(staende, staende[1:]):
            t = time.perf_counter()
            alt, neu = lies(a), lies(n)
            fenster = fenster_fuer({"neu_zeit": n["abgerufen_utc"], "alt_feed_bis": a["feed_bis"],
                                    "neu_feed_bis": n["feed_bis"]})
            aend, _, _ = vergleiche(fahrten(alt[0], alt[1], fenster), fahrten(neu[0], neu[1], fenster), alt[1], neu[1])
            ergebnis["paare"].append({"paar": f"{a['stand_id']} -> {n['stand_id']}", "aenderungen": len(aend),
                                      "sekunden": round(time.perf_counter() - t, 1)})
            cache.pop(a["stand_id"])
    ergebnis["sekunden_gesamt"] = round(time.perf_counter() - start, 1)
    ergebnis["spitze_mb"] = uhr.mb
    return ergebnis


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--staende", type=int, help="nur die ersten N Stände")
    parser.add_argument("--json", type=Path, help="Ergebnis zusätzlich als JSON speichern")
    args = parser.parse_args()

    staende = neue_staende(REPO / "data" / "snapshot_register.csv", REPO / "data" / "raw")
    staende = [s for s in staende if s["zip"].exists()][: args.staende]
    if len(staende) < 2:
        raise SystemExit("Mindestens zwei Stände in data/raw nötig.")

    erg = miss_pandas(staende)
    erg["staende"] = len(staende)
    erg["stop_times_zeilen"] = sum(s["stop_times"] for s in staende)
    erg["zip_mb"] = round(sum(s["zip"].stat().st_size for s in staende) / 1024 / 1024)

    zeilen = f"{erg['stop_times_zeilen']:,}".replace(",", ".")
    print(f"Stände: {erg['staende']}, ZIPs zusammen {erg['zip_mb']} MB, stop_times über alle Stände: {zeilen} Zeilen")
    for p in erg["paare"]:
        print(f"  {p['paar']}: {p['aenderungen']} Änderungen, {p['sekunden']} s")
    print(f"Pandas gesamt: {erg['sekunden_gesamt']} s, Spitze Arbeitsspeicher {erg['spitze_mb']} MB")
    if args.json:
        args.json.write_text(json.dumps(erg, indent=2, ensure_ascii=False), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
