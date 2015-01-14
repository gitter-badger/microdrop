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

import os
import math
import time
import logging
from StringIO import StringIO
from contextlib import closing
import re
import shutil

import gtk
import gobject
import numpy as np

import protocol
from protocol import Protocol
from utility import is_float, is_int, FutureVersionError
from utility.gui import register_shortcuts, textentry_validate,\
        text_entry_dialog
from plugin_manager import ExtensionPoint, IPlugin, SingletonPlugin, \
        implements, PluginGlobals, ScheduleRequest, emit_signal,\
        get_service_class, get_service_instance, get_service_instance_by_name,\
        IAppStatePlugin
from textbuffer_with_undo import UndoableBuffer
from app_context import get_app
import app_state
from utility.gui import yesno


PluginGlobals.push_env('microdrop')


class ProtocolController(SingletonPlugin):
    implements(IPlugin)
    implements(IAppStatePlugin)
    
    def __init__(self):
        self.name = "microdrop.gui.protocol_controller"
        self.builder = None
        self.label_step_number = None
        self.label_step_number = None
        self.button_run_protocol = None
        self.textentry_protocol_repeats = None

    def load_protocol(self, filename):
        app = get_app()
        original_protocol = app.protocol
        p = None
        try:
            p = Protocol.load(filename)
            for name, data in p.plugin_data.items():
                observers = ExtensionPoint(IPlugin)
                service = observers.service(name)
                if not service:
                    logging.warning("Protocol "
                        "requires the %s plugin, however this plugin is "
                        "not available." % (name))
        except FutureVersionError, why:
            logging.error('''\
Could not open protocol:
    %s
It was created with a newer version of the software.
Protocol is version %s, but only up to version %s is supported with this version of the software.'''\
            % (filename, why.future_version, why.current_version))
        except Exception, why:
            logging.error("Could not open %s. %s" % (filename, why))
        if p:
            if original_protocol is None:
                self.create_protocol(p, state=app_state.LOAD_PROTOCOL) 
            else:
                self.swap_protocol(p)
        emit_signal('on_step_run')

    def on_protocol_created(self, protocol):
        protocol.plugin_fields = emit_signal('get_step_fields')
        logging.debug('[ProtocolController] on_protocol_created(): plugin_fields=%s' % protocol.plugin_fields)
        
    def on_protocol_swapped(self, old_protocol, protocol):
        protocol.plugin_fields = emit_signal('get_step_fields')
        logging.debug('[ProtocolController] on_protocol_swapped(): plugin_fields=%s' % protocol.plugin_fields)
        
    def on_plugin_enable(self):
        app = get_app()
        self.builder = app.builder
        
        self.textentry_notes = self.builder.get_object("textview_notes")
        self.textentry_notes.set_buffer(UndoableBuffer())
        self.label_step_number = self.builder.get_object("label_step_number")
        self.textentry_protocol_repeats = self.builder.get_object(
            "textentry_protocol_repeats")        
        self.button_run_protocol = self.builder.get_object("button_run_protocol")
        
        self.menu_protocol = app.builder.get_object('menu_protocol')
        self.menu_new_protocol = app.builder.get_object('menu_new_protocol')
        self.menu_load_protocol = app.builder.get_object('menu_load_protocol')
        self.menu_rename_protocol = app.builder.get_object('menu_rename_protocol')
        self.menu_save_protocol = app.builder.get_object('menu_save_protocol')
        self.menu_save_protocol_as = app.builder.get_object('menu_save_protocol_as')

        app.signals["on_button_first_step_clicked"] = self.on_first_step
        app.signals["on_button_prev_step_clicked"] = self.on_prev_step
        app.signals["on_button_next_step_clicked"] = self.on_next_step
        app.signals["on_button_last_step_clicked"] = self.on_last_step
        app.signals["on_button_run_protocol_clicked"] = self.on_run_protocol
        app.signals["on_menu_new_protocol_activate"] = self.on_new_protocol
        app.signals["on_menu_load_protocol_activate"] = self.on_load_protocol
        app.signals["on_menu_rename_protocol_activate"] = self.on_rename_protocol
        app.signals["on_menu_save_protocol_activate"] = self.on_save_protocol
        app.signals["on_menu_save_protocol_as_activate"] = self.on_save_protocol_as
        app.signals["on_textentry_protocol_repeats_focus_out_event"] = \
                self.on_textentry_protocol_repeats_focus_out
        app.signals["on_textentry_protocol_repeats_key_press_event"] = \
                self.on_textentry_protocol_repeats_key_press
        app.protocol_controller = self
        self._register_shortcuts()

    def on_post_event(self, state, event):
        if type(state) in [app_state.NoDeviceNoProtocol]:
            self.menu_protocol.set_property('sensitive', False)
            self.menu_new_protocol.set_property('sensitive', False)
            self.menu_load_protocol.set_property('sensitive', False)
        else:
            self.menu_protocol.set_property('sensitive', True)
            self.menu_new_protocol.set_property('sensitive', True)
            self.menu_load_protocol.set_property('sensitive', True)
        if type(state) in [app_state.DeviceDirtyProtocol, app_state.DirtyDeviceDirtyProtocol]:
            self.menu_save_protocol.set_property('sensitive', True)
        else:
            self.menu_save_protocol.set_property('sensitive', False)

    def _register_shortcuts(self):
        app = get_app()
        view = app.main_window_controller.view
        shortcuts = {
            'space': self.on_run_protocol,
            'A': self.on_first_step,
            'S': self.on_prev_step,
            'D': self.on_next_step,
            'F': self.on_last_step,
            #'Delete': self.on_delete_step,
        }
        register_shortcuts(view, shortcuts,
                    disabled_widgets=[self.textentry_notes])

        notes_shortcuts = {
            '<Control>z': self.textentry_notes.get_buffer().undo,
            '<Control>y': self.textentry_notes.get_buffer().redo,
        }
        register_shortcuts(view, notes_shortcuts,
                    enabled_widgets=[self.textentry_notes])

    def on_first_step(self, widget=None, data=None):
        app = get_app()
        app.protocol.first_step()
        emit_signal('on_step_run')

    def on_prev_step(self, widget=None, data=None):
        app = get_app()
        app.protocol.prev_step()
        emit_signal('on_step_run')

    def on_next_step(self, widget=None, data=None):
        app = get_app()
        app.protocol.next_step()
        emit_signal('on_step_run')
        
    def on_last_step(self, widget=None, data=None):
        app = get_app()
        app.protocol.last_step()
        emit_signal('on_step_run')

    def on_new_protocol(self, widget=None, data=None):
        self.save_check()
        self.create_protocol()
        emit_signal('on_step_run')

    def save_check(self):
        app = get_app()
        state = app.state.current_state
        if type(state) in [app_state.DeviceDirtyProtocol,
                app_state.DirtyDeviceDirtyProtocol]:
            result = yesno('Protocol %s has unsaved changes.  Save now?'\
                    % app.protocol.name)
            if result == gtk.RESPONSE_YES:
                self.save_protocol()

    def on_load_protocol(self, widget=None, data=None):
        app = get_app()
        self.save_check()
        dialog = gtk.FileChooserDialog(title="Load protocol",
                                       action=gtk.FILE_CHOOSER_ACTION_OPEN,
                                       buttons=(gtk.STOCK_CANCEL,
                                                gtk.RESPONSE_CANCEL,
                                                gtk.STOCK_OPEN,
                                                gtk.RESPONSE_OK))
        dialog.set_default_response(gtk.RESPONSE_OK)
        dialog.set_current_folder(os.path.join(app.get_device_directory(),
                                               app.dmf_device.name,
                                               "protocols"))
        response = dialog.run()
        if response == gtk.RESPONSE_OK:
            filename = dialog.get_filename()
            self.load_protocol(filename)
        dialog.destroy()

    def on_rename_protocol(self, widget=None, data=None):
        self.save_protocol(rename=True)
    
    def on_save_protocol(self, widget=None, data=None):
        self.save_protocol()
    
    def on_save_protocol_as(self, widget=None, data=None):
        self.save_protocol(save_as=True)

    def save_protocol(self, save_as=False, rename=False):
        app = get_app()
        name = app.protocol.name
        if app.dmf_device.name:
            if save_as or rename or app.protocol.name is None:
                # if the dialog is cancelled, name = ""
                if name is None:
                    name=''
                name = text_entry_dialog('Protocol name', name, 'Save protocol')
                if name is None:
                    name=''

            if name:
                path = os.path.join(app.get_device_directory(),
                                    app.dmf_device.name,
                                    "protocols")
                if os.path.isdir(path) == False:
                    os.mkdir(path)

                # current file name
                if app.protocol.name:
                    src = os.path.join(path, app.protocol.name)
                dest = os.path.join(path, name)

                # if the protocol name has changed
                if name != app.protocol.name:
                    app.protocol.name = name
                    self.swap_protocol(app.protocol)

                # if we're renaming
                if rename and os.path.isfile(src):
                    shutil.move(src, dest)
                else: # save the file
                    app.protocol.save(dest)
                    app.state.trigger_event(app_state.PROTOCOL_SAVED)

    def swap_protocol(self, protocol, state=None):
        app = get_app()
        original_protocol = app.protocol
        if state is None:
            state = app_state.LOAD_PROTOCOL
        app.protocol = protocol
        emit_signal("on_protocol_swapped", [original_protocol, app.protocol])
        app.state.trigger_event(state)

    def create_protocol(self, protocol=None, state=None):
        app = get_app()
        if state is None:
            state = app_state.NEW_PROTOCOL
        if protocol is None:
            protocol = Protocol()
        app.protocol = protocol
        emit_signal("on_protocol_created", app.protocol)
        app.state.trigger_event(state)
    
    def on_textentry_protocol_repeats_focus_out(self, widget, data=None):
        self.on_protocol_repeats_changed()
    
    def on_textentry_protocol_repeats_key_press(self, widget, event):
        if event.keyval == gtk.gdk.keyval_from_name('Return'):
            # user pressed enter
            self.on_protocol_repeats_changed()
    
    def on_protocol_repeats_changed(self):
        app = get_app()
        app.protocol.n_repeats = \
            textentry_validate(self.textentry_protocol_repeats,
                app.protocol.n_repeats,
                int)
        emit_signal('on_step_run')

    def on_run_protocol(self, widget=None, data=None):
        app = get_app()
        if app.running:
            self.pause_protocol()
        else:
            self.run_protocol()

    def run_protocol(self):
        app = get_app()
        app.running = True
        self.button_run_protocol.set_image(self.builder.get_object(
            "image_pause"))
        emit_signal("on_protocol_run")
        
        while app.running:
            self.run_step()

    def pause_protocol(self):
        app = get_app()
        app.running = False
        self.button_run_protocol.set_image(self.builder.get_object(
            "image_play"))
        emit_signal("on_protocol_pause")
        app.experiment_log_controller.save()
        
    def run_step(self):
        app = get_app()
        if app.realtime_mode or app.running:
            attempt=0
            while True:
                app.experiment_log.add_step(app.protocol.current_step_number)
                if attempt > 0:
                    app.experiment_log.add_data({"attempt":attempt})
                return_codes = emit_signal("on_step_run")
                if 'Fail' in return_codes.values():
                    self.pause_protocol()
                    logging.error("Protocol failed.")
                    break
                elif 'Repeat' in return_codes.values():
                    attempt+=1
                else:
                    break
        else:
            data = {}
            emit_signal("on_step_run")

        if app.protocol.current_step_number < len(app.protocol) - 1:
            app.protocol.next_step()
        elif app.protocol.current_repetition < app.protocol.n_repeats - 1:
            app.protocol.next_repetition()
        else: # we're on the last step
            self.pause_protocol()

    def _get_dmf_control_fields(self, step_number):
        step = get_app().protocol.get_step(step_number)
        dmf_plugin_name = step.plugin_name_lookup(
            r'wheelerlab.dmf_control_board_', re_pattern=True)
        service = get_service_instance_by_name(dmf_plugin_name)
        if service:
            return service.get_step_values(step_number)
        return None

    def on_step_options_swapped(self, plugin, step_number):
        self.on_step_options_changed(plugin, step_number)

    def on_step_options_changed(self, plugin, step_number):
        logging.debug('[ProtocolController.on_step_options_changed] plugin=%s, step_number=%s'\
            % (plugin, step_number))
        app = get_app()
        if app.protocol:
            step = app.protocol.steps[step_number]
            app.state.trigger_event(app_state.PROTOCOL_CHANGED)

    def set_app_values(self, values_dict):
        logging.debug('[ProtocolController] set_app_values(): '\
                    'values_dict=%s' % (values_dict,))
        elements = self.AppFields(value=values_dict)
        if not elements.validate():
            raise ValueError('Invalid values: %s' % el.errors)
        values = dict([(k, v.value) for k, v in elements.iteritems() if v.value])
        if 'fps_limit' in values:
            self.grabber.set_fps_limit(values['fps_limit'])
        app = get_app()
        app.set_data(self.name, values)
        emit_signal('on_app_options_changed', [self.name], interface=IPlugin)

    def on_step_run(self):
        self._update_labels()
        app = get_app()
        step = app.protocol.current_step()
        for plugin_name in step.plugins:
            emit_signal('on_step_options_swapped',
                    [plugin_name,
                    app.protocol.current_step_number],
                    interface=IPlugin)
        with closing(StringIO()) as sio:
            for plugin_name, fields in app.protocol.plugin_fields.iteritems():
                observers = ExtensionPoint(IPlugin)
                service = observers.service(plugin_name)
                if service is None:
                    # We can end up here if a service has been disabled.
                    # TODO: protocol.plugin_fields should likely be updated
                    #    whenever a plugin is enabled/disabled...
                    continue
                if hasattr(service, 'get_step_value'):
                    print >> sio, '[ProtocolController] plugin.name=%s field_values='\
                            % (plugin_name),
                    print >> sio, [service.get_step_value(f) for f in fields]
            logging.debug(sio.getvalue())

    def on_step_swapped(self, original_step_number, step_number):
        self._update_labels()

    def _update_labels(self):
        app = get_app()
        self.label_step_number.set_text("Step: %d/%d\tRepetition: %d/%d" % 
            (app.protocol.current_step_number + 1,
            len(app.protocol.steps),
            app.protocol.current_repetition + 1,
            app.protocol.n_repeats))
        self.textentry_protocol_repeats.set_text(str(app.protocol.n_repeats))

    def on_dmf_device_created(self, dmf_device):
        self.create_protocol()

    def on_dmf_device_swapped(self, old_dmf_device, dmf_device):
        self.create_protocol()

    def on_app_exit(self):
        app = get_app()
        state = app.state.current_state
        print '[ProtocolController] on_app_exit() %s' % type(state)
        if type(state) in [app_state.DeviceDirtyProtocol,
                app_state.DirtyDeviceDirtyProtocol]:
            result = yesno('Protocol %s has unsaved changes.  Save now?'\
                    % app.protocol.name)
            if result == gtk.RESPONSE_YES:
                self.save_protocol()

    def get_schedule_requests(self, function_name):
        """
        Returns a list of scheduling requests (i.e., ScheduleRequest
        instances) for the function specified by function_name.
        """
        if function_name == 'on_plugin_enable':
            return [ScheduleRequest('microdrop.gui.main_window_controller',
                                    self.name)]
        return []

PluginGlobals.pop_env()
