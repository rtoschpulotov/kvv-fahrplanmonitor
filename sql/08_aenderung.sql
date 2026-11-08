-- Änderungen zwischen aufeinanderfolgenden Ständen (Phase 4).
-- Autor: Rustam T.
--
-- Die Erkennung selbst steht in analyse/diff.py. Hier liegt, was dabei
-- herauskommt, und die Prozedur, die aus fachlichen Schlüsseln
-- Surrogatschlüssel macht.
--
--   abruf                  jede Zeile des Registers, auch "unveraendert" und "fehler"
--   dim_standpaar          ein Eintrag je verglichenem Paar (alt, neu)
--   fakt_aenderung         eine Zeile je geänderter Fahrt an einem Tag
--   fakt_aenderung_halt    welche Stationen eine Änderung betrifft
--   fakt_vergleich_linie   je Paar und Linie: wie viele Fahrten, wie viele geändert

-- ------------------------------------------------------------------ Register

CREATE TABLE IF NOT EXISTS abruf (
    abgerufen_utc   timestamptz PRIMARY KEY,
    status          text   NOT NULL,          -- neu | unveraendert | fehler
    inhalts_hash    text,
    zip_hash        text,
    groesse_bytes   bigint,
    fehler          text
);

-- ------------------------------------------------------------------ Standpaar

CREATE TABLE IF NOT EXISTS dim_standpaar (
    standpaar_sk          serial PRIMARY KEY,
    stand_sk_alt          integer NOT NULL REFERENCES dim_stand,
    stand_sk_neu          integer NOT NULL REFERENCES dim_stand,
    -- Vergleichsfenster (E16): Fahrten, die nach fenster_ab beginnen,
    -- an Kalendertagen bis fenster_bis.
    fenster_ab            timestamptz NOT NULL,
    fenster_bis           date        NOT NULL,
    -- Wie lange lag zwischen den beiden Ständen, und gab es dazwischen
    -- fehlgeschlagene Abrufe? Dann ist die Kurzfristigkeit ungenauer.
    stunden_dazwischen    numeric(6,1) NOT NULL,
    fehler_dazwischen     integer      NOT NULL,
    fahrten_alt           integer NOT NULL,      -- Fahrt-Instanzen im Fenster
    fahrten_neu           integer NOT NULL,
    geaendert             integer NOT NULL,      -- davon nicht mehr wie vorher
    anteil_geaendert      numeric(7,5) NOT NULL,
    ist_grosser_wechsel   boolean NOT NULL,      -- E17
    -- Zum Vergleich (E15): Was ein naiver Abgleich über trip_id melden würde.
    -- trip_ids im Fenster, die es nur im alten bzw. nur im neuen Stand gibt.
    trip_id_nur_alt       integer NOT NULL,
    trip_id_nur_neu       integer NOT NULL,
    UNIQUE (stand_sk_alt, stand_sk_neu),
    CHECK (stand_sk_alt < stand_sk_neu)
);

-- ------------------------------------------------------------------ Fakten

CREATE TABLE IF NOT EXISTS fakt_aenderung (
    aenderung_id          bigserial PRIMARY KEY,
    standpaar_sk          integer  NOT NULL REFERENCES dim_standpaar,
    kalendertag           date     NOT NULL REFERENCES dim_datum,
    linie_sk              integer  NOT NULL REFERENCES dim_linie,
    -- Fahrtschlüssel (E15). Richtung, erste Station und Abfahrt dort machen
    -- zusammen mit Linie und Betriebstag eine Fahrt aus. nr unterscheidet
    -- zwei sonst gleiche Fahrten (Verstärker).
    richtung              smallint NOT NULL,
    erste_haltestelle_sk  integer  NOT NULL REFERENCES dim_haltestelle,
    erste_abfahrt_sek     integer  NOT NULL,
    betriebstag           date     NOT NULL,
    nr                    smallint NOT NULL,
    art                   text     NOT NULL CHECK (art IN ('neu', 'entfallen', 'betriebstage', 'halteverlauf', 'zeit')),
    detail                text,
    haltestelle_sk        integer  REFERENCES dim_haltestelle,   -- erste betroffene, nur bei halteverlauf und zeit
    verschiebung_min      integer,                               -- nur bei zeit
    vorlauf_tage          integer  NOT NULL CHECK (vorlauf_tage >= 0),
    trip_id_alt           text,
    trip_id_neu           text,
    UNIQUE (standpaar_sk, linie_sk, richtung, erste_haltestelle_sk, erste_abfahrt_sek, betriebstag, nr)
);

CREATE INDEX IF NOT EXISTS ix_aenderung_paar_art ON fakt_aenderung (standpaar_sk, art);

CREATE TABLE IF NOT EXISTS fakt_aenderung_halt (
    standpaar_sk          integer  NOT NULL REFERENCES dim_standpaar,
    linie_sk              integer  NOT NULL REFERENCES dim_linie,
    richtung              smallint NOT NULL,
    erste_haltestelle_sk  integer  NOT NULL REFERENCES dim_haltestelle,
    erste_abfahrt_sek     integer  NOT NULL,
    art                   text     NOT NULL,
    haltestelle_sk        integer  NOT NULL REFERENCES dim_haltestelle,
    PRIMARY KEY (standpaar_sk, linie_sk, richtung, erste_haltestelle_sk, erste_abfahrt_sek, art, haltestelle_sk)
);

