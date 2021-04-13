from ..qt import Qt, QtCore, QtWidgets, QtGui
from matplotlib.widgets import AxesWidget


class LabeledSlider(QtWidgets.QWidget):
    """QSlider with ticks and labels."""

    def __init__(
        self,
        minimum,
        maximum,
        init,
        interval=1,
        orientation=Qt.Horizontal,
        labels=None,
        parent=None,
    ):
        super().__init__(parent=parent)

        levels = range(minimum, maximum + interval, interval)
        if labels is not None:
            if not isinstance(labels, (tuple, list)):
                raise Exception("<labels> is a list or tuple.")
            if len(labels) != len(levels):
                raise Exception("Size of <labels> doesn't match levels.")
            self.levels = list(zip(levels, labels))
        else:
            self.levels = list(zip(levels, map(str, levels)))

        if orientation == Qt.Horizontal:
            self.layout = QtWidgets.QVBoxLayout(self)
        elif orientation == Qt.Vertical:
            self.layout = QtWidgets.QHBoxLayout(self)
        else:
            raise Exception("<orientation> wrong.")

        # gives some space to print labels
        self.left_margin = 10
        self.top_margin = 0
        self.right_margin = 10
        self.bottom_margin = 10

        self.layout.setContentsMargins(
            self.left_margin, self.top_margin, self.right_margin, self.bottom_margin
        )

        self.slider = QtWidgets.QSlider(orientation, self)
        self.slider.setMinimum(minimum)
        self.slider.setMaximum(maximum)
        self.slider.setValue(init)
        if orientation == Qt.Horizontal:
            self.slider.setTickPosition(QtWidgets.QSlider.TicksBelow)
        else:
            self.slider.setTickPosition(QtWidgets.QSlider.TicksLeft)
        self.slider.setTickInterval(interval)
        self.slider.setSingleStep(1)
        self.setSizePolicy(
            QtWidgets.QSizePolicy.MinimumExpanding, QtWidgets.QSizePolicy.Minimum
        )

        self.layout.addWidget(self.slider)

    def paintEvent(self, e):
        super().paintEvent(e)
        style = self.slider.style()
        painter = QtGui.QPainter(self)
        painter.setPen(QtGui.QPen(Qt.black, 1))
        st_slider = QtWidgets.QStyleOptionSlider()
        st_slider.initFrom(self.slider)
        st_slider.orientation = self.slider.orientation()

        length = style.pixelMetric(
            QtWidgets.QStyle.PM_SliderLength, st_slider, self.slider
        )
        available = style.pixelMetric(
            QtWidgets.QStyle.PM_SliderSpaceAvailable, st_slider, self.slider
        )

        for v, v_str in self.levels:
            # get the size of the label
            rect = painter.drawText(QtCore.QRect(), Qt.TextDontPrint, v_str)

            if self.slider.orientation() == Qt.Horizontal:
                # I assume the offset is half the length of slider, therefore
                # + length//2
                x_loc = (
                    QtWidgets.QStyle.sliderPositionFromValue(
                        self.slider.minimum(), self.slider.maximum(), v, available
                    )
                    + length // 2
                )

                # left bound of the text = center - half of text width + L_margin
                left = x_loc - rect.width() // 2 + self.left_margin
                bottom = self.rect().bottom()

                # enlarge margins if clipping
                if v == self.slider.minimum():
                    if left <= 0:
                        self.left_margin = rect.width() // 2 - x_loc
                    if self.bottom_margin <= rect.height():
                        self.bottom_margin = rect.height()

                    self.layout.setContentsMargins(
                        self.left_margin,
                        self.top_margin,
                        self.right_margin,
                        self.bottom_margin,
                    )

                if (
                    v == self.slider.maximum()
                    and rect.width() // 2 >= self.right_margin
                ):
                    self.right_margin = rect.width() // 2
                    self.layout.setContentsMargins(
                        self.left_margin,
                        self.top_margin,
                        self.right_margin,
                        self.bottom_margin,
                    )

            else:
                y_loc = QtWidgets.QStyle.sliderPositionFromValue(
                    self.slider.minimum(),
                    self.slider.maximum(),
                    v,
                    available,
                    upsideDown=True,
                )

                bottom = y_loc + length // 2 + rect.height() // 2 + self.top_margin - 3
                # there is a 3 px offset that I can't attribute to any metric

                left = self.left_margin - rect.width()
                if left <= 0:
                    self.left_margin = rect.width() + 2
                    self.layout.setContentsMargins(
                        self.left_margin,
                        self.top_margin,
                        self.right_margin,
                        self.bottom_margin,
                    )

            pos = QtCore.QPoint(left, bottom)
            painter.drawText(pos, v_str)
        return


class SliderWidget(QtWidgets.QWidget):
    """LabeledSlider synced with a spinbox to update/display current slider value."""

    def __init__(self, min, max, init, interval, parent=None):
        super().__init__(parent=parent)
        self.value_box = QtWidgets.QSpinBox(self)
        self.slider = LabeledSlider(min, max, init, interval=interval)
        layout = QtWidgets.QHBoxLayout(self)
        layout.addWidget(self.value_box)
        layout.addWidget(self.slider)
        self.slider.slider.valueChanged.connect(self.update_value)
        self.value_box.setMinimum(min)
        self.value_box.setMaximum(max)
        self.value_box.setValue(init)
        self.value_box.setKeyboardTracking(False)
        self.value_box.valueChanged.connect(self.update_value)
        self.update_value(init)
        sp = self.sizePolicy()
        sp.setVerticalPolicy(QtWidgets.QSizePolicy.Minimum)
        sp.setHorizontalPolicy(QtWidgets.QSizePolicy.MinimumExpanding)
        self.setSizePolicy(sp)

    def update_value(self, val):
        self.value_box.setValue(val)
        self.slider.slider.setValue(val)


