# Backlog and Implementation Plan

This backlog describes work that is not necessarily implemented. See
[03_DEVELOPMENT_ROADMAP.md](./03_DEVELOPMENT_ROADMAP.md) for phase sequence
and [02_SYSTEM_ARCHITECTURE.md](./02_SYSTEM_ARCHITECTURE.md) for boundaries.

Priority labels:

- **High Priority:** needed for the next practical increments or to make the
  current workflow dependable.
- **Medium Priority:** valuable after core contracts and profile/brand/format
  boundaries are stable.
- **Future:** depends on validated video production, distribution, or asset
  reuse needs.

The repository is a local Python modular monolith for a solo developer. Avoid
microservices, Kubernetes, event buses, distributed systems, and speculative
infrastructure.

## Current implementation baseline

**[CURRENT]** The project has a local CLI; configured Critical Thinking,
Comedy, and QA Engineering & AI content profiles; an optional d_agnostic_being
personal brand; Reel, single-page, and LinkedIn text-post formats; Instagram
platform; brief-driven content generation; local JSON records; manual list,
approval, rejection, and bulk review; structured timed/untimed storyboard
generation with readable scene-text export; image prompt generation; master
video prompt composition; a configured 4:5 single-page format and Instagram
Feed platform with separate post storage/design-prompt output; and a combined
Reel preparation command.

**[CURRENT] since 22 Oct 2026:** the Buddha-focused teachings system (the Buddha by default
plus Ambedkar, Phule, and Osho; 8 story modes; verified quotes; all
traditions labelled; Mirror voice, Threads-safe captions, Hinglish option); the one-image Reel format
(Poster/Panel layouts, 12 visual styles, cinematic art prompts, still or MP4
clip art); local rendering with music and a film finish; Instagram publishing
with scheduling, AI label, text covers, token refresh, and "Mark as posted";
and a Performance report. Multi-scene Reels still produce text prompts only;
no multi-scene video provider or 3D system is implemented.

## High Priority — code health and operations (from the 22 Oct 2026 review)

### Split the review UI module — [NEXT]
- `scripts/review_ui.py` (about 2,000 lines) mixes HTTP handling, pipeline
  status, publishing, and settings. Split into server, API handlers, and
  pipeline/publishing services without changing behavior; keep tests green.

### Rename the subtype field — [NEXT]
- `qa_subtype` now carries Critical Thinking story modes as well as QA topic
  pillars. Rename to `subtype` (or `story_mode`) and keep old records readable.

### Break up prompt assembly — [NEXT]
- `content_agent.generate_content` is one long function. Split it into small
  section builders (brand, format, thinker, story mode, lens, style, duration)
  and turn Comedy into ordinary profile configuration.

### Configurable text model — [CURRENT]
- Already supported: `MODEL_ENDPOINT` and `MODEL_NAME` in `.env` override the
  Ollama-compatible defaults in `app_settings.py`.

### Runtime upgrade — [NEXT]
- Upgrade from Python 3.9 to 3.11+ (boto3 drops 3.9 support in April 2026).

### Back up local content — [CURRENT]
- Done 22 Oct 2026: `scripts/backup_content.py` zips content to iCloud Drive
  weekly through the scheduler (keeps four, excludes `.env`).

### Scheduler availability — [FUTURE]
- Scheduling depends on the Mac being on. Consider a cloud scheduler only if
  late posts become a real problem.

## Medium Priority — growth features

- Drifting sparks/dust overlay for more motion in still-image Reels (free,
  local ffmpeg).
- One-click art with Cloudflare Workers AI (free tier) through the existing
  `ART_PROVIDER=cloudflare` client.
- A "Scheduled" queue view in the review UI.
- Optional unnamed roles (`art_alias`) for further thinkers when image tools
  refuse them by name.
- Archive or remove the unused multi-scene Reel pipeline if it stays unused.

## High Priority — original backlog

### Content profiles and prompt registry — [NEXT]

- Expand profiles to Storytelling, Motivation, Finance, Career, Fitness, and
  Education while retaining configurable profile assets.
- Add fixture-based evaluations for profile distinction, safe constraints,
  and format-valid output.
- Introduce stable prompt IDs/versions and avoid copying long prompts across
  scripts.
- Record prompt version with new content/plans after a compatible record
  contract is defined.

### Multi-brand foundation — [NEXT]

- Define brand identity, voice, visual identity, defaults, and allowed
  profiles separately from content profiles.
- Specify brand/profile/format/platform precedence and test conflicts.
- Add examples for personal, Daily LOL, and Growth Lab brands as
  configuration only after the schema supports them.
- Keep credentials separate from branding configuration.

### Multi-format contracts — [NEXT]

- Define format-owned fields, validation, aspect ratio, duration, and
  production needs.
- Keep Instagram Reel distinct from Instagram platform and Comedy profile.
- Implement and test a second format before adding the full candidate list:
  YouTube Short, TikTok Video, Carousel, LinkedIn Post, Thread, Blog Article.
