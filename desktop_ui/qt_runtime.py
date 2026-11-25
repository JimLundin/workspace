import concurrent.futures

import pydantic


def prepare() -> None:
    _executor = concurrent.futures.ThreadPoolExecutor
    _validation = (
        pydantic.BeforeValidator,
        pydantic.ConfigDict,
        pydantic.Field,
        pydantic.TypeAdapter,
        pydantic.ValidationError,
    )
