from __future__ import annotations

import pytest

from agent_os.agents.verifier import VerifierAgent


@pytest.mark.asyncio
async def test_good_gif_passes(gif_ok):
    verdict = await VerifierAgent().run({"gif": gif_ok})
    assert verdict.ok is True
    assert verdict.should_repair is False


@pytest.mark.asyncio
async def test_failed_steps_trigger_repair(gif_broken):
    verdict = await VerifierAgent().run({"gif": gif_broken})
    assert verdict.ok is False
    assert verdict.should_repair is True
    assert "2 paso(s)" in verdict.reason


@pytest.mark.asyncio
async def test_short_gif_triggers_repair(gif_ok):
    gif_ok["verification"]["duration"] = 1.9
    verdict = await VerifierAgent().run({"gif": gif_ok})
    assert verdict.should_repair is True
    assert "corto" in verdict.reason


@pytest.mark.asyncio
async def test_ffprobe_not_ok_triggers_repair(gif_ok):
    gif_ok["verification"]["ok"] = False
    verdict = await VerifierAgent().run({"gif": gif_ok})
    assert verdict.should_repair is True
    assert "ffprobe" in verdict.reason
