# calltrace

Record the **call stack** of any Python script or CLI into a single, readable,
collapsible **HTML report**. Loops are auto-collapsed to a repeat count, so a
500-token generation that walks the same code path 500 times shows up as one
branch with a `×500` badge instead of 500 copies.

## Install / use

No install needed — run it as a module from the project root:

```bash
# basic: trace example.py, step into everything under the script's directory
python -m calltrace example.py

# with forwarded script args
python -m calltrace example.py --foo bar

# explicit project dir + custom output
python -m calltrace --project /data/code/nano-vllm-main -o report.html example.py
```

Open the generated `calltrace_report.html` in a browser.

## What gets traced

By default calltrace **steps all the way into the target project** (the script's
own directory, or whatever `--project` you pass) and records calls *into* other
packages (torch, transformers, stdlib, …) as **leaf nodes marked `ext`** — you
see that the call happened, but not the package's internals.

```
--project DIR          Directory whose code is stepped into (repeatable).
                       Default: the directory containing the script.
--step-all-imports     Also descend into every non-stdlib import
                       (torch/transformers/…). Much slower, much bigger.
--no-external-leaves   Don't record `ext` leaves at all — only project-internal
                       calls. Fastest, most focused.
--no-collapse          Emit the raw call tree (no loop collapsing).
-o, --output FILE      Output HTML path (default: ./calltrace_report.html).
```

> Options must come **before** the script name (anything after the script is
> forwarded to it verbatim).

## How loop collapsing works

The tracer builds a literal call tree (one node per call). After the run it
collapses:

1. **Run-length merge** — consecutive identical subtrees become one node with a
   repeat count. `generate_one_token` called 512 times → `generate_one_token ×512`.
2. **Periodic grouping** — a fully periodic run of children (a multi-call loop
   body like `[a(), b()]` repeated) is wrapped in a `↻ loop ×N` block.

So the report stays small and skimmable even for long, repetitive runs.

## Requirements 1–5 mapping

1. **Loop count, not per-iteration paths** → run-length + periodic collapse.
2. **Step into the project to the innermost layer; skip other imports** →
   default behavior (project dir only). `--step-all-imports` opts into all
   non-stdlib imports.
3. **HTML, readable & aesthetic** → self-contained dark-theme collapsible tree
   with stats, expand/collapse-all, and a function-name filter.
4. **Works for any script/CLI launch, not just this project** → generic
   `runpy`-based runner; point `--project` wherever you like.
5. **Project folder saved in the current directory** → `calltrace/` lives next
   to your code.

## Notes / limitations

- Tracing adds overhead proportional to the number of *Python* function calls
  (C-level ops like `torch.matmul` are not traced by `sys.settrace`, so heavy
  compute is cheap to trace). For a full model run, prefer `--no-external-leaves`
  and a small `max_tokens`.
- Worker threads are captured (top-level project calls from each thread appear
  as separate branches under the root).
- External (`ext`) leaves do not carry a duration (only their enclosing project
  call is timed).
