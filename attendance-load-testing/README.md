# FaceGate attendance load testing (Locust)

Performance, accuracy, concurrency and data-integrity tests for the FaceGate face-attendance application, built on
[Locust](https://locust.io) (MIT). Everything in this folder is separate from the application:

- the tests run against **their own API process** (port 8010) started from the unmodified `backend/` code;
- that process uses **its own PostgreSQL** (Docker container `facegate-loadtest-pg`, port 5544) and its own encryption
  keys, so no real employee, face template or attendance record is ever read or written;
- deleting this folder and the container removes the whole thing.

The only change inside the application is a display-only page, *Admin → Locust load test*, which embeds the dashboard
that this harness serves. It calls no FaceGate API.

## What is simulated

Each virtual user is one enrolled test employee with a known identity. It follows the real kiosk protocol
(`test_scenarios/kiosk.py`, copied from `frontend/src/components/camera/useVerificationStream.ts`):

1. `POST /api/v1/verify/sessions`
2. WebSocket `/api/v1/verify/stream/{id}`: JPEG frames at 10 fps until the server answers `identified` or `rejected`
   (every frame goes through detection, quality gates, anti-spoofing, embedding and matching on the server)
3. `POST /api/v1/attendance/events` with the single-use token (`check_in` / `check_out`)

Every verdict is compared with the ground truth and written to `test_results/runs/<run>/predictions_*.jsonl`. An HTTP
200 is never counted as a correct recognition.

| Scenario | What each employee does |
|---|---|
| `attendance` | LOGIN → immediate second LOGIN (must be refused) → LOGOUT after the 120 s duplicate window → second LOGOUT (must be refused) |
| `burst` | everyone prepares, then all recognition requests are released at the same wall-clock instant |
| `sustained` | repeated scans for `--hold-seconds`; one scan in ten is by a person who is not enrolled |
| `accuracy` | every probe photo once at low load, plus unknown people, empty frames, two faces, dark / bright / blurred frames |
| `liveness` | the same photographs against the kiosk's *passive* anti-spoofing policy |

## Test data

`test_datasets/build_dataset.py` builds the dataset from a local copy of *Labeled Faces in the Wild* (press photographs,
research dataset; images are git-ignored and stay on this machine). For each identity, photo 1 is the enrolment
reference and photos 2–4 are probes taken on other occasions, so a correct match is a real recognition and not an image
compared with itself. People with a single photo are the "unknown" set and are never enrolled.

`tools/enrol.py` enrols through the application's own admin workflow (create employee, consent, enrolment stream,
save). The application decides what it accepts: photographs it judges to be spoofs, turned, covered or containing two
faces are refused and the next candidate is used.

Photographs are sent at native resolution in the middle of a 640×480 frame (`test_scenarios/frames.py`), with a
pixel-level random walk and brightness flicker between frames, as a hand-held or wall-mounted camera produces.

## Running

Prerequisites: Docker Desktop running, the application's `backend/.venv` installed, Python 3.12.

```powershell
cd attendance-load-testing
python -m venv .venv ; .venv\Scripts\pip install -r requirements.txt
docker run -d --name facegate-loadtest-pg -e POSTGRES_USER=loadtest -e POSTGRES_PASSWORD=loadtest-local-only -p 127.0.0.1:5544:5432 postgres:16-alpine -c max_connections=200

# one-off: database, dataset, enrolment, baseline snapshot
.venv\Scripts\python tools\env.py init
.venv\Scripts\python tools\env.py start
$env:LT_LFW_DIR = "C:\path\to\lfw" ; .venv\Scripts\python test_datasets\build_dataset.py
.venv\Scripts\python tools\enrol.py
.venv\Scripts\python tools\env.py snapshot

# every time
./start.ps1                                   # test API + Locust master + 4 workers
.venv\Scripts\python tools\run_suite.py       # all stages; or use the form at http://localhost:8089 for one run
.venv\Scripts\python tools\make_reports.py    # final reports from the recorded runs
./start.ps1 -Stop
```

- Live dashboard: <http://localhost:8089/facegate> (also *Admin → Locust load test* in FaceGate)
- Native Locust UI (start / stop / charts / downloads): <http://localhost:8089>
- Stages: `test_config/stages.json`. Settings: `test_config/settings.py` (every value has an `LT_…` environment override).

Each stage starts from the same baseline: `tools/env.py reset` restores the database to the post-enrolment snapshot and
restarts the test API, so attendance tables are empty and the face gallery is identical at the start of every stage.

The suite never waits on a run that has stopped: if Locust ends a stage by itself, or nothing (no request, verdict or
finished workflow) happens for 240 s, the stage is abandoned and retried, up to three attempts. Abandoned attempts keep
their folder with an `ABANDONED.txt` and are left out of the reports.

Keeping the load generator honest (it shares the machine with the server):

- Camera frames are built on a helper thread, never on a worker's event loop. Built inline, 125 users starting together
  froze a worker for over 20 s; the master then declared its workers dead and silently stopped the stage.
- The master's worker-heartbeat tolerance is raised from 3 s to 20 s for the same reason.
- OpenCV runs single-threaded in the generator, and nothing CPU-heavy should run on the machine during a stage.

## What is measured, and how

| Quantity | Source |
|---|---|
| Recognition verdict, match score, liveness score | the server's terminal WebSocket message |
| Recognition time | client clock: session request → verdict |
| Model time per frame | `timings_ms` the server reports with every analysed frame |
| Frames refused because the server was busy | `busy` replies |
| Recognitions in flight | open verification WebSockets, sampled every second in each load generator |
| Attendance write latency | `POST /attendance/events` response time |
| Stored attendance | SQL against the test database after each stage (`tools/validate_db.py`) |
| CPU / RAM | `psutil`, once a second: whole machine, the test API process, the Locust processes, everything else |
| Server responsiveness under load (deadlock check) | `tools/health_probe.py`: one `/api/health` request a second, answered by the event loop that serves recognitions; joined to each stage by time |
| Arrival times in the burst | the test API's access log, started with a timestamped log format |

Accuracy definitions (all computed in `locustfile.py: Agg.metrics`):

- **Correct identification rate** = correct ÷ genuine attempts that reached a verdict (correct + incorrect + rejected)
- **Incorrect identification rate** = matched to a different employee ÷ the same denominator
- **FRR** = genuine attempts refused ÷ the same denominator
- **FAR** = non-enrolled inputs identified as someone ÷ non-enrolled attempts that reached a verdict
- **Precision** = correct ÷ all identifications; **recall** = correct ÷ genuine attempts with a verdict; **F1** = their harmonic mean
- The **match score** is a cosine similarity between face embeddings. It is not a probability and is never reported as one.

Attempts that reach no verdict (timeouts, connection errors) are counted separately as system failures; they are a
capacity result, not a model result.

## Limits of what these tests can show

- The probes are photographs replayed as camera frames. Under the application's default *advisory* kiosk policy that is
  accepted (the anti-spoofing score is computed and logged, a frozen stream is still refused). Under the *passive*
  policy photographs are meant to be refused; the `liveness` stage measures that, it cannot measure how real faces fare.
- Load generator, API and database share one machine, so the generator's CPU is taken from the server. The hardware
  report shows how much each one used.
- LFW faces are about 110 px wide and of press-photo quality; a kiosk camera a metre away is comparable in size but
  the population, lighting and ageing of a real workforce differ.

## Removing it

```powershell
./start.ps1 -Stop
docker rm -f facegate-loadtest-pg
```

Then delete this folder. The application is unaffected.
