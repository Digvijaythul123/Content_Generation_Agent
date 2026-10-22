# Development Roadmap

The roadmap is incremental and deliberately local-first. Each phase is a
candidate scope, not a claim that work has shipped. Status terms:
**[CURRENT]** implemented, **[NEXT]** upcoming, **[FUTURE]** later direction.
Do not start a phase until its dependencies and acceptance criteria are
understood.

## Current baseline

**[CURRENT]** Profile-based Reel content generation, optional brief input,
local JSON records, CLI review/approval, structured timed/untimed storyboard
generation with readable scene-text export, profile-aware image prompt
generation, master video prompt composition, and configured single-page
Instagram Feed post generation with a separate design prompt.

**[CURRENT] since 22 Oct 2026:** a Buddha-focused teachings system (the Buddha by default, plus Ambedkar, Phule, and
Osho; 8 story modes; verified quotes; all traditions labelled); the
one-image Reel format with Poster/Panel layouts and 12 visual styles; local
rendering of cover images and 8-second MP4s (still or attached clip, music,
film finish); Instagram publishing with scheduling, AI label, text covers, and
token refresh; and a per-post Performance report.

**Not current:** richer editable visual/continuity plans, multi-scene AI video
generation, 3D assets, and publishing to platforms other than Instagram.

## Phase 1 — Multi-profile content generation

**Status: [CURRENT/NEXT]** Critical Thinking / Rational Thoughts, Comedy, and QA Engineering & AI
are configured; broader catalog breadth and evaluation remain incomplete.

- **Objectives:** make editorial modes genuinely configurable and keep the
  generation pipeline independent of niche-specific conditions.
- **Deliverables:** profile schema/prompt guidance; initial profiles for
  Critical Thinking, Comedy, Storytelling, Motivation, Finance, Career,
  Fitness, Education, Relationships, and future profiles; profile isolation
  tests; prompt/version references; consistent field validation.
- **Dependencies:** current config loader and content contracts.
- **Risks:** profile policies can conflict with brand identity or produce
  superficial tone changes only.
- **Exit criteria:** multiple materially different profiles pass saved
  fixture-based validation without changes to shared pipeline logic.

## Phase 2 — Multi-brand support

**Status: [CURRENT/NEXT]** The d_agnostic_being personal brand is configured;
brand catalog breadth and evaluation remain incomplete.

- **Objectives:** separate publisher identity from editorial profile.
- **Deliverables:** brand name, voice, reusable branding, visual identity,
  defaults, allowed profiles, and clear precedence; brand isolation tests.
- **Dependencies:** stable profile contracts and configuration validation.
- **Risks:** brand voice can override or conflict with profile requirements;
  secrets may be confused with public brand data.
- **Exit criteria:** two brands can use the same profile without leaking
  identity or settings; brand-specific defaults and overrides are documented.

## Phase 3 — Multi-format support

**Status: [CURRENT/NEXT]** Reel, one-image Reel, single-page post, and
LinkedIn text post are configured; YouTube Short, Carousel, and Thread remain.

- **Objectives:** separate content shape from profile and platform.
- **Deliverables:** reusable format schema and validators; prioritize
  Instagram Reel and YouTube Short, then assess TikTok Video, Carousel,
  LinkedIn Post, Thread, and Blog Article; format-specific prompts/tests.
- **Dependencies:** Phase 1 profiles and Phase 2 brand defaults.
- **Risks:** trying to force non-video formats into Reel-specific fields;
  conflating format constraints with platform limits.
- **Exit criteria:** at least two formats use the shared configuration
  pipeline with their own required fields and validation.

## Phase 4 — Visual planning and storyboarding

**Status: [NEXT]** Basic structured storyboards and timing preservation are
current; expanded visual planning and human editing/review remain.

- **Objectives:** make visual intent coherent and inspectable before video
  provider integration.
- **Deliverables:** richer ScenePlan and StoryboardShot contracts; VisualPlan;
  optional character/environment/camera/voiceover/music plans; prompt registry
  and versions; human edit/review flow; format-aware timing validation.
