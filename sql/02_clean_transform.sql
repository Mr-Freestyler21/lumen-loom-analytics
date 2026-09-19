/* ============================================================================
   02_clean_transform.sql - Lumen & Loom analytics
   ----------------------------------------------------------------------------
   Turn the messy staging tables into a clean, typed, analysis-ready model:

       dim_customers     one row per customer, standardized & validated
       dim_products      one row per product, valid prices only, margin derived
       fct_orders        one row per order, deduped, typed, status canonicalized
       fct_order_items   one valid line per row, outliers & bad rows removed
       fct_sales         the analytical "one big table" (line grain)
       v_valid_orders    order-grain revenue base (returns/cancellations removed)
       v_cleaning_report raw-vs-clean row counts (data-quality receipt)

   Cleaning decisions are documented inline. Note the DuckDB idioms:
     * TRY_CAST(x AS t)  -> NULL instead of erroring on bad values
       (PostgreSQL: wrap in a CASE/regex validity check, or a helper function).
     * regexp_replace(s, pat, repl, 'g')  -> global replace.
   ========================================================================== */

------------------------------------------------------------------- customers --
-- Fixes: de-duplicate customer_id; standardize channel spelling/casing;
-- normalize US state to a 2-letter code; validate email format; reject
-- impossible ages and future signup dates; coerce opt-in flag to boolean.
CREATE OR REPLACE TABLE dim_customers AS
WITH ranked AS (
    SELECT *,
           ROW_NUMBER() OVER (PARTITION BY customer_id ORDER BY customer_id) AS rn
    FROM stg_customers
),
one_row AS (SELECT * FROM ranked WHERE rn = 1)
SELECT
    TRY_CAST(customer_id AS INTEGER)                                   AS customer_id,
    TRIM(first_name)                                                   AS first_name,
    TRIM(last_name)                                                    AS last_name,
    -- a valid email must have chars around '@' and a dotted domain
    CASE WHEN LOWER(TRIM(email)) LIKE '%_@_%._%'
         THEN LOWER(TRIM(email)) END                                   AS email,
    -- strip any time component, then reject dates after the data window
    CASE WHEN TRY_CAST(SUBSTR(TRIM(signup_date), 1, 10) AS DATE) <= DATE '2025-12-31'
         THEN TRY_CAST(SUBSTR(TRIM(signup_date), 1, 10) AS DATE) END   AS signup_date,
    -- collapse every spelling variant to one canonical channel label
    CASE UPPER(REGEXP_REPLACE(TRIM(acquisition_channel), '[^A-Za-z]', '', 'g'))
        WHEN 'PAIDSEARCH'    THEN 'Paid Search'
        WHEN 'PAIDSOCIAL'    THEN 'Paid Social'
        WHEN 'SOCIAL'        THEN 'Paid Social'
        WHEN 'SOCIALMEDIA'   THEN 'Paid Social'
        WHEN 'ORGANIC'       THEN 'Organic'
        WHEN 'ORGANICSEARCH' THEN 'Organic'
        WHEN 'EMAIL'         THEN 'Email'
        WHEN 'AFFILIATE'     THEN 'Affiliate'
        WHEN 'REFERRAL'      THEN 'Referral'
        WHEN 'REFERAFRIEND'  THEN 'Referral'
        WHEN 'DIRECT'        THEN 'Direct'
        WHEN 'NONE'          THEN 'Direct'
        ELSE 'Unknown'
    END                                                                AS acquisition_channel,
    -- full state names -> code; otherwise keep a valid 2-letter code, else NULL
    CASE UPPER(REPLACE(TRIM(state), '.', ''))
        WHEN 'CALIFORNIA'    THEN 'CA'
        WHEN 'TEXAS'         THEN 'TX'
        WHEN 'NEW YORK'      THEN 'NY'
        WHEN 'FLORIDA'       THEN 'FL'
        WHEN 'WASHINGTON'    THEN 'WA'
        WHEN 'ILLINOIS'      THEN 'IL'
        WHEN 'MASSACHUSETTS' THEN 'MA'
        ELSE CASE WHEN LENGTH(UPPER(REPLACE(TRIM(state), '.', ''))) = 2
                  THEN UPPER(REPLACE(TRIM(state), '.', ''))
                  ELSE NULL END
    END                                                                AS state,
    CASE WHEN TRY_CAST(age AS INTEGER) BETWEEN 13 AND 110
         THEN TRY_CAST(age AS INTEGER) END                             AS age,
    CASE WHEN LOWER(TRIM(is_marketing_opt_in)) IN ('true', '1', 'yes')  THEN TRUE
         WHEN LOWER(TRIM(is_marketing_opt_in)) IN ('false', '0', 'no') THEN FALSE END AS is_marketing_opt_in
