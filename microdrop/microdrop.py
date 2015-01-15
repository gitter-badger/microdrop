#!/usr/bin/env python
"""
Copyright 2011 Ryan Fobel

This file is part of Microdrop.

Microdrop is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
Foundation, either version 3 of the License, or
(at your option) any later version.

Microdrop is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with Microdrop.  If not, see <http://www.gnu.org/licenses/>.
"""

import os
import sys

from path_helpers import path

# Change directory to where microdrop.py resides, so this program can be
# run from any directory.
root_dir = str(path(__file__).parent.abspath())

if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

import utility as utility

import gtk

settings = gtk.settings_get_default()
# Use a button ordering more consistent with Windows
print 'Use a button ordering more consistent with Windows'
settings.set_property('gtk-alternative-button-order', True)


def except_handler(*args, **kwargs):
    import traceback

    print args, kwargs
    traceback.print_tb(args[2])


if __name__ == '__main__':
    utility.PROGRAM_LAUNCHED = True

    from app import App
    from app_context import get_app

    my_app = get_app()
    sys.excepthook = except_handler
    my_app.run()
