"""
generate_data.py
================
Synthetic-data generator for the Lumen & Loom analytics case study.

Lumen & Loom is a (fictional) direct-to-consumer online retailer of home &
lifestyle products. This script simulates ~3 years of operational data
(2023-01-01 .. 2025-12-31) with realistic structure and then deliberately
dirties it, so the SQL layer has genuine cleaning work to do.

Baked-in, explainable trends
----------------------------
* Compound YoY growth (a scaling, growing business).
* Calendar seasonality: Q4 holiday surge, January dip, Black Friday /
  Cyber Monday spikes, a July summer sale.
* Category seasonality: Outdoor peaks in spring/summer; Decor & Lighting
  peak in Q4; Textiles skew to the cozy months.
* Channel-driven loyalty: Email / Referral customers repeat more and are
  worth more; paid channels acquire volume but retain worse.
* Realistic returns (Furniture returns more than Decor).

Deliberate "dirtiness" (for the SQL to clean)
---------------------------------------------
* Duplicate order rows.
* Inconsistent categoricals ("Paid Search" / "paid search" / "PAID_SEARCH").
* Currency strings ("$1,299.00"), stray whitespace, empty strings / NULLs.
* Negative/zero quantities & prices, price outliers (decimal-shift errors).
* Impossible ages, future signup dates.
* Orphan foreign keys (order -> missing customer, item -> missing product).

Output: four CSVs in ``data/raw/``. Deterministic (seeded).

Run:  python scripts/generate_data.py
"""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pandas as pd

# --------------------------------------------------------------------------- #
# Config
# --------------------------------------------------------------------------- #
SEED = 42
N_CUSTOMERS = 16_000
START = pd.Timestamp("2023-01-01")
END = pd.Timestamp("2025-12-31")

RAW_DIR = Path(__file__).resolve().parents[1] / "data" / "raw"

rng = np.random.default_rng(SEED)

# --------------------------------------------------------------------------- #
# Reference data
# --------------------------------------------------------------------------- #

# Canonical acquisition channels + relative acquisition volume + a "loyalty"
# multiplier that drives repeat-purchase propensity and lifetime value.
CHANNELS = {
    #                 acq_weight   loyalty_mult
    "Paid Search":   (0.26,        0.85),
    "Paid Social":   (0.24,        0.80),
    "Organic":       (0.16,        1.10),
    "Email":         (0.10,        1.70),
    "Affiliate":     (0.09,        0.90),
    "Referral":      (0.08,        1.60),
    "Direct":        (0.07,        1.30),
}

# Product taxonomy: category -> (subcategories, list-price low, list-price high).
# Prices are right-skewed within the range (see below), so category averages sit
# well below the midpoint, as real catalogs do (many cheap SKUs, few premium).
CATEGORIES = {
    "Furniture":       (["Sofas", "Chairs", "Tables", "Beds", "Storage"],       120, 1200),
    "Lighting":        (["Table Lamps", "Pendants", "Sconces", "Floor Lamps"],   20,  260),
    "Textiles":        (["Rugs", "Curtains", "Throws", "Bedding", "Cushions"],   15,  220),
    "Kitchen & Dining":(["Cookware", "Dinnerware", "Glassware", "Utensils"],     10,  160),
    "Decor":           (["Vases", "Wall Art", "Candles", "Mirrors", "Planters"],  8,  120),
    "Outdoor":         (["Patio Sets", "Planters", "Grills", "String Lights"],   20,  500),
}
CATEGORY_NAMES = list(CATEGORIES.keys())
N_CAT = len(CATEGORY_NAMES)

# How often each category is bought (independent of price). Cheap, everyday
# categories (Decor, Kitchen) sell in far higher volume than Furniture, which is
# what keeps average order value realistic.
CAT_BASE_WEIGHT = {
    "Furniture": 0.07, "Lighting": 0.15, "Textiles": 0.17,
    "Kitchen & Dining": 0.23, "Decor": 0.26, "Outdoor": 0.12,
}

