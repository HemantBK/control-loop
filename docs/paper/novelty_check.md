# Novelty check for the paper (2026-10-27)

Six papers, each read in full (main text and appendices) on 2026-10-27, from the arXiv HTML versions. No run was made for
this check. For each paper: the method, the models, the findings, and what it means for our thesis. The comparison with
our work is in `docs/paper/PLAN.md` §2.

## Terekhov, Panfilov, Dzenhaliou, Gulcehre, Andriushchenko, Prabhu, Geiping; "Adaptive Attacks on Trusted Monitors Subvert AI Control Protocols", arXiv:2510.09462 (ICLR 2026)

- Threat model: Kerckhoffs — attacker knows the monitor model, its prompt, the protocol and thresholds; stateless across tasks; high-stakes game; audit budget c = 2% (sensitivity 1%, 4%).
- Attack: prompt injection embedded in the untrusted model's output (code comment / text block) addressed to the monitor: (a) a public jailbreak (policy-puppetry style) adapted per monitor offline by DeepSeek-Chat using monitor prompt + feedback from first 10 side-task solutions, one universal injection per monitor; (b) zero-shot injections written by a jailbroken GPT-5 per query.
- Settings: APPS backdooring (552 problems; GPT-5 attacker) and BashBench (257 tasks; Claude Sonnet 4 attacker), ControlArena protocols: upfront auditing, trusted monitoring, defer-to-trusted, trusted editing, defer-to-resample.
- Monitors: GPT-4o-mini, GPT-4o, GPT-4.1 (and GPT-4 cross-monitor).
- Threshold/safety: audit budget on honest distribution; safety from optimized blue-red game (KDE, exponential budgets, min-max), bootstrapped 95% CIs.
- Results: injections collapse ROC (often below diagonal); GPT-4.1 scored all 375 backdoored GPT-5 samples 0; protocols fall to upfront-auditing safety; injections transfer across monitors (except GPT-4); DTR backfires (best-of-n, 1−(1−p)^k); zero-shot GPT-5 injections beat GPT-4o-mini. Mitigations proposed (not tested adaptively): instruction/data separation, ensembling, hierarchical scaffolds. Spent ~$10k.
- Relevance: the field's main "adaptive attack" result; one attack family (F1), fixed (not swept) search effort, weaker (4o/4.1-class) monitors; no curve of safety vs attacker search budget × monitor strength; defenses not tested adaptively.

## MiniLab (Kitaoka, Pham, Giudice, Merizian; arXiv:2610.24052, 16 Oct 2026; MATS/Redwood)

- Setting: MiniLab on Control Tower (Inspect, LinuxArena base): 5 live interconnected services (eval, registry, release, compute/change, serving), 249 benign tasks, 8 attack objectives (safety check faked, rebuilt from backups, shipped past review, backdoor, weight exfil, rogue compute, sandbox breakout, blinded monitoring); deterministic state graders; side tasks chainable.
- Attack: distributed attacks — 3 agents each with own main task, shared side task, fragments; 16 human-optimized attacks; optimization loop like SLEIGHT-Bench: offline edit of recorded trajectories against monitor scores+explanations (justifications, split tool calls, shift actions between agents), target ≤4/10; distilled to step-by-step plans run live by DeepSeek-V4-Pro executors (model-planned: V4-Flash).
- Monitors: GPT-5.6 Sol (strong), GPT-5.6 Luna (weaker); LinuxArena async trajectory monitor with ControlArena SWE-strong prompt (0-10); no reasoning, no messages; 12 readings per trajectory, median.
- Threshold: 7.5 = 2% FPR per agent trajectory, calibrated on 316 benign teams (per-agent FPR 1.4% 13/904); 8.5 = 1%.
- Results: per-agent Sol flags 7% (14/208) of successful distributed attacks vs 87% (118/136) single agent; at 1%: 2% vs 81%; joint monitoring 41% (31.7% at joint 2% thr 8.5). Six-stage chain without any agent flagged (agent medians ≤6, whole-team 9 by stage 4). Explanations: complete explanation 0.7% when one agent left out vs 16.1% full team.
- Model planning: 7 planners; without feedback best 19% covert (Luna); with execution+Luna feedback tool, Opus 4.8 3%→48%, DeepSeek V4 Flash 19%→45%; transfer to held-out Sol: 48→20%, 45→25%; human plans 85% (Luna) → 80% (Sol). No-plan: 0% covert; messaging doesn't help.
- Ablations: reasoning visible raises suspicion 0.9-1.5 → 2.5-5.0; synchronous Luna monitor thwarts 0/16 human attacks, 12% of AI-planned.
- Limits: human-crafted mostly; optimized for failures (not frequencies); joint monitoring assumes known colluders.
- Relevance to us: shows (i) attacker search with monitor feedback raises covert success (3→48%) — "search effort" axis partly; (ii) transfer to a stronger held-out monitor drops success (48→20%) — "monitor strength" axis partly; (iii) 2%/1% FPR thresholds calibrated on benign. Does NOT vary search budget systematically as a curve, nor ensembles/randomized prompts, nor ORBIT-style allocation/coalition.

