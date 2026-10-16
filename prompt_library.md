# Prompt Library

Internal prompt repository for planning, building, reviewing, and evolving the
Content Creation Platform. Treat prompts as maintained engineering assets:
adapt the bracketed inputs, preserve project constraints, and verify generated
recommendations against the repository before implementation.

## How to use this library

- Replace every `{{PLACEHOLDER}}` with concrete project context. Remove
  irrelevant optional sections before submitting.
- Include the repository state, relevant files, actual constraints, and desired
  deliverable. Do not assume the model has inspected the code unless it has.
- For implementation prompts, request a short file-by-file plan before edits
  when the change is broad, data-affecting, or architecturally significant.
- Ask for evidence: paths, symbols, observed behavior, and tests. Distinguish
  verified facts from assumptions and recommendations.
- Keep the project's current product model distinct: **source**, **brand**,
  **content profile**, **format**, and **platform** are separate concepts.
- Keep outputs local-first unless a task explicitly justifies external
  services. Do not introduce databases, APIs, queues, schedulers, publishers,
  or major architectural layers merely for hypothetical scale.
- Never include API keys, access tokens, private customer data, or other
  secrets in prompt inputs.

---

## 1. Project Analysis Prompts

### Repository Review

**Use when:** You need a broad, evidence-based assessment of an existing
repository before deciding what to build next.

```text
Act as a senior software architect and pragmatic engineering reviewer.

Review the entire repository at {{REPOSITORY_PATH}}. Inspect source,
configuration, tests, documentation, and representative persisted data where
available. Do not infer that documented features exist unless implementation
proves they do.

Project context:
- Product: {{PRODUCT_DESCRIPTION}}
- Current users/workflow: {{CURRENT_WORKFLOW}}
- Intended direction: {{TARGET_DIRECTION}}
- Constraints: {{CONSTRAINTS}}

Assess:
1. Repository structure, naming, cohesion, coupling, and technical debt.
2. Current architecture, strengths, weaknesses, hidden risks, and fit for the
   intended direction.
3. Core workflow correctness and failure handling.
4. Code quality, testing, dependency hygiene, configuration, and data safety.
5. Product readiness and the largest blockers to the intended direction.
6. Documentation accuracy and contradictions with implementation.

For each material finding, provide evidence (file and symbol/line), impact,
likelihood, and a practical remedy. Separate confirmed defects from risks and
future opportunities. Prioritize changes by user impact and architectural
leverage, not by theoretical purity.

Deliver:
- Executive summary
- Architecture, code quality, and product-readiness scores (1-10) with
  rationale
- Highest-impact findings
- Data-loss/security/reliability risks
- What should remain unchanged
- Recommended next three steps
- Suggested files to add, modify, or retire

Do not modify files. Do not recommend large infrastructure unless the evidence
shows it is necessary for the stated product and constraints.
```

### Architecture Review

**Use when:** Evaluating architecture fitness, boundaries, and evolution
options without asking for a line-by-line code review.

```text
Act as a principal software architect reviewing {{SYSTEM_OR_REPOSITORY}}.

Current architecture: {{CURRENT_ARCHITECTURE}}
Target capabilities: {{TARGET_CAPABILITIES}}
Scale and operating model: {{USERS_TRAFFIC_DATA_TEAM}}
Constraints: {{CONSTRAINTS}}

Trace the important runtime and data flows. Identify actual components,
dependencies, data ownership, integration boundaries, and failure paths from
the code. Assess cohesion, coupling, change isolation, observability, and
migration cost.

For each proposed boundary, explain what can change independently and why.
Distinguish boundaries that are useful now from those that should wait. Compare
at least two viable options when there is a meaningful tradeoff.

Return:
- Current-state diagram in text
- Key architectural strengths and weaknesses
- Highest-leverage design decisions
- Recommended target architecture at the smallest useful scale
- Migration sequence and compatibility risks
- Decisions explicitly deferred

Do not impose microservices, DDD, event-driven systems, or infrastructure
without a concrete requirement that cannot be met more simply.
Do not change files.
```

### Technical Debt Review

**Use when:** Creating an actionable debt register, rather than collecting
style preferences.

```text
Review {{REPOSITORY_OR_SCOPE}} for technical debt that materially affects
correctness, delivery speed, data safety, or future change.

Context: {{PRODUCT_AND_TEAM_CONTEXT}}
Near-term changes: {{PLANNED_WORK}}

For every finding:
- Cite the file and affected behavior.
- State the consequence and likelihood.
- Estimate remediation effort as XS/S/M/L.
- Identify dependencies and regression risks.
- Recommend the smallest durable fix.

Rank findings by expected cost of leaving them in place, not by code
imperfection. Separate:
1. Bugs and unsafe behavior
2. Reliability and data-loss risks
3. Change-friction debt
4. Documentation/test gaps
5. Cosmetic cleanup

Finish with a prioritized debt register and a short "do not fix yet" list.
Do not modify files.
```

### Scalability Review

**Use when:** Determining whether current design can support a specific,
measurable increase in products, content, users, or integrations.

```text
Assess the scalability of {{SYSTEM}} for this concrete target:
{{TARGET_SCALE_AND_WORKLOAD}}.

Current environment: {{RUNTIME_AND_STORAGE}}
Expected growth: {{EXPECTED_GROWTH}}
Constraints: {{TEAM_BUDGET_LATENCY_RELIABILITY}}

Trace likely bottlenecks through the actual implementation. Cover throughput,
concurrency, state growth, external-provider limits, operational burden, and
failure recovery. Estimate where possible and label assumptions clearly.

For each issue, state:
- Evidence in the current design
- Scale threshold or condition that makes it relevant
- User/business impact
- Smallest adequate remedy
- Cost and new operational complexity

Separate immediate design hygiene from scale-triggered investments. Do not
recommend distributed systems or optimization for unmeasured workloads.
Do not modify files.
```