# Category seasonality: multiplier on selection probability by month (Jan..Dec).
CAT_SEASON = {
    "Furniture":        [0.9, 0.9, 1.05, 1.15, 1.2, 1.1, 1.0, 1.0, 1.05, 1.05, 1.15, 1.1],
    "Lighting":         [0.9, 0.85, 0.9, 0.95, 0.95, 0.9, 0.9, 0.95, 1.0, 1.15, 1.5, 1.6],
    "Textiles":         [1.2, 1.1, 1.0, 0.9, 0.8, 0.75, 0.75, 0.85, 1.0, 1.2, 1.3, 1.35],
    "Kitchen & Dining": [0.95, 0.9, 0.95, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.05, 1.35, 1.45],
    "Decor":            [0.9, 0.95, 1.0, 1.0, 1.0, 0.95, 0.9, 0.9, 1.05, 1.3, 1.7, 1.85],
    "Outdoor":          [0.4, 0.45, 0.75, 1.3, 1.7, 1.85, 1.8, 1.5, 1.05, 0.7, 0.45, 0.4],
}

# Base return rate by category (Furniture is returned far more than Decor).
RETURN_RATE = {
    "Furniture": 0.16, "Lighting": 0.09, "Textiles": 0.10,
    "Kitchen & Dining": 0.07, "Decor": 0.05, "Outdoor": 0.11,
}

# Monthly demand multiplier (the overall calendar shape).
MONTH_SEASON = np.array(
    [0.75, 0.85, 0.95, 1.00, 1.05, 1.05, 1.10, 1.00, 1.00, 1.10, 1.45, 1.55]
)
# Weekday multiplier (online retail skews slightly to early week). Mon=0..Sun=6
WEEKDAY_FACTOR = np.array([1.10, 1.10, 1.05, 1.00, 0.95, 0.90, 0.95])
# Daily compound growth (~2.3x demand from start to end of the window).
GROWTH_DAILY = 1.00075

# US states with approximate population weights (millions).
STATE_POP = {
    "CA": 39.5, "TX": 29.1, "FL": 21.5, "NY": 20.2, "PA": 13.0, "IL": 12.8,
    "OH": 11.8, "GA": 10.7, "NC": 10.4, "MI": 10.0, "NJ": 9.3, "VA": 8.6,
    "WA": 7.7, "AZ": 7.2, "MA": 7.0, "TN": 6.9, "IN": 6.8, "MO": 6.2,
    "MD": 6.2, "WI": 5.9, "CO": 5.8, "MN": 5.7, "SC": 5.1, "AL": 5.0,
    "LA": 4.7, "KY": 4.5, "OR": 4.2, "OK": 4.0, "CT": 3.6, "UT": 3.3,
    "IA": 3.2, "NV": 3.1, "AR": 3.0, "MS": 2.9, "KS": 2.9, "NM": 2.1,
    "NE": 2.0, "ID": 1.8, "WV": 1.8, "HI": 1.5, "NH": 1.4, "ME": 1.4,
    "MT": 1.1, "RI": 1.1, "DE": 1.0, "SD": 0.9, "ND": 0.8, "AK": 0.7,
    "DC": 0.7, "VT": 0.6, "WY": 0.6,
}
STATE_FULL = {
    "CA": "California", "TX": "Texas", "NY": "New York", "FL": "Florida",
    "WA": "Washington", "IL": "Illinois", "MA": "Massachusetts",
}

FIRST_NAMES = [
    "James", "Mary", "Robert", "Patricia", "John", "Jennifer", "Michael",
    "Linda", "David", "Elizabeth", "William", "Barbara", "Richard", "Susan",
    "Joseph", "Jessica", "Thomas", "Sarah", "Charles", "Karen", "Chris",
    "Nancy", "Daniel", "Lisa", "Matthew", "Betty", "Anthony", "Sandra",
    "Mark", "Ashley", "Donald", "Kimberly", "Steven", "Emily", "Paul",
    "Donna", "Andrew", "Michelle", "Josh", "Carol", "Kevin", "Amanda",
    "Brian", "Melissa", "George", "Deborah", "Ethan", "Sofia", "Noah", "Maya",
]
LAST_NAMES = [
    "Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller",
    "Davis", "Rodriguez", "Martinez", "Hernandez", "Lopez", "Gonzalez",
    "Wilson", "Anderson", "Thomas", "Taylor", "Moore", "Jackson", "Martin",
    "Lee", "Perez", "Thompson", "White", "Harris", "Sanchez", "Clark",
    "Ramirez", "Lewis", "Robinson", "Walker", "Young", "Allen", "King",
    "Wright", "Scott", "Torres", "Nguyen", "Hill", "Flores", "Green",
    "Adams", "Nelson", "Baker", "Hall", "Rivera", "Campbell", "Mitchell",
]
EMAIL_DOMAINS = ["gmail.com", "yahoo.com", "outlook.com", "icloud.com", "hotmail.com"]


