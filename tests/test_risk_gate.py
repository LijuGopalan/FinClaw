from skills.enhanced_scan import is_confirmed_buy


def _candidate(risk_gate=None):
    return {
        "ticker": "TEST",
        "action": "BUY WATCH",
        "score": 80,
        "redteam_verdict": "PASS",
        "redteam_risk_score": 2,
        "risk_gate": risk_gate,
    }


def test_llm_approval_cannot_bypass_deterministic_risk_gate():
    assert not is_confirmed_buy(_candidate())
    assert not is_confirmed_buy(_candidate({"passed": False, "vetoes": ["stale"]}))
    assert is_confirmed_buy(_candidate({"passed": True, "vetoes": []}))
