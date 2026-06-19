from __future__ import annotations

import argparse
import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "aws-prewarm-cost-estimate.py"
SPEC = importlib.util.spec_from_file_location("aws_prewarm_cost_estimate", MODULE_PATH)
assert SPEC and SPEC.loader
estimator = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(estimator)


def test_estimate_reports_monthly_and_prorated_storage_cost():
    assert estimator.estimate(
        snapshot_gib=40,
        snapshot_rate=0.05,
        retained_days=15,
    ) == {
        "snapshot_gib": 40,
        "snapshot_rate_usd_per_gib_month": 0.05,
        "retained_days": 15,
        "monthly_storage_usd": 2.0,
        "prorated_storage_usd": 1.0,
    }


def test_positive_float_rejects_zero_and_negative_values():
    for value in ("0", "-1"):
        try:
            estimator.positive_float(value)
        except argparse.ArgumentTypeError:
            pass
        else:
            raise AssertionError(f"{value} should have been rejected")
