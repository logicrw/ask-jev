#!/usr/bin/env python3
"""Ask bounded advisory questions, or select verbatim spans, using shared Jev."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
import unicodedata

def _load_core():
    here = Path(__file__).resolve().parent
    for candidate in [here, Path.home() / '.agents' / 'scripts']:
        if (candidate / 'jev_context.py').is_file():
            if str(candidate) not in sys.path:
                sys.path.insert(0, str(candidate))
            try:
                import jev_context as mod
                return mod
            except Exception:
                pass
    return None

core = _load_core()

MAX_INPUT_BYTES = 256 * 1024  # local read guard, independent of helper availability
SCHEMA = 'ask-jev.v1'


def _pictures_path(path: Path) -> bool:
    fold = lambda p: tuple(unicodedata.normalize('NFD', x).casefold() for x in p.parts)
    parts = fold(path)
    private = Path.home() / 'Pictures'
    variants = [private]
    if sys.platform == 'darwin':
        variants.append(Path('/System/Volumes/Data') / private.relative_to('/'))
    return any(parts[:len(prefix)] == prefix for prefix in map(fold, variants))


def _read_input(name: str | None) -> str:
    if name is None or name == '-':
        if sys.stdin.isatty():
            raise ValueError('input_required')
        raw = sys.stdin.buffer.read(MAX_INPUT_BYTES + 1)
    else:
        path = Path(name).expanduser().absolute()
        if _pictures_path(path) or '..' in path.parts:
            raise ValueError('input_path_refused')
        # Pin each component: no symlink can redirect a checked path into Pictures.
        fd = os.open(path.anchor, os.O_RDONLY | os.O_DIRECTORY)
        try:
            for component in path.parts[1:-1]:
                next_fd = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                os.close(fd)
                fd = next_fd
            source_fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
        finally:
            os.close(fd)
        with os.fdopen(source_fd, 'rb') as source:
            if not stat.S_ISREG(os.fstat(source.fileno()).st_mode):
                raise ValueError('input_not_regular')
            raw = source.read(MAX_INPUT_BYTES + 1)
    if len(raw) > MAX_INPUT_BYTES:
        raise ValueError('input_budget')
    try:
        return raw.decode('utf-8', errors='strict')
    except UnicodeError:
        raise ValueError('input_not_utf8') from None


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_subparsers(dest='mode', required=True)
    for mode in ('choose', 'check', 'purify', 'score', 'batch'):
        p = modes.add_parser(mode)
        p.add_argument('--input-file', help='Read a regular UTF-8 file; default: stdin')
        if mode == 'purify':
            p.add_argument('--query', default='', help='What makes a passage useful?')
        elif mode != 'batch':
            p.add_argument('--question', required=True)
        if mode == 'choose':
            p.add_argument('--option', action='append', required=True, help='Repeat for 2-12 distinct labels')
        if mode == 'score':
            p.add_argument('--level', action='append', required=True, help='Repeat 2-10 concrete levels, low to high')
        if mode == 'check':
            p.add_argument('--expect', choices=('true', 'false'), help='Optional local expectation; never sent to Jev')
    return parser


def _escalation(reason: str | None = None) -> dict:
    return {'required': reason is not None, 'target': 'primary_model' if reason else None,
            'reason': reason}


def _decision(kind: str, value: object, expectation: bool | None = None) -> dict:
    answer = None
    if kind == 'choice':
        if value['confidence'] >= .85 and value['probabilities'][value['choice']] >= .85:
            answer = value['choice']
    elif kind == 'score':
        if value['confidence'] >= .85:
            answer = value['score']
    elif value >= .85:
        answer = True
    elif value <= .15:
        answer = False
    reason = 'uncertain' if answer is None else (
        'expectation_mismatch' if expectation is not None and answer is not expectation else None)
    result = {'status': 'unknown' if answer is None else 'ok',
              'reason': 'uncertain' if answer is None else 'decisive',
              'answer': answer, 'judgment': value, 'advisory': True,
              'escalation': _escalation(reason)}
    if expectation is not None:
        result['expectation'] = expectation
    return result


def _batch_input(text: str) -> tuple[object, dict, dict]:
    """Parse local policy separately from the evidence and provider questions."""
    def pairs(entries):
        result = {}
        for key, value in entries:
            if key in result:
                raise ValueError('invalid_batch')
            result[key] = value
        return result

    def invalid_constant(_value):
        raise ValueError('invalid_batch')

    try:
        payload = json.loads(text, object_pairs_hook=pairs, parse_constant=invalid_constant)
        json.dumps(payload, allow_nan=False)
        if not isinstance(payload, dict) or set(payload) != {'state', 'questions'}:
            raise ValueError('invalid_batch')
        questions = payload['questions']
        if not isinstance(questions, dict) or not 1 <= len(questions) <= 32:
            raise ValueError('invalid_batch')
        wire, expectations = {}, {}
        for key, question in questions.items():
            if (not re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]{0,63}', key)
                    or not isinstance(question, dict)
                    or question.get('type') not in ('noul', 'choice', 'score')):
                raise ValueError('invalid_batch')
            wire[key] = {k: v for k, v in question.items() if k != 'expect'}
            if 'expect' in question:
                if question.get('type') != 'noul' or type(question['expect']) is not bool:
                    raise ValueError('invalid_batch')
                expectations[key] = question['expect']
        prepare = getattr(core, 'prepare_questions', None)
        if callable(prepare):
            prepare(payload['state'], wire)
        return payload['state'], wire, expectations
    except (ValueError, TypeError, RecursionError, OverflowError):
        raise ValueError('invalid_batch') from None


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    base = {'schema': SCHEMA, 'mode': args.mode}
    try:
        if args.mode == 'choose' and (not 2 <= len(args.option) <= 12
                or len(set(args.option)) != len(args.option)
                or any(not option.strip() or len(option) > 128
                       or any(ord(c) < 32 for c in option) for option in args.option)):
            raise ValueError('invalid_options')
        question = getattr(args, 'question', getattr(args, 'query', ''))
        if len(question) > 4096 or (args.mode not in {'purify', 'batch'} and not question.strip()):
            raise ValueError('invalid_question')
        if args.mode == 'score' and (not 2 <= len(args.level) <= 10
                or len(set(args.level)) != len(args.level)
                or any(not level.strip() or len(level) > 4096 for level in args.level)):
            raise ValueError('invalid_levels')
        text = _read_input(args.input_file)
        if args.mode == 'batch':
            state, questions, expectations = _batch_input(text)
    except (OSError, ValueError) as exc:
        reason = str(exc) if isinstance(exc, ValueError) else 'input_unavailable'
        print(json.dumps({**base, 'status': 'error', 'reason': reason}, ensure_ascii=False))
        return 64

    result = {**base, 'status': 'fallback', 'reason': 'unavailable', 'advisory': True,
              'input_sha256': hashlib.sha256(text.encode()).hexdigest()}
    if args.mode == 'batch':
        result['decisions'] = {key: {'type': q.get('type'), 'status': 'fallback',
            'reason': 'unavailable', 'answer': None, 'advisory': True,
            'escalation': _escalation('unavailable'),
            **({'expectation': expectations[key]} if key in expectations else {})}
            for key, q in questions.items()}
    elif args.mode == 'purify':
        result.update(text=text, spans=[])
    else:
        result['answer'] = None
        if args.mode == 'check' and args.expect is not None:
            result['expectation'] = args.expect == 'true'
    if args.mode != 'batch':
        result['escalation'] = _escalation('unavailable')
    try:
        candidate = result
        if core is not None:
            if args.mode == 'purify':
                marked = core.auto_mark_text(text, source='ask-jev', query=args.query)
                if marked is not None:
                    lines = core.lf_lines(text)
                    spans = marked['spans']
                    last_end = 0
                    for span in spans:
                        start, end = span['start'], span['end']
                        if (type(start) is not int or type(end) is not int
                                or not last_end < start <= end <= len(lines)):
                            raise ValueError('invalid_spans')
                        last_end = end
                    if not spans:
                        raise ValueError('empty_spans')
                    selected = ''.join(''.join(lines[s['start'] - 1:s['end']]) for s in spans)
                    candidate = {**base, **marked, 'status': 'ok', 'text': selected,
                                 'reason': 'verbatim_selection', 'original_available': True,
                                 'advisory': True, 'escalation': _escalation()}
            elif args.mode in {'score', 'batch'}:
                if args.mode == 'score':
                    state, questions, expectations = text, {'decision': {
                        'type': 'score', 'instructions': args.question, 'criteria': args.level}}, {}
                response = core.ask_questions(state, questions)
                if response is not None:
                    decisions = {key: {'type': q['type'], **_decision(q['type'], response['values'][key],
                                   expectations.get(key))} for key, q in questions.items()}
                    metadata = {key: response[key] for key in ('receipt', 'evidence_path')}
                    metadata['model'] = response.get('model')
                    candidate = ({**base, **metadata, **decisions['decision']} if args.mode == 'score' else
                                 {**base, **metadata, 'status': 'ok', 'reason': 'evaluated',
                                  'advisory': True, 'decisions': decisions})
            else:
                response = core.ask_decision(text, args.question,
                                            args.option if args.mode == 'choose' else None)
                if response is not None:
                    value = response['values']['decision']
                    expect = getattr(args, 'expect', None)
                    candidate = {**base, **_decision('choice' if args.mode == 'choose' else 'noul', value,
                                 None if expect is None else expect == 'true'),
                                 'receipt': response['receipt'], 'evidence_path': response['evidence_path'],
                                 'model': response.get('model')}
        # A malformed adapter result must not escape through JSON serialization.
        json.dumps(candidate, ensure_ascii=False, allow_nan=False)
        result = candidate
    except Exception:
        # No stderr, retries, synthetic answer, or loss of the original text.
        pass
    print(json.dumps(result, ensure_ascii=False, allow_nan=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
