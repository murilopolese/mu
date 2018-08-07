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
import subprocess
from time import sleep
from tokenize import TokenError
from mu.logic import HOME_DIRECTORY
from mu.contrib import uflash
from mu.contrib import pixelfs as pixelfs
from mu.modes.api import MICROBIT_APIS, SHARED_APIS
from mu.modes.base import MicroPythonMode
from PyQt5.QtCore import QObject, QThread, pyqtSignal, QTimer
from PyQt5.QtWidgets import QMessageBox

# We can run without nudatus
can_minify = False

logger = logging.getLogger(__name__)

class DeviceFlasher(QThread):
    """
    Used to flash the Pixel Kit in a non-blocking manner.
    """
    # Emitted when flashing the Pixel Kit fails for any reason.
    on_flash_fail = pyqtSignal(str)
    on_step = pyqtSignal(str)

    def __init__(self, port):
        QThread.__init__(self)
        self.port = port

    def erase_flash(self):
        erase_flash = 'python mu/contrib/esptool.py --baud 921600 --port {0} erase_flash'.format(self.port)
        p = subprocess.Popen(erase_flash, stdout=subprocess.PIPE, shell=True)
        result = b''
        while True:
            out = p.stdout.readline()
            if out == b'' and p.poll() != None:
                break
            if out != b'':
                logger.info(out)
                result += out
                self.on_step.emit("{0}: {1}".format(_("Erasing flash"), out.decode('utf-8')))
        return result

    def write_flash(self, fname=''):
        write_flash = 'python mu/contrib/esptool.py --baud 921600 --port {0} write_flash 0x1000 {1}'.format(self.port, fname)
        p = subprocess.Popen(write_flash, stdout=subprocess.PIPE, shell=True)
        result = b''
        line = b''
        while True:
            out = p.stdout.read(1)
            if out == b'' and p.poll() != None:
                break
            if out != b'':
                if out == b'\r' or out == b'\n':
                    logger.info(line)
                    self.on_step.emit("{0}: {1}".format(_("Writing flash"), line.decode('utf-8')))
                    result += line
                    line = b''
                else:
                    line += out
        return result

    def download_firmware(self):
        import tempfile
        import urllib.request
        # Check if there is internet connection
        url = 'http://micropython.org/resources/firmware/esp32-20180511-v1.9.4.bin'
        f = tempfile.NamedTemporaryFile()
        f.close()
        logger.info("Downloading firmware to {0}".format(f.name))
        self.on_step.emit(_("Downloading firmware."))
        urllib.request.urlretrieve(url, f.name)
        return f.name

    def run(self):
        """
        Flash the device.
        """
        try:
            filename = self.download_firmware()
            erase_result = self.erase_flash()
            write_result = self.write_flash(filename)
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
        serial = self.view.serial
        if serial and self.view.current_tab and self.view.current_tab.text():
            code = self.view.current_tab.text()
            self.enterRawRepl(serial)
            serial.write(bytes(code, 'ascii'))
            sleep(0.01)
            self.exitRawRepl(serial)

    def enterRawRepl(self, serial):
        serial.write(b'\x01')
        sleep(0.01)

    def exitRawRepl(self, serial):
        serial.write(b'\x04') # CTRL-D
        sleep(0.01)
        serial.write(b'\x02') # CTRL-B
        sleep(0.01)

    def stop(self):
        """
        Send keyboard interrupt.
        """
        if not self.repl:
            self.toggle_repl(self)
        if self.view.serial:
            self.view.serial.write(b'\x03') # CTRL-C

    def flash(self):
        from time import sleep
        message = _("Flash your Pixel Kit with MicroPython.")
        information = _("Make sure you have internet connection and don't "
                        "disconnect your device during the process. It "
                        "might take a minute or two but you will only need"
                        "to do it once.")
        if self.view.show_confirmation(message, information) != QMessageBox.Cancel:
            port, serial = pixelfs.find_pixelkit()
            if port:
                self.set_buttons(mpflash=False, mpfiles=False, run=False, stop=False, repl=False)
                self.flash_thread = DeviceFlasher(port)
                self.flash_thread.finished.connect(self.flash_finished)
                self.flash_thread.on_flash_fail.connect(self.flash_failed)
                self.flash_thread.on_step.connect(self.on_step)
                self.flash_thread.start()
            else:
                self.flash_failed('No Pixel Kit was found.')


    def flash_finished(self):
        self.set_buttons(mpflash=True, mpfiles=True, run=True, stop=True, repl=True)
        self.editor.show_status_message(_('Pixel Kit was flashed. Have fun!'))
        message = _("Pixel Kit was flashed. Have fun!")
        information = _("Your Pixel Kit now has MicroPython on it. If you want "
                        "to revert it to the original firmware, please "
                        "download the Kano Code App and follow the onboarding "
                        "process.")
        self.view.show_message(message, information, 'Warning')
        logger.info('Flash finished.')
        self.flash_thread = None
        self.flash_timer = None

    def flash_failed(self, error):
        self.set_buttons(mpflash=True, mpfiles=True, run=True, stop=True, repl=True)
        logger.info('Flash failed.')
        logger.error(error)
        message = _("There was a problem flashing the Pixel Kit.")
        information = _("Please do not disconnect the device until flashing"
                        " has completed. Please check the logs for more"
                        " information.")
        self.view.show_message(message, information, 'Warning')
        self.editor.show_status_message(_('Pixel Kit could not be flashed. Please restart the Pixel Kit and try again.'))
        if self.flash_timer:
            self.flash_timer.stop()
            self.flash_timer = None
        self.flash_thread = None

    def on_step(self, message):
        self.editor.show_status_message(message)

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
