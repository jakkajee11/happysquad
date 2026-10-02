"""Command provenance (spec §7.0): config commands are authoritative; agent commands must be a
full-argv-prefix extension of one, or a bare grep/rg/test for verify. Never shell=True.
"""
import os
import shlex
import signal
import subprocess
import time

REJECT_TOKENS = {"sh", "bash", "zsh", "env", "xargs", "npx", "dlx", "exec", "run", "x", "eval",
                 "--", "-c", "-e", "sudo"}
REJECT_PAIRS = {("pnpm", "dlx"), ("npm", "exec"), ("yarn", "dlx"), ("python", "-c"), ("python3", "-c"),
                ("node", "-e")}
SHELL_META = ("|", ";", "&&", "||", ">", "<", "$(", "`")
VERIFY_BINS = {"grep", "rg", "test", "["}


def split(cmd):
    try:
        return shlex.split(cmd)
    except ValueError:
        return None


def classify(cmd, config_cmds, allowed_flags, for_verify=False):
    """Return (ok: bool, reason: str). `config_cmds` are the raw config command strings."""
    argv = split(cmd)
    if not argv:
        return False, "empty or unparseable"
    negate = argv[0] == "!"
    if negate:
        argv = argv[1:]
        if not argv:
            return False, "bare !"
    for tok in argv:
        if any(m in tok for m in SHELL_META):
            return False, "shell metacharacter in %r" % tok
        if tok in REJECT_TOKENS:
            return False, "rejected token %r" % tok
    for a, b in zip(argv, argv[1:]):
        if (a, b) in REJECT_PAIRS:
            return False, "rejected pair %s %s" % (a, b)
    if for_verify and argv[0] in VERIFY_BINS:
        if argv[0] in ("grep", "rg") and any(t in ("-f", "--file") for t in argv):
            return False, "verify grep with -f"
        return True, "verify-bin"
    for c in config_cmds:
        cargv = split(c or "") or []
        if not cargv:
            continue
        if argv[: len(cargv)] == cargv:
            extra = argv[len(cargv):]
            for t in extra:
                if t.startswith("-") and t.split("=")[0] not in allowed_flags:
                    return False, "flag %r not in allowed_flags" % t
            return True, "config-prefix"
    return False, "not a prefix of any config command"


def run(argv, cwd, timeout, log_path=None, env=None):
    """Run argv without a shell in its own process group; kill the group on timeout.

    Returns (exit_code, output_text). exit -9 on timeout.
    """
    out_chunks = []
    p = subprocess.Popen(argv, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         text=True, start_new_session=True, env=env)
    try:
        out, _ = p.communicate(timeout=timeout)
        out_chunks.append(out or "")
        code = p.returncode
    except subprocess.TimeoutExpired:
        try:
            os.killpg(p.pid, signal.SIGKILL)
        except OSError:
            pass
        out, _ = p.communicate()
        out_chunks.append(out or "")
        out_chunks.append("\n[hs] killed after %ss timeout\n" % timeout)
        code = -9
    text = "".join(out_chunks)
    if log_path:
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        with open(log_path, "w") as f:
            f.write(text)
    return code, text


def run_cmd(cmd, cwd, timeout, log_path=None, env=None):
    """Run a trusted command string (config or already-classified). Handles leading `!`."""
    argv = split(cmd)
    negate = argv and argv[0] == "!"
    if negate:
        argv = argv[1:]
    started = time.time()
    code, text = run(argv, cwd, timeout, log_path, env=env)
    if negate and code != -9:
        code = 0 if code != 0 else 1
    return code, text, round(time.time() - started, 1)
