"""Offline CLI regression coverage for typed judgments and branch-local escalation."""
from __future__ import annotations

import contextlib
import copy
import importlib.util
import io
import json
from pathlib import Path
import sys
import time
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import jev_context as jev


@pytest.fixture(autouse=True)
def offline_environment(monkeypatch, tmp_path):
    for name in ('TYPESAFE_API_KEY', 'HARNESS_JEV_ALLOW_REMOTE', 'JEV_MODEL'):
        monkeypatch.delenv(name, raising=False)
    evidence = tmp_path.resolve() / 'evidence'
    evidence.mkdir(mode=0o700)
    monkeypatch.setenv('HARNESS_JEV_EVIDENCE_DIR', str(evidence))


def configured(monkeypatch):
    monkeypatch.setenv('TYPESAFE_API_KEY', 'offline-fixture-only')
    monkeypatch.setenv('HARNESS_JEV_ALLOW_REMOTE', '1')


def load_cli():
    spec = importlib.util.spec_from_file_location('ask_jev_batch_test_cli', ROOT / 'scripts' / 'ask_jev.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def invoke(monkeypatch, argv, raw='supplied evidence\n', *, expected_code=0, cli=None):
    module = cli or load_cli()
    stream = io.TextIOWrapper(io.BytesIO(raw.encode('utf-8')), encoding='utf-8', newline='')
    monkeypatch.setattr(sys, 'stdin', stream)
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = module.main(argv)
        except SystemExit as exc:
            code = exc.code
    assert code == expected_code, (out.getvalue(), err.getvalue())
    assert err.getvalue() == ''
    result = json.loads(out.getvalue())
    assert result['schema'] == 'ask-jev.v1'
    assert result['mode'] == argv[0]
    return result


def batch_document():
    return {
        'state': {'observed': {'tests': 'failed', 'count': 17}, 'notes': ['中文', False, None]},
        'questions': {
            'failed': {'type': 'noul', 'instructions': 'Did state.observed.tests report failure?'},
            'route': {'type': 'choice', 'instructions': {'question': 'Select the next step'},
                      'criteria': {'inspect': 'Inspect the failure', 'continue': 'Continue normally'}},
            'severity': {'type': 'score', 'instructions': 'Assess severity',
                         'criteria': ['low', 'medium', 'high']},
        },
    }


def arguments(mode):
    if mode == 'score':
        return ['score', '--question', 'Assess severity', '--level', 'low',
                '--level', 'medium', '--level', 'high']
    if mode == 'check':
        return ['check', '--question', 'Does the evidence support success?']
    if mode == 'choose':
        return ['choose', '--question', 'Choose a next step', '--option', 'inspect', '--option', 'continue']
    return [mode]


def assert_escalation(result, reason=None):
    assert result['escalation'] == {
        'required': reason is not None,
        'target': 'primary_model' if reason else None,
        'reason': reason,
    }


def fixture_transport(monkeypatch, *, outcome='success', noul=.97, confidence=.97,
                      score_probabilities=(.1, .8, .1)):
    """The actual evaluator receives a network-free child worker, never the API."""
    native_evaluate = jev.evaluate
    calls = []
    if outcome == 'timeout':
        code = 'import time; time.sleep(10)'
    elif outcome == '402':
        code = (
            'import sys,urllib.request,urllib.error\n'
            f'sys.path.insert(0,{str(ROOT / "scripts")!r})\n'
            'import jev_context as j\n'
            'class OfflineOpener:\n'
            ' def open(self,*args,**kwargs):\n'
            '  raise urllib.error.HTTPError(j.ENDPOINT,402,"offline",None,None)\n'
            'urllib.request.build_opener=lambda *args,**kwargs: OfflineOpener()\n'
            'raise SystemExit(j._worker())\n'
        )
    else:
        code = (
            'import json,sys\n'
            'request=json.load(sys.stdin); answers={}\n'
            'for key,q in request["questions"].items():\n'
            ' if q["type"]=="noul":\n'
            f'  answers[key]={{"type":"noul","noul":{noul!r}}}\n'
            ' elif q["type"]=="choice":\n'
            '  labels=list(q["criteria"])\n'
            f'  answers[key]={{"type":"choice","choice":labels[0],"confidence":{confidence!r},'
            '"probabilities":{label:.97 if label==labels[0] else .03/(len(labels)-1) for label in labels}}\n'
            ' else:\n'
            f'  probabilities={score_probabilities!r}\n'
            '  answers[key]={"type":"score","score":sum(i*p for i,p in enumerate(probabilities)),\n'
            f'    "confidence":{confidence!r},'
            '"probabilities":{str(i):p for i,p in enumerate(probabilities)},\n'
            '    "legend":{str(i):level for i,level in enumerate(q["criteria"])}}\n'
            'print(json.dumps({"model":"offline-fixture","answers":answers}))\n'
        )

    def evaluate(request, **kwargs):
        calls.append(copy.deepcopy(request))
        return native_evaluate(request, worker_argv=[sys.executable, '-c', code], **kwargs)

    monkeypatch.setattr(jev, 'evaluate', evaluate)
    return calls


def test_heterogeneous_batch_shares_one_state_and_one_request(monkeypatch):
    configured(monkeypatch)
    calls = fixture_transport(monkeypatch)
    document = batch_document()
    result = invoke(monkeypatch, ['batch'], json.dumps(document, ensure_ascii=False))
    assert result['status'] == 'ok'
    assert len(calls) == 1
    assert calls[0]['state'] == document['state']
    assert set(calls[0]['questions']) == set(document['questions'])
    assert result['model'] == 'offline-fixture'
    assert Path(result['receipt']).is_file()
    assert Path(result['evidence_path']).is_file()
    assert 'escalation' not in result
    assert result['decisions']['failed']['answer'] is True
    assert result['decisions']['route']['answer'] == 'inspect'
    assert result['decisions']['severity']['answer'] == pytest.approx(1.)
    for key, decision in result['decisions'].items():
        assert decision['type'] == document['questions'][key]['type']
        assert decision['status'] == 'ok'
        assert decision['advisory'] is True
        assert decision['reason']
        assert 'judgment' in decision
        assert_escalation(decision)


def test_multiple_nouls_are_independent_not_a_normalized_choice(monkeypatch):
    configured(monkeypatch)
    calls = fixture_transport(monkeypatch)
    document = {'state': ['red', 'large'], 'questions': {
        'red': {'type': 'noul', 'instructions': 'Is the object red?'},
        'large': {'type': 'noul', 'instructions': 'Is the object large?'},
    }}
    result = invoke(monkeypatch, ['batch'], json.dumps(document))
    assert len(calls) == 1
    assert [d['answer'] for d in result['decisions'].values()] == [True, True]
    assert sum(d['judgment'] for d in result['decisions'].values()) > 1


@pytest.mark.parametrize('state', ['raw\r\n中文\u2028text', {'big_integer': 2**60 + 1,
                       'nested': [None, True, {'path': 'state.nested[2].path'}]}, ['a', 1, False]])
def test_structured_state_is_not_double_encoded_or_coerced(monkeypatch, state):
    configured(monkeypatch)
    calls = fixture_transport(monkeypatch)
    document = {'state': state, 'questions': {'ok': {'type': 'noul', 'instructions': ['Assess the evidence']}}}
    result = invoke(monkeypatch, ['batch'], json.dumps(document, ensure_ascii=False))
    assert result['status'] == 'ok'
    assert calls[0]['state'] == state
    assert type(calls[0]['state']) is type(state)


@pytest.mark.parametrize(('confidence', 'expected'), [(.97, 1.), (.85, 1.), (.8499, None)])
def test_middle_score_measures_position_independently_from_uncertainty(monkeypatch, confidence, expected):
    configured(monkeypatch)
    calls = fixture_transport(monkeypatch, confidence=confidence)
    raw = 'An ordinary middle-severity observation.\r\n'
    result = invoke(monkeypatch, arguments('score'), raw)
    assert result['answer'] == expected
    assert result['status'] == ('unknown' if expected is None else 'ok')
    assert result['judgment'] == {
        'score': 1., 'normalized_score': .5, 'confidence': confidence,
        'probabilities': {'0': .1, '1': .8, '2': .1},
        'legend': {'0': 'low', '1': 'medium', '2': 'high'},
    }
    assert max(result['judgment']['probabilities'].values()) < .85
    assert_escalation(result, 'uncertain' if expected is None else None)
    assert calls[0]['state'] == raw
    assert calls[0]['questions']['decision']['criteria'] == ['low', 'medium', 'high']


def test_uncertain_unused_branch_does_not_block_other_batch_answers(monkeypatch):
    configured(monkeypatch)
    fixture_transport(monkeypatch, noul=.5)
    result = invoke(monkeypatch, ['batch'], json.dumps(batch_document()))
    assert result['status'] == 'ok'
    assert 'escalation' not in result
    assert result['decisions']['failed']['status'] == 'unknown'
    assert_escalation(result['decisions']['failed'], 'uncertain')
    assert result['decisions']['route']['answer'] == 'inspect'
    assert_escalation(result['decisions']['route'])


@pytest.mark.parametrize(('noul', 'expect', 'expected_reason'), [
    (.02, None, None), (.02, False, None), (.02, True, 'expectation_mismatch'),
    (.98, False, 'expectation_mismatch'), (.98, True, None), (.5, True, 'uncertain'),
])
def test_check_escalates_only_uncertainty_or_explicit_expectation_mismatch(monkeypatch, noul, expect, expected_reason):
    configured(monkeypatch)
    calls = fixture_transport(monkeypatch, noul=noul)
    argv = arguments('check')
    if expect is not None:
        argv += ['--expect', str(expect).lower()]
    result = invoke(monkeypatch, argv)
    assert_escalation(result, expected_reason)
    if expect is not None:
        assert result['expectation'] is expect
    assert 'expect' not in calls[0]['questions']['decision']
    assert 'expectation' not in calls[0]['questions']['decision']


def test_batch_expectations_are_local_and_do_not_bias_provider_input(monkeypatch):
    configured(monkeypatch)
    calls = fixture_transport(monkeypatch, noul=.97)
    document = batch_document()
    document['questions']['failed']['expect'] = False
    result = invoke(monkeypatch, ['batch'], json.dumps(document))
    decision = result['decisions']['failed']
    assert decision['answer'] is True
    assert decision['expectation'] is False
    assert_escalation(decision, 'expectation_mismatch')
    assert 'expect' not in json.dumps(calls[0])


@pytest.mark.parametrize('mode', ['score', 'batch'])
@pytest.mark.parametrize(('key', 'consent'), [(None, None), ('fixture', None), (None, '1'), ('fixture', 'true')])
def test_new_modes_without_exact_gate_do_not_call_transport(monkeypatch, mode, key, consent):
    if key is not None:
        monkeypatch.setenv('TYPESAFE_API_KEY', key)
    if consent is not None:
        monkeypatch.setenv('HARNESS_JEV_ALLOW_REMOTE', consent)

    def forbidden(*args, **kwargs):
        pytest.fail('closed environment gate reached transport')

    monkeypatch.setattr(jev, 'evaluate', forbidden)
    raw = json.dumps(batch_document()) if mode == 'batch' else 'original evidence'
    result = invoke(monkeypatch, arguments(mode), raw)
    assert result['status'] == 'fallback'
    if mode == 'batch':
        assert 'escalation' not in result
        for decision in result['decisions'].values():
            assert decision['status'] == 'fallback'
            assert decision['answer'] is None
            assert_escalation(decision, 'unavailable')
    else:
        assert result['answer'] is None
        assert_escalation(result, 'unavailable')


@pytest.mark.parametrize('mode', ['score', 'batch'])
def test_missing_core_still_produces_silent_new_mode_fallback(monkeypatch, mode):
    cli = load_cli()
    monkeypatch.setattr(cli, 'core', None)
    raw = json.dumps(batch_document()) if mode == 'batch' else 'original evidence'
    result = invoke(monkeypatch, arguments(mode), raw, cli=cli)
    assert result['status'] == 'fallback'
    if mode == 'batch':
        assert set(result['decisions']) == set(batch_document()['questions'])
        assert all(d['answer'] is None for d in result['decisions'].values())
    else:
        assert result['answer'] is None


@pytest.mark.parametrize('mode', ['score', 'batch'])
def test_older_core_without_new_apis_is_still_a_silent_fallback(monkeypatch, mode):
    cli = load_cli()
    monkeypatch.setattr(cli, 'core', SimpleNamespace())
    raw = json.dumps(batch_document()) if mode == 'batch' else 'original evidence'
    result = invoke(monkeypatch, arguments(mode), raw, cli=cli)
    assert result['status'] == 'fallback'
    if mode == 'batch':
        assert all(d['answer'] is None for d in result['decisions'].values())
    else:
        assert result['answer'] is None


@pytest.mark.parametrize('mode', ['score', 'batch'])
def test_new_helper_failure_never_escapes_cli(monkeypatch, mode):
    configured(monkeypatch)

    def fail(*args, **kwargs):
        raise RuntimeError('private diagnostic must not reach the console')

    monkeypatch.setattr(jev, 'ask_questions', fail)
    raw = json.dumps(batch_document()) if mode == 'batch' else 'original evidence'
    result = invoke(monkeypatch, arguments(mode), raw)
    assert result['status'] == 'fallback'
    assert 'private diagnostic' not in json.dumps(result)


@pytest.mark.parametrize('expected', ['true', 'false'])
def test_check_fallback_preserves_explicit_expectation(monkeypatch, expected):
    result = invoke(monkeypatch, arguments('check') + ['--expect', expected])
    assert result['status'] == 'fallback'
    assert result['expectation'] is (expected == 'true')
    assert_escalation(result, 'unavailable')


@pytest.mark.parametrize('mode', ['score', 'batch'])
@pytest.mark.parametrize('outcome', ['402', 'timeout'])
def test_new_modes_http402_and_timeout_preserve_fail_open(monkeypatch, mode, outcome):
    configured(monkeypatch)
    calls = fixture_transport(monkeypatch, outcome=outcome)
    raw = json.dumps(batch_document()) if mode == 'batch' else 'original evidence'
    started = time.monotonic()
    result = invoke(monkeypatch, arguments(mode), raw)
    elapsed = time.monotonic() - started
    assert len(calls) == 1
    assert result['status'] == 'fallback'
    assert 'offline' not in json.dumps(result)
    if mode == 'batch':
        assert all(d['answer'] is None and d['status'] == 'fallback' for d in result['decisions'].values())
    else:
        assert result['answer'] is None
    if outcome == 'timeout':
        assert elapsed < .45


@pytest.mark.parametrize('mode', ['choose', 'check', 'purify'])
def test_legacy_modes_expose_unavailable_signal_and_preserve_native_fallback(monkeypatch, mode):
    raw = 'all original\r\n中文\n'
    result = invoke(monkeypatch, arguments(mode), raw)
    assert result['status'] == 'fallback'
    assert_escalation(result, 'unavailable')
    if mode == 'purify':
        assert result['text'] == raw
    else:
        assert result['answer'] is None


def test_batch_input_file_uses_exact_json_document(monkeypatch, tmp_path):
    configured(monkeypatch)
    calls = fixture_transport(monkeypatch)
    document = batch_document()
    path = tmp_path.resolve() / 'questions.json'
    path.write_text(json.dumps(document), encoding='utf-8')
    result = invoke(monkeypatch, ['batch', '--input-file', str(path)], 'ignored stdin')
    assert result['status'] == 'ok'
    assert calls[0]['state'] == document['state']


BAD_DOCUMENTS = [
    'not-json', '[]', '{}',
    '{"state":"first","state":"second","questions":{}}',
    '{"state":"s","questions":{"q":{"type":"noul","instructions":"a","instructions":"b"}}}',
    '{"state":{"nested":[NaN]},"questions":{"q":{"type":"noul","instructions":"q"}}}',
    '{"state":{"nested":[Infinity]},"questions":{"q":{"type":"noul","instructions":"q"}}}',
    '{"state":{"nested":[1e999]},"questions":{"q":{"type":"noul","instructions":"q"}}}',
    json.dumps({'state': 's', 'questions': {}, 'extra': True}),
    json.dumps({'state': 's', 'questions': {}}),
    json.dumps({'state': True, 'questions': {'q': {'type': 'noul', 'instructions': 'q'}}}),
    json.dumps({'state': 's', 'questions': {'q': {'type': 'other', 'instructions': 'q'}}}),
    json.dumps({'state': 's', 'questions': {'q': {'type': 'noul', 'instructions': 'q', 'expect': 'true'}}}),
    json.dumps({'state': 's', 'questions': {'q': {'type': 'noul', 'instructions': 'q', 'extra': 1}}}),
    json.dumps({'state': 's', 'questions': {'q': {'type': 'score', 'instructions': 'q', 'criteria': ['low']}}}),
    json.dumps({'state': 's', 'questions': {'q': {'type': 'score', 'instructions': 'q',
                                               'criteria': ['low', 'high'], 'expect': True}}}),
    json.dumps({'state': 's', 'questions': {'q': {'type': 'choice', 'instructions': 'q',
                                               'criteria': {'a': None, 'b': None}, 'expect': False}}}),
    json.dumps({'state': 's', 'questions': {f'q{i}': {'type': 'noul', 'instructions': 'q'} for i in range(33)}}),
]


@pytest.mark.parametrize('raw', BAD_DOCUMENTS)
def test_invalid_batch_documents_fail_as_structured_input_errors(monkeypatch, raw):
    def forbidden(*args, **kwargs):
        pytest.fail('invalid request reached transport')

    monkeypatch.setattr(jev, 'evaluate', forbidden)
    result = invoke(monkeypatch, ['batch'], raw, expected_code=64)
    assert result['status'] == 'error'
    assert result['reason']


@pytest.mark.parametrize('raw', [
    '{"state":[1e999],"questions":{"q":{"type":"noul","instructions":"q"}}}',
    '{"state":"s","questions":{"\\ud800":{"type":"noul","instructions":"q"}}}',
    '{"state":"s","questions":{"q":{"type":{"unexpected":"object"},"instructions":"q"}}}',
])
def test_malformed_json_stays_structured_even_without_core(monkeypatch, raw):
    cli = load_cli()
    monkeypatch.setattr(cli, 'core', None)
    result = invoke(monkeypatch, ['batch'], raw, expected_code=64, cli=cli)
    assert result['status'] == 'error'


@pytest.mark.parametrize('levels', [['only'], ['same', 'same'], ['low', ''],
                                  [str(i) for i in range(11)]])
def test_invalid_score_level_sets_are_structured_input_errors(monkeypatch, levels):
    argv = ['score', '--question', 'Assess quality']
    for level in levels:
        argv += ['--level', level]
    result = invoke(monkeypatch, argv, expected_code=64)
    assert result['status'] == 'error'


def test_maximum_batch_has_one_complete_request(monkeypatch):
    configured(monkeypatch)
    calls = fixture_transport(monkeypatch)
    document = {'state': 'bounded evidence', 'questions': {
        f'q{i}': {'type': 'noul', 'instructions': 'Does the evidence support the claim?'} for i in range(32)}}
    result = invoke(monkeypatch, ['batch'], json.dumps(document))
    assert result['status'] == 'ok'
    assert len(calls) == 1
    assert len(calls[0]['questions']) == len(result['decisions']) == 32
