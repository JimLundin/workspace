"""Small native vector marks for the work feed's application badges."""

from functools import lru_cache

from .feed_origin import App
from .qt import Qt, QtCore, QtGui, QtSvg
from .vector_icons import icon as workspace_icon

_MARKS = {
    App.TEAMS: '<circle cx="17" cy="6" r="3" fill="#b8b5ff"/><circle cx="22" cy="9" r="2" fill="#8f8be5"/>'
               '<rect x="13" y="10" width="10" height="12" rx="4" fill="#8f8be5"/>'
               '<rect x="2" y="6" width="14" height="15" rx="2" fill="#6264ce"/>'
               '<path d="M6 10h6m-3 0v7" stroke="white" stroke-width="2"/>',
    App.OUTLOOK: '<rect x="9" y="4" width="14" height="17" rx="2" fill="#28a8ea"/>'
                '<path d="m10 11 6 5 7-5v11H10z" fill="#0078d4"/>'
                '<rect x="1" y="7" width="13" height="14" rx="2" fill="#106ebe"/>'
                '<ellipse cx="7.5" cy="14" rx="3" ry="4" fill="none" stroke="white" stroke-width="1.8"/>',
    App.CODEX: '<rect x="2" y="3" width="20" height="18" rx="4" fill="#e7edf4"/>'
              '<path d="m6 8 4 4-4 4m7 0h5" fill="none" stroke="#273440" stroke-width="2" stroke-linecap="round"/>',
    App.CLAUDE: '<g stroke="#e4a38b" stroke-width="2.2" stroke-linecap="round">'
               '<path d="M12 2v20M2 12h20M5 5l14 14M5 19 19 5M8 3l8 18M3 8l18 8M3 16l18-8M8 21l8-18"/></g>',
    App.EDGE: '<path d="M22 15a10 10 0 1 1-2-10C12 1 6 8 8 13c3 6 10 6 14 2" fill="#2ac5bb"/>'
              '<path d="M22 15a10 10 0 0 1-18 3c2 1 6 1 7-1-4-6 1-11 6-9 5 2 5 5 5 7" fill="#2585da"/>',
    App.WINDOWS: '<path d="M2 4l9-1v9H2zm11-1 9-1v10h-9zM2 14h9v9l-9-1zm11 0h9v10l-9-1z" fill="#79bafa"/>',
}


@lru_cache(maxsize=16)
def icon(app: App) -> QtGui.QIcon:
    if app is App.WORKSPACE:
        return workspace_icon('agent', '#d7c8ff', 20)
    source = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">' + _MARKS[app] + '</svg>'
    renderer = QtSvg.QSvgRenderer(QtCore.QByteArray(source.encode()))
    pixmap = QtGui.QPixmap(48, 48)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QtGui.QPainter(pixmap)
    renderer.render(painter)
    painter.end()
    pixmap.setDevicePixelRatio(2)
    return QtGui.QIcon(pixmap)
