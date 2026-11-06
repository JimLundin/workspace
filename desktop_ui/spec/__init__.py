"""The desktop's UI as data: one frozen value per module, which Workspace reloads while it runs.

Edit a value and save: the bar re-lays itself out (`sizes`, `controls`, `island`),
and the tray menu (`tray`) and canvas toolbar (`canvas`) show the edit the next time
they open. Nothing restarts. A spec that doesn't import or check is reported and
the previous one stays. Pyright checks every name and shape here; see `ui_spec`.
"""
