-- Database indexing example for PostgreSQL.
--
-- The script creates a session-scoped temporary table, compares the same query
-- before and after a composite covering index, reports storage, and removes the
-- temporary table. Run it in a fresh psql session with autocommit enabled.

CREATE TEMPORARY TABLE database_indexing_orders (
    order_id BIGINT PRIMARY KEY,
    customer_id BIGINT NOT NULL,
    status TEXT NOT NULL,
    total_amount NUMERIC(12, 2) NOT NULL,
    ordered_at TIMESTAMP NOT NULL
);

INSERT INTO database_indexing_orders (
    order_id,
    customer_id,
    status,
    total_amount,
    ordered_at
)
SELECT
    generated_order_id,
    (generated_order_id % 1000) + 1,
    CASE generated_order_id % 3
        WHEN 0 THEN 'PAID'
        WHEN 1 THEN 'PENDING'
        ELSE 'CANCELLED'
    END,
    (10 + ((generated_order_id % 5000) / 100.0))::NUMERIC(12, 2),
    TIMESTAMP '2026-01-01 00:00:00'
        + (generated_order_id * INTERVAL '1 minute')
FROM GENERATE_SERIES(1, 100000) AS generated(generated_order_id);

ANALYZE database_indexing_orders;

-- Baseline: expect a sequential scan because no useful customer/time index exists.
EXPLAIN (ANALYZE, BUFFERS)
SELECT
    ordered_at,
    status,
    total_amount
FROM database_indexing_orders
WHERE customer_id = 501
  AND ordered_at >= TIMESTAMP '2026-03-01 00:00:00'
ORDER BY ordered_at DESC
LIMIT 3;

CREATE INDEX database_indexing_orders_customer_time_idx
ON database_indexing_orders (
    customer_id,
    ordered_at DESC
)
INCLUDE (
    status,
    total_amount
);

ANALYZE database_indexing_orders;

-- Comparison: look for an index scan or index-only scan and fewer buffers.
EXPLAIN (ANALYZE, BUFFERS)
SELECT
    ordered_at,
    status,
    total_amount
FROM database_indexing_orders
WHERE customer_id = 501
  AND ordered_at >= TIMESTAMP '2026-03-01 00:00:00'
ORDER BY ordered_at DESC
LIMIT 3;

SELECT
    ordered_at,
    status,
    total_amount
FROM database_indexing_orders
WHERE customer_id = 501
  AND ordered_at >= TIMESTAMP '2026-03-01 00:00:00'
ORDER BY ordered_at DESC
LIMIT 3;

SELECT
    PG_SIZE_PRETTY(
        PG_RELATION_SIZE('database_indexing_orders')
    ) AS table_size,
    PG_SIZE_PRETTY(
        PG_RELATION_SIZE('database_indexing_orders_customer_time_idx')
    ) AS candidate_index_size;

DROP TABLE database_indexing_orders;