# --------------------------------------------------------------------------- #
# Build the daily demand curve
# --------------------------------------------------------------------------- #
days = pd.date_range(START, END, freq="D")
D = len(days)
day_index = np.arange(D)
months = days.month.to_numpy()
weekdays = days.weekday.to_numpy()

growth = GROWTH_DAILY ** day_index
season = MONTH_SEASON[months - 1]
wf = WEEKDAY_FACTOR[weekdays]

holiday = np.ones(D)


def _bump(mask, factor):
    holiday[mask] *= factor


# Black Friday / Cyber Monday (4th Thursday of November +1 / +4 days) & holiday run-up.
for yr in (2023, 2024, 2025):
    novs = days[(days.year == yr) & (days.month == 11)]
    thursdays = novs[novs.weekday == 3]
    bf = thursdays[3] + pd.Timedelta(days=1)          # Black Friday
    cm = thursdays[3] + pd.Timedelta(days=4)          # Cyber Monday
    _bump(days == bf, 4.2)
    _bump(days == cm, 3.6)
    _bump((days >= bf) & (days <= cm), 1.8)
    _bump((days.year == yr) & (days.month == 12) & (days.day <= 22), 1.25)
    # Fourth-of-July summer sale week.
    _bump((days.year == yr) & (days.month == 7) & (days.day >= 1) & (days.day <= 7), 1.5)

daily_weight = growth * season * wf * holiday
p_day = daily_weight / daily_weight.sum()


# --------------------------------------------------------------------------- #
# Products
# --------------------------------------------------------------------------- #
products = []
pid = 1000
for cat, (subs, lo, hi) in CATEGORIES.items():
    n = 50
    for _ in range(n):
        sub = rng.choice(subs)
        # right-skewed price: most SKUs cheap, a few premium (mean ~27% of range)
        frac = rng.beta(1.5, 4.0)
        list_price = float(np.round(lo + (hi - lo) * frac, 2))
        margin_rate = rng.uniform(0.42, 0.62)             # cost is 42-62% of list
        unit_cost = float(np.round(list_price * margin_rate, 2))
        popularity = float(rng.gamma(2.0, 1.0))           # some products sell far more
        products.append(
            dict(product_id=pid, product_name=f"{sub[:-1] if sub.endswith('s') else sub} {rng.integers(100, 999)}",
                 category=cat, subcategory=sub, unit_cost=unit_cost,
                 list_price=list_price, _popularity=popularity)
        )
        pid += 1
products_df = pd.DataFrame(products)

# Per-category product id / popularity lookups (for fast sampling).
cat_products = {
    cat: (
        products_df.loc[products_df.category == cat, "product_id"].to_numpy(),
        (lambda w: w / w.sum())(
            products_df.loc[products_df.category == cat, "_popularity"].to_numpy()
        ),
    )
    for cat in CATEGORY_NAMES
}
price_lookup = products_df.set_index("product_id")["list_price"].to_dict()


# --------------------------------------------------------------------------- #
# Customers
# --------------------------------------------------------------------------- #
chan_names = list(CHANNELS.keys())
chan_acq_w = np.array([CHANNELS[c][0] for c in chan_names])
chan_acq_w = chan_acq_w / chan_acq_w.sum()
chan_loyal = {c: CHANNELS[c][1] for c in chan_names}

cust_channel = rng.choice(chan_names, size=N_CUSTOMERS, p=chan_acq_w)
signup_idx = rng.choice(D, size=N_CUSTOMERS, p=p_day)      # acquisition follows demand curve

state_codes = np.array(list(STATE_POP.keys()))
state_w = np.array(list(STATE_POP.values()))
state_w = state_w / state_w.sum()
cust_state = rng.choice(state_codes, size=N_CUSTOMERS, p=state_w)

cust_age = np.round(rng.normal(43, 14, N_CUSTOMERS)).astype(int).clip(18, 84)
cust_optin = rng.random(N_CUSTOMERS) < 0.68

