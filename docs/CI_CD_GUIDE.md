# CI/CD for tracecraft — a learning doc

This is a working-engineer's introduction to CI/CD, grounded in the two workflows tracecraft uses today (`.github/workflows/test.yml` and `release.yml`). By the end you'll understand every line of YAML in this repo, the trust model that lets GitHub publish to PyPI without a stored password, and how to debug failures.

Written for someone who knows Python and git but hasn't owned a CI/CD pipeline before. Skip sections you already know.

---

## Part 1 — The concepts, in 5 minutes

### What CI/CD actually is

Two related-but-distinct things:

- **Continuous Integration (CI)** — every time someone pushes code or opens a PR, a fresh computer (a "runner") checks the code out, installs dependencies, and runs your tests. If anything is broken, you see it within seconds on the commit/PR. The point is to catch breakage *before* it merges to `main`, not after.

- **Continuous Delivery (CD)** — when you mark a commit as a release (cut a tag, click "Publish release"), a fresh computer builds the shippable artifact (a Python wheel, a Docker image, a binary) and uploads it to wherever users get it (PyPI, Docker Hub, App Store). The point is to make releases boring and repeatable — no "did I remember to bump the version in both files?" mistakes.

Sometimes people add **Continuous Deployment** (same acronym, different word) — automatically pushing every green commit to production. Tracecraft has no servers, so that doesn't apply here.

### Why it exists

Before CI/CD, releases were a checklist a human did by hand. Six steps, easy to skip one, easy to miss "this works on my machine" bugs. CI runs the checklist in a known-clean environment, every time, and fails loudly when it can't.

The deeper point: **CI is the executable documentation of how your project works.** Someone reading your repo can look at `.github/workflows/test.yml` and learn "this is how you install and test this code." Conversely, if your CI passes on a fresh machine, you've proven the install instructions in your README actually work.

### The GitHub Actions vocabulary

GitHub Actions is one of many CI/CD systems. Others: CircleCI, GitLab CI, Jenkins, Travis CI. The concepts below are mostly universal; the keywords are GitHub-specific.

- **Workflow** — one YAML file under `.github/workflows/`. One workflow = one purpose (run tests, publish release, run nightly job, etc.).
- **Job** — a single unit of work inside a workflow. Jobs run in parallel unless you tell them to depend on each other. One job runs on one runner.
- **Step** — a command inside a job. Steps run sequentially. If a step fails, the rest of the job stops.
- **Runner** — the VM that executes the job. GitHub provides `ubuntu-latest`, `macos-latest`, `windows-latest`. You can also self-host runners.
- **Trigger / `on:`** — what causes the workflow to fire. `push`, `pull_request`, `release`, `schedule` (cron), `workflow_dispatch` (manual button), and more.
- **Matrix** — a single job that runs N times with different variable values (e.g., one per Python version). Saves duplication.
- **Action** — a reusable building block, e.g. `actions/checkout@v4`. Other people's code you call from your workflow. Hosted on the GitHub Marketplace.
- **Secrets / variables** — encrypted values stored on GitHub, available to workflows. Used for API tokens, etc. *We deliberately don't use stored secrets for PyPI — see Part 4.*
- **Concurrency** — controls whether multiple runs of the same workflow can run at once. Useful to cancel old runs when you push twice in a row.
- **Artifact** — files a job produces that you want to keep (build outputs, screenshots, coverage reports). Stored on GitHub for 90 days by default.

### Cost

For tracecraft (public repo): **free, unlimited**. GitHub gives unlimited Actions minutes to public repos. PyPI is always free for public packages.

For private repos: free tier is 2,000 minutes/month, then ~$0.008/min on Linux. A 30-second run × 10 pushes/day × 30 days = 1.5 hours of CI/month — well under the free tier.

---

## Part 2 — `test.yml` line by line

Here's the actual file in this repo, with annotations.

```yaml
name: tests
```
The display name for the workflow in GitHub's UI. Shows up as "tests" on commits and PRs.

```yaml
on:
  push:
    branches: [main]
  pull_request:
    branches: [main]
```
**The trigger.** "Run this workflow when (a) someone pushes to `main`, or (b) someone opens/updates a PR targeting `main`." If we removed the `branches:` filter, the workflow would also run on pushes to feature branches — wasteful since the PR run already covers that.

