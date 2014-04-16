DROP MATERIALIZED VIEW IF EXISTS emails_search;

CREATE MATERIALIZED VIEW emails_search AS
SELECT id, gm_thrid,
    setweight(to_tsvector('simple', subject), 'A') ||
    setweight(to_tsvector('simple', text), 'C') ||
    setweight(to_tsvector(coalesce(array_to_string("from", ','), '')), 'C') ||
    setweight(to_tsvector(coalesce(array_to_string("to", ','), '')), 'C') ||
    setweight(to_tsvector(coalesce(array_to_string("cc", ','), '')), 'C') ||
    setweight(to_tsvector(coalesce(array_to_string("bcc", ','), '')), 'C')
    as document
FROM emails;

CREATE INDEX ix_emails_search ON emails_search USING gin(document);
