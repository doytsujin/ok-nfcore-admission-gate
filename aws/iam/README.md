# The policies

Four documents, kept as **valid IAM policy JSON** with no comment keys, so each
can be applied directly:

```
aws iam put-role-policy --role-name ROLE --policy-name NAME \
    --policy-document file://aws/iam/THIS-FILE.json
```

IAM rejects unknown top-level keys, so the reasoning lives here instead of
inline. The placeholders `ACCOUNT_ID`, `REGION`, `RUN_BUCKET` and
`DECISION_BUCKET` are substituted by `aws/setup.sh`; if you apply a file by
hand, substitute them first.

## `deny-startrun-except-gate.json` — this one is the gate

The Lambda is the decision. **This is the enforcement.** A decision function a
caller can walk around is a logging statement with extra steps.

Attach it to every principal that must not start runs directly — humans, CI
roles, notebook roles. At organisation scale it belongs in an SCP, where the
account it constrains cannot detach it.

Two statements, and both are load-bearing:

- `OnlyTheGateMayStartRuns` denies `omics:StartRun` with an `ArnNotLike`
  exception for the gate's assumed-role session. Without the exception the deny
  also locks out the gate itself. Naming the gate by *user* rather than by role
  would break the first time the function is redeployed.
- `AndMayNotEditTheirWayOutOfIt` denies edits to the gate role. An enforcement
  point a constrained principal can rewrite is not one.

**`setup.sh` deliberately does not attach this.** Attaching it to the wrong
principal locks you out of your own account's HealthOmics. Attach it yourself,
then verify a direct `StartRun` is refused — until that is done, E2 is not
measured.

## `gate-role-policy.json` — what the gate may do

`omics:StartRun` plus the two reads needed to follow a run, `iam:PassRole`
narrowed to the run role and conditioned on `iam:PassedToService`, and
`s3:PutObject` restricted to the `decisions/` prefix. The gate can start runs
and write decision records. It cannot read the run outputs and cannot pass any
other role.

## `omics-run-role-policy.json` — what the run may do

Read inputs, write outputs, pull containers from the `nfgate/*` repositories,
write its own logs. **It cannot call `StartRun`**, so a task cannot launch an
ungated run from inside a gated one.

## `omics-run-role-trust.json`

Trust policy letting `omics.amazonaws.com` assume the run role. Nothing else.