FROM one_row
WHERE TRY_CAST(customer_id AS INTEGER) IS NOT NULL;

-------------------------------------------------------------------- products --
-- Fixes: standardize category casing; parse currency strings to numeric;
-- drop products with non-positive price/cost; derive unit margin.
CREATE OR REPLACE TABLE dim_products AS
WITH cleaned AS (
    SELECT
        TRY_CAST(product_id AS INTEGER)                                        AS product_id,
        TRIM(product_name)                                                     AS product_name,
        CASE UPPER(TRIM(category))
            WHEN 'FURNITURE'        THEN 'Furniture'
            WHEN 'LIGHTING'         THEN 'Lighting'
            WHEN 'TEXTILES'         THEN 'Textiles'
            WHEN 'KITCHEN & DINING' THEN 'Kitchen & Dining'
            WHEN 'DECOR'            THEN 'Decor'
            WHEN 'OUTDOOR'          THEN 'Outdoor'
            ELSE 'Other'
        END                                                                    AS category,
        TRIM(subcategory)                                                      AS subcategory,
        TRY_CAST(REPLACE(REPLACE(TRIM(unit_cost),  '$', ''), ',', '') AS DECIMAL(12,2)) AS unit_cost,
        TRY_CAST(REPLACE(REPLACE(TRIM(list_price), '$', ''), ',', '') AS DECIMAL(12,2)) AS list_price
    FROM stg_products
)
SELECT
    product_id, product_name, category, subcategory, unit_cost, list_price,
    ROUND(list_price - unit_cost, 2)                       AS unit_margin,
    ROUND((list_price - unit_cost) / list_price, 4)        AS margin_pct
FROM cleaned
WHERE product_id IS NOT NULL
  AND list_price > 0
  AND unit_cost  > 0;

---------------------------------------------------------------------- orders --
-- Fixes: drop duplicate rows; type dates (strip time); canonicalize status and
-- derive sale/return flags; parse currency/blank discounts (blank -> 0);
-- drop orders whose customer_id doesn't exist (orphan foreign keys).
CREATE OR REPLACE TABLE fct_orders AS
WITH deduped AS (
    SELECT *,
           ROW_NUMBER() OVER (PARTITION BY order_id ORDER BY order_id) AS rn
    FROM stg_orders
),
cleaned AS (
    SELECT
        TRY_CAST(order_id AS INTEGER)                                        AS order_id,
        TRY_CAST(customer_id AS INTEGER)                                     AS customer_id,
        TRY_CAST(SUBSTR(TRIM(order_date), 1, 10) AS DATE)                    AS order_date,
        CASE UPPER(TRIM(order_status))
            WHEN 'COMPLETED'  THEN 'completed'
            WHEN 'COMPLETE'   THEN 'completed'
            WHEN 'DELIVERED'  THEN 'delivered'
            WHEN 'SHIPPED'    THEN 'shipped'
            WHEN 'IN TRANSIT' THEN 'shipped'
            WHEN 'CANCELLED'  THEN 'cancelled'
            WHEN 'CANCELED'   THEN 'cancelled'
            WHEN 'RETURNED'   THEN 'returned'
            WHEN 'REFUNDED'   THEN 'refunded'
            WHEN 'REFUND'     THEN 'refunded'
            ELSE 'other'
        END                                                                  AS order_status,
        COALESCE(TRY_CAST(REPLACE(REPLACE(TRIM(discount_amount), '$', ''), ',', '') AS DECIMAL(12,2)), 0) AS discount_amount,
        COALESCE(TRY_CAST(TRIM(shipping_cost) AS DECIMAL(12,2)), 0)          AS shipping_cost
    FROM deduped
    WHERE rn = 1
)
SELECT
    c.order_id,
    c.customer_id,
    c.order_date,
    DATE_TRUNC('month', c.order_date)                       AS order_month,
    c.order_status,
    c.order_status IN ('completed', 'delivered', 'shipped') AS is_valid_sale,
    c.order_status IN ('returned', 'refunded')              AS is_returned,
    c.discount_amount,
    c.shipping_cost
