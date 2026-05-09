"""前端工具函数单元测试"""

from datetime import datetime
from decimal import Decimal

from frontend.core.utils import format_amount, format_datetime, paginate


class TestFormatAmount:
    def test_strips_trailing_zeros(self):
        assert format_amount(Decimal("10.500000")) == "10.5"

    def test_integer_amount(self):
        assert format_amount(Decimal("100.000000")) == "100"

    def test_full_precision(self):
        assert format_amount(Decimal("1.234567")) == "1.234567"

    def test_small_fraction(self):
        assert format_amount(Decimal("0.000001")) == "0.000001"

    def test_custom_decimals(self):
        assert format_amount(Decimal("1.23"), decimals=2) == "1.23"

    def test_zero(self):
        assert format_amount(Decimal("0")) == "0"


class TestFormatDatetime:
    def test_none_returns_dash(self):
        assert format_datetime(None) == "-"

    def test_formats_correctly(self):
        dt = datetime(2026, 5, 8, 14, 30, 0)
        assert format_datetime(dt) == "2026-05-08 14:30"


class TestPaginate:
    def test_first_page(self):
        total_pages, offset, limit = paginate(total=25, page=1, per_page=5)
        assert total_pages == 5
        assert offset == 0
        assert limit == 5

    def test_middle_page(self):
        total_pages, offset, limit = paginate(total=25, page=3, per_page=5)
        assert offset == 10

    def test_page_beyond_max_clamps(self):
        total_pages, offset, _ = paginate(total=10, page=999, per_page=5)
        assert total_pages == 2
        assert offset == 5

    def test_page_zero_clamps_to_one(self):
        _, offset, _ = paginate(total=10, page=0, per_page=5)
        assert offset == 0

    def test_negative_page_clamps(self):
        _, offset, _ = paginate(total=10, page=-5, per_page=5)
        assert offset == 0

    def test_zero_total(self):
        total_pages, offset, _ = paginate(total=0, page=1, per_page=5)
        assert total_pages == 1
        assert offset == 0

    def test_partial_last_page(self):
        total_pages, _, _ = paginate(total=7, page=1, per_page=5)
        assert total_pages == 2
