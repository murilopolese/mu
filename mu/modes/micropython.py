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
from mu.modes.base import MicroPythonMode as VendorMicroPythonMode
import binascii

class MicroPythonMode(VendorMicroPythonMode):
    """
    Represents the functionality required by the Adafruit mode.
    """

    name = _('MicroPython')
    description = _("Use MicroPython on any board.")
    icon = 'micropython'
    save_timeout = 30  #: Don't autosave on Adafruit boards. Casues a restart.
    connected = True  #: is the Adafruit board connected.
    force_interrupt = True  #: NO keyboard interrupt on serial connection.
    valid_boards = False
    # Modules built into CircuitPython which mustn't be used as file names
    # for source code.
    module_names = {'storage', 'os', 'touchio', 'microcontroller', 'bitbangio',
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
                'shortcut': 'CTRL+Shift+U',
            },
            {
                'name': 'run',
                'display_name': _('Run'),
                'description': _('Execute code from editor on board.'),
                'handler': self.run,
                'shortcut': 'CTRL+Shift+R',
            },
            ]
        return buttons

    def run(self):
        if not self.repl:
            self.toggle_repl(self)
        s = self.view.serial
        if self.view.current_tab and self.view.current_tab.text():
            code = self.view.current_tab.text()
            # enter raw repl mode
            s.write(b'\x01')
            # write code
            s.write(bytes(code, 'ascii'))
            # execute code
            s.write(b'\x04')
            # exit raw repl mode
            s.write(b'\r\x02')


    def api(self):
        """
        Return a list of API specifications to be used by auto-suggest and call
        tips.
        """
        return []
