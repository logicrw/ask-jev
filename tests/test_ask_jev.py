"""Offline public CLI contracts; local workers do not establish model quality."""
from __future__ import annotations

import contextlib
import builtins
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import pytest

ROOT = Path(__file__).resolve().parents[1]
CLI_PATH = ROOT / 'scripts' / 'ask_jev.py'
sys.path.insert(0, str(ROOT / 'scripts'))
import jev_context as jev


@pytest.fixture(autouse=True)
def offline_private_environment(monkeypatch, tmp_path):
    for name in ('TYPESAFE_API_KEY', 'HARNESS_JEV_ALLOW_REMOTE', 'JEV_MODEL'):
        monkeypatch.delenv(name, raising=False)
    root = tmp_path.resolve() / 'evidence'
    root.mkdir(mode=0o700)
    monkeypatch.setenv('HARNESS_JEV_EVIDENCE_DIR', str(root))
    return root


def configured(monkeypatch):
    monkeypatch.setenv('TYPESAFE_API_KEY', 'offline-fixture-only')
    monkeypatch.setenv('HARNESS_JEV_ALLOW_REMOTE', '1')


def load_cli():
    spec = importlib.util.spec_from_file_location('ask_jev_test_cli', CLI_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def arguments(mode):
    if mode == 'choose':
        return [mode, '--question', 'Which label does the evidence support?',
                '--option', 'action', '--option', 'information']
    if mode == 'check':
        return [mode, '--question', 'Does the supplied evidence support the claim?']
    return [mode, '--query', 'substantive evidence']


def invoke(monkeypatch, mode, raw='original\rprogress\n中文\u2028same LF line\n', *, argv=None):
    cli = load_cli()
    stream = io.TextIOWrapper(io.BytesIO(raw.encode('utf-8')), encoding='utf-8', newline='')
    monkeypatch.setattr(sys, 'stdin', stream)
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = cli.main(arguments(mode) if argv is None else argv)
        except SystemExit as exc:
            code = exc.code
    assert code == 0
    assert err.getvalue() == ''
    result = json.loads(out.getvalue())
    assert result['schema'] == 'ask-jev.v1'
    assert result['mode'] == mode
    return result


def subprocess_cli(argv, raw=b'original\rprogress\n', timeout=2):
    completed = subprocess.run([sys.executable, str(CLI_PATH), *argv], input=raw,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               timeout=timeout, check=False)
    assert b'Traceback' not in completed.stderr
    assert b'Traceback' not in completed.stdout
    return completed


def real_fixture_transport(monkeypatch, *, outcome='success', probability=0.96,
                           confidence=0.97):
    """Run the production evaluator/runtime with a network-free child worker.

    HTTP cases invoke the actual production HTTP worker with an opener that
    raises a real urllib HTTPError; timeouts use a sleeping child killed by the
    shared runtime. No replacement URL or response schema is added to the CLI.
    """
    production_evaluate = jev.evaluate
    calls = []
    if outcome in ('401', '402', '429'):
        code = (
            'import sys,urllib.error,urllib.request\n'
            f'sys.path.insert(0,{str(ROOT / "scripts")!r})\n'
            'import jev_context as j\n'
            'class OfflineOpener:\n'
            ' def open(self,*args,**kwargs):\n'
            f'  raise urllib.error.HTTPError(j.ENDPOINT,{int(outcome)},"offline",None,None)\n'
            'urllib.request.build_opener=lambda *args,**kwargs:OfflineOpener()\n'
            'raise SystemExit(j._worker())\n'
        )
    elif outcome == 'timeout':
        code = 'import time; time.sleep(10)'
    elif outcome == 'malformed':
        code = 'print("not valid JSON")'
    else:
        code = (
            'import json,sys\n'
            'request=json.load(sys.stdin)\n'
            'answers={}\n'
            'for key,q in request["questions"].items():\n'
            ' if q["type"]=="choice":\n'
            '  names=list(q["criteria"])\n'
            f'  p={probability!r}\n'
            f'  answers[key]={{"type":"choice","choice":names[0],"confidence":{confidence!r},'
            '"probabilities":{name:p if name==names[0] else (1-p)/(len(names)-1) for name in names}}\n'
            ' else:\n'
            '  text=q.get("instructions",{}).get("candidate_text", "")\n'
            f'  p={probability!r}\n'
            '  if key!="decision":\n'
            '   p=.99 if any(word in text for word in ("```", "diff --git", "Traceback", "substantive")) else .01\n'
            '  answers[key]={"type":"noul","noul":p}\n'
            'print(json.dumps({"answers":answers,"model":"offline-fixture"}))\n'
        )

    def evaluate(request, **kwargs):
        calls.append(request)
        return production_evaluate(request, worker_argv=[sys.executable, '-c', code], **kwargs)

    monkeypatch.setattr(jev, 'evaluate', evaluate)
    return calls


@pytest.mark.parametrize('mode', ['choose', 'check', 'purify'])
def test_natural_cli_without_credentials_reads_stdin_and_falls_back(mode):
    raw = '中文\rprogress\n\nlast\u2028same-line\vsegment\n'.encode()
    completed = subprocess_cli(arguments(mode), raw)
    assert completed.returncode == 0
    assert completed.stderr == b''
    result = json.loads(completed.stdout)
    assert result['schema'] == 'ask-jev.v1'
    assert result['mode'] == mode
    assert result['status'] == 'fallback'
    if mode == 'purify':
        assert result['text'].encode('utf-8') == raw
    else:
        assert result['answer'] is None


@pytest.mark.parametrize('mode', ['choose', 'check', 'purify'])
@pytest.mark.parametrize(('key', 'consent'), [(None, None), ('fixture', None),
                                           (None, '1'), ('fixture', 'true'), ('fixture', '0')])
def test_exact_environment_gate_prevents_any_transport(monkeypatch, mode, key, consent):
    if key is not None:
        monkeypatch.setenv('TYPESAFE_API_KEY', key)
    if consent is not None:
        monkeypatch.setenv('HARNESS_JEV_ALLOW_REMOTE', consent)

    def forbidden(*args, **kwargs):
        pytest.fail('closed environment gate performed remote/evidence work')

    monkeypatch.setattr(jev, 'evaluate', forbidden)
    monkeypatch.setattr(jev, '_save_auto_evidence', forbidden)
    result = invoke(monkeypatch, mode)
    assert result['status'] == 'fallback'


@pytest.mark.parametrize('mode', ['choose', 'check'])
def test_success_uses_one_shared_batch_without_model_configuration(monkeypatch, mode):
    configured(monkeypatch)
    calls = real_fixture_transport(monkeypatch)
    raw = 'The supplied evidence reports a completed action.\n'
    result = invoke(monkeypatch, mode, raw)
    assert result['status'] == 'ok'
    assert result['answer'] == ('action' if mode == 'choose' else True)
    assert len(calls) == 1
    assert calls[0]['model'] == jev.DEFAULT_MODEL
    assert set(calls[0]['questions']) == {'decision'}
    source = Path(result['evidence_path'])
    evidence_bytes = source.read_bytes()
    evidence = json.loads(evidence_bytes)
    assert evidence['state'] == raw
    assert evidence['question'] == arguments(mode)[2]
    assert evidence['options'] == (['action', 'information'] if mode == 'choose' else None)
    receipt = json.loads(Path(result['receipt']).read_text())
    assert receipt['sha256'] == hashlib.sha256(evidence_bytes).hexdigest()
    assert receipt['evidence_path'] == str(source)


@pytest.mark.parametrize(('probability', 'expected'), [(0.85, True), (1.0, True),
                                                       (0.15, False), (0.0, False),
                                                       (0.5, None), (0.8499, None), (0.1501, None)])
def test_truth_check_abstains_between_closed_probability_thresholds(monkeypatch, probability, expected):
    configured(monkeypatch)
    real_fixture_transport(monkeypatch, probability=probability)
    result = invoke(monkeypatch, 'check')
    assert result['answer'] is expected
    assert result['status'] == ('unknown' if expected is None else 'ok')


@pytest.mark.parametrize(('probability', 'confidence', 'expected'), [
    (.85, .85, 'action'), (.8499, .99, None), (.99, .8499, None), (.5, .5, None)])
def test_choice_requires_both_confidence_and_winner_probability(monkeypatch, probability, confidence, expected):
    configured(monkeypatch)
    real_fixture_transport(monkeypatch, probability=probability, confidence=confidence)
    result = invoke(monkeypatch, 'choose')
    assert result['answer'] == expected
    assert result['status'] == ('unknown' if expected is None else 'ok')


def test_closed_choice_preserves_unicode_labels(monkeypatch):
    configured(monkeypatch)
    calls = real_fixture_transport(monkeypatch)
    argv = ['choose', '--question', '材料更支持哪个标签？', '--option', '需要跟进', '--option', '仅供知晓']
    result = invoke(monkeypatch, 'choose', '请明天复核这份公开设计。\n', argv=argv)
    assert result['status'] == 'ok'
    assert result['answer'] == '需要跟进'
    assert set(calls[0]['questions']['decision']['criteria']) == {'需要跟进', '仅供知晓'}


@pytest.mark.parametrize('mode', ['choose', 'check', 'purify'])
@pytest.mark.parametrize('outcome', ['401', '402', '429', 'timeout', 'malformed'])
def test_real_shared_transport_failure_is_silent_and_preserves_native_result(monkeypatch, mode, outcome, record_property):
    configured(monkeypatch)
    calls = real_fixture_transport(monkeypatch, outcome=outcome)

    def forbidden(*args, **kwargs):
        pytest.fail('provider failure attempted post-error receipt I/O')

    monkeypatch.setattr(jev, '_save_auto_receipt', forbidden)
    raw = 'first\rprogress\n\n中文\u2028one physical line\n'
    start = time.monotonic()
    result = invoke(monkeypatch, mode, raw)
    elapsed = time.monotonic() - start
    record_property('elapsed_seconds', elapsed)
    assert len(calls) == 1
    assert result['status'] == 'fallback'
    if mode == 'purify':
        assert result['text'] == raw
    else:
        assert result['answer'] is None
    if outcome == 'timeout':
        # Actual decision deadline is 280 ms + bounded reap. Include only a small
        # scheduling tolerance for invoking the public CLI in a busy test runner.
        assert elapsed < .45


def test_purification_spans_reconstruct_exact_original_structure(monkeypatch):
    configured(monkeypatch)
    calls = real_fixture_transport(monkeypatch)
    fence = '```python\nimport math\n\ndef area(r):\n    return math.pi * r*r\n```\n'
    patch = 'diff --git a/x.py b/x.py\n--- a/x.py\n+++ b/x.py\n@@ -1 +1 @@\n-old\n+new\n'
    traceback = 'Traceback (most recent call last):\n  File "x.py", line 1\nRuntimeError: root cause\n'
    raw = 'intro\rprogress\n\n## optional\nnoise\u2028same LF line\n\n' + fence + patch + traceback
    result = invoke(monkeypatch, 'purify', raw)
    assert result['status'] == 'ok'
    assert result['original_available'] is True
    assert len(calls) == 1
    assert Path(result['evidence_path']).read_bytes() == raw.encode('utf-8')
    lines = jev.lf_lines(raw)
    selected = ''.join(''.join(lines[s['start'] - 1:s['end']]) for s in result['spans'])
    assert result['text'] == selected
    assert fence in selected
    assert patch in selected
    assert traceback in selected
    assert 'noise' not in selected
    assert [s['start'] for s in result['spans']] == sorted(s['start'] for s in result['spans'])
    assert Path(result['receipt']).is_file()


@pytest.mark.parametrize('mode', ['choose', 'check', 'purify'])
def test_unexpected_adapter_failure_never_escapes_cli(monkeypatch, mode):
    configured(monkeypatch)

    def fail(*args, **kwargs):
        raise RuntimeError('fixture exception must not leak')

    monkeypatch.setattr(jev, 'ask_decision' if mode != 'purify' else 'auto_mark_text', fail)
    raw = 'fully preserved\r\n原文\n'
    result = invoke(monkeypatch, mode, raw)
    assert result['status'] == 'fallback'
    if mode == 'purify':
        assert result['text'] == raw
    else:
        assert result['answer'] is None
    assert 'fixture exception' not in json.dumps(result)


@pytest.mark.parametrize('mode', ['choose', 'check', 'purify'])
def test_missing_shared_core_is_a_silent_fallback(monkeypatch, mode):
    native_import = builtins.__import__

    def unavailable(name, *args, **kwargs):
        if name == 'jev_context':
            raise ImportError('offline missing core fixture')
        return native_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, '__import__', unavailable)
    raw = 'preserve all original text\r\n中文\n'
    result = invoke(monkeypatch, mode, raw)
    assert result['status'] == 'fallback'
    if mode == 'purify':
        assert result['text'] == raw
    else:
        assert result['answer'] is None


