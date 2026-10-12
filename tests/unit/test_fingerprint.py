"""Tests for configuration fingerprint determinism."""

from core.kernel.fingerprint import (
    configuration_fingerprint,
    content_hash,
    payload_hash,
)


class TestConfigurationFingerprint:
    def _base_args(self) -> dict:
        return dict(
            core_version="1.0.0",
            agent_version_id="agv_abc",
            contract_version="1.0",
            model_id="mdl_xyz",
            resource_limits={
                "max_duration_seconds": 1800,
                "max_model_calls": 100,
            },
            task_input_hash="deadbeef",
        )

    def test_fingerprint_deterministic(self):
        args = self._base_args()
        assert configuration_fingerprint(**args) == configuration_fingerprint(**args)

    def test_fingerprint_order_independent(self):
        args = self._base_args()
        args["resource_limits"] = {
            "max_model_calls": 100,
            "max_duration_seconds": 1800,
        }
        expected = configuration_fingerprint(**self._base_args())
        assert configuration_fingerprint(**args) == expected

    def test_fingerprint_changes_when_core_version_changes(self):
        a = configuration_fingerprint(**self._base_args())
        args = self._base_args()
        args["core_version"] = "1.0.1"
        b = configuration_fingerprint(**args)
        assert a != b

    def test_fingerprint_changes_when_agent_version_changes(self):
        a = configuration_fingerprint(**self._base_args())
        args = self._base_args()
        args["agent_version_id"] = "agv_different"
        b = configuration_fingerprint(**args)
        assert a != b

    def test_fingerprint_produces_hex_sha256(self):
        fp = configuration_fingerprint(**self._base_args())
        assert len(fp) == 64
        int(fp, 16)


class TestContentHash:
    def test_content_hash_string(self):
        h = content_hash("hello")
        assert len(h) == 64

    def test_content_hash_bytes_matches_string(self):
        assert content_hash("hello") == content_hash(b"hello")

    def test_content_hash_differs_by_content(self):
        assert content_hash("a") != content_hash("b")


class TestPayloadHash:
    def test_payload_hash_order_independent(self):
        a = payload_hash({"x": 1, "y": 2})
        b = payload_hash({"y": 2, "x": 1})
        assert a == b

    def test_payload_hash_differs_by_content(self):
        a = payload_hash({"x": 1})
        b = payload_hash({"x": 2})
        assert a != b