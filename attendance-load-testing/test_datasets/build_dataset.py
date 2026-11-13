"""Build the face dataset for the load tests from a local copy of Labeled Faces in the Wild (LFW).

LFW is a public research dataset of press photographs (http://vis-www.cs.umass.edu/lfw/). It is used here, locally and
unredistributed, purely as labelled test input: several different photographs of each person, taken on different days
with different lighting, pose and expression. The images are git-ignored and never leave this machine.

    LT_LFW_DIR=<path to extracted lfw folder> python test_datasets/build_dataset.py

Output: test_datasets/faces/ and test_datasets/manifest.json
  employees  identities with >= 3 photographs: photo 1 is the enrolment reference, photos 2..4 are probes that the
             system has never seen (so a correct match is a real recognition, not an image comparison with itself)
  unknown    people with exactly one photograph who are never enrolled (must be rejected as unknown)
More candidates than LT_EMPLOYEES are written, because the application may refuse to enrol some photographs (quality,
liveness floor, or "looks like someone already enrolled"); tools/enrol.py stops at LT_EMPLOYEES successful enrolments.
"""
from __future__ import annotations

import json
import random
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from test_config import settings as S  # noqa: E402

SPARE = 1.8    # candidates = LT_EMPLOYEES * SPARE (measured: the application accepts about 58 % of LFW photographs for enrolment)
MAX_PROBES = 3


def main() -> None:
    if not S.LFW_DIR.is_dir():
        raise SystemExit("set LT_LFW_DIR to the extracted LFW folder (one sub-folder per person)")
    rng = random.Random(S.SEED)
    people = {d.name: sorted(d.glob("*.jpg")) for d in sorted(S.LFW_DIR.iterdir()) if d.is_dir()}
    multi = sorted(n for n, f in people.items() if len(f) >= 3)
    single = sorted(n for n, f in people.items() if len(f) == 1)
    rng.shuffle(multi)
    rng.shuffle(single)
    want = min(len(multi), int(S.EMPLOYEES * SPARE))   # the shuffle is seeded, so a larger SPARE only appends candidates

    employees = []
    for i, name in enumerate(multi[:want], start=1):
        code = f"LT{i:04d}"
        files = people[name]
        d = S.FACES / code
        d.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(files[0], d / "enrol.jpg")
        probes = []
        for k, f in enumerate(files[1:1 + MAX_PROBES], start=1):
            shutil.copyfile(f, d / f"probe_{k}.jpg")
            probes.append(f"faces/{code}/probe_{k}.jpg")
        employees.append({"code": code, "first_name": "Test", "last_name": f"Employee {i:04d}", "email": f"{code.lower()}@loadtest.example.com",
                          "source": name, "enrol": f"faces/{code}/enrol.jpg", "probes": probes})
    unknown = []
    (S.FACES / "unknown").mkdir(parents=True, exist_ok=True)
    for i, name in enumerate(single[:S.UNKNOWN_FACES], start=1):
        shutil.copyfile(people[name][0], S.FACES / "unknown" / f"U{i:03d}.jpg")
        unknown.append({"id": f"U{i:03d}", "source": name, "image": f"faces/unknown/U{i:03d}.jpg"})

    S.MANIFEST.write_text(json.dumps({"seed": S.SEED, "source": "LFW", "employees": employees, "unknown": unknown}, indent=1))
    print(f"{len(employees)} candidate employees ({sum(len(e['probes']) for e in employees)} probe images), {len(unknown)} unknown faces -> {S.MANIFEST}")


if __name__ == "__main__":
    main()
