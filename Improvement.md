# Repository Improvement Review

This document consolidates the repository audit findings and recommendations.
It is a review and improvement backlog, not a record of changes already made.
No cleanup, deletion, or implementation work is implied by listing a
recommendation.

## Executive summary

The repository is a useful local-first content authoring and review prototype.
Its modular-monolith direction, YAML configuration, local JSON records,
approval gate, explicit service errors, atomic record writes, and focused tests
are a good fit for a solo developer.

It is not yet a complete media-production or social-publishing platform. The
application generates content and production prompts, but does not render
images or video, publish or schedule content, or collect analytics. Its
format/profile abstractions are useful, but Comedy and QA subtype behavior
still contains special cases.

The most urgent confirmed correctness issue is that storyboard parsing does
not recognize the `NARRATION:` directive. For Reel 021, narration is included
inside visual beats, the storyboard has no narration entries, and the master
video prompt says no voiceover is specified. Fix this before relying on those
production prompts.

At the time of the audit, the full test suite passed: **100 passed**, with one
environment warning about urllib3 and LibreSSL. The worktree was not clean:
22 tracked files were modified and 14 files were untracked. Some untracked
files are required configuration or valuable generated content; do not
bulk-delete or stage all untracked files.

## Current workflow and product alignment

```text
CLI or local review UI
  -> resolve brand, profile, format, and platform
  -> assemble prompt and call the local Ollama-compatible text service
  -> validate the selected format's required fields
  -> save Reel or post JSON
  -> human review and approval
       -> Reel: storyboard -> image prompts -> master video prompt
       -> single-page post: design prompt
       -> LinkedIn text post: saved copy and image prompt in the record
```

The product is best described as a **hybrid local content authoring and
review tool with a Reel-oriented prompt-production workflow**. It is not an
Instagram publishing system and not yet a fully generic media platform.

| Capability | Current state |
|---|---|
| Content profiles | Three configured profiles: Comedy, QA Engineering & AI, and Critical Thinking / Rational Thoughts. |
| Formats | Reel, single-page post, and LinkedIn text post. |
| Review | Local UI supports review and approval; CLI review commands also exist. |
| Production preparation | Storyboard, image/design prompt, and master video prompt generation. |
| Image/video rendering | Not implemented. Generated image/video directories contain prompt artifacts, not rendered media. Two SVG editorial assets exist. |
| Recurring 3D avatar library | Not implemented; correctly a future roadmap item. |
| Publishing, scheduling, analytics | Not implemented. |

## Architecture assessment

### Strengths

- A local-first modular monolith avoids infrastructure that is not justified
  by the current solo-developer workflow.
- Configuration, data models, prompt construction, storage, and CLI/UI entry
  points have identifiable boundaries.
- Storage uses atomic writes for JSON records.
- The AI client reports connection, HTTP, timeout, and response-shape errors.
- UI production stages require approved content.
- The test suite covers configuration, generation, storage, review, and
  production prompt behavior.

### Weaknesses and risks

- Storyboard parsing currently loses narration for supported input.
- CLI and UI behavior diverges for review decisions, Comedy subtype selection,
  batching, and brand resolution.
- Profile and category behavior is special-cased for Comedy and QA rather
  than consistently driven by a shared subtype contract.
- The review server coordinates HTTP handling, workflow, storage, and
  production stages in one large module.
- CLI and UI duplicate parts of the generation-and-save flow.
- The fixed AI endpoint and model are hard-coded.
- Some Comedy configuration fields are validated but are not consumed by
  prompt generation; prompt behavior is also duplicated in code.
- Activity history uses per-record JSONL files in a generated-output folder.
  This is workable locally, but data-retention and ownership policies are
  unclear.
- The editor-selected Python 3.14 environment did not resolve project
  dependencies, while the terminal test run passed under Python 3.9. The
  development environment is therefore not reproducible from the editor
  state observed during the audit.

### What should remain

- Keep the local-first modular monolith and avoid premature infrastructure.
- Keep the current JSON storage until volume or concurrency demonstrates a
  concrete need for a database.
- Keep the human approval gate before production stages.
- Keep the compatibility command `scripts.scene_generator` while documented
  or tested callers depend on it.
