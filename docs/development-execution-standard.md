# Development Execution Standard

Reusable execution rules for implementation work across projects.

This document defines **how development work is executed**, not product-specific business rules. It is intentionally generic so it can be copied into other repositories and used by human engineers or coding agents.

---

## 1. Core principle

> **A card is an audit/commit boundary, not a conversation boundary.**

Do not stop after every implementation card just to ask whether to continue.

Group related cards into an **execution wave** that produces one meaningful end-to-end capability. Keep commits small and auditable inside the wave, but checkpoint and report mainly at the wave boundary.

The goal is to optimize for:

- correct end-to-end outcomes;
- fast execution with low coordination overhead;
- small, reviewable and revertible commits;
- source-of-truth correctness;
- regression safety;
- truthful validation reporting.

Do not optimize for the number of commits, number of status updates, or number of documents produced.

---

## 2. Planning hierarchy

Use four levels of work decomposition.

### 2.1 Product outcome

The real user/business capability that must work end to end.

Examples:

- Talent submits an attendance correction and PMO can review it.
- Operator configures a device and the setting reaches the edge safely.
- User uploads evidence and can later audit its processing state.

### 2.2 Execution wave

A group of related cards that closes one meaningful vertical slice.

A wave should normally contain multiple cards when they share the same flow, dependencies and validation context.

Examples:

```text
Review Queue API
  -> Review Queue UI
  -> Bulk decision service
  -> Approve/reject UX
  -> Regression pass
  -> Wave checkpoint
```

### 2.3 Card

A logical implementation boundary with one clear responsibility.

Cards remain useful for:

- scope control;
- commit boundaries;
- code review;
- rollback;
- targeted tests;
- dependency tracking.

Cards are **not** an automatic reason to pause execution.

### 2.4 Commit

The smallest reviewable code/document change that leaves the branch coherent.

A card may contain multiple commits when this improves safety or reviewability.

---

## 3. Default wave execution flow

For a normal multi-card wave:

1. **Verify repository state once at wave start.**
   - correct repository;
   - correct branch;
   - expected HEAD/checkpoint;
   - inspect parallel changes before writing.

2. **Read only the context needed for this wave.**
   - canonical architecture/business rules;
   - relevant source-of-truth services;
   - existing tests/contracts;
   - previous checkpoint.

3. **Map card dependencies before coding.**
   - identify authority/service to reuse;
   - identify API/UI/runtime sequence;
   - identify regression surfaces;
   - identify what is explicitly out of scope.

4. **Implement cards continuously.**
   - do not pause for approval between cards unless a material product/architecture decision is discovered;
   - keep each card/commit narrow;
   - reuse existing authorities instead of creating duplicate state or business logic.

5. **Validate incrementally.**
   - add focused tests with the behavior they protect;
   - run/inspect relevant regression surfaces during the wave;
   - do not wait until the end to discover fundamental integration problems.

6. **Perform one wave-level integration review.**
   - trace the full user/system flow;
   - check error/recovery paths;
   - compare changed files against the wave scope;
   - verify no unrelated redesign slipped in.

7. **Checkpoint once at the end of the wave.**
   - summarize delivered capability;
   - record relevant commits/files;
   - state validation actually performed;
   - state known limitations;
   - point to the next wave.

---

## 4. When to stop inside a wave

Do **not** stop merely because a card finished.

Stop and surface the issue only when continuing would risk implementing the wrong product or corrupting state, for example:

- a canonical business rule conflicts with the planned card;
- source-of-truth ownership is ambiguous;
- a required external credential/resource is unavailable and no safe local boundary can continue;
- a parallel change materially conflicts with the same code path;
- schema/API compatibility would require a breaking change not already approved;
- a safety/security/data-integrity invariant would be weakened;
- the discovered implementation is substantially different from the approved architecture.

Minor implementation choices, naming, helper placement, local refactors and test structure should be resolved without interrupting the wave.

