"""算力配置目录：档位秒单价 + workflow 预计时长。"""

from decimal import Decimal

from common.compute_catalog import estimate_hold_amount, load_priority_tiers


def test_estimate_hold_amount_from_tier_and_workflow_configs() -> None:
    assert estimate_hold_amount("face_swap", "lite") == Decimal("0.050000")
    assert estimate_hold_amount("face_swap", "default") == Decimal("0.180000")
    assert estimate_hold_amount("face_swap", "plus") == Decimal("0.350000")
    assert estimate_hold_amount("remove_watermark", "lite") == Decimal("0.060000")
    assert estimate_hold_amount("remove_watermark", "default") == Decimal("0.216000")
    assert estimate_hold_amount("remove_watermark", "plus") == Decimal("0.420000")


def test_priority_tiers_include_second_prices() -> None:
    tiers = load_priority_tiers()

    assert tiers["lite"].price_per_second_usd == Decimal("0.000200000")
    assert tiers["default"].price_per_second_usd == Decimal("0.000720000")
    assert tiers["plus"].price_per_second_usd == Decimal("0.001400000")
