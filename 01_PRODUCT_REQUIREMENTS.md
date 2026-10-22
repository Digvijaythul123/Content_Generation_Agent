# Product Requirements

## 1. Product vision

Evolve the current local content generator and review workflow into a
configurable AI Content Creation Platform whose primary output is short-form
video content. The platform should progress from content generation to
structured visual planning, then (only after validation) to rendered video,
distribution, and analytics.

The project remains Python-based, locally executable, and a solo-developer-
friendly modular monolith. These requirements describe current state and
future scope explicitly; they do not imply unbuilt features exist.

### Status labels

- **[CURRENT]** Implemented and usable in the repository.
- **[NEXT]** A near-term increment planned for implementation.
- **[FUTURE]** A longer-term direction dependent on earlier phases.

## 2. Current product

### [CURRENT] Implemented capabilities

- Profile-aware content generation for configured profiles, currently
  Critical Thinking, Comedy, and QA Engineering & AI.
- Optional QA Engineering & AI topic-pillar guidance for testing strategy,
  automation architecture, test boundaries, CI reliability, exploratory
  testing, AI-assisted QA, LLM evaluation, and QA communication. Multi-draft
  batches can rotate across these pillars.
- Optional cross-format Comedy category with ten subtypes, Life Is a Glitch
  branding, and format-specific guidance for Reel, single-page, and explicitly
  requested LinkedIn content. Comedy batches can create up to ten separate
  drafts, rotating across subtypes when none is specified. The selected
  category/subtype is stored only on opted-in drafts.
- Single-page social post generation with a format-specific design prompt
  containing exact copy and explicit optional visual labels.
- CLI brief input and JSON draft storage.
- Brand, profile, format, and platform configuration loading; the personal
  brands are d_agnostic_being and Life Is a Glitch, and generation supports no
  brand.
- Human review commands for listing, approving, rejecting, and bulk reviewing
  saved content.
- Structured timed/untimed storyboard generation from a saved Reel, with a
  readable scene-text export for compatibility.
- AI image-prompt generation and master video prompt composition.
- Local file-based workflow and automated tests.
- **Buddha's teachings content (profile `rational_thoughts`, "Buddha's
  Teachings"):** a worldwide Buddhist audience, all traditions labelled, the
  Buddha by default plus Ambedkar, Phule, and Osho (ideas, sources, known
  misattributions), 8 story modes (including
  Mirror and Verified Quote), curated verified quotes, a lens in the Buddha's own "test it in your life"
  spirit, a personal second-person voice, captions capped at
  5 hashtags and 500 characters (Threads-compatible), and an optional
  Hinglish caption line.
- **One-image Reel format:** a 9:16 Reel built from one artwork (a still or
  an MP4/MOV motion clip), with Poster (text over open sky) and Panel (text on
  a dark band) layouts, 12 visual styles, cinematic art prompts, and a
  source/handle footer.
- **Rendering:** a 1080x1920 cover image and an 8-second MP4 with a
  first-frame hook, staggered text reveals, a free film finish (push-in,
  breathing light, vignette, grain), and royalty-free music matched to mood.
- **Instagram publishing:** one-click or scheduled publishing through the
  Instagram API (via Cloudflare R2), text covers, the AI-content label,
  weekly token refresh, a per-minute macOS scheduler, and a manual
  "Mark as posted" path.
- **Analytics:** a Performance report of views, reach, saves, shares, and
  watch time per post, grouped by story mode, visual style, and thinker.

Artwork is created by hand in an image tool (Gemini, Meta AI) from the
generated art prompt, or by the optional image API. The text model is an
Ollama-compatible endpoint set by `MODEL_ENDPOINT` and `MODEL_NAME` in `.env`. Multi-scene AI video generation is not
implemented.

## 3. Product users

- **[CURRENT] Creator / solo operator:** supplies a brief, chooses a profile,
  runs generation, and reviews local drafts.
- **[NEXT] Editor:** reviews structured scenes and storyboard plans, edits
  content and visual instructions, and approves preparation for production.
- **[FUTURE] Publisher / team administrator:** manages accounts, permissions,
  publishing policy, and multiple collaborators if product usage warrants it.

## 4. Domain model and separation

- **Source / idea / brief:** input to a generation run. Initially a text brief;
  later it may include a transcript or referenced source with provenance.
- **Brand:** optional publishing identity: name, brand voice, reusable
  branding, defaults, and (later) account references. Example: d_agnostic_being.
- **Content profile:** editorial mode, such as Critical Thinking / Rational Thoughts, Comedy,
  Storytelling, Motivation, Finance, Career, Fitness, Education, Relationships,
  or a future profile. It defines audience, objectives, voice, constraints,
  and relevant prompt/visual guidance.
