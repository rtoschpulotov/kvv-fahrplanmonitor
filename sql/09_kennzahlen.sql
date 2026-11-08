-- Kennzahlen zur Fahrplanstabilität als Sichten (Phase 4).
-- Autor: Rustam T.
--
-- Power BI soll hier nur noch anzeigen, nicht selbst rechnen. Jede Sicht
-- beantwortet eine Frage aus der Aufgabenstellung (D1 bis D5).

-- Hilfssicht: Standpaar mit lesbaren Daten
CREATE OR REPLACE VIEW v_standpaar AS
SELECT p.standpaar_sk,
       a.stand_id AS stand_alt, n.stand_id AS stand_neu,
       (a.abgerufen_utc AT TIME ZONE 'Europe/Berlin') AS abruf_alt,
       (n.abgerufen_utc AT TIME ZONE 'Europe/Berlin') AS abruf_neu,
       p.fenster_bis, p.stunden_dazwischen, p.fehler_dazwischen,
       p.fahrten_alt, p.fahrten_neu, p.geaendert, p.anteil_geaendert, p.ist_grosser_wechsel,
       p.trip_id_nur_alt, p.trip_id_nur_neu
  FROM dim_standpaar p
  JOIN dim_stand a ON a.stand_sk = p.stand_sk_alt
  JOIN dim_stand n ON n.stand_sk = p.stand_sk_neu;

-- D1. Stabilitätsquote je Linie und Standpaar: Anteil der Fahrten im
-- Fenster, die unverändert bleiben.
CREATE OR REPLACE VIEW v_stabilitaet_linie AS
SELECT sp.standpaar_sk, sp.stand_neu, sp.ist_grosser_wechsel,
       l.route_id, l.kurzname, l.verkehrsmittel,
       v.fahrten_alt, v.geaendert, v.hinzu,
       CASE WHEN v.fahrten_alt > 0
            THEN round(1 - v.geaendert::numeric / v.fahrten_alt, 4) END AS stabilitaetsquote
  FROM fakt_vergleich_linie v
  JOIN v_standpaar sp USING (standpaar_sk)
  JOIN dim_linie l USING (linie_sk);

-- D1 zusammengefasst je Linie über alle Standpaare, einmal mit und einmal
-- ohne große Fahrplanwechsel (E17). Gewichtet nach Fahrten, nicht als
-- Mittel der Quoten, damit ein Paar mit wenigen Fahrten nicht genauso
-- zählt wie eines mit vielen.
CREATE OR REPLACE VIEW v_stabilitaet_linie_gesamt AS
SELECT route_id, kurzname, verkehrsmittel,
       count(*)                                    AS standpaare,
       count(*) FILTER (WHERE geaendert > 0)       AS standpaare_mit_aenderung,
       round(1 - sum(geaendert)::numeric / nullif(sum(fahrten_alt), 0), 4) AS quote_mit_grossen,
       round(1 - sum(geaendert) FILTER (WHERE NOT ist_grosser_wechsel)::numeric
               / nullif(sum(fahrten_alt) FILTER (WHERE NOT ist_grosser_wechsel), 0), 4) AS quote_ohne_grosse
  FROM v_stabilitaet_linie
 GROUP BY route_id, kurzname, verkehrsmittel;

-- D2. Änderungshäufigkeit je Haltestelle: in wie vielen Standpaaren hat
-- sich dort mindestens eine Abfahrt geändert?
CREATE OR REPLACE VIEW v_aenderung_haltestelle AS
SELECT h.station_id, h.name, h.gemeinde,
       count(DISTINCT a.standpaar_sk)                              AS standpaare_mit_aenderung,
       (SELECT count(*) FROM dim_standpaar)                        AS standpaare_gesamt,
       count(DISTINCT a.standpaar_sk) FILTER (WHERE NOT p.ist_grosser_wechsel) AS ohne_grosse
  FROM fakt_aenderung_halt a
  JOIN dim_standpaar p USING (standpaar_sk)
  JOIN dim_haltestelle h ON h.haltestelle_sk = a.haltestelle_sk
 GROUP BY h.station_id, h.name, h.gemeinde;

