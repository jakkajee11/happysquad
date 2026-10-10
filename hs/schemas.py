"""out.json contracts (spec §6). Source of truth for validate, advance and {{out_schema}}.

Tiny schema language (no jsonschema dependency):
  "str" | "int" | "bool" | "dict" | "any"
  enum(a, b)            one of the literals
  list_of(spec)         list whose items match spec
  obj(k=spec, ...)      dict with exactly these keys (missing required -> error, unknown -> error)
  opt(spec)             key may be absent
  nullable(spec)        value may be null
"""
import fnmatch
import json


def enum(*vals):
    return ("enum", list(vals))


def list_of(spec):
    return ("list_of", spec)


def obj(**fields):
    return ("obj", fields)


def opt(spec):
    return ("opt", spec)


def nullable(spec):
    return ("nullable", spec)


_SIMPLE = {"str": str, "int": int, "bool": bool, "dict": dict}


def _check(value, spec, path, errors):
    if isinstance(spec, str):
        if spec == "any":
            return
        t = _SIMPLE[spec]
        if spec == "int" and isinstance(value, bool):
            errors.append("%s: expected int, got bool" % path)
        elif not isinstance(value, t):
            errors.append("%s: expected %s, got %s" % (path, spec, type(value).__name__))
        return
    kind, arg = spec
    if kind == "nullable":
        if value is None:
            return
        _check(value, arg, path, errors)
    elif kind == "opt":
        # an optional key set to null means "not used" — agents write that instead of omitting the key,
        # and rejecting it cost a whole re-dispatch (seen live: implementer build_cmds/unmet_ac null)
        if value is not None:
            _check(value, arg, path, errors)
    elif kind == "enum":
        if value not in arg:
            errors.append("%s: expected one of %s, got %r" % (path, arg, value))
    elif kind == "list_of":
        if not isinstance(value, list):
            errors.append("%s: expected list, got %s" % (path, type(value).__name__))
            return
        for i, item in enumerate(value):
            _check(item, arg, "%s[%d]" % (path, i), errors)
    elif kind == "obj":
        if not isinstance(value, dict):
            errors.append("%s: expected object, got %s" % (path, type(value).__name__))
            return
        for k, sub in arg.items():
            if k not in value:
                if isinstance(sub, tuple) and sub[0] == "opt":
                    continue
                errors.append("%s: missing key %r" % (path, k))
                continue
            _check(value[k], sub, "%s.%s" % (path, k), errors)
        for k in value:
            if k not in arg:
                errors.append("%s: unknown key %r" % (path, k))
    else:
        raise ValueError("bad spec kind %r" % kind)


def validate(value, spec):
    errors = []
    _check(value, spec, "$", errors)
    return errors


# --- the contracts -----------------------------------------------------------

TAGS = ("REQ", "SEC", "PERF", "STD", "SIMPL", "TEST", "CONFLICT")
ROUTES = ("implementer", "tester", "architecter")

AC = obj(id="str", text="str")
UNTESTABLE = obj(ac="str", reason="str")
# an AC only a person can confirm (real-device render, a Builder-run harness): the loop builds it, the
# run still COMPLETEs, and the `done` action lists it for a human to tick (HUMAN-CHECK.md)
NEEDS_HUMAN = obj(ac="str", reason="str", how="str")
# a tester-proposed mutant: replace `find` (exactly once) with `replace` in `file`; one of `tests` must go red
MUTATION = obj(ac="str", file="str", find="str", replace="str", tests=list_of("str"))
WORKSTREAM = obj(name="str", owned=list_of("str"), depends_on=opt(list_of("str")), ac=list_of("str"))

ARCHITECT = obj(
    phase=enum("ARCHITECT"),
    size=enum("S", "M", "L"),
    design="str",
    ac=list_of(AC),
    untestable=opt(list_of(UNTESTABLE)),
    needs_human=opt(list_of(NEEDS_HUMAN)),
    workstreams=list_of(WORKSTREAM),
    test_owned=opt("dict"),
)
# keys an older prompt asked for that nothing reads; dropped before validation instead of failing it
RETIRED = {"ARCHITECT": ("assumptions", "shared_read_only")}
# design.md word caps by size: every later phase reads design.md, so length is a per-dispatch cost.
# Real runs (2026-10-10): S median ~1,600 words, M ~2,100, for a median of 4 owned files.
DESIGN_WORDS = {"S": 600, "M": 1500, "L": 3000}

IMPLEMENT = obj(
    phase=enum("IMPLEMENT"),
    workstream=nullable("str"),
    files=list_of("str"),
    build_cmds=opt(list_of("str")),
    unmet_ac=opt(list_of(obj(id="str", reason="str"))),
    design_conflict=opt(nullable("str")),
    ownership_gap=opt(nullable(obj(file="str", reason="str"))),
)

TEST = obj(
    phase=enum("TEST"),
    workstream=nullable("str"),
    test_cmds=opt(list_of("str")),
    coverage_report=opt(nullable("str")),
    test_files=list_of("str"),
    new_tests=list_of("str"),
    ac_map="dict",
    untestable=opt(list_of(UNTESTABLE)),
    redgreen=opt(nullable("str")),
    mutations=opt(list_of(MUTATION)),
    findings=opt(list_of(obj(ac="str", desc="str"))),
)

FINDING = obj(
    id="str",
    prior_id=opt(nullable("str")),
    severity=enum("blocker", "major", "minor"),
    tag=enum(*TAGS),
    file=nullable("str"),
    line=opt(nullable("int")),
    desc="str",
    route=enum(*ROUTES),
    workstream=opt(nullable("str")),
    verify="str",
    source=opt("str"),
)