- **Content category:** optional cross-format generation guidance, currently
  Comedy. It can include a subtype without changing the selected format or its
  output contract.
- **Format:** output shape and requirements. Examples include Instagram Reel,
  YouTube Short, TikTok Video, Carousel, LinkedIn Post, Thread, and Blog
  Article. Instagram Reel, single-page post, and LinkedIn text post are
  currently configured.
- **Platform:** destination capabilities, media limits, and (eventually)
  publishing rules. Instagram is the current configured platform.
- **Content item:** generated draft plus selected brand, profile, format,
  platform, source/brief, content fields, and lifecycle state.
- **Production plan / asset:** structured scene, storyboard, character,
  environment, camera, voice, music, prompt, or rendered-media data. Most of
  these are planned rather than current domain records.

Format is distinct from profile: Comedy can produce a Reel or a text post;
Instagram Reel is not an editorial niche. A platform can accept multiple
formats subject to its configured capabilities.

## 5. Functional requirements by status

### [CURRENT] Generation and review

1. Accept a text brief or generate without one for legacy behavior.
2. Select a configured content profile, brand, format, and platform.
3. Generate and validate the configured content fields.
4. Store a local JSON draft with the brief and selected configuration IDs.
5. Support manual listing, approval, rejection, and bulk review.
6. Generate a validated storyboard JSON and readable scene text, then image
   prompts and a master video prompt from a saved Reel.
7. Preserve explicit scene time ranges and keep narration separate from visual
   directions in storyboard-driven prompt composition.
8. Keep errors visible when configuration, storage, storyboard, or model
   responses fail.
9. Generate single-page posts with their own required fields and save them
   separately from Reel records, including a reusable design prompt.
10. Apply optional Comedy category/subtype guidance to supported formats
    without changing their required content fields or normal non-comedy
    behavior.
11. Generate up to ten separate drafts in a batch; when Comedy is selected
    without a subtype, rotate across its configured subtypes.

### [NEXT] Configurable content and production planning

1. Expand the profile catalog while keeping profile policy in configuration
   and prompt assets rather than shared business-logic branches.
2. Support multiple brands with explicit identity, voice, reusable branding,
   and profile/format/platform defaults.
3. Support multiple formats with format-specific schemas and validation.
4. Add a prompt registry with stable IDs/versions and consistent use across
   generation and visual preparation.
5. Extend the current validated storyboard contract with editable review
   workflows, continuity, and richer scene/shot planning.
6. Add explicit planning contracts for visual style, character, environment,
   camera, voiceover, and music.
7. Keep human review between content generation and production preparation.

### [CURRENT] Production and distribution (one-image Reels)

1. Generate a text-free, cinematic art prompt per post (subject placement
   per layout, style recipe, thinker named or replaced by an unnamed role
   when image tools refuse a public figure).
2. Accept artwork as an image or a short MP4/MOV clip and render a cover
   image and an 8-second MP4 with text, footer, film finish, and music.
3. Review the caption (hashtag and Threads length checks), music, and layout
   before posting; publishing always needs explicit confirmation or a
   schedule.
4. Publish Reels through the Instagram API with a text cover and the AI label;
   record the permalink and status; never retry a failed scheduled post
   until it is rescheduled.
5. Refresh the Instagram token automatically and report post performance.

### [FUTURE] Video production and distribution

1. Integrate one or more video-generation providers through a provider-neutral
   contract (today, clips from tools such as Meta AI are attached by hand).
2. Track generation requests, provider responses, costs/limits where exposed,
   failures, and rendered media paths or references.
3. Support reusable 3D characters, recurring characters, environments,
   visual styles, voices, and music identities.
4. Create platform-specific rendered variants without embedding platform
   logic in the editorial profile.
5. Add publishing adapters for further platforms (Instagram is current).
6. Extend analytics into optimization suggestions linked to content versions,
   always human-reviewed.

## 6. Short-form video production requirements

The intended pipeline is:

```text
Source / Idea / Brief
    -> Brand + Content Profile + Format + Platform
    -> Content Generation
    -> Review
    -> Scene Planning
    -> Visual Planning
    -> Storyboard
    -> Character + Environment + Camera + Voiceover + Music Plans
    -> Master Video Prompt
    -> AI Video Generation
    -> Rendered Video Asset
    -> Platform Variants
    -> Publishing
```

Status at each stage:

