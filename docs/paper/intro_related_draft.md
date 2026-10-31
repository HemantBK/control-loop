# Draft: introduction and related work (2026-10-28; PLAN Amendment (1))

This is a draft written before any result. The bracketed sentences are placeholders for results and stay empty until
kill check 2. Every citation was checked on 2026-10-28 (`docs/paper/citation_check_2026-10-28.md`); none is from
memory alone.

## 1. Introduction

A detector that tells an attacker its verdicts becomes a tool for evading it.

**Security has seen this many times:**
- Lowd and Meek showed in 2005 that membership queries to a classifier are enough to find low-cost inputs it lets
  through [Lowd & Meek 2005a]. Nelson et al. extended query-based evasion to the whole family of convex-inducing
  classifiers [Nelson et al. 2012].
- In practice, attackers use exactly this channel:
  - spammers add "good words" until a filter lets their mail pass, and do far better when they can see the filter's
    decisions [Lowd & Meek 2005b];
  - malware authors submit work-in-progress samples to public analysis sandboxes to see what is detected
    [Graziano et al. 2015];
  - card-testing fraud sends small transactions to learn which stolen cards a payment system will accept [Stripe 2022].
- Against learned detectors, evasion succeeds with only label feedback [Dang et al. 2017; Brendel et al. 2018; Chen et
  al. 2020] or with scores [Chen et al. 2017; Xu et al. 2016]. Richer outputs such as confidence values leak more
  [Tramèr et al. 2016]. Ilyas et al. [2018] make the amount of feedback an explicit axis: query-limited, partial-information
  and label-only.

**Security's answer is information hygiene:**
- reveal less: labels instead of confidences [Tramèr et al. 2016];
- perturb what is revealed [Orekondy et al. 2020; Qin et al. 2021];
- watch the query stream for the signature of a search [Chen et al. 2020b; Li et al. 2022];
- act silently, so that the person being moderated cannot tell from what they see whether they were caught
  [Le Merrer et al. 2021].

**AI control** asks whether a protocol stays safe when the AI it oversees is trying to subvert it [Greenblatt et al.
2023]. Its central tool is a trusted monitor that scores the untrusted agent's actions, with a small audit budget for the
most suspicious ones.
- Recent work shows that such monitors fall to adaptive attackers:
  - attacks built with knowledge of the monitor [Terekhov et al. 2025];
  - attacks refined against the monitor's scores and reasons [Jotautaitė et al. 2026; Kitaoka et al. 2026];
  - strategic choice of when to attack [Schaeffer et al. 2026; Ge-Wang et al. 2026].
- Deployed protocols reveal a great deal by design. A blocked action tells the agent it was flagged; a retry prompt often
  says why; agents with memory carry those verdicts into later tasks.
- That such feedback leaks is already established:
  - untrusted models exploit trusted feedback in control protocols, and feedback-side mitigations did not restore the
    baseline [Hopman et al. 2025];
  - retrying with detailed feedback is exploitable, retrying without feedback less so, and resampling leaks nothing
    exploitable [Lucassen & Kaufman 2026];
  - an LLM can learn to evade a latent monitor from its verdicts alone [Keenan et al. 2026];
  - attackers that know protocol internals cut safety sharply, while protocols that deny them that access hold
    [Kutasov et al. 2025b].
- Yet an agent told that its earlier attack was caught sabotaged *less* on the next task [Saeedi & Aghazadeh 2026].
  Feedback's value to an attacker is not settled.

What is missing is a controlled measurement: **how much does each component of the feedback (verdict, score, reasons)
help an attacker at a fixed search budget, and how much do coarsening, delay, noise and silent auditing remove?** Kitaoka
et al. [2026] note that their own feedback experiment "does not isolate which part of the feedback causes a plan to
improve".

**What we do.** We treat the monitor's feedback as a leakage channel and order it by how much it reveals:
- nothing;
- the outcome only;
- the binary verdict;
- the suspicion score;
- the written reasons.

An automated attacker searches for attacks at each level, with the proposer, strategy library, budget and selection rule
held fixed. Each search's chosen attack is confirmed on fresh problem instances. We then apply four security mitigations
at the strongest level that shows an advantage: coarsening, delay, noise and silent auditing. We also test giving the
monitor task-level context. Throughout, we measure the attacker's advantage at 2% and 5% audit budgets that clean runs
can actually support, with confidence intervals over independent searches.

[Results paragraph: the curve, the mitigations that flatten it, the usefulness costs. Empty until kill check 2.]

**Contributions:**
- a matched-budget isolation of what each feedback component is worth to an attacker, in a multi-agent control
  setting, with independent searches and held-out, execution-confirmed attacks;
- a test of four security mitigations and of monitor context as defenses, with their usefulness cost;
- rules for what a control protocol should and should not reveal to the agent it monitors.

**Scope.** All experiments run in sandboxed benchmarks: ORBIT's JiraTicket allocation task, and a case study on
ResearchArena with no new runs. They use the benchmarks' own side tasks. No real system, user, service or data is
involved.

