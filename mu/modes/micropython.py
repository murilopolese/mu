"""
A mode for working with any MicroPython enabled board.

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
import ctypes
from subprocess import check_output
from mu.modes.base import BaseMode
import binascii

class MicroPythonMode(MultiBoardBase):
    """
    Represents the functionality required by the Adafruit mode.
    """

    name = _('MicroPython')
    description = _("Use MicroPython on any board.")
    icon = 'micropython'
    save_timeout = 30
    connected = True
    force_interrupt = False  #: NO keyboard interrupt on serial connection.
    # Modules built into MicroPython which mustn't be used as file names
    # for source code.
    module_names = {'storage', 'os', 'touchio', 'machine', 'bitbangio',
                    'digitalio', 'audiobusio', 'multiterminal', 'nvm',
                    'pulseio', 'usb_hid', 'analogio', 'time', 'busio',
                    'random', 'audioio', 'sys', 'math', 'builtins'}

    def actions(self):
        """
        Return an ordered list of actions provided by this module. An action
        is a name (also used to identify the icon) , description, and handler.
        """
        buttons = [
            {
                'name': 'serial',
                'display_name': _('Serial'),
                'description': _('Open a serial connection to your device.'),
                'handler': self.toggle_repl,
                'shortcut': '',
            },
            {
                'name': 'run',
                'display_name': _('Run'),
                'description': _('Execute code from editor on board.'),
                'handler': self.run,
                'shortcut': '',
            },
            {
                'name': 'stop',
                'display_name': _('Stop'),
                'description': _('Stop code running on board.'),
                'handler': self.stop,
                'shortcut': '',
            },
            ]
        return buttons

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
            # write code to serial
            serial.write(bytes(code, 'ascii'))
            self.exitRawRepl(serial)

    def enterRawRepl(self, serial):
        serial.write(b'\x01')

    def exitRawRepl(self, serial):
        serial.write(b'\x04') # CTRL-D
        serial.write(b'\x02') # CTRL-B

    def stop(self):
        """
        Send keyboard interrupt.
        """
        if self.view.serial:
            self.view.serial.write(b'\x03') # CTRL-C

    def api(self):
        """
        Return a list of API specifications to be used by auto-suggest and call
        tips.
        """
        return []
