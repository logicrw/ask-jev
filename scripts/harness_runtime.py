#!/usr/bin/env python3
"""POSIX bounded execution. No shell, native consent, deletion or retry policy.

Timeout/limit means evidence is incomplete and the external effect is UNKNOWN.
A child which deliberately escapes its process group needs an OS sandbox.
"""
from __future__ import annotations
import dataclasses, math, os, selectors, signal, subprocess, time
from typing import BinaryIO, Mapping, Sequence

@dataclasses.dataclass(frozen=True)
class Result:
    returncode: int | None
    stdout: bytes
    stderr: bytes
    reason: str | None
    observed_bytes: int
    elapsed: float


def kill_group(proc: subprocess.Popen, wait_timeout: float = 2) -> None:
    # A dead leader can leave live descendants holding our pipes.
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    except PermissionError:
        # macOS can race with final group removal after the leader exits.
        # A dead leader alone is insufficient: descendants may still exist.
        if proc.poll() is None:
            raise
        try:
            os.killpg(proc.pid, 0)
        except ProcessLookupError:
            pass
        else:
            raise
    if wait_timeout == 0:
        # A latency-bounded advisory caller must not wait for kernel reaping.
        # Popen retains an unreaped child for nonblocking cleanup if necessary.
        proc.poll()
    else:
        try:
            proc.wait(timeout=wait_timeout)
        except subprocess.TimeoutExpired:
            if wait_timeout >= 2:
                raise


def run_bytes(argv: Sequence[str], *, timeout: float = 30, max_bytes: int | None = 1048576,
              input_bytes: bytes | None = None, cwd: str | None = None,
              env: Mapping[str, str] | None = None, sink: BinaryIO | None = None,
              merge: bool = False, projection_bytes: int = 8192,
              channel_limits: Mapping[str, int] | None = None,
              sinks: Mapping[str, BinaryIO] | None = None,
              kill_wait: float = 2) -> Result:
    if isinstance(argv, (str, bytes)) or not argv or any(not isinstance(x, str) or '\0' in x for x in argv):
        raise ValueError('argv must be a nonempty sequence of NUL-free strings')
    if not math.isfinite(timeout) or timeout <= 0 or (max_bytes is not None and not 0 < max_bytes <= 1024**3) or projection_bytes < 0:
        raise ValueError('invalid execution budget')
    if not math.isfinite(kill_wait) or kill_wait < 0:
        raise ValueError('invalid reap budget')
    destinations = dict(sinks or {})
    if sink is not None and destinations:
        raise ValueError('sink and sinks are mutually exclusive')
    if any(k not in {'stdout', 'stderr'} for k in destinations):
        raise ValueError('invalid sink channel')
    if max_bytes is None and sink is None and not ({'stdout'} if merge else {'stdout', 'stderr'}) <= destinations.keys():
        raise ValueError('unlimited capture requires durable sinks for every channel')
    if input_bytes is not None and len(input_bytes) > 16 * 1024**2:
        raise ValueError('stdin budget exceeded')
    limits = dict(channel_limits or {})
    if any(k not in {"stdout", "stderr"} or not isinstance(v, int) or v <= 0
           for k, v in limits.items()):
        raise ValueError("invalid channel limits")
    start = time.monotonic()
    proc = subprocess.Popen(list(argv), stdin=subprocess.PIPE if input_bytes else subprocess.DEVNULL,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT if merge else subprocess.PIPE,
                            cwd=cwd, env=None if env is None else dict(env), start_new_session=True,
                            close_fds=True, bufsize=0)
    sel = selectors.DefaultSelector()
    buffers = {'stdout': bytearray(), 'stderr': bytearray()}
    observed = 0
    channel_bytes = {"stdout": 0, "stderr": 0}
    reason = None
    termination_requested = False
    position = 0
    try:
        for label, stream in [('stdout', proc.stdout), ('stderr', proc.stderr)]:
            if stream is not None:
                os.set_blocking(stream.fileno(), False)
                sel.register(stream, selectors.EVENT_READ, label)
        if input_bytes:
            os.set_blocking(proc.stdin.fileno(), False)
            sel.register(proc.stdin, selectors.EVENT_WRITE, 'stdin')
        while sel.get_map():
            remaining = start + timeout - time.monotonic()
            if remaining <= 0:
                reason = 'timeout'
                break
            for key, _ in sel.select(min(remaining, .1)):
                stream, label = key.fileobj, key.data
                if label == 'stdin':
                    try:
                        position += os.write(stream.fileno(), memoryview(input_bytes)[position:position+16384])
                    except BlockingIOError:
                        continue
                    except BrokenPipeError:
                        position = len(input_bytes)
                    if position == len(input_bytes):
                        sel.unregister(stream)
                        stream.close()
                    continue
                try:
                    chunk = os.read(stream.fileno(), 65536)
                except BlockingIOError:
                    continue
                if not chunk:
                    sel.unregister(stream)
                    stream.close()
                    continue
                allowed = len(chunk)
                if max_bytes is not None:
                    allowed = min(allowed, max_bytes - observed)
                if label in limits:
                    allowed = min(allowed, limits[label] - channel_bytes[label])
                piece = chunk[:allowed]
                observed += len(piece)
                channel_bytes[label] += len(piece)
                destination = sink if sink is not None else destinations.get(label)
                if destination is not None:
                    view = memoryview(piece)
                    while view:
                        written = destination.write(view)
                        if written is None or written <= 0:
                            raise OSError('evidence sink made no progress')
                        view = view[written:]
                    # Projection is only a bounded tail. Evidence bytes stay unchanged.
                    buffers[label].extend(piece)
                    if len(buffers[label]) > projection_bytes:
                        del buffers[label][:len(buffers[label])-projection_bytes]
                else:
                    buffers[label].extend(piece)
                if len(chunk) > allowed:
                    reason = 'output_limit'
                    break
            if reason:
                break
        if reason:
            termination_requested = True
            kill_group(proc, kill_wait)
        else:
            remaining = start + timeout - time.monotonic()
            try:
                proc.wait(timeout=max(.001, remaining))
            except subprocess.TimeoutExpired:
                reason = 'timeout'
                termination_requested = True
                kill_group(proc, kill_wait)
        return Result(proc.returncode, bytes(buffers['stdout']), bytes(buffers['stderr']),
                      reason, observed, time.monotonic()-start)
    finally:
        sel.close()
        if proc.poll() is None and not termination_requested:
            kill_group(proc, kill_wait)
        for stream in (proc.stdin, proc.stdout, proc.stderr):
            if stream is not None:
                stream.close()
