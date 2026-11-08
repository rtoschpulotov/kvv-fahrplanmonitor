-- Sternschema für den KVV-Fahrplanmonitor (Phase 3).
-- Autor: Rustam T.
--
-- Die Dateien in sql/ sind nummeriert, weil der Postgres-Container sie beim
-- allerersten Start in alphabetischer Reihenfolge ausführt. Läuft der
-- Container schon länger (Volume aus Phase 1 vorhanden), passiert das nicht
-- mehr. Deshalb ist jede Datei so geschrieben, dass sie beliebig oft laufen
-- darf, und laden/lade_postgres.py spielt sie bei Bedarf selbst ein.
--
-- Überblick:
--   dim_stand        ein Eintrag je geladenem Stand
--   dim_haltestelle  SCD2, Körnung Station (E9)
--   dim_linie        SCD2, Körnung route_id
--   dim_datum        Kalender mit Feiertagen und Schulferien BW (02_dim_datum.sql)
--   dim_stunde       0 bis 23 mit Tageszeitband (03_dim_stunde.sql)
--   fakt_abfahrten   Anzahl Abfahrten je Stand, Tag, Stunde, Station, Linie
--   stg_*            Rohdaten des gerade geladenen Stands, bei jedem Lauf geleert

-- ------------------------------------------------------------------ dim_stand

CREATE TABLE IF NOT EXISTS dim_stand (
    stand_sk        serial PRIMARY KEY,
    -- Fachlicher Schlüssel ist der Zeitstempel des Abrufs, nicht der
    -- Inhalts-Hash. Kommt nach A, B ein zweites Mal A, sind das zwei Stände
    -- (dieselbe Überlegung wie E7 in MongoDB).
    stand_id        text        NOT NULL UNIQUE,          -- 2026-11-03T201359Z
    abgerufen_utc   timestamptz NOT NULL UNIQUE,
    inhalts_hash    text        NOT NULL,
    zip_hash        text        NOT NULL,
    groesse_bytes   bigint      NOT NULL,
    feed_version    text,
    feed_von        date,                                 -- Gültigkeit laut feed_info
    feed_bis        date,
    horizont_von    date        NOT NULL,                 -- welche Tage in fakt_abfahrten stehen (E13)
    horizont_bis    date        NOT NULL,
    geladen_am      timestamptz NOT NULL DEFAULT now()
);

-- ------------------------------------------------------------------ SCD2-Dimensionen
--
-- Jede Version einer Haltestelle oder Linie ist eine eigene Zeile.
--   *_sk            Surrogatschlüssel, darauf zeigen die Fakten
--   station_id      fachlicher Schlüssel aus dem Feed
--   attr_hash       md5 über alle fachlichen Attribute, damit der Vergleich
--                   "hat sich etwas geändert" eine einzige Spalte ist
--   gueltig_von     Abrufzeitpunkt des Stands, in dem die Version zuerst da war
--   gueltig_bis     Abrufzeitpunkt des Stands, in dem sie nicht mehr da war,
--                   bei der aktuellen Version 9999-12-31 (nicht NULL)
--   ist_aktuell     doppelt zu gueltig_bis, macht Abfragen aber lesbarer
--   stand_sk_erstmals  in welchem Stand die Version zuerst gesehen wurde
--
-- gueltig_bis ist ausschließlich gemeint: eine Version gilt für Zeitpunkte t
-- mit gueltig_von <= t < gueltig_bis. So grenzen alte und neue Version genau
-- aneinander, ohne sich an der Grenze zu überlappen (E12).

CREATE TABLE IF NOT EXISTS dim_haltestelle (
    haltestelle_sk     serial PRIMARY KEY,
    station_id         text          NOT NULL,
    name               text          NOT NULL,
    lat                numeric(8,5)  NOT NULL,     -- auf 5 Stellen gerundet (E14)
    lon                numeric(8,5)  NOT NULL,
    gemeinde_ags       text,                       -- NULL: liegt in keiner deutschen Gemeinde
    gemeinde           text,
    attr_hash          text          NOT NULL,
    gueltig_von        timestamptz   NOT NULL,
    gueltig_bis        timestamptz   NOT NULL DEFAULT '9999-12-31',
    ist_aktuell        boolean       NOT NULL DEFAULT true,
    stand_sk_erstmals  integer       NOT NULL REFERENCES dim_stand,
    CHECK (gueltig_von < gueltig_bis),
    CHECK (ist_aktuell = (gueltig_bis = '9999-12-31'))
);

