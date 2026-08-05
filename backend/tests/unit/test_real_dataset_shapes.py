"""Ingestion tests against the header shapes of real public datasets.

The sample CSV is tidy and pre-computed; real exports are neither. These use
the actual column names from datasets people would plausibly try, because the
failure mode they cause is silent: no delay column means every shipment reads
as on-time and the risk score comes out zero.
"""

from __future__ import annotations

import io
import uuid
from datetime import date

import pytest

from app.core.exceptions import ValidationError
from app.models.enums import ShipmentStatus
from app.services.csv_ingest import CsvIngestService, IngestStats

UPLOAD_ID = uuid.uuid4()


@pytest.fixture
def service() -> CsvIngestService:
    return CsvIngestService()


class TestUsaidShipmentPricing:
    """USAID "Supply Chain Shipment Pricing Data" — vendor, country, and a
    scheduled/delivered date pair with no precomputed delay."""

    CSV = (
        b"ID,Country,Vendor,Item Description,Scheduled Delivery Date,"
        b"Delivered to Client Date,Line Item Quantity,Unit Price\n"
        b"1,Zambia,Orgenics Ltd,HIV test kit,2024-01-15,2024-01-29,1000,3.50\n"
        b"2,Nigeria,Aurobindo Pharma,Lamivudine 150mg,2024-02-10,2024-02-10,5000,0.80\n"
        b"3,Zambia,Orgenics Ltd,HIV test kit,2024-03-01,2024-03-21,2000,3.50\n"
    )

    def test_columns_map_without_editing_the_file(self, service):
        result = service.parse(self.CSV, UPLOAD_ID)
        detected = result.report.detected_columns
        assert detected["vendor"] == "Vendor"
        assert detected["origin_country"] == "Country"
        assert detected["scheduled_delivery"] == "Scheduled Delivery Date"
        assert detected["actual_delivery"] == "Delivered to Client Date"

    def test_delay_is_derived_from_the_date_pair(self, service):
        shipments = service.parse(self.CSV, UPLOAD_ID).shipments
        # 15 Jan scheduled, 29 Jan delivered.
        assert shipments[0].delay_days == 14
        assert shipments[1].delay_days == 0
        assert shipments[2].delay_days == 20

    def test_status_is_inferred_from_the_derived_delay(self, service):
        shipments = service.parse(self.CSV, UPLOAD_ID).shipments
        assert shipments[0].status == ShipmentStatus.DELAYED
        assert shipments[1].status == ShipmentStatus.ON_TIME

    def test_rows_get_a_date_so_the_trend_can_be_plotted(self, service):
        # Without this the dashboard reports "0 dated periods". With no ship
        # date column, the actual delivery date is what places the shipment in
        # a month — it's the event that really happened.
        shipments = service.parse(self.CSV, UPLOAD_ID).shipments
        assert [s.shipped_on for s in shipments] == [
            date(2024, 1, 29),
            date(2024, 2, 10),
            date(2024, 3, 21),
        ]

    def test_the_derivation_is_reported_to_the_user(self, service):
        # Counted as structured data rather than prose, so the UI can say it in
        # its own words — a number the app invented must never be presented as
        # one the file supplied.
        assert service.parse(self.CSV, UPLOAD_ID).report.derived_delays == 3


class TestDataCoSmartSupplyChain:
    """Kaggle "DataCo Smart Supply Chain" — scheduled and real shipping days,
    delivery status, and date columns with a parenthesised suffix."""

    CSV = (
        b"Order Id,Days for shipping (real),Days for shipment (scheduled),"
        b"Delivery Status,Order Country,Product Name,Order Item Quantity,"
        b"Order Item Product Price,order date (DateOrders)\n"
        b"1001,6,4,Late delivery,Indonesia,Smart watch,1,327.75,1/13/2024 12:27\n"
        b"1002,2,4,Shipping on time,India,Field jacket,3,49.98,2/2/2024 10:15\n"
        b"1003,5,4,Late delivery,Indonesia,Smart watch,2,327.75,3/9/2024 8:40\n"
    )

    def test_headers_with_parenthesised_suffixes_map(self, service):
        detected = service.parse(self.CSV, UPLOAD_ID).report.detected_columns
        assert detected["shipment_ref"] == "Order Id"
        assert detected["origin_country"] == "Order Country"
        assert detected["lead_time_days"] == "Days for shipment (scheduled)"
        assert detected["shipped_on"] == "order date (DateOrders)"

    def test_us_datetime_format_parses(self, service):
        shipments = service.parse(self.CSV, UPLOAD_ID).shipments
        assert shipments[0].shipped_on == date(2024, 1, 13)

    def test_delivery_status_text_maps_onto_the_enum(self, service):
        shipments = service.parse(self.CSV, UPLOAD_ID).shipments
        assert shipments[1].status == ShipmentStatus.ON_TIME

    def test_three_months_of_dates_support_a_trend(self, service):
        periods = {
            s.shipped_on.strftime("%Y-%m")
            for s in service.parse(self.CSV, UPLOAD_ID).shipments
            if s.shipped_on
        }
        assert periods == {"2024-01", "2024-02", "2024-03"}


