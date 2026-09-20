"""Offline decision-projection contracts; stubs do not establish model quality."""
from __future__ import annotations

import json
from pathlib import Path
import sys
import time

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
sys.path.insert(0, str(SCRIPTS))
import jev_context as jev


@pytest.fixture(autouse=True)
def remote_disabled(monkeypatch):
    for name in ('HARNESS_JEV_ALLOW_REMOTE', 'TYPESAFE_API_KEY', 'JEV_MODEL'):
        monkeypatch.delenv(name, raising=False)


def configure(monkeypatch):
    monkeypatch.setenv('HARNESS_JEV_ALLOW_REMOTE', '1')
    monkeypatch.setenv('TYPESAFE_API_KEY', 'offline-fixture-only')
    monkeypatch.setenv('JEV_MODEL', 'offline-fixture')


def candidates(texts):
    units = []
    start = 1
    for index, text in enumerate(texts):
        count = len(jev.lf_lines(text))
        units.append(dict(id=f'u{index}', start=start, end=start + count - 1,
                          kind='text_event', text=text, pinned=False))
        start += count
    return units


def fixture_scores(monkeypatch, relevant=None, critical=None):
    calls = []

    def evaluate(request, **_kwargs):
        calls.append(request)
        values = {key: 0.0 for key in request['questions']}
        values.update({f'{key}_relevant': value for key, value in (relevant or {}).items()})
        values.update({f'{key}_critical': value for key, value in (critical or {}).items()})
        return dict(status='ok', values=values, model='offline-fixture', elapsed_ms=1)

    monkeypatch.setattr(jev, 'evaluate', evaluate)
    return calls


@pytest.mark.parametrize('value', [None, True, False, '0.1', [], {}, float('nan'),
                                  float('inf'), -float('inf'), -0.01, 1.01])
def test_noul_rejects_nonfinite_nonprobability_and_bool(value):
    with pytest.raises(ValueError, match='invalid probability'):
        jev.validate_answers({'answers': {'q': {'type': 'noul', 'noul': value}}}, {'q'})


@pytest.mark.parametrize('response', [None, [], {}, {'answers': []},
    {'answers': {}},
    {'answers': {'q': {'type': 'noul', 'noul': 0}, 'extra': {'type': 'noul', 'noul': 0}}},
    {'answers': {'q': {'type': 'score', 'score': 0}}},
    {'answers': {'q': {'type': 'noul'}}},
    {'answers': {'q': 0.2}},
])
def test_noul_schema_requires_exact_answer_identity(response):
    with pytest.raises(ValueError):
        jev.validate_answers(response, {'q'})


def test_noul_accepts_closed_interval_and_preserves_probability():
    answers = {key: dict(type='noul', noul=value)
               for key, value in {'zero': 0, 'mid': 0.125, 'one': 1}.items()}
    assert jev.validate_answers({'answers': answers}, set(answers)) == {
        'zero': 0.0, 'mid': 0.125, 'one': 1.0}


def test_one_batch_one_call_with_explicit_candidate_binding(monkeypatch):
    configure(monkeypatch)
    calls = fixture_scores(monkeypatch)
    units = candidates(['start\n', 'irrelevant detail\n', 'end\n'])
    result = jev.project_units(units, purpose='retrieval', query='request', enabled=True)
    assert result['status'] == 'applied'
    assert len(calls) == 1
    request = calls[0]
    assert request['state']['query'] == 'request'
    assert request['state'] == {'purpose': 'retrieval', 'query': 'request'}
    assert len(request['questions']) == 2 * len(units)
    for unit in units:
        for kind in ('relevant', 'critical'):
            question = request['questions'][f"{unit['id']}_{kind}"]
            assert question['type'] == 'noul'
            assert question['instructions']['candidate_id'] == unit['id']
            assert question['instructions']['candidate_text'] == unit['text']
            assert 'candidate_text' in question['instructions']['question']
            assert 'untrusted evidence' in question['instructions']['rule']