- Keep `profile_loader.py` while application code or tests depend on its
  compatibility interface.
- Preserve legacy generated content unless an explicit retention decision is
  made.
- Keep generated folders in scope: each currently supports an application
  workflow.

## Confirmed findings and recommended fixes

### 1. Storyboard narration is lost

The storyboard directive expression does not recognize `NARRATION`, although
the renderer emits that directive. Rebuilding the storyboard from Reel 021
produced four visual beats and zero narration entries. The generated master
prompt consequently says “No voiceover specified.”

**Recommendation:** add a regression test using the Reel 021 input shape,
recognize the narration directive, regenerate the Reel 021 storyboard, scene
export, and master prompt, and archive the previous derived outputs for
comparison.

Relevant files: `scripts/storyboard_generator.py`,
`generated_reels/reel_021.json`,
`generated_videos/reel_021_scenes.txt`, and
`generated_videos/reel_021_master_prompt.txt`.

### 2. Comedy behavior differs between CLI and UI

- CLI Comedy batch rotation checks `--category comedy`; the README also
  demonstrates profile-based Comedy usage. A batch invoked with
  `--profile comedy --count ...` does not take the same subtype-rotation path.
- The UI maps a selected `content_subtype` to the Comedy category only when a
  subtype is supplied. The configuration resolver chooses the Life Is a Glitch
  brand based on category, so choosing a subtype can change category/brand
  behavior for an otherwise identical Comedy profile request.
- The profile-owned subtype experience and legacy category/subtype options
  therefore do not have a single consistent source of truth.

**Recommendation:** decide the intended Comedy behavior when no subtype is
selected; then apply that rule consistently across CLI, UI, persistence,
regeneration, batching, and brand resolution. Prefer a shared profile-owned
subtype contract while retaining compatibility aliases only where needed.

Relevant files: `scripts/main.py`, `scripts/review_ui.py`,
`config_loader.py`, `content_agent.py`, and `README.md`.

### 3. CLI review paths do not enforce the same rules as the UI

The UI restricts decisions to Draft content and records activity. Direct
approve/reject commands overwrite statuses without the same Draft-only guard
or history entry. `bulk_review.py` also saves after an unrecognized response
and prints “Updated” without changing the decision.

**Recommendation:** route CLI and UI review decisions through the same
workflow function, validate transitions centrally, record history
consistently, and make an invalid interactive choice explicit without
reporting success.

Relevant files: `scripts/approve_reel.py`, `scripts/reject_reel.py`,
`scripts/bulk_review.py`, and `scripts/review_ui.py`.

### 4. Some Comedy configuration is not effective configuration

`config/comedy.yaml` includes humor and production guidelines, visual
approaches, quality checks, and per-format requirements. The loader validates
some of these fields, but generation uses only part of this data and repeats
guidance in Python. `publishing_identity` is computed in `content_agent.py`
but not used.

**Recommendation:** wire the intended fields into prompt construction or
remove declarations that have no consumer. Keep configuration authoritative;
avoid validating settings that cannot affect runtime behavior.

Relevant files: `config/comedy.yaml`, `config_loader.py`, and
`content_agent.py`.

### 5. Documentation and command behavior have drifted

The roadmap says Reel is the only configured format, which contradicts the
three formats in the implementation and README. The README demonstrates both
profile/subtype and legacy category/subtype usage without consistently
distinguishing the canonical path from compatibility behavior.

**Recommendation:** correct the roadmap's current-state statement, clarify
the canonical CLI options, and document the actual batch-rotation and
no-subtype behavior after it has been made consistent.

Relevant files: `03_DEVELOPMENT_ROADMAP.md` and `README.md`.

### 6. Dependencies and Python environments need reconciliation

The code imports `requests` and `yaml`; tests use `pytest`. These are declared
in `requirements.txt`. The Pylance-selected Python 3.14 interpreter reported
these imports unresolved and showed only MLX installed. The audit's terminal
test run succeeded under Python 3.9, so this is an environment mismatch, not
evidence that those dependencies are unused.

