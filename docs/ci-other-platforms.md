# GitLab CI, Jenkins, Azure Pipelines and Bitbucket

The published composite action covers GitHub Actions ([its own
page](ci-github-actions.md)). Everything else is a shell command and an exit
code, which is the whole integration surface: `devrepro` is a normal CLI, it
writes to stdout, and it never contacts the network unless you pass a flag that
says to.

!!! warning "Install source"

    Until `devrepro-doctor` is published on PyPI, replace every
    `pip install devrepro-doctor` below with
    `pip install git+https://github.com/webdevsamran/devrepro-doctor@main`.
    The package name is not yet claimed, so the short form installs nothing.

The [exit-code contract](EXIT-CODES.md) is what every example below relies on:

| Code | Meaning |
|---|---|
| `0` | READY |
| `1` | READY_WITH_WARNINGS |
| `2` | BLOCKED |
| `3` | INTERNAL_ERROR |
| `4` | USAGE_ERROR |

Codes `3` and `4` matter more than they look. A crash or a mistyped flag must
not be mistaken for a verdict about the machine, so neither reuses a verdict
code — a pipeline that treats "non-zero" as "blocked" will report a typo as an
unusable runner.

## Which command

Two shapes, and the difference is not cosmetic:

- **`devrepro preflight`** — the full report, for a job on a fresh runner where
  the question is "can this machine build this project at all".
- **`devrepro guard --scope changed`** — gates only when the merge request
  alters the *environment contract*: a lockfile, manifest, toolchain pin, CI
  workflow, container definition or `.devrepro.toml`. When nothing in the
  contract moved it exits `0` without scanning, which is what keeps it cheap
  enough to run on every push.

Use `--base` to compare against the target branch rather than the working tree.

## GitLab CI

```yaml
# .gitlab-ci.yml
devrepro:
  stage: test
  image: python:3.12-slim
  before_script:
    - pip install --no-cache-dir devrepro-doctor
  script:
    - devrepro guard --scope changed --base "origin/$CI_MERGE_REQUEST_TARGET_BRANCH_NAME"
  rules:
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"

devrepro-report:
  stage: test
  image: python:3.12-slim
  before_script:
    - pip install --no-cache-dir devrepro-doctor
  script:
    # `|| [ $? -eq 1 ]` keeps READY_WITH_WARNINGS green while still failing on
    # BLOCKED (2) and on a crash (3). Do not replace it with `|| true`, which
    # hides the difference between all three.
    - devrepro preflight --json > devrepro-report.json || [ $? -eq 1 ]
  artifacts:
    when: always
    paths:
      - devrepro-report.json
    expire_in: 1 week
```

GitLab needs the target branch fetched before `--base` can resolve it. Add
`GIT_DEPTH: 0` to the job's `variables:` if your runner uses a shallow clone.

## Jenkins

```groovy
// Jenkinsfile
pipeline {
  agent any
  stages {
    stage('Environment contract') {
      steps {
        sh 'python -m pip install --no-cache-dir devrepro-doctor'
        script {
          // `returnStatus` rather than letting a non-zero exit abort the
          // stage: the code is the result, and collapsing it into
          // pass/fail throws away the distinction this tool exists to draw.
          def code = sh(
            script: 'devrepro guard --scope changed --base origin/main',
            returnStatus: true,
          )
          if (code == 2) {
            error('Environment contract blocked: run `devrepro doctor` locally.')
          }
          if (code >= 3) {
            error("devrepro exited ${code} — a tool failure, not a verdict.")
          }
        }
      }
    }
  }
}
```

## Azure Pipelines

```yaml
# azure-pipelines.yml
steps:
  - task: UsePythonVersion@0
    inputs:
      versionSpec: '3.12'

  - script: python -m pip install --no-cache-dir devrepro-doctor
    displayName: Install devrepro-doctor

  - script: devrepro guard --scope changed --base origin/$(System.PullRequest.TargetBranch)
    displayName: Environment contract
    condition: eq(variables['Build.Reason'], 'PullRequest')

  - script: devrepro scan --format junit -o $(Build.ArtifactStagingDirectory)/devrepro.xml
    displayName: Environment report (JUnit)
    condition: always()

  - task: PublishTestResults@2
    condition: always()
    inputs:
      testResultsFormat: JUnit
      testResultsFiles: $(Build.ArtifactStagingDirectory)/devrepro.xml
      testRunTitle: Environment
```

`devrepro scan --format junit` exists so a findings list can appear in a
results tab that already knows how to render one, rather than as a wall of log
output nobody expands.

## Bitbucket Pipelines

```yaml
# bitbucket-pipelines.yml
pipelines:
  pull-requests:
    '**':
      - step:
          name: Environment contract
          image: python:3.12-slim
          script:
            - pip install --no-cache-dir devrepro-doctor
            - devrepro guard --scope changed --base "origin/$BITBUCKET_PR_DESTINATION_BRANCH"
```

## Posting the result as a merge-request comment

`devrepro guard --format markdown` renders the same verdict as a comment and
prints it to stdout. It posts nothing itself — what happens to the text is the
pipeline's decision, which is what keeps the no-telemetry guarantee something
you can verify by reading the command rather than trusting a claim.

The output starts with a stable HTML marker:

```html
<!-- devrepro-doctor: environment-contract guard -->
```

Find that marker in the existing comments and edit that comment instead of
posting a new one. A bot that appends on every push turns a useful signal into
fifteen near-identical comments that people collapse and stop reading.

A GitHub Actions example is in
[GitHub Actions & SARIF](ci-github-actions.md#pull-request-comment). For GitLab,
the same shape with `curl` and the Notes API:

```bash
BODY=$(devrepro guard --scope changed --base "origin/$CI_MERGE_REQUEST_TARGET_BRANCH_NAME" --format markdown)
API="$CI_API_V4_URL/projects/$CI_PROJECT_ID/merge_requests/$CI_MERGE_REQUEST_IID/notes"

EXISTING=$(curl -sf -H "PRIVATE-TOKEN: $GITLAB_TOKEN" "$API" \
  | jq -r '[.[] | select(.body | contains("devrepro-doctor: environment-contract guard"))][0].id // empty')

if [ -n "$EXISTING" ]; then
  curl -sf -X PUT -H "PRIVATE-TOKEN: $GITLAB_TOKEN" "$API/$EXISTING" --data-urlencode "body=$BODY"
else
  curl -sf -X POST -H "PRIVATE-TOKEN: $GITLAB_TOKEN" "$API" --data-urlencode "body=$BODY"
fi
```

The token needs `api` scope on that project and nothing more.

## Air-gapped and offline runners

Nothing above needs the network at scan time. `devrepro` reads files and asks
installed tools for their versions; the only commands that reach out are the
ones that say so — `network --allow-network` and `ports --probe`. If your
runner has no internet, install the wheel from an internal index and everything
on this page still works.