-- D3. Kurzfristigkeit: Wie viele Tage vor der Fahrt war die Änderung
-- zuerst im Feed? Eingeteilt in Stufen, die für Fahrgäste etwas bedeuten.
CREATE OR REPLACE VIEW v_kurzfristigkeit AS
SELECT a.standpaar_sk, a.art,
       CASE WHEN a.vorlauf_tage = 0  THEN '1 am selben Tag'
            WHEN a.vorlauf_tage = 1  THEN '2 am Vortag'
            WHEN a.vorlauf_tage <= 7 THEN '3 bis 7 Tage'
            WHEN a.vorlauf_tage <= 14 THEN '4 bis 14 Tage'
            WHEN a.vorlauf_tage <= 28 THEN '5 bis 4 Wochen'
            ELSE '6 mehr als 4 Wochen' END AS vorlauf_stufe,
       count(*) AS fahrten,
       p.ist_grosser_wechsel,
       p.fehler_dazwischen > 0 AS ungenau   -- Abruf dazwischen fehlgeschlagen
  FROM fakt_aenderung a
  JOIN dim_standpaar p USING (standpaar_sk)
 GROUP BY 1, 2, 3, 5, 6;

-- D4. Änderungszeitpunkte: An welchem Wochentag und Monatstag erscheinen
-- Stände mit vielen Änderungen?
CREATE OR REPLACE VIEW v_aenderungszeitpunkt AS
SELECT sp.standpaar_sk, sp.stand_neu,
       d.wochentag, extract(day FROM sp.abruf_neu)::int AS monatstag,
       sp.geaendert, sp.anteil_geaendert, sp.ist_grosser_wechsel,
       (SELECT count(*) FROM fakt_aenderung a WHERE a.standpaar_sk = sp.standpaar_sk) AS aenderungen
  FROM v_standpaar sp
  JOIN dim_datum d ON d.datum = sp.abruf_neu::date;

-- D5. Umpacken gegen Ändern, aus dem Register. Je erfolgreichem Abruf:
-- Hat sich die ZIP geändert? Hat sich der Inhalt geändert?
-- LAG holt den vorigen erfolgreichen Abruf.
CREATE OR REPLACE VIEW v_umpacken AS
WITH ok AS (
    SELECT abgerufen_utc, inhalts_hash, zip_hash,
           lag(inhalts_hash) OVER (ORDER BY abgerufen_utc) AS inhalt_vorher,
           lag(zip_hash)     OVER (ORDER BY abgerufen_utc) AS zip_vorher
      FROM abruf
     WHERE status <> 'fehler'
)
SELECT abgerufen_utc,
       CASE WHEN inhalt_vorher IS NULL THEN 'erster Abruf'
            WHEN inhalts_hash <> inhalt_vorher THEN 'Inhalt geändert'
            WHEN zip_hash <> zip_vorher THEN 'nur neu gepackt'
            ELSE 'unverändert' END AS ergebnis
  FROM ok;

CREATE OR REPLACE VIEW v_umpacken_anteil AS
SELECT ergebnis, count(*) AS abrufe,
       round(100.0 * count(*) / sum(count(*)) OVER (), 1) AS prozent
  FROM v_umpacken
 WHERE ergebnis <> 'erster Abruf'
 GROUP BY ergebnis;

-- E3. Abfrage mit LAG über die Standfolge: Wie entwickeln sich die
-- Werktagsabfahrten je Linie von Stand zu Stand? Gezählt auf einem festen
-- Tag, damit das Vorrücken des Horizonts nichts verfälscht: dem letzten
-- Werktag außerhalb der Ferien, den alle Stände in fakt_abfahrten haben.
CREATE OR REPLACE VIEW v_werktag_je_linie_verlauf AS
WITH stichtag AS (
    SELECT max(d.datum) AS tag
      FROM dim_datum d
     WHERE d.tagestyp = 'Werktag' AND d.ist_schulferien IS FALSE
       AND d.datum >= (SELECT max(horizont_von) FROM dim_stand)
       AND d.datum <= (SELECT min(horizont_bis) FROM dim_stand)
), je_stand AS (
    SELECT s.stand_sk, s.stand_id, l.route_id, max(l.kurzname) AS kurzname, sum(f.anzahl) AS abfahrten
      FROM fakt_abfahrten f
      JOIN dim_stand s USING (stand_sk)
      JOIN dim_linie l USING (linie_sk)
     WHERE f.datum = (SELECT tag FROM stichtag)
     GROUP BY s.stand_sk, s.stand_id, l.route_id
)
SELECT (SELECT tag FROM stichtag) AS stichtag, stand_id, route_id, kurzname, abfahrten,
       abfahrten - lag(abfahrten) OVER (PARTITION BY route_id ORDER BY stand_sk) AS veraenderung
  FROM je_stand;