### Security Review

**Use when:** Performing a security-focused review. Supply this prompt to an
authorized security reviewer or tool and follow its required reporting format.

```text
Perform a security review of {{REPOSITORY_OR_DIFF}}. Treat this as a
defensive, authorized assessment. Do not exploit live systems, access
credentials, or exfiltrate data.

Review the relevant trust boundaries, input validation, file/path handling,
secrets, subprocess/network use, dependencies, authentication/authorization,
logging, and data exposure. Trace reachable flows and distinguish exploitable
vulnerabilities from hardening suggestions.

For each finding report:
- Severity: Critical, High, Medium, or Low
- Exact file and line(s)
- Preconditions and attack path
- Concrete impact
- Confidence from 1-10
- Minimal remediation

Do not report hypothetical issues without a plausible reachable path. Include
scope, areas inspected, and important limitations. Do not modify files.
```

### Performance Review

**Use when:** Investigating a measured slowdown or checking a hot path before
optimizing it.

```text
Review {{CODE_PATH_OR_WORKFLOW}} for performance against this measured
problem: {{OBSERVED_LATENCY_OR_RESOURCE_USE}}.

Workload and environment: {{WORKLOAD_ENVIRONMENT}}
Target: {{MEASURABLE_TARGET}}
Available measurements: {{PROFILES_LOGS_METRICS}}

Follow the actual execution path. Identify likely costs, but separate measured
facts from hypotheses. Recommend the smallest profiling step needed to confirm
uncertainty. Rank fixes by expected impact, implementation effort, and
regression risk.

Do not optimize unrelated code or introduce caches/concurrency without
considering invalidation, consistency, and operational cost. Provide a
verification plan using the same workload and metric. Do not modify files.
```

---

## 2. AI Agent Design Prompts

### Generic Agent Design

**Use when:** Designing one agent that performs a bounded task with explicit
inputs, tools, and completion criteria.

```text
Design a reliable AI agent for {{TASK}}.

User and use case: {{USER_AND_USE_CASE}}
Inputs: {{INPUTS}}
Expected outputs: {{OUTPUTS}}
Allowed tools/actions: {{TOOLS}}
Forbidden actions: {{FORBIDDEN_ACTIONS}}
Human checkpoints: {{HUMAN_CHECKPOINTS}}
Runtime constraints: {{CONSTRAINTS}}

Specify:
1. Agent responsibility and explicit non-responsibilities.
2. Input/output schema and validation.
3. State transitions and stopping conditions.
4. Prompt structure and what belongs in configuration versus code.
5. Tool-use policy, error handling, retries, and idempotency.
6. Safety, privacy, and human approval boundaries.
7. Evaluation cases, success metrics, and failure tests.

Prefer a deterministic workflow with model calls at well-defined steps over
open-ended autonomy. Identify assumptions and unresolved decisions. Do not
implement until the design is reviewed.
```

### Multi-Agent Design

**Use when:** Multiple specialized agents may be justified and coordination
cost must be compared with a single pipeline.

```text
Evaluate whether {{WORKFLOW}} needs multiple AI agents or can be implemented
as one agent/pipeline.

Requirements: {{REQUIREMENTS}}
Independent responsibilities: {{CANDIDATE_RESPONSIBILITIES}}
Shared state/data: {{SHARED_STATE}}
Risk and approval constraints: {{CONSTRAINTS}}

First compare one-agent, deterministic-pipeline, and multi-agent options.
Recommend multiple agents only if independent context, permissions, or
parallel work produces a meaningful benefit.

If multi-agent is justified, define each agent's bounded responsibility,
contract, tools, allowed data, handoff format, failure behavior, and human
oversight. Explain coordination, duplicate-work, consistency, and debugging
risks. Include a simpler fallback design.
```

### Content Agent Design

**Use when:** Specifying the generation behavior for the Content Creation
Platform.

```text
Design the content-generation agent for {{CONTENT_USE_CASE}}.

Resolved context:
- Source/brief: {{SOURCE}}
- Brand: {{BRAND}}
- Content profile: {{PROFILE}}
- Format: {{FORMAT}}
- Platform: {{PLATFORM_OR_NONE}}

Output schema: {{OUTPUT_SCHEMA}}
Voice/safety constraints: {{POLICIES}}
Human review requirements: {{REVIEW_RULES}}

Define prompt inputs, generation steps, validation, provenance, failure
handling, and evaluation. Keep source, brand, editorial profile, format, and
platform distinct. Platform constraints must not silently change editorial
policy. Do not invent facts or claims; specify when to ask for sources or flag
uncertainty.

Return a concise design, example request/result, edge cases, and tests. Do not
generate implementation code unless separately requested.
```

### Workflow Design

**Use when:** Designing an end-to-end content workflow with human checkpoints.

