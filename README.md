# PathGuard V1

PathGuard verifies a proposed source patch by running one reproduction test against the original
snapshot, applying the patch only to a disposable copy, rerunning that test, and running the
regression suite. A patch is reported as verified only when policy and all three test stages pass.

## Requirements

- Windows PowerShell and Python 3.11 or 3.12
- Git
- Docker Desktop running
- A Gemini API key and model name for real Gemini calls

## Setup (PowerShell)

Run these commands from the `bug-agent` folder:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
Copy-Item .env.example .env
notepad .env
```

Set `GEMINI_API_KEY` and `GEMINI_MODEL` in Notepad. Build the isolated pytest image and check the
local setup:

```powershell
docker build -f sandbox/Dockerfile.runner -t pathguard-runner .
pathguard doctor
```

The sandbox image contains pytest and pytest-timeout. If a target repository needs extra test
dependencies, build a local runner image with `--build-arg EXTRA_REQS="package==version"` and set
`PATHGUARD_DOCKER_IMAGE` to its tag.

With Gemini credentials configured, check the provider separately:

```powershell
python scripts/smoke_gemini.py
```

## Run tests

```powershell
python -m pytest -q
```

Docker-specific isolation checks are marked `docker` and can be run after building the image:

```powershell
python -m pytest -m docker -q
```

## Run the MCP servers

Each server uses stdio transport. Start the appropriate command through an MCP host, with the
working directory set to this project:

```powershell
python -m mcp_servers.repo_mcp
python -m mcp_servers.sandbox_mcp
```

Repository inspection tools are `search_files`, `read_file`, `git_log`, and `git_diff`. Sandbox
tools are `run_repro_test`, `run_regression_suite`, `apply_patch_dry_run`, and
`verify_candidate_patch`.

`verify_candidate_patch` takes `repo_path`, `repro_file`, `repro_source`, and a unified-diff
`patch`. For example, provide `repro_file="tests/test_repro_pathguard.py"` and a Python test as
`repro_source`; the patch must change application source and cannot edit tests, CI, dependency, or
build files. Its result includes `policy_ok`, `reproduced_before`, `repro_passes_after`,
`regression_green`, `verified`, a failure reason, and each stage's bounded execution result.

## Configuration

All repositories passed to MCP tools must be directories under `target_repos`. Configure paths and
runtime limits with these environment variables:

```text
PATHGUARD_TARGET_REPOS
PATHGUARD_DOCKER_IMAGE
GEMINI_API_KEY
GEMINI_MODEL
```

Original repositories are only inspected. Sandbox copies exclude Git metadata and environment
files, reject symlinks, and are removed after each run. Candidate patches are applied only inside
these temporary copies. Docker runs without network access, as UID 1000, with read-only workspace,
memory, CPU, process, timeout, and output limits.

Use the provider-neutral `LLMClient` interface in `agent.llm`; `GeminiClient` is the configured
provider and `MockLLM` provides deterministic replies for tests and offline callers. PathGuard V1
does not include an autonomous agent, RAG, API, or UI.
