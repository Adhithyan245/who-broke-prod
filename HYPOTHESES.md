# Preregistered hypotheses (fixed before any experiment run)

Written and committed before `python -m whobrokeprod experiment` was ever executed. The git history of
this directory shows this file's commit before the commit of `results/`. Every number below is a
decision threshold fixed in advance. Refuted hypotheses are reported as refuted.

## Question

In a deterministic simulated incident, how do coordination topology (flat, hub-mediator, chain), the
agents' blame incentive (neutral, self-protective), and the investigator's trace access (full trace
verification, claims only) affect root-cause attribution accuracy, false-blame rate, and rounds to a
stable correct attribution?

## Fixed design

- Scenarios: 4 fixed incidents (`bad_deploy`, `flag_flip`, `migration_lock`, `cache_stampede`), each a
  seeded ground-truth event trace with exactly one causal event and one red-herring event.
- Agents: 5 rule-based agents (DeployBot, ConfigBot, AutoScaler, DBMigrator, CacheBot).
- Fixed parameters: witness probability 0.35, culprit fabricated-citation probability 0.5, chain hop
  evidence-drop probability 0.15, investigator verification budget 1 claim per round, mediator budget 1
  check, deadline 5 rounds.
- Repetitions: seeds 0..49 per scenario = 200 matched units per cell; 3 x 2 x 2 = 12 cells; 2400 runs.
  The same (scenario, seed) unit uses common random numbers across all cells, so comparisons are paired.
- Analysis: proportions with Wilson 95% intervals; paired two-sided exact sign test on discordant
  (scenario, seed) pairs; alpha = 0.01. Means of steps-to-attribution over runs that reach a stable
  correct attribution.

## H1 - Trace access raises accuracy
- Claim: under self-protective incentive, pooled over topologies, accuracy(full) - accuracy(claims_only) >= 0.10, sign-test p < 0.01.
- H0: difference < 0.10 or p >= 0.01.

## H2 - Trace access converts false blame into abstention
- Claim: under self-protective incentive, pooled over topologies, false_blame(full) <= 0.5 x false_blame(claims_only).
- H0: false_blame(full) > 0.5 x false_blame(claims_only).

## H3 - Incentive x access interaction
- Claim: under claims_only, false_blame(self_protective) - false_blame(neutral) >= 0.10 (pooled over
  topologies); under full access the same difference <= 0.05.
- H0: either condition fails.

## H4 - Latency ordering of topologies
- Claim: under full access and self-protective incentive, mean steps-to-attribution satisfies
  flat <= hub <= chain, with flat < chain.
- H0: the ordering fails.

## H5 - Chain relay distortion costs accuracy (competes with H6 as the dominant topology effect)
- Claim: under full access and self-protective incentive, accuracy(flat) - accuracy(chain) >= 0.10, sign-test p < 0.01.
- H0: difference < 0.10 or p >= 0.01.

## H6 - A verifying mediator improves accuracy over flat reporting
- Claim: under full access and self-protective incentive, accuracy(hub) - accuracy(flat) >= 0.05, sign-test p < 0.01.
- H0: difference < 0.05 or p >= 0.01.

## Scope

Evidence about this simulation only. No claim transfers to real production systems, real incident
response teams, or real organisations. Several effects are partly built in by the simulator's design;
the experiment tests whether the specified mechanisms produce effects of the stated size.
