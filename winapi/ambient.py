"""Windows power observations."""

from typing import Final

lazy from win32more.Windows.Win32.System.Power import SYSTEM_POWER_STATUS, GetSystemPowerStatus

from winapi.machine_status import Battery, Power, PowerUnavailable

UNKNOWN_LIFETIME: Final = 0xFFFFFFFF


def power() -> Power:
    status = SYSTEM_POWER_STATUS()
    return power_from_status(status if GetSystemPowerStatus(status) else None)


def power_from_status(status: SYSTEM_POWER_STATUS | None) -> Power:
    """Validate one native observation before publishing the toolbar's power state."""
    if status is None or status.BatteryFlag == 255:
        return PowerUnavailable.UNKNOWN
    if status.BatteryFlag & 128:
        return PowerUnavailable.NO_BATTERY
    if not 0 <= status.BatteryLifePercent <= 100:
        return PowerUnavailable.UNKNOWN
    powered = status.ACLineStatus == 1
    # Windows reports an unknown estimate as all ones, and none at all on mains power.
    remaining = None if powered or status.BatteryLifeTime >= UNKNOWN_LIFETIME else int(status.BatteryLifeTime)
    return Battery(int(status.BatteryLifePercent), powered=powered, charging=bool(status.BatteryFlag & 8), remaining=remaining)
