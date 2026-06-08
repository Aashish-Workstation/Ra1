"""
Tests for Output Engine service.
"""

import pytest

from app.models.output import OutputFormat
from app.services.output_engine import OutputEngineService


@pytest.fixture
def make_output_engine(make_atrs):
    atrs_service, atrs_rows, outbox = make_atrs
    service = OutputEngineService(atrs=atrs_service)
    return service, atrs_rows


@pytest.mark.asyncio
async def test_determine_format_defaults_to_prose(make_output_engine):
    service, atrs_rows = make_output_engine
    fmt = await service.determine_format()
    assert fmt == OutputFormat.PROSE


@pytest.mark.asyncio
async def test_determine_format_respects_spec(make_output_engine):
    service, atrs_rows = make_output_engine
    from app.models.output import OutputSpec
    spec = OutputSpec(requested_format=OutputFormat.MARKDOWN)
    fmt = await service.determine_format(spec)
    assert fmt == OutputFormat.MARKDOWN


@pytest.mark.asyncio
async def test_synthesize_returns_synthesis(make_output_engine):
    service, atrs_rows = make_output_engine
    result = await service.synthesize("Hello world")
    assert result.format == OutputFormat.PROSE
    assert len(result.chunks) == 1


@pytest.mark.asyncio
async def test_synthesize_logs_atrs(make_output_engine):
    service, atrs_rows = make_output_engine
    await service.synthesize("Hello world")
    event_types = [row["event_type"] for row in atrs_rows]
    assert "output.received" in event_types
    assert "output.synthesised" in event_types


@pytest.mark.asyncio
async def test_package_multi_part(make_output_engine):
    service, atrs_rows = make_output_engine
    result = await service.package_multi_part(
        text_block="Explanation text",
        code_blocks=[("python", "print('hello')"), ("javascript", "console.log('hi')")],
        tables=["| a | b |", "| 1 | 2 |"]
    )
    assert result.format == OutputFormat.MIXED
    assert len(result.chunks) == 3