-- Die Datenbank selbst verhindert eine zweite aktuelle Version je Station.
-- Die Prüfabfrage in 07_pruefungen.sql bleibt trotzdem, sie prüft dasselbe
-- von außen und funktioniert auch, wenn jemand den Index entfernt.
CREATE UNIQUE INDEX IF NOT EXISTS ux_haltestelle_aktuell
    ON dim_haltestelle (station_id) WHERE ist_aktuell;
CREATE INDEX IF NOT EXISTS ix_haltestelle_zeit
    ON dim_haltestelle (station_id, gueltig_von, gueltig_bis);

CREATE TABLE IF NOT EXISTS dim_linie (
    linie_sk           serial PRIMARY KEY,
    route_id           text          NOT NULL,
    kurzname           text          NOT NULL,
    langname           text          NOT NULL,
    verkehrsmittel     text          NOT NULL,
    betreiber_id       text          NOT NULL,
    betreiber          text          NOT NULL,
    attr_hash          text          NOT NULL,
    gueltig_von        timestamptz   NOT NULL,
    gueltig_bis        timestamptz   NOT NULL DEFAULT '9999-12-31',
    ist_aktuell        boolean       NOT NULL DEFAULT true,
    stand_sk_erstmals  integer       NOT NULL REFERENCES dim_stand,
    CHECK (gueltig_von < gueltig_bis),
    CHECK (ist_aktuell = (gueltig_bis = '9999-12-31'))
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_linie_aktuell
    ON dim_linie (route_id) WHERE ist_aktuell;
CREATE INDEX IF NOT EXISTS ix_linie_zeit
    ON dim_linie (route_id, gueltig_von, gueltig_bis);

-- ------------------------------------------------------------------ dim_datum, dim_stunde
-- Befüllt in 02_dim_datum.sql und 03_dim_stunde.sql.

CREATE TABLE IF NOT EXISTS dim_datum (
    datum            date     PRIMARY KEY,
    jahr             smallint NOT NULL,
    monat            smallint NOT NULL,
    iso_woche        smallint NOT NULL,
    wochentag_nr     smallint NOT NULL,      -- 1 = Montag ... 7 = Sonntag (ISO)
    wochentag        text     NOT NULL,
    ist_feiertag     boolean  NOT NULL,
    feiertag         text,
    -- Werktag, Samstag oder "Sonn- und Feiertag". Ein Feiertag an einem
    -- Werktag fährt im KVV nach Sonntagsplan (Befund C2 aus Phase 2).
    tagestyp         text     NOT NULL,
    -- NULL heißt: Für dieses Datum sind die Ferien noch nicht festgelegt.
    -- Das ist etwas anderes als false.
    ist_schulferien  boolean,
    ferien           text
);

CREATE TABLE IF NOT EXISTS dim_stunde (
    stunde       smallint PRIMARY KEY CHECK (stunde BETWEEN 0 AND 23),
    band         text     NOT NULL,
    band_sort    smallint NOT NULL
);

-- ------------------------------------------------------------------ Fakt

-- Körnung: ein Stand, ein Kalendertag, eine Stunde, eine Station, eine Linie.
-- Gezählt wird die Zahl der Abfahrten nach E9. Begründung der Körnung in E13.
CREATE TABLE IF NOT EXISTS fakt_abfahrten (
    stand_sk        integer  NOT NULL REFERENCES dim_stand,
    datum           date     NOT NULL REFERENCES dim_datum,
    stunde          smallint NOT NULL REFERENCES dim_stunde,
    haltestelle_sk  integer  NOT NULL REFERENCES dim_haltestelle,
    linie_sk        integer  NOT NULL REFERENCES dim_linie,
    anzahl          integer  NOT NULL CHECK (anzahl > 0),
    PRIMARY KEY (stand_sk, datum, stunde, haltestelle_sk, linie_sk)
);

-- Bewusst keine weiteren Indizes. Der Primärschlüssel beginnt mit stand_sk
-- und datum und deckt damit die häufigsten Abfragen ab ("Stand X, Tag Y").
-- Zwei zusätzliche Indizes auf Haltestelle und Linie kosteten bei fünf
-- Ständen zusammen 48 MB, gut 15 Prozent der Tabelle, ohne dass eine meiner
-- Abfragen sie braucht. Power BI importiert die Tabelle ohnehin.

-- ------------------------------------------------------------------ Staging
-- Alles als Text, so wie es im Feed steht. Umgewandelt wird erst in den
-- Sichten unten. UNLOGGED: Der Inhalt ist bei jedem Lauf neu, und ein
-- Absturz kostet nur einen erneuten Lauf. Dafür schreibt Postgres schneller.

CREATE UNLOGGED TABLE IF NOT EXISTS stg_stops (
    stop_id         text NOT NULL,
    stop_name       text NOT NULL,
    stop_lat        text NOT NULL,
    stop_lon        text NOT NULL,
    location_type   text NOT NULL,
    parent_station  text NOT NULL
);

CREATE UNLOGGED TABLE IF NOT EXISTS stg_routes (
    route_id          text NOT NULL,
    agency_id         text NOT NULL,
    route_short_name  text NOT NULL,
    route_long_name   text NOT NULL,
    route_type        text NOT NULL
);

CREATE UNLOGGED TABLE IF NOT EXISTS stg_agency (
    agency_id    text NOT NULL,
    agency_name  text NOT NULL
);

-- Ergebnis der Punkt-in-Polygon-Zuordnung aus Python (GeoPandas). Postgres
-- hat ohne PostGIS keine Geometrie, und für eine einzige Zuordnung je Stand
-- lohnt sich die Erweiterung nicht.
CREATE UNLOGGED TABLE IF NOT EXISTS stg_station_gemeinde (
    station_id  text NOT NULL,
    ags         text NOT NULL,
    gemeinde    text NOT NULL
);

-- Ergebnis der Abfahrten-Logik aus Phase 2, schon je Stunde gezählt.
CREATE UNLOGGED TABLE IF NOT EXISTS stg_abfahrten (
    datum       date     NOT NULL,
    stunde      smallint NOT NULL,
    station_id  text     NOT NULL,
    route_id    text     NOT NULL,
    anzahl      integer  NOT NULL
);

-- ------------------------------------------------------------------ Sichten auf Staging
-- Hier wird aus Rohdaten genau die Zeile, die in die Dimension soll,
-- mitsamt Hash. Die SCD2-Prozeduren lesen nur diese Sichten.

-- Station nach E9: Einträge ohne parent_station. Das sind die Stationen
-- selbst (location_type 1) und Halte, die zu keiner Station gehören.
CREATE OR REPLACE VIEW v_stg_haltestelle AS
SELECT
    s.stop_id                          AS station_id,
    s.stop_name                        AS name,
    round(s.stop_lat::numeric, 5)      AS lat,
    round(s.stop_lon::numeric, 5)      AS lon,
    g.ags                              AS gemeinde_ags,
    g.gemeinde                         AS gemeinde,
    -- concat_ws lässt NULL einfach weg. Dann wären (NULL, 'x') und ('x', NULL)
    -- derselbe Text. Mit coalesce bekommt NULL einen festen Platzhalter.
    md5(concat_ws('|',
        s.stop_name,
        round(s.stop_lat::numeric, 5)::text,
        round(s.stop_lon::numeric, 5)::text,
        coalesce(g.ags, '<null>'),
        coalesce(g.gemeinde, '<null>')
    ))                                 AS attr_hash
FROM stg_stops s
LEFT JOIN stg_station_gemeinde g ON g.station_id = s.stop_id
WHERE s.parent_station = ''
  AND s.location_type IN ('', '0', '1');

CREATE OR REPLACE VIEW v_stg_linie AS
SELECT
    r.route_id,
    r.route_short_name                 AS kurzname,
    r.route_long_name                  AS langname,
    CASE r.route_type
        WHEN '0' THEN 'Straßenbahn/Stadtbahn'
        WHEN '1' THEN 'U-Bahn'
        WHEN '2' THEN 'Zug'
        WHEN '3' THEN 'Bus'
        WHEN '4' THEN 'Fähre'
        ELSE 'route_type ' || r.route_type
    END                                AS verkehrsmittel,
    r.agency_id                        AS betreiber_id,
    coalesce(a.agency_name, '<unbekannt>') AS betreiber,
    md5(concat_ws('|',
        r.route_short_name,
        r.route_long_name,
        r.route_type,
        r.agency_id,
        coalesce(a.agency_name, '<null>')
    ))                                 AS attr_hash
FROM stg_routes r
LEFT JOIN stg_agency a ON a.agency_id = r.agency_id;
