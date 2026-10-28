"""Optional local temperature, refreshed off the UI thread and expired on failure."""

import json
import queue
import threading
from contextlib import suppress
from typing import cast

import httpx

from .ambient import Weather


def weather_response(raw: object) -> Weather:
    if not isinstance(raw, dict):
        raise ValueError("Weather response must be an object.")
    current: object = cast(dict[str, object], raw).get("current")
    if not isinstance(current, dict):
        raise ValueError("Missing current weather.")
    values = cast(dict[str, object], current)
    temperature, code, day = values.get("temperature_2m"), values.get("weather_code"), values.get("is_day")
    if (type(temperature) not in (int, float) or type(code) is not int or type(day) is not int or day not in (0, 1)):
        raise ValueError("Invalid weather fields.")
    return Weather(float(cast(float, temperature)), code, day == 1)


class LocalWeather:
    __slots__ = ("cancelled", "results", "worker")

    def __init__(self) -> None:
        self.cancelled = threading.Event()
        self.results: queue.Queue[Weather | None] = queue.Queue(maxsize=1)
        self.worker = threading.Thread(target=self.run, name="toolbar weather", daemon=True)
        self.worker.start()

    def run(self) -> None:
        from winapi.ambient import location  # noqa: PLC0415

        while not self.cancelled.is_set():
            observed = None
            try:
                coordinates = location(self.cancelled)
                if coordinates is not None and not self.cancelled.is_set():
                    # Coarse coordinates suffice for temperature without sending a precise location.
                    latitude, longitude = (round(value, 1) for value in coordinates)
                    with httpx.Client(timeout=5, follow_redirects=True) as client:
                        response = client.get("https://api.open-meteo.com/v1/forecast", params={
                            "latitude": latitude, "longitude": longitude,
                            "current": "temperature_2m,weather_code,is_day", "temperature_unit": "celsius",
                        })
                        response.raise_for_status()
                        raw: object = json.loads(response.text)
                        observed = weather_response(raw)
            except (OSError, ValueError, httpx.HTTPError):
                pass
            if self.cancelled.is_set():
                return
            with suppress(queue.Empty):
                self.results.get_nowait()
            self.results.put_nowait(observed)
            # Retry missing location quietly; successful weather refreshes every fifteen minutes.
            self.cancelled.wait(900 if observed is not None else 300)

    def close(self) -> None:
        self.cancelled.set()
        self.worker.join(timeout=.1)