@pytest.mark.parametrize('mode', ['choose', 'check', 'purify'])
def test_detected_secret_never_reaches_transport(monkeypatch, mode):
    configured(monkeypatch)

    def forbidden(*args, **kwargs):
        pytest.fail('secret-bearing evidence reached remote transport')

    monkeypatch.setattr(jev, 'evaluate', forbidden)
    result = invoke(monkeypatch, mode, 'api_key=synthetic-fixture-value\n')
    assert result['status'] == 'fallback'


@pytest.mark.parametrize('mode', ['choose', 'check', 'purify'])
def test_empty_stdin_is_a_native_empty_fallback(mode):
    completed = subprocess_cli(arguments(mode), b'')
    assert completed.returncode == 0
    assert completed.stderr == b''
    result = json.loads(completed.stdout)
    assert result['status'] == 'fallback'
    if mode == 'purify':
        assert result['text'] == ''
    else:
        assert result['answer'] is None


@pytest.mark.parametrize('raw', [b'\xffinvalid UTF-8', b'x' * (jev.MAX_INPUT_BYTES + 1)])
def test_invalid_or_oversized_input_is_bounded_structured_error(raw):
    completed = subprocess_cli(['purify'], raw)
    assert completed.returncode == 64
    assert completed.stderr == b''
    result = json.loads(completed.stdout)
    assert result['schema'] == 'ask-jev.v1'
    assert result['status'] == 'error'
    assert result['reason']


