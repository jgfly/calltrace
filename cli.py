"""Command-line entry point for calltrace."""

import argparse
import os
import sys

from .runner import run


def build_parser():
    p = argparse.ArgumentParser(
        prog="calltrace",
        description=(
            "Record the call stack of a Python script/CLI into a readable, "
            "collapsible HTML report. Loops are auto-collapsed to a repeat count."
        ),
    )
    p.add_argument(
        "script",
        help="Path to the Python script to run (e.g. example.py).",
    )
    p.add_argument(
        "script_args",
        nargs=argparse.REMAINDER,
        help="Arguments forwarded verbatim to SCRIPT.",
    )
    p.add_argument(
        "--project", action="append", default=[], metavar="DIR",
        help=(
            "Directory whose code should be stepped into (repeatable). "
            "Default: the directory containing SCRIPT."
        ),
    )
    p.add_argument(
        "--step-all-imports", action="store_true",
        help=(
            "Also step into every non-stdlib imported package "
            "(e.g. torch, transformers). Off by default for speed and focus."
        ),
    )
    p.add_argument(
        "--no-external-leaves", action="store_true",
        help=(
            "Do not record calls into external packages at all (faster, "
            "but the stack only shows project-internal calls)."
        ),
    )
    p.add_argument(
        "--no-collapse", action="store_true",
        help="Disable loop collapsing; emit the raw call tree.",
    )
    p.add_argument(
        "-o", "--output", default=None,
        help="Output HTML path (default: ./calltrace_report.html).",
    )
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)

    script = os.path.abspath(args.script)
    if not os.path.isfile(script):
        print(f"calltrace: script not found: {script}", file=sys.stderr)
        return 2

    script_dir = os.path.dirname(script)
    step_in_dirs = [os.path.abspath(d) for d in args.project] or [script_dir]
    if script_dir not in step_in_dirs:
        step_in_dirs.append(script_dir)

    output = args.output or os.path.join(os.getcwd(), "calltrace_report.html")

    exit_code = run(
        script=script,
        script_args=args.script_args,
        step_in_dirs=step_in_dirs,
        step_all_imports=args.step_all_imports,
        output=output,
        collapse_loops=not args.no_collapse,
        record_external=not args.no_external_leaves,
    )
    print(f"[calltrace] report written to: {output}", file=sys.stderr)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
