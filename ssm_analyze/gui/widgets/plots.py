import pickle
from typing import Callable, NamedTuple, Optional

import h5py
import matplotlib.pyplot as plt
import numpy as np
import pyqtgraph as pg
from matplotlib import cm, colors, transforms
from matplotlib.collections import LineCollection
from matplotlib.figure import Figure
from matplotlib.widgets import Slider
from scipy.io import savemat
from scipy.linalg import lstsq
from scipy.ndimage.interpolation import rotate

from ..qt import FigureCanvasQTAgg, NavigationToolbar2QT, Qt, QtCore, QtWidgets
from ..utils import scan_to_arrays, set_h5_attrs, td_to_arrays
from .sliders import SliderWidget, VertSlider

mpl_cmaps = sorted(plt.colormaps())
qt_cmaps = (
    "thermal",
    "flame",
    "yellowy",
    "bipolar",
    "grey",
    "spectrum",
    "cyclic",
    "greyclip",
)
qt_cmaps = sorted(qt_cmaps)
plot_lw = 3
font_size = 12
plt.rcParams["font.size"] = font_size


__all__ = ["DataSetPlotter"]


class DataItem(NamedTuple):
    name: str
    array: np.ndarray


def format_units(units, skip=True):
    if skip:
        return str(units)
    units = str(units).lower()
    scale_map = {
        "giga": "G",
        "mega": "M",
        "kilo": "k",
        "milli": "m",
        "micro": "$\\mu$",
        "nano": "n",
        "pico": "p",
        "femto": "f",
    }
    unit_map = {
        "meter": "m",
        "phi0": "$\\Phi_0$",
        "farad": "F",
        "ampere": "A",
        "volt": "V",
    }
    for name, abbrev in scale_map.items():
        units = units.replace(name, abbrev)
    for name, abbrev in unit_map.items():
        units = units.replace(name, abbrev)
    return units


def subtract_line_by_line(zdata: np.ndarray, axis: int, func: Callable):
    """Perform line-by-line background subtraction of ``zdata``
    along axis ``axis`` according to callable ``func``.

    Args:
        zdata: 2D data for which you want to do background subtraction.
        axis: Axis along which you want to do line-by-line background subtraction.
        func: Function applied to each line to calculate the value to subtract
            (e.g. np.min, np.mean, etc.)

    Returns:
        A copy of zdata with background subtracted line-by-line.
    """
    zdata = zdata.copy()
    if axis == 0:  # x
        for i in range(zdata.shape[axis]):
            zdata[i, :] -= func(zdata[i, :])
    else:  # y
        for i in range(zdata.shape[axis]):
            zdata[:, i] -= func(zdata[:, i])
    return zdata


def fit_line(x: np.ndarray, y: np.ndarray) -> np.ndarray:
    """Returns the best-fit line ``slope * x + offset`` to ``y``"""
    slope, offset = np.polyfit(x, y, 1)
    return slope * x + offset


def fit_plane(x: np.ndarray, y: np.ndarray, z: np.ndarray) -> np.ndarray:
    """Returns the best-fit plane ``z = f(x, y)``"""
    X, Y = np.meshgrid(x, y)
    mask = np.isfinite(z)
    r = np.column_stack((X[mask], Y[mask], np.ones(mask.sum(), dtype=float)))
    coeffs, *_ = lstsq(r, z[mask])
    plane = coeffs[0] * X + coeffs[1] * Y + coeffs[2]
    return plane