## Colosseum (Nakamura, Kumar, Das, Abdelnabi, Mahmud, Fioretto, Zilberstein, Bagdasarian; arXiv:2602.15198; UMass/UVA/ELLIS)

- Method: auditing collusion in cooperative multi-agent LLM systems cast as DCOPs (Terrarium blackboard framework). Action-based collusion via regret vs cooperative optimum (overall regret, coalition mean regret, coalition advantage); communication-based via LLM-as-judge (GPT-5.4, 3 prompts, 0-5 Likert). Behavioral probe: secret channel between 2 agents; Emergent (no collusion prompt, λ_spec=0) vs Prompted (maximize coalition reward). λ-alignment interpolation between nominal and coalition objective.
- Environments: Jira ticket allocation, Hospital job-shop with resource provisioner, Meeting scheduling (CoLLAB). Topologies complete/path/star/BA/WS/ER.
- Models: 19 out-of-the-box models (incl. Claude Sonnet 4.5, Opus 4.6, Gemini 2.5 Flash, GPT-4.1-mini, GPT-4o-mini, Kimi-K2); temp 0.7, judge temp 0; 5 seeds (10 for Fig 4); ~$2k.
- Findings: secret channel induces emergent collusion: 57.89% of models show action-based (Δ-advantage>0) vs 10.53% judge-detected (Δjudge≥1) → hidden collusion; Prompted 78.95%/78.95%. Inverse association advantage vs judge score (r=−0.24). "Collusion on paper": planning in text but non-collusive actions. Coalitions with high-leverage provisioner reliably achieve objectives; authority/reciprocity persuasion raise regret up to 2.65×/2.77×; misinformation belief rises ~linearly with # adversaries; dense topologies resist. Larger models less action-based emergent collusion. Simple coalition prompt > aggressive deception prompts.
- Mitigations proposed (not tested as defenses against an adaptive attacker): audit private channels, stricter controls on high-leverage agents, verify allocation claims against shared state (outcome-based), preserve cross-checking topology.
- Relevance: closest to ORBIT's coalition/allocation setting and to outcome-based (regret/allocation) checks vs text judges — shows judges miss action-based collusion. Does NOT run an adaptive attacker search, no monitor-strength sweep, no audit-budget safety curves.

## ResearchArena (Libon, Rank, Yeon, Schmotz, Qin, Donnelly, Prinzhorn, Andriushchenko; arXiv:2607.19321; ELLIS Tübingen/MPI)

- Framework: 4 long-horizon AI R&D tasks (safety post-training Qwen3-1.7B, capabilities post-training Qwen2.5-0.5B GSM8K, CUDA-kernel optimization TinyLlama-1.1B, inference-server optimization Qwen2.5-3B), 1 H100, 5 h / 1 h budgets. Side tasks: embedded (sabotage in the artifact: safety backdoor, cross-lingual alignment faking, test-set contamination, long-context RoPE / latency / bf16 kernel backdoors, benchmark gaming, wrong-answer trigger, conversation exfiltration) vs independent (checkpoint exfiltration; typosquat dependency py-cod in requirements.txt).
- Monitors: post-hoc agentic monitors on 4 access types (traj, traj+CoT, artifact, artifact+CoT); 0-100 suspicion; fixed threshold 50 for detection; also AUROC.
- Models: red team Claude Opus 4.6/4.8, Sonnet 4.6 (Claude Code), GPT-5.4/5.5 (Codex), Gemini 3.1 Pro and GLM-5.1 (OpenCode) (+GPT-5.3-codex); monitors Sonnet 4.6, GPT-5.4 (all), + GPT-5.5, Opus 4.8, Kimi K2.6, GLM-5.1 on optimization settings. 3 runs/config; 345 red-team runs; 4,576 monitor runs.
- Findings: sabotage has no main-task cost; embedded executed almost always, independent refused more (15, all Opus); 12 unprompted sabotages in no-side-task runs. Artifact access raises suspicion; CoT can lower it (rationale talks monitor down). Post-training embedded hardest: AUC 0.53-0.71, det. rate 19-44% (art+CoT); optimization embedded AUC 0.92-1.00, det 72-88%; independent attacks "caught reliably" at 50. Sonnet 4.6 scores everything lower (lowest det rate at 50, similar AUC). Typosquat example: traj-only Sonnet hedges 47 ("possible hallucination"), artifact access 88. Failure modes: surface inspection; anomaly noticed then dismissed; wrong probe.
- Limits stated: red team does not strategically hide (detection rates are an upper bound); no adaptive attacker; one fixed threshold 50 (plus AUC); no audit-budget thresholds from benign distribution.
- Relevance: our cell 733 is their CUDA/typosquat independent side task with GLM-5.1 + Sonnet 4.6 M∅ (traj). Ours adds: adaptive proposer, audit-budget thresholds, change 00-10 benchmark fixes (rope guard, evaluator trust, baseline, correctness gate), the 120 s timeout finding. They explicitly name adaptive obfuscation as future work.

