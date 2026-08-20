import pytest

from dronedream_agent_core.evidence import EvidenceChain


def test_evidence_chain_is_hash_linked(tmp_path):
    chain = EvidenceChain(tmp_path / "evidence.jsonl")
    first = chain.append("intent", {"accepted": True})
    second = chain.append("route", {"points": 12})
    records = chain.read()
    assert records == [first, second]
    assert second.previous_record_sha256 == first.record_sha256


def test_evidence_chain_rejects_tampering(tmp_path):
    path = tmp_path / "evidence.jsonl"
    chain = EvidenceChain(path)
    chain.append("intent", {"accepted": True})
    path.write_text(path.read_text().replace("true", "false"), encoding="utf-8")
    with pytest.raises(ValueError, match="hash"):
        chain.read()