```text
Design a workflow for {{WORKFLOW_GOAL}} using the existing capabilities
{{CURRENT_CAPABILITIES}}.

Inputs: {{INPUTS}}
Outputs/artifacts: {{OUTPUTS}}
Approval policy: {{APPROVAL_POLICY}}
Failure/retry constraints: {{CONSTRAINTS}}

Describe each stage, its input/output contract, persisted state, owner,
validation, and recovery behavior. Identify which steps are synchronous and
which are long-running; do not introduce background jobs unless the measured
workflow requires them.

Include a text flow diagram, state transitions, error paths, idempotency
considerations, and the smallest useful implementation sequence.
```

### Configuration Design

**Use when:** Defining configuration objects, schemas, defaults, and precedence.

```text
Design a configuration hierarchy for {{SYSTEM_CAPABILITIES}}.

Required concepts: {{CONCEPTS}}
Example configurations: {{EXAMPLES}}
Runtime overrides: {{OVERRIDES}}
Validation and secret constraints: {{CONSTRAINTS}}

For the Content Creation Platform, consider Brand, ContentProfile, Format,
Platform, and per-run request as separate concepts. Define:
- Required/optional fields and stable IDs
- Defaults and override precedence
- Cross-reference validation
- Versioning and compatibility
- Safe loading and actionable errors
- Which values are secret and where they belong

Keep configuration declarative; do not put executable business logic in YAML.
Recommend the simplest format and schema validation appropriate for the
repository. Include valid and invalid examples.
```

### Prompt Registry Design

**Use when:** Organizing reusable prompt assets and tracking which prompt
produced an output.

```text
Design a prompt registry for {{AGENT_OR_PRODUCT}}.

Prompt dimensions: {{SHARED_PROFILE_BRAND_FORMAT_PLATFORM}}
Required traceability: {{VERSIONING_REQUIREMENTS}}
Template runtime: {{RUNTIME_CONSTRAINTS}}

Define prompt IDs, file organization, composition order, variable validation,
versioning, escaping, and provenance stored with generated output. Separate
prompt content from code that selects and renders it. Explain how to test
rendered prompts and prevent missing-variable or injection errors.

Provide a minimal example registry and two composed prompts. Avoid building a
general-purpose templating platform unless project evidence requires it.
```

---

## 3. Project Generation Prompts

### Design an End-to-End Production-Ready Project

**Use when:** Starting a project or producing a coherent project blueprint
before code generation. This prompt produces a design package, not a claim
that the design is already implemented.

```text
Act as a product-minded principal architect and senior implementation
engineer. Design an end-to-end project for: {{PROJECT_TYPE}}.

Problem and users: {{PROBLEM_AND_USERS}}
Core workflows: {{WORKFLOWS}}
Scale and operating model: {{SCALE_AND_TEAM}}
Integrations: {{INTEGRATIONS}}
Constraints and exclusions: {{CONSTRAINTS}}
Success criteria: {{SUCCESS_CRITERIA}}

Produce:
1. Product requirements, user stories, acceptance criteria, and non-goals.
2. Domain concepts and data contracts.
3. Current/target architecture and key decisions with alternatives.
4. Repository structure appropriate to the scale and team.
5. Configuration, secrets, error handling, privacy, and security approach.
6. Test strategy and measurable quality gates.
7. Phased roadmap, dependencies, and prioritized backlog.
8. Risks, mitigations, migration/rollout strategy, and future evolution.

Use concrete examples and identify assumptions. Distinguish MVP from later
capabilities. Prefer the least complex architecture that meets stated
requirements. Do not add infrastructure merely because the prompt says
"production-ready"; justify each operational component. Do not write code
unless asked.
```

#### Content Creation Platform

**Use when:** Designing this repository's broader product direction.

```text
Design an end-to-end Content Creation Platform that accepts source material
and creates reviewable content for multiple brands, editorial profiles,
formats, and social platforms.

Must keep distinct: Source, Brand, ContentProfile, Format, Platform, generated
content item, and platform-specific content variant.
Initial workflow: {{CURRENT_WORKFLOW}}
Human approval: {{APPROVAL_POLICY}}
Team/scale: {{TEAM_AND_SCALE}}
Constraints: {{CONSTRAINTS}}

Generate requirements, architecture, domain contracts, configuration
hierarchy, prompt strategy, project structure, test plan, phased roadmap,
prioritized backlog, migration risks, and future evolution. Keep each capability
at the correct boundary. Separate implemented/current capabilities from
proposed capabilities. Do not assume a particular database, API, scheduler, or
publisher; justify each against requirements.
```

#### Instagram Automation Platform

**Use when:** Planning an Instagram-specific product while keeping editorial
configuration reusable.

```text
Design an Instagram content automation platform for {{USER_AND_BRAND}}.

Content formats and workflow: {{FORMATS_AND_WORKFLOW}}
Required human review: {{REVIEW_POLICY}}
Instagram account/API constraints known: {{KNOWN_CONSTRAINTS}}
Operating environment: {{ENVIRONMENT}}

Produce requirements, content lifecycle, account/permission assumptions,
format validation, media preparation, failure handling, test strategy,
roadmap, backlog, and risks. Keep Instagram-only behavior in the platform
adapter/configuration, not in editorial profiles. Explicitly identify
requirements that need verification against current Instagram policies or API
documentation. Do not claim publishing is possible without confirming account
eligibility and permissions.
```

#### AI Agent Platform

**Use when:** Designing reusable agent execution capabilities.

