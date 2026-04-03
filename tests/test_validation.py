"""Tests for §4: Pydantic validation error handling."""

import pytest
from pydantic import BaseModel
from fastapi.params import Depends

from fastapi_sio_di.dependencies import (
    Dependant,
    LifespanContext,
    solve_dependant,
)
from fastapi_sio_di.exceptions import SocketIOValidationError


class StrictModel(BaseModel):
    name: str
    age: int


async def run_handler(handler, make_cache, **cache_kwargs):
    dependant = Dependant(handler)
    cache = make_cache(**cache_kwargs)
    async with LifespanContext() as context:
        return await solve_dependant(dependant, context, cache)


class TestValidationError:
    @pytest.mark.asyncio
    async def test_invalid_data_raises_validation_error(self, make_cache):
        async def handler(data: StrictModel):
            return data

        with pytest.raises(SocketIOValidationError):
            await run_handler(
                handler,
                make_cache,
                data={"name": "test", "age": "not_a_number"},
                args=({"name": "test", "age": "not_a_number"},),
            )

    @pytest.mark.asyncio
    async def test_validation_error_contains_details(self, make_cache):
        async def handler(data: StrictModel):
            return data

        with pytest.raises(SocketIOValidationError) as exc_info:
            await run_handler(
                handler,
                make_cache,
                data={"name": 123},  # missing age, name wrong type is ok for pydantic
                args=({"name": 123},),
            )

        err = exc_info.value
        assert err.model_name == "StrictModel"
        assert isinstance(err.errors, list)
        assert len(err.errors) > 0

    @pytest.mark.asyncio
    async def test_valid_data_no_error(self, make_cache):
        async def handler(data: StrictModel):
            return data

        result = await run_handler(
            handler,
            make_cache,
            data={"name": "test", "age": 25},
            args=({"name": "test", "age": 25},),
        )
        assert isinstance(result, StrictModel)
        assert result.name == "test"
        assert result.age == 25
