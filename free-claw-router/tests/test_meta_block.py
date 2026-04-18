from router.meta.meta_evaluator import (
    record_rollback,
    record_apply_success,
    is_blocked,
    unblock,
)


def test_first_rollback_does_not_block(tmp_path):
    record_rollback("target.yaml", store_dir=tmp_path)
    assert not is_blocked("target.yaml", store_dir=tmp_path)


def test_second_consecutive_rollback_blocks(tmp_path):
    record_rollback("target.yaml", store_dir=tmp_path)
    record_rollback("target.yaml", store_dir=tmp_path)
    assert is_blocked("target.yaml", store_dir=tmp_path)


def test_successful_apply_resets_counter(tmp_path):
    record_rollback("target.yaml", store_dir=tmp_path)
    record_apply_success("target.yaml", store_dir=tmp_path)
    record_rollback("target.yaml", store_dir=tmp_path)
    assert not is_blocked("target.yaml", store_dir=tmp_path)


def test_manual_unblock_clears_block(tmp_path):
    record_rollback("x", store_dir=tmp_path)
    record_rollback("x", store_dir=tmp_path)
    assert is_blocked("x", store_dir=tmp_path)
    unblock("x", store_dir=tmp_path)
    assert not is_blocked("x", store_dir=tmp_path)
