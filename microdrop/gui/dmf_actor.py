from gi.repository import Clutter, GLib
from svg_model.data_frame import (close_paths, get_path_infos,
                                  get_bounding_box)
from clutter_webcam_viewer.svg import PathActor, aspect_fit
import zmq
import pandas as pd


class DmfDevice(object):
    '''
    Connect to Microdrop DMF device controller plugin and provide bidirectional
    updates for channel states.

    Three ZeroMQ socket connections are used:

     - `REQ`: Synchronous request/response (e.g., initial channel states).
     - `PUSH`: Asynchronous notification of change in local states.
     - `SUB`: Asynchronous notification of remote change in channel states.

    TODO
    ====

     - Parse hostname from `uri` (which is used for the `REQ` socket) and use
       host for setting up the `PUSH` and `SUB` sockets.  Currently, the `PUSH`
       and `SUB` sockets use `localhost`.
     - Periodically request a full synchronization of channel states from DMF
       device controller.
    '''
    def __init__(self, uri):
        self.uri = uri
        self.ctx = zmq.Context.instance()
        self.ports = self._command('ports')
        self.electrode_channels = self._command('electrode_channels')
        self.df_svg = self._command('device_svg_frame')
        self.sync_states()

        self.sub = zmq.Socket(self.ctx, zmq.SUB)
        self.sub.connect('tcp://localhost:%s' % self.ports.pub)
        self.sub.setsockopt(zmq.SUBSCRIBE, '')

    def toggle_channels(self, channels):
        '''
        Toggle the state of the specified channels.
        '''
        self.channel_states[channels] = ~self.channel_states[channels]

    def sync_states(self):
        '''
        Request state of all channels from DMF device controller and update
        local state.
        '''
        channel_states = self._command('sync')
        self.channel_states = pd.Series(channel_states, dtype=bool)
        self.channel_states.index.name = 'channel'

    def _command(self, cmd):
        '''
        Send a request to the DMF device controller response socket.

        This is used, for example, to request initial channel states.
        '''
        req = zmq.Socket(self.ctx, zmq.REQ)
        req.connect(self.uri)
        req.send_pyobj({'command': cmd})

        while not req.poll(50):
            pass

        response = req.recv_pyobj()
        return response['result']

    def push_channel_states(self):
        '''
        Notify DMF device controller of the local channel states.
        '''
        ctx = zmq.Context.instance()
        push = zmq.Socket(ctx, zmq.PUSH)
        push.connect('tcp://localhost:%s' % self.ports.pull)
        push.send_pyobj(self.channel_states)

    def spin(self, timeout=zmq.NOBLOCK):
        '''
        Check for any channel state updates on the local subscription socket.

        __NB__ The Microdrop DMF device controller plugin publishes all channel
        state changes.
        '''
        updated = False
        while self.sub.poll(timeout):
            updated = True
            diff_states = self.sub.recv_pyobj()
            self.channel_states[diff_states.index] = diff_states
            if not timeout == zmq.NOBLOCK:
                break
        return updated


class DmfActor(Clutter.Group):
    '''
    Draw the device associated with a remote Microdrop DMF device controller
    instance.  Update the color of each electrode according to corresponding
    actuation state.
    '''
    def __init__(self, uri, actuated_color='#ffffff',
                 non_actuated_color='#000000'):
        super(DmfActor, self).__init__()
        self.actuated_color = actuated_color
        self.non_actuated_color = non_actuated_color
        self.device = DmfDevice(uri)

        self.df_device = close_paths(self.device.df_svg)
        self.bbox = get_bounding_box(self.df_device)
        self.df_paths = get_path_infos(self.df_device)

        for path_id, df_i in self.df_device.groupby('path_id'):
            actor = PathActor(path_id, df_i)
            actor.set_size(self.bbox.width, self.bbox.height)
            actor.color = non_actuated_color
            actor.connect("button-release-event", self.clicked_cb)
            self.add_actor(actor)
        self.connect("allocation-changed", aspect_fit, self.bbox)
        Clutter.threads_add_idle(GLib.PRIORITY_DEFAULT, self.update_ui)
        Clutter.threads_add_timeout(GLib.PRIORITY_DEFAULT, 100,
                                    self.refresh_channels)

    def refresh_channels(self, timeout=zmq.NOBLOCK):
        '''
        Check for incoming channel state updates on subscription socket and
        update the UI accordingly.
        '''
        if self.device.spin(timeout):
            self.update_ui()
        return True

    def update_ui(self):
        '''
        Update the UI attributes of the each electrode actor based on the on
        corresponding channel state.
        '''
        for p in self.get_children():
            channels = self.device.electrode_channels.ix[p.path_id]
            actuated = self.device.channel_states[channels].any()
            p.color = (self.actuated_color if actuated else
                       self.non_actuated_color)

    def clicked_cb(self, actor, event):
        '''
        Toggle the state of the channels corresponding to the electrode that
        was clicked.
        '''
        channels = self.device.electrode_channels.ix[actor.path_id]
        self.device.toggle_channels(channels)
        self.update_ui()
        self.device.push_channel_states()