> *Note:* YAML 1.1 interprets the unquoted word `on` as the boolean `true` when parsed by some libraries. GitHub Actions handles this correctly. Just leave it as `on:` — no need to quote it.

```yaml
jobs:
  pytest:
```
One job named `pytest`. The name appears as the status check on PRs (`pytest (3.10)`, `pytest (3.11)`, etc., because of the matrix below).

```yaml
    runs-on: ubuntu-latest
```
Use GitHub's latest Ubuntu runner. As of 2026 that's Ubuntu 24.04. Other choices: `ubuntu-22.04`, `macos-latest`, `windows-latest`. Ubuntu is the cheapest and fastest; we add macOS/Windows only when needed.

```yaml
    strategy:
      fail-fast: false
      matrix:
        python-version: ["3.10", "3.11", "3.12", "3.13"]
```
The **matrix**. This single job definition gets expanded into 4 parallel runs, each with `${{ matrix.python-version }}` set to one of the listed versions. `fail-fast: false` means "if 3.10 fails, keep running 3.11/3.12/3.13 anyway" — useful because failures are often version-specific and you want to see them all.

```yaml
    steps:
      - uses: actions/checkout@v4
```
**Step 1**: `actions/checkout@v4` is an official GitHub action that does `git clone` into the runner. The `@v4` is a version pin — major version 4. You should always pin actions; `@main` would mean "whatever they push" which can break you.

```yaml
      - name: Set up Python ${{ matrix.python-version }}
        uses: actions/setup-python@v5
        with:
          python-version: ${{ matrix.python-version }}
          cache: pip
```
**Step 2**: installs the matrix Python version. `cache: pip` tells the action to cache `~/.cache/pip` between runs — speeds up subsequent runs by 30-60s because dependencies don't redownload.

`${{ matrix.python-version }}` is GitHub's expression syntax: it substitutes the current matrix value. So this step runs four times across the four matrix cells with `3.10`, `3.11`, `3.12`, `3.13`.

```yaml
      - name: Install package + dev extras
        working-directory: sdk
        run: |
          python -m pip install --upgrade pip
          pip install -e ".[dev,huggingface]"
```
**Step 3**: install tracecraft + its test/dev dependencies. The `|` lets you write multiline shell. `working-directory: sdk` means commands run from `sdk/`. `[dev,huggingface]` pulls the optional extras defined in `sdk/pyproject.toml`.

```yaml
      - name: Run tests
        run: pytest sdk/tests/ -v
```
**Step 4**: actually run the tests. `working-directory` is back to repo root because we didn't specify one here. `-v` is verbose (one line per test). Exit code 0 = green check, non-zero = red X.

That's the whole file. Less than 30 lines of YAML, and it gives you "the tests pass on 4 Python versions on Ubuntu" on every push.

### What you'll see in the GitHub UI

- On the commit list, a small ✓ or ✗ icon next to the commit hash.
- On a PR, a "Checks" tab showing each matrix cell separately.
- Click into a run to see logs per step.
- The workflow file itself appears in the "Actions" tab.

---

## Part 3 — `release.yml` line by line

```yaml
name: release

on:
  release:
    types: [published]
```
Triggered by the `release.published` event, which fires when you click "Publish release" in the GitHub UI (or run `gh release create v0.2.0 ...`). NOT triggered by simply pushing a tag — there's a distinction. A tag is just a label on a commit; a "release" is a tag plus optional metadata (notes, attached binaries). We use the release event because it gives you a confirmation step before publication.

```yaml
jobs:
  build-and-publish:
    runs-on: ubuntu-latest
    environment:
      name: pypi
      url: https://pypi.org/project/tracecraft-ai/
```
The job runs in an **environment** called `pypi`. Environments are a GitHub feature for adding extra protection around sensitive jobs:
- You can require manual approval before the job runs.
- You can restrict which branches can deploy to the environment.
- The environment shows up in the GitHub UI with the URL above as a clickable link.

For tracecraft, the environment also matches what we'll tell PyPI to trust (in Part 4).

