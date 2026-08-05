"""Unit tests for CSV ingestion — header mapping, coercion, and rejection."""

from __future__ import annotations

import uuid
from datetime import date

import pytest

from app.core.exceptions import PayloadTooLargeError, ValidationError
from app.models.enums import ShipmentStatus
from app.services.csv_ingest import CsvIngestService, map_columns

UPLOAD_ID = uuid.uuid4()

CANONICAL_CSV = b"""shipment_id,vendor,product,origin_country,destination,quantity,unit_cost,lead_time_days,status,delay_days,shipped_on
S001,Acme,Widget,China,Dallas TX,500,45.00,14,delayed,8,2024-01-15
S002,Beta,Gadget,Brazil,Houston TX,1200,12.50,7,on_time,0,2024-01-16
"""


@pytest.fixture
def service() -> CsvIngestService:
    return CsvIngestService()


class TestColumnMapping:
    def test_maps_canonical_headers(self):
        mapping, unmapped = map_columns(["vendor", "delay_days", "status"])
        assert mapping["vendor"] == "vendor"
        assert mapping["delay_days"] == "delay_days"
        assert unmapped == []

    def test_matches_regardless_of_case_spacing_and_punctuation(self):
        mapping, _ = map_columns(["Unit Cost", "LEAD-TIME-DAYS", "Origin Country"])
        assert mapping["unit_cost"] == "Unit Cost"
        assert mapping["lead_time_days"] == "LEAD-TIME-DAYS"
        assert mapping["origin_country"] == "Origin Country"

    def test_accepts_common_synonyms(self):
        mapping, _ = map_columns(["Supplier", "Days Late", "SKU"])
        assert mapping["vendor"] == "Supplier"
        assert mapping["delay_days"] == "Days Late"
        assert mapping["product"] == "SKU"

    def test_reports_columns_it_could_not_place(self):
        _, unmapped = map_columns(["vendor", "internal_notes", "approver_initials"])
        assert set(unmapped) == {"internal_notes", "approver_initials"}

    def test_one_header_is_not_claimed_by_two_fields(self):
        mapping, _ = map_columns(["id", "shipment_id"])
        assert len(set(mapping.values())) == len(mapping.values())


class TestParsing:
    def test_parses_a_well_formed_file(self, service):
        result = service.parse(CANONICAL_CSV, UPLOAD_ID)

        assert result.report.accepted_rows == 2
        assert result.report.rejected_rows == 0

        first = result.shipments[0]
        assert first.vendor == "Acme"
        assert first.delay_days == 8
        assert first.status == ShipmentStatus.DELAYED
        assert first.unit_cost == 45.0
        assert first.shipped_on == date(2024, 1, 15)

    def test_strips_currency_symbols_and_thousands_separators(self, service):
        csv = b'vendor,quantity,unit_cost\nAcme,"1,200","$1,450.75"\n'
        shipment = service.parse(csv, UPLOAD_ID).shipments[0]
        assert shipment.quantity == 1200
        assert shipment.unit_cost == 1450.75

    def test_accepts_multiple_date_formats(self, service):
        csv = b"vendor,shipped_on\nAcme,15/01/2024\nBeta,2024-02-20\n"
        shipments = service.parse(csv, UPLOAD_ID).shipments
        assert shipments[0].shipped_on == date(2024, 1, 15)
        assert shipments[1].shipped_on == date(2024, 2, 20)

    def test_unparseable_cell_degrades_to_null_without_losing_the_row(self, service):
        csv = b"vendor,quantity,shipped_on\nAcme,not-a-number,never\n"
        shipment = service.parse(csv, UPLOAD_ID).shipments[0]
        assert shipment.vendor == "Acme"
        assert shipment.quantity is None
        assert shipment.shipped_on is None

    def test_status_is_inferred_from_delay_when_the_column_is_absent(self, service):
        csv = b"vendor,delay_days\nAcme,0\nBeta,5\n"
        shipments = service.parse(csv, UPLOAD_ID).shipments
        assert shipments[0].status == ShipmentStatus.ON_TIME
        assert shipments[1].status == ShipmentStatus.DELAYED

    def test_negative_delay_is_clamped_to_zero(self, service):
        # An "early" arrival is not negative lateness.
        csv = b"vendor,delay_days\nAcme,-3\n"
        assert service.parse(csv, UPLOAD_ID).shipments[0].delay_days == 0

    def test_blank_rows_are_rejected_not_stored(self, service):
        csv = b"vendor,delay_days\nAcme,1\n,\n,\n"
        result = service.parse(csv, UPLOAD_ID)
        assert result.report.accepted_rows == 1
        assert result.report.rejected_rows == 2

    def test_utf8_bom_from_excel_is_handled(self, service):
        csv = "﻿vendor,delay_days\nAcmé,3\n".encode()
        assert service.parse(csv, UPLOAD_ID).shipments[0].vendor == "Acmé"

    def test_cp1252_export_is_handled(self, service):
        csv = "vendor,delay_days\nCafé Supply,2\n".encode("cp1252")
        assert service.parse(csv, UPLOAD_ID).shipments[0].vendor is not None

    def test_row_cap_truncates_and_warns(self):
        service = CsvIngestService(max_rows=2)
        csv = b"vendor,delay_days\n" + b"".join(f"V{i},1\n".encode() for i in range(10))
        result = service.parse(csv, UPLOAD_ID)
        assert result.report.accepted_rows == 2
        assert any("truncated" in w for w in result.report.warnings)

    def test_missing_critical_column_produces_a_warning_not_an_error(self, service):
        csv = b"vendor,product\nAcme,Widget\n"
        result = service.parse(csv, UPLOAD_ID)
        assert result.report.accepted_rows == 1

        warnings = " ".join(result.report.warnings).lower()
        # The file parses, but the user is told which metrics will be empty:
        # no delay source, and nothing to date the trend chart with.
        assert "delay" in warnings
        assert "date" in warnings


class TestRejection:
    def test_oversized_file_is_rejected(self):
        service = CsvIngestService(max_bytes=10)
        with pytest.raises(PayloadTooLargeError):
            service.parse(b"vendor,delay_days\n" + b"x" * 100, UPLOAD_ID)

    def test_file_with_no_recognisable_columns_is_rejected(self, service):
        with pytest.raises(ValidationError, match="No recognisable"):
            service.parse(b"alpha,beta,gamma\n1,2,3\n", UPLOAD_ID)

    def test_header_only_file_is_rejected(self, service):
        with pytest.raises(ValidationError, match="No usable rows"):
            service.parse(b"vendor,delay_days\n", UPLOAD_ID)

    def test_empty_file_is_rejected(self, service):
        with pytest.raises(ValidationError):
            service.parse(b"", UPLOAD_ID)
