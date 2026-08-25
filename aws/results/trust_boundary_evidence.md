# E2 — who does the gate protect?

Run 2026-08-24, account `426674444486`, `us-east-1`. Test role
`nfgate-caller-test`, assumed rather than applied to the calling user, so a
Deny could not lock the account out of HealthOmics.

## The question

The `beforeScript` gate lives inside the workflow bundle **the caller
supplies** and runs in the image **the caller chooses**. It therefore protects a
caller from their own pipeline. Whether it can be enforced *against* that caller
was the only research question left in this line.

The candidate closure was IAM: restrict `omics:StartRun` to an allowlist of
approved workflow ARNs, so a caller who writes their own ungated definition
cannot start it. Whether `StartRun` honours resource-level restriction is a fact
about AWS's behaviour, and — per `aws/audit/RESULTS.md` — AWS's documentation is
not evidence about that. So it was tested.

## Result

| Check | Outcome | |
|---|---|---|
| 1. Start the **approved** workflow | **ALLOWED** — run `2475440` | policy is not simply denying everything |
| 2. Start a **different** workflow | **DENIED** `AccessDeniedException` | resource-level restriction works |
| 3. **Author** a new ungated workflow | **ALLOWED** — workflow `3838526` | the caller does own the bundle |
| 4. Start the workflow they authored | **DENIED** `AccessDeniedException` | **the boundary closes** |

Check 1 matters as much as check 2: a policy that denied everything would pass
checks 2 and 4 while being useless, and would look like a result.

## Reading

**`omics:StartRun` honours resource-level restriction to an approved workflow.**
A caller can write an ungated definition — they own the bundle, and nothing
prevents that — and cannot start it. So the gate **is** enforceable against the
caller, by configuration rather than by architecture:

> approved-workflow allowlist on `StartRun` (who may run *what*)
> **+** in-bundle `beforeScript` gate (what each task may do *given dataset state*)

The two are complementary and neither substitutes for the other. IAM decides
which artifact may run; the descriptor gate decides, per task, whether the
operation is permissible in the state its input is actually in — which IAM
cannot express.

## What this costs the research framing

**It removes the last open research question in the cloud line.** The trust
boundary was the one thing left that looked like a question rather than an
integration exercise, and it turns out to be answered by an ordinary IAM
resource restriction.

What remains is a deployable pattern with evidence behind it. That is worth
publishing as an experience report and is not a research contribution. Recording
it that way now is cheaper than discovering it in review.

## Caveat

Single trial per check, and the checks are binary authorisation outcomes rather
than measurements. The `AccessDeniedException` in checks 2 and 4 is the specific
error for the specific action and resource, not a generic failure, which is why
one trial is defensible here in a way it would not be for a timing claim.