```yaml
    permissions:
      id-token: write  # required for PyPI trusted publishing
      contents: read
```
**This is the magic.** GitHub Actions has a per-job permission model. By default, the `GITHUB_TOKEN` (auto-generated for each run) has read-only access. `id-token: write` is what lets the job request an **OIDC token** — a short-lived JWT signed by GitHub that proves to PyPI "yes, this is the genuine release.yml workflow on Arrmlet/tracecraft running right now."

`contents: read` keeps the rest of the permissions minimal — we don't need to write to the repo, only read its files.

```yaml
    steps:
      - uses: actions/checkout@v4
        with:
          ref: ${{ github.event.release.tag_name }}
```
Checkout the repo, but specifically at the tag of the release that triggered this. Without `ref:`, it would check out the default branch — which might be ahead of the tag if someone pushed to `main` after creating the release. Using the tag means the wheel we publish is exactly the code in the release.

```yaml
      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.12"
```
Only one Python version needed for building — the wheel is pure Python (`py3-none-any.whl`), so any modern Python builds it correctly.

```yaml
      - name: Sync root README into sdk/ before build
        run: cp README.md sdk/README.md
```
A tracecraft-specific quirk. The Python package source lives in `sdk/`, but the README we want users to see on PyPI lives at the repo root. We copy it into `sdk/` before build so setuptools picks it up.

```yaml
      - name: Build sdist + wheel
        working-directory: sdk
        run: |
          python -m pip install --upgrade pip build
          python -m build
```
Runs Python's modern build tool. Produces two files in `sdk/dist/`:
- `tracecraft_ai-X.Y.Z.tar.gz` — the *source distribution* (sdist). What `pip` falls back to if no wheel is available.
- `tracecraft_ai-X.Y.Z-py3-none-any.whl` — the *wheel*. Pre-built, no compilation needed on install.

```yaml
      - name: Verify artifacts
        working-directory: sdk
        run: |
          pip install twine
          twine check dist/*
          python -m venv /tmp/verify
          /tmp/verify/bin/pip install dist/*.whl
          /tmp/verify/bin/tracecraft --version
```
Three sanity checks before publishing:
1. `twine check` validates the wheel metadata (README rendering, classifiers, etc.).
2. Install the wheel in a fresh venv — proves it's installable.
3. Run `tracecraft --version` — proves the CLI entry point actually works.

If any of these fail, the workflow stops here and doesn't publish a broken package.

```yaml
      - name: Publish to PyPI
        uses: pypa/gh-action-pypi-publish@release/v1
        with:
          packages-dir: sdk/dist/
```
**The actual publish step.** This action sends the contents of `sdk/dist/` to PyPI using the OIDC token from earlier. Notice there is no `password:` or `username:` or `token:` field — that's the whole point of trusted publishing.

This step fails until you configure PyPI to trust this workflow (Part 4).

---

## Part 4 — PyPI Trusted Publishing setup

This is the one-time browser configuration that unlocks `release.yml`. It's required because PyPI doesn't blindly accept uploads from any GitHub workflow — it needs to know which workflows you trust.

### Background — why trusted publishing exists

The old way: generate a PyPI API token, save it as a GitHub Secret, reference it in the workflow. Problems:
- The token is long-lived. If your GitHub account is breached, the attacker has your PyPI publish access.
- Hard to rotate; everyone forgets to.
- One leak from any project = total PyPI account takeover.

The new way (introduced 2023, mature in 2024-2025): **OIDC trusted publishing.** GitHub generates a short-lived token *per run*, signed by GitHub, that proves "this is genuinely the `release.yml` workflow in `Arrmlet/tracecraft` running right now, on a runner GitHub controls, for the tag `v0.2.0`." PyPI verifies that signature and accepts the upload.

Properties:
- The token is valid for ~10 minutes and only inside that specific job.
- No secret stored anywhere — there's nothing to leak.
- Scoped to one workflow file in one repo. An attacker would need to compromise GitHub itself.

### Step-by-step setup

You do this once, today. After that you never touch PyPI tokens for this project again.

1. **Sign in to PyPI** at https://pypi.org/.