No project imports were found for `openai`, `python-dotenv`, `fastapi`,
`uvicorn`, `sqlalchemy`, or `pydantic`. `pytest` is a test dependency;
`requests` and PyYAML are runtime dependencies. `.env.example` lists
OpenAI and Instagram values, but the current code does not load those
settings. The model endpoint and model identifier are hard-coded in
`ai_service.py`.

**Recommendation:** remove dependencies only after confirming no separate
planned integration relies on them; separate runtime and test requirements;
document a reproducible interpreter setup; and either wire configuration for
the model endpoint/model or clearly document the fixed local service.
Do not describe `.env.example` values as functional configuration until they
are consumed.

Relevant files: `requirements.txt`, `.env.example`, `ai_service.py`, and
workspace Python configuration.

## Generated output classification

The audit found 57 files across the generated-content directories and no
byte-identical generated artifact files. Repeated titles alone are not proof
that saved drafts are duplicates.

| Output | Classification | Recommendation |
|---|---|---|
| All 23 JSON records in `generated_reels/` | **KEEP** | Includes tracked and untracked content; older records without newer metadata are still valuable records/history. |
| Three JSON records in `generated_posts/` | **KEEP** | Distinct saved post drafts. |
| Ten files in `generated_assets/` | **KEEP** | Includes post prompts, SVG assets, and review history. |
| Eleven files in `generated_images/` | **KEEP** | These are text image-prompt artifacts, not rendered images. |
| Reel 016, 018, and 023 outputs in `generated_videos/` | **KEEP** | Useful production artifacts; Reel 023 files are untracked. |
| Reel 021 storyboard, scenes, and master prompt | **ARCHIVE** | Narration is embedded incorrectly in visual beats. Regenerate after the fix, retaining the old version for comparison. |
| Browser captures under `.playwright-mcp/` | **ARCHIVE** | Retain only if they serve as UI evidence; they are not production content. |
| `.pytest_cache/` | **SAFE TO DELETE** | Disposable test cache, regenerated by pytest. |

Required untracked configuration at audit time:

- `config/comedy.yaml` — **KEEP**; current Comedy configuration loading
  requires it.
- `config/brands/life_is_a_glitch.yaml` — **KEEP**; Comedy brand resolution
  requires it.

Untracked Reel 022/023 records, history, and production outputs are user
content. Decide whether to commit them, but do not delete them as cleanup.

## Cleanup plan

### Safe to delete immediately

- Only `.pytest_cache/`, the disposable test cache observed during the audit.

### Archive candidates; do not delete without a retention decision

- Reel 021 derived outputs, after corrected outputs have been generated.
- `.playwright-mcp/` browser captures if they are not needed as UI evidence.
- `scripts/bulk_review.py` and `scripts/approved_reels.py` are standalone
  commands not referenced by the README or tests inspected in the audit.
  Confirm they are not part of the user's workflow before retiring them.
- `prompt_library.md` is a manual prompt collection, not a runtime dependency.
  Keep it if it is actively used; otherwise archive it outside application
  source.

### Rename, merge, or folder removal

- No file or folder rename is justified by the evidence.
- Do not remove `scripts/scene_generator.py` or `profile_loader.py`; they are
  compatibility surfaces used by tests or application code.
- No exact duplicate files or safely mergeable configuration files were
  identified.
- No generated folder was verified unused.
- Consider a compatibility-preserving rename of `AIService.generate_reel` to
  a text-generation name: it is used for content and image-prompt text, not
  only Reels.
- Update the CLI startup banner, which still says “Instagram Manager Agent,”
  to reflect the current product name.

### Git hygiene

- Do not blanket-ignore generated directories. Tests currently consume
  checked-in generated content, including Reel 018 as a fixture.
- Move test fixtures to a dedicated test-fixtures location before changing
  generated-output ignore rules.
- Add `.pytest_cache/` to `.gitignore`; decide separately whether new browser
  captures should be ignored.
- Do not use `git clean`, `git add .`, or bulk deletion. Untracked files
  include required configuration and valuable generated content.

## Readiness scores

