"""
Copyright 2011-2015 Ryan Fobel and Christian Fobel

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

import traceback
import logging

import gtk
import numpy as np
from flatland import Form, Integer, String, Boolean
from path_helpers import path
import yaml
from pygtkhelpers.ui.extra_widgets import Enum
from pygst_utils.video_pipeline.window_service_proxy import WindowServiceProxy
from pygst_utils.video_source import GstVideoSourceManager

from ..app_context import get_app
from ..logger import logger
from ..plugin_helpers import AppDataController
from ..plugin_manager import (IPlugin, SingletonPlugin, implements,
                              PluginGlobals, ScheduleRequest, emit_signal,
                              get_service_instance_by_name)
from .dmf_device_view import DmfDeviceView

PluginGlobals.push_env('microdrop')


class DmfDeviceViewController(SingletonPlugin, AppDataController):
    implements(IPlugin)

    def __init__(self):
        self.name = "microdrop.gui.dmf_device_view_controller"
        self.view = DmfDeviceView(self, 'device_view')
        self.view.connect('transform-changed', self.on_transform_changed)
        self.recording_enabled = False
        self._video_initialized = False
        self._video_enabled = False
        self._gui_initialized = False
        self._bitrate = None
        self._record_path = None
        self._recording = False
        self._AppFields = None
        self._video_available = False

    @property
    def AppFields(self):
        if self._AppFields is None:
            self._AppFields = self._populate_app_fields()
        return self._AppFields

    def _populate_app_fields(self):
        with WindowServiceProxy(59000) as w:
            self.video_mode_map = w.get_video_mode_map()
            if self.video_mode_map:
                self._video_available = True
            else:
                self._video_available = False
            self.video_mode_keys = sorted(self.video_mode_map.keys())
            if self._video_available:
                self.device_key, self.devices = w.get_video_source_configs()

        field_list = [Integer.named('overlay_opacity').using(default=50,
                                                             optional=True),
                      String.named('transform_matrix')
                      .using(default='', optional=True,
                             properties={'show_in_gui': False})]

        if self._video_available:
            video_mode_enum = Enum.named('video_mode').valued(
                *self.video_mode_keys).using(default=self.video_mode_keys[0],
                                             optional=True)
            video_enabled_boolean = (Boolean.named('video_enabled')
                                     .using(default=False, optional=True,
                                            properties={'show_in_gui': True}))
            recording_enabled_boolean = (Boolean.named('recording_enabled')
                                         .using(default=False, optional=True,
                                                properties={'show_in_gui':
                                                            False}))
            field_list.append(video_mode_enum)
            field_list.append(video_enabled_boolean)
            field_list.append(recording_enabled_boolean)
        return Form.of(*field_list)

    @property
    def video_enabled(self):
        return self._video_enabled

    @video_enabled.setter
    def video_enabled(self, value):
        if not self._video_available and value:
            raise ValueError('Video cannot be enabled with no sources.')
        self._video_enabled = value

    def on_video_started(self, device_view, start_time):
        self.set_app_values(dict(transform_matrix=
                                 self.get_app_value('transform_matrix')))

    def on_transform_changed(self, device_view, array):
        self.set_app_values(dict(transform_matrix=yaml.dump(array.tolist())))

    def on_gui_ready(self):
        self._gui_initialized = True
        gtk.timeout_add(50, self._initialize_video)

    def on_app_options_changed(self, plugin_name):
        try:
            if plugin_name == self.name:
                values = self.get_app_values()
                if self._video_available and 'video_enabled' in values:
                    video_enabled = values['video_enabled']
                    if not (self.video_enabled and video_enabled):
                        if video_enabled:
                            self.video_enabled = True
                        else:
                            self.video_enabled = False
                        self.reset_video()
                if self.video_enabled:
                    if'overlay_opacity' in values:
                        self.view.overlay_opacity =\
                            int(values.get('overlay_opacity'))
                if 'transform_matrix' in values:
                    matrix = yaml.load(values['transform_matrix'])
                    if matrix is not None and len(matrix):
                        matrix = np.array(matrix, dtype='float32')
                        def update_transform(self, matrix):
                            if self.view._proxy and (self.view._proxy
                                                     .pipeline_available()):
                                transform_str = ','.join([str(v)
                                        for v in matrix.flatten()])
                                (self.view._proxy
                                 .set_warp_transform(transform_str))
                                return False
                            return True
                        gtk.timeout_add(10, update_transform, self, matrix)
                if 'recording_enabled' in values:
                    self.recording_enabled = values['recording_enabled']
                if 'video_mode' in values:
                    video_mode = values['video_mode']
                    if video_mode is not None\
                            and video_mode != self.video_mode:
                        self.video_mode = video_mode
        except (Exception,):
            logger.info(''.join(traceback.format_exc()))
            raise

    @property
    def video_mode(self):
        if not hasattr(self, '_video_mode'):
            self._video_mode = self.video_mode_keys[0]
        return self._video_mode

    @video_mode.setter
    def video_mode(self, value):
        '''
        When the video_mode are set, we must force the video
        pipeline to be re-initialized.
        '''
        self._video_mode = value
        self.reset_video()

    def reset_video(self):
        self.view.destroy_video_proxy()
        self._video_initialized = False

    def _initialize_video(self):
        '''
        Initialize video if necessary.

        Note that this function must only be called by the main GTK
        thread.  Otherwise, dead-lock will occur.  Currently, this is
        ensured by calling this function in a gtk.timeout_add() call.
        '''
        if not self._video_initialized:
            if self._gui_initialized and (self._video_available and
                                          self.video_enabled and
                                          self.view.window_xid and
                                          self.video_mode):
                self._video_initialized = True
                selected_mode = self.video_mode_map[self.video_mode]
                caps_str = GstVideoSourceManager.get_caps_string(selected_mode)
                if self.recording_enabled:
                    bitrate = self._bitrate
                    record_path = self._record_path
                else:
                    bitrate = None
                    record_path = None
                self.view._initialize_video(str(selected_mode['device']),
                                            str(caps_str),
                                            record_path=record_path,
                                            bitrate=bitrate)
                self.set_app_values({'transform_matrix':
                                     self.get_app_value('transform_matrix')})
                if self.recording_enabled:
                    self._recording = True
            else:
                x, y, width, height = self.view.widget.get_allocation()
                self.view._initialize_video('',
                                            'video/x-raw-yuv,width={}'
                                            ',height={}'.format(width, height))
                self._video_initialized = True
        return True

    def on_plugin_enable(self):
        AppDataController.on_plugin_enable(self)
        app = get_app()

        self.event_box_dmf_device = (app.builder
                                     .get_object('event_box_dmf_device'))
        self.event_box_dmf_device.add(self.view.device_area)
        self.event_box_dmf_device.show_all()

        def set_channel_states(view, updated_channels, channel_states):
            plugin = get_service_instance_by_name('microdrop.gui'
                                                  '.dmf_device_controller',
                                                  env='microdrop')
            # TODO: Use `StepOptionsController` mixin as base of
            # `DmfDeviceController` to provide `get_step_data` and
            # `set_step_data`.
            plugin.get_step_options().state_of_channels[:] = channel_states
            plugin._notify_observers_step_options_changed()

        self.view.connect('channel-state-changed', set_channel_states)
        app.signals["on_event_box_dmf_device_size_allocate"] =\
            self.on_size_allocate
        app.dmf_device_view_controller = self

    def stop_recording(self):
        self._bitrate = None
        self._record_path = None
        self.reset_video()
        self._recording = False
        logging.info('[DmfDeviceController] recording stopped')

    def start_recording(self, record_path):
        self._bitrate = 150000
        self._record_path = str(path(record_path).abspath())
        self._recording = False
        self.reset_video()
        logging.info('[DmfDeviceController] recording to: {}'.format(
                self._record_path))

    def on_dmf_device_swapped(self, old_device, new_device):
        if old_device is None:
            # Need to reset the video to display the device
            self.reset_video()

    def on_protocol_run(self):
        app = get_app()
        log_dir = path(app.experiment_log.get_log_path())
        video_path = log_dir.joinpath('%s.avi' % log_dir.name)
        if self.recording_enabled:
            self.start_recording(video_path)

    def on_protocol_pause(self):
        if self._recording:
            self.stop_recording()

    def on_app_exit(self):
        self.view.destroy_video_proxy()

    def on_step_options_changed(self, plugin_name, step_number):
        '''
        The step options for the current step have changed.
        If the change was to options affecting this plugin, update state.
        '''
        app = get_app()
        if (app.protocol.current_step_number
            == step_number) and (plugin_name ==
                                 'microdrop.gui.dmf_device_controller'):
            self._update()

    def on_step_swapped(self, old_step_number, step_number):
        self._update()

    def on_size_allocate(self, widget, data=None):
        self.reset_video()

    def _update(self):
        app = get_app()
        if not app.dmf_device:
            return
        plugin = get_service_instance_by_name('microdrop.gui'
                                              '.dmf_device_controller',
                                              env='microdrop')
        channel_states = plugin.get_step_options().state_of_channels

        for id, electrode in app.dmf_device.electrodes.iteritems():
            channels = app.dmf_device.electrodes[id].channels
            if channels:
                # Get the state(s) of the channel(s) connected to this
                # electrode.
                states = channel_states[channels]

                # If all of the states are the same.
                if len(np.nonzero(states == states[0])[0]) == len(states):
                    if states[0] > 0:
                        self.view.electrode_color[id] = [1, 1, 1]
                    else:
                        color = app.dmf_device.electrodes[id].path.color
                        self.view.electrode_color[id] = [c / 255.
                                                         for c in color]
                else:
                    # TODO: This could be used for resistive heating.
                    logger.error("not supported yet")
            else:
                # Assign the color _red_ to any electrode that has no assigned
                # channels.
                self.view.electrode_color[id] = [1, 0, 0]
        self.view.update_draw_queue()

    def get_schedule_requests(self, function_name):
        """
        Returns a list of scheduling requests (i.e., ScheduleRequest
        instances) for the function specified by function_name.
        """
        if function_name == 'on_plugin_enable':
            return [ScheduleRequest('microdrop.gui.config_controller',
                                    self.name),
                    ScheduleRequest('microdrop.gui.dmf_device_controller',
                                    self.name)]
        return []


PluginGlobals.pop_env()
