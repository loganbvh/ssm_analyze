from IPython.lib import guisupport
from qtconsole.rich_jupyter_widget import RichJupyterWidget
from qtconsole.inprocess import QtInProcessKernelManager


class QJupyterWidget(RichJupyterWidget):
    """Convenience class for a live Jupyter console widget."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        kernel_manager = QtInProcessKernelManager()
        kernel_manager.start_kernel()
        kernel = kernel_manager.kernel
        kernel.gui = "qt"

        kernel_client = kernel_manager.client()
        kernel_client.start_channels()

        self.kernel_manager = kernel_manager
        self.kernel_client = kernel_client

        def stop():
            kernel_client.stop_channels()
            kernel_manager.shutdown_kernel()
            guisupport.get_app_qt4().exit()

        self.exit_requested.connect(stop)

    def push_variables(self, variable_dict):
        """Given a dictionary containing name / value pairs,
        push those variables to the Jupyter console widget.
        """
        self.kernel_manager.kernel.shell.push(variable_dict)

    def clear(self):
        """Clears the terminal."""
        self._control.clear()

    def print_text(self, text):
        """Prints some plain text to the console."""
        self._append_plain_text(text)

    def execute_command(self, command):
        """Execute a command in the console widget."""
        self._execute(command, False)
