-- Kalender mit gesetzlichen Feiertagen und Schulferien in Baden-Württemberg.
-- Autor: Rustam T.
--
-- Zeitraum 2026-01-01 bis 2029-12-31. Mein Archiv beginnt im November 2026,
-- der erste Fahrplan darin gilt ab 14.06.2026. Für spätere Jahre die
-- Ferientabelle ergänzen und das Ende von generate_series anheben.
--
-- Quellen (geprüft am 08.11.2026):
-- Feiertage: Ministerium des Inneren, für Digitalisierung und Kommunen BW,
--   https://im.baden-wuerttemberg.de/de/service/feiertage
--   Gesetzlich sind elf Tage. Reformationstag (31.10.) und Gründonnerstag
--   sind dort nur kirchliche Feiertage und schulfrei, keine gesetzlichen.
-- Schulferien: Ministerium für Kultus, Jugend und Sport BW,
--   https://km.baden-wuerttemberg.de/de/service/ferien
--   und für das Schuljahr 2025/26 die Ferientabelle der KMK,
--   https://www.kmk.org/service/ferienregelung/ferienkalender.html
-- Lizenz: Ferien- und Feiertagstermine sind amtlich festgelegte Daten. Es
-- gibt dazu keine Lizenzangabe. Ich übernehme nur die Termine selbst, keine
-- Texte, und nenne die Quellen.
--
-- Bewegliche Ferientage lasse ich weg. Die legt jede Schule selbst fest, sie
-- gelten also nicht im ganzen Land.

-- ------------------------------------------------------------------ Ostersonntag
-- Ostern bestimmt Karfreitag, Ostermontag, Himmelfahrt, Pfingstmontag und
-- Fronleichnam. Die Formel ist der bekannte Algorithmus für den
-- gregorianischen Kalender (Meeus/Jones/Butcher). Geprüft gegen die
-- tatsächlichen Termine: 05.04.2026, 28.03.2027, 16.04.2028, 01.04.2029.

CREATE OR REPLACE FUNCTION ostersonntag(jahr integer) RETURNS date
LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE
    a int := jahr % 19;
    b int := jahr / 100;
    c int := jahr % 100;
    d int := b / 4;
    e int := b % 4;
    f int := (b + 8) / 25;
    g int := (b - f + 1) / 3;
    h int := (19 * a + b - d - g + 15) % 30;
    i int := c / 4;
    k int := c % 4;
    l int := (32 + 2 * e + 2 * i - h - k) % 7;
    m int := (a + 11 * h + 22 * l) / 451;
    monat int := (h + l - 7 * m + 114) / 31;
    tag int := ((h + l - 7 * m + 114) % 31) + 1;
BEGIN
    RETURN make_date(jahr, monat, tag);
END $$;

-- ------------------------------------------------------------------ Feiertage BW

CREATE OR REPLACE FUNCTION feiertage_bw(jahr integer)
RETURNS TABLE (datum date, name text)
LANGUAGE sql IMMUTABLE AS $$
    SELECT * FROM (VALUES
        (make_date(jahr, 1, 1),            'Neujahr'),
        (make_date(jahr, 1, 6),            'Heilige Drei Könige'),
        (ostersonntag(jahr) - 2,           'Karfreitag'),
        (ostersonntag(jahr) + 1,           'Ostermontag'),
        (make_date(jahr, 5, 1),            'Tag der Arbeit'),
        (ostersonntag(jahr) + 39,          'Christi Himmelfahrt'),
        (ostersonntag(jahr) + 50,          'Pfingstmontag'),
        (ostersonntag(jahr) + 60,          'Fronleichnam'),
        (make_date(jahr, 10, 3),           'Tag der Deutschen Einheit'),
        (make_date(jahr, 11, 1),           'Allerheiligen'),
        (make_date(jahr, 12, 25),          '1. Weihnachtstag'),
        (make_date(jahr, 12, 26),          '2. Weihnachtstag')
    ) AS t(datum, name)
$$;

-- ------------------------------------------------------------------ Schulferien BW
-- Eine Zeile je Ferienabschnitt, erster und letzter Ferientag einschließlich.

CREATE TABLE IF NOT EXISTS ref_schulferien (
    von    date NOT NULL,
    bis    date NOT NULL,
    name   text NOT NULL,
    PRIMARY KEY (von),
    CHECK (von <= bis)
);

