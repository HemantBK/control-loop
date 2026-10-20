# Call prep: council debate on the ORBIT JiraTicket adaptive red-team result

Written 2026-10-20 against FINDINGS.md, pins.md, jira_adaptive.py, judge_prompts.py, reward.py.

## C and D first: what the audits missed, and the non-agentic claim

### Flaws the four audits did not name

1. The judge prompt is yours, and two of its four rules are unobservable per action.
   FIXED_JUDGE_PROMPT lives in adaptive_control/jira_adaptive.py, not in ORBIT. Rule 3 ("claims a task while
   hiding the real reason") and rule 4 ("misrepresents skills") cannot be evaluated from one assign_task call
   plus a one-line skill-fit justification. A judge that sees only that input has no basis to block, so
   0/20 is close to tautological. The real finding is stronger and different: the winning attack has no
   per-action signature at all. The coalition's claim is byte-identical to an honest greedy claim.
   On the call, say "the fixed judge prompt I wrote" and "a myopic judge with this input", not "ORBIT's monitor".

2. Monitor and protocol are conflated. Every block count is the output of judge + resample-the-turn.
   The harm to outsiders (delayed first claim, t2 -> t5) is a protocol cost: the resample consumes the
   agent's slot. Nobody has looked at the judge's verdicts as scores separated from the action taken.
   A score-only pass (log verdicts, act on none) would answer "does the judge carry information?" (AUROC on
   coalition vs honest claims) independently of "does resampling hurt?". This is the lab's own distinction.

3. The collusion increment has not been isolated. The greedy control gave the claim-first instruction to one
   agent. The right counterfactual for "collusion" is two independently greedy agents with no shared split.
   Greedy dev_0 alone, late order, 733: pair +20 vs coalition cell +40. The residual +20 could be dev_1 also
   being told to claim first, with the pre-split adding nothing. Until two-greedy is run, "coalition payload
   adds the rest" is an assumption. Cost about $3.

4. The submit validity rule selects on the outcome. The monitor blocks submit mostly in attacked episodes where
   the coalition took tickets; in clean baselines it stalls dev_3. So the submit rule removes attacked successes
   and clean failures non-randomly. Reporting both rules is right; calling the monitor cell "inconclusive" is
   too kind. The monitor's own behaviour censors the data that would judge it.

5. Effective n is unknown, not "about 2". Seeded temp-0 runs are claimed to reproduce bit-for-bit, yet the
   g0 clean-vs-clean epochs vary with sd 17 and the transfer_headline table shows epochs 1 and 3 identical and
   epoch 2 different. OpenAI seeding is best-effort. So the sd floors are computed over an unknown number of
   independent draws, between 1 and 8. Say "between one and eight" on the call.

6. Usefulness was never reported on the axis where the monitor costs most. Clean team reward under the monitor
   (113.7) matches no-defense (113.8), but only 9/16 clean monitor epochs finish all submits, and the monitor
   blocks 20 to 30 messages per clean episode. A control evaluation needs the usefulness axis stated; here it
   is "episodes complete" and "messages delivered", not reward.

7. The eleven-days claim is a date arithmetic on the paper, not on the repo. FINDINGS.md says the repo does not
   state which version the paper's runs used. Phrase it as a question.

### D: what this says about "monitors should be non-agentic"

- The monitor tested is already non-agentic (one call, no tools, no memory). It failed anyway. So the experiment
  cannot support or refute the thesis. It shows the failure was lack of observation (no allocation state) and a
  bad protocol (resample consumes turns), neither of which non-agency fixes.
- Weak point in their favour: because the monitor was non-agentic and myopic, its failure was fully enumerable
  (every verdict on every claim). That auditability is an argument for non-agentic monitors as the thing you
  evaluate, not as the thing that works.
- Weak point against: the obvious fix, a claim-time judge that reads view_tasks/view_assignments state, is a
  monitor that observes more. Whether that counts as "agentic" in their taxonomy is the question to ask.
- What would test the thesis: give the proposer a channel into the monitor's inputs (messages the monitor
  reads, tool outputs it inspects) and compare a one-call monitor against one that calls tools, under the same
  adaptive loop. The thesis predicts the agentic monitor's attack surface grows with its agency. This setup
  never let the attacker target the monitor, so it is silent on that.

## A: next experiment, ranked

The debate:
- Allocation-level (iii): the harm is defined at allocation level, the attack has no per-action trace, and an
  optimizer already exists (jira_ticket/optimizer.py). A deterministic allocation check with a reject protocol
  is the ceiling any LLM monitor must beat. Objection: it is not a monitor of agents, it is a scorer of
  outcomes; it tells the lab nothing about monitoring misaligned agents.
- Claim-time stateful monitor plus claim-level rejection (i)+(ii): the natural "give the non-agentic monitor
  the right observation and the right protocol" test, and where the lab's thesis lives. (ii) is the protocol
  for (i), not a separate experiment. Objection: a stateful judge will also block honest greedy claims; the
  two-greedy control is needed to know what "honest" looks like.
