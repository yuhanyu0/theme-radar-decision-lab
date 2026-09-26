"""Runner qualification. Synthetic fixtures below test plumbing, not investment value."""
import importlib
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).parent


def runner():
    name = 'experiments.repricing_graph_v0_1.run_shadow'
    assert importlib.util.find_spec(name) is not None, 'shadow runner is not implemented'
    return importlib.import_module(name)


def test_real_capture_does_not_invent_our_estimate():
    from experiments.repricing_graph_v0_1.case_io import load_shadow_case
    c = load_shadow_case(ROOT / 'cases/ETN_20260926_capture.yaml')
    assert c.our_expectation is None
    assert c.market_expectation.method.value == 'COMPANY_GUIDANCE'
    assert c.market_expectation.confidence is None
    assert not c.scenarios


def test_runner_exports_provenance_not_synthetic_tape(tmp_path):
    m = runner()
    # The real market directory is external to the production source. No fallback.
    with pytest.raises((FileNotFoundError, ValueError)):
        m.build_report(ROOT / 'cases/ETN_20260926_capture.yaml',
                       ROOT / 'datacenter_etn_template.yaml', tmp_path)


def test_runner_refuses_source_sha_mismatch(tmp_path):
    m = runner()
    (tmp_path / 'receipt.json').write_text(json.dumps({'retrieved_at': '2026-09-26T07:20:14Z',
        'symbols': {'ETN': {'status': 'FETCHED', 'sha256': '0' * 64}}}))
    (tmp_path / 'ETN.csv').write_text('deliberately altered')
    with pytest.raises(ValueError, match='hash'):
        m.read_market(tmp_path)