@pytest.mark.parametrize('options', [[], ['only'], ['same', 'same'], ['one', ''],
                                    [f'item{i}' for i in range(13)]])
def test_invalid_closed_option_sets_are_rejected(options):
    argv = ['choose', '--question', 'Select one']
    for option in options:
        argv.extend(['--option', option])
    completed = subprocess_cli(argv)
    assert completed.returncode in (2, 64)


@pytest.mark.parametrize('argv', [[], ['unknown-command'], ['check'], ['purify', '--unknown-flag']])
def test_argparse_usage_errors_remain_conventional(argv):
    completed = subprocess_cli(argv)
    assert completed.returncode == 2


def test_input_file_preserves_raw_lf_and_unicode(tmp_path):
    raw = 'first\rline\r\n中文\u2028same LF line\n'.encode('utf-8')
    path = tmp_path / 'source.txt'
    path.write_bytes(raw)
    completed = subprocess_cli(['purify', '--input-file', str(path)], b'ignored stdin')
    assert completed.returncode == 0
    assert completed.stderr == b''
    result = json.loads(completed.stdout)
    assert result['text'].encode('utf-8') == raw


@pytest.mark.parametrize('kind', ['missing', 'directory', 'symlink', 'fifo'])
def test_nonregular_input_files_are_rejected_without_blocking(tmp_path, kind):
    path = tmp_path / kind
    if kind == 'directory':
        path.mkdir()
    elif kind == 'symlink':
        target = tmp_path / 'original.txt'
        target.write_text('original')
        path.symlink_to(target)
    elif kind == 'fifo':
        os.mkfifo(path)
    completed = subprocess_cli(['purify', '--input-file', str(path)])
    assert completed.returncode == 64
    assert completed.stderr == b''
    assert json.loads(completed.stdout)['status'] == 'error'


