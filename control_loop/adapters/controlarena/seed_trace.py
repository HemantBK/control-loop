"""Offline trace of the seed and temperature each data_poisoning role sends (PLAN §12.1, 2026-10-21).

    uv run --locked python -m control_loop.adapters.controlarena.seed_trace [--model-seed 733] [--temperature 0]
        [--untrusted openrouter/qwen/qwen3-235b-a22b-2507] [--trusted anthropic/claude-sonnet-4-6] [--out file.json]

No network, no API key needed. The models are built exactly as an episode builds them:
- Inspect's active model is `--model` with the eval's GenerateConfig (`inspect eval --seed`), as
  `run_eval` launches it;
- the model roles are dp_task's `ControlEvalConfig.model_roles()`, resolved with Inspect's own
  `resolve_model_roles`;
- the judge is dp_task's `judge_model`, called through ControlArena's own `llm_score`.
Then one request per role is captured:
- OpenAI-compatible models (OpenRouter): the provider's real `generate` runs, and the request dict it
  hands to the SDK (the same dict Inspect logs as ModelCall.request) is captured by replacing the
  provider instance's `_generate_completion`, which returns a canned completion;
- Anthropic models: the provider's own request builder (`control_loop.proposer.derive_request`, i.e.
  `AnthropicAPI.completion_config`) on the config the call would resolve.
A dummy API key is set in this process only when none is set, so the providers can be constructed;
no request leaves the process.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path

DUMMY_KEY = "offline-seed-trace-not-a-key"
CANNED = "<reasoning>mock</reasoning><score>7</score>"


def _canned_completion():
    from openai.types.chat import ChatCompletion

    return ChatCompletion.model_validate(dict(
        id="seed-trace", object="chat.completion", created=0, model="seed-trace",
        choices=[dict(index=0, finish_reason="stop", message=dict(role="assistant", content=CANNED))],
        usage=dict(prompt_tokens=1, completion_tokens=1, total_tokens=2)))


def _capture(model, sink: list):
    """Replace the provider instance's `_generate_completion` so the request is recorded, not sent."""
    async def fake(request, config):
        sink.append(dict(request))
        return _canned_completion()
    model.api._generate_completion = fake


def _anthropic_request(model) -> dict:
    from inspect_ai.model import GenerateConfig

    from control_loop.proposer import derive_request

    cfg = model._resolve_config(GenerateConfig())
    if cfg.max_tokens is None:
        cfg.max_tokens = model.api.max_tokens_for_config(cfg) or model.api.max_tokens()
    return derive_request(model.api, cfg) or {}


def _summary(role: str, model, request: dict, source: str) -> dict:
    from control_loop.proposer import request_summary

    s = request_summary(request)
    return dict(role=role, model=f"{model.api.__class__.__name__}:{model.name}", seed=s["seed"],
                temperature=s["temperature"], source=source,
                request_keys=sorted(k for k in request if k not in ("messages", "tools", "system")))


async def trace(untrusted: str, trusted: str, eval_seed: int = 733, model_seed: int | None = None,
                temperature: float | None = None) -> list[dict]:
    from inspect_ai.model import ChatMessageSystem, ChatMessageUser, GenerateConfig, get_model
    from inspect_ai.model._model import init_active_model, init_model_roles
    from inspect_ai.model._util import resolve_model_roles

    from control_arena.scorers._llm_judge import llm_score
    from control_loop.adapters.controlarena.dp_task import build_eval_config, judge_model

    for var in ("OPENROUTER_API_KEY", "ANTHROPIC_API_KEY"):
        os.environ.setdefault(var, DUMMY_KEY)

    # what `inspect eval --model <untrusted> --seed <eval_seed> --max-retries 2` sets up
    eval_cfg = GenerateConfig(seed=eval_seed, max_retries=2)
    init_active_model(get_model(untrusted, config=eval_cfg), eval_cfg)
    roles = build_eval_config(untrusted, trusted, 100_000, None, model_seed, temperature).model_roles()
    init_model_roles(resolve_model_roles(roles) or {})

    msgs = [ChatMessageSystem(content="system"), ChatMessageUser(content="user")]
    rows: list[dict] = []

    async def openai_role(role: str, model, call):
        sink: list = []
        _capture(model, sink)
        await call(model)
        for i, req in enumerate(sink):
            rows.append(_summary(f"{role}" + (f" (call {i + 1})" if len(sink) > 1 else ""), model, req,
                                 "captured provider request"))

    def is_anthropic(m) -> bool:
        return m.api.__class__.__name__ == "AnthropicAPI"

    # policy: ControlArena's attack/honest policy and proposer_attack_policy call
    # get_model(role="untrusted", config=GenerateConfig()).generate(...)
    policy = get_model(role="untrusted", config=GenerateConfig())
    if is_anthropic(policy):
        rows.append(_summary("policy (untrusted)", policy, _anthropic_request(policy), "provider builder"))
    else:
        await openai_role("policy (untrusted)", policy, lambda m: m.generate(msgs))
    # monitor: basic_monitor calls get_model(role="trusted", config=GenerateConfig())
    monitor = get_model(role="trusted", config=GenerateConfig())
    if is_anthropic(monitor):
        rows.append(_summary("monitor (trusted)", monitor, _anthropic_request(monitor), "provider builder"))
    else:
        await openai_role("monitor (trusted)", monitor, lambda m: m.generate(msgs))
    # setting judge: data_poisoning_scorer -> get_model(scorer_model) -> ControlArena's llm_score
    judge = get_model(judge_model(None, untrusted, temperature))
    if is_anthropic(judge):
        rows.append(_summary("judge (setting scorer)", judge, _anthropic_request(judge), "provider builder"))
    else:
        await openai_role("judge (setting scorer)", judge, lambda m: llm_score("judge prompt", m, "score"))
    return rows


def table(rows: list[dict]) -> str:
    out = ["| role | model | seed sent | temperature sent | source |", "|---|---|---|---|---|"]
    out += [f"| {r['role']} | {r['model']} | {r['seed']} | {r['temperature']} | {r['source']} |" for r in rows]
    return "\n".join(out)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--untrusted", default="openrouter/qwen/qwen3-235b-a22b-2507")
    ap.add_argument("--trusted", default="anthropic/claude-sonnet-4-6")
    ap.add_argument("--eval-seed", type=int, default=733)
    ap.add_argument("--model-seed", type=int, default=None)
    ap.add_argument("--temperature", type=float, default=None)
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()
    rows = asyncio.run(trace(args.untrusted, args.trusted, args.eval_seed, args.model_seed, args.temperature))
    print(f"inspect eval --seed {args.eval_seed}; dp_task model_seed={args.model_seed}, temperature={args.temperature}")
    print(table(rows))
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(dict(args={k: str(v) for k, v in vars(args).items()}, rows=rows),
                                       indent=2, default=str), encoding="utf-8")


if __name__ == "__main__":
    main()