- **Dependencies:** stable profile, brand, and format context.
- **Risks:** over-modeling before validating prompt quality; losing timing or
  continuity during text parsing.
- **Exit criteria:** a saved Reel can produce a validated, editable storyboard
  with timings that satisfy format constraints and traceable prompt versions.
  Current JSON/text exports cover basic beats and timing but do not meet these
  richer planning and review criteria.

## Phase 5 — AI video generation

**Status: [CURRENT/FUTURE]** One-image Reels render locally to MP4 and can
use a hand-attached AI clip (for example from Meta AI) as moving art. No
multi-scene video provider is integrated.

- **Objectives:** render approved plans through a provider-neutral boundary.
- **Deliverables:** normalized video request/result contract; one provider
  adapter selected after product, cost, access, and rights review; local
  rendered asset tracking; explicit failures/status; mocked contract tests.
- **Dependencies:** Phase 4 storyboard quality and a provider access/rights
  decision.
- **Risks:** variable output quality, provider availability/limits, cost,
  rights, and inconsistency between shots.
- **Exit criteria:** approved plan reliably maps to a tracked rendered asset
  or explicit failure; no provider details leak into domain logic.

## Phase 6 — Character and asset system

**Status: [FUTURE]** A thinker library, visual-style library, and local music
folder exist; no character, environment, or voice library exists.

- **Objectives:** support reusable identities and continuity for episodic,
  educational, and comedy storytelling, including possible 3D production.
- **Deliverables:** asset records and ownership; Character Library,
  Environment Library, Visual Style Library, Voice Library, Music Library;
  version and rights metadata; episode references; consistency evaluation.
- **Dependencies:** Phase 4 plan contracts; Phase 5 provider capabilities
  determine viable reference workflows.
- **Risks:** rights/consent violations, excessive catalog complexity, and
  overstated consistency guarantees.
- **Exit criteria:** an episode can refer to approved versioned assets and a
  human reviewer can compare continuity across scenes/episodes.

## Phase 7 — Publishing and distribution

**Status: [CURRENT]** for Instagram: approved Reels and Feed posts publish
through the Instagram API with confirmation, scheduling (macOS LaunchAgent),
AI label, text cover, and weekly token refresh. Other platforms are [FUTURE].

- **Objectives:** distribute only approved and validated content.
- **Deliverables:** platform capability contracts; one verified publishing
  adapter; platform variants; explicit approval gate; credentials isolated
  from content configuration; publish status and recovery guidance.
- **Dependencies:** stable format/platform contracts and, for video,
  Phase 5 rendered assets.
- **Risks:** API policy/access changes, account restrictions, duplicate posts,
  and credential exposure.
- **Exit criteria:** tests cover validation, approval, success, and explicit
  failure; live publishing remains opt-in and auditable.

## Phase 8 — Analytics and optimization

**Status: [CURRENT/FUTURE]** A Performance report reads per-post insights and
groups them by story mode, visual style, and thinker. Automated optimization
is [FUTURE] and must stay human-reviewed.

- **Objectives:** understand content outcomes without uncontrolled policy
  changes.
- **Deliverables:** per-platform metrics linked to content/version/brand;
  simple local reports; reviewed experiments and recommendations.
- **Dependencies:** Phase 7 publication identifiers and available metrics.
- **Risks:** platform metric differences, attribution errors, and optimizing
  for engagement at the expense of brand or audience well-being.
- **Exit criteria:** metrics can be traced to a content variant and all
  recommendations remain human-reviewed.

## Cross-phase quality gates

- Keep commands runnable locally and preserve existing JSON and text assets.
- Add focused tests for contracts, configuration, prompt assembly, and error
  paths before expanding features.
- Update all five project documents when actual implementation status changes.
- Keep provider/vendor specifics behind small adapters.
- Do not introduce microservices, Kubernetes, event buses, distributed
  processing, or infrastructure without a demonstrated local requirement.
- Respect source, image, character, voice, and music rights and permissions.
