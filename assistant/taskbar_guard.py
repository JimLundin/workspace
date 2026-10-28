"""Restore Windows taskbars even if Workspace's entire job is terminated."""

import sys


def main() -> None:
    from winapi.desktop_shell import taskbar_visible, taskbars, wait_for_exit  # noqa: PLC0415

    wait_for_exit(int(sys.argv[1]), lambda: print("ready", flush=True))
    for handle in taskbars():
        taskbar_visible(handle, show=True)


if __name__ == "__main__":
    main()