def test_uncertainty_critical_and_boundary_evidence_survives(monkeypatch):
    configure(monkeypatch)
    fixture_scores(monkeypatch, relevant={'u2': 0.051, 'u3': 0.5}, critical={'u4': 0.4})
    units = candidates(['start\n', 'routine detail\n', 'weak association\n',
                        'ambiguous meaning\n', 'possible dependency\n',
                        'ERROR root cause\n', 'end\n'])
    result = jev.project_units(units, purpose='diagnostics', enabled=True)
    assert result['status'] == 'applied'
    assert result['dropped_ids'] == ['u1']
    assert result['kept_ids'] == ['u0', 'u2', 'u3', 'u4', 'u5', 'u6']
    assert result['text'] == ''.join(u['text'] for u in units if u['id'] != 'u1')


def test_protected_budget_overflow_restores_entire_original(monkeypatch):
    configure(monkeypatch)
    fixture_scores(monkeypatch, relevant={'u2': 0.5})
    units = candidates(['start\rprogress\n', 'optional\n', 'uncertain\n', 'end\n'])
    result = jev.project_units(units, purpose='diagnostics', enabled=True, max_chars=1)
    assert result['status'] == 'fallback'
    assert result['reason'] == 'protected_budget_overflow'
    assert result['text'] == ''.join(u['text'] for u in units)
    assert result['dropped_ids'] == []


@pytest.mark.parametrize(('setting', 'text', 'query', 'reason'), [
    ('disabled', 'safe\n', '', 'disabled'),
    ('no_remote', 'safe\n', '', 'remote_not_authorized'),
    ('no_key', 'safe\n', '', 'not_configured'),
    ('configured', 'password=fixture-only-value\n', '', 'sensitive_input'),
    ('configured', 'safe\n', 'Authorization: Bearer fixture-only-value', 'sensitive_input'),
])
def test_privacy_and_configuration_gates_never_invoke_evaluator(monkeypatch, setting, text, query, reason):
    configure(monkeypatch)
    for case, name in [('no_remote', 'HARNESS_JEV_ALLOW_REMOTE'),
                       ('no_key', 'TYPESAFE_API_KEY'), ('no_model', 'JEV_MODEL')]:
        if setting == case:
            monkeypatch.delenv(name)

    def forbidden(_request, **_kwargs):
        pytest.fail('remote evaluator was invoked despite a closed gate')

    monkeypatch.setattr(jev, 'evaluate', forbidden)
    result = jev.project_text(text, purpose='retrieval', query=query, enabled=setting != 'disabled')
    assert result['reason'] == reason
    assert result['text'] == text


def test_candidate_budget_refuses_entire_batch_before_evaluation(monkeypatch):
    configure(monkeypatch)
    calls = fixture_scores(monkeypatch)
    units = candidates(['line\n'] * (jev.MAX_UNITS + 1))
    result = jev.project_units(units, purpose='diagnostics', enabled=True)
    assert result['reason'] == 'candidate_budget'
    assert result['text'] == ''.join(u['text'] for u in units)
    assert calls == []


@pytest.mark.parametrize('failure', ['timeout', 'exception'])
def test_transport_failure_is_exact_original_text(monkeypatch, failure):
    configure(monkeypatch)
    text = 'first\rprogress\n\n## detail\nordinary content\n\nlast\u2028segment'

    def fail(_request, **_kwargs):
        if failure == 'exception':
            raise TimeoutError('offline fixture')
        return dict(status='fallback', reason='deadline')

    monkeypatch.setattr(jev, 'evaluate', fail)
    result = jev.project_text(text, purpose='diagnostics', enabled=True)
    assert result['status'] == 'fallback'
    assert result['text'] == text
    assert result['dropped_ids'] == []


def test_physical_lines_follow_only_lf():
    text = 'progress\rnext\n\n## section\nalpha\u2028beta\vlast\nfinal\r'
    lines = jev.lf_lines(text)
    assert lines == ['progress\rnext\n', '\n', '## section\n', 'alpha\u2028beta\vlast\n', 'final\r']
    units = jev.split_units(text)
    assert ''.join(unit['text'] for unit in units) == text
    for unit in units:
        assert unit['text'] == ''.join(lines[unit['start'] - 1:unit['end']])


def test_python_module_keeps_imports_decorators_and_dependency_together():
    text = 'from functools import cache\n\n@cache\ndef dependent(x):\n    return helper(x)\n\ndef helper(x):\n    return x + 1\n'
    units = jev.split_units(text)
    assert len(units) == 1
    assert units[0]['kind'] == 'python_ast_module'
    assert units[0]['pinned']
    assert units[0]['text'] == text


