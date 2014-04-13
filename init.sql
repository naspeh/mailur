DROP MATERIALIZED VIEW IF EXISTS search_index;

CREATE MATERIALIZED VIEW search_index AS
SELECT id, gm_thrid,
    setweight(to_tsvector(subject), 'A') ||
    setweight(to_tsvector(text), 'C') ||
    setweight(to_tsvector(coalesce(array_to_string("from", ','), '')), 'C') ||
    setweight(to_tsvector(coalesce(array_to_string("to", ','), '')), 'C') ||
    setweight(to_tsvector(coalesce(array_to_string("cc", ','), '')), 'C') ||
    setweight(to_tsvector(coalesce(array_to_string("bcc", ','), '')), 'C')
    as document
FROM emails;

CREATE INDEX idx_fts_search ON search_index USING gin(document);