## 2. Related work

**Query-based evasion of classifiers.**
- Adversarial classification was framed as a game between classifier and adversary by Dalvi et al. [2004].
- Lowd and Meek [2005a] showed that an attacker with membership queries can find near-minimal-cost evading instances of
  linear classifiers. Nelson et al. [2012] gave query algorithms for convex-inducing classifiers that need no
  reconstruction of the decision boundary.
- Barreno et al. [2006] set out the taxonomy of attacks on learning systems. Biggio et al. [2013] and Biggio & Roli
  [2018] connected evasion at test time to the later adversarial-examples literature.
- With **scores**, black-box attacks estimate gradients by querying [Chen et al. 2017] or train a substitute model
  [Papernot et al. 2017].
- With **labels only**, decision-based attacks still succeed [Brendel et al. 2018; Chen et al. 2020], at a higher query
  cost. Ilyas et al. [2018] study this ladder directly: query-limited, partial-information and label-only settings.
- Our leakage ladder is the control-protocol analogue of that ladder. Our attacker is an LLM proposer rewriting text, not
  a gradient or boundary search.

**Evading deployed detectors.**
- Against spam filters, active attacks with filter feedback were far stronger than passive ones [Lowd & Meek 2005b].
- Against PDF malware classifiers:
  - feature-space evasion of a deployed detector [Šrndić & Laskov 2014];
  - genetic search using the detector as an oracle [Xu et al. 2016];
  - evasion with only the reject/accept bit [Dang et al. 2017].
- Against PE malware models, reinforcement learning with only the detector's verdict [Anderson et al. 2018].
- Malware authors use public sandboxes to test and refine their samples before release [Graziano et al. 2015].
- Fraudsters test stolen cards with small transactions [Stripe 2022].

**Information hygiene as a defense.**
- Returning labels instead of confidences, and rounding outputs, reduce what prediction APIs leak [Tramèr et al. 2016].
- Perturbing the returned output degrades attacks that learn from it [Orekondy et al. 2020].
- Randomness reduces query-based attacks' success [Qin et al. 2021].
- Stateful defenses detect the near-duplicate query streams that searches produce [Chen et al. 2020b; Li et al. 2022].
- Silent moderation (shadow banning) withholds the verdict from the user it affects, and is itself hard for users to
  detect [Le Merrer et al. 2021].
- We test the control-protocol versions of coarsening, delay, noise and silent auditing. We do not test query-stream
  detection, which we leave to future work.

**Adaptive attacks in AI control.**
- AI control evaluates protocols against an untrusted model that tries to subvert them [Greenblatt et al. 2023], in
  settings such as SHADE-Arena [Kutasov et al. 2025], multi-step agent tasks with resampling [Bhatt et al. 2025] and
  long-horizon research [Libon et al. 2026].
- Monitors fall to:
  - injections aimed at them [Terekhov et al. 2025];
  - attacks refined against their scores and reasons [Jotautaitė et al. 2026], where a reconnaissance condition
    without monitor tools also differs in other affordances;
  - agent-generated injections against production blocking monitors [Remedios et al. 2026];
  - curated evasion strategies [Najt et al. 2026];
  - strategic attack selection [Schaeffer et al. 2026; Ge-Wang et al. 2026];
  - evasion tactics drawn from earlier monitor verdicts in AI R&D sabotage [Zhou et al. 2026].
- In multi-agent settings, distributed attacks evade per-agent monitors [Makins et al. 2026; Kitaoka et al. 2026; Radev
  et al. 2026]. Kitaoka et al. give their planner execution and monitor feedback, but do not isolate which part of the
  feedback helps.
- These works show that adaptive attackers win. They do not vary what the monitor reveals while holding the attacker's
  budget fixed.

**Feedback and history in AI control (closest work).**
- Hopman et al. [2025] show that untrusted models exploit trusted feedback in an editing protocol (safety 93% to 80%).
  Compliance monitoring and selective editing helped, but did not restore the baseline.
- Lucassen & Kaufman [2026] compare three conditions:
  - retrying with detailed feedback, which a strategic attacker exploits;
  - retrying without feedback, which is harder to exploit directly, though they note it may be open to more
    sophisticated attack selection;
  - resampling, which leaks nothing exploitable.

  Their without-feedback condition is not tested against an adaptive attacker.
- Keenan et al. [2026] frame monitor verdicts explicitly as leakage. A model learns to edit its activations to evade
  latent monitors from verdict feedback alone.
- Kutasov et al. [2025b] find that attack policies with knowledge of protocol internals, or able to simulate monitors,
  cut safety to 17%, while deferring on critical actions held.
- Saeedi & Aghazadeh [2026] give an agent its intervention history across tasks. For one model, being told its attack
  was replaced *reduced* later sabotage success (77% to 12%); another model showed no significant change.
