/* ============================================================================
   03_analysis.sql - Lumen & Loom analytics
   ----------------------------------------------------------------------------
   Analytical views that answer the business questions. Each view is consumed
   directly by the Python EDA layer (python/eda.py). Everything reconciles to
   one revenue definition: net_revenue = valid-sale line revenue (returns and
   cancellations excluded).
   ========================================================================== */

------------------------------------------------------------------ headline KPIs
CREATE OR REPLACE VIEW v_kpis AS
SELECT
    (SELECT ROUND(SUM(net_revenue), 2) FROM fct_sales)                            AS total_net_revenue,
    (SELECT COUNT(*)              FROM v_valid_orders)                            AS valid_orders,
    (SELECT COUNT(DISTINCT customer_id) FROM v_valid_orders)                      AS active_customers,
    (SELECT ROUND(AVG(order_revenue), 2) FROM v_valid_orders)                     AS avg_order_value,
    (SELECT ROUND(100.0 * SUM(gross_margin) / NULLIF(SUM(net_revenue), 0), 1)
       FROM fct_sales WHERE is_valid_sale)                                        AS gross_margin_pct,
    -- share of customers with more than one valid order
    (SELECT ROUND(100.0 * COUNT(*) FILTER (WHERE n > 1) / COUNT(*), 1)
       FROM (SELECT customer_id, COUNT(*) n FROM v_valid_orders GROUP BY customer_id)) AS repeat_rate_pct,
    -- returned orders as a share of all orders that were not cancelled
    (SELECT ROUND(100.0 * COUNT(*) FILTER (WHERE is_returned)
                  / NULLIF(COUNT(*) FILTER (WHERE is_valid_sale OR is_returned), 0), 1)
       FROM fct_orders)                                                           AS return_rate_pct;

--------------------------------------------------------- monthly revenue trend
-- Net revenue, order volume, AOV and margin by calendar month.
CREATE OR REPLACE VIEW v_monthly_revenue AS
SELECT
    order_month,
    ROUND(SUM(order_revenue), 2)                       AS net_revenue,
    COUNT(*)                                           AS orders,
    ROUND(AVG(order_revenue), 2)                       AS avg_order_value,
    ROUND(SUM(order_margin), 2)                        AS gross_margin
FROM v_valid_orders
GROUP BY order_month
ORDER BY order_month;

------------------------------------------------------- revenue by category/month
CREATE OR REPLACE VIEW v_category_month AS
SELECT
    order_month,
    category,
    ROUND(SUM(net_revenue), 2) AS net_revenue
FROM fct_sales
WHERE is_valid_sale
GROUP BY order_month, category
ORDER BY order_month, category;

--------------------------------------------------- category seasonality profile
-- Each category's share of its own annual revenue that lands in each calendar
-- month (averaged across years) -> a clean seasonality fingerprint for a heatmap.
CREATE OR REPLACE VIEW v_category_seasonality AS
WITH by_month AS (
    SELECT category,
           EXTRACT(month FROM order_date) AS month_no,
           SUM(net_revenue)               AS rev
    FROM fct_sales
    WHERE is_valid_sale
    GROUP BY category, EXTRACT(month FROM order_date)
)
SELECT
    category,
    month_no,
    ROUND(100.0 * rev / SUM(rev) OVER (PARTITION BY category), 2) AS pct_of_annual
FROM by_month
ORDER BY category, month_no;

------------------------------------------------------------ RFM segmentation
-- Recency / Frequency / Monetary scored into quintiles (5 = best) and mapped
-- to actionable segments.
CREATE OR REPLACE VIEW v_rfm AS
WITH per_customer AS (
    SELECT
        customer_id,
        MAX(order_date)  AS last_order,
        COUNT(*)         AS frequency,
        SUM(order_revenue) AS monetary
    FROM v_valid_orders
    GROUP BY customer_id
),
snap AS (SELECT MAX(order_date) AS snapshot FROM v_valid_orders),
scored AS (
    SELECT
        pc.*,
        DATE_DIFF('day', pc.last_order, (SELECT snapshot FROM snap))              AS recency_days,
        -- customer_id breaks NTILE ties so quintiles are reproducible run-to-run
        NTILE(5) OVER (ORDER BY DATE_DIFF('day', pc.last_order, (SELECT snapshot FROM snap)) DESC, pc.customer_id) AS r_score,
        NTILE(5) OVER (ORDER BY pc.frequency, pc.customer_id)                      AS f_score,
        NTILE(5) OVER (ORDER BY pc.monetary,  pc.customer_id)                      AS m_score
    FROM per_customer pc
)
SELECT
    *,
    CASE
        WHEN r_score >= 4 AND f_score >= 4 THEN 'Champions'
        WHEN r_score >= 3 AND f_score >= 3 THEN 'Loyal'
        WHEN r_score >= 4 AND f_score <= 2 THEN 'New / Promising'
        WHEN r_score <= 2 AND f_score >= 4 THEN 'At Risk'
        WHEN r_score <= 2 AND f_score <= 2 THEN 'Hibernating'
        ELSE 'Needs Attention'
    END AS segment
