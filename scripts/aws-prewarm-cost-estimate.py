#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json


def positive_float(value: str) -> float:
    parsed = float(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("value must be greater than zero")
    return parsed


def estimate(snapshot_gib: float, snapshot_rate: float, retained_days: float) -> dict[str, float]:
    monthly = snapshot_gib * snapshot_rate
    prorated = monthly * (retained_days / 30.0)
    return {
        "snapshot_gib": snapshot_gib,
        "snapshot_rate_usd_per_gib_month": snapshot_rate,
        "retained_days": retained_days,
        "monthly_storage_usd": round(monthly, 4),
        "prorated_storage_usd": round(prorated, 4),
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Estimate conservative EBS snapshot storage cost for a prewarmed PermeantOS AMI."
    )
    parser.add_argument(
        "--snapshot-gib",
        type=positive_float,
        required=True,
        help="Estimated written GiB stored by the AMI backing snapshot.",
    )
    parser.add_argument(
        "--snapshot-rate",
        type=positive_float,
        default=0.05,
        help="EBS standard snapshot rate in USD per GiB-month for the target region. Default: 0.05.",
    )
    parser.add_argument(
        "--retained-days",
        type=positive_float,
        default=30.0,
        help="How long the snapshot is expected to remain retained. Default: 30.",
    )
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON output.")
    args = parser.parse_args()

    result = estimate(args.snapshot_gib, args.snapshot_rate, args.retained_days)
    if args.pretty:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
