import os
import sys
from .qt import QtGui, QtWidgets, QtCore, Qt
import matplotlib.pyplot as plt
from .widgets import QJupyterWidget, MetaWidget, DataSetBrowser, DataSetPlotter
from .utils import load_json_ordered
import warnings

warnings.filterwarnings("ignore", message="The unit of the quantity is stripped")
warnings.filterwarnings("ignore", message="tight_layout")
warnings.filterwarnings("ignore", message="Tight layout not applied.")
warnings.filterwarnings("ignore", message="All-NaN slice encountered")
warnings.filterwarnings("ignore", message="All-NaN axis encountered")
warnings.filterwarnings(
    "ignore", message="Attempting to set identical bottom==top results"
)
warnings.filterwarnings("ignore", message="invalid value encountered in less")


class MainWindow(QtWidgets.QMainWindow):
    """Main window for scanning-squid-analysis gui."""

    def __init__(self):
        super().__init__()
        self.dataset = None
        self.setWindowTitle("ssm_analyze")
        self.shell = QJupyterWidget()
        self.station_snap = MetaWidget()
        self.measurement_meta = MetaWidget()
        self.dataset_browser = DataSetBrowser()
        self.dataset_browser.dataset_selector.clicked.connect(self.load_dataset)
        self.dataset_plotter = DataSetPlotter()
        self.dataset_browser.dataset_selector.clicked.connect(self.update_dataset_plot)

        import numpy

        self.shell.push_variables({"np": numpy, "plt": plt})

        self.file_menu = self.menuBar().addMenu("File")
        self.plot_menu = self.menuBar().addMenu("Plot")
        self.view_menu = self.menuBar().addMenu("View")

        self.dataset_dock = self.add_dock(
            self.dataset_browser, "DataSet Browser", "Left"
        )
        self.snapshot_dock = self.add_dock(
            self.station_snap, "Microscope Snapshot", "Left"
        )
        self.meta_dock = self.add_dock(
            self.measurement_meta, "Measurement Metadata", "Left"
        )
        self.shell_dock = self.add_dock(self.shell, "Shell", "Left")
        self.plotter_dock = self.add_dock(
            self.dataset_plotter, "DataSet Plotter", "Right"
        )
        self.tabifyDockWidget(self.snapshot_dock, self.meta_dock)

        self.plot_menu.addAction(
            "Export matplotlib...",
            self.dataset_plotter.export_mpl,
            QtGui.QKeySequence("Ctrl+P"),
        )
        # removing this feature due to a bug in pyqtgraph
        # see: https://github.com/pyqtgraph/pyqtgraph/issues/538
        # self.plot_menu.addAction('Export pyqtgraph...', self.dataset_plotter.export_qt,
        #                             QtGui.QKeySequence('Ctrl+Shift+P'))
        self.file_menu.addAction(
            "Select directory...",
            self.dataset_browser.select_from_dialog,
            QtGui.QKeySequence("Ctrl+O"),
        )
        self.file_menu.addAction(
            "Export current data...",
            self.dataset_plotter.export_data,
            QtGui.QKeySequence("Ctrl+S"),
        )

    def add_dock(self, widget, name, location, min_width=None):
        """Add a QDockWidget to the main window.
        Args:
            widget (QWidget): Widget to add to dock.
            name (str): Name to give dock.
            location (str): Where to put dock, in ('Left', 'Right', 'Top', 'Bottom').
            min_width (optional, int): Minimum width of the dock. Default: None.
        """
        dock = QtWidgets.QDockWidget(name)
        dock.setWidget(widget)
        self.view_menu.addAction(dock.toggleViewAction())
        loc_const = getattr(Qt, f"{location}DockWidgetArea")
        self.addDockWidget(loc_const, dock)
        if min_width is not None:
            dock.setMinimumWidth(min_width)
        return dock

    def load_dataset(self):
        """Get dataset selected in self.dataset_browser."""
        dataset = self.dataset_browser.get_dataset()
        if "snapshot.json" not in os.listdir(dataset.location):
            return
        path = os.path.join(dataset.location, "snapshot.json")
        meta = load_json_ordered(path)
        snap = meta.pop("station")
        self.station_snap.load_meta(data=snap)
        self.measurement_meta.load_meta(data=meta)
        self.dataset = dataset
        self.shell.push_variables({"dataset": self.dataset})

    def update_dataset_plot(self):
        """Get dataset and update plot."""
        self.load_dataset()
        if isinstance(self.dataset, str):
            self.dataset_plotter.update(self.dataset)
            return
        if self.dataset is None or "snapshot.json" not in os.listdir(
            self.dataset.location
        ):
            return
        self.dataset_plotter.update(self.dataset)
        self.shell.push_variables({"arrays": self.dataset_plotter.arrays})


def main():
    icon_path = os.path.join(os.path.dirname(__file__), "img", "icon.png")
    app = QtWidgets.QApplication([])
    app.setWindowIcon(QtGui.QIcon(icon_path))
    win = MainWindow()
    win.showMaximized()
    app.lastWindowClosed.connect(sys.exit)
    app.exec_()


if __name__ == "__main__":
    main()