fn = rng.choice(FIRST_NAMES, N_CUSTOMERS)
ln = rng.choice(LAST_NAMES, N_CUSTOMERS)

customers_df = pd.DataFrame(dict(
    customer_id=np.arange(1, N_CUSTOMERS + 1),
    first_name=fn,
    last_name=ln,
    email=[f"{a}.{b}{rng.integers(1, 999)}@{rng.choice(EMAIL_DOMAINS)}".lower()
           for a, b in zip(fn, ln)],
    signup_date=days[signup_idx],
    acquisition_channel=cust_channel,
    state=cust_state,
    age=cust_age,
    is_marketing_opt_in=cust_optin,
))

# Repeat-order propensity: Gamma mixing -> negative-binomial counts (heavy tail
# of loyal VIPs, but most customers order only once or twice).
loyalty = np.array([chan_loyal[c] for c in cust_channel])
lam = rng.gamma(shape=0.9, scale=0.7, size=N_CUSTOMERS) * loyalty
n_orders = 1 + rng.poisson(lam)                            # every customer buys >=1


# --------------------------------------------------------------------------- #
# Orders & order items (event simulation)
# --------------------------------------------------------------------------- #
order_rows = []
item_rows = []
oid = 100000
iid = 500000

for c in range(N_CUSTOMERS):
    lo = signup_idx[c]
    k = n_orders[c]
    order_day_idxs = [lo]
    n_extra = k - 1
    if n_extra > 0:
        w = p_day * np.exp(-(day_index - lo) / 150.0)      # seasonality * recency decay
        w[:lo] = 0.0
        s = w.sum()
        if s > 0:
            w = w / s
            extra = rng.choice(D, size=n_extra, p=w)
            order_day_idxs.extend(extra.tolist())
    order_day_idxs.sort()

    cid = c + 1
    for d_idx in order_day_idxs:
        m = months[d_idx]
        # Category selection = base popularity * this month's seasonal pull.
        cat_w = np.array([CAT_BASE_WEIGHT[cat] * CAT_SEASON[cat][m - 1]
                          for cat in CATEGORY_NAMES])
        cat_w = cat_w / cat_w.sum()

        n_items = min(1 + rng.poisson(0.5), 6)
        chosen_cats = rng.choice(N_CAT, size=n_items, p=cat_w)

        # Seasonal promo depth (deeper discounts in Nov/Dec/Jul).
        promo_base = 0.18 if m in (7, 11, 12) else 0.07
        gross = 0.0
        cat_counter = np.zeros(N_CAT, dtype=int)
        for ci in chosen_cats:
            cat = CATEGORY_NAMES[ci]
            cat_counter[ci] += 1
            pids, pw = cat_products[cat]
            product_id = int(rng.choice(pids, p=pw))
            qty = int(min(1 + rng.poisson(0.25), 8))
            promo = float(np.clip(rng.normal(promo_base, 0.06), 0.0, 0.45))
            unit_price = round(price_lookup[product_id] * (1 - promo), 2)
            gross += qty * unit_price
            item_rows.append(dict(order_item_id=iid, order_id=oid,
                                  product_id=product_id, quantity=qty,
                                  unit_price=unit_price))
            iid += 1

        dominant_cat = CATEGORY_NAMES[int(np.argmax(cat_counter))]
        # Order status.
        r = rng.random()
        if r < 0.02:
            status = "cancelled"
        elif r < 0.02 + RETURN_RATE[dominant_cat]:
            status = rng.choice(["returned", "refunded"])
        else:
            status = rng.choice(["completed", "delivered", "shipped"], p=[0.7, 0.2, 0.1])

        # Order-level coupon (separate from item promos) + shipping.
        coupon = 0.0
        if rng.random() < 0.22:
            coupon = round(min(gross * rng.uniform(0.05, 0.15), 60.0), 2)
        shipping = 0.0 if gross > 75 else round(rng.uniform(4.95, 12.95), 2)

        order_rows.append(dict(order_id=oid, customer_id=cid,
                               order_date=days[d_idx], order_status=status,
                               discount_amount=coupon, shipping_cost=shipping))
        oid += 1

orders_df = pd.DataFrame(order_rows)
items_df = pd.DataFrame(item_rows)