def test_python_fence_is_indivisible_in_surrounding_prose():
    fence = '~~~python\nimport math\n\ndef f(x):\n    return math.sqrt(x)\n~~~\n'
    text = 'intro\n\n' + fence + '\nending\n'
    units = jev.split_units(text)
    protected = [unit for unit in units if unit['kind'] == 'python_ast_fence']
    assert len(protected) == 1
    assert protected[0]['text'] == fence
    assert protected[0]['pinned']
    assert ''.join(unit['text'] for unit in units) == text


def test_diff_preserves_file_metadata_and_all_hunks():
    first = ('diff --git a/old.py b/new.py\nsimilarity index 70%\nrename from old.py\nrename to new.py\n'
             '--- a/old.py\n+++ b/new.py\n@@ -1 +1 @@\n-old\n+new\n'
             '@@ -10 +10 @@\n-before\n+after\n')
    second = 'diff --git a/t.py b/t.py\n--- a/t.py\n+++ b/t.py\n@@ -1 +1 @@\n-a\n+b\n'
    units = jev.split_units(first + second)
    assert [unit['text'] for unit in units] == [first, second]
    assert all(unit['kind'] == 'diff_file' and unit['pinned'] for unit in units)


def test_chained_traceback_keeps_terminal_root_cause_until_next_event():
    traceback = ('Traceback (most recent call last):\n  File "x.py", line 2, in x\n'
                 '    missing()\nNameError: missing\n\nDuring handling of the above exception, '
                 'another exception occurred:\n\nTraceback (most recent call last):\n'
                 '  File "x.py", line 4, in x\n    raise RuntimeError("root cause")\nRuntimeError: root cause\n')
    units = jev.split_units('2026-09-20T00:00:00 start\n' + traceback + '2026-09-20T00:00:01 INFO done\n')
    matches = [unit for unit in units if unit['kind'] == 'traceback']
    assert len(matches) == 1
    assert matches[0]['text'] == traceback
    assert matches[0]['pinned']


def small_request():
    return jev.build_request(candidates(['first\n']), 'retrieval', '', 'offline-fixture')


@pytest.mark.parametrize('code', [
    'import time; time.sleep(2)',
    'import os,time\nfor _ in range(100):\n os.write(1,b"x"); time.sleep(.02)',
    'import os,time; os.close(1); os.close(2); time.sleep(2)',
])
def test_real_worker_total_deadline_covers_sleep_slow_body_and_closed_pipes(code, record_property):
    start = time.monotonic()
    result = jev.evaluate(small_request(), worker_argv=[sys.executable, '-c', code])
    elapsed = time.monotonic() - start
    record_property('observed_wall_seconds', elapsed)
    assert result == {'status': 'fallback', 'reason': 'deadline'}
    assert elapsed < 0.45, f'full call took {elapsed:.6f}s'


@pytest.mark.parametrize(('body', 'reason'), [
    ('{"answers":{"u0_relevant":{"type":"noul","noul":0},"u0_relevant":{"type":"noul","noul":1}}}',
     'invalid_response_or_transport'),
    ('not json', 'invalid_response_or_transport'),
    ('x' * (jev.MAX_RESPONSE_BYTES + 1), 'response_budget'),
], ids=['duplicate-json-key', 'not-json', 'response-budget'])
def test_real_worker_invalid_or_oversized_response_fails_open(body, reason):
    code = f'import sys; sys.stdout.write({body!r})'
    result = jev.evaluate(small_request(), worker_argv=[sys.executable, '-c', code])
    assert result == dict(status='fallback', reason=reason)


def test_real_worker_nonzero_exit_is_provider_failure():
    result = jev.evaluate(small_request(), worker_argv=[sys.executable, '-c', 'raise SystemExit(7)'])
    assert result == dict(status='fallback', reason='provider_unavailable')


def test_real_worker_valid_response_and_request_identity():
    request = small_request()
    response = {'model': 'offline-fixture', 'answers': {
        key: dict(type='noul', noul=0.25) for key in request['questions']}}
    code = f'import sys; sys.stdin.buffer.read(); print({json.dumps(response)!r})'
    result = jev.evaluate(request, worker_argv=[sys.executable, '-c', code])
    assert result['status'] == 'ok'
    assert result['values'] == dict.fromkeys(request['questions'], 0.25)
    assert len(result['request_sha256']) == 64


