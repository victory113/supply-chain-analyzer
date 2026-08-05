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

## How your columns are understood

Your file is mapped onto a **canonical shipment model** — one internal shape
that every upload is translated into. The analytics never see your original
column names, which is why an SAP export, a carrier report and a hand-made
spreadsheet all produce the same dashboard.

Matching happens in two passes:

1. **Alias.** Headers are lowercased and stripped of punctuation, so
   `Unit Cost`, `unit_cost`, `UNIT-COST` and `unitcost` are the same column.
   Around 350 aliases are recognised.
2. **Fuzzy.** Anything left over is matched by similarity, so a typo in your
   source system (`Suppler Name`, `Frght Cost`) still lands correctly. These are
   flagged separately in the upload summary as guesses, not recognised columns.

### The canonical fields

| Group | What it means | Header names that work |
|---|---|---|
| **Identity** | Shipment reference | `shipment id`, `order id`, `po`, `record id` |
| | Order reference | `sales order`, `purchase order`, `order reference` |
| | Tracking | `tracking number`, `waybill`, `awb`, `bill of lading`, `pro number` |
| | Customer ref | `customer id`, `account number`, `client id` |
| **Parties** | Vendor / supplier | `vendor`, `supplier`, `manufacturer`, `seller`, `shipper` |
| | Carrier | `carrier`, `freight forwarder`, `shipping line`, `transporter`, `3pl` |
| | Customer | `customer`, `client`, `consignee name`, `buyer` |
| | Service level | `service level`, `shipping method`, `service type` |
| **Product** | Product | `product`, `item`, `description`, `material`, `commodity` |
| | SKU | `sku`, `item code`, `part number`, `material number` |
| | Category | `category`, `product category`, `product line`, `segment` |
| | Brand | `brand`, `make`, `label` |
| | Quantity | `quantity`, `qty`, `units`, `order item quantity` |
| | Quantity delivered | `quantity delivered`, `received quantity`, `quantity fulfilled` |
| | Unit cost | `unit cost`, `price`, `unit price`, `pack price` |
| | Currency | `currency`, `currency code`, `ccy` |
| | Weight | `weight`, `weight kg`, `gross weight`, `chargeable weight` |
| | Hazardous | `hazardous`, `hazmat`, `dangerous goods` |
| | Temp controlled | `refrigerated`, `reefer`, `cold chain` |
| **Geography** | Origin country | `origin country`, `country`, `country of origin`, `ship from` |
| | Origin city | `origin city`, `ship from city`, `pickup city` |
| | Destination | `destination`, `ship to`, `consignee`, `region` |
| | Destination country/city | `delivery country`, `ship to city`, `arrival city` |
| | Warehouse | `warehouse`, `distribution center`, `facility`, `site` |
| **Transport** | Mode | `transport mode`, `mode`, `shipment mode`, `freight mode` |
| | Container | `container number`, `equipment id` |
| | Vehicle | `truck number`, `flight number`, `vessel name`, `voyage` |
| | Route / lane | `route id`, `lane`, `lane code` |
| | Packages | `packages`, `cartons`, `pallets`, `pieces` |
| | Distance | `distance`, `distance km`, `route distance` |
| **Timing** | Ship date | `ship date`, `order date`, `dispatch date`, `purchase date` |
| | Promised date | `promised delivery date`, `scheduled delivery date`, `eta`, `due date` |
| | Actual date | `actual delivery date`, `delivered to client date`, `received date` |
| | Lead time | `lead time`, `transit days`, `days for shipment (scheduled)` |
| | Transit time | `transit time`, `days in transit`, `actual shipping days` |
| | Delay | `delay days`, `days late`, `slippage days` |
| | Status | `status`, `delivery status`, `order status` |
| | Priority | `priority`, `order priority`, `urgency` |
| **Money** | Freight cost | `freight cost`, `shipping cost`, `transport cost`, `haulage cost` |
| | Insurance | `insurance cost`, `insurance amount` |
| | Customs duty | `customs duty`, `duty`, `tariff`, `import duty` |
| | Total cost | `total cost`, `landed cost`, `invoice amount`, `grand total` |
| **Quality** | Damaged | `damaged`, `damage reported` |
| | Returned | `returned`, `return flag`, `rma` |
| **Customs** | Incoterms | `incoterms`, `delivery terms`, `trade terms` |
| | HS code | `hs code`, `harmonized code`, `tariff code` |
| **Carbon** | CO₂ | `co2`, `carbon emissions`, `ghg emissions`, `carbon footprint` |

Columns that don't match anything are ignored, and listed back to you after the
upload so you can see what was skipped.

**Nothing here is mandatory.** A row is kept as long as *one* of these columns
has a value in it. A file with only `country` and `delay_days` analyses fine —
you just get fewer sections.

### What each column unlocks

The dashboard adapts to what you provide. Sections you have no data for are
**omitted entirely**, never shown as zeros:

| Add this column | And you get |
|---|---|
| `carrier` | Carrier performance league table |
| `transport mode` | Air vs ocean vs road comparison, and carbon by mode |
| `service level` | Whether your premium service earns its premium |
| `category` | Which product groups run late |
| `destination` | Trade-lane analysis, worst routes first |
| `freight cost` | Freight economics, incl. what lateness costs you |
| `weight` + `distance` | Estimated CO₂e per shipment and per mode |
| `damaged` / `returned` | Damage and return rates, perfect-order rate |
| `quantity delivered` | Fill rate |

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

**In this repo:** [`sample_data/shipments_2024.csv`](sample_data/shipments_2024.csv)
— 2,400 orders across six suppliers and a full year, with no delay, status, or
lead-time column, so every metric has to be derived. `backend/sample_shipments.csv`
is a four-row version for quick smoke tests.

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

**A section you expected is missing** — the app omits any section it has no
data for, rather than showing zeros. Open "Show column mapping" after the
upload: it lists exactly which of your headers were used, which were guessed,
and which were ignored.

**A column was mapped to the wrong thing** — fuzzy matching guessed. The upload
summary flags guesses separately from exact matches; rename the header to one
of the aliases above to make it exact.