class TestDelimiters:
    def test_semicolon_separated_export_is_detected(self, service):
        # The default separator in locales that use a comma for decimals.
        csv = b"vendor;delay_days;origin_country\nAcme;5;China\nBeta;0;Brazil\n"
        result = service.parse(csv, UPLOAD_ID)
        assert result.report.accepted_rows == 2
        assert result.shipments[0].vendor == "Acme"
        assert result.shipments[0].delay_days == 5

    def test_tab_separated_export_is_detected(self, service):
        csv = b"vendor\tdelay_days\nAcme\t3\nBeta\t0\n"
        assert service.parse(csv, UPLOAD_ID).report.accepted_rows == 2

    def test_pipe_separated_export_is_detected(self, service):
        csv = b"vendor|delay_days\nAcme|7\n"
        assert service.parse(csv, UPLOAD_ID).shipments[0].delay_days == 7


class TestRowAcceptance:
    def test_a_row_survives_on_any_recognised_column(self, service):
        # The old rule demanded vendor, ref or product and rejected whole
        # datasets whose identity column wasn't aliased.
        csv = b"origin_country,delay_days\nChina,4\nBrazil,0\n"
        result = service.parse(csv, UPLOAD_ID)
        assert result.report.accepted_rows == 2
        assert result.shipments[0].vendor is None

    def test_genuinely_blank_rows_are_still_rejected(self, service):
        csv = b"vendor,delay_days\nAcme,3\n,\n,\n"
        result = service.parse(csv, UPLOAD_ID)
        assert result.report.accepted_rows == 1
        assert result.report.rejected_rows == 2

    def test_spreadsheet_null_tokens_count_as_empty(self, service):
        csv = b"vendor,delay_days,quantity\nAcme,3,100\nN/A,NULL,-\n"
        result = service.parse(csv, UPLOAD_ID)
        assert result.report.accepted_rows == 1

    def test_a_title_row_above_the_header_is_skipped(self, service):
        # What Excel produces when someone exports a formatted report.
        csv = (
            b"Quarterly Supplier Report,,\n"
            b"Generated 2024-04-01,,\n"
            b"\n"
            b"vendor,delay_days,origin_country\n"
            b"Acme,5,China\n"
            b"Beta,0,Brazil\n"
        )
        result = service.parse(csv, UPLOAD_ID)
        assert result.report.accepted_rows == 2
        assert result.shipments[0].vendor == "Acme"
        assert result.report.detected_columns["vendor"] == "vendor"
        assert any("above the header" in w for w in result.report.warnings)

    def test_a_normal_file_skips_nothing_and_says_nothing(self, service):
        result = service.parse(b"vendor,delay_days\nAcme,5\n", UPLOAD_ID)
        assert not any("above the header" in w for w in result.report.warnings)

    def test_a_file_with_no_recognisable_columns_still_errors_helpfully(self, service):
        with pytest.raises(ValidationError) as exc:
            service.parse(b"alpha,beta,gamma\n1,2,3\n", UPLOAD_ID)
        assert "recognisable" in str(exc.value)
        assert "found_headers" in exc.value.details


class TestValueParsing:
    def test_currency_and_thousands_separators(self, service):
        csv = b'vendor,unit_cost,quantity\nAcme,"$1,450.75","1,200"\n'
        shipment = service.parse(csv, UPLOAD_ID).shipments[0]
        assert shipment.unit_cost == 1450.75
        assert shipment.quantity == 1200

    def test_accounting_negatives(self, service):
        csv = b'vendor,unit_cost\nAcme,"(250.00)"\n'
        assert service.parse(csv, UPLOAD_ID).shipments[0].unit_cost == -250.0

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            (b"2024-03-15", date(2024, 3, 15)),
            (b"15/03/2024", date(2024, 3, 15)),
            (b"03/15/2024", date(2024, 3, 15)),
            (b"15-Mar-2024", date(2024, 3, 15)),
            (b"Mar 15, 2024", date(2024, 3, 15)),
            (b"15.03.2024", date(2024, 3, 15)),
            (b"20240315", date(2024, 3, 15)),
            (b"2024-03-15T09:30:00", date(2024, 3, 15)),
        ],
    )
    def test_date_formats(self, service, raw: bytes, expected: date):
        # Quoted, because "Mar 15, 2024" contains the delimiter.
        csv = b'vendor,shipped_on\nAcme,"' + raw + b'"\n'
        assert service.parse(csv, UPLOAD_ID).shipments[0].shipped_on == expected


class TestStreaming:
    def test_batches_are_bounded_by_batch_size(self):
        service = CsvIngestService(batch_size=100)
        rows = b"".join(f"V{i},{i % 5}\n".encode() for i in range(450))
        stats = IngestStats()

        sizes = [
            len(batch)
            for batch in service.stream_batches(
                io.BytesIO(b"vendor,delay_days\n" + rows), UPLOAD_ID, stats
            )
        ]

        # Peak memory tracks the batch, not the file.
        assert max(sizes) <= 100
        assert sum(sizes) == 450
        assert stats.accepted == 450

    def test_row_cap_truncates_and_flags_it(self):
        service = CsvIngestService(max_rows=50, batch_size=20)
        rows = b"".join(f"V{i},1\n".encode() for i in range(200))
        stats = IngestStats()

        total = sum(
            len(b)
            for b in service.stream_batches(
                io.BytesIO(b"vendor,delay_days\n" + rows), UPLOAD_ID, stats
            )
        )

        assert total == 50
        assert stats.truncated is True
        assert any("truncated" in w for w in stats.warnings)

    def test_oversized_file_is_rejected_before_parsing(self):
        from app.core.exceptions import PayloadTooLargeError

        service = CsvIngestService(max_bytes=100)
        stats = IngestStats()
        with pytest.raises(PayloadTooLargeError):
            list(
                service.stream_batches(
                    io.BytesIO(b"vendor,delay_days\n" + b"x" * 500), UPLOAD_ID, stats
                )
            )
