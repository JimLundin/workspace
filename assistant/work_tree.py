"""Qt tree observations and row updates shared by the native work views."""

from collections.abc import Sequence

lazy from PySide6 import QtWidgets
lazy from PySide6.QtCore import Qt


def tree(title: str) -> QtWidgets.QTreeWidget:
    tree = QtWidgets.QTreeWidget()
    tree.setHeaderLabels(["Name", title])
    tree.setRootIsDecorated(False)
    tree.setAlternatingRowColors(False)
    tree.setColumnWidth(0, 230)
    tree.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.SingleSelection)
    tree.setAccessibleName(title)
    return tree


def item_identity(item: QtWidgets.QTreeWidgetItem) -> str | None:
    value: object = item.data(0, Qt.ItemDataRole.UserRole)
    return value if isinstance(value, str) else None


def selected_identity(tree: QtWidgets.QTreeWidget) -> str | None:
    item = tree.currentItem()
    return item_identity(item) if item is not None else None


def rows(tree: QtWidgets.QTreeWidget, rows: Sequence[tuple[str, str, tuple[str, ...]]]) -> None:
    selected, scroll = selected_identity(tree), tree.verticalScrollBar().value()
    previous = {item_identity(item): item for i in range(tree.topLevelItemCount()) if (item := tree.topLevelItem(i)) is not None}
    tree.blockSignals(True)
    try:
        wanted = {identity for identity, _, _ in rows}
        for identity, item in previous.items():
            if identity not in wanted:
                tree.takeTopLevelItem(tree.indexOfTopLevelItem(item))
        for index, (identity, title, values) in enumerate(rows):
            item = previous.get(identity)
            if item is None:
                item = QtWidgets.QTreeWidgetItem()
                item.setData(0, Qt.ItemDataRole.UserRole, identity)
            else:
                tree.takeTopLevelItem(tree.indexOfTopLevelItem(item))
            for column_index, text in enumerate((title, *values)):
                item.setText(column_index, text)
            tree.insertTopLevelItem(index, item)
            if identity == selected or (selected not in wanted and index == 0):
                tree.setCurrentItem(item)
        tree.verticalScrollBar().setValue(scroll)
    finally:
        tree.blockSignals(False)