class PlotWidget(QtWidgets.QWidget):
    """Plotting widget comprised of a matplotlib canvas and a pyqtgraph widget, along with some
    options like slices of image data, axis transforms, etc.
    """

    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.current_data = None
        self.exp_data = {}

        # matplotlib stuff
        self.fig = Figure(constrained_layout=True)
        self.fig.patch.set_alpha(1)
        self.canvas = FigureCanvasQTAgg(self.fig)
        self.canvas.setParent(self)
        self.canvas.setSizePolicy(
            QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding
        )
        self.toolbar = NavigationToolbar2QT(self.canvas, self)

        # pyqtgraph stuff
        self.pyqt_plot = SlicePlotWidget(parent=self)
        self.pyqt_imview = SliceableImageView(parent=self)
        self.pyqt_plot.hide()
        self.pyqt_imview.hide()
        pyqt_top_widgets = QtWidgets.QWidget(parent=self)
        pyqt_bottom_widgets = QtWidgets.QWidget(parent=self)
        pyqt_top_layout = QtWidgets.QVBoxLayout(pyqt_top_widgets)
        pyqt_bottom_layout = QtWidgets.QVBoxLayout(pyqt_bottom_widgets)
        pyqt_top_layout.addWidget(self.pyqt_plot)
        pyqt_top_layout.addWidget(self.pyqt_imview)
        pyqt_bottom_layout.addWidget(self.pyqt_imview.x_slice_widget)
        pyqt_bottom_layout.addWidget(self.pyqt_imview.y_slice_widget)
        self.pyqt_imview.x_slice_widget.hide()
        self.pyqt_imview.y_slice_widget.hide()
        self.pyqt_splitter = QtWidgets.QSplitter(Qt.Vertical, parent=self)
        self.pyqt_splitter.hide()
        self.pyqt_splitter.addWidget(pyqt_top_widgets)
        self.pyqt_splitter.addWidget(pyqt_bottom_widgets)

        # plot options
        self.top_option_layout = QtWidgets.QHBoxLayout()
        self.bottom_option_layout = QtWidgets.QHBoxLayout()
        self._setup_cmap()
        self._setup_options()
        self._setup_background_subtraction()
        self._setup_slices()
        self._setup_transforms()
        self.slice_state = 1  # no slices
        self.set_slice()

        # main layout
        layout = QtWidgets.QVBoxLayout(self)
        layout.addLayout(self.top_option_layout)
        layout.addWidget(self.backsub_widget)
        layout.addWidget(self.toolbar)
        layout.addWidget(self.canvas)
        layout.addWidget(self.pyqt_splitter)
        layout.addLayout(self.bottom_option_layout)

    def _setup_cmap(self) -> None:
        """Setup the UI for selecting matplotlib and pyqtgraph colormaps."""
        self.mpl_cmap = "viridis"
        self.mpl_cmap_selector = QtWidgets.QComboBox()
        self.mpl_cmap_selector.setEditable(True)
        self.mpl_cmap_selector.setSizeAdjustPolicy(QtWidgets.QComboBox.AdjustToContents)
        self.qt_cmap_selector = QtWidgets.QComboBox()
        self.qt_cmap_selector.setEditable(True)
        self.qt_cmap_selector.setSizeAdjustPolicy(QtWidgets.QComboBox.AdjustToContents)

        cmap_widget = QtWidgets.QGroupBox("Colormap")
        self.mpl_cmap_widget = QtWidgets.QGroupBox("matplotlib")
        mpl_cmap_layout = QtWidgets.QHBoxLayout(self.mpl_cmap_widget)
        mpl_cmap_layout.addWidget(self.mpl_cmap_selector)
        self.qt_cmap_widget = QtWidgets.QGroupBox("pyqtgraph")
        qt_cmap_layout = QtWidgets.QHBoxLayout(self.qt_cmap_widget)
        qt_cmap_layout.addWidget(self.qt_cmap_selector)
        cmap_layout = QtWidgets.QHBoxLayout(cmap_widget)
        cmap_layout.addWidget(self.mpl_cmap_widget)
        cmap_layout.addWidget(self.qt_cmap_widget)
        self.top_option_layout.addWidget(cmap_widget)

        self.mpl_cmap_selector.currentIndexChanged.connect(self.set_cmap_mpl)
        for name in mpl_cmaps:
            self.mpl_cmap_selector.addItem(name)
        self.mpl_cmap_selector.setCurrentIndex(mpl_cmaps.index("viridis"))
        self.qt_cmap_selector.currentIndexChanged.connect(self.set_cmap_qt)
        for name in qt_cmaps:
            self.qt_cmap_selector.addItem(name)
        self.qt_cmap_selector.setCurrentIndex(0)
        self.qt_cmap_widget.hide()

    def _setup_background_subtraction(self) -> None:
        """Setup UI for global or line-by-line background subtraction."""
        self.backsub_radio = QtWidgets.QButtonGroup()
        backsub_buttons = [
            QtWidgets.QRadioButton(s)
            for s in ("none", "min", "max", "mean", "median", "linear")
        ]
        backsub_buttons[0].setChecked(True)
        self.backsub_widget = QtWidgets.QGroupBox("Background subtraction")
        backsub_layout = QtWidgets.QHBoxLayout(self.backsub_widget)
        for i, b in enumerate(backsub_buttons):
            backsub_layout.addWidget(b)
            self.backsub_radio.addButton(b, i)
        self.backsub_radio.buttonClicked.connect(self.replot)

        self.line_backsub_radio = QtWidgets.QButtonGroup()
        self.line_backsub_btn = QtWidgets.QCheckBox("line-by-line")
        self.line_backsub_btn.setChecked(False)
        self.x_line_backsub_btn, self.y_line_backsub_btn = xy_btns = [
            QtWidgets.QRadioButton(s) for s in ("x", "y")
        ]
        xy_btns[0].setChecked(True)
        backsub_layout.addWidget(self.line_backsub_btn)
        for i, b in enumerate(xy_btns):
            b.setEnabled(False)
            backsub_layout.addWidget(b)
            self.line_backsub_radio.addButton(b, i)

        self.line_backsub_btn.stateChanged.connect(self.update_line_by_line)
        self.line_backsub_radio.buttonClicked.connect(self.replot)

    def _setup_transforms(self) -> None:
        """Setup UI for axis transformations. Currently this is only rotation."""
        self.rotate_widget = QtWidgets.QGroupBox("Rotate")
        rotate_layout = QtWidgets.QVBoxLayout()
        self.rotate_widget.setLayout(rotate_layout)
        self.rotate_slider = SliderWidget(-180, 180, 0, 180)
        rotate_layout.addWidget(self.rotate_slider)
        self.rotate_slider.value_box.valueChanged.connect(self.replot)
        self.top_option_layout.addWidget(self.rotate_widget)

    def _setup_slices(self) -> None:
        """Setup UI for slices of image/2D data."""
        self.slice_radio = QtWidgets.QButtonGroup()
        slice_buttons = [QtWidgets.QRadioButton(s) for s in ("none", "x", "y")]
        slice_buttons[0].setChecked(True)
        slice_widget = QtWidgets.QGroupBox("Slice")
        slice_layout = QtWidgets.QVBoxLayout(slice_widget)
        for i, b in enumerate(slice_buttons):
            slice_layout.addWidget(b)
            self.slice_radio.addButton(b, i)
        self.line_color_btn = QtWidgets.QCheckBox("color by value")
        self.line_color_btn.setChecked(True)
        self.line_color_btn.stateChanged.connect(self.replot)
        slice_layout.addWidget(self.line_color_btn)
        self.top_option_layout.addWidget(slice_widget)
        self.slice_radio.buttonClicked.connect(self.set_slice)

    def _setup_options(self) -> None:
        """Setup UI for other plot options."""
        opt_group = QtWidgets.QGroupBox("Plot options")
        opt_layout = QtWidgets.QVBoxLayout()
        opt_group.setLayout(opt_layout)
        plot_opts = [
            ("pyqtgraph", False),
            ("grid", False),
            ("histogram", False),
        ]
        self.opt_checks = {}
        for name, checked in plot_opts:
            btn = QtWidgets.QCheckBox(name)
            btn.setChecked(checked)
            opt_layout.addWidget(btn)
            btn.stateChanged.connect(self.replot)
            self.opt_checks[name] = btn
        self.bins_box = QtWidgets.QSpinBox()
        self.bins_box.setMinimum(10)
        self.bins_box.setMaximum(1000)
        self.bins_box.setValue(100)
        self.bins_box.setKeyboardTracking(False)
        self.bins_box.valueChanged.connect(self.replot)
        self.bins_box.setEnabled(self.get_opt("histogram"))

        bins_widget = QtWidgets.QWidget()
        bins_layout = QtWidgets.QHBoxLayout(bins_widget)
        if self.get_opt("histogram"):
            bins_widget.show()
        else:
            bins_widget.hide()
        bins_layout.addWidget(QtWidgets.QLabel("bins: "))
        bins_layout.addWidget(self.bins_box)
        opt_layout.addWidget(bins_widget)

        self.top_option_layout.addWidget(opt_group)
        self.opt_checks["histogram"].stateChanged.connect(
            lambda val: self.bins_box.setEnabled(val)
        )
        self.opt_checks["histogram"].stateChanged.connect(
            lambda val: bins_widget.show() if val else bins_widget.hide()
        )

    def set_cmap_mpl(self, idx: int) -> None:
        """Set the matplotlib colormap.

        Args:
            idx: Index of the requested colormap in self.mpl_cmap_selector.
        """
        name = str(self.mpl_cmap_selector.itemText(idx))
        if not name:
            return
        self.mpl_cmap = name
        self.replot()

    def set_cmap_qt(self, idx: int):
        """Set the pyqtgraph colormap.

        Args:
            idx: Index of the requested colormap in self.qt_cmap_selector.
        """
        name = str(self.qt_cmap_selector.itemText(idx))
        if not name:
            return
        self.pyqt_imview.set_cmap(name)

    def get_opt(self, optname: str) -> bool:
        """Returns True if option `optname` is checked, else False."""
        return bool(self.opt_checks[optname].isChecked())

    def plot_arrays(
        self,
        xs: DataItem,
        ys: DataItem,
        zs: Optional[DataItem] = None,
        title: str = "",
    ) -> None:
        """Plots data based on dimension and all user-selected options, transforms, etc."""
        self.fig_title = title
        self.fig.clear()
        self.pyqt_plot.clear()
        self.toolbar.hide()
        self.canvas.hide()
        self.pyqt_splitter.hide()
        self.pyqt_plot.hide()
        self.pyqt_imview.hide()
        if self.get_opt("pyqtgraph"):
            self.mpl_cmap_widget.hide()
            self.qt_cmap_widget.show()
        else:
            self.qt_cmap_widget.hide()
            self.mpl_cmap_widget.show()
        if zs is None:  # 1d data
            self.line_backsub_btn.setChecked(False)
            self.line_backsub_btn.setEnabled(False)
            self.pyqt_imview.x_slice_widget.hide()
            self.pyqt_imview.y_slice_widget.hide()
            self.plot_1d(xs, ys)
        else:  # 2d data
            self.line_backsub_btn.setEnabled(True)
            angle = self.rotate_slider.value_box.value()  # degrees
            if self.slice_state == 0:
                slice_state = None
            elif self.slice_state == 1:
                slice_state = "x"
                self.pyqt_imview.x_slice_widget.show()
                self.pyqt_imview.y_slice_widget.hide()
            elif self.slice_state == 2:
                slice_state = "y"
                self.pyqt_imview.x_slice_widget.hide()
                self.pyqt_imview.y_slice_widget.show()
            self.plot_2d(xs, ys, zs, angle=angle, slice_state=slice_state)
        self.fig.suptitle(self.fig_title, fontsize=12)
        self.canvas.draw()

    def plot_1d(self, xs: DataItem, ys: DataItem) -> None:
        """Plot 1D data according to user-selected options, transformations, etc."""
        self.bins_box.setEnabled(False)
        label = ys.name
        xlabel = f"{xs.name} [{xs.array.units}]"
        ylabel = f"{ys.name} [{ys.array.units}]"
        marker = "."
        if self.get_opt("pyqtgraph"):
            self.plot_1d_qt(xs, ys, xlabel, ylabel, label)
            self.pyqt_plot.show()
            self.pyqt_splitter.show()
        else:
            self.plot_1d_mpl(xs, ys, xlabel, ylabel, marker, label)
            self.toolbar.show()
            self.canvas.show()
        self.rotate_widget.hide()
        self.exp_data = {
            d.name: {"array": d.array.magnitude, "unit": str(d.array.units)}
            for d in (xs, ys)
        }

    def plot_1d_qt(
        self, xs: DataItem, ys: DataItem, xlabel: str, ylabel: str, legend_label: str
    ) -> None:
        """Plot 1D data on self.pyqt_plot."""
        self.pyqt_plot.setLabels(bottom=(xlabel,), left=(ylabel,))
        self.pyqt_plot.plot(
            xs.array.magnitude, ys.array.magnitude, symbol="o", pen=None
        )
        grid = self.get_opt("grid")
        self.pyqt_plot.plotItem.showGrid(x=grid, y=grid)

    def plot_1d_mpl(
        self,
        xs: DataItem,
        ys: DataItem,
        xlabel: str,
        ylabel: str,
        marker: str,
        legend_label: str,
    ) -> None:
        """Plot 1D data on self.fig."""
        ax = self.fig.add_subplot(111)
        ax.set_xlabel(xlabel)
        ax.set_ylabel(ylabel)
        ax.plot(xs.array.magnitude, ys.array.magnitude, marker, label=legend_label)
        ax.grid(self.get_opt("grid"))
        ax.legend()

    def plot_2d(
        self,
        xs: DataItem,
        ys: DataItem,
        zs: DataItem,
        cmap: Optional[str] = None,
        angle: float = 0.0,
        slice_state=None,
    ) -> None:
        """Plot 2D data according to user-selected options, transformations, etc."""
        cmap = cmap or self.mpl_cmap
        xlabel = f"{xs.name} [{xs.array.units}]"
        ylabel = f"{ys.name} [{ys.array.units}]"
        zlabel = f"{zs.name} [{zs.array.units}]"
        vmin, vmax = np.nanmin(zs.array.magnitude), np.nanmax(zs.array.magnitude)
        self.rotate_widget.show()
        if self.get_opt("pyqtgraph"):
            self.plot_2d_qt(xs, ys, zs, xlabel, ylabel, zlabel, angle=angle)
            self.pyqt_imview.show()
            self.pyqt_splitter.show()
        else:
            self.plot_2d_mpl(
                xs,
                ys,
                zs,
                xlabel,
                ylabel,
                zlabel,
                vmin=vmin,
                vmax=vmax,
                cmap=cmap,
                angle=angle,
                slice_state=slice_state,
            )
            self.toolbar.show()
            self.canvas.show()

    def plot_2d_qt(
        self,
        xs: DataItem,
        ys: DataItem,
        zs: DataItem,
        xlabel: str,
        ylabel: str,
        zlabel: str,
        angle: float = 0.0,
    ) -> None:
        """Plot 2D data on self.pyqt_imview."""
        self.bins_box.setEnabled(False)
        pos = np.nanmin(xs.array[0].magnitude), np.nanmin(ys.array[0].magnitude)
        scale = (
            np.ptp(xs.array.magnitude) / zs.array.shape[1],
            np.ptp(ys.array.magnitude) / zs.array.shape[0],
        )
        z = zs.array.magnitude.T
        if angle:
            z = rotate(z, angle, cval=np.nanmin(zs.array.magnitude))
        self.pyqt_imview.setImage(z, pos=pos, scale=scale)
        self.pyqt_imview.setLabels(xlabel=xlabel, ylabel=ylabel, zlabel=zlabel)
        self.pyqt_imview.autoRange()
        # set histogram range manually so that extra pixels added when rotating don't screw up histogram limits
        self.pyqt_imview.ui.histogram.vb.enableAutoRange(
            self.pyqt_imview.ui.histogram.vb.XAxis, False
        )
        hist = self.pyqt_imview.imageItem.getHistogram()[1]
        rng = -np.sort(hist)[:-1].max(), 0
        self.pyqt_imview.ui.histogram.vb.setXRange(*rng, 0.05)
        self.pyqt_imview.set_histogram(self.get_opt("histogram"))
        grid = self.get_opt("grid")
        self.pyqt_imview.getView().showGrid(grid, grid)
        self.pyqt_imview.x_slice_widget.plotItem.showGrid(x=grid, y=grid)
        self.pyqt_imview.y_slice_widget.plotItem.showGrid(x=grid, y=grid)
        self.exp_data = {
            d.name: {"array": d.array.magnitude, "unit": str(d.array.units)}
            for d in (xs, ys)
        }
        self.exp_data[zs.name] = {"array": z, "unit": str(zs.array.units)}

    def plot_2d_mpl(
        self,
        xs: DataItem,
        ys: DataItem,
        zs: DataItem,
        xlabel: str,
        ylabel: str,
        zlabel: str,
        cmap: Optional[str] = None,
        angle: float = 0.0,
        slice_state=None,
        **kwargs,
    ):
        """Plot 2D data on self.fig. kwargs are passed to plt.pcolormesh"""
        self.bins_box.setEnabled(self.get_opt("histogram"))
        if slice_state is None:
            if self.get_opt("histogram"):
                gs = self.fig.add_gridspec(
                    1,
                    4,
                    width_ratios=[1, 0.25, 0.05, 0.05],
                )
                ax = self.fig.add_subplot(gs[0])
                ax_hist = self.fig.add_subplot(gs[1])
                ax_min_slider = self.fig.add_subplot(gs[2])
                ax_max_slider = self.fig.add_subplot(gs[3])
            else:
                ax = self.fig.add_subplot(111)
        else:
            if self.get_opt("histogram"):
                gs = self.fig.add_gridspec(
                    3,
                    4,
                    height_ratios=[3, 1, 0.025],
                    width_ratios=[1, 0.25, 0.05, 0.05],
                )
                ax = self.fig.add_subplot(gs[0, 0])
                ax_hist = self.fig.add_subplot(gs[0, 1])
                ax_min_slider = self.fig.add_subplot(gs[0, 2])
                ax_max_slider = self.fig.add_subplot(gs[0, 3])
                ax_cut = self.fig.add_subplot(gs[1, 0])
                ax_slider = self.fig.add_subplot(gs[2, 0])
            else:
                gs = self.fig.add_gridspec(3, 1, height_ratios=[3, 1, 0.025])
                ax = self.fig.add_subplot(gs[0])
                ax_cut = self.fig.add_subplot(gs[1])
                ax_slider = self.fig.add_subplot(gs[2])
        ax.set_xlabel(xlabel)
        ax.set_ylabel(ylabel)
        x0, y0 = np.nanmean(xs.array.magnitude), np.nanmean(ys.array.magnitude)
        tr = transforms.Affine2D().rotate_deg_around(x0, y0, angle)
        im = ax.pcolormesh(
            xs.array.magnitude,
            ys.array.magnitude,
            zs.array.magnitude,
            cmap=cmap,
            transform=(tr + ax.transData),
            **kwargs,
        )
        cax = ax.inset_axes([1.05, 0, 0.05, 1])
        cbar = self.fig.colorbar(im, cax=cax)
        cbar.set_label(zlabel)
        ax.set_aspect("equal", anchor="C")
        if self.get_opt("histogram"):
            nbins = self.bins_box.value()
            min_val = np.nanmin(zs.array.magnitude)
            max_val = np.nanmax(zs.array.magnitude)
            # add axis for histogram
            # lines indicating cmin and cmax on histogram
            upper = ax_hist.axhline(max_val, color="k", lw=2)
            lower = ax_hist.axhline(min_val, color="k", lw=2)
            ax_hist.set_ylim(cbar.ax.get_ylim())
            ax_hist.set_xticklabels([])
            ax_hist.grid(self.get_opt("grid"))
            N, bins, patches = ax_hist.hist(
                zs.array.magnitude.ravel(), bins=nbins, orientation="horizontal"
            )
            # set color of histogram bins according to z value
            fracs = np.linspace(min_val, max_val, nbins)
            norm = colors.Normalize(min_val, max_val)
            for frac, patch in zip(fracs, patches):
                patch.set_facecolor(plt.get_cmap(cmap)(norm(frac)))
            # make sliders to control cmin and cmax
            self.min_slider = min_slider = VertSlider(
                ax_min_slider,
                "min",
                min_val,
                max_val,
                fontsize=font_size,
                valinit=min_val,
                labels=True,
                alpha=1,
                facecolor=getattr(cm, cmap)(norm(min_val)),
            )
            self.max_slider = max_slider = VertSlider(
                ax_max_slider,
                "max",
                min_val,
                max_val,
                slidermin=min_slider,
                fontsize=font_size,
                valinit=max_val,
                labels=True,
                alpha=1,
                facecolor=getattr(cm, cmap)(norm(max_val)),
                start_at_bottom=False,
            )

            def update_cval(val):
                """function called when min_slider or max_slider are changed"""
                cmin = min_slider.val
                cmax = max_slider.val
                # cbar.set_clim([cmin, cmax])
                im.set_clim([cmin, cmax])
                upper.set_ydata(cmax)
                lower.set_ydata(cmin)
                min_slider.valmax = cmax
                # update colors on the histogram to reflect current clims
                norm = colors.Normalize(cmin, cmax)
                for frac, patch in zip(fracs, patches):
                    if cmin <= frac <= cmax:
                        color = getattr(cm, cmap)(norm(frac))
                        patch.set_alpha(1)
                    else:
                        color = "k"
                        patch.set_alpha(0.25)
                    patch.set_facecolor(color)

            for s in [min_slider, max_slider]:
                s.on_changed(update_cval)

        z = zs.array.magnitude.T
        if angle:
            z = rotate(z, angle, cval=np.nan)
        x = np.linspace(*ax.get_xlim(), z.shape[1])
        y = np.linspace(*ax.get_ylim(), z.shape[0])
        self.exp_data = {
            xs.name: {"array": x, "unit": str(xs.array.units)},
            ys.name: {"array": y, "unit": str(ys.array.units)},
            zs.name: {"array": z.T, "unit": str(zs.array.units)},
        }

        if slice_state is not None:
            ax_cut.grid(self.get_opt("grid"))
            xlab = xlabel if slice_state == "x" else ylabel
            label = zlabel.split(" ")[:1] + ["".join(zlabel.split(" ")[1:])]
            ylab = "\n".join(label)
            ax_cut.set_xlabel(xlab)
            ax_cut.set_ylabel(ylab)

            color_by_value = self.line_color_btn.isChecked()
            if slice_state == "x":
                slice_xs = xs.array.magnitude
                slice_ys = zs.array.magnitude[0, :]
            else:
                slice_xs = ys.array.magnitude
                slice_ys = zs.array.magnitude[:, 0]

            mask = np.isfinite(slice_ys)
            slice_xs = slice_xs[mask]
            slice_ys = slice_ys[mask]

            points = np.array([slice_xs, slice_ys]).T.reshape(-1, 1, 2)
            # make segments overlap
            segments = np.concatenate([points[:-2], points[1:-1], points[2:]], axis=1)
            if mask.any():
                vmin, vmax = np.min(slice_ys), np.max(slice_ys)
            else:
                vmin, vmax = 0, 1
            lc = LineCollection(
                segments,
                cmap=cmap,
                norm=colors.Normalize(vmin, vmax),
            )
            lc.set_array(slice_ys)
            lc.set_linewidth(plot_lw)

            if color_by_value:
                ax_cut.add_collection(lc)
                # we need an invisible line so that the figure draws correctly
                (line,) = ax_cut.plot([0, 0], alpha=0)
            else:
                (line,) = ax_cut.plot(slice_xs, slice_ys, lw=plot_lw)

            if slice_state == "x":
                cut = ax.axhline(y=np.nanmin(y), color="k", alpha=0.8, lw=2)
            else:
                cut = ax.axvline(x=np.nanmin(x), color="k", alpha=0.8, lw=2)

            if self.line_color_btn.isChecked() and self.get_opt("histogram"):
                # adjust line color based on min_slider and max_slider
                def update_line_color(val):
                    lc.set_norm(colors.Normalize(min_slider.val, max_slider.val))

                for s in [min_slider, max_slider]:
                    s.on_changed(update_line_color)

            idx_label = "y" if slice_state == "x" else "x"
            idx = 1 if slice_state == "x" else 0
            self.slider = slider = Slider(
                ax_slider,
                f"{idx_label} index",
                0,
                zs.array.shape[idx] - 1,
                valinit=0,
                valstep=1,
                valfmt="%i",
            )
            z = zs.array.magnitude
            if angle:
                z = rotate(z, angle, cval=np.nan)
            x = np.linspace(*ax.get_xlim(), z.shape[1])
            y = np.linspace(*ax.get_ylim(), z.shape[0])

            def update(val):
                """Function called when slider is moved"""
                i = int(slider.val)
                z = zs.array.magnitude
                if angle:
                    z = rotate(z, angle, cval=np.nan)
                x = np.linspace(*ax.get_xlim(), z.shape[1])
                y = np.linspace(*ax.get_ylim(), z.shape[0])
                margin = 0.025
                color_by_value = self.line_color_btn.isChecked()
                if slice_state == "x":
                    z0 = z[i, :]
                    slider.valmax = len(y) - 1
                    if color_by_value:
                        points = np.array([x, z0]).T.reshape(-1, 1, 2)
                        # make segments overlap
                        segments = np.concatenate(
                            [points[:-2], points[1:-1], points[2:]], axis=1
                        )
                        lc.set_segments(segments)
                        lc.set_array(z0)
                        lc.set_norm(colors.Normalize(np.nanmin(z0), np.nanmax(z0)))
                    else:
                        line.set_xdata(x)
                        line.set_ydata(z0)
                    rng = np.nanmax(x) - np.nanmin(x)
                    xmin = np.nanmin(x) - margin * rng
                    xmax = np.nanmax(x) + margin * rng
                    cut.set_ydata(2 * [y[i]])
                    xdata, ydata = x, z0
                    self.exp_data["slice"] = {
                        xs.name: {"array": xdata, "unit": str(xs.array.units)},
                        zs.name: {"array": ydata, "unit": str(zs.array.units)},
                        "index": int(slider.val),
                    }
                elif slice_state == "y":
                    slider.valmax = len(x) - 1
                    z0 = z[:, i]
                    if color_by_value:
                        points = np.array([y, z0]).T.reshape(-1, 1, 2)
                        # make segments overlap
                        segments = np.concatenate(
                            [points[:-2], points[1:-1], points[2:]], axis=1
                        )
                        lc.set_segments(segments)
                        lc.set_array(z0)
                        lc.set_norm(colors.Normalize(np.nanmin(z0), np.nanmax(z0)))
                    else:
                        line.set_xdata(y)
                        line.set_ydata(z0)
                    rng = np.nanmax(y) - np.nanmin(y)
                    xmin = np.nanmin(y) - margin * rng
                    xmax = np.nanmax(y) + margin * rng
                    cut.set_xdata(2 * [x[i]])
                    xdata, ydata = y, z0
                    self.exp_data["slice"] = {
                        ys.name: {"array": xdata, "unit": str(ys.array.units)},
                        zs.name: {"array": ydata, "unit": str(zs.array.units)},
                        "index": int(slider.val),
                    }
                ax_cut.set_xlim(xmin, xmax)
                slider.ax.set_xlim(slider.valmin, slider.valmax)
                vmin, vmax = np.nanmin(ydata), np.nanmax(ydata)
                margin = 0.1
                rng = vmax - vmin
                vmin = vmin - margin * rng
                vmax = vmax + margin * rng
                try:
                    ax_cut.set_ylim(vmin, vmax)
                except ValueError:  # vmin == vmax
                    pass

            update(0)
            slider.on_changed(update)

    def replot(self):
        """Update the current plot from self.current_data."""
        if self.current_data is not None:
            xs = self.current_data["xs"]
            ys = self.current_data["ys"]
            zs = self.current_data["zs"]
            if self.xy_units_box.isChecked():
                try:
                    xs.array.ito(self.xy_units.text())
                except Exception:
                    self.xy_units.setText(str(xs.array.units))
            if zs is None:
                name = ys.name
                try:
                    ys.array.ito(self.units.text())
                except Exception:
                    self.units.setText(str(ys.array.units))
            else:
                name = zs.name
                if self.xy_units_box.isChecked():
                    try:
                        ys.array.ito(self.xy_units.text())
                    except Exception:
                        self.xy_units.setText(str(ys.array.units))
                try:
                    zs.array.ito(self.units.text())
                except Exception:
                    self.units.setText(str(zs.array.units))
            name = ys.name if zs is None else zs.name
            self.fig_title = f"{self.dataset.metadata['location']} [{name}]"
            self.current_data = {"xs": xs, "ys": ys, "zs": zs}
            self.subtract_background()

    def set_slice(self, idx=None, replot=True):
        """Capture the user-requested slice state."""
        if isinstance(idx, QtWidgets.QRadioButton):
            idx = self.slice_radio.id(idx)
        if idx is None:
            idx = self.slice_radio.checkedId()
        self.slice_state = idx
        self.update_slice()
        if replot:
            self.replot()

    def update_slice(self):
        """Show or hide pyqtgraph slice widgets based on self.slice_state."""
        if self.slice_state == 0:
            self.pyqt_imview.x_slice_widget.hide()
            self.pyqt_imview.y_slice_widget.hide()
            self.line_color_btn.setEnabled(False)
        elif self.slice_state == 1:
            self.pyqt_imview.x_slice_widget.show()
            self.pyqt_imview.y_slice_widget.hide()
            self.line_color_btn.setEnabled(True)
        elif self.slice_state == 2:
            self.pyqt_imview.x_slice_widget.hide()
            self.pyqt_imview.y_slice_widget.show()
            self.line_color_btn.setEnabled(True)
        else:
            raise ValueError(f"Unknown Slice State: {self.slice_state}")

    def update_line_by_line(self):
        """Enable/disable line-by-line background subtraction based on self.line_backsub_btn."""
        self.x_line_backsub_btn.setEnabled(self.line_backsub_btn.isChecked())
        self.y_line_backsub_btn.setEnabled(self.line_backsub_btn.isChecked())
        self.replot()

    def subtract_background(self, idx: Optional[int] = None):
        """Perform global or line-by-line background subtraction."""
        if self.current_data is None:
            return
        if isinstance(idx, QtWidgets.QRadioButton):
            idx = self.backsub_radio.id(idx)
        idx = idx or self.backsub_radio.checkedId()

        xs = self.current_data["xs"]
        ys = self.current_data["ys"]
        zs = self.current_data["zs"]
        line_by_line = self.line_backsub_btn.isChecked()
        if line_by_line and zs is not None:
            funcs = (
                lambda x: 0,
                np.nanmin,
                np.nanmax,
                np.nanmean,
                np.nanmedian,
                lambda y, x=xs.array.magnitude: fit_line(x, y),
            )
            axis = self.line_backsub_radio.checkedId()
            z = subtract_line_by_line(zs.array.magnitude, axis, funcs[idx])
            zs = DataItem(
                zs.name, z * zs.array.units
            )  # restore units after background subtraction
        else:
            funcs = (
                lambda z: 0,
                np.nanmin,
                np.nanmax,
                np.nanmean,
                lambda z: np.nanmedian(z.ravel()),
            )
            if zs is None:
                funcs = funcs + (lambda y, x=xs.array.magnitude: fit_line(x, y),)
                y = ys.array.magnitude
                ys = DataItem(ys.name, ys.array.units * (y - funcs[idx](y)))
            else:
                funcs = funcs + (
                    lambda z, x=xs.array.magnitude, y=ys.array.magnitude: fit_plane(
                        x, y, z
                    ),
                )
                z = zs.array.magnitude
                zs = DataItem(zs.name, zs.array.units * (z - funcs[idx](z)))

        self.plot_arrays(xs, ys, zs=zs, title=self.fig_title)

    def export_mpl(self, dpi=220):
        """Open dialog to export matplotlib figure."""
        if self.dataset is None:
            return
        name = self.fig_title.split("/")[-1].replace(" ", "")
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Export matplotlib", name, "PNG (*.png)"
        )
        self.fig.savefig(path, dpi=dpi)

    def export_qt(self, width=1200):
        """Open dialog to export pyqtgraph figure.
        Args:
            width (int): Figure width in pixels (I think).
        Note: this is not currently used by the GUI because the pyqtgraph figures are ugly.
        """
        if self.dataset is None:
            return
        name = self.fig_title.split("/")[-1].replace(" ", "")
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Export pyqtgraph", name, "PNG Image (*.png);; JPG Image (*.jpg)"
        )
        plot = (
            self.pyqt_plot.plotItem
            if self.pyqt_plot.isVisible()
            else self.pyqt_imview.scene
        )
        exporter = pg.exporters.ImageExporter(plot)
        exporter.parameters()["width"] = width
        exporter.export(path)

    def export_data(self):
        """Open dialog to export current data (post transformations and background subtraction)
        to .mat, .h5, or .pickle files.
        """
        if not self.exp_data:
            return
        name = self.fig_title.split("/")[-1].replace(" ", "")
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self,
            "Export current data",
            name,
            "MAT (*.mat);;HDF5 (*.h5);;pickle (*.pickle)",
        )
        if path.endswith("mat"):
            try:
                savemat(path, self.exp_data)
            except Exception:
                pass
        elif path.endswith("h5"):
            try:
                with h5py.File(path) as df:
                    set_h5_attrs(df, self.exp_data)
            except Exception:
                pass
        elif path.endswith("pickle"):
            try:
                with open(path, "wb") as f:
                    pickle.dump(self.exp_data, f)
            except Exception:
                pass


