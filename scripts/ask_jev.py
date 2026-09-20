#!/usr/bin/env python3
"""Ask bounded advisory questions, or select verbatim spans, using shared Jev."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
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
    for mode in ('choose', 'check', 'purify'):
        p = modes.add_parser(mode)
        p.add_argument('--input-file', help='Read a regular UTF-8 file; default: stdin')
        if mode == 'purify':
            p.add_argument('--query', default='', help='What makes a passage useful?')
        else:
            p.add_argument('--question', required=True)
        if mode == 'choose':
            p.add_argument('--option', action='append', required=True, help='Repeat for 2-12 distinct labels')
    return parser


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
        if len(question) > 4096 or (args.mode != 'purify' and not question.strip()):
            raise ValueError('invalid_question')
        text = _read_input(args.input_file)
    except (OSError, ValueError) as exc:
        reason = str(exc) if isinstance(exc, ValueError) else 'input_unavailable'
        print(json.dumps({**base, 'status': 'error', 'reason': reason}, ensure_ascii=False))
        return 64

    result = {**base, 'status': 'fallback', 'reason': 'unavailable',
              'input_sha256': hashlib.sha256(text.encode()).hexdigest()}
    if args.mode == 'purify':
        result.update(text=text, spans=[])
    else:
        result['answer'] = None
    try:
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
                    result = {**base, **marked, 'status': 'ok', 'text': selected,
                              'reason': 'verbatim_selection', 'original_available': True}
            else:
                response = core.ask_decision(text, args.question,
                                            args.option if args.mode == 'choose' else None)
                if response is not None:
                    value = response['values']['decision']
                    answer = None
                    if args.mode == 'choose':
                        if value['confidence'] >= .85 and value['probabilities'][value['choice']] >= .85:
                            answer = value['choice']
                    elif value >= .85:
                        answer = True
                    elif value <= .15:
                        answer = False
                    result = {**base, 'status': 'ok' if answer is not None else 'unknown',
                              'reason': 'decisive' if answer is not None else 'uncertain',
                              'answer': answer, 'judgment': value, 'advisory': True,
                              'receipt': response['receipt'], 'evidence_path': response['evidence_path'],
                              'model': response.get('model')}
    except Exception:
        # No stderr, retries, synthetic answer, or loss of the original text.
        pass
    print(json.dumps(result, ensure_ascii=False, allow_nan=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
