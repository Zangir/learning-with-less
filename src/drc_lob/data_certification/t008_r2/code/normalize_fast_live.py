"""Apply the predeclared dense-snapshot policy to the separate fast capture."""
import live_snapshot_contract as normalizer

normalizer.CAPTURE_ROOT = normalizer.ROOT / "fast_live"
normalizer.OUT = normalizer.CAPTURE_ROOT / "normalized"
normalizer.MAX_AGE = 1_500_000_000
normalizer.MAX_GAP = 2_000_000_000
normalizer.DEPTH = 5
normalizer.AGE_WORDS = "1.5 seconds"
normalizer.SOURCE_PREFIX = "official-live-fast-"

if __name__ == "__main__":
    normalizer.main()
