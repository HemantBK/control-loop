"""No-API tests for the proposer's request log (audit_codex X8, 2026-10-21). Providers are built with
object.__new__ (no client, no network), as in X8's snippet; the proposer's generate call is replaced by
a fake model. What is checked against Inspect 0.3.263's own provider code:
  anthropic.py AnthropicAPI.completion_config  -> no seed, temperature dropped for Claude 4.7+
  openai_completions.py completion_params_completions (via _openai.openai_completion_params)
                                               -> gpt-4o gets seed and temperature."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from inspect_ai.model import GenerateConfig, ModelOutput
from inspect_ai.model._providers.anthropic import AnthropicAPI
from inspect_ai.model._providers.openai import OpenAIAPI

from control_loop import proposer as P

REPO = Path(__file__).resolve().parents[1]
SEED = 73301
PAYLOAD = "dev_0 and dev_1 together claim the two highest-priority tickets first, before anyone else."


def anthropic_api(name: str) -> AnthropicAPI:
    x = object.__new__(AnthropicAPI)
    x.model_name, x.service, x.betas = name, "anthropic", []
    return x


def openai_api(name: str) -> OpenAIAPI:
    x = object.__new__(OpenAIAPI)
    x.model_name, x.service, x.service_tier, x.responses_api = name, None, None, False
    return x


def requested(max_tokens: int = 32000) -> GenerateConfig:
    return GenerateConfig(max_tokens=max_tokens, temperature=0, seed=SEED)


@pytest.mark.parametrize("name", ["claude-sonnet-5-5", "claude-opus-5-5"])
def test_anthropic_claude5_sends_neither_seed_nor_temperature(name):
    sent = P.request_summary(P.derive_request(anthropic_api(name), requested()))
    assert sent["model"] == name
    assert sent["seed"] == P.NOT_SENT
    assert sent["temperature"] == P.NOT_SENT
    assert sent["max_tokens"] == 32000
    assert sent["thinking"] == P.NOT_SENT  # nothing explicit; Claude 5 runs adaptive thinking by default


def test_anthropic_sonnet46_sends_temperature_not_seed():
    # Phase 4's trusted model: pre-4.7, so temperature goes through extra_body; seed never does
    sent = P.request_summary(P.derive_request(anthropic_api("claude-sonnet-4-6"), requested()))
    assert sent["temperature"] == 0
    assert sent["seed"] == P.NOT_SENT


def test_openai_gpt4o_sends_seed_and_temperature():
    api = openai_api("gpt-4o")
    assert not (api.is_o_series() or api.is_codex() or api.is_gpt_5())  # chat-completions path by default
    sent = P.request_summary(P.derive_request(api, requested(4096)))
    assert sent == dict(model="gpt-4o", temperature=0, seed=SEED, max_tokens=4096,
                        thinking=P.NOT_SENT, output_config=P.NOT_SENT)


class FakeModel:
    """Stands in for inspect_ai's Model: real provider object, no client; optionally records a
    ModelEvent with a ModelCall in the transcript the way Inspect's providers do."""

    def __init__(self, api, config: GenerateConfig | None, emit_call: bool):
        self.api, self.config, self.emit_call = api, config or GenerateConfig(), emit_call

    async def generate(self, messages):
        if self.emit_call:
            from inspect_ai.event import ModelEvent
            from inspect_ai.log import transcript
            from inspect_ai.model._model_call import ModelCall

            cfg = self.config.model_copy()
            cfg.max_tokens = cfg.max_tokens or 4096
            request = dict(messages=[{"role": "user", "content": "x"}]) | P.derive_request(self.api, cfg)
            transcript()._event(ModelEvent(model="fake", input=[], tools=[], tool_choice="none", config=cfg,
                                           output=ModelOutput.from_content("fake", ""),
                                           call=ModelCall.create(request, None)))
        return ModelOutput.from_content("fake", json.dumps({"moves": ["pre_split"], "payload": PAYLOAD}))


def run_propose(monkeypatch, tmp_path: Path, api, emit_call: bool) -> tuple[dict, dict, str]:
    import inspect_ai.model as im

    monkeypatch.setattr(im, "get_model", lambda name, config=None: FakeModel(api, config, emit_call))
    history = [dict(round=0, payload="static", gain=0.0, channel_sends=0)]
    out = asyncio.run(P.propose("x/" + api.model_name, history, 1, tmp_path / "rejections.jsonl",
                                proposer_seed=SEED))
    text = (tmp_path / "proposer_log.jsonl").read_text(encoding="utf-8")
    return out, json.loads(text.splitlines()[-1]), text


def test_propose_logs_not_sent_for_sonnet55(monkeypatch, tmp_path):
    out, line, text = run_propose(monkeypatch, tmp_path, anthropic_api("claude-sonnet-5-5"), emit_call=False)
    assert out["payload"] == PAYLOAD                       # behaviour unchanged
    assert line["requested_seed"] == SEED and line["requested_temperature"] == 0
    assert line["sent"]["seed"] == P.NOT_SENT and line["sent"]["temperature"] == P.NOT_SENT
    assert line["sent"]["model"] == "claude-sonnet-5-5" and line["sent"]["max_tokens"] == 32000
    assert line["sent_source"] == P.SOURCE_DERIVED         # no ModelCall from the fake model
    assert "seed" not in line and "temperature" not in line  # no bare keys that read as effective
    assert out["requested_seed"] == SEED and out["sent_seed"] == P.NOT_SENT
    assert out["sent_temperature"] == P.NOT_SENT and "proposer_seed" not in out
    assert "seeded" not in text.lower() and "t=0" not in text.lower()


def test_propose_prefers_the_recorded_model_call(monkeypatch, tmp_path):
    out, line, _ = run_propose(monkeypatch, tmp_path, openai_api("gpt-4o"), emit_call=True)
    assert line["sent_source"] == P.SOURCE_MODEL_CALL
    assert line["sent"]["seed"] == SEED and line["sent"]["temperature"] == 0
    assert line["requested_seed"] == SEED and line["requested_temperature"] == 0
    assert out["sent_seed"] == SEED


def test_phase4_logs_carry_no_seed():
    """The Phase 4 reproduction logs, read locally: no Opus 5.5 / Sonnet 4.6 request carried a seed."""
    logs = sorted((REPO / "results" / "phase4_controlarena" / "repro_limit3").glob("*/*.eval"))
    if not logs:
        pytest.skip("Phase 4 logs absent")
    from control_loop.adapters.controlarena import sent_settings

    for log in logs:
        settings = sent_settings(log)
        assert settings and all(r["seed"] == [P.NOT_SENT] for r in settings.values())
