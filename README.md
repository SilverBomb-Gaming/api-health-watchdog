# api-watch by Alfredo Cardona (SilverBomb-Gaming)

A local-first CLI that reads a YAML or JSON file of HTTP(S) endpoints, records pass/fail and latency, and alerts when a check fails.

The pass/fail decision is the status code and the clock. No model is required. `--summarize` is optional: when a check has already failed, [Ollama](https://ollama.com) on your machine (`llama3.2`) can write a short summary. No cloud API key is required for that path. Check results stay on localhost unless you opt into an OpenAI-compatible endpoint or set a webhook URL.

The installable project name is `api-health-watchdog`. The command is `api-watch`.

Built by Alfredo Cardona ([SilverBomb-Gaming](https://github.com/SilverBomb-Gaming)).

## In the owner's words

<!-- Replace this paragraph after merge. It is the one spot left for a human voice. -->

I wanted a health check I could run from a laptop without a hosted monitor. The pass/fail decision is the status code and the clock, not a model. `--summarize` only runs after something failed, and a sentence that names an endpoint, status, or latency this run did not record is dropped. That limitation is the one I would explain first.

## What it is / isn't

**It is** a portfolio CLI for one job: probe the URLs in a config file, print a table (or JSON), exit non-zero when any target fails, and optionally POST that same JSON to a webhook. Each row is one request this process made. A timeout or a connection error is a failure with a reason. Latency is the time this process measured.

**It isn't** a hosted status page, a Slack or email client, or a writer that may invent endpoints, status codes, or latencies. If `--summarize` is on and the model cites a fact this run did not record, that sentence is dropped. If nothing usable remains, the tool prints a summary built from the check results it already has. The table is the measurement.

## Demo

You will need Python 3.11+. Ollama is only required for the last command. The dry run does not use the network. The live demo uses a local fixture server, so it does not need httpbin, an API key, or any secret.

```bash
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e .
```

Validate the public sample and print the checks that would run. This does not send a request and it does not call a model:

```bash
api-watch check --config samples/endpoints.yaml --dry-run
```

```text
Planned checks (3) from samples/endpoints.yaml
- httpbin-ok  GET  https://httpbin.org/status/200  expect 200  timeout 10s  headers: -
- httpbin-server-error  GET  https://httpbin.org/status/500  expect 200  timeout 10s  headers: -
- httpbin-headers  GET  https://httpbin.org/headers  expect 200  timeout 10s  headers: X-Demo-Client, X-Request-Source
Config ok. No requests sent.
```

Header names are printed. Header values are not. `samples/endpoints.json` is the same list.

Run the same idea against a server on your machine. In one terminal:

```bash
python samples/fixture_server.py
```

That listens on `http://127.0.0.1:8765`. Routes: `/ok` returns 200, `/fail` returns 500, `/slow` returns 200 after 2 seconds. Ctrl+C stops it.

In another terminal:

```bash
api-watch check --config samples/local.yaml
```

`local-ok` passes. `local-fail` fails because the body came back 500 and the config expects 200. `local-slow` fails because the timeout is 1 second. The process exits 1. Failure lines also go to stderr as `ALERT ...`. The same document is written to `.api-watch/last-results.json`.

JSON on stdout, still no model:

```bash
api-watch check --config samples/local.yaml --json --no-save
```

Repeat until Ctrl+C. Ctrl+C prints `Stopped.` and exits 0, including when the latest cycle had failures. Use `check` in a script when you want a non-zero exit.

```bash
api-watch watch --config samples/local.yaml --interval 30
```

With Ollama, summarize only the failures. A passing run does not call the model:

```bash
ollama pull llama3.2
api-watch check --config samples/local.yaml --summarize
```

`samples/endpoints.yaml` is the public-URL variant (`https://httpbin.org/status/200`, `/status/500`, and `/headers`). It is safe to commit. It can be slow or rate-limited, which is why the fixture server is the demo above.

## How a run is built

```text
config  ──►  HTTP probe  ──►  table or JSON  ──►  stderr alert, exit 1, optional webhook
(yaml/json)   (this program)    (this program)     (this program)

failures only  ──►  optional model  ──►  drop invented facts  ──►  summary
                    (Ollama by default)   (this program)
```

1. **Load.** UTF-8 YAML or JSON. Unknown keys, duplicate names, bad URLs, and missing secret env vars fail here, before any socket opens. `--dry-run` stops after printing the plan.
2. **Probe.** One request per target, in order. The expected status defaults to 200. The method defaults to GET. Redirects are followed, and the final status is the one that is compared. A timeout, a connection error, or any other request error is a failed row with `status_code: null` and a reason. One bad target does not cancel the rest.
3. **Record.** Stdout is the table, or one JSON document with `--json`. The last run is also written to `.api-watch/last-results.json` unless you pass `--no-save` or `--results`.
4. **Alert.** Each failure is one `ALERT` line on stderr. The process exits 1. If `API_WATCH_WEBHOOK_URL` is set, that same JSON is POSTed. A webhook error is a warning. It does not replace the check result.
5. **Summarize, when you ask.** `--summarize` builds an Ollama client only when at least one check failed. The model receives only those failed rows and must return JSON. The system prompt forbids inventing endpoints, status codes, or latencies that are not in the check results. Those sentences are pinned by `tests/test_prompts.py`.
6. **Check in code.** A summary line is kept only when its `name` is a failed target in this run, every URL in the sentence is that target's URL, every status code is that target's `expected_status` or `status_code`, and every latency written with `ms` matches that target's `latency_ms`. Anything else is dropped. `tests/test_guard.py` pins this.
7. **Fall back.** Unusable model output, or output with no grounded lines, is replaced by a summary this program renders from the recorded rows. A warning goes to stderr. If Ollama is down, the checks still stand: you get the recorded summary and the same exit code.

`--dry-run` stops after step 1. It does not write the results file.

`watch` reloads the config every cycle, prints each run, and sleeps `--interval` seconds. A failed cycle does not stop the loop. A config error on the first cycle exits 2. A later config error is printed and the loop continues, so you can fix the file without restarting. Ctrl+C exits 0.

## Config

```yaml
targets:
  - name: billing
    url: https://example.test/health
    method: GET              # default GET
    expect_status: 200       # default 200. expected_status is an alias
    timeout_seconds: 10      # default 10. timeout is an alias
    headers:
      Accept: application/json
      Authorization: ${API_TOKEN}                 # required env var
      X-Request-Source: ${API_WATCH_SOURCE:-local-demo}
      X-Region: env:REGION                        # same idea, env:NAME form
```

| Field | Default | Rule |
| --- | --- | --- |
| `name` | required | Unique, non-empty |
| `url` | required | Absolute `http://` or `https://` |
| `method` | `GET` | `GET`, `HEAD`, `POST`, `PUT`, `PATCH`, `DELETE`, `OPTIONS` |
| `expect_status` | `200` | Integer from 100 to 599. Alias: `expected_status` |
| `timeout_seconds` | `10` | Positive number of seconds. Alias: `timeout` |
| `headers` | none | Mapping of header name to string |

A header value is read from the environment only when the **whole** value is a reference: `${NAME}`, `${NAME:-default}`, or `env:NAME`. `Bearer ${API_TOKEN}` is sent literally and is not expanded. That is deliberate, so a half-written value cannot silently pick up a secret. Do not commit secret values. Put them in the environment or in a gitignored `.env`.

The samples set `X-Request-Source` to `${API_WATCH_SOURCE:-local-demo}`, so they load with no env file. `X-Demo-Client: api-watch` is a literal, not a secret.

There is no request body. An empty POST is as far as this version goes.

The client sends `User-Agent: api-watch/0.1.0` unless the config sets `User-Agent`.

## Output

Human output is a table. `PASS` / `FAIL`, the status or `-` when there was no response, the measured latency, and the reason:

```text
2026-09-23T20:46:00Z  samples/local.yaml
NAME        RESULT  STATUS  LATENCY   DETAIL
----------  ------  ------  --------  ------------------------------
local-ok    PASS    200     4.0 ms
local-fail  FAIL    500     3.0 ms    expected status 200, got 500
local-slow  FAIL    -       1000.2 ms timeout after 1s
```

The latency column is filled for timeouts too: it is how long this process waited, not a status code. `-` in STATUS means no HTTP status was observed.

`--json` on `check` prints one pretty JSON document. `--json` on `watch` prints one compact JSON object per cycle. The results file is pretty JSON either way.

```json
{
  "checked_at": "2026-09-23T20:46:00Z",
  "config": "samples/local.yaml",
  "ok": false,
  "failure_count": 2,
  "results": [
    {
      "name": "local-ok",
      "url": "http://127.0.0.1:8765/ok",
      "method": "GET",
      "ok": true,
      "expected_status": 200,
      "status_code": 200,
      "latency_ms": 4.0,
      "error": null
    }
  ],
  "results_path": ".api-watch/last-results.json"
}
```

`--summarize` adds `summary` and `summary_source`. `summary_source` is `model` (every printed sentence passed the check), `recorded` (the program wrote the lines from the results), or `skipped` (nothing failed, so the model was not called). `summary` is `null` when the source is `skipped`. Passing rows are not included in the model input.

Stderr, not the JSON document, carries `ALERT` lines, `Saved ...`, and `warning:` lines. A webhook failure is one of those warnings.

## Results file

Each run replaces `.api-watch/last-results.json` in the current working directory. The directory is gitignored. `--results PATH` chooses another file. `--no-save` writes nothing. `--dry-run` writes nothing. `--results` and `--no-save` together are an error.

The file is the same object printed by `--json`, so a later command can open the last run without probing again. This is a single file, not a time-series database.

## Alerting

1. The failing rows are printed to stderr: `ALERT local-fail: expected status 200, got 500`.
2. `check` exits 1 when any row failed. `watch` keeps looping.
3. If `API_WATCH_WEBHOOK_URL` is set, the run JSON is POSTed with `Content-Type: application/json` only when at least one check failed. There is no Slack SDK and no email SDK. Point the variable at a Slack incoming webhook, a generic automation URL, or anything else that accepts a JSON POST.

A webhook timeout or a non-2xx response is a warning on stderr. The exit code still comes from the checks.

## Configuration

Copy `.env.example` to `.env` in the working directory (the directory you run the command from), or export the variables yourself. Existing environment variables win over `.env`. `.env` is gitignored.

| Variable | Default | Role |
| --- | --- | --- |
| `OLLAMA_BASE_URL` | `http://127.0.0.1:11434` | Ollama server. Used only with `--summarize` after a failure |
| `OLLAMA_MODEL` | `llama3.2` | Chat model for the Ollama path |
| `OLLAMA_NUM_CTX` | `8192` | Context window sent to Ollama |
| `API_WATCH_PROVIDER` | `ollama` | `ollama` or `openai` |
| `API_WATCH_TIMEOUT` | `120` | Seconds for the model call |
| `OPENAI_API_KEY` | empty | Only for the OpenAI-compatible path. Ollama does not use it |
| `OPENAI_BASE_URL` | `https://api.openai.com/v1` | Compatible base URL, usually ending in `/v1` |
| `OPENAI_MODEL` | `gpt-4o-mini` | Model name when the provider is `openai` |
| `API_WATCH_WEBHOOK_URL` | empty | Optional POST target for failure JSON |
| `API_WATCH_SOURCE` | empty | Example only. The public sample uses it as a header default |

Ollama is the default, and it does not need an API key. The OpenAI-compatible path is opt-in. Setting `OPENAI_BASE_URL` in the environment for some other tool does **not** switch this CLI. You have to set `API_WATCH_PROVIDER=openai` (or pass `--provider openai`).

```bash
# Remote or local OpenAI-compatible server (LM Studio, a proxy, api.openai.com, …)
export API_WATCH_PROVIDER=openai
export OPENAI_BASE_URL=https://api.openai.com/v1
export OPENAI_API_KEY=sk-...
export OPENAI_MODEL=gpt-4o-mini
api-watch check --config samples/local.yaml --summarize
```

`api.openai.com` refuses to run without `OPENAI_API_KEY`. A local compatible server may omit the key. `--provider` and `--model` override the environment for one command. Both apply only when `--summarize` actually calls a model.

A failure batch is small. The samples fit easily inside `OLLAMA_NUM_CTX`.

## Scope / out of scope

**In scope**

- One config file, one request per target, table or JSON
- Timeouts and connection errors recorded as failures
- A local last-run file
- Stderr alerts, a non-zero exit from `check`, and an optional JSON webhook
- Ollama by default, OpenAI-compatible chat as an option, and only after a failure
- A dry run so you can see the plan before any socket opens

**Out of scope**

- Slack, email, PagerDuty, or any SDK beyond one HTTP POST
- Dashboards, Prometheus, multi-host schedulers, retries, and backoff
- Request bodies, OAuth, or any auth besides static headers
- Letting a model decide pass or fail
- Inventing endpoints, status codes, or latencies that this run did not record
- A guarantee that two models will phrase the same failure the same way. The table is the check

## Samples

| File | What it is for |
| --- | --- |
| `samples/endpoints.yaml` | Three public httpbin URLs. One is expected to fail (HTTP 500). A demo header uses an env var with a default |
| `samples/endpoints.json` | The same list as JSON |
| `samples/local.yaml` | Three targets on `127.0.0.1:8765`. Two are expected failures |
| `samples/fixture_server.py` | Standard-library server for those local targets. No packages and no secrets |

## Layout

```text
src/api_watch/
  cli.py         # api-watch check / watch
  config.py      # YAML and JSON loading, header env references
  checker.py     # one HTTP probe per target
  prompts.py     # system prompt and the failure-batch prompt
  guard.py       # drop lines that cite a fact this run did not record
  summarize.py   # model call, grounding, recorded fallback
  render.py      # table, dry-run plan, JSON
  alert.py       # stderr lines and the optional webhook
  store.py       # .api-watch/last-results.json
  llm.py         # Ollama and OpenAI-compatible clients
  dotenv.py      # optional .env loader
samples/
tests/           # pytest, no live model, no real network
```

## Development

```bash
pip install -e ".[dev]"
pytest
```

`pytest` mocks the HTTP transport and the model client. It does not start Ollama, does not call httpbin, and does not bind the fixture server. Config validation, exit codes, the webhook payload, CLI parsing, the no-fabrication prompt, and the grounding check are covered from the samples and from in-memory targets.

Exit codes: `0` every check passed, a dry run succeeded, or `watch` was stopped with Ctrl+C. `1` one or more checks failed (`check` only; `watch` keeps going). `2` the config or the command line is not usable (missing file, bad URL, unset secret, `--interval` that is not positive, `--results` together with `--no-save`).

## License

MIT © 2026 Alfredo Cardona