```text
Design an AI Agent Platform for {{USERS_AND_TASKS}}.

Agent capabilities required: {{CAPABILITIES}}
Tools and trust boundaries: {{TOOLS_AND_BOUNDARIES}}
Human oversight: {{OVERSIGHT}}
Scale, privacy, and cost constraints: {{CONSTRAINTS}}

Produce requirements, agent/tool contracts, state and execution model,
configuration/prompt strategy, observability, evaluation, safety controls,
project structure, roadmap, backlog, risks, and future evolution. Compare a
single deterministic pipeline with general agent orchestration. Recommend
orchestration only where evidence supports it.
```

#### SaaS Platform

**Use when:** Designing a multi-user hosted product with explicit tenancy and
operational needs.

```text
Design a SaaS platform for {{PRODUCT_AND_CUSTOMERS}}.

Tenancy and roles: {{TENANCY_AND_ROLES}}
Workflows and data sensitivity: {{WORKFLOWS_AND_DATA}}
Availability/compliance requirements: {{REQUIREMENTS}}
Team and delivery constraints: {{CONSTRAINTS}}

Produce requirements, tenant/data isolation model, architecture alternatives,
security and privacy requirements, deployment/operations plan, test strategy,
project structure, migration/rollout plan, roadmap, backlog, risks, and future
evolution. Justify every infrastructure component and identify launch
non-goals. Do not confuse a single-user local MVP with a SaaS requirement.
```

#### Internal Productivity Tool

**Use when:** Building a lightweight tool for a known internal workflow.

```text
Design an internal productivity tool for {{TEAM_AND_WORKFLOW}}.

Current process and pain points: {{CURRENT_PROCESS}}
Users and access: {{USERS}}
Data and integrations: {{DATA_AND_INTEGRATIONS}}
Operating constraints: {{CONSTRAINTS}}

Produce requirements, workflow and data model, simplest maintainable
architecture, project structure, permission/privacy considerations, test plan,
rollout strategy, prioritized backlog, risks, and future evolution. Prefer
existing organization tools and a small deployment footprint. Identify what
should remain manual.
```

---

## 4. Refactoring Prompts

### Convert MVP to Scalable Architecture

**Use when:** An MVP has validated behavior and a concrete next scale target.

```text
Refactor {{MVP_OR_REPOSITORY}} to support {{CONCRETE_NEXT_CAPABILITIES}}.

Preserve: {{BEHAVIOR_AND_DATA_TO_PRESERVE}}
Constraints: {{TEAM_RUNTIME_BUDGET}}
Current evidence of limits: {{MEASURED_OR_OBSERVED_LIMITS}}

First identify the smallest architectural seams needed. Map each current
responsibility to a target module and define compatibility tests. Prioritize
data contracts, ownership, configuration, and integration boundaries before
infrastructure.

Return current-to-target mapping, phased file-level changes, breaking
changes, migration/rollback plan, risks, and acceptance tests. Do not perform
a speculative rewrite. Keep the existing user workflow operational at each
phase.
```

### Remove Technical Debt

**Use when:** Addressing a defined set of high-cost debt without broad cleanup.

```text
Reduce the verified technical debt in {{SCOPE}}.

Debt findings and evidence: {{FINDINGS}}
Behavior that must remain unchanged: {{INVARIANTS}}
Constraints: {{CONSTRAINTS}}

Rank fixes by risk reduction and delivery leverage. For each, specify minimal
files, dependencies, tests, data implications, and rollback concerns. Implement
only in-scope items, preserve unrelated work, and avoid formatting or
renaming unrelated code. Report any finding that cannot be safely addressed
without a product decision.
```

### Introduce Configuration Layer

**Use when:** Moving hardcoded policy into validated configuration.

```text
Introduce configuration for {{POLICIES_OR_SETTINGS}} in {{REPOSITORY}}.

Existing hardcoded behavior: {{CURRENT_VALUES_AND_LOCATIONS}}
Required defaults: {{DEFAULTS}}
Selection/override rules: {{RULES}}
Backward compatibility: {{COMPATIBILITY}}

Design the smallest declarative schema, loader, validation, and error
behavior. Keep secrets separate. Preserve existing defaults exactly unless
explicitly instructed otherwise. Add tests for defaults, invalid config,
unknown IDs, path safety, and old records/callers. Provide a file-by-file plan
before editing if multiple modules or data contracts are affected.
```

### Introduce Domain Models

**Use when:** Multiple modules need a stable shared data contract.

```text
Introduce typed domain models for {{CONCEPTS}} into {{REPOSITORY}}.

Current representations: {{CURRENT_DATA_SHAPES}}
Required workflows: {{WORKFLOWS}}
Legacy data and callers: {{COMPATIBILITY}}

Define required/optional fields, validation, IDs, serialization, versioning,
and invalid-state handling. Keep models focused on shared concepts; do not add
fields for hypothetical use. Provide conversion from legacy data and tests
for valid, invalid, and legacy examples. Preserve existing behavior during
adoption.
```

### Modular Monolith Refactoring

**Use when:** A growing single-process application needs clearer module
ownership without separate services.

```text
Refactor {{APPLICATION}} into a modular monolith while retaining one
deployable/runtime unit.

Current modules and pain points: {{CURRENT_STRUCTURE}}
Likely change boundaries: {{BOUNDARIES}}
Constraints: {{CONSTRAINTS}}

Define module responsibilities, public interfaces, allowed dependencies, and
shared contracts. Propose incremental moves with compatibility shims where
needed. Keep transaction and process boundaries simple. Do not create empty
layers or split deployables. Include import-boundary tests and a staged
migration plan.
```

### Migration Planning

**Use when:** Changing schemas, storage, configuration, or workflow contracts.