REVIEW = obj(
    phase=enum("REVIEW"),
    mode=enum("single", "split-on-risk", "delta"),
    report="str",
    findings=list_of(FINDING),
    overrides=opt(list_of(obj(id="str", reason="str"))),
    axes=opt("dict"),
    confirmed_fixes=opt(list_of("str")),
)

SPECIALIST_FINDING = obj(
    id="str",
    severity=enum("blocker", "major", "minor"),
    file=nullable("str"),
    line=opt(nullable("int")),
    desc="str",
)

SPECIALIST = obj(
    phase=enum("SPECIALIST"),
    axis=enum("sec", "perf"),
    report="str",
    findings=list_of(SPECIALIST_FINDING),
)

BY_PHASE = {
    "ARCHITECT": ARCHITECT,
    "IMPLEMENT": IMPLEMENT,
    "TEST": TEST,
    "REVIEW": REVIEW,
    "SPECIALIST": SPECIALIST,
}


# --- semantic checks (beyond shape) ------------------------------------------

def _globs_overlap(a, b):
    return a == b or fnmatch.fnmatch(a, b) or fnmatch.fnmatch(b, a)


def _has_cycle(ws):
    deps = {w["name"]: set(w.get("depends_on") or []) for w in ws}
    seen, stack = set(), set()

    def visit(n):
        if n in stack:
            return True
        if n in seen:
            return False
        stack.add(n)
        for d in deps.get(n, ()):
            if visit(d):
                return True
        stack.discard(n)
        seen.add(n)
        return False

    return any(visit(n) for n in deps)


def semantic_architect(out):
    errs = []
    ws = out["workstreams"]
    names = [w["name"] for w in ws]
    if len(set(names)) != len(names):
        errs.append("workstreams: duplicate names")
    for w in ws:
        for d in w.get("depends_on") or []:
            if d not in names:
                errs.append("workstream %s: depends_on unknown %r" % (w["name"], d))
    if _has_cycle(ws):
        errs.append("workstreams: depends_on is not a DAG")
    for i, a in enumerate(ws):
        for b in ws[i + 1:]:
            for pa in a["owned"]:
                for pb in b["owned"]:
                    if _globs_overlap(pa, pb):
                        errs.append("ownership overlap: %s and %s both own %r/%r" % (a["name"], b["name"], pa, pb))
    ac_ids = {a["id"] for a in out["ac"]}
    covered = {x for w in ws for x in w["ac"]} | {u["ac"] for u in out.get("untestable") or []}
    for h in out.get("needs_human") or []:
        if h["ac"] not in ac_ids:
            errs.append("needs_human references unknown AC %s" % h["ac"])
    for ac in sorted(ac_ids - covered):
        errs.append("AC %s is in no workstream and not marked untestable" % ac)
    for ac in sorted(covered - ac_ids):
        errs.append("workstream/untestable references unknown AC %s" % ac)
    return errs


def semantic_test(out, required_ac):
    """required_ac: AC ids this workstream must map, minus untestable."""
    errs = []
    untestable = {u["ac"] for u in out.get("untestable") or []}
    for ac in required_ac:
        if ac in untestable:
            continue
        tests = out["ac_map"].get(ac)
        if not tests:
            errs.append("ac_map: AC %s has no test" % ac)
    return errs


def semantic(phase, out, state=None, workstream=None):
    if phase == "ARCHITECT":
        return semantic_architect(out)
    if phase == "TEST" and state is not None:
        req = []
        for w in state.get("workstreams", []):
            if workstream is None or w["name"] == workstream:
                req.extend(w.get("ac", []))
        skip = {u["ac"] for u in state.get("untestable", [])} | {h["ac"] for h in state.get("needs_human", [])}
        return semantic_test(out, [a for a in req if a not in skip])
    return []


def design_length(out, design_path):
    """design.md over its size cap → one error naming the counts; missing file → no error (shape owns that)."""
    try:
        with open(design_path, errors="replace") as f:
            n = len(f.read().split())
    except OSError:
        return []
    cap = DESIGN_WORDS.get(out.get("size"))
    if cap and n > cap:
        return ["design.md is %d words; size %s allows %d — cut to AC, owned files and the decisions the "
                "implementer can't infer from the repo" % (n, out["size"], cap)]
    return []

def check(phase, out, state=None, workstream=None, design_path=None):
    """Shape + semantics (+ design length for ARCHITECT when design_path is given). Empty list = valid."""
    spec = BY_PHASE.get(phase)
    if spec is None:
        return ["unknown phase %r" % phase]
    if isinstance(out, dict):
        for k in RETIRED.get(phase, ()):
            out.pop(k, None)
    errs = validate(out, spec)
    if errs:
        return errs
    errs = semantic(phase, out, state, workstream)
    if not errs and phase == "ARCHITECT" and design_path:
        errs = design_length(out, design_path)
    return errs


# --- rendering for prompts ---------------------------------------------------

def _skeleton(spec):
    if isinstance(spec, str):
        return {"str": "<string>", "int": 0, "bool": False, "dict": {}, "any": "<any>"}[spec]
    kind, arg = spec
    if kind == "enum":
        return "|".join(str(a) for a in arg)
    if kind == "list_of":
        return [_skeleton(arg)]
    if kind == "obj":
        return {k: _skeleton(v) for k, v in arg.items()}
    if kind == "opt":
        return _skeleton(arg)
    if kind == "nullable":
        return _skeleton(arg)
    raise ValueError(kind)


def render(phase):
    """JSON skeleton of the phase's out.json for the {{out_schema}} prompt var."""
    return json.dumps(_skeleton(BY_PHASE[phase]), indent=2)
