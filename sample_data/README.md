# Sample data

`shipments_2024.csv` — 2,400 purchase orders across six suppliers and a full
year, ~290 KB. Drop it straight into the app.

It's shaped like a **real** export rather than a tidy one, which is the point:

- **No delay column.** The app derives delay from `Promised Delivery Date` vs
  `Actual Delivery Date` — the thing real datasets always make you do.
- **No status column.** On-time / delayed is inferred from the derived delay.
- **No lead-time column.** Computed from order date to delivery date.

So the only columns given are ones a purchasing system would actually export,
and every metric on the dashboard is calculated from them.

What it should produce:

| | |
|---|---|
| Late shipments | ~55% |
| Avg delay | ~9.7 days |
| Composite risk | ~44 (MEDIUM) |
| Trend | Worsening across 12 months |
| Best / worst vendor health | ~84 vs ~20 |
| Highest country risk | China, then India |

The supplier performance spread is deliberate — one supplier carries a third of
the volume *and* has the worst delivery record, which is what makes the vendor
concentration driver worth looking at.

For other realistic datasets to try, see [DATA.md](../DATA.md).