```text
Plan migration from {{CURRENT_STATE}} to {{TARGET_STATE}}.

Data/artifacts involved: {{DATA}}
Consumers and commands: {{CONSUMERS}}
Downtime/rollback limits: {{LIMITS}}
Compatibility period: {{COMPATIBILITY_WINDOW}}

Inventory files and data shapes. Specify backup, transformation, validation,
dual-read/write policy if needed, cutover, rollback, and cleanup criteria.
Never assume data can be recreated. Provide measurable reconciliation checks,
failure handling, operator instructions, and tests using representative
fixtures. Call out irreversible actions explicitly.
```

---

## 5. Developer Review Prompts

### Full Repository Review

**Use when:** Producing a product/architecture/codebase assessment and next
steps.

```text
Act as a principal software architect, senior engineer, product reviewer, and
pragmatic technical reviewer.

Review the entire repository {{REPOSITORY}} as a product and system, not as
isolated snippets.

Product/current workflow: {{PRODUCT_AND_WORKFLOW}}
Target direction: {{TARGET}}
Team and constraints: {{CONSTRAINTS}}

Inspect implementation, tests, configuration, docs, and representative data.
Assess repository structure, architecture, AI workflow, correctness,
maintainability, reliability, data safety, extensibility, and documentation
consistency. Distinguish facts, inferences, and recommendations.

Generate:
- Executive Summary
- Architecture Score (1-10) with evidence
- Code Quality Score (1-10) with evidence
- Product Readiness Score (1-10) with evidence
- Top Improvements ordered by impact
- High/medium/low risks with file evidence
- Things That Should NOT Be Changed
- Recommended Next 3 Development Steps
- Recommended Files to Add, Modify, or Retire
- Detailed phased refactoring plan

Optimize for {{OPTIMIZATION_GOALS}}. Do not suggest infrastructure or
architectural patterns without a concrete requirement. Do not modify files.
```

### PR Review

**Use when:** Reviewing a proposed change for correctness, regression, and
scope.

```text
Review the changes in {{DIFF_OR_PR}} against the base branch and these
requirements: {{REQUIREMENTS}}.

Prioritize actionable bugs, data loss, security/privacy issues, behavior
regressions, broken compatibility, and missing critical tests. Trace affected
callers and workflows. Ignore trivial style issues unless they hide a defect.

For each finding include severity, exact file/line, reproducible scenario,
impact, and concise remedy. Report only findings introduced by this change;
label pre-existing risks separately. If no findings, state that and note
validation limits. Do not modify code.
```

### File Review

**Use when:** Reviewing one file in the context of its callers and purpose.

```text
Review {{FILE_PATH}} for correctness, readability, error handling, and fit
with its responsibility.

Purpose: {{PURPOSE}}
Callers/consumers: {{CALLERS}}
Required behavior: {{INVARIANTS}}

Read enough adjacent code to understand contracts. Identify concrete defects
and maintainability risks with line references. Recommend minimal changes,
not a redesign. Check boundary validation, resource/file handling, and tests.
Do not modify the file.
```

### Python Code Review

**Use when:** Reviewing Python implementation details and runtime behavior.

```text
Review {{PYTHON_SCOPE}} as a senior Python engineer.

Runtime/version: {{PYTHON_VERSION}}
Expected behavior: {{BEHAVIOR}}
Relevant tests: {{TESTS}}

Check types and data validation, exceptions, resource management, path
handling, JSON/config parsing, dependency use, import behavior, testability,
and compatibility. Trace error paths and identify silent failure or
success-shaped fallback. Avoid style-only comments and speculative
abstractions.

Return prioritized findings with file/line, scenario, impact, fix, and test.
Do not change code.
```

### Documentation Review

**Use when:** Checking whether user and engineering documentation is accurate,
consistent, and usable.

```text
Review {{DOCUMENTS}} against the current implementation in {{REPOSITORY}}.

Audience: {{AUDIENCE}}
Intended product direction: {{DIRECTION}}

Check factual accuracy, current-vs-future distinctions, terminology,
cross-document consistency, setup instructions, examples, broken references,
and missing operational caveats. Identify contradictions with source evidence.
Recommend exact edits and priority. Do not claim unimplemented capabilities
are available. Do not modify files unless explicitly asked.
```

---

## 6. Prompt Engineering Prompts

### Improve a System Prompt

**Use when:** A prompt produces inconsistent, verbose, unsafe, or poorly
structured outputs.

```text
Improve the following system prompt for {{TASK}}.

Current prompt:
{{PROMPT}}

Observed failures: {{FAILURES}}
Required behavior and output schema: {{REQUIREMENTS}}
Safety/authority boundaries: {{BOUNDARIES}}

Identify ambiguity, conflicting instructions, missing constraints, and
unnecessary wording. Produce a revised prompt and explain material changes.
Include at least three adversarial/edge test inputs and the expected behavior.
Do not claim prompt instructions replace code validation.
```

### Convert Hardcoded Behavior into Configuration

**Use when:** Removing category-, brand-, or platform-specific constants from
shared code.

```text
Find the hardcoded behavior in {{SCOPE}} that should vary by {{DIMENSION}}.

Examples and desired variants: {{EXAMPLES}}
Behavior that must remain shared: {{SHARED_RULES}}
Compatibility constraints: {{CONSTRAINTS}}

Classify each value as policy, content data, format requirement, platform
constraint, secret, or true invariant. Propose a small validated config
schema, safe defaults, and explicit precedence. Show how current defaults map
without behavior drift. Add tests proving a new variant needs no shared-code
branch. Avoid turning arbitrary control flow into unvalidated configuration.
```

