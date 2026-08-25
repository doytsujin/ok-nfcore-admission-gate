# Where the audit should go

## What is being placed

> Of 8 entries with a decidable probe on a vendor-published list of 23
> unsupported features — shipped by the vendor as a linter, last edited 907 days
> before the test — **7 do not hold**.
>
> A governance mechanism whose correctness is argued from a provider's
> documentation inherits that documentation's error rate, and that rate is
> measurable rather than assumed.

It is **not** a biomedical informatics result and must not go in the JBI paper.
There it is one subsection: portability, plus the two deployment constraints.

## Recommendation: IEEE Software

Best fit, and the fit is unusually close.

| Requirement | This work |
|---|---|
| ≤ 4,200 words (250 per figure/table) | comfortable; the study is small by design |
| ≤ 15 references | comfortable |
| 150-word abstract | fine |
| **Three actionable insights, bulleted** | the paper's actual spine, see below |
| Practitioner audience | anyone building on a provider's documented behaviour |
| No travel | magazine, [[project_venue_strategy]] satisfied |

Editor-in-chief accepts an abstract by email to gauge suitability before a full
submission, which costs a day and de-risks the whole thing.

**The three insights write themselves, which is the strongest signal of fit:**

1. **Test the vendor's claims about the vendor.** The list was published for
   exactly this purpose and was wrong 7 times in 8.
2. **Calibrate the instrument before believing it.** Every probe was run first
   against a reference engine where the answer was known. Three probe defects
   would otherwise have been reported as service behaviour.
3. **A no-directive control is not optional.** Three verdicts looked like
   "the vendor is wrong" on evidence that could equally have been the default.

## Why not the obvious empirical venues

**Empirical Software Engineering (EMSE)** and **JSS** would want a study, not a
case. One provider, one service, one list, 8 decidable claims, n=1 for the
positives. A reviewer would reasonably ask for multiple providers before
accepting a claim about documentation error rates in general — and that
question would be right.

**That is the expansion path, not an objection.** The same harness points at
Azure Batch, Google Batch and Seqera Platform, and the method transfers
unchanged: take each provider's published statements about its own supported
features, probe them, control them, report what could not be decided. A
three-provider version is an EMSE paper. This one is not, and submitting it
there would waste a year finding that out.

**IEEE Access** would take it and adds little. **;login:** is not peer
reviewed. Neither is worth the result.

## What must be in the paper regardless of venue

The **six probe defects caught by calibration**, three of which would have
produced a wrong finding rather than an obvious failure. A paper reporting
someone else's error rate while concealing its own near-misses is making the
same move it criticises, and a reviewer who notices that is right to reject it.

## The special issues, checked 2026-08-25

Three of the open calls looked plausible. Two are already closed.

| Call | Deadline | Status |
|---|---|---|
| Engineering Agentic Systems | **5 Jan 2026** | **closed** |
| The Edge–Cloud Continuum | **17 Jul 2026** | **closed** |
| **Building Trustworthy Software in the Time of AI** | **5 Nov 2026** | **open — 72 days** |

The agentic and edge–cloud issues were the two whose *titles* fit best, and
both sailed months ago. That is worth noting rather than glossing: a venue
search that reads titles and not dates produces a plan that cannot be executed.

**Two routes remain, and they are genuinely different papers.**

**A. Regular submission, no deadline.** The audit exactly as measured. IEEE
Software takes rolling submissions and the result needs no theme to justify it.
Lowest risk, no reframing, and the three actionable insights are already
written.

**B. The Trustworthy Software special issue, 5 November.** Requires a frame the
audit does not currently have: *you cannot assure an autonomous system's
guardrails from the platform's documentation.* That is a real argument and this
programme is unusually well placed to make it — the admission gate supplies the
guardrail, and the audit supplies the measurement that its enforcement surface
was described wrongly by the vendor 7 times in 8.

The special issue asks for "practical, evidence-based approaches" to
reliability and safety across the lifecycle, which this is. The risk is that
the issue is about **AI-enabled** software and the audit is not; the framing has
to carry that, and if it feels forced to write, it will read forced to a
reviewer.

**Recommendation: A, unless the trustworthy framing is one you actually
believe.** B is worth more if it lands, and 72 days is comfortable, but a paper
bent to fit a theme reads like a paper bent to fit a theme. Send the abstract
to the EiC and let that decide it — the same email settles both questions.

## Order of work

1. Email the abstract to the EiC. One day, and it settles fit before drafting.
2. Draft against the 4,200-word limit — the constraint suits the result.
3. Do **not** expand to a multi-provider study first. Publish the case, then
   expand if it lands.