class DataSetPlotter(PlotWidget):
    """PlotWidget with functionality specific to scanning-squid datasets."""

    def __init__(self, dataset=None, parent=None):
        super().__init__(parent=parent)
        self.dataset = dataset
        self.arrays = None
        self.indep_vars = None
        arrays_widget = QtWidgets.QGroupBox("Arrays")
        arrays_layout = QtWidgets.QGridLayout(arrays_widget)
        self.selector = QtWidgets.QComboBox()
        arrays_layout.addWidget(self.selector, 0, 0)
        self.top_option_layout.insertWidget(0, arrays_widget)
        self.selector.currentIndexChanged.connect(self.set_plot)
        self.units = QtWidgets.QLineEdit("Array unit")
        self.units.setEnabled(False)
        self.units.returnPressed.connect(self.replot)
        arrays_layout.addWidget(self.units, 1, 0)

        self.xy_units_box = QtWidgets.QCheckBox("real x-y units")
        self.xy_units_box.setChecked(False)
        self.xy_units = QtWidgets.QLineEdit()
        self.xy_units.setText("Length unit")
        self.xy_units.setEnabled(False)
        arrays_layout.addWidget(self.xy_units_box, 0, 1)
        arrays_layout.addWidget(self.xy_units, 1, 1)
        # xy_units_widget = QtWidgets.QWidget()
        # xy_units_layout = QtWidgets.QVBoxLayout()
        # xy_units_widget.setLayout(xy_units_layout)
        # xy_units_layout.addWidget(self.xy_units_box)
        # xy_units_layout.addWidget(self.xy_units)
        # arrays_layout.addWidget(xy_units_widget)
        self.xy_units_box.stateChanged.connect(self.update_xy_units)
        self.xy_units.returnPressed.connect(self.replot)

    def get_arrays(self):
        """Create a dict of arrays from self.dataset."""
        if self.dataset is None:
            return
        if "_scan_" in self.dataset.location:
            if self.xy_units_box.isChecked():
                try:
                    self.arrays = scan_to_arrays(
                        self.dataset, xy_unit=self.xy_units.text()
                    )
                except Exception:
                    self.arrays = scan_to_arrays(self.dataset, xy_unit="um")
                    self.xy_units.setText("um")
            else:
                self.arrays = scan_to_arrays(self.dataset)
            self.indep_vars = ("x", "y")
        elif "_td_cap_" in self.dataset.location:
            if self.xy_units_box.isChecked():
                try:
                    self.arrays = td_to_arrays(
                        self.dataset, z_unit=self.xy_units.text()
                    )
                except Exception:
                    self.arrays = td_to_arrays(self.dataset, z_unit="um")
                    self.xy_units.setText("um")
            else:
                self.arrays = td_to_arrays(self.dataset)
            self.indep_vars = ("height",)
        old_text = self.selector.currentText()
        old_units = self.units.text()
        self.selector.clear()
        for name in self.arrays.keys():
            if name.lower() not in self.indep_vars:
                self.selector.addItem(name)
        if old_text and old_text in self.arrays.keys():
            self.selector.setCurrentText(old_text)
            self.set_plot_from_name(old_text)
            if "Array" not in old_units:
                self.units.setText(old_units)
        else:
            self.selector.setCurrentIndex(0)
            self.set_plot_from_name(self.selector.currentText())

    def set_plot(self, idx):
        """Set current plot to the given index of self.selector.
        Args:
            idx (int): Index of requested plot.
        """
        name = str(self.selector.itemText(idx))
        if not name:
            return
        self.set_plot_from_name(name)

    def set_plot_from_name(self, name: str):
        """Set current plot by name.

        Args:
            name: Name of requested plot/array.
        """
        meas_params = self.dataset.metadata["loop"]["metadata"]
        if len(self.indep_vars) == 1:
            xs = DataItem(self.indep_vars[0], self.arrays[self.indep_vars[0]])
            ys = DataItem(name, self.arrays[name])
            zs = None
            try:
                unit = self.units.text()
                ys.array.ito(unit)
            except Exception:
                unit = ys.array.units
            self.units.setText(str(unit))
            self.units.setEnabled(True)
        elif len(self.indep_vars) == 2:
            x_dir = y_dir = "pos"
            if "direction" in meas_params:
                x_dir = meas_params["direction"]["x"]
                y_dir = meas_params["direction"]["y"]
            xs, ys = (DataItem(name, self.arrays[name]) for name in self.indep_vars)
            z = self.arrays[name]
            if x_dir == "neg":
                z = np.fliplr(z.magnitude) * z.units
            if y_dir == "neg":
                z = np.flipud(z.magnitude) * z.units
            zs = DataItem(name, z)
            try:
                unit = self.units.text()
                zs.array.ito(unit)
            except Exception:
                unit = zs.array.units
            self.units.setText(str(unit))
            self.units.setEnabled(True)

        self.fig_title = ""
        if self.dataset is not None:
            self.fig_title = f"{self.dataset.metadata['location']} [{name}]"
        self.current_data = {"xs": xs, "ys": ys, "zs": zs}
        self.subtract_background()

    def update_xy_units(self):
        """Enable or disable user entry for x-y length units."""
        if self.xy_units_box.isChecked():
            self.xy_units.setText("um")
            self.xy_units.setEnabled(True)
        else:
            self.xy_units.setText("Length unit")
            self.xy_units.setEnabled(False)
        self.update()

    def update(self, dataset=None):
        """Update arrays and plot from dataset."""
        self.dataset = dataset or self.dataset
        self.get_arrays()
        self.backsub_radio.button(0).setChecked(True)
        self.set_plot_from_name(self.selector.currentText())