---

## 5. Source-of-truth rules

Before adding state or business logic, identify the existing authority.

Default rules:

- never create a second lifecycle when an existing lifecycle can be extended;
- never make UI state the business authority;
- never infer approval/readiness from evidence alone;
- never overwrite immutable/raw source facts to simulate a correction;
- never duplicate canonical identity, schedule, configuration or approval state in convenience JSON unless explicitly required as a snapshot/reference;
- derived/projection state must be recomputable from canonical facts;
- durable snapshots may preserve interpretation/order/context, but must not silently become a second source of current truth.

When state may change between prompt and mutation, **revalidate immediately before mutation**.

---

## 6. Mutation safety

Every mutation path should answer these questions:

1. **Who owns this object/action?**
2. **What exact stable identity is being mutated?**
3. **What is the current authoritative source state?**
4. **Has anything changed since the user first saw the data?**
5. **Is this mutation idempotent or safely retryable?**
6. **What happens on partial failure?**
7. **What wording can truthfully be shown after the operation?**

Prefer explicit states such as:

```text
DRAFT -> SUBMITTED -> APPROVED / REJECTED
```

over inferred booleans such as `ready=true` when readiness depends on multiple facts.

---

## 7. Commit discipline

Commits should be small enough to review and revert independently, but not artificially fragmented.

Good boundaries include:

- schema/migration;
- domain/service behavior;
- API contract;
- UI wiring;
- focused tests;
- corrective hardening;
- wave checkpoint documentation.

Avoid:

- unrelated cleanup in feature commits;
- mass formatting mixed with behavior changes;
- speculative abstractions;
- renaming large surfaces without functional need;
- one huge wave commit that hides logical boundaries.

A wave may contain many commits. The user does not need a separate conversation turn for each commit.

---

## 8. Parallel-change handling

Before the first write in a wave, verify HEAD.

If a write is rejected because the target file changed:

1. fetch the latest version;
2. inspect the parallel changes;
3. merge only the intended wave changes onto the new version;
4. never overwrite blindly;
5. mention the conflict only if it materially affects behavior/scope.

Do not restart the entire audit when an unrelated file changes.

---

## 9. Testing strategy

Testing should follow the risk, not the card count.

### 9.1 During implementation

Add focused tests for:

- business invariants;
- routing/precedence;
- ownership validation;
- stale-state handling;
- idempotency;
- regression behavior of existing flows;
- expected error/recovery paths.

### 9.2 At wave boundary

Trace at least one end-to-end scenario across all cards in the wave.

Example:

```text
API fact
 -> UI/action
 -> service mutation
 -> projection refresh
 -> next user-visible state
```

### 9.3 Full CI

Run the repository's full quality gate when available.

If the execution environment cannot run the full gate:

- do not claim it passed;
- report the targeted validation that actually ran;
- state the remaining PR/main/staging CI gate explicitly.

Never convert "tests were added" into "tests passed" unless they actually ran successfully.

---

## 10. Documentation standard

Documentation should reduce future execution cost.

Use three layers only when needed:

### Canonical plan

Stable product/architecture/business rules. Avoid rewriting this after every small commit.

### Rolling checkpoint

Current execution pointer:

- completed wave;
- relevant HEAD;
- delivered contract;
- validation notes;
- next wave.

Update this **at wave boundaries**, not after every card by default.

### Reusable execution standard

This file. It describes how implementation work should be executed across projects.

Do not create documentation merely to mirror every commit.

---

## 11. User communication standard

For substantial work, communicate by meaningful milestones rather than low-level operations.

During a wave:

- send short updates when there is a meaningful finding, design constraint, conflict, or partial capability worth showing;
- do not narrate every file read/write;
- do not ask "continue?" after every card;
- do not repeat the same plan in every update.

At wave completion, report:

1. what is now usable end to end;
2. important safeguards/constraints;
3. meaningful commits/checkpoint;
4. validation status and limitations;
5. next wave.