# --------------------------------------------------------------------------- #
# Inject realistic "dirtiness"
# --------------------------------------------------------------------------- #
CHANNEL_VARIANTS = {
    "Paid Search": ["Paid Search", "paid search", "PAID_SEARCH", "Paid-Search", " Paid Search "],
    "Paid Social": ["Paid Social", "paid social", "PAID_SOCIAL", "Social", "social media"],
    "Organic":     ["Organic", "organic", "ORGANIC", "Organic Search"],
    "Email":       ["Email", "email", "EMAIL", "e-mail", "Email "],
    "Affiliate":   ["Affiliate", "affiliate", "AFFILIATE"],
    "Referral":    ["Referral", "referral", "REFERRAL", "refer-a-friend"],
    "Direct":      ["Direct", "direct", "DIRECT", "(none)"],
}
STATUS_VARIANTS = {
    "completed": ["completed", "Completed", "COMPLETE", "complete"],
    "delivered": ["delivered", "Delivered", "DELIVERED"],
    "shipped":   ["shipped", "Shipped", "SHIPPED", "in transit"],
    "cancelled": ["cancelled", "canceled", "Cancelled", "CANCELLED"],
    "returned":  ["returned", "Returned", "RETURNED"],
    "refunded":  ["refunded", "Refunded", "REFUND"],
}


def messy_choice(mapping, key):
    return str(rng.choice(mapping[key]))


def money_str(x):
    """Occasionally render a number as a currency string like '$1,299.00'."""
    return f"${x:,.2f}"


# ---- customers: channel/state casing, whitespace, bad emails, bad ages/dates ----
cust = customers_df.copy()
cust["acquisition_channel"] = [messy_choice(CHANNEL_VARIANTS, c) for c in cust["acquisition_channel"]]

# State: sometimes full name, lowercase, or trailing period.
def messy_state(code):
    r = rng.random()
    if r < 0.08 and code in STATE_FULL:
        return STATE_FULL[code]
    if r < 0.14:
        return code.lower()
    if r < 0.18:
        return f"{code}."
    if r < 0.205:
        return ""                       # missing
    return code

cust["state"] = [messy_state(s) for s in cust["state"]]

# Emails: uppercase some, add whitespace, break a few, blank a few.
def messy_email(e):
    r = rng.random()
    if r < 0.03:
        return ""                       # missing
    if r < 0.06:
        return e.replace("@", "")       # malformed (no @)
    if r < 0.11:
        return f"  {e.upper()}  "       # whitespace + case
    return e

cust["email"] = [messy_email(e) for e in cust["email"]]

# Ages: inject impossible values; blank some.
age = cust["age"].astype(object).to_numpy(copy=True)
n = len(age)
bad_age_idx = rng.choice(n, size=int(0.02 * n), replace=False)
for i in bad_age_idx:
    age[i] = rng.choice([0, -5, 3, 150, 220])
blank_age_idx = rng.choice(n, size=int(0.03 * n), replace=False)
for i in blank_age_idx:
    age[i] = ""
cust["age"] = age

# Signup dates: format as strings, some with a time component, a few in the future.
sd = cust["signup_date"].dt.strftime("%Y-%m-%d").to_numpy().astype(object)
time_idx = rng.choice(n, size=int(0.10 * n), replace=False)
for i in time_idx:
    sd[i] = sd[i] + f" {rng.integers(0,24):02d}:{rng.integers(0,60):02d}:{rng.integers(0,60):02d}"
future_idx = rng.choice(n, size=int(0.006 * n), replace=False)
for i in future_idx:
    sd[i] = "2027-05-14"                # impossible (after the data window)
ws_idx = rng.choice(n, size=int(0.03 * n), replace=False)
for i in ws_idx:
    sd[i] = f" {sd[i]} "
cust["signup_date"] = sd

# opt-in as mixed truthy/falsy tokens.
cust["is_marketing_opt_in"] = [
    rng.choice(["true", "1", "yes"]) if v else rng.choice(["false", "0", "no"])
    for v in cust["is_marketing_opt_in"]
]

# ---- products: category casing + currency strings + a few invalid prices ----
prod = products_df.drop(columns=["_popularity"]).copy()

def messy_category(cat):
    r = rng.random()
    if r < 0.10:
        return cat.upper()
    if r < 0.18:
        return cat.lower()
    if r < 0.22:
        return f" {cat} "
    return cat

prod["category"] = [messy_category(c) for c in prod["category"]]

