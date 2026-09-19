/* ============================================================================
   01_staging.sql - Lumen & Loom analytics
   ----------------------------------------------------------------------------
   Load the four raw CSV exports into staging tables AS-IS.

   Every column is read as VARCHAR on purpose: the raw files are dirty
   (currency strings, blanks, mixed casing, stray whitespace, bad dates), and
   we want the *cleaning* layer (02_clean_transform.sql) to be responsible for
   parsing and validating, not the loader silently coercing/dropping values.

   Engine: written for DuckDB (`read_csv`), which runs the whole pipeline with
   zero database setup. On PostgreSQL the equivalent is:
       CREATE TABLE stg_customers (... all text ...);
       \copy stg_customers FROM 'data/raw/customers.csv' WITH (FORMAT csv, HEADER true);
   ========================================================================== */

CREATE OR REPLACE TABLE stg_customers AS
SELECT * FROM read_csv('data/raw/customers.csv', header = true, all_varchar = true);

CREATE OR REPLACE TABLE stg_products AS
SELECT * FROM read_csv('data/raw/products.csv', header = true, all_varchar = true);

CREATE OR REPLACE TABLE stg_orders AS
SELECT * FROM read_csv('data/raw/orders.csv', header = true, all_varchar = true);

CREATE OR REPLACE TABLE stg_order_items AS
SELECT * FROM read_csv('data/raw/order_items.csv', header = true, all_varchar = true);
