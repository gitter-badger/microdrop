"""
Copyright 2011 Ryan Fobel

This file is part of Microdrop.

Microdrop is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

Microdrop is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with Microdrop.  If not, see <http://www.gnu.org/licenses/>.
"""
import sys
import os
import traceback
import shutil
from copy import deepcopy
try:
    import cPickle as pickle
except ImportError:
    import pickle

import gtk
import numpy as np
from flatland import Form
from path_helpers import path
from pygtkhelpers.delegates import SlaveView
from pygtkhelpers.ui.extra_widgets import Directory
from pygtkhelpers.ui.extra_dialogs import text_entry_dialog
from microdrop_utility.gui import yesno
from microdrop_utility import copytree
import zmq
from zmq_helpers.utils import bind_to_random_port

from ..app_context import get_app
from ..dmf_device import DmfDevice
from ..logger import logger
from ..plugin_helpers import AppDataController
from ..plugin_manager import (IPlugin, SingletonPlugin, implements,
                              PluginGlobals, ScheduleRequest, emit_signal)
from .. import base_path

PluginGlobals.push_env('microdrop')


class DmfDeviceOptions(object):
    def __init__(self, state_of_channels=None):
        app = get_app()
        if state_of_channels is None:
            self.state_of_channels = np.zeros(app.dmf_device.max_channel() + 1)
        else:
            self.state_of_channels = deepcopy(state_of_channels)


class DmfDeviceInfoView(SlaveView):
    def __init__(self, controller):
        self.controller = controller
        super(DmfDeviceInfoView, self).__init__()

    def create_ui(self):
        service_port = self.controller.df_socks.port.rep
        box = gtk.HBox()
        label = gtk.Label('Device controller (port=%s)' % service_port)

        def launch_device_controller_viewer(button):
            from subprocess import Popen, PIPE

            args = [sys.executable, '-m', 'microdrop.bin.dmf_device_control',
                    '-u', 'tcp://localhost:%s' %  service_port]
            process = Popen(args, stdout=PIPE, stderr=PIPE)
        open_ui_button = gtk.Button('Launch UI...')
        open_ui_button.connect('clicked', launch_device_controller_viewer)

        box.pack_start(label, False, False, 0)
        box.pack_end(open_ui_button, False, False, 0)
        box.show_all()

        self.widget.pack_start(box, False, False, 0)


