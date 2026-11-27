"""Generate synthetic OmniRetail data with Faker. Expand on the day to match the card.

Usage: python scripts/generate_synthetic_data.py --stores 50 --products 5000 --days 365
Writes POS CSV per store, e-commerce JSON, and product/store master CSVs into data/landing/.
Include a few PLANTED DEFECTS so the pipeline can demonstrate handling them:
  - a re-delivered file (identical bytes)
  - late-arriving sales for a prior day
  - a product renamed mid-year (SCD2)
  - amounts with currency symbols
  - mixed time zones
"""
import argparse


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stores", type=int, default=50)
    ap.add_argument("--products", type=int, default=5000)
    ap.add_argument("--days", type=int, default=365)
    args = ap.parse_args()
    # TODO on the day: use faker to emit files into data/landing/.
    # Keep the generator deterministic (seed) so re-runs are comparable.
    print(f"[stub] would generate {args.stores} stores, {args.products} products, {args.days} days")


if __name__ == "__main__":
    main()