CREATE TABLE IF NOT EXISTS fakt_vergleich_linie (
    standpaar_sk   integer NOT NULL REFERENCES dim_standpaar,
    linie_sk       integer NOT NULL REFERENCES dim_linie,
    fahrten_alt    integer NOT NULL,
    fahrten_neu    integer NOT NULL,
    geaendert      integer NOT NULL,     -- alte Fahrten, die es so nicht mehr gibt
    hinzu          integer NOT NULL,     -- neue Fahrten und zusätzliche Tage
    PRIMARY KEY (standpaar_sk, linie_sk)
);

-- ------------------------------------------------------------------ Staging

CREATE UNLOGGED TABLE IF NOT EXISTS stg_aenderung (
    kalendertag        date     NOT NULL,
    route_id           text     NOT NULL,
    richtung           smallint NOT NULL,
    erste_station      text     NOT NULL,
    erste_abfahrt_sek  integer  NOT NULL,
    betriebstag        date     NOT NULL,
    nr                 smallint NOT NULL,
    art                text     NOT NULL,
    detail             text,
    station            text,
    verschiebung_min   integer,
    trip_id_alt        text,
    trip_id_neu        text
);

CREATE UNLOGGED TABLE IF NOT EXISTS stg_aenderung_halt (
    route_id           text     NOT NULL,
    richtung           smallint NOT NULL,
    erste_station      text     NOT NULL,
    erste_abfahrt_sek  integer  NOT NULL,
    art                text     NOT NULL,
    station            text     NOT NULL
);

CREATE UNLOGGED TABLE IF NOT EXISTS stg_vergleich_linie (
    route_id     text    NOT NULL,
    fahrten_alt  integer NOT NULL,
    fahrten_neu  integer NOT NULL,
    geaendert    integer NOT NULL,
    hinzu        integer NOT NULL
);

-- ------------------------------------------------------------------ Schlüssel auflösen
-- Welche Version gilt? Für Haltestellen und Linien die zum neuen Stand,
-- und wenn es sie dort nicht mehr gibt (eine entfallene Fahrt an einer
-- Haltestelle, die verschwunden ist), die zum alten Stand.

CREATE OR REPLACE FUNCTION haltestelle_zum(p_station text, p_neu timestamptz, p_alt timestamptz)
RETURNS integer LANGUAGE sql STABLE AS $$
    SELECT haltestelle_sk FROM dim_haltestelle
     WHERE station_id = p_station
       AND ((p_neu >= gueltig_von AND p_neu < gueltig_bis) OR (p_alt >= gueltig_von AND p_alt < gueltig_bis))
     ORDER BY gueltig_von DESC
     LIMIT 1
$$;

CREATE OR REPLACE FUNCTION linie_zum(p_route text, p_neu timestamptz, p_alt timestamptz)
RETURNS integer LANGUAGE sql STABLE AS $$
    SELECT linie_sk FROM dim_linie
     WHERE route_id = p_route
       AND ((p_neu >= gueltig_von AND p_neu < gueltig_bis) OR (p_alt >= gueltig_von AND p_alt < gueltig_bis))
     ORDER BY gueltig_von DESC
     LIMIT 1
$$;

CREATE OR REPLACE PROCEDURE lade_aenderung(p_standpaar_sk integer)
LANGUAGE plpgsql AS $$
DECLARE
    v_alt  timestamptz;
    v_neu  timestamptz;
    v_tag  date;
    v_n    bigint;
    v_soll bigint;
BEGIN
    SELECT a.abgerufen_utc, n.abgerufen_utc, (n.abgerufen_utc AT TIME ZONE 'Europe/Berlin')::date
      INTO STRICT v_alt, v_neu, v_tag
      FROM dim_standpaar p
      JOIN dim_stand a ON a.stand_sk = p.stand_sk_alt
      JOIN dim_stand n ON n.stand_sk = p.stand_sk_neu
     WHERE p.standpaar_sk = p_standpaar_sk;

    SELECT count(*) INTO v_soll FROM stg_aenderung;
    INSERT INTO fakt_aenderung (standpaar_sk, kalendertag, linie_sk, richtung, erste_haltestelle_sk,
                                erste_abfahrt_sek, betriebstag, nr, art, detail, haltestelle_sk,
                                verschiebung_min, vorlauf_tage, trip_id_alt, trip_id_neu)
    SELECT p_standpaar_sk, s.kalendertag,
           linie_zum(s.route_id, v_neu, v_alt),
           s.richtung,
           haltestelle_zum(s.erste_station, v_neu, v_alt),
           s.erste_abfahrt_sek, s.betriebstag, s.nr, s.art, s.detail,
           CASE WHEN s.station IS NOT NULL THEN haltestelle_zum(s.station, v_neu, v_alt) END,
           s.verschiebung_min,
           -- Vorlauf: wie viele Tage vor der Fahrt die Änderung zuerst zu sehen war
           s.kalendertag - v_tag,
           s.trip_id_alt, s.trip_id_neu
      FROM stg_aenderung s;
    GET DIAGNOSTICS v_n = ROW_COUNT;
    IF v_n <> v_soll THEN
        RAISE EXCEPTION 'Standpaar %: % Änderungen erwartet, % geladen', p_standpaar_sk, v_soll, v_n;
    END IF;

    INSERT INTO fakt_aenderung_halt
    SELECT DISTINCT p_standpaar_sk,
           linie_zum(h.route_id, v_neu, v_alt), h.richtung,
           haltestelle_zum(h.erste_station, v_neu, v_alt), h.erste_abfahrt_sek, h.art,
           haltestelle_zum(h.station, v_neu, v_alt)
      FROM stg_aenderung_halt h;

    INSERT INTO fakt_vergleich_linie
    SELECT p_standpaar_sk, linie_zum(v.route_id, v_neu, v_alt), v.fahrten_alt, v.fahrten_neu, v.geaendert, v.hinzu
      FROM stg_vergleich_linie v;
END $$;
