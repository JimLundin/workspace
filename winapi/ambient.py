"""Windows power observations."""

lazy from win32more.Windows.Win32.System.Power import SYSTEM_POWER_STATUS, GetSystemPowerStatus

from winapi.machine_status import Battery, Power, PowerUnavailable


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
    return Battery(int(status.BatteryLifePercent), powered=status.ACLineStatus == 1, charging=bool(status.BatteryFlag & 8))
