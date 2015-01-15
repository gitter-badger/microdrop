"""
Copyright 2011 Ryan Fobel

This file is part of dmf_control_board.

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
import sys
from StringIO import StringIO
from contextlib import closing
from collections import namedtuple
import logging
import re

from pyutilib.component.core import Interface, ExtensionPoint, implements, \
    Plugin, PluginGlobals
import pyutilib.component.loader
from path_helpers import path
import gtk

import utility
import task_scheduler

if utility.PROGRAM_LAUNCHED:
    from pyutilib.component.core import SingletonPlugin
else:
    from pyutilib.component.config import ManagedPlugin as SingletonPlugin


PluginGlobals.push_env('microdrop.managed')
PluginGlobals.pop_env()


PluginGlobals.push_env('microdrop')


ScheduleRequest = namedtuple('ScheduleRequest', 'before after')


# Workaround to allow Sphinx autodoc to run.  If the program is not actually
# running, we are just being imported here, so declare plugin interfaces as
# plain-old objects, rather than Interface sub-classes.
if not utility.PROGRAM_LAUNCHED:
    class IPlugin(object):
        __interface_namespace__ = None


    class IWaveformGenerator(object):
        __interface_namespace__ = None


    class ILoggingPlugin(object):
        __interface_namespace__ = None


    class IVideoPlugin(object):
        __interface_namespace__ = None


else:
    class ILoggingPlugin(Interface):
        def on_debug(self, record):
            pass

        def on_info(self, record):
            pass

        def on_warning(self, record):
            pass

        def on_error(self, record):
            pass

        def on_critical(self, record):
            pass


    class IWaveformGenerator(Interface):
        def set_voltage(self, voltage):
            """
            Set the waveform voltage.

            Parameters:
                voltage : RMS voltage
            """
            pass

        def set_frequency(self, frequency):
            """
            Set the waveform frequency.

            Parameters:
                frequency : frequency in Hz
            """
            pass


    class IPlugin(Interface):
        def get_schedule_requests(self, function_name):
            """
            Returns a list of scheduling requests (i.e., ScheduleRequest
            instances) for the function specified by function_name.
            """
            return []

        def on_plugin_disable(self):
            """
            Handler called once the plugin instance is disabled.
            """
            pass

        def on_plugin_enable(self):
            """
            Handler called once the plugin instance is enabled.

            Note: if you inherit your plugin from AppDataController and don't
            implement this handler, by default, it will automatically load all
            app options from the config file. If you decide to overide the
            default handler, you should call:

                super(PluginClass, self).on_plugin_enable()

            to retain this functionality.
            """
            pass

        def on_plugin_enabled(self, env, plugin):
            """
            Handler called to notify that a plugin has been enabled.

            Note that this signal is broadcast to all plugins
            implementing the IPlugin interface, whereas the
            on_plugin_enable method is called directly on the plugin
            that is being enabled.
            """
            pass

        def on_plugin_disabled(self, env, plugin):
            """
            Handler called to notify that a plugin has been disabled.

            Note that this signal is broadcast to all plugins
            implementing the IPlugin interface, whereas the
            on_plugin_disable method is called directly on the plugin
            that is being disabled.
            """
            pass

        def on_app_exit(self):
            """
            Handler called just before the Microdrop application exists.
            """
            pass

        def on_protocol_swapped(self, old_protocol, protocol):
            """
            Handler called when a different protocol is swapped in (e.g., when
            a protocol is loaded or a new protocol is created).
            """
            pass

        def on_protocol_changed(self):
            """
            Handler called when a protocol is modified.
            """
            pass

        def on_protocol_run(self):
            """
            Handler called when a protocol starts running.
            """
            pass

        def on_protocol_pause(self):
            """
            Handler called when a protocol is paused.
            """
            pass

        def on_dmf_device_swapped(self, old_dmf_device, dmf_device):
            """
            Handler called when a different DMF device is swapped in (e.g., when
            a new device is loaded).
            """
            pass

        def on_dmf_device_changed(self):
            """
            Handler called when a DMF device is modified (e.g., channel
            assignment, scaling, etc.). This signal is also sent when a new
            device is imported or loaded from outside of the main device
            directory.
            """
            pass

        def on_experiment_log_changed(self, experiment_log):
            """
            Handler called when the current experiment log changes (e.g., when a
            protocol finishes running.
            """
            pass

        def on_experiment_log_selection_changed(self, data):
            """
            Handler called whenever the experiment log selection changes.

            Parameters:
                data : experiment log data (list of dictionaries, one per step)
                    for the selected steps
            """
            pass

        def on_app_options_changed(self, plugin_name):
            """
            Handler called when the app options are changed for a particular
            plugin.  This will, for example, allow for GUI elements to be
            updated.

            Parameters:
                plugin : plugin name for which the app options changed
            """
            pass

        def on_step_options_changed(self, plugin, step_number):
            """
            Handler called when the step options are changed for a particular
            plugin.  This will, for example, allow for GUI elements to be
            updated based on step specified.

            Parameters:
                plugin : plugin instance for which the step options changed
                step_number : step number that the options changed for
            """
            pass

        def on_step_options_swapped(self, plugin, old_step_number, step_number):
            """
            Handler called when the step options are changed for a particular
            plugin.  This will, for example, allow for GUI elements to be
            updated based on step specified.

            Parameters:
                plugin : plugin instance for which the step options changed
                step_number : step number that the options changed for
            """
            pass

        def on_step_swapped(self, old_step_number, step_number):
            """
            Handler called when the current step is swapped.
            """
            pass


        def on_step_run(self):
            """
            Handler called whenever a step is executed. Note that this signal
            is only emitted in realtime mode or if a protocol is running.

            Plugins that handle this signal must emit the on_step_complete
            signal once they have completed the step. The protocol controller
            will wait until all plugins have completed the current step before
            proceeding.
            """
            pass

        def on_step_complete(self, plugin_name, return_value=None):
            """
            Handler called whenever a plugin completes a step.

            return_value can be one of:
                None
                'Repeat' - repeat the step
                or 'Fail' - unrecoverable error (stop the protocol)
            """
            pass

        def on_step_created(self, step_number):
            pass

        def get_step_form_class(self):
            pass

        def get_step_values(self, step_number=None):
            pass

    class IVideoPlugin(Interface):
        def on_new_frame(self, frame):
            pass


def load_plugins(plugins_dir='plugins'):
    plugins_dir = path(plugins_dir)
    logging.info('Loading plugins:')
    if plugins_dir.parent.abspath() not in sys.path:
        sys.path.insert(0, plugins_dir.parent.abspath())

    for d in plugins_dir.dirs():
        package = (d / path('microdrop'))
        if package.isdir():
            try:
                logging.info('\t %s' % package.abspath())
                import_statement = 'import %s.%s.microdrop' % \
                    (plugins_dir.name, d.name)
                logging.debug(import_statement)
                exec(import_statement)
            except Exception, why:
                logging.info(''.join(traceback.format_exc()))
                logging.error('Error loading %s plugin.' % d.name)

    # Create an instance of each of the plugins, but set it to disabled
    e = PluginGlobals.env('microdrop.managed')
    for class_ in e.plugin_registry.values():
        service = class_()
        service.disable()


def log_summary():
    observers = ExtensionPoint(IPlugin)
    logging.info('Registered plugins:')
    for observer in observers:
        logging.info('\t %s' % observer)
    observers = ExtensionPoint(IWaveformGenerator)
    logging.info('Registered function generator plugins:')
    for observer in observers:
        logging.info('\t %s' % observer)
    observers = ExtensionPoint(ILoggingPlugin)
    logging.info('Registered logging plugins:')
    for observer in observers:
        logging.info('\t %s' % observer)
    observers = ExtensionPoint(IVideoPlugin)
    logging.info('Registered video plugins:')
    for observer in observers:
        logging.info('\t %s' % observer)


def get_plugin_names(env=None):
    if env is None:
        env = 'pca'
    e = PluginGlobals.env(env)
    return list(e.plugin_registry.keys())


def get_service_class(name, env='microdrop.managed'):
    e = PluginGlobals.env(env)
    if name not in e.plugin_registry:
        raise KeyError, 'No plugin registered with name: %s' % name
    return e.plugin_registry[name]


def get_service_instance_by_name(name, env='microdrop.managed'):
    e = PluginGlobals.env(env)
    plugins = [p for i, p in enumerate(e.services) if name == p.name]
    if plugins:
        return plugins[0]
    else:
        raise KeyError, 'No plugin registered with name: %s' % name


def get_service_instance_by_package_name(name, env='microdrop.managed'):
    e = PluginGlobals.env(env)
    plugins = [p for i, p in enumerate(e.services) \
               if name == get_plugin_package_name(p.__class__.__module__)]
    if plugins:
        return plugins[0]
    else:
        raise KeyError, 'No plugin registered with package name: %s' % name


def get_plugin_package_name(class_name):
    match = re.search(r'plugins\.(?P<name>.*?)\.microdrop',
                      class_name)
    if match is None:
        logging.error('Could not determine package name from: %s'\
                % class_name)
        return None
    return match.group('name')


def get_service_instance(class_, env='microdrop.managed'):
    e = PluginGlobals.env(env)
    for service in e.services:
        if isinstance(service, class_):
            # A plugin of this type is registered
            return service
    return None


def get_service_names(env='microdrop.managed'):
    e = PluginGlobals.env(env)
    service_names = []
    for name in get_plugin_names(env):
        plugin_class = e.plugin_registry[name]
        service = get_service_instance(plugin_class, env=env)
        service_names.append(service.name)
    return service_names


def get_schedule(observers, function):
    # Query plugins for schedule requests for 'function'
    schedule_requests = {}
    for observer in observers.values():
        if hasattr(observer, 'get_schedule_requests'):
            schedule_requests[observer.name] =\
                    observer.get_schedule_requests(function)

    if schedule_requests:
        scheduler = task_scheduler.TaskScheduler(observers.keys())
        for request in [r for name, requests in schedule_requests.items() for r in requests]:
            try:
                scheduler.request_order(*request)
            except AssertionError:
                logging.info('[PluginManager] emit_signal(%s) could not '\
                        'add schedule request %s' % (function, request))
                continue
        return scheduler.get_schedule()
    else:
        return observers.keys()


def get_observers(function, interface=IPlugin):
    observers = {}
    for obs in ExtensionPoint(interface):
        if hasattr(obs, function):
            observers[obs.name] = obs
    return observers


def emit_signal(function, args=[], interface=IPlugin):
    observers = get_observers(function, interface)
    schedule = get_schedule(observers, function)
    return_codes = {}
    for observer_name in schedule:
        observer = observers[observer_name]
        logging.debug('emit_signal: %s.%s()' % (observer.name, function))
        try:
            if type(args) is not list:
                args = [args]
            f = getattr(observer, function)
            return_codes[observer.name] = f(*args)
        except Exception, why:
            with closing(StringIO()) as message:
                if hasattr(observer, "name"):
                    if interface == ILoggingPlugin:
                        # If this is a logging plugin, do not try to log
                        # since that will result in infinite recursion.
                        # Instead, just continue onto the next plugin.
                        continue
                    print >> message, \
                        '%s plugin crashed processing %s signal.' % \
                        (observer.name, function)
                print >> message, 'Reason:', str(why)
                logging.error(message.getvalue().strip())
            logging.info(''.join(traceback.format_exc()))
    return return_codes


def enable(name, env='microdrop.managed'):
    service = get_service_instance_by_name(name, env)
    if not service.enabled():
        service.enable()
        logging.info('[PluginManager] Enabled plugin: %s' % name)
    if hasattr(service, "on_plugin_enable"):
        service.on_plugin_enable()
    emit_signal('on_plugin_enabled', [env, service])


def disable(name, env='microdrop.managed'):
    service = get_service_instance_by_name(name, env)
    if service and service.enabled():
        service.disable()
        if hasattr(service, "on_plugin_disable"):
            service.on_plugin_disable()
        emit_signal('on_plugin_disabled', [env, service])
        logging.info('[PluginManager] Disabled plugin: %s' % name)


PluginGlobals.pop_env()