def test_symlink_parent_is_rejected_without_following_target(tmp_path):
    target = tmp_path / 'real'
    target.mkdir()
    (target / 'source.txt').write_text('untrusted alias input')
    link = tmp_path / 'alias'
    link.symlink_to(target, target_is_directory=True)
    completed = subprocess_cli(['purify', '--input-file', str(link / 'source.txt')])
    assert completed.returncode == 64
    assert json.loads(completed.stdout)['status'] == 'error'


def test_pictures_path_is_rejected_lexically_without_any_filesystem_access(monkeypatch):
    cli = load_cli()
    original_open = os.open

    def guarded_open(path, *args, **kwargs):
        assert 'Pictures' not in str(path), 'Pictures boundary reached filesystem access'
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(os, 'open', guarded_open)
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = cli.main(['purify', '--input-file', str(Path.home() / 'Pictures' / 'forbidden.txt')])
    assert code == 64
    assert err.getvalue() == ''
    assert json.loads(out.getvalue())['status'] == 'error'


def test_empty_evidence_never_requests_a_decision(monkeypatch):
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
    import jev_context
    monkeypatch.setenv('TYPESAFE_API_KEY', 'fixture-only')
    monkeypatch.setenv('HARNESS_JEV_ALLOW_REMOTE', '1')
    calls = []
    def forbidden(*args, **kwargs):
        calls.append(True)
        return None
    monkeypatch.setattr(jev_context, '_evaluate_evidenced', forbidden)
    assert jev_context.ask_decision('  \n', 'Does the evidence support success?') is None
    assert calls == []