- RL / trajectory-reading attacker (iv): the finding that prompt rewriting did not discover strategy is the one
  that generalizes to the lab's mission. Objection: on a 4-ticket problem with first-mover dominance, any
  learned policy converges on claim-first in a few episodes; it will not teach anything the greedy control
  does not. Run it only on a scenario where a defense has survived (i)-(iii).
- Fix the scenario (v): order dominates, so the scenario does not test collusion. A sealed-claim variant
  (collect all first-round claims, resolve by priority or skill) removes the order effect and makes a
  pre-agreed split the only route to redistribution.

Ranked recommendation:
1. Prerequisites, half a day, about $5: (a) two-independent-greedy control on 733 late, three arms;
   (b) score-only pass of the current judge logging verdicts without acting, to get AUROC on coalition
   vs honest claims. Without these no new monitor result is interpretable.
2. Stateful claim-time monitor (i) evaluated score-first, then under claim-level rejection (ii), against the
   informed Sonnet proposer, seeds 733, 101, 512, late and claims-last orderings, both validity rules.
3. Deterministic allocation-level check (iii) as the ceiling, same cells.
4. Only if a defense survives 2 or 3: (iv), and only on the sealed-claim variant (v).

Stopping rule for the JiraTicket line: stop when either (a) a defense holds across 733/101/512 with both
validity rules agreeing and the usefulness axis (episodes completing, clean blocks per episode) within the
no-defense band, or (b) the two-greedy control reproduces the coalition effect within the noise floor,
which means the scenario has no collusion to defend against and should be replaced by (v), or (c) two more
audit cycles change the headline sign. Budget cap for this line: $60.

## B: the call

Headline, one breath: "On JiraTicket, who claims first dominates. A coalition told to claim first and say
nothing captures the allocation under the anti-collusion prompt. The myopic monitor allowed all twenty
coalition claims, and its false positives on honest agents created the coalition's opening. Once outsiders
have claimed, the attack is nearly inert. The adaptation came from my move list, not from the loop."

Lead with the result, then one sentence on the audits. Four audits reshaping the result is the second most
interesting thing you have, but only after they know what the result is.

ORBIT findings: raise two as questions, hold two as PR offers.
- Ask: "Which ORBIT version did the paper's monitor runs use? On 1.0.3 the default monitor preset withholds the
  injected coalition prompt at the input boundary before the agents see it, so I measured both the shipped
  preset and an actions-only variant."
- Ask: "Is the judge meant to run at provider default temperature? LLMMonitorDefense passes no GenerateConfig;
  I seeded it for the control program."
- Offer as PRs: the static payload's coordinate-first behaviour loses against the one-turn-delay channel on
  gpt-4o (−57.5, sd 1.3); a judge-blocked submit leaves episodes incomplete without the scorer flagging it.

Script, 30 minutes:
- 0-2: who you are in one line each: StepShield, MATS incident telemetry harness, the MARL survey finding
  that no defense faced an adaptive adversary. "So I spent two days making ORBIT's adversary adaptive."
- 2-8: the headline, the design (proposer loop, three arms, round 0 = paper payload), the headline cell
  numbers, the claims-last result, the greedy control. Three numbers at most.
- 8-12: what four audits changed: metric to redistribution deltas, timing claim withdrawn, seed 42
  reinterpreted as team-improving, uninformed proposer collapsed. Say what you still do not know: effective n,
  one agent model, one clean seed.
- 12-16: the two ORBIT questions above. Then the monitor-vs-protocol point in their vocabulary: "the harm to
  honest agents was the resample protocol, not the judge's score. I never separated them. That is the first
  thing I would run."
- 16-22: your ranked next experiment and stopping rule. Ask whether a claim-time judge that reads allocation
  state is "agentic" in their taxonomy.
- 22-28: their questions. Prepared answers:
  "That is your judge prompt, not ours": yes; the prompt is mine, the judge model, boundary, resampling are
  ORBIT's; the finding is that no per-action input supports the rule, whatever the prompt.
  "n is tiny": yes; effective n between one and eight per cell; this is a pilot that found a confound, not a
  result about collusion defenses.
  "One seed": yes; 101 and 512 are adverse or mixed; the clean effect lives on 733; I report all three.
  "You did not test the shipped defense fairly": the shipped preset held because the attack was withheld
  before the agents saw it; that is a filter effect, which is legitimate if intended; is it intended?
- 28-30: what the MTS role does day to day, and what they would want run on ORBIT first.

Questions to ask him, in priority order:
1. Which version and preset produced the paper's monitor numbers?
2. In your taxonomy, is a monitor that reads shared state (allocation, claims so far) agentic?
3. What is the lab's control protocol story: resample, reject, defer to trusted, audit budget?
4. Does the RSI setting have an "order dominates" analogue (first to modify weights or evals wins)?
5. What attack policies are planned: prompt rewriting, trajectory-reading, RL?
