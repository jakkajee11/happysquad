"""Per-run state.json + events.jsonl with flock and atomic writes (spec §5).

Rules enforced here:
- every write goes tmp -> fsync -> os.replace
- `commit()` appends the event BEFORE saving state
- one `locked()` per mutating command; never nest (flock is per open file description)
- `now()` honours HS_NOW so tests can drive the clock
"""
import contextlib
import datetime
import fcntl
import json
import os
import tempfile

HS_DIR = ".happysquad"


def now():
    forced = os.environ.get("HS_NOW")
    if forced:
        return forced
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_ts(ts):
    return datetime.datetime.fromisoformat(ts.replace("Z", "+00:00"))


# --- paths -------------------------------------------------------------------

def hs_dir(root):
    return os.path.join(root, HS_DIR)


def runs_dir(root):
    return os.path.join(hs_dir(root), "runs")


def run_dir(root, run_id):
    return os.path.join(runs_dir(root), run_id)


def current_run_id(root):
    p = os.path.join(hs_dir(root), "current")
    if not os.path.isfile(p):
        return None
    with open(p) as f:
        rid = f.read().strip()
    return rid or None


def set_current(root, run_id):
    atomic_write(os.path.join(hs_dir(root), "current"), run_id + "\n")


# --- atomic io ---------------------------------------------------------------

def atomic_write(path, text):
    d = os.path.dirname(path) or "."
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".tmp-", dir=d)
    try:
        with os.fdopen(fd, "w") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def atomic_write_json(path, obj):
    atomic_write(path, json.dumps(obj, indent=2, ensure_ascii=False) + "\n")


def read_json(path, default=None):
    if not os.path.isfile(path):
        return default
    with open(path) as f:
        return json.load(f)


# --- lock --------------------------------------------------------------------

@contextlib.contextmanager
def locked(rdir):
    """Exclusive lock for the run directory. Hold it for the whole mutating command."""
    os.makedirs(rdir, exist_ok=True)
    with open(os.path.join(rdir, ".lock"), "a+") as lf:
        fcntl.flock(lf, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lf, fcntl.LOCK_UN)


# --- events ------------------------------------------------------------------

def append_event(rdir, event, **data):
    rec = {"ts": now(), "event": event}
    rec.update(data)
    line = json.dumps(rec, ensure_ascii=False)
    with open(os.path.join(rdir, "events.jsonl"), "a") as f:
        f.write(line + "\n")
        f.flush()
        os.fsync(f.fileno())
    return rec


def read_events(rdir):
    p = os.path.join(rdir, "events.jsonl")
    if not os.path.isfile(p):
        return []
    out = []
    with open(p) as f:
        for line in f:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


# --- state -------------------------------------------------------------------

def state_path(rdir):
    return os.path.join(rdir, "state.json")


def load_state(rdir):
    return read_json(state_path(rdir))


def save_state(rdir, st):
    st["updated_at"] = now()
    atomic_write_json(state_path(rdir), st)


def commit(rdir, st, event, **data):
    """Event first, then state. A crash between the two leaves a replayable event."""
    append_event(rdir, event, **data)
    save_state(rdir, st)