class ImageView(pg.ImageView):
    """pyqtgraph ImageView wrapper."""

    def __init__(self, **kwargs):
        kwargs["view"] = pg.PlotItem(labels=kwargs.pop("labels", None))
        super().__init__(**kwargs)
        self.view.setAspectLocked(lock=True)
        self.view.invertY(False)
        self.set_histogram(True)
        histogram_action = QtWidgets.QAction("Histogram", self)
        histogram_action.setCheckable(True)
        histogram_action.triggered.connect(self.set_histogram)
        self.scene.contextMenu.append(histogram_action)
        self.ui.histogram.gradient.loadPreset("grey")

    def set_histogram(self, visible):
        """Show or hide the histogram.
        Args:
            visible (bool): Whether you want the histogram to be visible.
        """
        self.ui.histogram.setVisible(visible)
        self.ui.roiBtn.setVisible(False)
        self.ui.normGroup.setVisible(False)
        self.ui.menuBtn.setVisible(False)

    def set_data(self, data):
        """Set the image data.
        Args:
            data (np.ndarray): 2D array of iamge data.
        """
        self.setImage(data)

    def set_cmap(self, name):
        """Set the colormap to one of pyqtgraph's presets.
        Args:
            name (str): Name of preset colormap.
        """
        self.ui.histogram.gradient.loadPreset(name)


