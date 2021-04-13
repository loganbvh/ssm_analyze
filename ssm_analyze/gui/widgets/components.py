from ..qt import QtGui, QtWidgets


class ItemComboBox(QtWidgets.QComboBox):
    def go_to_item(self, item):
        idx = self.findText(item)
        if idx >= 0:
            self.setCurrentIndex(idx)
        else:
            raise ValueError("No item %d" % idx)


class NoEditItem(QtGui.QStandardItem):
    def __init__(self, name):
        super(NoEditItem, self).__init__(name)
        self.setEditable(False)

    def findItems(self, name):
        matches = []
        for i in range(self.rowCount()):
            item = self.child(i)
            if str(item.text()) == name:
                matches.append(item)
        return matches