FROM cleaned c
WHERE c.order_id IS NOT NULL
  AND c.order_date IS NOT NULL
  AND c.customer_id IN (SELECT customer_id FROM dim_customers);

----------------------------------------------------------------- order_items --
-- Fixes: type quantity/price; parse currency strings; drop non-positive or
-- null quantities/prices; drop decimal-shift price outliers (charged price far
-- above list is impossible since promos only *reduce* price); drop items whose
-- product doesn't exist.
CREATE OR REPLACE TABLE fct_order_items AS
WITH cleaned AS (
    SELECT
        TRY_CAST(order_item_id AS INTEGER)                                          AS order_item_id,
        TRY_CAST(order_id AS INTEGER)                                               AS order_id,
        TRY_CAST(product_id AS INTEGER)                                             AS product_id,
        TRY_CAST(quantity AS INTEGER)                                               AS quantity,
        TRY_CAST(REPLACE(REPLACE(TRIM(unit_price), '$', ''), ',', '') AS DECIMAL(12,2)) AS unit_price
    FROM stg_order_items
)
SELECT
    i.order_item_id, i.order_id, i.product_id, i.quantity, i.unit_price
FROM cleaned i
JOIN dim_products p ON p.product_id = i.product_id          -- removes orphan products
WHERE i.quantity BETWEEN 1 AND 50
  AND i.unit_price > 0
  AND i.unit_price <= 3 * p.list_price;                     -- removes 100x outliers

------------------------------------------------------------ fct_sales (OBT) --
-- Denormalized line-grain fact joining items -> orders -> products -> customers,
-- with revenue, cost and margin derived. net_revenue counts only valid sales
-- (returns/refunds/cancellations contribute 0). This is the table analyses read.
CREATE OR REPLACE TABLE fct_sales AS
SELECT
    i.order_item_id,
    i.order_id,
    o.order_date,
    o.order_month,
    o.customer_id,
    c.acquisition_channel,
    c.state,
    i.product_id,
    p.category,
    p.subcategory,
    i.quantity,
    i.unit_price,
    p.list_price,
    p.unit_cost,
    ROUND(i.quantity * i.unit_price, 2)                                   AS gross_revenue,
    ROUND(i.quantity * i.unit_price - i.quantity * p.unit_cost, 2)        AS gross_margin,
    o.order_status,
    o.is_valid_sale,
    o.is_returned,
    CASE WHEN o.is_valid_sale THEN ROUND(i.quantity * i.unit_price, 2) ELSE 0 END AS net_revenue
FROM fct_order_items i
JOIN fct_orders    o ON o.order_id    = i.order_id
JOIN dim_products  p ON p.product_id  = i.product_id
JOIN dim_customers c ON c.customer_id = o.customer_id;

------------------------------------------------------- v_valid_orders (base) --
-- Order-grain revenue base: one row per completed/shipped/delivered order.
-- Every downstream revenue metric (AOV, RFM, cohorts, channel LTV) builds on
-- this single definition of "net revenue" so numbers reconcile across analyses.
CREATE OR REPLACE VIEW v_valid_orders AS
SELECT
    order_id,
    ANY_VALUE(customer_id)          AS customer_id,
    ANY_VALUE(order_date)           AS order_date,
    ANY_VALUE(order_month)          AS order_month,
    ANY_VALUE(acquisition_channel)  AS channel,
    ANY_VALUE(state)                AS state,
    SUM(net_revenue)                AS order_revenue,
    SUM(gross_margin)               AS order_margin,
    SUM(quantity)                   AS units
FROM fct_sales
WHERE is_valid_sale
GROUP BY order_id;

------------------------------------------------------- v_cleaning_report ------
-- A quick "receipt" of how much each table shrank during cleaning.
CREATE OR REPLACE VIEW v_cleaning_report AS
             SELECT 'customers'   AS table_name, (SELECT COUNT(*) FROM stg_customers)   AS raw_rows, (SELECT COUNT(*) FROM dim_customers)   AS clean_rows
   UNION ALL SELECT 'products',                  (SELECT COUNT(*) FROM stg_products),                (SELECT COUNT(*) FROM dim_products)
   UNION ALL SELECT 'orders',                    (SELECT COUNT(*) FROM stg_orders),                  (SELECT COUNT(*) FROM fct_orders)
   UNION ALL SELECT 'order_items',               (SELECT COUNT(*) FROM stg_order_items),             (SELECT COUNT(*) FROM fct_order_items);
