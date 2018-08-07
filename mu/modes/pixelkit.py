"""
The mode for working with the Kano's Pixel Kit. Conatains most of the origial
functionality from Mu when it was only a micro:bit related editor as it's a
clone of micro:bit mode.

Copyright (c) 2015-2017 Nicholas H.Tollervey and others (see the AUTHORS file).

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <http://www.gnu.org/licenses/>.
"""
import os
import sys
import os.path
import logging
import semver
from tokenize import TokenError
from mu.logic import HOME_DIRECTORY
from mu.contrib import uflash
from mu.contrib import pixelfs as pixelfs
from mu.modes.api import MICROBIT_APIS, SHARED_APIS
from mu.modes.base import MicroPythonMode
from PyQt5.QtCore import QObject, QThread, pyqtSignal, QTimer

# We can run without nudatus
can_minify = False

logger = logging.getLogger(__name__)

class DeviceFlasher(QThread):
    """
    Used to flash the Pixel Kit in a non-blocking manner.
    """
    # Emitted when flashing the Pixel Kit fails for any reason.
    on_flash_fail = pyqtSignal(str)

    def __init__(self, paths_to_microbits, python_script, path_to_runtime):
        """
        The paths_to_microbits should be a list containing filesystem paths to
        attached Pixel Kits to flash. The python_script should be the text of
        the script to flash onto the device. The path_to_runtime should be the
        path of the hex file for the MicroPython runtime to use. If the
        path_to_runtime is None, the default MicroPython runtime is used by
        default.
        """
        QThread.__init__(self)
        self.paths_to_microbits = paths_to_microbits
        self.python_script = python_script
        self.path_to_runtime = path_to_runtime

    def run(self):
        """
        Flash the device.
        """
        try:
            uflash.flash(paths_to_microbits=self.paths_to_microbits,
                         python_script=self.python_script,
                         path_to_runtime=self.path_to_runtime)
        except Exception as ex:
            # Catch everything so Mu can recover from all of the wide variety
            # of possible exceptions that could happen at this point.
            logger.error(ex)
            self.on_flash_fail.emit(str(ex))


class FileManager(QObject):
    """
    Used to manage Pixel Kit filesystem operations in a manner such that the
    UI remains responsive.

    Provides an FTP-ish API. Emits signals on success or failure of different
    operations.
    """

    # Emitted when the tuple of files on the Pixel Kit is known.
    on_list_files = pyqtSignal(tuple)
    # Emitted when the file with referenced filename is got from the Pixel Kit.
    on_get_file = pyqtSignal(str)
    # Emitted when the file with referenced filename is put onto the Pixel Kit.
    on_put_file = pyqtSignal(str)
    # Emitted when the file with referenced filename is deleted from the
    # Pixel Kit.
    on_delete_file = pyqtSignal(str)
    # Emitted when Mu is unable to list the files on the Pixel Kit.
    on_list_fail = pyqtSignal()
    # Emitted when the referenced file fails to be got from the Pixel Kit.
    on_get_fail = pyqtSignal(str)
    # Emitted when the referenced file fails to be put onto the Pixel Kit.
    on_put_fail = pyqtSignal(str)
    # Emitted when the referenced file fails to be deleted from the Pixel Kit.
    on_delete_fail = pyqtSignal(str)

    def on_start(self):
        """
        Run when the thread containing this object's instance is started so
        it can emit the list of files found on the connected Pixel Kit.
        """
        self.ls()

    def ls(self):
        """
        List the files on the Pixel Kit. Emit the resulting tuple of filenames
        or emit a failure signal.
        """
        try:
            result = tuple(pixelfs.ls())
            self.on_list_files.emit(result)
        except Exception as ex:
            logger.exception(ex)
            self.on_list_fail.emit()

    def get(self, microbit_filename, local_filename):
        """
        Get the referenced Pixel Kit filename and save it to the local
        filename. Emit the name of the filename when complete or emit a
        failure signal.
        """
        try:
            pixelfs.get(microbit_filename, local_filename)
            self.on_get_file.emit(microbit_filename)
        except Exception as ex:
            logger.error(ex)
            self.on_get_fail.emit(microbit_filename)

    def put(self, local_filename):
        """
        Put the referenced local file onto the filesystem on the Pixel Kit.
        Emit the name of the file on the Pixel Kit when complete, or emit
        a failure signal.
        """
        try:
            pixelfs.put(local_filename, target=None)
            self.on_put_file.emit(os.path.basename(local_filename))
        except Exception as ex:
            logger.error(ex)
            self.on_put_fail.emit(local_filename)

    def delete(self, microbit_filename):
        """
        Delete the referenced file on the Pixel Kit's filesystem. Emit the name
        of the file when complete, or emit a failure signal.
        """
        try:
            pixelfs.rm(microbit_filename)
            self.on_delete_file.emit(microbit_filename)
        except Exception as ex:
            logger.error(ex)
            self.on_delete_fail.emit(microbit_filename)


