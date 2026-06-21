"""The sys.settrace-based tracer that builds the call tree.

How tracing actually works (and the gotcha that shapes this design)
------------------------------------------------------------------
* ``sys.settrace`` installs a *global* trace function that fires a ``'call'``
  event for **every** new Python frame in the thread -- regardless of what the
  trace function returns. Returning ``None`` only disables line/return events
  for that one frame; it does *not* stop the global trace from firing for its
  callees. (Returning ``None`` does, however, stop C-level ``c_call`` noise --
  settrace never reports C functions at all, which is why heavy torch ops incur
  no per-op trace cost.)

* ``frame.f_trace_lines = False`` suppresses per-line events for a frame, so a
  traced frame costs only one ``'call'`` + one ``'return'`` -- not one event
  per executed line.

Consequences for the design
---------------------------
* We cannot "skip into" a package by returning None -- the global trace still
  sees every nested call. Instead we decide per call, using the frame's own
  filename and its caller (``frame.f_back``):
    - project frame (under a step-in dir): record a node and trace its return.
    - external frame whose *caller* is a project frame: record a single leaf
      (the boundary call) and do not descend.
    - external frame whose caller is also external: skip entirely (it is an
      internal detail of an external package).

* Parentage is recovered by walking ``frame.f_back`` to the nearest project
  ancestor frame (looked up in a per-thread ``id(frame) -> node`` map). This
  avoids maintaining a fragile parallel stack and naturally handles exceptions.

* Threading: each thread gets its own node map and "started" flag (via
  ``threading.local``). Tree mutation is guarded by a lock. Worker threads are
  captured; their top project calls appear as separate branches under root.

* Frames before the first project frame (runpy / our own runner / import
  bootstrap) are skipped via a per-thread ``started`` flag so the report's root
  children are the script's own calls.
"""

import os
import time
import threading

from .tree import CallNode
from . import filters


class Tracer:
    def __init__(self, step_in_dirs, step_all_imports, record_external=True):
        self.step_in_dirs = [filters._norm(d) for d in step_in_dirs if d]
        self.step_all_imports = step_all_imports
        self.record_external = record_external
        self.exclude_dirs = []          # never stepped into (e.g. calltrace itself)
        self.root = CallNode(name="<root>", filename="", lineno=0)
        self.raw_call_count = 0
        self._tl = threading.local()
        self._lock = threading.Lock()
        self._step_cache = {}

    # -- thread-local state -------------------------------------------------

    def _nodes(self):
        d = getattr(self._tl, "nodes", None)
        if d is None:
            d = {}
            self._tl.nodes = d
        return d

    def _started(self):
        return getattr(self._tl, "started", False)

    # -- path decisions -----------------------------------------------------

    def _excluded(self, fnorm):
        for d in self.exclude_dirs:
            if fnorm == d or fnorm.startswith(d + os.sep):
                return True
        return False

    def _compute_step(self, filename):
        if not filename or filename.startswith("<"):
            return False
        f = filters._norm(filename)
        if self._excluded(f):
            return False
        # Anything in site-packages is a third-party dependency, never "the
        # project" -- even when the venv physically lives under the project
        # directory (e.g. ./project/.venv). Only descend with --step-all-imports.
        if filters.is_sitepackage(filename):
            return self.step_all_imports
        for d in self.step_in_dirs:
            if f == d or f.startswith(d + os.sep):
                return True
        if self.step_all_imports and not filters.is_stdlib(filename):
            return True
        return False

    def _should_step_in(self, filename):
        v = self._step_cache.get(filename)
        if v is None:
            v = self._compute_step(filename)
            self._step_cache[filename] = v
        return v

    def _parent_node(self, frame):
        """Nearest recorded project ancestor of ``frame`` (or root)."""
        nodes = self._nodes()
        f = frame.f_back
        while f is not None:
            node = nodes.get(id(f))
            if node is not None:
                return node
            f = f.f_back
        return self.root

    # -- trace events -------------------------------------------------------

    def _on_call(self, frame):
        # Suppress per-line events; we only need call/return.
        frame.f_trace_lines = False

        code = frame.f_code
        filename = code.co_filename
        name = getattr(code, "co_qualname", code.co_name)
        lineno = code.co_firstlineno
        step = self._should_step_in(filename)

        if step:
            self._tl.started = True
            node = CallNode(name=name, filename=filename, lineno=lineno, external=False)
            node.t0 = time.perf_counter()
            parent = self._parent_node(frame)
            with self._lock:
                parent.add_child(node)
                self.raw_call_count += 1
            self._nodes()[id(frame)] = node
            return self._local_trace

        # External frame.
        if not self._started() or not self.record_external:
            return None
        # Record only the boundary call: caller must be a project frame.
        caller = frame.f_back
        parent_node = self._nodes().get(id(caller)) if caller is not None else None
        if parent_node is not None:
            node = CallNode(name=name, filename=filename, lineno=lineno, external=True)
            with self._lock:
                parent_node.add_child(node)
                self.raw_call_count += 1
        return None

    def _on_return(self, frame):
        node = self._nodes().pop(id(frame), None)
        if node is not None:
            node.duration += time.perf_counter() - node.t0

    # -- trace functions ----------------------------------------------------

    def global_trace(self, frame, event, arg):
        if event == "call":
            return self._on_call(frame)
        return None

    def _local_trace(self, frame, event, arg):
        if event == "return":
            self._on_return(frame)
            return self._local_trace
        return self._local_trace
