# AI Content Creation Platform

## Purpose

This repository is a local Python prototype for generating and reviewing
short-form content. Its intended direction is a configurable content platform
whose primary output is short-form video content. Development is planned as a
solo-developer-friendly modular monolith; distributed infrastructure is not a
goal.

The status labels in this document distinguish shipped behavior from planned
work:

- **[CURRENT]** Implemented in this repository.
- **[NEXT]** A reasonable near-term increment; not implemented yet.
- **[FUTURE]** A longer-term capability that depends on earlier work.

## Capability status

| Capability | Status | What that means today |
|---|---|---|
| Profile-based content generation | [CURRENT] | YAML profiles currently include Rational Thoughts and Comedy. |
| Brief input and JSON content records | [CURRENT] | The CLI accepts a brief and saves a local JSON draft. |
| Draft review and approval | [CURRENT] | CLI commands list, approve, reject, and bulk-review saved drafts. |
| Scene and visual preparation | [CURRENT] | Commands produce scene text, image prompts, and a master video prompt. |
| Single-page social posts | [CURRENT] | The pipeline generates 4:5 Instagram Feed post copy and a ready-to-use design prompt with exact copy and optional diagram labels. |
| Additional profiles, brands, and formats | [NEXT] | The data-driven direction exists, but support and coverage are incomplete. |
| Structured storyboard parsing | [CURRENT] | Timed or untimed scene beats are saved as JSON and readable text; richer review/edit flows remain [NEXT]. |
| Character, environment, camera, and music plans | [NEXT] | Reusable, independently reviewable plans are not yet modeled. |
| AI video rendering | [FUTURE] | No video provider integration or rendered video output exists. |
| Recurring 3D characters and reusable asset library | [FUTURE] | Not implemented. |
| Social publishing and analytics | [FUTURE] | No scheduler, publisher, or analytics integration exists. |

## Current workflow

```text
Brief + Brand + Content Profile + Format + Platform
    -> generated Reel or single-page post draft
    -> local JSON record
    -> human review / approval
    -> Reel: structured storyboard + image prompt + master video prompt
    -> Single-page: post copy + design prompt
```

**[CURRENT]** The model client uses a fixed Ollama-compatible endpoint/model.
Content and text assets are stored locally. The visual preparation pipeline
creates prompts only; it does not create images, animation, or video. The
single-page workflow saves records under `generated_posts/` and design prompts
under `generated_assets/`.

## Domain concepts

- **Content profile**: editorial mode such as Comedy, Finance, or Rational
  Thoughts. It defines audience, goals, voice, constraints, and profile visual
  direction.
- **Brand**: publisher identity, brand voice, reusable identity, and defaults.
  A brand can use multiple content profiles.
- **Format**: output shape, such as Instagram Reel, YouTube Short, carousel,
  LinkedIn post, thread, or blog article.
- **Platform**: destination and its capabilities or publishing constraints.

**Format is not a content profile.** Comedy is an editorial profile; Instagram
Reel is a format; Instagram is a platform. A profile should work across
compatible brands, formats, and platforms without niche-specific branches in
the shared pipeline.

## Running the current CLI

Run commands from the repository root using Python module invocation:

```bash
python3 -m scripts.main --profile comedy \
  --brief "A relatable office mix-up with an unexpected punchline"
python3 -m scripts.main --profile rational_thoughts \
  --format single_page --platform instagram_feed \
  --brief "Explain why confidence is not evidence."
python3 -m scripts.review_ui
python3 -m scripts.list_reels
python3 -m scripts.approve_reel reel_017
python3 -m scripts.storyboard_generator reel_017
python3 -m scripts.prepare_reel reel_017
```

`scripts.prepare_reel` creates a validated storyboard at
`generated_videos/<reel_id>_storyboard.json`, exports a readable
`<reel_id>_scenes.txt`, generates image prompts, and composes a master video
prompt. Timed beats retain their source timecodes; untimed legacy scripts stay
untimed. Image-prompt generation calls the configured model. No stage renders
an image or video. See the individual commands under [scripts/](./scripts/).
The older `scripts.scene_generator` command remains as a compatibility alias
for storyboard generation.

`scripts.review_ui` opens a local-only browser workspace at
`http://127.0.0.1:8765`. It lists saved Reels and single-page posts with their
statuses, lets you inspect their content, and provides a form to generate
drafts by brand, profile, format, platform, and optional brief. Generation
uses the same configured model service as the CLI; status changes remain in
the existing review commands.

## Configuration and storage

**[CURRENT]** Brand, profile, format, and platform YAML live under `config/`.
Reusable generation instructions are in `prompts/`. Reel records are JSON in
`generated_reels/`; single-page records are JSON in `generated_posts/`.
Storyboard records are JSON and scene/master prompts are text under
`generated_videos/`; image/design prompts are text under `generated_images/`
and `generated_assets/`.

Local paths resolve from the project directory. Keep credentials out of YAML,
JSON records, and prompts. The current provider endpoint and model are fixed
in code, so provider configuration is a planned task, not an existing feature.

## Planned direction

- **[NEXT]** Expand profile and brand configuration; extend storyboard
  contracts with richer visual planning, continuity, and editing/review.
- **[NEXT]** Add a prompt registry and explicit visual planning for style,
  characters, environments, camera, voiceover, and music.
- **[FUTURE]** Add an optional provider-neutral video generation adapter and
  rendered asset tracking after manual prompt quality is validated.
- **[FUTURE]** Add reusable character, environment, style, voice, and music
  libraries, including 3D consistency support.
- **[FUTURE]** Add publishing and analytics only after approved content,
  rendered assets, and platform requirements are established.

See [01_PRODUCT_REQUIREMENTS.md](./01_PRODUCT_REQUIREMENTS.md) for scope,
[02_SYSTEM_ARCHITECTURE.md](./02_SYSTEM_ARCHITECTURE.md) for boundaries,
[03_DEVELOPMENT_ROADMAP.md](./03_DEVELOPMENT_ROADMAP.md) for sequencing, and
[04_BACKLOG_AND_TASKS.md](./04_BACKLOG_AND_TASKS.md) for prioritized work.

## Development constraints

Keep the implementation Python-based, locally executable, and organized as a
modular monolith. Prefer configuration, explicit contracts, small modules,
and tests over new infrastructure. Do not introduce microservices,
Kubernetes, event buses, or distributed systems for this project.
