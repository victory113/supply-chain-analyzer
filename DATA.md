# What files can I upload?

Short version: **any CSV of shipment, order, or delivery records, up to 100 MB.**
You don't have to rename columns or reshape the file first — the parser reads
whatever headers are there and works out what it can.

---

## The rules

| | |
|---|---|
| Format | `.csv` (comma, semicolon, tab, or pipe separated — detected automatically) |
| Max size | **100 MB** |
| Max rows | 500,000 (anything beyond is ignored and you're told so) |
| Encoding | UTF-8, UTF-8-with-BOM, or Windows-1252 (Excel's default) |
| Header row | Required, but it doesn't have to be the first line — a title or blank lines above it are skipped |

One row should be one shipment, order, or line item.

---

## Which columns get used

Headers are matched by **alias**, after lowercasing and stripping punctuation.
So `Unit Cost`, `unit_cost`, `UNIT-COST`, and `unitcost` are all the same column.

| What it means | Header names that work |
|---|---|
| Vendor / supplier | `vendor`, `supplier`, `supplier name`, `manufacturer`, `carrier`, `seller`, `shipper` |
| Product | `product`, `item`, `sku`, `description`, `product name`, `category name`, `commodity` |
| Origin | `origin country`, `country`, `source country`, `manufacturing country`, `order country` |
| Destination | `destination`, `ship to`, `customer country`, `customer city`, `consignee`, `region` |
| Quantity | `quantity`, `qty`, `units`, `order item quantity`, `line item quantity` |
| Cost | `unit cost`, `price`, `unit price`, `pack price`, `sales`, `amount` |
| Reference | `shipment id`, `order id`, `order number`, `po number`, `tracking number` |
| Status | `status`, `delivery status`, `order status`, `shipping status` |
| Lead time | `lead time`, `transit days`, `days for shipment (scheduled)` |
| Delay | `delay days`, `days late`, `days delayed`, `slippage days` |
| Ship date | `ship date`, `shipped on`, `order date`, `dispatch date`, `purchase date` |
| Promised date | `scheduled delivery date`, `expected delivery date`, `eta`, `due date`, `required date` |
| Actual date | `delivered to client date`, `actual delivery date`, `delivery date`, `received date` |

Columns that don't match anything are ignored, and listed back to you after the
upload so you can see what was skipped.

**Nothing here is mandatory.** A row is kept as long as *one* of these columns
has a value in it. A file with only `country` and `delay_days` analyses fine —
you just get fewer charts.

---

## You don't need a "delay" column

This is the part that matters, because most real exports don't have one.

If there's no delay column but the file has a **promised date and an actual
date**, the delay is calculated for you:

```
Scheduled Delivery Date   Delivered to Client Date   →   delay
2024-01-15                2024-01-29                     14 days late
2024-02-10                2024-02-10                     on time
2024-03-01                2024-02-27                     2 days early
```

The status (on-time / delayed / critical) is then inferred from that number, so
a file with no status column still produces a proper risk score. After the
upload you'll see a note like *"Delay derived from scheduled vs. actual dates
for 8,412 rows"* — derived numbers are always labelled as derived.

Lead time works the same way: with no lead-time column, it's the gap between
the order/ship date and the delivery date. If neither is available the tile
reads "—" rather than "0.0d", because a missing measurement shouldn't look like
a measured zero.

Dates are read in 18 formats, including `2024-03-15`, `15/03/2024`,
`03/15/2024`, `15-Mar-2024`, `Mar 15, 2024`, `15.03.2024`, `20240315`, and full
timestamps like `1/13/2024 12:27`.

Money and numbers survive spreadsheet formatting too: `$1,450.75` reads as
`1450.75`, and `(250.00)` reads as `-250.00`.

---

## Where to get realistic test data

All free. Search the dataset name on the site listed.

**USAID Supply Chain Shipment Pricing Data** — `data.usaid.gov` (also on HDX).
~10,000 real health-commodity shipments: vendor, country, scheduled vs.
delivered dates, quantity, unit price. No delay column — the app derives it.
This is the best single file to demo with.

**DataCo Smart Supply Chain** — Kaggle. ~180,000 orders with scheduled vs. real
shipping days, delivery status, countries, and product categories. Big enough to
show the streaming parser doing real work.

**Brazilian E-Commerce Public Dataset (Olist)** — Kaggle. ~100,000 orders with
purchase, estimated-delivery, and actual-delivery timestamps. Upload
`olist_orders_dataset.csv` directly.

**Supply Chain Analysis / FMCG datasets** — Kaggle, various. Smaller and tidier;
good for quick checks.

**data.gov** — search "shipment", "procurement", or "freight" for government
procurement and logistics exports.

A tiny hand-made file works too: `backend/sample_shipments.csv` in this repo is
four rows and exercises the whole pipeline.

---

## If an upload doesn't work

**"No recognisable columns found"** — none of your headers matched. The error
lists the headers it did find; rename one of them to something in the table
above.

**"No usable rows found"** — every row was blank in every recognised column.
Check that the file isn't just headers, and that it isn't a summary export
where the values live in merged cells.

(A title row or blank lines above the header are fine — the first 15 lines are
scanned for the real header, and anything above it is skipped and reported.)

**Trend chart says "not enough dated periods"** — the app needs at least three
distinct months to call a direction, and it can only date a row if it has a
ship, delivery, or scheduled date. A file with no dates at all still gives you
KPIs, vendor rankings, and country risk — just no trend line.

**Everything shows as on-time** — there's no delay column *and* no date pair to
derive one from. Check that your promised-date and actual-date columns are
named something in the table above.