2. **Go to project settings** — https://pypi.org/manage/project/tracecraft-ai/settings/publishing/

   If that URL 404s, navigate manually: Account dropdown → "Your projects" → click `tracecraft-ai` → "Publishing" in the left sidebar.

3. **Click "Add a new pending publisher"** or "Add a new trusted publisher."

4. **Choose "GitHub" as the publisher.**

5. **Fill in the form exactly:**
   - **Owner:** `Arrmlet`
   - **Repository name:** `tracecraft`
   - **Workflow filename:** `release.yml` (just the filename, not the path)
   - **Environment name:** `pypi`

   The `Environment name` here MUST match the `environment.name:` in `release.yml` (which is `pypi`). Case matters.

6. **Click "Add."**

That's it. PyPI now trusts `release.yml`. The next time you create a GitHub Release, the workflow will run end-to-end and publish to PyPI without any prompt.

### Verifying it works

Don't ship a real release just to test. Instead, the first release that goes through the workflow IS the test. Recommended:

1. Make a tiny code change (a comment, a typo fix in README).
2. Bump version to `0.1.6` in `sdk/pyproject.toml` and `sdk/tracecraft/__init__.py`.
3. Commit, push, tag, push tag.
4. `gh release create v0.1.6 --title "v0.1.6 — CI/CD test" --notes "Testing trusted publishing"`
5. Watch the workflow in the Actions tab. Should turn green in ~1 minute.
6. Verify on PyPI: `pip install --upgrade tracecraft-ai` → version should be `0.1.6`.

If step 5 fails at "Publish to PyPI" with a 403 — go back and check the publisher config matches exactly (owner case, workflow filename, environment name).

---

## Part 5 — Reading the GitHub Actions UI

When you push or create a PR, here's where the action is in the UI:

### Per-commit status
On the commit list, look for a circle/check/X next to the commit hash:
- Yellow dot = running
- Green check = all green
- Red X = at least one job failed

Hover or click for a summary. Click the icon to see the workflow details.

### Per-PR status
At the bottom of the PR, the "Checks" section shows each workflow. For a matrix workflow you'll see one row per matrix cell (`pytest (3.10)`, `pytest (3.11)`, etc.). Click "Details" to see logs.

### Actions tab (`github.com/Arrmlet/tracecraft/actions`)
The full history of all workflow runs. Filter by workflow on the left, by branch/event/status at the top. Click a run for detailed logs.

### Inside a run
You see the matrix cells (or single job) listed. Click one to expand the steps. Each step has its own logs and timing. Failed steps are highlighted red and auto-expand to show the error.

### Re-running failed jobs
If a run failed due to a flake (network blip, etc.), the "Re-run failed jobs" button at the top right re-runs only the failed cells. Re-runs preserve the commit SHA, so the new attempt is genuinely a do-over of the same code.

---

## Part 6 — `gh` (GitHub CLI) for local interaction

You don't have to use the browser UI. The `gh` CLI is faster:

```bash
# Watch the most recent run for the current branch
gh run watch

# List recent runs
gh run list --limit 10

# View the details of a specific run
gh run view <run-id>

# View just the failed step logs
gh run view <run-id> --log-failed

# Re-run a failed run
gh run rerun <run-id>

# Cancel a stuck run
gh run cancel <run-id>

# Create a release (this triggers release.yml)
gh release create v0.2.0 --title "v0.2.0" --notes "..."

# List releases
gh release list

# View one release
gh release view v0.1.5
```

---

## Part 7 — Common failures and how to debug them

### Test workflow goes red

1. **Open the failed run** (Actions tab → click the red run).
2. **Find the failing matrix cell.** Maybe only 3.10 failed — that narrows the cause to "Python 3.10 specific."
3. **Expand "Run tests"** to see the pytest output. Same format as your local terminal.
4. **Reproduce locally** with the same Python version: `pyenv install 3.10` → `pyenv local 3.10` → `pip install -e "sdk/[dev]"` → `pytest sdk/tests/`.
5. **Fix and push again.** The workflow re-runs.

### Workflow doesn't trigger at all