class PixelKitMode(MicroPythonMode):
    """
    Represents the functionality required by the Kano Pixel Kit mode.
    """
    name = _('Kano Pixel Kit')
    description = _("Write MicroPython on the Kano Pixel Kit.")
    icon = 'pixelkit'
    fs = None  #: Reference to filesystem navigator.
    flash_thread = None
    flash_timer = None

    valid_boards = [
        (0x0403, 0x6015),  # Kano Pixel Kit USB VID, PID
    ]

    valid_serial_numbers = [9900, 9901]  # Serial numbers of supported boards.

    python_script = ''

    def actions(self):
        """
        Return an ordered list of actions provided by this module. An action
        is a name (also used to identify the icon) , description, and handler.
        """
        buttons = [
            {
                'name': 'run',
                'display_name': _('Run'),
                'description': _('Execute code from active tab.'),
                'handler': self.run,
                'shortcut': '',
            },
            {
                'name': 'stop',
                'display_name': _('Stop'),
                'description': _('Interrupts running code.'),
                'handler': self.stop,
                'shortcut': '',
            },
            {
                'name': 'mpfiles',
                'display_name': _('Files'),
                'description': _('Access the file system on the Pixel Kit.'),
                'handler': self.toggle_files,
                'shortcut': 'F4',
            },
            {
                'name': 'repl',
                'display_name': _('REPL'),
                'description': _('Use the REPL to live-code on the '
                                 'Pixel Kit.'),
                'handler': self.toggle_repl,
                'shortcut': 'Ctrl+Shift+I',
            },
            {
                'name': 'mpflash',
                'display_name': _('Flash'),
                'description': _('Flash your Pixel Kit with MicroPython'),
                'handler': self.flash,
                'shortcut': 'Ctrl+Shift+I',
            }, ]
        return buttons

    def api(self):
        """
        Return a list of API specifications to be used by auto-suggest and call
        tips.
        """
        return SHARED_APIS

    def run(self):
        """
        Run code on current tab.
        """
        if not self.repl:
            self.toggle_repl(self)
        self.stop()
        serial = self.view.serial
        if serial and self.view.current_tab and self.view.current_tab.text():
            code = self.view.current_tab.text()
            self.enterRawRepl(serial)
            # write code to serial
            serial.write(bytes(code, 'ascii'))
            self.exitRawRepl(serial)

    def stop(self):
        """
        Send keyboard interrupt.
        """
        if not self.repl:
            self.toggle_repl(self)
        if self.view.serial:
            self.view.serial.write(b'\x03') # CTRL-C

    def flash(self):
        pass

    def toggle_repl(self, event):
        """
        Check for the existence of the file pane before toggling REPL.
        """
        if self.fs is None:
            super().toggle_repl(event)
            if self.repl:
                self.set_buttons(mpflash=False, mpfiles=False, run=True, stop=True,)
            elif not (self.repl or self.plotter):
                self.set_buttons(mpflash=True, mpfiles=True, run=True, stop=True,)
        else:
            message = _("REPL and file system cannot work at the same time.")
            information = _("The REPL and file system both use the same USB "
                            "serial connection. Only one can be active "
                            "at any time. Toggle the file system off and "
                            "try again.")
            self.view.show_message(message, information)

    def toggle_files(self, event):
        """
        Check for the existence of the REPL or plotter before toggling the file
        system navigator for the Pixel Kit on or off.
        """
        if (self.repl or self.plotter):
            message = _("File system cannot work at the same time as the "
                        "REPL or plotter.")
            information = _("The file system and the REPL and plotter "
                            "use the same USB serial connection. Toggle the "
                            "REPL and plotter off and try again.")
            self.view.show_message(message, information)
        else:
            if self.fs is None:
                self.add_fs()
                if self.fs:
                    logger.info('Toggle filesystem on.')
                    self.set_buttons(mpflash=False, repl=False, run=False, stop=False, plotter=False)
            else:
                self.remove_fs()
                logger.info('Toggle filesystem off.')
                self.set_buttons(mpflash=True, repl=True, run=True, stop=True, plotter=True)

    def add_fs(self):
        """
        Add the file system navigator to the UI.
        """
        # Check for Pixel Kit
        port, serial_number = self.find_device()
        if not port:
            message = _('Could not find an attached Pixel Kit.')
            information = _("Please make sure the device is plugged "
                            "into this computer.\n\nThe device must "
                            "have MicroPython flashed onto it before "
                            "the file system will work.\n\n"
                            "Finally, press the device's reset button "
                            "and wait a few seconds before trying "
                            "again.")
            self.view.show_message(message, information)
            return
        self.file_manager_thread = QThread(self)
        self.file_manager = FileManager()
        self.file_manager.moveToThread(self.file_manager_thread)
        self.file_manager_thread.started.\
            connect(self.file_manager.on_start)
        self.fs = self.view.add_filesystem(self.workspace_dir(),
                                           self.file_manager)
        self.fs.set_message.connect(self.editor.show_status_message)
        self.fs.set_warning.connect(self.view.show_message)
        self.file_manager_thread.start()

    def remove_fs(self):
        """
        Remove the file system navigator from the UI.
        """
        self.view.remove_filesystem()
        self.file_manager = None
        self.file_manager_thread = None
        self.fs = None

    def on_data_flood(self):
        """
        Ensure the Files button is active before the REPL is killed off when
        a data flood of the plotter is detected.
        """
        self.set_buttons(mpfiles=True)
        super().on_data_flood()

    def open_file(self, path):
        """
        Tries to open a MicroPython hex file with an embedded Python script.
        """
        text = None
        if path.lower().endswith('.hex'):
            # Try to open the hex and extract the Python script
            try:
                with open(path, newline='') as f:
                    text = uflash.extract_script(f.read())
            except Exception:
                return None
        return text
