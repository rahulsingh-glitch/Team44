from src.common.checksum import ChecksumLedger


def test_redelivered_file_is_skipped():
    ledger = ChecksumLedger()
    assert ledger.load_if_new("abc123") is True   # first delivery loads
    assert ledger.load_if_new("abc123") is False  # re-delivery skipped


def test_rerun_is_idempotent():
    ledger = ChecksumLedger()
    first = [ledger.load_if_new(c) for c in ["f1", "f2", "f3"]]
    # a full re-run of the same day loads nothing new
    second = [ledger.load_if_new(c) for c in ["f1", "f2", "f3"]]
    assert first == [True, True, True]
    assert second == [False, False, False]