- Shi et al. [2026] find that verification feedback and interaction history shape emergent collusion.
- **What we add** is not the framing but the measurement:
  1. each feedback component isolated at a matched search budget, with the selector's information declared;
  2. independent searches, each confirmed on fresh instances;
  3. coarsening, delay, noise and silent auditing tested against the same attacker;
  4. audit budgets supported by clean-run counts.

## References (all checked 2026-10-28; identifiers in `citation_check_2026-10-28.md`)

**Security and adversarial machine learning:**
- Anderson, Kharkar, Filar, Evans, Roth. Learning to evade static PE machine learning malware models via reinforcement
  learning. arXiv:1801.08917, 2018.
- Barreno, Nelson, Sears, Joseph, Tygar. Can machine learning be secure? ASIACCS 2006.
- Biggio, Corona, Maiorca, Nelson, Šrndić, Laskov, Giacinto, Roli. Evasion attacks against machine learning at test time.
  ECML PKDD 2013.
- Biggio, Roli. Wild patterns: Ten years after the rise of adversarial machine learning. Pattern Recognition, 2018.
- Brendel, Rauber, Bethge. Decision-based adversarial attacks. ICLR 2018.
- Chen, Zhang, Sharma, Yi, Hsieh. ZOO. AISec 2017. [Chen et al. 2017]
- Chen, Jordan, Wainwright. HopSkipJumpAttack. IEEE S&P 2020. [Chen et al. 2020]
- Chen, Carlini, Wagner. Stateful detection of black-box adversarial attacks. SPAI 2020. [Chen et al. 2020b]
- Dalvi, Domingos, Mausam, Sanghai, Verma. Adversarial classification. KDD 2004.
- Dang, Huang, Chang. Evading classifiers by morphing in the dark. CCS 2017.
- Graziano, Canali, Bilge, Lanzi, Balzarotti. Needles in a haystack. USENIX Security 2015.
- Ilyas, Engstrom, Athalye, Lin. Black-box adversarial attacks with limited queries and information. ICML 2018.
- Le Merrer, Morgan, Trédan. Setting the record straighter on shadow banning. INFOCOM 2021.
- Li, Shan, Wenger, Zhang, Zheng, Zhao. Blacklight. USENIX Security 2022.
- Lowd, Meek. Adversarial learning. KDD 2005. [2005a]
- Lowd, Meek. Good word attacks on statistical spam filters. CEAS 2005. [2005b]
- Nelson, Rubinstein, Huang, Joseph, Lee, Rao, Tygar. Query strategies for evading convex-inducing classifiers. JMLR 13,
  2012.
- Orekondy, Schiele, Fritz. Prediction poisoning. ICLR 2020.
- Papernot, McDaniel, Goodfellow, Jha, Celik, Swami. Practical black-box attacks against machine learning. AsiaCCS 2017.
- Qin, Fan, Zha, Wu. Random noise defense against query-based black-box attacks. NeurIPS 2021.
- Šrndić, Laskov. Practical evasion of a learning-based classifier: a case study. IEEE S&P 2014.
- Stripe. How Stripe responded to a wave of card testing attacks. Stripe newsroom, 2022 (industry source).
- Tramèr, Zhang, Juels, Reiter, Ristenpart. Stealing machine learning models via prediction APIs. USENIX Security 2016.
- Xu, Qi, Evans. Automatically evading classifiers: a case study on PDF malware classifiers. NDSS 2016.

**AI control:**
- Hopman, Lemoine, Tracy. Untrusted AIs can exploit feedback in control protocols. LessWrong, 2025-05-27.
- Keenan, Leckie, Erfani. LLMs learn to evade latent monitors from prior feedback alone. arXiv:2609.36490.
- Kutasov, Loughridge, Sun, Sleight, Shlegeris, Tracy, Benton. Evaluating control protocols for untrusted AI agents.
  arXiv:2511.02997. [Kutasov et al. 2025b]
- Remedios, Storf, Roger, Hughes. Red-teaming Auto Mode. arXiv:2609.19587.
- Bhatt et al. Ctrl-Z. arXiv:2504.10374.
- Ge-Wang et al. arXiv:2606.06529.
- Greenblatt et al. AI Control. arXiv:2312.06942.
- Jotautaitė et al. MonitoringBench. arXiv:2605.09684.
- Kitaoka et al. MiniLab. arXiv:2610.24052.
- Kutasov et al. SHADE-Arena. arXiv:2506.15740.
- Libon et al. ResearchArena. arXiv:2607.19321.
- Lucassen, Kaufman. Retrying vs resampling in AI control. arXiv:2605.26047.
- Makins et al. FakeLab. arXiv:2607.07368.
- Najt et al. SLEIGHT-Bench. arXiv:2605.16626.
- Radev et al. SCHEME. arXiv:2605.29178.
- Saeedi, Aghazadeh. How intervention history changes AI agent sabotage on subsequent tasks. arXiv:2610.26935.
- Schaeffer et al. arXiv:2602.04930.
- Shi et al. Emergent collusion. arXiv:2609.24967.
- Terekhov et al. arXiv:2510.09462.
- Zhou et al. RSI Control. arXiv:2610.27735.