- Check `on:` filters — pushing to a feature branch with `branches: [main]` only triggers on PR, not on direct push.
- Check `.github/workflows/` path. Typos like `.github/workflow/` won't be picked up.
- Check the workflow YAML is valid. GitHub UI will show a "Workflow invalid" error in the Actions tab.

### Release workflow fails at "Publish to PyPI"

- The error message is usually `403 Forbidden` or `Invalid or non-existent authentication information`.
- Cause: trusted publishing config doesn't match the actual workflow run.
- Fix: double-check the PyPI publishing form. Owner case-sensitive. Workflow filename is just `release.yml` (no path). Environment name `pypi` matches the `environment.name:` in the YAML.

### "Resource not accessible by integration" error

- Cause: missing `permissions:` in the YAML. The default permissions are read-only.
- Fix: explicitly request what you need (`id-token: write`, `contents: write`, etc.) in the job.

### Action versions deprecated

You may see a banner: "Node.js 20 actions are deprecated." This is GitHub's runtime, not your code. Fix by bumping action versions (e.g., `actions/checkout@v4` → `actions/checkout@v5` when released). Non-urgent unless the runner refuses to execute the action.

### Cached pip install picks up wrong package

If you change `pyproject.toml` deps but CI still uses the cached old version, force a cache refresh by changing the `cache:` config or, easiest, the lockfile/`pyproject.toml` hash will already invalidate the cache automatically (which is the point of `cache: pip`).

---

## Part 8 — What we deliberately did NOT add (and why)

These are common CI additions that aren't worth it for a small Python OSS project. Add them if you grow into the need; don't add them just because.

| Feature | Why we skipped |
|---|---|
| Coverage reporting (codecov) | 12 tests at this scale tell you more than a coverage % does. Add when team-size justifies. |
| Linting gate (ruff in CI) | Ruff is in `dev` extras; run locally. Blocking PRs on lint is friction for a solo maintainer. |
| Pre-commit hooks | Local-only friction. Helpful with 3+ contributors; overkill solo. |
| Dependabot / Renovate | Adds noise. Manual quarterly review of deps is fine at this scale. |
| Branch protection rules | You're solo. Self-review is acceptable. Add when contributors arrive. |
| Auto-version-bump (release-please, semantic-release) | Overengineering until 5+ releases/quarter. |
| Windows / macOS runners | Add on first user bug report from those platforms. |
| Nightly cron tests against real S3 | Premature; moto covers correctness, real S3 issues are rare. |
| CodeQL security scanning | Free if you enable it. Useful eventually; not on the critical path. |
| Slack / Discord notifications | The Actions email is enough until you have a team channel. |

The principle: **CI complexity should match project stakes.** Right now tracecraft is small and the maintainer is one person; the two workflows we have are the right size. Re-evaluate when stakes change.

---

## Part 9 — Where to learn more

- **GitHub Actions docs** — https://docs.github.com/en/actions. The official reference. The "Quickstart" and "Workflow syntax" pages are the most useful.
- **PyPI trusted publishing docs** — https://docs.pypi.org/trusted-publishers/
- **awesome-actions** — https://github.com/sdras/awesome-actions. Curated list of useful actions.
- **Anatomy of a workflow** — https://docs.github.com/en/actions/learn-github-actions/understanding-github-actions
- **GitHub Actions security hardening** — https://docs.github.com/en/actions/security-guides/security-hardening-for-github-actions. Becomes relevant when you start using secrets, deployments, or third-party actions.

---

## TL;DR — what you have now

- **`test.yml`** runs the 12 backtests on Python 3.10/3.11/3.12/3.13 every push and PR. Free, ~30s, catches regressions before merge.
- **`release.yml`** builds + publishes to PyPI on every GitHub Release. Requires one-time trusted publishing setup at https://pypi.org/manage/project/tracecraft-ai/settings/publishing/ (Owner: `Arrmlet`, Repo: `tracecraft`, Workflow: `release.yml`, Environment: `pypi`).
- **No tokens stored anywhere.** OIDC-based trust.
- **Free** for public repos.

The next time you ship is:
```
# bump version in two files, commit
gh release create v0.2.0 --title "..." --notes "..."
# walk away; PyPI has it in ~60 seconds
```