| Stage | Status | Requirement |
|---|---|---|
| Source / brief | [CURRENT] | Text brief is accepted and stored. Structured sources and citations are [NEXT]. |
| Brand/profile/format/platform selection | [CURRENT] | Basic YAML resolution exists; broader catalogs and brand independence are [NEXT]. |
| Content generation and review | [CURRENT] | Reel draft generation and local review workflow exist. |
| Scene planning | [CURRENT] | Basic timed/untimed storyboard beats can be generated; richer intent/continuity is [NEXT]. |
| Visual planning | [CURRENT] | Profile guidance informs image/master prompts; opted-in Comedy drafts add joke-driven visual and timing guidance. More complete planning is [NEXT]. |
| Storyboard | [NEXT] | Define editable scene-to-shot plans, timing, intent, and continuity. |
| Character/environment/camera/voice/music plans | [NEXT] | Begin as optional structured plans; do not require 3D. |
| Master video prompt | [CURRENT] | Text prompt composition exists; versioning and richer contracts are [NEXT]. |
| Video generation and rendered asset | [CURRENT] / [FUTURE] | One-image Reels render to MP4 locally (still or attached clip). Multi-scene AI video generation is [FUTURE]. |
| Platform variants/publishing | [CURRENT] | Instagram Reels and Feed posts publish through the Instagram API with scheduling. Other platforms are [FUTURE]. |
| Analytics | [CURRENT] | Per-post Instagram insights grouped by story mode, style, and thinker. |

## 7. 3D and recurring-story requirements

### [FUTURE]

- Original 3D character definitions and reusable character references.
- Recurring characters with stable appearance, voice, and behavior across
  episodes.
- Reusable environments and visual identities.
- Cinematic camera and lighting continuity.
- Comedy, educational, and other character-based storytelling.
- Episode-level references to the exact versions of characters, environments,
  styles, and prompts used.

These capabilities must not be described as current. First validate
storyboards and visual consistency through human review and provider-neutral
asset references.

## 8. Asset library requirements

- **[NEXT] Prompt registry:** stable prompt IDs, version history, profile/
  format applicability, and test examples. Avoid duplicating prompt text
  across scripts.
- **[CURRENT] Visual style references:** 12 visual styles with recipes and
  "avoid" lists live in the Buddha's Teachings profile configuration.
- **[FUTURE] Character Library:** reusable character identity and approved
  visual references; owned by a brand or shared library with explicit reuse
  permissions.
- **[FUTURE] Environment Library:** reusable locations and continuity
  guidance; owned by a brand/story world or explicitly shared.
- **[FUTURE] Voice Library:** voice identity, pronunciation, language, and
  rights/consent metadata.
- **[CURRENT] Music folder:** royalty-free tracks in `music/` (not in git),
  matched to each post's mood by file name. **[FUTURE]** licensing metadata.

Asset ownership, permission, version, and provenance must be explicit before
cross-brand reuse or generated commercial use.

## 9. Provider-neutral video generation

### [FUTURE]

The platform may support multiple video-generation providers, including
current or future services. Product logic must not depend on a specific
vendor's API, prompt format, or output storage. Define a small internal
contract for:

- submitted prompt/storyboard and generation settings;
- optional referenced assets and capabilities;
- returned job/result status, rendered asset references, and provider
  metadata;
- explicit errors, retries, timeouts, and usage/cost information where
  available.

Provider-specific adaptation belongs in a narrow Python module. Do not build
a general plugin framework before a second provider is needed.

## 10. Non-functional requirements

- **Simple:** Python, local execution, modular monolith; no microservices,
  Kubernetes, event buses, or distributed systems.
- **Maintainable:** clear contracts, small modules, configuration validation,
  focused tests, and docs synchronized with implementation.
- **Extensible:** adding a profile or brand should primarily add configuration
  and prompt assets; adding a format should provide its contract and tests.
- **Reliable:** do not save malformed successful-looking output; surface
  model, file, validation, and provider failures.
- **Traceable:** preserve selected configuration IDs, source/brief, and prompt
  versions as contracts evolve.
- **Human-controlled:** retain approval before any future publishing.
- **Rights-aware:** record permissions/provenance for source, character,
  voice, and music assets before production and distribution.

## 11. Success measures

### [NEXT]

- Add a new profile without editing shared generation logic.
- Produce valid outputs for several materially different profiles.
- Review scene/storyboard plans for timing, continuity, and brief alignment.
- Track acceptance, edits, and rejections for manually generated drafts.

### [FUTURE]

- Measure rendered-video success, visual consistency, cost, and editing time.
- Measure publishing reliability and performance only after integrations
  exist.

## 12. Out of scope until justified

- Multi-tenant SaaS, billing, team administration, microservices, Kubernetes,
  event buses, and distributed processing.
- Publishing without human approval: every post is reviewed and either
  published with confirmation or explicitly scheduled.
- A custom 3D renderer or video editor before a provider-backed workflow is
  validated.
- Autonomous optimization that changes brand or editorial policy without
  human review.
