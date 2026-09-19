"""
build_database.py
=================
Run the SQL pipeline (staging -> clean/transform -> analysis views) against a
local DuckDB database file, then print a data-quality report and the headline
KPIs so we can confirm the model built correctly.

Run:  python scripts/build_database.py
"""

from __future__ import annotations

import os
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "lumen_loom.duckdb"
SQL_FILES = ["sql/01_staging.sql", "sql/02_clean_transform.sql", "sql/03_analysis.sql"]

# read_csv paths inside the SQL are relative to the process working directory
os.chdir(ROOT)

if DB_PATH.exists():
    DB_PATH.unlink()

con = duckdb.connect(str(DB_PATH))
for f in SQL_FILES:
    print(f"-- executing {f}")
    con.execute(Path(f).read_text(encoding="utf-8"))

print("\n=== Data-quality report (raw -> clean) ===")
report = con.execute("SELECT * FROM v_cleaning_report").df()
report["removed"] = report["raw_rows"] - report["clean_rows"]
report["pct_removed"] = (100 * report["removed"] / report["raw_rows"]).round(2)
print(report.to_string(index=False))

print("\n=== Headline KPIs ===")
kpis = con.execute("SELECT * FROM v_kpis").df().T
kpis.columns = ["value"]
print(kpis.to_string())

print("\n=== First / last month of revenue ===")
print(con.execute("""
    SELECT MIN(order_month) AS first_month, MAX(order_month) AS last_month,
           COUNT(*) AS months
    FROM v_monthly_revenue
""").df().to_string(index=False))

con.close()
print(f"\nBuilt {DB_PATH}")
