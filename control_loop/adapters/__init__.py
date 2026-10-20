"""Framework adapters: the only place that knows how a particular benchmark framework runs an
episode and where its logs come from. The loop, the proposer and the analysis import from here,
never from the framework directly. See README.md in this directory for the interface and
`control_loop/adapters/orbit/` for the one adapter that exists (ORBIT 1.0.3, JiraTicket).
"""