class SlicePlotWidget(pg.PlotWidget):
    """pyqtgraph PlotWidget with crosshairs that follow mouse."""

    crosshair_moved = QtCore.Signal(float, float)

    def __init__(self, parametric=False, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.cross_section_enabled = False
        self.parametric = parametric
        self.search_mode = True
        self.label = None
        self.selected_point = None
        self.plotItem.showGrid(x=True, y=True)
        self.scene().sigMouseClicked.connect(self.toggle_search)
        self.scene().sigMouseMoved.connect(self.handle_mouse_move)

    def set_data(self, data, **kwargs):
        if data is not None and len(data) > 0 and np.isfinite(data).all():
            self.clear()
            self.plot(data, **kwargs)

    def toggle_search(self, mouse_event):
        """Toggle the crosshairs tracking mouse movement on click event."""
        if mouse_event.double():
            if self.cross_section_enabled:
                self.hide_crosshair()
            else:
                self.add_crosshair()
        elif self.cross_section_enabled:
            self.search_mode = not self.search_mode
            if self.search_mode:
                self.handle_mouse_move(mouse_event.scenePos())

    def handle_mouse_move(self, mouse_event):
        """Depending on search_mode and cross_section_enabled, track mouse movement
        and emit a signal with the crosshair position.
        """
        if self.cross_section_enabled and self.search_mode:
            item = self.getPlotItem()
            view_coords = item.getViewBox().mapSceneToView(mouse_event)
            view_x, view_y = view_coords.x(), view_coords.y()
            # try to get data indices corresponding to mouse position
            guesses = []
            for data_item in item.items:
                if isinstance(data_item, pg.PlotDataItem):
                    xdata, ydata = data_item.xData, data_item.yData
                    index_distance = (
                        lambda i: (xdata[i] - view_x) ** 2 + (ydata[i] - view_y) ** 2
                    )
                    if self.parametric:
                        index = min(range(len(xdata)), key=index_distance)
                    else:
                        index = min(np.searchsorted(xdata, view_x), len(xdata) - 1)
                        if index and xdata[index] - view_x > view_x - xdata[index - 1]:
                            index -= 1
                    pt_x, pt_y = xdata[index], ydata[index]
                    guesses.append(((pt_x, pt_y), index_distance(index), index))
            if not guesses:
                return

            (pt_x, pt_y), _, index = min(guesses, key=lambda x: x[1])
            self.selected_point = (pt_x, pt_y)
            self.v_line.setPos(pt_x)
            self.h_line.setPos(pt_y)
            self.label.setText("x={:.5f}, y={:.5f}".format(pt_x, pt_y))
            self.crosshair_moved.emit(pt_x, pt_y)

    def add_crosshair(self):
        self.h_line = pg.InfiniteLine(angle=0, movable=False)
        self.v_line = pg.InfiniteLine(angle=90, movable=False)
        self.addItem(self.h_line, ignoreBounds=False)
        self.addItem(self.v_line, ignoreBounds=False)
        if self.label is None:
            self.label = pg.LabelItem(justify="right")
            self.getPlotItem().layout.addItem(self.label, 4, 1)
        self.x_cross_index = 0
        self.y_cross_index = 0
        self.cross_section_enabled = True

    def hide_crosshair(self):
        self.removeItem(self.h_line)
        self.removeItem(self.v_line)
        self.cross_section_enabled = False


class SliceableImageView(ImageView):
    """ImageView combined with a SlicePlotWidget for both x and y slices."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.search_mode = False
        self._connect_signals()
        self.angle = 0
        self.y_cross_index = 0
        self.x_cross_index = 0
        self.x_slice_widget = SlicePlotWidget()
        self.x_slice_widget.add_crosshair()
        self.x_slice_widget.search_mode = False
        self.pen = pg.mkPen(width=plot_lw)
        self.x_slice_widget_data = self.x_slice_widget.plot([0, 0], pen=self.pen)
        self.h_line = pg.InfiniteLine(pos=0, angle=0, movable=False, pen=self.pen)
        self.view.addItem(self.h_line, ignoreBounds=False)

        self.y_slice_widget = SlicePlotWidget()
        self.y_slice_widget.add_crosshair()
        self.y_slice_widget.search_mode = False
        self.y_slice_widget_data = self.y_slice_widget.plot([0, 0], pen=self.pen)
        self.v_line = pg.InfiniteLine(pos=0, angle=90, movable=False, pen=self.pen)
        self.view.addItem(self.v_line, ignoreBounds=False)

        self.x_slice_widget.crosshair_moved.connect(lambda x, _: self.set_position(x=x))
        self.y_slice_widget.crosshair_moved.connect(lambda y, _: self.set_position(y=y))

        self.text_item = pg.LabelItem(justify="right")
        self.view.layout.addItem(self.text_item, 4, 1)

    def setImage(self, *args, **kwargs):
        """Set the image and adjust ViewBox, etc.
        *args and **kwargs passed to ImageItem constructor.
        """
        if "pos" in kwargs:
            self._x0, self._y0 = kwargs["pos"]
        else:
            self._x0, self._y0 = 0, 0
        if "scale" in kwargs:
            self._xscale, self._yscale = kwargs["scale"]
        else:
            self._xscale, self._yscale = 1, 1
        # adjust to make pixel centers align on ticks
        self._x0 -= self._xscale / 2.0
        self._y0 -= self._yscale / 2.0
        if "pos" in kwargs:
            kwargs["pos"] = self._x0, self._y0

        if self.imageItem.image is not None:
            (min_x, max_x), (min_y, max_y) = self.imageItem.getViewBox().viewRange()
            mid_x, mid_y = (max_x + min_x) / 2.0, (max_y + min_y) / 2.0
        else:
            mid_x, mid_y = 0, 0

        self.h_line.setPos(mid_y)
        self.v_line.setPos(mid_x)
        super().setImage(*args, **kwargs)
        self.set_position()

    def setLabels(self, xlabel="x", ylabel="y", zlabel="z"):
        """Set x, y, and z labels."""
        self.view.setLabels(bottom=(xlabel,), left=(ylabel,))
        self.x_slice_widget.plotItem.setLabels(bottom=xlabel, left=zlabel)
        self.y_slice_widget.plotItem.setLabels(bottom=ylabel, left=zlabel)
        self.ui.histogram.item.axis.setLabel(text=zlabel)

    def _connect_signals(self):
        """Setup signals."""
        if self.imageItem.scene() is None:
            raise RuntimeError(
                "Signal can only be connected after it has been embedded in a scene."
            )
        self.imageItem.scene().sigMouseClicked.connect(self.toggle_search)
        self.imageItem.scene().sigMouseMoved.connect(self.handle_mouse_move)
        self.timeLine.sigPositionChanged.connect(self.update_slice)

    def toggle_search(self, mouse_event):
        """Toggle the crosshairs tracking mouse movement on click event."""
        if mouse_event.double():
            return
        self.search_mode = not self.search_mode
        if self.search_mode:
            self.handle_mouse_move(mouse_event.scenePos())

    def handle_mouse_move(self, mouse_event):
        """Depending on search_mode, track mouse movement and update position text_item."""
        if self.search_mode:
            view_coords = self.imageItem.getViewBox().mapSceneToView(mouse_event)
            view_x, view_y = view_coords.x(), view_coords.y()
            self.set_position(view_x, view_y)

    def set_position(self, x=None, y=None):
        """Update text_item displaying x, y, and z mouse position."""
        if x is None:
            x = self.v_line.getXPos()
        if y is None:
            y = self.h_line.getYPos()

        item_coords = self.imageItem.getViewBox().mapFromViewToItem(
            self.imageItem, QtCore.QPointF(x, y)
        )
        item_x, item_y = item_coords.x(), item_coords.y()
        max_x, max_y = self.imageItem.image.shape

        item_x = self.x_cross_index = max(min(int(item_x), max_x - 1), 0)
        item_y = self.y_cross_index = max(min(int(item_y), max_y - 1), 0)

        view_coords = self.imageItem.getViewBox().mapFromItemToView(
            self.imageItem, QtCore.QPointF(item_x + 0.5, item_y + 0.5)
        )
        x, y = view_coords.x(), view_coords.y()

        self.v_line.setPos(x)
        self.h_line.setPos(y)
        z_val = self.imageItem.image[self.x_cross_index, self.y_cross_index]
        self.update_slice()
        self.text_item.setText("x={:.5f}, y={:.5f}, z={:.5f}".format(x, y, z_val))

    def update_slice(self):
        """Update the current x and y slices."""
        zdata = self.imageItem.image
        nx, ny = zdata.shape
        x0, y0, xscale, yscale = self._x0, self._y0, self._xscale, self._yscale
        xdata = np.linspace(x0, x0 + (xscale * (nx - 1)), nx)
        ydata = np.linspace(y0, y0 + (yscale * (ny - 1)), ny)
        zval = zdata[self.x_cross_index, self.y_cross_index]
        self.x_slice_widget_data.setData(xdata, zdata[:, self.y_cross_index])
        self.x_slice_widget.v_line.setPos(xdata[self.x_cross_index])
        self.x_slice_widget.h_line.setPos(zval)
        self.y_slice_widget_data.setData(ydata, zdata[self.x_cross_index, :])
        self.y_slice_widget.v_line.setPos(ydata[self.y_cross_index])
        self.y_slice_widget.h_line.setPos(zval)