### Build a Profile-Driven System

**Use when:** Supporting multiple editorial profiles without niche-specific
branches.

```text
Design/implement profile-driven behavior for {{SYSTEM}}.

Profiles required: {{PROFILE_EXAMPLES}}
Shared pipeline behavior: {{SHARED_BEHAVIOR}}
Profile-specific differences: {{DIFFERENCES}}
Existing records and default behavior: {{COMPATIBILITY}}

Keep ContentProfile distinct from Brand, Format, and Platform. Define the
profile schema, validation, prompt inputs, selection, provenance, and legacy
fallback. Demonstrate that adding a profile requires configuration/prompt
assets and tests, not a conditional in shared generation code. Preserve
existing default behavior.
```

### Create Reusable Prompt Templates

**Use when:** Extracting prompt text into maintainable, tested assets.

```text
Create a reusable prompt template for {{TASK}}.

Inputs: {{INPUTS}}
Output contract: {{OUTPUT}}
Shared instructions: {{SHARED_RULES}}
Variable context: {{VARIABLE_CONTEXT}}

Separate stable instructions from runtime data. List every variable, type,
required/optional status, escaping rule, and fallback behavior. Ensure
untrusted source content cannot be confused with system instructions. Provide
one rendered example and tests for missing values, special characters, and
empty optional sections. Keep validation in application code.
```

---

## 7. Sprint Planning Prompts

### Sprint Planning

**Use when:** Turning a goal into a bounded, dependency-aware sprint.

```text
Plan a sprint to achieve {{SPRINT_GOAL}}.

Available capacity: {{CAPACITY}}
Current system/repository: {{CURRENT_STATE}}
Constraints/non-goals: {{CONSTRAINTS}}
Definition of success: {{SUCCESS}}

Break work into independently verifiable tasks. For each provide objective,
deliverables, affected files, estimate, dependencies, acceptance criteria,
risks, and out-of-scope items. Order tasks by real dependencies. Include a
small vertical slice and a fallback scope if capacity is exceeded. Do not
include speculative infrastructure.
```

### Prioritization

**Use when:** Ranking candidate work against product value and delivery cost.

```text
Prioritize these candidate changes: {{CANDIDATES}}.

Product goal: {{GOAL}}
Users and pain: {{USER_IMPACT}}
Dependencies and constraints: {{CONSTRAINTS}}

Rank by user impact, risk reduction, architectural leverage, time-to-value,
and effort. State assumptions and explain tradeoffs. Identify prerequisites,
quick wins, high-risk investments, and work that should wait. Do not treat
"future-ready" as value unless it unlocks a named capability.
```

### ROI Analysis

**Use when:** Comparing changes with different effort and strategic leverage.

```text
Estimate the relative ROI of {{OPTIONS}} for {{PRODUCT_GOAL}}.

For each option estimate effort range, expected benefit, time-to-benefit,
maintenance cost, risk reduced, dependencies, and confidence. Use a transparent
scoring method and avoid false precision. Include the impact of doing nothing
and identify the smallest experiment that could validate uncertain benefit.
Recommend a sequence, not only a score.
```

### Dependency Analysis

**Use when:** Checking whether a task order is technically valid.

```text
Analyze dependencies among {{TASKS}} for {{TARGET_OUTCOME}}.

For each dependency, distinguish hard prerequisite, useful ordering, and
independent work. Identify contract decisions, migration risks, parallelizable
tasks, critical path, and tasks that can be removed or deferred. Return a
dependency graph in text and the recommended execution order. Do not infer
dependencies merely from the current list order.
```

### Architecture Planning

**Use when:** Planning architecture work that should be implemented
incrementally.

```text
Plan architecture changes for {{CAPABILITY}} in {{CURRENT_SYSTEM}}.

Target users/workload: {{TARGET}}
Existing behavior/data to preserve: {{INVARIANTS}}
Constraints: {{CONSTRAINTS}}

Describe the smallest target boundary, contracts, configuration and data
ownership, failure behavior, and migration sequence. Compare options only
where a decision matters. Include implementation tasks, test gates, rollback
plan, and deferred decisions. Optimize for future leverage without imposing
complexity before demand.
```

---

## 8. Debugging Prompts

### Root Cause Analysis

**Use when:** A symptom has multiple plausible causes and you need a verified
diagnosis.

```text
Investigate this issue in {{REPOSITORY}}:

Symptom: {{SYMPTOM}}
Reproduction: {{REPRO_STEPS}}
Expected vs actual: {{EXPECTED_ACTUAL}}
Logs/errors/environment: {{EVIDENCE}}

Trace the execution path and identify the earliest point where actual
behavior diverges. Separate confirmed facts from hypotheses. Propose
discriminating tests or observations before recommending a fix. Consider
configuration, persisted state, dependencies, and environment. Do not modify
unrelated code.

Return root cause, evidence, minimal fix, regression test, and remaining
uncertainty.
```

### Error Investigation

**Use when:** Diagnosing a stack trace or runtime failure.

```text
Diagnose this error using the code and environment evidence provided.

Error/stack trace:
{{ERROR}}

Command and context:
{{COMMAND_CONTEXT}}

Relevant files/config:
{{FILES_CONFIG}}

Explain the failing operation, likely root cause, and how to verify it.
Distinguish an application defect from missing dependency, invalid
configuration, external-service failure, or environment mismatch. Give
minimal corrective steps and a regression check. Do not guess hidden
environment values.
```

