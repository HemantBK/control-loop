# Citation check for the introduction and related work (2026-10-28)

Each entry was checked on 2026-10-28 against a primary record:
- a Crossref DOI record (api.crossref.org);
- an arXiv API record (export.arxiv.org), which gives the full author list;
- or the publisher or venue page.

For the arXiv entries, the claim made in the draft was also checked against the abstract. Nothing is cited from memory
alone.

## Security and adversarial ML
| citation | checked against | identifier |
|---|---|---|
| Dalvi et al., Adversarial classification, KDD 2004 | Crossref | doi:10.1145/1014052.1014066 |
| Lowd & Meek, Adversarial learning, KDD 2005 | Crossref | doi:10.1145/1081870.1081950 |
| Lowd & Meek, Good word attacks on statistical spam filters, CEAS 2005 | paper full text (personal.utdallas.edu copy); Virus Bulletin, Feb 2006, "Does Bayesian poisoning exist?" | no DOI (CEAS) |
| Barreno et al., Can machine learning be secure?, ASIACCS 2006 | Crossref | doi:10.1145/1128817.1128824 |
| Nelson et al., Query strategies for evading convex-inducing classifiers, JMLR 13 (2012) 1293–1332 | jmlr.org/papers/v13/nelson12a.html; arXiv:1007.0484 | JMLR v13 |
| Biggio et al., Evasion attacks against ML at test time, ECML PKDD 2013 | mlanthology.org listing; arXiv:1708.06131 | doi:10.1007/978-3-642-40994-3_25 |
| Šrndić & Laskov, Practical evasion of a learning-based classifier, IEEE S&P 2014 | Crossref | doi:10.1109/sp.2014.20 |
| Graziano et al., Needles in a haystack, USENIX Security 2015 | usenix.org presentation page | USENIX Sec '15, pp. 1057–1072 |
| Xu, Qi, Evans, Automatically evading classifiers, NDSS 2016 | Crossref | doi:10.14722/ndss.2016.23115 |
| Tramèr et al., Stealing ML models via prediction APIs, USENIX Security 2016 | arXiv:1609.02943 (comment: USENIX Security 2016; 5 authors) | arXiv:1609.02943 |
| Papernot et al., Practical black-box attacks, AsiaCCS 2017 | Crossref + arXiv:1602.02697 (6 authors) | doi:10.1145/3052973.3053009 |
| Chen et al., ZOO, AISec 2017 | Crossref + arXiv:1708.03999 | doi:10.1145/3128572.3140448 |
| Dang, Huang, Chang, Evading classifiers by morphing in the dark, CCS 2017 | Crossref | doi:10.1145/3133956.3133978 |
| Brendel, Rauber, Bethge, Decision-based adversarial attacks, ICLR 2018 | arXiv:1712.04248 (comment: ICLR 2018) | arXiv:1712.04248 |
| Ilyas et al., Black-box adversarial attacks with limited queries and information, ICML 2018 | arXiv:1804.08598 (comment: ICML 2018) | arXiv:1804.08598 |
| Anderson et al., Learning to evade static PE malware models via RL, 2018 | arXiv:1801.08917 (5 authors) | arXiv:1801.08917 |
| Biggio & Roli, Wild patterns, Pattern Recognition 2018 | Crossref | doi:10.1016/j.patcog.2018.07.023 |
| Orekondy, Schiele, Fritz, Prediction poisoning, ICLR 2020 | arXiv:1906.10908 (comment: ICLR 2020) | arXiv:1906.10908 |
| Chen, Jordan, Wainwright, HopSkipJumpAttack, IEEE S&P 2020 | Crossref | doi:10.1109/sp40000.2020.00045 |
| Chen, Carlini, Wagner, Stateful detection of black-box adversarial attacks, SPAI 2020 | Crossref + arXiv:1907.05587 | doi:10.1145/3385003.3410925 |
| Le Merrer, Morgan, Trédan, Setting the record straighter on shadow banning, INFOCOM 2021 | Crossref | doi:10.1109/infocom42981.2021.9488792 |
| Qin et al., Random noise defense against query-based black-box attacks, NeurIPS 2021 | arXiv:2104.11470 (comment: NeurIPS 2021) | arXiv:2104.11470 |
| Li et al., Blacklight, USENIX Security 2022 | usenix.org presentation page; arXiv:2006.14042 | USENIX Sec '22, pp. 2117–2134 |
| Stripe, How Stripe responded to a wave of card testing attacks (2022) | stripe.com newsroom page (industry source, described as such) | stripe.com/newsroom/news/card-testing-surge |