---

## 12. Efficiency rules

To keep execution fast without losing correctness:

- verify HEAD once per wave, then re-check only after conflicts or at the end;
- audit only changed/relevant surfaces, not the whole repository repeatedly;
- batch related reads/searches;
- reuse existing factories/services/contracts;
- keep helper abstractions local unless they are genuinely reusable;
- avoid migrations when existing durable fields already satisfy the requirement;
- do not redesign unrelated UI/architecture while implementing a vertical slice;
- checkpoint docs once per wave;
- combine closely coupled API + UI + service work in the same wave while preserving separate commits;
- prefer an end-to-end usable slice over many disconnected "completed" cards.

---

## 13. Correctness rules that efficiency must never override

Speed must not weaken:

- authorization and identity ownership;
- immutable/raw source data;
- source-of-truth boundaries;
- validation before mutation;
- auditability;
- idempotency/retry safety;
- backward compatibility unless explicitly changed;
- truthful user-facing status;
- data migration safety;
- error and partial-failure handling;
- production safety gates.

If making the implementation faster requires sacrificing one of these, choose correctness.

---

## 14. Recommended wave sizing

A wave should normally be large enough to produce a real capability but small enough to reason about and review.

Typical target:

- **2–6 implementation cards**;
- one coherent vertical flow;
- one main source-of-truth domain;
- one wave-level regression pass;
- one checkpoint.

Split a wave when:

- it crosses unrelated product domains;
- it introduces a major new infrastructure dependency;
- it mixes risky migrations with unrelated UI work;
- it becomes impossible to describe the end-to-end acceptance condition clearly.

Merge cards into the same wave when they cannot provide useful value independently, such as API + UI + action wiring for one operational workflow.

---

## 15. Definition of done for a wave

A wave is `DONE` only when:

- the intended vertical capability is implemented across all required layers;
- source-of-truth and ownership boundaries are preserved;
- focused regression coverage exists for the important invariants;
- known stale/error/partial-failure cases have defined behavior;
- changed files match the intended scope;
- documentation/checkpoint reflects the actual result;
- validation claims are truthful;
- the next wave can start without rediscovering the completed architecture.

A wave is **not** done merely because all planned files were edited.

---

## 16. Reusable execution template

Use this at the start of another project.

```text
Outcome:
  <end-to-end capability>

Wave:
  <wave name>

Cards:
  C01 <boundary>
  C02 <boundary>
  C03 <boundary>

Canonical authorities to reuse:
  - <service/table/API>

Must preserve:
  - <invariant>
  - <backward compatibility>

Out of scope:
  - <explicitly excluded work>

Validation:
  - focused unit/integration tests
  - regression surfaces
  - full CI/staging gate when available

Execution rule:
  implement cards continuously; small commits per boundary; checkpoint once at wave end unless a material decision blocks safe continuation.
```

---

## 17. Default instruction for coding agents

The following can be copied into a project handoff:

> Execute implementation in end-to-end waves. Treat cards as audit/commit boundaries, not conversation boundaries. Do not pause after every card. Verify repository/branch/HEAD at wave start, inspect relevant source-of-truth code, then implement all cards in the wave continuously with small revertible commits and focused regression tests. Revalidate authoritative state before mutations, preserve immutable/raw data and backward compatibility, and reuse existing lifecycle/services instead of creating duplicate sources of truth. Stop only for a material product/architecture/data-integrity conflict. At the end of the wave, perform an integration review, update one rolling checkpoint, and report what is actually usable plus the validation that truly ran. Never claim full tests/CI passed unless they were executed successfully.

---

## 18. Adoption

When this standard is adopted by a repository:

- reference this file from the project's current execution checkpoint or agent handoff;
- project-specific business rules remain authoritative over this generic execution process;
- if a project needs a stricter rule, document the stricter project-specific override explicitly;
- otherwise, this document is the default development execution behavior.