# TODO: Use `StepOptionsController` mixin to provide `get_step_data` and
# `set_step_data` API.
class DmfDeviceController(SingletonPlugin, AppDataController):
    implements(IPlugin)

    AppFields = Form.of(Directory.named('device_directory')
                        .using(default='', optional=True))

    def __init__(self):
        self.name = "microdrop.gui.dmf_device_controller"
        self.previous_device_dir = None
        self._modified = False

    @property
    def modified(self):
        return self._modified

    @modified.setter
    def modified(self, value):
        self._modified = value
        self.menu_save_dmf_device.set_sensitive(value)

    def on_app_options_changed(self, plugin_name):
        try:
            if plugin_name == self.name:
                values = self.get_app_values()
                if 'device_directory' in values:
                    self.apply_device_dir(values['device_directory'])
        except (Exception,):
            logger.info(''.join(traceback.format_exc()))
            raise

    def apply_device_dir(self, device_directory):
        app = get_app()

        # if the device directory is empty or None, set a default
        if not device_directory:
            device_directory = path(app.config.data['data_dir']).joinpath(
                'devices')
            self.set_app_values({'device_directory': device_directory})

        if self.previous_device_dir and (device_directory ==
                                         self.previous_device_dir):
            # If the data directory hasn't changed, we do nothing
            return False

        device_directory = path(device_directory)
        if self.previous_device_dir:
            device_directory.makedirs_p()
            if device_directory.listdir():
                result = yesno('Merge?', '''\
Target directory [%s] is not empty.  Merge contents with
current devices [%s] (overwriting common paths in the target
directory)?''' % (device_directory, self.previous_device_dir))
                if not result == gtk.RESPONSE_YES:
                    return False

            original_directory = path(self.previous_device_dir)
            for d in original_directory.dirs():
                copytree(d, device_directory.joinpath(d.name))
            for f in original_directory.files():
                f.copyfile(device_directory.joinpath(f.name))
            original_directory.rmtree()
        elif not device_directory.isdir():
            # if the device directory doesn't exist, copy the skeleton dir
            device_directory.parent.makedirs_p()
            base_path().joinpath('devices').copytree(device_directory)
        self.previous_device_dir = device_directory
        return True

    def on_plugin_enable(self):
        import pandas as pd

        AppDataController.on_plugin_enable(self)
        app = get_app()

        self.menu_load_dmf_device = app.builder.get_object('menu_load_dmf_device')
        self.menu_import_dmf_device = app.builder.get_object('menu_import_dmf_device')
        self.menu_rename_dmf_device = app.builder.get_object('menu_rename_dmf_device')
        self.menu_save_dmf_device = app.builder.get_object('menu_save_dmf_device')
        self.menu_save_dmf_device_as = app.builder.get_object('menu_save_dmf_device_as')

        app.signals["on_menu_load_dmf_device_activate"] = self.on_load_dmf_device
        app.signals["on_menu_import_dmf_device_activate"] = \
                self.on_import_dmf_device
        app.signals["on_menu_rename_dmf_device_activate"] = self.on_rename_dmf_device
        app.signals["on_menu_save_dmf_device_activate"] = self.on_save_dmf_device
        app.signals["on_menu_save_dmf_device_as_activate"] = self.on_save_dmf_device_as
        app.dmf_device_controller = self

        # disable menu items until a device is loaded
        self.menu_rename_dmf_device.set_sensitive(False)
        self.menu_save_dmf_device.set_sensitive(False)
        self.menu_save_dmf_device_as.set_sensitive(False)
        self.zmq_ctx = zmq.Context.instance()
        self.df_socks = pd.DataFrame([zmq.Socket(self.zmq_ctx, zmq.REP),
                                      zmq.Socket(self.zmq_ctx, zmq.PULL),
                                      zmq.Socket(self.zmq_ctx, zmq.PUB)],
                                     index=['rep', 'pull', 'pub'],
                                     columns=['sock'])
        self.df_socks['port'] = [bind_to_random_port(s)
                                 for s in self.df_socks.sock]
        for k, p in self.df_socks.port.iteritems():
            logger.info('[DmfDeviceController].df_socks["%s"].port: %s' %
                        (k, p))

        self.device_info_view = DmfDeviceInfoView(self)
        self.device_info_view.show()

        box = app.main_window_controller.vbox2
        box.pack_start(self.device_info_view.widget, False, False, 0)
        box.reorder_child(self.device_info_view.widget, 0)

        def check_pull(self):
            channel_states = None

            while self.df_socks.sock.rep.poll(zmq.NOBLOCK):
                raw = False
                response = None
                # Request is waiting
                request = self.df_socks.sock.rep.recv_pyobj()
                try:
                    if request['command'] == 'sync':
                        response = self.get_step_options().state_of_channels
                    elif request['command'] == 'ports':
                        response = self.df_socks.port
                    elif request['command'] == 'electrode_name_map_keys':
                        response = app.dmf_device.electrode_name_map.keys()
                    elif request['command'] == 'electrode_name_map':
                        response = app.dmf_device.electrode_name_map
                    elif request['command'] == 'device_svg_frame':
                        response = app.dmf_device.get_svg_frame()
                    elif request['command'] == 'electrode_channels':
                        response = app.dmf_device.get_electrode_channels()
                except AttributeError:
                    pass
                self.df_socks.sock.rep.send_pyobj({'result': response,
                                                   'raw': raw})

            while self.df_socks.sock.pull.poll(zmq.NOBLOCK):
                # Request is waiting
                msg = self.df_socks.sock.pull.recv_pyobj()

                if msg is None:
                    continue

                channel_states = pd.Series(self.get_step_options()
                                           .state_of_channels, dtype=bool)
                if not isinstance(msg, pd.Series):
                    msg = pd.Series(msg, dtype=bool)
                    assert(channel_states.shape[0] == msg.shape[0])

                channel_states = channel_states[msg.index.tolist()]
                diff_index = channel_states[channel_states != msg].index
                diff_states = msg[diff_index.tolist()].astype(bool)

                if diff_states.shape[0] > 0:
                    # TODO: Use `StepOptionsController` mixin as base of
                    # `DmfDeviceController` to provide `get_step_data` and
                    # `set_step_data`.
                    channel_states = self.get_step_options().state_of_channels
                    channel_states[diff_states.index.tolist()] = diff_states
                    logger.info('[DmfDeviceController] Update state from '
                                'request. %s' % diff_states)
                    self._notify_observers_step_options_changed(publish=False)
                    self.df_socks.sock.pub.send_pyobj(diff_states)
            return True

        # Check for messages on ZeroMQ sockets every 10 ms.
        self.check_timer_id = gtk.timeout_add(100, check_pull, self)

    def on_app_exit(self):
        self.save_check()

    def get_default_options(self):
        return DmfDeviceOptions()

    def get_step_options(self, step=None):
        '''
        Return a FeedbackOptions object for the current step in the protocol.
        If none exists yet, create a new one.
        '''
        app = get_app()
        options = app.protocol.current_step().get_data(self.name)
        if options is None:
            # No data is registered for this plugin (for this step).
            options = self.get_default_options()
            app.protocol.current_step().set_data(self.name, options)
        return options

    def load_device(self, filename):
        app = get_app()
        self.modified = False
        device = app.dmf_device
        try:
            logger.info('[DmfDeviceController].load_device: %s' % filename)
            device = DmfDevice.load(str(filename))
            if path(filename).parent.parent != app.get_device_directory():
                logger.info('[DmfDeviceController].load_device: Import new '
                            'device.')
                self.modified = True
            else:
                logger.info('[DmfDeviceController].load_device: load existing '
                            'device.')
            emit_signal("on_dmf_device_swapped", [app.dmf_device,
                                                  device])
        except Exception, e:
            logger.error('Error loading device: %s.' % e)
            logger.info(''.join(traceback.format_exc()))

    def save_check(self):
        app = get_app()
        if self.modified:
            result = yesno('Device %s has unsaved changes.  Save now?' %
                           app.dmf_device.name)
            if result == gtk.RESPONSE_YES:
                self.save_dmf_device()

    def save_dmf_device(self, save_as=False, rename=False):
        '''
        Save device configuration.

        If `save_as=True`, we are saving a copy of the current device with a
        new name.

        If `rename=True`, we are saving the current device with a new name _(no
        new copy is created)_.
        '''
        app = get_app()

        name = app.dmf_device.name
        # If the device has no name, try to get one.
        if save_as or rename or name is None:
            if name is None:
                name = ""
            name = text_entry_dialog('Device name', name, 'Save device')
            if name is None:
                name = ""

        if name:
            # Construct the directory name for the current device.
            if app.dmf_device.name:
                src = os.path.join(app.get_device_directory(),
                                   app.dmf_device.name)
            # Construct the directory name for the new device _(which is the
            # same as the current device, if we are not renaming or "saving
            # as")_.
            dest = os.path.join(app.get_device_directory(), name)

            # If we're renaming, move the old directory.
            if rename and os.path.isdir(src):
                if src == dest:
                    return
                if os.path.isdir(dest):
                    logger.error("A device with that "
                                 "name already exists.")
                    return
                shutil.move(src, dest)

            # Create the directory for the new device name, if it doesn't
            # exist.
            if not os.path.isdir(dest):
                os.mkdir(dest)

            # If the device name has changed, update the application device
            # state.
            if name != app.dmf_device.name:
                app.dmf_device.name = name
                # Update GUI to reflect updated name.
                app.main_window_controller.update_device_name_label()

            # Save the device to the new target directory.
            app.dmf_device.save(os.path.join(dest, "device"))
            # Reset modified status, since save acts as a checkpoint.
            self.modified = False

    def on_step_swapped(self, old_step_number, step_number):
        # An actuation state for each channel is maintained for each protocol
        # step.  Therefore, trigger a notification whenever a new step is
        # selected.
        self._notify_observers_step_options_changed()

    # TODO: Use `StepOptionsController` mixin # to provide `get_step_data` and
    # `set_step_data` API.
    def _notify_observers_step_options_changed(self, publish=True):
        import pandas as pd

        app = get_app()
        if not app.dmf_device:
            return
        if publish:
            channel_states = pd.Series(self.get_step_options()
                                       .state_of_channels, dtype=bool)
            self.df_socks.sock.pub.send_pyobj(channel_states)
        emit_signal('on_step_options_changed',
                    [self.name, app.protocol.current_step_number],
                    interface=IPlugin)

    def get_schedule_requests(self, function_name):
        """
        Returns a list of scheduling requests (i.e., ScheduleRequest
        instances) for the function specified by function_name.
        """
        if function_name == 'on_plugin_enable':
            return [ScheduleRequest('microdrop.gui.config_controller',
                                    self.name),
                    ScheduleRequest('microdrop.gui.main_window_controller',
                                    self.name)]
        elif function_name == 'on_dmf_device_swapped':
            return [ScheduleRequest('microdrop.app', self.name),
                    ScheduleRequest('microdrop.gui.protocol_controller',
                                    self.name)]
        return []

    # GUI callbacks

    def on_load_dmf_device(self, widget, data=None):
        self.save_check()
        app = get_app()
        directory = app.get_device_directory()
        dialog = gtk.FileChooserDialog(title="Load device",
                                       action=gtk.FILE_CHOOSER_ACTION_OPEN,
                                       buttons=(gtk.STOCK_CANCEL,
                                                gtk.RESPONSE_CANCEL,
                                                gtk.STOCK_OPEN,
                                                gtk.RESPONSE_OK))
        dialog.set_default_response(gtk.RESPONSE_OK)
        if directory:
            dialog.set_current_folder(directory)
        response = dialog.run()
        if response == gtk.RESPONSE_OK:
            filename = dialog.get_filename()
            self.load_device(filename)
        dialog.destroy()

    def on_import_dmf_device(self, widget, data=None):
        self.save_check()
        app = get_app()
        dialog = gtk.FileChooserDialog(title="Import device",
                                       action=gtk.FILE_CHOOSER_ACTION_OPEN,
                                       buttons=(gtk.STOCK_CANCEL,
                                                gtk.RESPONSE_CANCEL,
                                                gtk.STOCK_OPEN,
                                                gtk.RESPONSE_OK))
        filter = gtk.FileFilter()
        filter.set_name("*.svg")
        filter.add_pattern("*.svg")
        dialog.add_filter(filter)
        dialog.set_default_response(gtk.RESPONSE_OK)
        response = dialog.run()
        filename = dialog.get_filename()
        dialog.destroy()
        if response == gtk.RESPONSE_OK:
            try:
                dmf_device = DmfDevice.load_svg(filename)
                self.modified = True
                emit_signal("on_dmf_device_swapped", [app.dmf_device,
                                                          dmf_device])
            except Exception, e:
                logger.error('Error importing device. %s' % e)
                logger.info(''.join(traceback.format_exc()))

    def on_rename_dmf_device(self, widget, data=None):
        self.save_dmf_device(rename=True)

    def on_save_dmf_device(self, widget, data=None):
        self.save_dmf_device()

    def on_save_dmf_device_as(self, widget, data=None):
        self.save_dmf_device(save_as=True)

    def on_dmf_device_swapped(self, old_device, new_device):
        self.menu_rename_dmf_device.set_sensitive(True)
        self.menu_save_dmf_device_as.set_sensitive(True)

    def on_dmf_device_changed(self):
        self.modified = True

PluginGlobals.pop_env()