@pytest.mark.parametrize(('home', 'path'), [
    ('/Users/Example', '/Users/Example/pictures/forbidden.txt'),
    ('/Users/Example', '/uSeRs/eXaMpLe/PiCtUrEs/forbidden.txt'),
    ('/Users/Résumé', '/Users/Re\u0301sume\u0301/PiCtUrEs/forbidden.txt'),
    ('/Users/Re\u0301sume\u0301', '/users/RÉSUMÉ/pictures/forbidden.txt'),
    ('/Users/Example', '/System/Volumes/Data/Users/Example/Pictures/forbidden.txt'),
    ('/Users/Example', '/system/volumes/data/users/EXAMPLE/pictures/forbidden.txt'),
    ('/Users/Résumé', '/System/Volumes/Data/Users/Re\u0301sume\u0301/pictures/forbidden.txt'),
], ids=['lowercase', 'mixed-case-ancestors', 'nfd-alias', 'nfc-alias',
        'data-volume', 'data-volume-case-alias', 'data-volume-nfd-alias'])
@pytest.mark.parametrize('surface', ['cli', 'shared-evidence-root'])
def test_pictures_aliases_are_refused_before_all_filesystem_access(monkeypatch, home, path, surface):
    """All homes are fictional; every filesystem observation is intercepted.

    Count operations independently from raised exceptions, so a broad fail-open
    handler cannot conceal an attempted forbidden access from this regression.
    """
    cli = load_cli()
    calls = []

    def forbidden(*args, **kwargs):
        calls.append((args, kwargs))
        raise OSError('test fixture forbids all filesystem access')

    with monkeypatch.context() as boundary:
        boundary.setattr(sys, 'platform', 'darwin')
        boundary.setattr(Path, 'home', classmethod(lambda cls: Path(home)))
        boundary.setattr(os, 'open', forbidden)
        boundary.setattr(os, 'mkdir', forbidden)
        boundary.setattr(Path, 'stat', forbidden)
        boundary.setattr(Path, 'lstat', forbidden)
        boundary.setattr(Path, 'is_symlink', forbidden)
        if surface == 'cli':
            out, err = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = cli.main(['purify', '--input-file', path])
        else:
            boundary.setenv('HARNESS_JEV_EVIDENCE_DIR', path)
            with pytest.raises(ValueError, match='unsupported evidence root'):
                jev._evidence_root()
    assert calls == []
    if surface == 'cli':
        assert code == 64
        assert err.getvalue() == ''
        assert json.loads(out.getvalue())['reason'] == 'input_path_refused'


@pytest.mark.parametrize('surface', ['cli', 'shared-evidence-root'])
def test_pictures_component_guard_does_not_match_sibling_directory_names(monkeypatch, surface):
    cli = load_cli()
    monkeypatch.setattr(sys, 'platform', 'darwin')
    monkeypatch.setattr(Path, 'home', classmethod(lambda cls: Path('/Users/Example')))
    checker = cli._pictures_path if surface == 'cli' else jev._pictures_path
    for path in ('/Users/Example/Pictures-archive/file.txt',
                 '/Users/ExampleOther/Pictures/file.txt',
                 '/System/Volumes/Data/Users/Example/pictures-other/file.txt'):
        assert checker(Path(path)) is False
