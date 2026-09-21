"""Offline primitive and fan-out contracts; no fixture establishes model accuracy."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import sys
import time

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import jev_context as jev


@pytest.fixture(autouse=True)
def offline_environment(monkeypatch, tmp_path):
    for name in ('HARNESS_JEV_ALLOW_REMOTE', 'TYPESAFE_API_KEY', 'JEV_MODEL'):
        monkeypatch.delenv(name, raising=False)
    evidence = tmp_path.resolve() / 'evidence'
    evidence.mkdir(mode=0o700)
    monkeypatch.setenv('HARNESS_JEV_EVIDENCE_DIR', str(evidence))


def configure(monkeypatch):
    monkeypatch.setenv('HARNESS_JEV_ALLOW_REMOTE', '1')
    monkeypatch.setenv('TYPESAFE_API_KEY', 'offline-fixture-only')


def mixed_questions():
    return {
        'present': {'type': 'noul', 'instructions': 'Does state.ticket describe a broken export?'},
        'urgent': {'type': 'noul', 'instructions': ['Does state.ticket require prompt action?'],
                   'criteria': {'true': 'An urgent issue is reported', 'false': 'No urgency is reported'}},
        'route': {'type': 'choice', 'instructions': {'question': 'Which team handles state.ticket?'},
                  'criteria': {'Engineering': {'owns': ['export']}, 'Support': None}},
        'severity': {'type': 'score', 'instructions': 'Grade the impact of state.ticket.',
                     'criteria': [
                         {'impact': 'Cosmetic', 'examples': ['color']},
                         {'impact': 'Workaround exists', 'examples': ['retry']},
                         {'impact': 'Blocking', 'examples': ['data loss']}]},
    }


def score_answer(criteria=None):
    criteria = criteria or ['Low', 'Medium', 'High']
    return {'type': 'score', 'score': 1.25, 'confidence': 0.9,
            'probabilities': {'0': 0.05, '1': 0.65, '2': 0.3},
            'legend': {str(index): level for index, level in enumerate(criteria)}}


def validate_score(answer, criteria=None):
    questions = {'q': {'type': 'score', 'criteria': criteria or ['Low', 'Medium', 'High']}}
    return jev.validate_answers({'answers': {'q': answer}}, {'q'}, questions)['q']


def test_score_preserves_ordinal_distribution_and_exposes_normalized_mean():
    answer = score_answer()
    result = validate_score(answer)
    assert result == {key: value for key, value in answer.items() if key != 'type'} | {
        'normalized_score': 0.625}


def test_structured_score_legend_matches_levels_deeply_not_object_key_order():
    levels = [{'impact': 'Low', 'examples': ['label']}, ['workaround', 'retry'], {'impact': 'High'}]
    answer = score_answer(levels)
    answer['legend']['0'] = {'examples': ['label'], 'impact': 'Low'}
    assert validate_score(answer, levels)['legend'] == answer['legend']


@pytest.mark.parametrize(('field', 'value'), [
    ('type', 'noul'), ('type', None), ('score', True), ('score', False), ('score', '1.25'),
    ('score', float('nan')), ('score', float('inf')), ('score', -0.01), ('score', 2.01),
    ('score', 10 ** 1000), ('score', 1.0), ('confidence', True), ('confidence', '0.9'),
    ('confidence', float('nan')), ('confidence', float('inf')), ('confidence', -0.01),
    ('confidence', 1.01), ('confidence', 10 ** 1000),
    ('probabilities', {'0': 0.05, '1': 0.65}),
    ('probabilities', {'0': 0.05, '1': 0.65, '2': 0.3, '3': 0.0}),
    ('probabilities', {'0': 0.05, '1': 0.65, '02': 0.3}),
    ('probabilities', {'0': True, '1': 0, '2': 0}),
    ('probabilities', {'0': 0.05, '1': float('nan'), '2': 0.3}),
    ('probabilities', {'0': 0.05, '1': 0.75, '2': 0.3}),
    ('probabilities', {'0': -0.05, '1': 0.75, '2': 0.3}),
    ('probabilities', [0.05, 0.65, 0.3]),
    ('legend', {'0': 'Low', '1': 'Medium'}),
    ('legend', {'0': 'Low', '1': 'Medium', '2': 'High', '3': 'Other'}),
    ('legend', {'0': 'Medium', '1': 'Low', '2': 'High'}),
    ('legend', ['Low', 'Medium', 'High']),
])
def test_score_rejects_invalid_types_incomplete_distributions_and_inconsistent_means(field, value):
    answer = score_answer()
    answer[field] = value
    with pytest.raises(ValueError):
        validate_score(answer)


def test_legend_comparison_does_not_conflate_boolean_and_number():
    levels = [{'value': 1}, {'value': 2}, {'value': 3}]
    answer = score_answer(levels)
    answer['legend']['0'] = {'value': True}
    with pytest.raises(ValueError):
        validate_score(answer, levels)


def test_score_tolerance_is_absolute_and_bounded():
    answer = score_answer()
    answer['score'] += 0.000009
    assert validate_score(answer)['score'] == answer['score']
    answer['score'] += 0.000002
    with pytest.raises(ValueError):
        validate_score(answer)


def test_mixed_answers_keep_independent_nouls_without_normalization():
    questions = mixed_questions()
    answers = {
        'present': {'type': 'noul', 'noul': 0.9},
        'urgent': {'type': 'noul', 'noul': 0.8},
        'route': {'type': 'choice', 'choice': 'Engineering', 'confidence': 0.95,
                  'probabilities': {'Engineering': 0.98, 'Support': 0.02}},
        'severity': score_answer(questions['severity']['criteria']),
    }
    values = jev.validate_answers({'answers': answers}, set(questions), questions)
    assert values['present'] + values['urgent'] == pytest.approx(1.7)
    assert values['route']['choice'] == 'Engineering'
    assert values['severity']['normalized_score'] == 0.625


def test_unknown_question_type_cannot_be_interpreted_as_noul():
    with pytest.raises(ValueError, match='unknown question type'):
        jev.validate_answers({'answers': {'q': {'type': 'noul', 'noul': 0.9}}},
                             {'q'}, {'q': {'type': 'unknown'}})


def test_prepare_preserves_structured_state_paths_and_does_not_mutate_inputs():
    state = {'ticket': {'subject': 'export broken'}, 'metadata': [1, None, True]}
    questions = mixed_questions()
    originals = copy.deepcopy((state, questions))
    wire = jev.prepare_questions(state, questions)
    assert (state, questions) == originals
    assert wire == questions
    assert list(wire) == list(questions)
    wire['severity']['criteria'][0]['examples'].append('new example')
    assert (state, questions) == originals


def test_structured_instruction_local_paths_are_not_moved_by_an_implicit_wrapper():
    questions = {'same_person': {
        'type': 'noul',
        'instructions': {
            'potential_duplicate': {'name': 'John Smith', 'location': 'Oakland'},
            'question': 'Is the resume for the same person as `potential_duplicate`?'},
        'criteria': {'true': {'match': 'Same person'}, 'false': ['Different person', 'Not established']}}}
    wire = jev.prepare_questions({'resume': 'John Smith, Oakland'}, questions)
    assert wire == questions
    assert wire is not questions
    assert wire['same_person']['instructions'] is not questions['same_person']['instructions']


@pytest.mark.parametrize('state', ['', ' \n', {}, [], None, False, True, 42, 0.5])
def test_prepare_rejects_empty_or_nonstate_values(state):
    with pytest.raises(ValueError, match='invalid_state'):
        jev.prepare_questions(state, mixed_questions())


@pytest.mark.parametrize('state', [
    {'v': float('nan')}, [float('inf')], {1: 'nonstring key'}, {'a': (1, 2)},
    {'a': {1, 2}}, {'a': b'bytes'}, {'a': object()},
])
def test_prepare_rejects_non_json_nested_state(state):
    with pytest.raises(ValueError, match='invalid_json'):
        jev.prepare_questions(state, mixed_questions())


def test_prepare_rejects_cyclic_state_without_unbounded_traversal():
    state = []
    state.append(state)
    with pytest.raises(ValueError, match='invalid_json'):
        jev.prepare_questions(state, mixed_questions())


@pytest.mark.parametrize('questions', [None, [], {}, {'q' + str(i): {'type': 'noul', 'instructions': 'Q?'}
                                                   for i in range(33)}])
def test_prepare_rejects_invalid_or_oversized_question_maps(questions):
    with pytest.raises(ValueError, match='invalid_questions'):
        jev.prepare_questions('evidence', questions)


@pytest.mark.parametrize('ident', ['', '0q', 'two words', '中文', 'x' * 65, '../q', 'q\n'])
def test_prepare_rejects_unstable_question_identities(ident):
    with pytest.raises(ValueError, match='invalid_question_id'):
        jev.prepare_questions('evidence', {ident: {'type': 'noul', 'instructions': 'Q?'}})


@pytest.mark.parametrize('question', [
    None, [], {'type': 'unknown', 'instructions': 'Q?'},
    {'type': 'noul', 'instructions': 'Q?', 'model': 'override'},
    {'type': 'noul', 'instructions': 'Q?', 'endpoint': 'https://example.invalid'},
    {'type': 'noul', 'instructions': 'Q?', 'expect': True},
    {'instructions': 'Q?'},
])
def test_prepare_rejects_extra_configuration_and_unknown_question_shapes(question):
    with pytest.raises(ValueError, match='invalid_question'):
        jev.prepare_questions('evidence', {'q': question})


@pytest.mark.parametrize('instructions', ['', ' ', [], {}, None, True, 1, 'x' * 4095])
def test_prepare_requires_nonempty_bounded_structured_instructions(instructions):
    with pytest.raises(ValueError, match='invalid_instructions'):
        jev.prepare_questions('evidence', {'q': {'type': 'noul', 'instructions': instructions}})


@pytest.mark.parametrize('kind,criteria', [
    ('choice', {}), ('choice', {'one': None}), ('choice', ['one', 'two']),
    ('choice', {'one': True, 'two': None}), ('choice', {'one': 1, 'two': None}),
    ('choice', {'one': '', 'two': None}), ('choice', {'one': {}, 'two': None}),
    ('choice', {'one\n': None, 'two': None}), ('choice', {'one\u2028two': None, 'three': None}),
    ('choice', {'x' * 129: None, 'two': None}), ('choice', {' ': None, 'two': None}),
    ('choice', {f'c{i}': None for i in range(256)}),
    ('score', ['one']), ('score', ['one', 'one']), ('score', ['one', False]),
    ('score', ['one', '']), ('score', ['one', {}]), ('score', ['one', []]),
    ('score', list(range(3))), ('score', [str(i) for i in range(11)]),
    ('score', [{'x': 'one', 'y': 'two'}, {'y': 'two', 'x': 'one'}]),
    ('noul', None), ('noul', {}), ('noul', {'true': 'yes'}),
    ('noul', {'true': 'yes', 'false': 'no', 'other': 'unknown'}),
    ('noul', {'true': '', 'false': 'no'}), ('noul', {'true': True, 'false': False}),
])
def test_prepare_rejects_invalid_primitive_criteria(kind, criteria):
    with pytest.raises(ValueError, match=f'invalid_{kind}_criteria'):
        jev.prepare_questions('evidence', {'q': {'type': kind, 'instructions': 'Q?', 'criteria': criteria}})


def test_maximum_supported_choice_score_and_question_counts():
    questions = {f'q{i}': {'type': 'noul', 'instructions': 'Q?'} for i in range(30)}
    questions['choice'] = {'type': 'choice', 'instructions': 'Which?',
                           'criteria': {f'候选{i}': None for i in range(255)}}
    questions['score'] = {'type': 'score', 'instructions': 'How much?',
                          'criteria': [f'Level {i}' for i in range(10)]}
    assert len(jev.prepare_questions('evidence', questions)) == 32


@pytest.mark.parametrize('key,consent', [(None, None), ('fixture', None), (None, '1'), ('fixture', '0')])
def test_environment_gate_precedes_validation_storage_and_transport(monkeypatch, key, consent):
    if key is not None:
        monkeypatch.setenv('TYPESAFE_API_KEY', key)
    if consent is not None:
        monkeypatch.setenv('HARNESS_JEV_ALLOW_REMOTE', consent)
    def forbidden(*_args, **_kwargs):
        pytest.fail('closed gate invoked the pipeline')
    monkeypatch.setattr(jev, 'prepare_questions', forbidden)
    monkeypatch.setattr(jev, '_evaluate_evidenced', forbidden)
    assert jev.ask_questions(None, {}) is None


@pytest.mark.parametrize('state', [
    'Authorization: Bearer fixture-only-value',
    {'api_key': 'fixture-only-value'},
    {'account': {'password': 'fixture-only-value'}},
    {'headers': {'Authorization': 'Bearer fixture-only-value'}},
    {'api_key': ['fixture-only-value']},
    {'api_key': {'value': 'fixture-only-value'}},
    {'Authorization': ['Bearer fixture-only-value']},
    {'request': ['client_secret=fixture-only-value']},
])
def test_sensitive_structured_keys_and_nested_text_fail_open_before_storage(monkeypatch, state):
    configure(monkeypatch)
    def forbidden(*_args, **_kwargs):
        pytest.fail('sensitive input reached evidence or network')
    monkeypatch.setattr(jev, '_evaluate_evidenced', forbidden)
    assert jev.ask_questions(state, mixed_questions()) is None


def test_normal_nested_containers_do_not_acquire_sensitive_field_meaning():
    assert not jev._sensitive_json({
        'ticket': {'details': ['An ordinary support question', {'value': 'fixture-only-value'}]},
        'headers': {'Content-Type': ['application/json']},
    })


def test_one_shared_deadline_starts_before_validation_and_evidence(monkeypatch):
    configure(monkeypatch)
    clock = [100.0]
    monkeypatch.setattr(jev.time, 'monotonic', lambda: clock[0])
    original_prepare = jev.prepare_questions
    def prepare(*args):
        clock[0] += 0.1
        return original_prepare(*args)
    monkeypatch.setattr(jev, 'prepare_questions', prepare)
    observed = []
    def pipeline(request, evidence, source, total, evaluated, deadline):
        observed.append((request, evidence, source, total, evaluated, deadline))
        return {'result': 'fixture'}
    monkeypatch.setattr(jev, '_evaluate_evidenced', pipeline)
    state, questions = {'ticket': 'export broken'}, mixed_questions()
    assert jev.ask_questions(state, questions) == {'result': 'fixture'}
    assert len(observed) == 1
    request, evidence, source, total, evaluated, deadline = observed[0]
    assert deadline == pytest.approx(100.28)
    assert (source, total, evaluated) == ('ask-jev', 4, 4)
    assert evidence == {'state': state, 'questions': questions}
    assert request['state'] is state
    assert request['model'] == jev.DEFAULT_MODEL
    assert request['questions'] == questions


def test_expired_validation_budget_does_not_start_pipeline(monkeypatch):
    configure(monkeypatch)
    ticks = iter([0.0, 0.281])
    monkeypatch.setattr(jev.time, 'monotonic', lambda: next(ticks))
    monkeypatch.setattr(jev, '_evaluate_evidenced', lambda *_a, **_k: pytest.fail('expired budget'))
    assert jev.ask_questions('evidence', mixed_questions()) is None


def install_worker(monkeypatch, outcome):
    production = jev.evaluate
    calls = []
    if outcome in ('401', '402', '429', 'offline'):
        failure = ('urllib.error.URLError("offline")' if outcome == 'offline' else
                   f'urllib.error.HTTPError(j.ENDPOINT,{int(outcome)},"offline",None,None)')
        code = ('import sys,urllib.error,urllib.request\n'
                f'sys.path.insert(0,{str(ROOT / "scripts")!r})\n'
                'import jev_context as j\n'
                'class Opener:\n'
                ' def open(self,*args,**kwargs):\n'
                f'  raise {failure}\n'
                'urllib.request.build_opener=lambda *args,**kwargs:Opener()\n'
                'raise SystemExit(j._worker())\n')
    elif outcome == 'timeout':
        code = 'import time; time.sleep(10)'
    elif outcome == 'duplicate':
        code = 'print(\'{"answers":{"present":{"type":"noul","noul":0.9,"noul":0.1}}}\')'
    elif outcome == 'malformed':
        code = 'print("not JSON")'
    else:
        code = ('import json,sys\n'
                'request=json.load(sys.stdin)\n'
                'answers={}\n'
                'for key,q in request["questions"].items():\n'
                ' if q["type"]=="noul":\n'
                '  answers[key]={"type":"noul","noul":0.9}\n'
                ' elif q["type"]=="choice":\n'
                '  names=list(q["criteria"])\n'
                '  answers[key]={"type":"choice","choice":names[0],"confidence":0.99,'
                '"probabilities":{name:1.0 if name==names[0] else 0.0 for name in names}}\n'
                ' else:\n'
                '  levels=q["criteria"]\n'
                '  answers[key]={"type":"score","score":1.0,"confidence":0.95,'
                '"probabilities":{str(i):1.0 if i==1 else 0.0 for i in range(len(levels))},'
                '"legend":{str(i):v for i,v in enumerate(levels)}}\n'
                'print(json.dumps({"answers":answers,"model":"offline-fixture"}))\n')
    def evaluate(request, **kwargs):
        calls.append((copy.deepcopy(request), kwargs.copy()))
        return production(request, worker_argv=[sys.executable, '-c', code], **kwargs)
    monkeypatch.setattr(jev, 'evaluate', evaluate)
    return calls


def test_mixed_fanout_uses_one_worker_and_archives_original_state_questions(monkeypatch, capsys):
    configure(monkeypatch)
    calls = install_worker(monkeypatch, 'success')
    questions = mixed_questions()
    state = {'ticket': 'The export fails and blocks work.', 'numbers': [1, 2, 3]}
    result = jev.ask_questions(state, questions)
    assert result is not None
    assert len(calls) == 1
    assert result['total'] == result['evaluated'] == 4
    assert result['values']['present'] == result['values']['urgent'] == 0.9
    assert result['values']['severity']['normalized_score'] == 0.5
    raw = Path(result['evidence_path']).read_bytes()
    assert json.loads(raw) == {'state': state, 'questions': questions}
    assert result['sha256'] == hashlib.sha256(raw).hexdigest()
    assert Path(result['receipt']).is_file()
    assert Path(result['evidence_path']).stat().st_mode & 0o777 == 0o600
    assert capsys.readouterr() == ('', '')


@pytest.mark.parametrize('outcome', ['401', '402', '429', 'offline', 'timeout', 'duplicate', 'malformed'])
def test_transport_and_protocol_failures_are_silent_single_attempt_fallback(monkeypatch, capsys, outcome):
    configure(monkeypatch)
    calls = install_worker(monkeypatch, outcome)
    start = time.monotonic()
    assert jev.ask_questions({'ticket': 'A test issue'}, mixed_questions()) is None
    elapsed = time.monotonic() - start
    assert len(calls) == 1
    # Scheduling allowance is not a service SLA; the worker budget remains 280ms.
    assert elapsed < 0.8
    assert calls[0][1]['deadline'] - start <= 0.281
    assert capsys.readouterr() == ('', '')


def test_invalid_schema_or_storage_failure_never_reaches_network(monkeypatch):
    configure(monkeypatch)
    monkeypatch.setattr(jev, 'evaluate', lambda *_a, **_k: pytest.fail('network called'))
    assert jev.ask_questions('evidence', {'q': {'type': 'invented'}}) is None
    def unavailable(*_args, **_kwargs):
        raise OSError('private storage unavailable')
    monkeypatch.setattr(jev, '_save_auto_evidence', unavailable)
    assert jev.ask_questions('evidence', mixed_questions()) is None


def test_request_byte_budget_remains_enforced_for_fanout(monkeypatch):
    configure(monkeypatch)
    monkeypatch.setattr(jev, 'run_bytes', lambda *_a, **_k: pytest.fail('oversized request launched'))
    assert jev.ask_questions('x' * jev.MAX_PAIR_BYTES, mixed_questions()) is None