| Area | Score | Rationale |
|---|---:|---|
| Architecture | 6/10 | Good local modular-monolith direction; provider configuration and feature-specific routing remain. |
| Code quality | 6/10 | Explicit errors and atomic JSON writes are strengths; the parser defect and inconsistent review paths are material weaknesses. |
| Content workflow | 6/10 | Generation-to-approval-to-prompt flow exists; narration loss affects production output, and media is not rendered. |
| Configuration system | 5/10 | YAML is useful, but some Comedy fields are unused and subtype handling is not generic. |
| Documentation | 6/10 | README is substantial; roadmap and CLI behavior need correction. |
| Maintainability | 5/10 | Manageable now, but duplicated save logic, a large review module, and special cases make changes harder. |
| Scalability | 5/10 | Adequate for a solo local workflow and many drafts; publishing-scale throughput is neither implemented nor tested. |

## Top 20 improvements ranked by ROI

1. Fix `NARRATION` parsing and add a regression test using Reel 021's input
   shape.
2. Regenerate Reel 021's storyboard, scenes, and master prompt; archive the
   old derived outputs.
3. Define consistent Comedy profile/category/subtype behavior for CLI and UI.
4. Make CLI Comedy batches rotate when invoked through the documented profile
   path.
5. Align Comedy brand defaults whether or not a subtype is selected.
6. Route CLI approve/reject commands through the same status guard and history
   workflow as the UI.
7. Make invalid `bulk_review` responses explicit; do not save or report a
   successful update.
8. Deliberately stage the two required untracked configuration files with the
   relevant feature changes.
9. Decide whether untracked Reel 022/023 outputs belong in Git; preserve them
   either way until that decision is made.
10. Move test fixtures out of production-generated directories before
    changing ignore rules.
11. Align the VS Code/Pylance interpreter with the environment used for the
    passing test run.
12. Trim unused dependencies and separate runtime from test requirements.
13. Correct the roadmap's stale format statement and clarify canonical CLI
    examples.
14. Wire or remove Comedy configuration fields that currently have no
    consumers.
15. Make model endpoint and model selection configurable with simple local
    defaults.
16. Consolidate duplicated CLI/UI content-record save behavior.
17. Add tests for Comedy defaults, omitted subtype, batch rotation, and brand
    resolution.
18. Add tests for status/history consistency and partial batch failure.
19. Establish a generated-data retention policy and move test fixtures before
    ignoring generated output.
20. Consider a small shared storage helper or splitting the review server
    only after higher-impact correctness and consistency work; neither
    warrants a broad redesign now.

## Technical debt assessment

Technical debt is **moderate**, not architectural collapse. The most
important debt is correctness in the production path, divergence between
generation/review entry points, and ambiguous ownership of generated data.
The JSON storage choice is not itself a problem. Do not replace it with a
database or add distributed infrastructure without evidence of a concrete
need.

## Recommended next sprint: reliability and consistency

1. Fix and test storyboard narration parsing; regenerate the affected Reel
   021 outputs.
2. Normalize Comedy and QA subtype behavior across CLI, UI, persistence,
   regeneration, and batch generation. Decide the Comedy no-subtype brand
   behavior.
3. Make CLI review decisions use the same transition rules and history events
   as the UI.
4. Update roadmap and CLI documentation; establish reproducible dependency
   and interpreter setup.
5. Review untracked files and preserve the required configurations and any
   drafts the user wants retained.

### Sprint acceptance criteria

- Full test suite passes.
- A narration fixture produces narration fields in the storyboard and
  voiceover in the master prompt.
- Comedy batch behavior is consistent across CLI and UI.
- A fresh, documented environment resolves declared runtime and test imports.
- No user-generated records are removed as a side effect of cleanup.

## Exact commands

The only deletion command verified safe by the audit is for the disposable
pytest cache:

```bash
rm -rf .pytest_cache
```

Inspect the current worktree before staging anything:

```bash
git status --short
```

If retaining the current Comedy configuration feature, stage only the two
required untracked configuration files—not all untracked files:

```bash
git add config/comedy.yaml config/brands/life_is_a_glitch.yaml
```

No `git rm` command is recommended. The other untracked files include
user-generated content and browser evidence, and no generated media record
was verified safe to delete.
