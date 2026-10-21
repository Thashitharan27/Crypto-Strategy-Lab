"""Release native test windows while Python/Qt wrappers are still alive."""
import gc
import sys


def pytest_sessionfinish(session, exitstatus):
    # GUI tests often create windows outside qtbot's ownership. Leaving those
    # windows until interpreter finalization makes PySide destroy large object
    # graphs after their Python callbacks/module globals have been dismantled.
    # Do not create/import a Qt application for suites that never used one.
    if "PySide6.QtWidgets" not in sys.modules:
        return
    from PySide6.QtCore import QCoreApplication, QEvent
    from PySide6.QtWidgets import QApplication
    from shiboken6 import delete, isValid

    app = QApplication.instance()
    if app is None:
        return
    for window in app.topLevelWidgets():
        if isValid(window):
            window.close()
            if isValid(window):
                window.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()
    gc.collect()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()
    # PySide's implicit application destruction also runs too late in Python
    # finalization. Invalidate its wrappers explicitly while modules are live.
    delete(app)
    gc.collect()