**Not cited, because no primary source was found:** that game anti-cheat systems delay bans to deny cheat developers
feedback. Only community forum posts were found, and no official Valve statement.

## AI control
Every arXiv ID was resolved on 2026-10-27 or 2026-10-28 through the arXiv API, with the title and first author matching.
- **Abstracts read for the claims made in the draft:**
  - 2605.26047 (Lucassen, Kaufman)
  - 2610.26935 (Saeedi, Aghazadeh)
  - 2609.24967 (Shi, Zhang, Yang)
  - 2610.24052
  - 2610.27735
  - 2605.09684
  - 2607.07368
  - 2605.29178
  - 2606.06529
- **IDs resolved:**
  - 2312.06942
  - 2504.10374
  - 2506.15740
  - 2510.09462
  - 2602.04930
  - 2605.16626
  - 2607.19321

**Checked in the body:** Kitaoka et al.'s statement that feedback components are not isolated. The arXiv HTML of
2610.24052v1, in the caption of its feedback-planning figure, says the tool "returns task results and trajectories along
with Luna feedback, so this experiment does not isolate which part of the feedback causes a plan to improve".

## Added after council checkpoint 1 (2026-10-28)
| citation | checked against | what was confirmed |
|---|---|---|
| Keenan, Leckie, Erfani, arXiv:2609.36490 | arXiv API abstract | "each verdict the monitor delivers leaks information"; latent-monitor evasion from verdict feedback |
| Hopman, Lemoine, Tracy, LessWrong post wKGdiXuWfn8YoYpMQ | LessWrong GraphQL API (author, coauthors, postedAt 2025-05-27); post summary | safety 93% to 80%; compliance monitoring and selective editing did not restore the baseline |
| Lucassen & Kaufman, arXiv:2605.26047v1 | arXiv HTML body, main findings list | detailed feedback exploitable; retrying without feedback harder to exploit directly, may be vulnerable to attack selection; resampling not exploitable |
| Kutasov et al., arXiv:2511.02997 | arXiv API abstract (7 authors) | attack policies aware of resampling or able to simulate monitors cut safety to 17%; deferring on critical actions robust |
| Remedios, Storf, Roger, Hughes, arXiv:2609.19587 | arXiv API abstract | production blocking monitors (Auto Mode, Guardian); injection succeeds in 79% of trials |
| MonitoringBench reconnaissance arm without monitor tools | reported by three council members from H.1.3; not re-read by me | described in the draft with the council's caveat on confounded affordances; to be read before submission |

## Added for Amendment (3) (2026-10-28)
| citation | checked against | what was confirmed |
|---|---|---|
| Blackwell, Comparison of experiments, Proc. Second Berkeley Symposium (1951) 93–102 | Crossref | doi:10.1525/9780520411586-009 |
| Blackwell, Equivalent comparisons of experiments, Ann. Math. Statist. 24 (1953) 265–272 | Crossref | doi:10.1214/aoms/1177729032 |
| Hartley & David, Universal bounds for mean range and extreme observation, Ann. Math. Statist. 25 (1954) 85–99 | Crossref | doi:10.1214/aoms/1177728848 |
| Gumbel, The maxima of the mean largest value and of the range, Ann. Math. Statist. 25 (1954) 76–84 | Crossref | doi:10.1214/aoms/1177728847 |
| Xu, Zhao, Song, Stewart, Ermon, A theory of usable information under computational constraints, ICLR 2020 | arXiv API (5 authors; comment "ICLR 2020 (Talk)") | arXiv:2002.10689 |
| Pinsker's inequality | textbook (Cover & Thomas, Elements of Information Theory, 2nd ed., Lemma 11.6.1) | not a paper citation |

**Selection-protocol table (A3.4).** Each quote was confirmed by an exact string search of the plain text extracted from
the arXiv HTML on 2026-10-28:
- Terekhov et al. 2510.09462v2, §3.4;
- MiniLab 2610.24052v1, §4.3 and App. G;
- SLEIGHT-Bench 2605.16626, §3.2 and §5.1;
- Lucassen & Kaufman 2605.26047v1, §4.2, App. E and App. G;
- Kutasov et al. 2511.02997, §4 and App. E.

The windows are kept with checkpoint council 1b's packet (`lit_excerpts.md`, outside the repository). "Not stated" in
the table means a full read found no statement.

**Superseded:** the A3.4 table was replaced by the affordance audit in Amendment (4), A4.2. Its quotes are the ones checked above, plus Terekhov §1, "knows the protocol and the monitor model", confirmed by the same string search.