lp = prod["list_price"].astype(object).to_numpy(copy=True)
money_idx = rng.choice(len(lp), size=int(0.15 * len(lp)), replace=False)
for i in money_idx:
    lp[i] = money_str(lp[i])
bad_price_idx = rng.choice(len(lp), size=6, replace=False)
for i in bad_price_idx:
    lp[i] = rng.choice([0, -19.99])     # invalid price
prod["list_price"] = lp

# ---- orders: status casing, currency/blank discounts, string dates, duplicates, orphans ----
ordf = orders_df.copy()
ordf["order_status"] = [messy_choice(STATUS_VARIANTS, s) for s in ordf["order_status"]]

# discount_amount: some as "$x", some blank (should be treated as 0).
disc = ordf["discount_amount"].astype(object).to_numpy(copy=True)
for i in range(len(disc)):
    if disc[i] == 0.0:
        if rng.random() < 0.5:
            disc[i] = ""                # blank instead of 0
    elif rng.random() < 0.25:
        disc[i] = money_str(disc[i])
ordf["discount_amount"] = disc

# order_date -> strings, some with time, some padded.
od = ordf["order_date"].dt.strftime("%Y-%m-%d").to_numpy().astype(object)
t2 = rng.choice(len(od), size=int(0.10 * len(od)), replace=False)
for i in t2:
    od[i] = od[i] + f" {rng.integers(8,20):02d}:{rng.integers(0,60):02d}:00"
ordf["order_date"] = od

# Orphan foreign keys: point a few orders at non-existent customers.
orphan_idx = rng.choice(len(ordf), size=40, replace=False)
ordf.loc[ordf.index[orphan_idx], "customer_id"] = rng.integers(900000, 999999, size=40)

# Duplicate ~1.2% of order rows (full-row duplicates).
dup_idx = rng.choice(len(ordf), size=int(0.012 * len(ordf)), replace=False)
ordf = pd.concat([ordf, ordf.iloc[dup_idx]], ignore_index=True)
ordf = ordf.sample(frac=1.0, random_state=SEED).reset_index(drop=True)

# ---- order_items: bad quantities/prices, currency strings, orphan products ----
itemf = items_df.copy()

q = itemf["quantity"].astype(object).to_numpy(copy=True)
bad_q = rng.choice(len(q), size=int(0.01 * len(q)), replace=False)
for i in bad_q:
    q[i] = rng.choice([0, -1, -2])
null_q = rng.choice(len(q), size=int(0.004 * len(q)), replace=False)
for i in null_q:
    q[i] = ""
itemf["quantity"] = q

up = itemf["unit_price"].astype(object).to_numpy(copy=True)
money_up = rng.choice(len(up), size=int(0.08 * len(up)), replace=False)
for i in money_up:
    up[i] = money_str(up[i])
# decimal-shift outliers (price accidentally 100x) + a few non-positive.
out_up = rng.choice(len(up), size=int(0.002 * len(up)), replace=False)
for i in out_up:
    val = up[i]
    up[i] = round(float(str(val).replace("$", "").replace(",", "")) * 100, 2)
neg_up = rng.choice(len(up), size=int(0.003 * len(up)), replace=False)
for i in neg_up:
    up[i] = rng.choice([0, -5.0])
itemf["unit_price"] = up

# Orphan product ids on a few items.
orphan_p = rng.choice(len(itemf), size=60, replace=False)
itemf.loc[itemf.index[orphan_p], "product_id"] = rng.integers(90000, 99999, size=60)


# --------------------------------------------------------------------------- #
# Write
# --------------------------------------------------------------------------- #
RAW_DIR.mkdir(parents=True, exist_ok=True)
cust.to_csv(RAW_DIR / "customers.csv", index=False)
prod.to_csv(RAW_DIR / "products.csv", index=False)
ordf.to_csv(RAW_DIR / "orders.csv", index=False)
itemf.to_csv(RAW_DIR / "order_items.csv", index=False)

print("Wrote raw CSVs to", RAW_DIR)
print(f"  customers.csv   {len(cust):>8,} rows")
print(f"  products.csv    {len(prod):>8,} rows")
print(f"  orders.csv      {len(ordf):>8,} rows  (incl. {len(dup_idx):,} injected duplicates)")
print(f"  order_items.csv {len(itemf):>8,} rows")
