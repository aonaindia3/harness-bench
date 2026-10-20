"""Copy a finished run into results/ (committed) and pack its attempts for a GitHub release.

    python3 -m bench.publish runs/<run> [--name hermes-gpt-6-luna]

results/<name>/<suite>/{results.jsonl,config.json} go in git, so `./bench.sh report --compare
results/*/*/results.jsonl` lines every harness up. The full attempts (transcripts, screenshots,
recordings) are too big for git: they are packed into dist/<name>-<suite>.tar.gz to attach to
a release (`gh release upload <tag> dist/...`).
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import tarfile
from pathlib import Path

from bench.tasks import ROOT


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("run", help="runs/<run> directory")
    ap.add_argument("--name", help="results/<name>/ (default: <harness>-<model> from the rows)")
    args = ap.parse_args(argv)

    run = Path(args.run).resolve()
    rows = [json.loads(l) for l in (run / "results.jsonl").read_text().splitlines() if l.strip()]
    cfg = json.loads((run / "config.json").read_text())
    suite = cfg.get("suite") or rows[0]["suite"]
    models = {r.get("model") for r in rows} - {None}
    name = args.name or f"{rows[0]['harness']}-{'+'.join(sorted(models)) or 'default'}"
    name = re.sub(r"[^A-Za-z0-9._+-]", "-", name)

    dest = ROOT / "results" / name / suite
    dest.mkdir(parents=True, exist_ok=True)
    shutil.copy(run / "results.jsonl", dest / "results.jsonl")
    shutil.copy(run / "config.json", dest / "config.json")

    dist = ROOT / "dist"
    dist.mkdir(exist_ok=True)
    archive = dist / f"{name}-{suite}.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        tar.add(run, arcname=f"{name}-{suite}")
    print(f"{dest.relative_to(ROOT)}/  ({len(rows)} rows)")
    print(f"{archive.relative_to(ROOT)}  ({archive.stat().st_size / 1e6:.1f} MB) -> attach to a GitHub release")


if __name__ == "__main__":
    main()
