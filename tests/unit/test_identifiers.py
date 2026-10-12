"""Tests for ULID identifier generation and validation."""

from core.storage.identifiers import IdPrefix, new_id, is_valid_id


class TestIdentifiers:
    def test_new_id_has_prefix(self):
        id_ = new_id(IdPrefix.ORGANIZATION)
        assert id_.startswith("org_")

    def test_new_id_is_unique(self):
        ids = {new_id(IdPrefix.TASK) for _ in range(100)}
        assert len(ids) == 100

    def test_is_valid_id_accepts_valid(self):
        id_ = new_id(IdPrefix.EXECUTION)
        assert is_valid_id(id_)
        assert is_valid_id(id_, expected_prefix=IdPrefix.EXECUTION)

    def test_is_valid_id_rejects_wrong_prefix(self):
        id_ = new_id(IdPrefix.EXECUTION)
        assert not is_valid_id(id_, expected_prefix=IdPrefix.AGENT)

    def test_is_valid_id_rejects_garbage(self):
        assert not is_valid_id("not_a_valid_id")
        assert not is_valid_id("")
        assert not is_valid_id("org_notarealulid")