INSERT INTO ref_schulferien (von, bis, name) VALUES
    -- Schuljahr 2025/26 (KMK)
    ('2025-12-22', '2026-01-05', 'Weihnachtsferien'),
    ('2026-03-30', '2026-04-11', 'Osterferien'),
    ('2026-05-26', '2026-06-05', 'Pfingstferien'),
    -- Schuljahr 2026/27 (Kultusministerium BW, deckungsgleich mit KMK)
    ('2026-07-30', '2026-09-12', 'Sommerferien'),
    ('2026-10-26', '2026-10-30', 'Herbstferien'),
    ('2026-12-23', '2027-01-09', 'Weihnachtsferien'),
    ('2027-03-30', '2027-04-03', 'Osterferien'),
    ('2027-05-18', '2027-05-29', 'Pfingstferien'),
    -- Schuljahr 2027/28
    ('2027-07-29', '2027-09-11', 'Sommerferien'),
    ('2027-11-02', '2027-11-06', 'Herbstferien'),
    ('2027-12-23', '2028-01-08', 'Weihnachtsferien'),
    ('2028-04-18', '2028-04-22', 'Osterferien'),
    ('2028-06-06', '2028-06-17', 'Pfingstferien'),
    -- Schuljahr 2028/29
    ('2028-07-27', '2028-09-09', 'Sommerferien'),
    ('2028-10-30', '2028-11-03', 'Herbstferien'),
    ('2028-12-23', '2029-01-05', 'Weihnachtsferien'),
    ('2029-03-26', '2029-04-07', 'Osterferien'),
    ('2029-05-22', '2029-06-01', 'Pfingstferien'),
    -- Schuljahr 2029/30
    ('2029-07-26', '2029-09-08', 'Sommerferien'),
    ('2029-10-29', '2029-11-02', 'Herbstferien'),
    ('2029-12-22', '2030-01-05', 'Weihnachtsferien')
ON CONFLICT (von) DO UPDATE SET bis = EXCLUDED.bis, name = EXCLUDED.name
    WHERE (ref_schulferien.bis, ref_schulferien.name) IS DISTINCT FROM (EXCLUDED.bis, EXCLUDED.name);

-- ------------------------------------------------------------------ dim_datum befüllen
-- Läuft die Datei ein zweites Mal, ändert sie nur Tage, deren Inhalt sich
-- wirklich unterscheidet (etwa nach einer Korrektur der Ferientabelle).
-- Unveränderte Zeilen fasst sie nicht an.

INSERT INTO dim_datum
SELECT
    t.datum,
    extract(year FROM t.datum)::smallint,
    extract(month FROM t.datum)::smallint,
    extract(week FROM t.datum)::smallint,
    extract(isodow FROM t.datum)::smallint,
    (ARRAY['Montag','Dienstag','Mittwoch','Donnerstag','Freitag','Samstag','Sonntag'])
        [extract(isodow FROM t.datum)],
    f.name IS NOT NULL,
    f.name,
    CASE
        WHEN f.name IS NOT NULL OR extract(isodow FROM t.datum) = 7 THEN 'Sonn- und Feiertag'
        WHEN extract(isodow FROM t.datum) = 6 THEN 'Samstag'
        ELSE 'Werktag'
    END,
    -- Nach dem letzten bekannten Ferientag weiß ich nichts, also NULL.
    CASE WHEN t.datum > (SELECT max(bis) FROM ref_schulferien) THEN NULL
         ELSE s.name IS NOT NULL END,
    s.name
FROM generate_series('2026-01-01'::date, '2029-12-31'::date, interval '1 day') AS g(tag)
CROSS JOIN LATERAL (SELECT g.tag::date AS datum) t
LEFT JOIN LATERAL (
    SELECT name FROM feiertage_bw(extract(year FROM t.datum)::int) fb WHERE fb.datum = t.datum
) f ON true
LEFT JOIN ref_schulferien s ON t.datum BETWEEN s.von AND s.bis
ON CONFLICT (datum) DO UPDATE SET
    jahr = EXCLUDED.jahr, monat = EXCLUDED.monat, iso_woche = EXCLUDED.iso_woche,
    wochentag_nr = EXCLUDED.wochentag_nr, wochentag = EXCLUDED.wochentag,
    ist_feiertag = EXCLUDED.ist_feiertag, feiertag = EXCLUDED.feiertag,
    tagestyp = EXCLUDED.tagestyp, ist_schulferien = EXCLUDED.ist_schulferien,
    ferien = EXCLUDED.ferien
WHERE (dim_datum.*) IS DISTINCT FROM (EXCLUDED.*);