### VS Code Troubleshooting

**Use when:** Diagnosing an editor, interpreter, test discovery, or extension
problem.

```text
Troubleshoot this VS Code issue: {{ISSUE}}.

OS: {{OS}}
Workspace and repo: {{WORKSPACE}}
Selected interpreter/tool versions: {{VERSIONS}}
Expected vs actual behavior: {{EXPECTED_ACTUAL}}
Relevant settings/logs: {{EVIDENCE}}

Separate workspace configuration from user settings and extension behavior.
Give low-risk diagnostic steps in order, explain what each result means, and
avoid destructive cleanup or resetting unrelated settings. Ask for missing
evidence only if it blocks a safe diagnosis.
```

### Dependency Troubleshooting

**Use when:** Diagnosing installation, import, version, or environment errors.

```text
Investigate dependency failure {{ERROR}} for {{PROJECT}}.

Python/runtime: {{RUNTIME}}
Package manager and environment: {{ENVIRONMENT}}
Manifest/lock files: {{MANIFESTS}}
Install/import commands: {{COMMANDS}}

Determine whether the cause is an inactive environment, missing declaration,
version conflict, platform wheel, or network/index issue. Recommend the
smallest reproducible fix. Do not upgrade unrelated dependencies. If a
manifest change is needed, state why and identify compatibility tests.
```

### Integration Troubleshooting

**Use when:** Investigating a model, file, platform, or other external
integration.

```text
Troubleshoot the integration between {{APPLICATION}} and {{SERVICE}}.

Operation: {{OPERATION}}
Request/response evidence with secrets redacted: {{EVIDENCE}}
Configuration and versions: {{CONFIG_VERSIONS}}
Expected vs actual: {{EXPECTED_ACTUAL}}

Trace request construction, transport, status handling, response parsing,
timeouts, and downstream state changes. Identify the exact failing boundary.
Never request or expose secrets. Recommend safe diagnostics, explicit error
handling, and a mocked regression test. Do not retry destructive operations
without checking idempotency.
```

---

## 9. Content Creation Platform Prompts

### Create a Content Profile

**Use when:** Adding an editorial niche such as Comedy, Finance, or Career.

```text
Create a ContentProfile configuration for {{PROFILE_NAME}}.

Audience: {{AUDIENCE}}
Objectives: {{OBJECTIVES}}
Voice traits: {{VOICE_TRAITS}}
Avoid: {{AVOID}}
Topics or boundaries: {{TOPICS_AND_BOUNDARIES}}
Language: {{LANGUAGE}}

Return valid YAML matching this schema:
id, display_name, language, audience.description, objectives[], voice.traits[],
voice.avoid[], topics[].

Keep editorial guidance concrete and testable. Do not include brand identity,
platform limits, format structure, secrets, or unsupported factual claims.
Include two short example directions and note any ambiguity needing owner
approval.
```

### Create a Brand

**Use when:** Defining publisher identity and defaults independently of niche.

```text
Create a Brand configuration for {{BRAND_NAME}}.

Brand promise/audience: {{BRAND_CONTEXT}}
Voice traits and exclusions: {{VOICE}}
Default profile, format, and platform: {{DEFAULTS}}
Visual identity: {{VISUAL_IDENTITY}}
Constraints: {{CONSTRAINTS}}

Return valid YAML matching the project's Brand schema. Keep account
credentials out of the file; use secret references only if supported by the
implementation. Do not duplicate profile objectives or platform hard limits.
Explain how the brand can use multiple profiles and where brand/profile
guidance may conflict.
```

### Create a Format

**Use when:** Defining an output structure such as a Reel, carousel, or text
post.

```text
Create a Format configuration for {{FORMAT_NAME}}.

Intended use: {{USE}}
Required content fields and order: {{FIELDS}}
Length/timing/media needs: {{REQUIREMENTS}}
Supported platforms: {{PLATFORMS}}

Return valid YAML matching the project's Format schema. Define format
structure and technical production requirements only. Do not add editorial
niche rules or claim platform acceptance. Identify what must be validated in
code rather than trusted to the model.
```

### Create a Platform

**Use when:** Recording destination capabilities and constraints.

```text
Create a Platform configuration for {{PLATFORM_NAME}} based on these
verified requirements: {{VERIFIED_REQUIREMENTS}}.

Supported formats: {{FORMATS}}
Media/copy limits: {{LIMITS}}
Known account/API assumptions: {{ASSUMPTIONS}}

Return valid YAML matching the project's Platform schema. Separate verified
facts from assumptions and include a source/date for externally changeable
limits. Do not place editorial voice or brand rules here. Do not invent
publishing capability or credentials.
```

### Review Generated Content

**Use when:** Reviewing a draft for profile fit, clarity, correctness, and
publication readiness.

```text
Review this generated content as an editor. Do not rewrite it unless asked.

Brand: {{BRAND}}
Content profile: {{PROFILE}}
Format: {{FORMAT}}
Platform constraints: {{PLATFORM_CONSTRAINTS}}
Source material: {{SOURCE}}
Draft:
{{DRAFT}}

Assess:
- Fit with brand and profile voice
- Hook, clarity, structure, originality, and audience relevance
- Factual claims and whether they are supported by the source
- Harmful, misleading, sensitive, or legally risky wording
- Format completeness and platform constraints

Return: approve/revise/reject recommendation, blocking issues, non-blocking
improvements, confidence, and a minimally edited version only if requested.
Never invent citations or imply fact-checking was performed without sources.
```

