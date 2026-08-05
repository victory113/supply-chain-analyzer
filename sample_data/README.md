# Sample data

`shipments_2024.csv` — 2,400 purchase orders across six suppliers, four
carriers and a full year, ~490 KB. Drop it straight into the app.

It's shaped like a **real** export rather than a tidy one, which is the point:

- **No delay column.** Delay is derived from `Promised Delivery Date` vs
  `Actual Delivery Date` — the thing real datasets always make you do.
- **No status column.** On-time / delayed is inferred from the derived delay.
- **No lead-time or transit column.** Computed from order to delivery date.
- **No CO₂ column.** Estimated from transport mode, distance and weight.

Everything else is a column a purchasing or transport system would genuinely
export: carrier, mode, service level, category, quantity ordered *and*
delivered, freight cost, customs duty, damage and return flags, incoterms.

What it should produce:

| | |
|---|---|
| Late shipments | ~44% |
| Avg delay | ~7.7 days |
| Composite risk | ~36 (MEDIUM) |
| Trend | Worsening across 12 months |
| Best / worst vendor health | ~84 vs ~31 |
| Highest country risk | China, then India |
| Perfect order rate | ~52% |
| Damage / return rate | ~3.2% / ~1.6% |
| Total freight | ~$2.3M, of which ~$920K went on late deliveries |

The interesting shape is deliberate and mirrors a real trade-off: **ocean is
the cheapest mode per shipment and the worst performer (61% late); air is the
most expensive, the most punctual, and produces the large majority of the
carbon footprint.** Express service runs 21 points more punctual than Standard
at roughly three times the freight cost. Those are the conversations the
dashboard exists to start.

One supplier also carries a third of the volume *and* has the worst delivery
record, which is what makes the vendor concentration risk driver worth reading.

## Testing the adaptive behaviour

Delete columns from this file and re-upload it. Sections disappear rather than
showing zeros — remove `Carrier` and the carrier table is gone; remove
`Freight Cost` and the freight panel is gone; remove `Quantity` and
`Unit Price` and "value at risk" reads "—" instead of "$0", with its weight
redistributed across the remaining risk components.

For other realistic datasets to try, see [DATA.md](../DATA.md).
