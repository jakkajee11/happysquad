"""git helpers (spec §17): snapshot refs, diff pathspec, tmp dir, prune."""
import os
import shutil
import subprocess

EXCLUDE = [":(exclude).happysquad", ":(exclude)knowledge"]


def git(root, *args, check=True, env=None):
    p = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, env=env)
    if check and p.returncode != 0:
        raise RuntimeError("git %s failed: %s" % (" ".join(args), p.stderr.strip()))
    return p.stdout


def is_repo(root):
    p = subprocess.run(["git", "rev-parse", "--is-inside-work-tree"], cwd=root, capture_output=True, text=True)
    return p.returncode == 0 and p.stdout.strip() == "true"


def head(root):
    p = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True)
    return p.stdout.strip() if p.returncode == 0 else None


def common_dir(root):
    return os.path.abspath(os.path.join(root, git(root, "rev-parse", "--git-common-dir").strip()))


def tmp_dir(root):
    d = os.path.join(common_dir(root), "happysquad", "tmp")
    os.makedirs(d, exist_ok=True)
    return d


def snapshot(root, ref_name):
    """Pin the working tree (tracked + untracked, honouring .gitignore) at refs/happysquad/<ref_name>.

    Uses a temp index copied from the real one so the real index is never touched.
    Returns the commit sha, or None when the repo has no commits.
    """
    if head(root) is None:
        return None
    tmp = tmp_dir(root)
    idx = os.path.join(tmp, "index-%d" % os.getpid())
    real = os.path.join(common_dir(root), "index")
    try:
        if os.path.isfile(real):
            shutil.copy(real, idx)
        env = dict(os.environ, GIT_INDEX_FILE=idx)
        # Do not name .happysquad/knowledge in the pathspec: if the repo's own .gitignore already
        # ignores them, git add errors out ("paths are ignored") even with :(exclude). Add everything
        # the ignore rules allow, then drop the two dirs from the temp index explicitly.
        git(root, "add", "-A", "--", ".", env=env)
        git(root, "rm", "-r", "-q", "--cached", "--ignore-unmatch", "--", ".happysquad", "knowledge", env=env)
        tree = git(root, "write-tree", env=env).strip()
        sha = git(root, "commit-tree", tree, "-p", "HEAD", "-m", "happysquad snapshot %s" % ref_name).strip()
        git(root, "update-ref", "refs/happysquad/%s" % ref_name, sha)
        return sha
    finally:
        try:
            os.unlink(idx)
        except OSError:
            pass


def delete_refs(root, prefix):
    out = git(root, "for-each-ref", "--format=%(refname)", "refs/happysquad/%s" % prefix, check=False)
    for ref in out.split():
        git(root, "update-ref", "-d", ref, check=False)


def changed_files(root, base_ref):
    """Tracked changes vs base_ref plus untracked, both excluding .happysquad and knowledge."""
    files = set()
    if base_ref:
        out = git(root, "diff", "--name-only", base_ref, "--", ".", *EXCLUDE, check=False)
        files.update(l for l in out.splitlines() if l)
    out = git(root, "ls-files", "--others", "--exclude-standard", "--", ".", *EXCLUDE, check=False)
    files.update(l for l in out.splitlines() if l)
    return sorted(files)


def prune(root):
    git(root, "worktree", "prune", check=False)
    d = os.path.join(common_dir(root), "happysquad", "tmp")
    if os.path.isdir(d):
        for name in os.listdir(d):
            p = os.path.join(d, name)
            if os.path.isdir(p):
                subprocess.run(["git", "worktree", "remove", "--force", p], cwd=root, capture_output=True)
                shutil.rmtree(p, ignore_errors=True)
            else:
                try:
                    os.unlink(p)
                except OSError:
                    pass