def test_worker_does_not_inherit_unrelated_client_secrets(monkeypatch):
    configure(monkeypatch)
    monkeypatch.setenv('FAKE_OTHER_PROVIDER_SECRET', 'must-stay-in-parent')
    request = small_request()
    response = {'answers': {key: dict(type='noul', noul=0.25) for key in request['questions']}}
    code = ('import os,sys\nassert "FAKE_OTHER_PROVIDER_SECRET" not in os.environ\n'
            'assert os.environ["TYPESAFE_API_KEY"] == "offline-fixture-only"\n'
            'sys.stdin.buffer.read()\n' + f'print({json.dumps(response)!r})')
    result = jev.evaluate(request, worker_argv=[sys.executable, '-c', code])
    assert result['status'] == 'ok'


def test_projection_preparation_and_worker_share_one_deadline(monkeypatch, record_property):
    configure(monkeypatch)
    original_split = jev.split_units
    original_evaluate = jev.evaluate

    def slow_split(text):
        time.sleep(0.15)
        return original_split(text)

    def local_worker(request, **kwargs):
        return original_evaluate(request, worker_argv=[sys.executable, '-c',
                                 'import time; time.sleep(2)'], **kwargs)

    monkeypatch.setattr(jev, 'split_units', slow_split)
    monkeypatch.setattr(jev, 'evaluate', local_worker)
    text = 'first\n\n## detail\nroutine\n\nlast\n'
    start = time.monotonic()
    result = jev.project_text(text, purpose='diagnostics', enabled=True)
    elapsed = time.monotonic() - start
    record_property('observed_wall_seconds', elapsed)
    assert result['reason'] == 'deadline'
    assert result['text'] == text
    assert elapsed < 0.45, f'parse + worker took {elapsed:.6f}s'


def test_request_budget_prevents_worker_creation(monkeypatch):
    def forbidden(*_args, **_kwargs):
        pytest.fail('oversized request spawned a worker')

    monkeypatch.setattr(jev, 'run_bytes', forbidden)
    request = small_request()
    request['state']['query'] = 'x' * jev.MAX_REQUEST_BYTES
    assert jev.evaluate(request) == dict(status='fallback', reason='request_budget')


def test_advisory_worker_uses_bounded_reap_budget_and_discards_unknown_exit(monkeypatch):
    from harness_runtime import Result
    options = []

    def timed_out(_argv, **kwargs):
        options.append(kwargs)
        return Result(returncode=None, stdout=b'', stderr=b'', reason='timeout',
                      observed_bytes=0, elapsed=0.28)

    monkeypatch.setattr(jev, 'run_bytes', timed_out)
    assert jev.evaluate(small_request()) == dict(status='fallback', reason='deadline')
    assert len(options) == 1
    assert 0 < options[0]['kill_wait'] <= 0.005


def test_per_question_context_budget_blocks_before_worker(monkeypatch):
    def forbidden(*_args, **_kwargs):
        pytest.fail('oversized state plus question must not spawn a worker')
    monkeypatch.setattr(jev, 'run_bytes', forbidden)
    request = {'model': 'offline-fixture', 'state': 's' * 12000,
               'questions': {'q': {'type': 'noul', 'instructions': 'q' * 18000}}}
    result = jev.evaluate(request)
    assert result == {'status': 'fallback', 'reason': 'question_budget'}


def test_default_sized_cass_pack_fits_one_atomic_question_batch(monkeypatch):
    from types import SimpleNamespace
    units = candidates(['x' * 1600 + '\n' for _ in range(24)])
    request = jev.build_request(units, 'retrieval', 'query', 'offline-fixture')
    calls = []
    def worker(_argv, **kwargs):
        calls.append(kwargs)
        received = json.loads(kwargs['input_bytes'])
        assert len(received['questions']) == 48
        answers = {key: {'type': 'noul', 'noul': 0.5} for key in received['questions']}
        return SimpleNamespace(reason=None, returncode=0,
                               stdout=json.dumps({'answers': answers}).encode())
    monkeypatch.setattr(jev, 'run_bytes', worker)
    result = jev.evaluate(request)
    assert result['status'] == 'ok'
    assert len(calls) == 1
    assert len(calls[0]['input_bytes']) <= jev.MAX_REQUEST_BYTES
