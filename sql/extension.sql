-- Section 9, R2: materialize the complete unfiltered Q4 financial question.
-- This is derived reporting data, created after the full ETL by extend_z1.py.

-- name: create_financial_report
CREATE MATERIALIZED VIEW "z1".financial_report AS
SELECT t.currency, t.search_value AS merchant_search_value,
       count(*) AS transaction_records,
       count(*) FILTER (WHERE t.amount_state = 'valid') AS valid_amount_records,
       count(*) FILTER (WHERE t.amount_state = 'missing') AS missing_amount_records,
       count(*) FILTER (WHERE t.amount_state = 'invalid') AS invalid_amount_records,
       count(*) FILTER (WHERE t.amount_state = 'valid' AND t.amount < 0) AS negative_amount_records,
       count(*) FILTER (WHERE t.amount_state = 'valid' AND t.amount = 0) AS zero_amount_records,
       count(*) FILTER (WHERE t.amount_state = 'valid' AND t.amount > 0) AS positive_amount_records,
       sum(t.amount) FILTER (WHERE t.amount_state = 'valid' AND t.currency IS NOT NULL) AS amount_sum
FROM "z1".financial_transactions t
GROUP BY t.currency, t.search_value
WITH NO DATA;

-- name: refresh_financial_report
REFRESH MATERIALIZED VIEW "z1".financial_report;

-- name: read_financial_report
-- Materialized storage has no guaranteed ordering; sort on each read.
SELECT currency, merchant_search_value, transaction_records,
       valid_amount_records, missing_amount_records, invalid_amount_records,
       negative_amount_records, zero_amount_records, positive_amount_records, amount_sum
FROM "z1".financial_report
ORDER BY currency NULLS FIRST, merchant_search_value NULLS FIRST;
