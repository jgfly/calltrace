"""Run a target script under the tracer and emit the HTML report."""

import os
import sys
import time
import runpy
import threading

from .tracer import Tracer
from .tree import collapse, count_nodes, max_depth
from .render import render_html
from . import filters


def run(script, script_args, step_in_dirs, step_all_imports, output,
        collapse_loops=True, record_external=True, base_dir=None):
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
        _emit(tracer, script, output, base, elapsed, collapse_loops)
        raise
    finally:
        sys.settrace(None)
        threading.settrace(None)

    elapsed = time.perf_counter() - start
    _emit(tracer, script, output, base, elapsed, collapse_loops)
    return exit_code


def _emit(tracer, script, output, base, elapsed, collapse_loops):
    root = tracer.root
    if collapse_loops:
        collapse(root, base=base)
    collapsed_nodes = count_nodes(root)
    depth = max_depth(root)
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
    )
    with open(output, "w", encoding="utf-8") as f:
        f.write(html)