- Ensure existing Reel JSON records retain a read path.

### Storyboard system — [NEXT]

- **[CURRENT]** Parse explicit time ranges into stable scene IDs and separate
  visual beats, narration/dialogue, sound cues, and camera notes; preserve
  untimed legacy scenes without inventing timing.
- **[CURRENT]** Save canonical storyboard JSON and export readable scene text
  for existing workflows.
- Add editable scene beats with purpose and continuity notes.
- Define storyboard shots with action, composition, camera intent, and visual
  prompt references.
- Validate duration against the selected format and support human review/edit.

### Visual planning and consistency — [NEXT]

- Define VisualPlan fields for style, lighting, palette, aspect ratio, and
  constraints.
- Separate visual style from content profile where brand overrides or reuse
  require it.
- Add optional character, environment, and camera references to storyboard
  plans without requiring a 3D renderer.
- Add human review of visual prompts and continuity before rendering.

### Local workflow quality — [NEXT]

- Test an end-to-end sample from brief through review and prompt preparation
  without contacting a live model (mock provider).
- Clearly distinguish text prompts from generated images/video in outputs and
  documentation.
- Preserve local paths, safe JSON operations, and existing generated assets.

## Medium Priority

Priority describes relative sequencing within the backlog; a `[FUTURE]`
status means the work is not part of the next implementation phase.

### Video provider abstraction — [FUTURE]

- Define a normalized request/result contract only after storyboard
  acceptance.
- Keep vendor request IDs and provider metadata optional and isolated in the
  adapter.
- Select one provider based on access, quality, cost, rights, and reference
  asset support; do not design around a vendor.
- Mock provider calls and report failure/status explicitly.
- Do not build a generic plugin framework before another provider is needed.

### Voice system — [FUTURE]

- Define voice plan independent of voice rendering: language, delivery,
  pronunciation, timing, and reference identity.
- Define consent, permitted use, and ownership before any voice asset
  generation or reuse.
- Add provider adapter only after text/timing contracts are reliable.

### Music system — [FUTURE]

- Separate music direction from licensed track selection and rendered audio.
- Store rights, attribution, and allowed channels for reusable music assets.
- Keep default music guidance as descriptive prompt text until a verified
  audio workflow exists.

### Asset management — [FUTURE]

- Start with local files plus metadata only when recurring reuse becomes a
  demonstrated need.
- Track stable IDs, owner/brand scope, version, source, rights, and
  production-plan references.
- Avoid a database or remote asset service until local file management is
  insufficient.

## Future

### Character system and 3D animation — [FUTURE]

- Character definitions and reusable visual references.
- Recurring character identity and continuity across scenes/episodes.
- Optional 3D style, model/reference assets, rig/animation requirements, and
  cinematic direction if a selected rendering workflow supports them.
- Comedy, educational, and narrative use cases with human quality review.
- Never promise deterministic character consistency solely from prompts.

### Environment and visual consistency — [FUTURE]

- Reusable environments and scene identities.
- Consistency references shared between storyboard shots and episodes.
- Versioned style references and continuity review.
- Brand-owned reusable visual identities with controlled cross-brand reuse.

### Asset libraries — [FUTURE]

- **Character Library:** identity, appearance, behavior, rights, and approved
  references; owned by a brand/story world or explicitly shared.
- **Environment Library:** reusable locations and continuity constraints;
  ownership and reuse permission attached.
- **Visual Style Library:** palettes, lighting, materials, compositions, and
  examples; brand/profile ownership is explicit.
- **Voice Library:** voice identity, language, consent, and permitted use.
- **Music Library:** track/style metadata, license, channel permissions, and
  attribution.
- Link exact asset versions from each scene/episode for traceability.

### Video generation and rendered asset management — [FUTURE]

- Generate only from reviewed, validated plans.
- Store rendered asset references, generation status, provider metadata, and
  explicit errors.
- Add variant generation only after aspect ratio, duration, and platform
  requirements are verified.
- Establish cost, retention, and rights expectations before sustained use.

### Platform adapters — [FUTURE]

- Define a small platform capability/adapter contract.
- Validate and create platform variants without embedding destination logic
  in profile content.
- Require approval; isolate credentials; record remote IDs and failures.
- Add scheduling only after a real distribution need and safe retry behavior
  are established.

### Analytics and optimization — [FUTURE]

- Link metrics to brand, profile, format, platform variant, and content
  version.
- Begin with simple reports; normalize metrics only when multiple platforms
  are active.
- Keep recommendations human-reviewed and do not silently alter policy.

## Cross-cutting acceptance criteria

- New profile configuration does not require a branch in shared generation
  logic.
- Brand, profile, format, and platform policies remain separate and have
  explicit precedence.
- Scene/storyboard outputs are editable, validated, and traceable to prompt
  versions before video rendering is attempted.
- Provider-specific details remain behind small adapters.
- Current CLI behavior and saved user content remain readable during changes.
- Documentation labels match implementation and never present planned work as
  shipped.
