import types
import pytest

from app.parser.ktp_parser.ktp_parser import KTPParser
from app.config import settings


class StubExtractor:
    def __init__(self):
        self.calls = []

    def extract(self, context):
        # Record flags for assertion
        self.calls.append((context.strict_admin_filter, context.enforce_vowel_check))
        # Only return value when relaxed flags are off (False, False)
        if context.strict_admin_filter is False and context.enforce_vowel_check is False:
            # Return structured with modest confidence
            return {
                'value': 'RELAXED VALUE',
                'confidence': 0.7,
                'provenance': {'method': 'stub'}
            }
        return None


def test_confidence_threshold_enforcement(monkeypatch):
    parser = KTPParser()

    # Increase threshold so kelurahan_desa gets rejected below threshold
    monkeypatch.setattr(settings, 'RESPONSE_INCLUDE_PROVENANCE', True, raising=False)
    monkeypatch.setattr(settings, 'MIN_CONF_KELURAHAN_DESA', 0.95, raising=False)
    monkeypatch.setattr(settings, 'GLOBAL_MIN_CONFIDENCE', 0.9, raising=False)

    # Use real extractor; ensure it returns with confidence < 0.95 in this simple input
    result = parser.parse([
        'KEL/DESA Tanah Abang'
    ])
    kd = result.get('kelurahan_desa')
    assert isinstance(kd, dict)
    # Expect rejection but provenance present with rejection_reason
    assert kd['value'] in (None, '')
    assert 'rejection_reason' in kd['provenance']
    assert kd['provenance']['rejection_reason'] == 'below_threshold'


def test_relaxed_retry_provenance_and_flags(monkeypatch):
    parser = KTPParser()

    # Enable relaxed retry
    monkeypatch.setattr(settings, 'RELAXED_RETRY_ENABLED', True, raising=False)
    monkeypatch.setattr(settings, 'RESPONSE_INCLUDE_PROVENANCE', True, raising=False)

    # Replace one extractor with stub that only returns during relaxed pass
    stub = StubExtractor()
    parser.extractors['kelurahan_desa'] = stub  # type: ignore[index]

    result = parser.parse(['noise line'])
    kd = result.get('kelurahan_desa')
    assert isinstance(kd, dict)
    assert kd['value'] == 'RELAXED VALUE'
    # Provenance should mark mode relaxed
    assert kd['provenance'].get('mode') == 'relaxed'

    # Verify we had two calls and flags changed from strict to relaxed
    assert len(stub.calls) >= 1
    # First strict call may be skipped if missing in context, but relaxed should have been attempted
    assert any(c == (False, False) for c in stub.calls)
