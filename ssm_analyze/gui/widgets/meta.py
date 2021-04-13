from ..qjsonmodel import QJsonModel
from ..utils import load_json_ordered
from ..qt import *


class MetaWidget(QtWidgets.QTreeView):
    """Widget for inspecting dataset metadata."""

    def __init__(self, path=None, data=None):
        super(MetaWidget, self).__init__()
        self.setContextMenuPolicy(Qt.ActionsContextMenu)
        self.model = QJsonModel()
        self.setModel(self.model)
        assert not (path and data), "path and data cannot both be None."
        if path is not None:
            self.load_meta(path=path)
        elif data is not None:
            self.load_meta(data=data)
        self.expanded.connect(lambda item: self.resizeColumnToContents(0))
        self.setHeaderHidden(True)

    def load_meta(self, path=None, data=None):
        """Loads metadata stored in json file at `path`."""
        assert not (path and data), "path and data cannot both be None."
        if path is not None:
            self.model.load(load_json_ordered(path))
        elif data is not None:
            self.model.load(data)
        self.resizeColumnToContents(0)