class VertSlider(AxesWidget):
    """
    A slider representing a floating point range.
    For the slider to remain responsive you must maintain a
    reference to it.
    """

    def __init__(
        self,
        ax,
        label,
        valmin,
        valmax,
        valinit=0,
        valfmt="%1.2f",
        closedmin=True,
        closedmax=True,
        slidermin=None,
        slidermax=None,
        dragging=True,
        fontsize=None,
        labels=True,
        start_at_bottom=True,
        **kwargs
    ):
        """
        Create a slider from *valmin* to *valmax* in axes *ax*.

        Additional kwargs are passed on to ``self.poly`` which is the
        :class:`matplotlib.patches.Rectangle` which draws the slider
        knob.  See the :class:`matplotlib.patches.Rectangle` documentation
        valid property names (e.g., *facecolor*, *edgecolor*, *alpha*, ...).

        Args:
            ax (Axes): The Axes to put the slider in
            label (str): Slider label
            valmin (float): The minimum value of the slider
            valmax (float): The maximum value of the slider
            valinit (optional, float): The slider initial position. Default: 0
            valfmt (str): Used to format the slider value, fprint format string
            closedmin (optional, bool): Indicate whether the slider interval is closed on the bottom. Default: True
            closedmax (optional, bool): Indicate whether the slider interval is closed on the top. Default: True
            slidermin (optional, Slider) Do not allow the current slider to have a value less than
                `slidermin`. Default: None
            slidermax (optional, Slider): Do not allow the current slider to have a value greater than
                `slidermax`. Default: None
            dragging (optional, bool): Whether the slider can be dragged by the mouse. Default: True.
            fontsize (optional, int): If provided, sets the label font size. Default: None
            labels (optional, bool): Sets whether to show labels. Default: True
            start_at_bottom (optional, bool): Sets whether the filled rectangle starts at the lower or upper
                end of the axis. Default: True
            **kwargs: Passed to self.poly, see above.

        """
        super().__init__(ax)
        self.valmin = valmin
        self.valmax = valmax
        self.val = valinit
        self.valinit = valinit
        if start_at_bottom:
            self.poly = ax.axhspan(valmin, valinit, 0, 1, **kwargs)
        else:
            self.poly = ax.axhspan(valinit, valmax, 0, 1, **kwargs)

        self.hline = ax.axhline(valinit, 0, 1, color="k", lw=2)

        self.valfmt = valfmt
        ax.set_xticks([])
        ax.set_ylim((valmin, valmax))
        ax.set_yticks([])
        ax.set_navigate(False)

        self.connect_event("button_press_event", self._update)
        self.connect_event("button_release_event", self._update)
        if dragging:
            self.connect_event("motion_notify_event", self._update)
        if labels:
            self.label = ax.text(
                0.5,
                1.05,
                label,
                transform=ax.transAxes,
                verticalalignment="center",
                horizontalalignment="center",
                size=fontsize,
            )

            self.valtext = ax.text(
                0.5,
                -0.1,
                valfmt % valinit,
                transform=ax.transAxes,
                verticalalignment="center",
                horizontalalignment="center",
                size=fontsize,
            )

        self.cnt = 0
        self.observers = {}

        self.closedmin = closedmin
        self.closedmax = closedmax
        self.slidermin = slidermin
        self.slidermax = slidermax
        self.drag_active = False

    def _update(self, event):
        """Update the slider position."""
        if self.ignore(event):
            return

        if event.button != 1:
            return

        if event.name == "button_press_event" and event.inaxes == self.ax:
            self.drag_active = True
            event.canvas.grab_mouse(self.ax)

        if not self.drag_active:
            return

        elif (event.name == "button_release_event") or (
            event.name == "button_press_event" and event.inaxes != self.ax
        ):
            self.drag_active = False
            event.canvas.release_mouse(self.ax)
            return

        val = event.ydata
        if val <= self.valmin:
            if not self.closedmin:
                return
            val = self.valmin
        elif val >= self.valmax:
            if not self.closedmax:
                return
            val = self.valmax

        if self.slidermin is not None and val <= self.slidermin.val:
            if not self.closedmin:
                return
            val = self.slidermin.val

        if self.slidermax is not None and val >= self.slidermax.val:
            if not self.closedmax:
                return
            val = self.slidermax.val

        self.set_val(val)

    def set_val(self, val):
        """Set the slider value and update rectangle."""
        xy = self.poly.xy
        xy[1] = 0, val
        xy[2] = 1, val
        self.poly.xy = xy
        self.hline.set_ydata(val)
        if hasattr(self, "valtext"):
            self.valtext.set_text(self.valfmt % val)
        if self.drawon:
            self.ax.figure.canvas.draw_idle()
        self.val = val
        if not self.eventson:
            return
        for cid, func in self.observers.items():
            func(val)

    def on_changed(self, func):
        """When the slider value is changed, call *func* with the new
        slider position.

        A connection id is returned which can be used to disconnect
        """
        cid = self.cnt
        self.observers[cid] = func
        self.cnt += 1
        return cid

    def disconnect(self, cid):
        """Remove the observer with connection id *cid*."""
        try:
            del self.observers[cid]
        except KeyError:
            pass

    def reset(self):
        """Reset the slider to the initial value if needed."""
        if self.val != self.valinit:
            self.set_val(self.valinit)