FROM scored;

-- Segment roll-up (size + revenue contribution) for charting.
CREATE OR REPLACE VIEW v_rfm_segments AS
SELECT
    segment,
    COUNT(*)                       AS customers,
    ROUND(SUM(monetary), 2)        AS revenue,
    ROUND(AVG(monetary), 2)        AS avg_ltv,
    ROUND(AVG(frequency), 2)       AS avg_orders
FROM v_rfm
GROUP BY segment
ORDER BY revenue DESC;

------------------------------------------------------------ cohort retention
-- Monthly acquisition cohorts and the % of each cohort placing an order N
-- months later.
CREATE OR REPLACE VIEW v_cohort_retention AS
WITH firsts AS (
    SELECT customer_id, DATE_TRUNC('month', MIN(order_date)) AS cohort_month
    FROM v_valid_orders
    GROUP BY customer_id
),
activity AS (
    SELECT DISTINCT
        f.cohort_month,
        DATE_DIFF('month', f.cohort_month, o.order_month) AS month_offset,
        o.customer_id
    FROM firsts f
    JOIN v_valid_orders o ON o.customer_id = f.customer_id
),
sizes AS (SELECT cohort_month, COUNT(*) AS cohort_size FROM firsts GROUP BY cohort_month)
SELECT
    a.cohort_month,
    a.month_offset,
    s.cohort_size,
    COUNT(DISTINCT a.customer_id)                                    AS active_customers,
    ROUND(COUNT(DISTINCT a.customer_id) * 1.0 / s.cohort_size, 4)    AS retention
FROM activity a
JOIN sizes s USING (cohort_month)
GROUP BY a.cohort_month, a.month_offset, s.cohort_size
ORDER BY a.cohort_month, a.month_offset;

----------------------------------------------------- marketing-channel value
-- Customers acquired, total & average lifetime revenue, avg orders and repeat
-- rate by acquisition channel. Shows which channels buy loyalty vs volume.
CREATE OR REPLACE VIEW v_channel_performance AS
WITH per_customer AS (
    SELECT
        c.customer_id,
        c.acquisition_channel,
        COUNT(o.order_id)          AS orders,
        COALESCE(SUM(o.order_revenue), 0) AS ltv
    FROM dim_customers c
    LEFT JOIN v_valid_orders o ON o.customer_id = c.customer_id
    GROUP BY c.customer_id, c.acquisition_channel
)
SELECT
    acquisition_channel                                   AS channel,
    COUNT(*)                                              AS customers,
    ROUND(SUM(ltv), 2)                                    AS total_revenue,
    ROUND(AVG(ltv), 2)                                    AS avg_ltv,
    ROUND(AVG(orders), 2)                                 AS avg_orders,
    ROUND(100.0 * COUNT(*) FILTER (WHERE orders > 1) / COUNT(*), 1) AS repeat_rate_pct
FROM per_customer
WHERE acquisition_channel <> 'Unknown'
GROUP BY channel
ORDER BY avg_ltv DESC;

----------------------------------------------------------- geography (states)
CREATE OR REPLACE VIEW v_state_revenue AS
SELECT
    state,
    ROUND(SUM(net_revenue), 2)      AS net_revenue,
    COUNT(DISTINCT order_id)        AS orders
FROM fct_sales
WHERE is_valid_sale AND state IS NOT NULL
GROUP BY state
ORDER BY net_revenue DESC;

------------------------------------------------------------- top products
CREATE OR REPLACE VIEW v_top_products AS
SELECT
    p.product_id,
    p.product_name,
    p.category,
    ROUND(SUM(s.net_revenue), 2) AS net_revenue,
    SUM(s.quantity)              AS units
FROM fct_sales s
JOIN dim_products p USING (product_id)
WHERE s.is_valid_sale
GROUP BY p.product_id, p.product_name, p.category
ORDER BY net_revenue DESC;

-------------------------------------------------- category performance summary
CREATE OR REPLACE VIEW v_category_performance AS
SELECT
    category,
    ROUND(SUM(net_revenue), 2)                                   AS net_revenue,
    SUM(quantity)                                                AS units,
    ROUND(100.0 * SUM(gross_margin) / NULLIF(SUM(net_revenue),0), 1) AS margin_pct,
    ROUND(SUM(net_revenue) / COUNT(DISTINCT order_id), 2)        AS revenue_per_order
FROM fct_sales
WHERE is_valid_sale
GROUP BY category
ORDER BY net_revenue DESC;
