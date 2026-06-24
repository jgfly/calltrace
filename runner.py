"""Run a target script under the tracer and emit the HTML report."""

import os
import sys
import time
import runpy
import threading
import multiprocessing
import multiprocessing.process

from .tracer import Tracer
from .tree import collapse, count_nodes, max_depth
from .render import render_html
from .source import collect_snippets, SourceServer
from . import filters


def _patch_multiprocessing():
    """Prevent child processes from inheriting the sys.settrace hook.

    vLLM (and similar frameworks) spawn worker subprocesses via
    ``multiprocessing.Process``.  If the child inherits our ``sys.settrace``
    hook, and the child later calls ``torch.compile`` (Dynamo), Dynamo will
    walk the bytecode, encounter the trace function, follow it into
    ``time.perf_counter()`` (a C builtin), and crash with
    ``torch._dynamo.exc.Unsupported``.

    We fix this two ways:

    1. **spawn start method**: Monkey-patch ``Process.start`` to temporarily
       clear ``sys.settrace`` / ``threading.settrace`` around the original
       ``start()`` call, so the child is never created with an active trace.
    2. **fork start method**: Register an ``os.register_at_fork`` handler
       that clears the trace in the child immediately after fork.
    """
    _orig_start = multiprocessing.process.BaseProcess.start

    def _patched_start(self, *args, **kwargs):
        old_trace = sys.gettrace()
        old_thread_trace = threading.gettrace()
        sys.settrace(None)
        threading.settrace(None)
        try:
            return _orig_start(self, *args, **kwargs)
        finally:
            sys.settrace(old_trace)
            threading.settrace(old_thread_trace)

    multiprocessing.process.BaseProcess.start = _patched_start

    # Belt-and-suspenders for the fork start method (Linux/macOS only).
    if hasattr(os, "register_at_fork"):
        def _clear_after_fork():
            sys.settrace(None)
            threading.settrace(None)
        try:
            os.register_at_fork(after_in_child=_clear_after_fork)
        except (OSError, RuntimeError):
            # Already registered or not supported – fine.
            pass


def run(script, script_args, step_in_dirs, step_all_imports, output,
        collapse_loops=True, record_external=True, base_dir=None,
        serve=False, port=None):
    script = os.path.abspath(script)
    script_dir = os.path.dirname(script)

    sys.argv = [script] + list(script_args)
    if script_dir not in sys.path:
        sys.path.insert(0, script_dir)

    base = base_dir or os.getcwd()

    tracer = Tracer(step_in_dirs, step_all_imports, record_external=record_external)
    # Never trace into the calltrace tool itself.
    here = os.path.dirname(os.path.abspath(__file__))
    tracer.exclude_dirs.append(filters._norm(here))

    # Prevent child processes from inheriting our sys.settrace hook,
    # which would crash torch.compile (Dynamo) inside them.
    _patch_multiprocessing()

    start = time.perf_counter()
    sys.settrace(tracer.global_trace)
    threading.settrace(tracer.global_trace)
    exit_code = 0
    try:
        runpy.run_path(script, run_name="__main__")
    except SystemExit as e:
        exit_code = e.code if isinstance(e.code, int) else 1
    except BaseException:
        # The script crashed -- still render whatever we captured, then re-raise
        # so the user sees the original traceback.
        sys.settrace(None)
        threading.settrace(None)
        elapsed = time.perf_counter() - start
        _emit(tracer, script, output, base, elapsed, collapse_loops,
              step_in_dirs, serve, port)
        raise
    finally:
        sys.settrace(None)
        threading.settrace(None)

    elapsed = time.perf_counter() - start
    _emit(tracer, script, output, base, elapsed, collapse_loops,
          step_in_dirs, serve, port)
    return exit_code


def _emit(tracer, script, output, base, elapsed, collapse_loops,
          step_in_dirs, serve, port):
    root = tracer.root
    if collapse_loops:
        collapse(root, base=base)
    collapsed_nodes = count_nodes(root)
    depth = max_depth(root)

    # Source-on-hover: embed per-function snippets by default (offline), or bake
    # a server URL when --serve is used (no code in the HTML). In serve mode the
    # server is constructed first so its real port is known and can be baked in.
    server = None
    snippets = None
    src_url = None
    if serve:
        server = SourceServer(base, step_in_dirs, port=port or 0)
        src_url = server.url.rstrip("/")
    else:
        snippets = collect_snippets(root, base)

    html = render_html(
        root,
        script=script,
        base=base,
        raw_calls=tracer.raw_call_count,
        collapsed_nodes=collapsed_nodes,
        max_depth=depth,
        elapsed=elapsed,
        collapsed=collapse_loops,
        step_in_dirs=tracer.step_in_dirs,
        step_all_imports=tracer.step_all_imports,
        snippets=snippets,
        src_url=src_url,
    )
    with open(output, "w", encoding="utf-8") as f:
        f.write(html)

    if serve:
        server.html = html
        print(f"[calltrace] serving report at {server.url} (Ctrl+C to stop)",
              file=sys.stderr)
        server.serve_forever(open_browser=True)