### Generate Scene Prompts

**Use when:** Converting a reviewed script into a visual storyboard.

```text
Create scene descriptions for the following content.

Brand visual direction: {{BRAND_VISUAL_DIRECTION}}
Content profile direction: {{PROFILE_VISUAL_DIRECTION}}
Format requirements: {{FORMAT_REQUIREMENTS}}
Platform constraints: {{PLATFORM_CONSTRAINTS}}
Script and hook:
{{SCRIPT}}

Preserve the narration's meaning and order. Divide into scenes based on
semantic beats, not arbitrary sentence length. For each scene return scene
number, associated narration, visual description, subject/action, setting,
composition, and continuity notes. Avoid adding text inside generated images
unless explicitly requested. Flag any imagery that could misrepresent factual
content.
```

### Generate Video Prompts

**Use when:** Assembling a video-generation brief from approved content and
visual prompts.

```text
Create a video-generation prompt for the approved content below.

Brand: {{BRAND}}
Content profile: {{PROFILE}}
Format: {{FORMAT_AND_DURATION}}
Platform: {{PLATFORM_AND_LIMITS}}
Voiceover/script: {{VOICEOVER}}
Storyboard/image prompts: {{STORYBOARD}}
Audio/subtitle requirements: {{AUDIO_SUBTITLES}}

Keep platform and format limits separate from creative direction. Preserve
the approved message; do not add claims or dialogue. Specify aspect ratio,
duration, visual continuity, transitions, voiceover timing, subtitles, and
audio only where provided by configuration. Return a production-ready prompt
and a checklist of unresolved inputs. Do not state that a video was rendered.
```

---

## 10. Personal Favorites

### My High-Value Prompts

These prompts are the recommended starting points for recurring engineering
work. Use them with concrete repository context and ask for evidence before
acting on conclusions.

#### 1. Repository Review

**Use when:** Beginning a project, returning after a pause, or choosing the
next investment.

```text
Review {{REPOSITORY}} as a product, architecture, and codebase. Inspect source,
tests, docs, configuration, and representative data. Compare actual behavior
with documented claims.

Product today: {{CURRENT_PRODUCT}}
Target: {{TARGET}}
Constraints: {{CONSTRAINTS}}

Return an executive summary; architecture/code-quality/product-readiness
scores with evidence; top risks and improvements; what not to change; next
three steps; and file-level recommendations. Separate facts from assumptions.
Optimize for shipping value and long-term maintainability. Do not modify files
or recommend infrastructure without a demonstrated need.
```

#### 2. Architecture Planning

**Use when:** A feature crosses modules or establishes a contract that future
work will depend on.

```text
Plan the smallest durable architecture for {{CAPABILITY}} in {{REPOSITORY}}.

Current behavior/data to preserve: {{INVARIANTS}}
Future use cases: {{USE_CASES}}
Constraints: {{CONSTRAINTS}}

Identify domain concepts, contracts, boundaries, configuration, ownership,
error paths, and migration sequence. Compare alternatives only for material
decisions. Return a current-to-target diagram, exact file-level steps,
acceptance tests, risks, and deferred decisions. Do not over-abstract or add
infrastructure without a concrete need.
```

#### 3. Refactoring

**Use when:** Improving a known area while minimizing unrelated churn.

```text
Refactor {{SCOPE}} to address {{VERIFIED_PROBLEM}}.

Required behavior to preserve: {{INVARIANTS}}
Out of scope: {{OUT_OF_SCOPE}}
Tests/fixtures: {{TESTS}}

Before editing, provide the exact files to create/modify/retire, migration
approach, and risks. Then make the smallest complete change, preserve unrelated
work, add targeted tests, run the narrowest relevant validation, and report
what changed and what remains unverified. Do not silently change user data or
public behavior.
```

#### 4. Sprint Planning

**Use when:** Turning strategic work into a deliverable sequence.

```text
Create a practical sprint plan for {{GOAL}} with {{CAPACITY}} capacity.

Current state: {{CURRENT_STATE}}
Non-goals/constraints: {{CONSTRAINTS}}
Success criteria: {{SUCCESS}}

List tasks in dependency order. For each include objective, files, effort,
dependencies, acceptance criteria, and risk. Rank by ROI and identify a
minimum releasable slice and scope-cut order. Keep architecture leverage
without building speculative subsystems.
```

#### 5. Implementation Planning

**Use when:** Preparing to make a bounded code change before implementation.

```text
Plan implementation of {{CHANGE}} in {{REPOSITORY}}.

Requirements: {{REQUIREMENTS}}
Behavior to preserve: {{COMPATIBILITY}}
Explicitly forbidden changes: {{FORBIDDEN}}
Validation expectations: {{TESTS_AND_CHECKS}}

Inspect the relevant code first. Return exact files to create/modify, design
and data flow, migration/compatibility approach, risks, and a small test plan.
Call out ambiguities that require a decision. Do not write code until the plan
is approved. Keep the proposal limited to the requested scope.
```

---

## Maintenance notes

- Add prompts only when a workflow recurs or benefits from a stable checklist.
- Give each prompt a clear use case, required inputs, expected output, and
  safety/compatibility constraints.
- Prefer updating an existing prompt over maintaining near-duplicates.
- When prompts drive production behavior, assign stable IDs/versions in the
  runtime prompt registry and test rendered outputs separately from this
  human-facing library.
- Review this library when domain terminology or project constraints change.