## Auditing Sabotage Bench / ASMR-Bench (Gan, Bhatt, Shlegeris, Stastny, Hebbar; arXiv:2604.16286; Redwood)

- Benchmark: 9 real ML research codebases (subliminal learning, CoT monitoring, feature vs lazy, eval-aware steering, two-hop latent reasoning ×2, copy suppression, steganographic collusion, sandbagging detection, multi-turn jailbreaking ×2) with honest + 11 human-made sabotaged variants that flip a key finding while keeping high-level method; sabotage in hyperparameters, data, eval code, paper–code mismatch.
- Protocol: auditor sees paper+codebase, 50% prior; outputs credence (AUROC) + 5 ranked fixes (top-k fix rate, 100/50/0 scoring); codebase-weighted. Affordances: paper only / no experiments / full experiments.
- Models: auditors Claude Opus 4.6 (Claude Code), GPT-5.2 (Codex), Gemini 3.1 Pro (Cursor), 5 trials each; 31 LLM-assisted humans, 72 audits (2 h each). Red team LLMs: Opus 4.6, Gemini 3.1 Pro (could iterate sabotage ideas, not against auditors).
- Findings: best AUROC 0.77 (Gemini 3.1 Pro, full experiments), top-1 fix 42%, top-5 53%; humans AUROC 0.68, top-1 38%; paper-only ≈ chance. Poor calibration; benign distractors main source of false positives. LLM sabotages: AUROC up to 0.80 but easier to fix (top-1 68%); can evade same-capability auditors. Design sabotages (omission!) harder than logic sabotages. Human red-teamer iterating against LLM auditors helped little. Ensembling across auditors suggested (complementary strengths), not tested.
- Relevance: outcome/artifact-level auditing of research; not a monitor-vs-adaptive-search curve; no audit-budget thresholds (AUROC only); red-team search effort not varied systematically.

## Emergent Collusion in Long-Horizon LLM Agent Interaction (Shi, Zhang, Yang; arXiv:2609.24967; Stanford/Georgia Tech)

- Setting: two agents, 50 trajectories × 10 episodes; each episode: solve own task (code analysis / data search / record extraction, 50 instances each), 5 rounds of communication, ACCEPT/REJECT verdict on peer's task, feedback + private reflection; memory across episodes. Verification protocol requires the peer's full raw log; channel limited to 200 chars so the only compliant verdict is REJECT; shared reward for correct verdicts (w=10). No agent instructed to misbehave; no monitor.
- Metrics: mutual ACCEPT = collusion; EC (episode rate), TC (trajectory rate), CC (converged). Onset pathways via LLM judge: explicit coordination (EX), responsive relaxation (RR), simultaneous relaxation (SR).
- Models (10, same-model pairs; reasoning high/xhigh): Gemini-3.1-Flash-Lite, Gemini-3.7-Flash, GPT-5.6-Luna, GPT-5.6-Terra, Claude-Sonnet-4.6, Claude-Opus-4.6, Qwen-3.6-27B, Qwen-3.8-27B, DeepSeek-V4-Flash, Gemma-4-31B.
- Findings: collusion in 93.6% of trajectories (EC 66.0%, CC 78.8%); more capable models within a family collude earlier; Gemini-3.7-Flash EX 90%, GPT-5.6-Luna 0% EX (RR 62.5%). Cross-model pairs fall between same-model rates; scripted violating peer raises ACCEPT 13.6%→41.2%; visible reciprocity 37.0%→55.2%. Ablations: removing cross-episode memory almost eliminates collusion; short memory makes it volatile; separate rewards cut collusion sharply; when ACCEPT itself is the reward collusion drops 72%→0% (violations need a rationale); verdict review feedback matters more than reward.
- Relevance: emergent (unprompted) collusion and an outcome-looks-right failure; "defenses" here are design levers (memory limits, separate rewards), not monitors; no adaptive attacker or audit budgets.

## Not yet read, and needed before the novelty claim is final

MiniLab cites three papers close to our thesis. They are not among the six above, and the claim in PLAN §2 is provisional
until they are read:
- **SLEIGHT-Bench** (Najt, Toft, Tracy, Roger, Benton, 2026, arXiv:2605.16626), "a benchmark of evasion attacks against
  agent monitors". MiniLab's attack-optimisation loop follows it. This is the closest risk to the attacker-search-effort
  axis.
- **Makins, Angelini, Shams, Phuong** (2026, arXiv:2607.07368), "Multi-agent AI control: distributed attacks hamper
  per-instance monitors".
- **Hills, Caspary, Cooper Stickland** (2026, arXiv:2607.02514), "Distributed attacks in persistent-state AI control".
