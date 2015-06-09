from threading import Thread

from gi.repository import Clutter, GLib, Gst
from clutter_webcam_viewer import RecordView


def parse_args(args=None):
    """Parses arguments, returns (options, args)."""
    import sys
    from argparse import ArgumentParser

    if args is None:
        args = sys.argv

    parser = ArgumentParser(description='DMF device control UI')
    parser.add_argument('-u', '--dmf-device-uri', required=True)
    parser.add_argument('-i', '--interactive', action='store_true',
                        help='Run UI in background thread (useful for '
                        'running, e.g., from IPython).')

    args = parser.parse_args()
    return args


def main(args):
    Gst.init()
    record_view = RecordView()

    if args.interactive:
        gui_thread = Thread(target=record_view.show_and_run)
        gui_thread.daemon = True
        gui_thread.start()
    else:
        record_view.show()

    while record_view.video_view is None:
        time.sleep(.1)
        print 'waiting for GUI'

    view = record_view.video_view

    def add_dmf_device(view, uri):
        from ..gui.dmf_actor import DmfActor

        actor = DmfActor(uri)
        view.stage.add_actor(actor)
        actor.add_constraint(Clutter.BindConstraint
                             .new(view.stage, Clutter.BindCoordinate.SIZE, 1))
        actor.set_opacity(.5 * 255)

    Clutter.threads_add_idle(GLib.PRIORITY_DEFAULT, add_dmf_device, view,
                             args.dmf_device_uri)

    if args.interactive:
        raw_input()
    else:
        record_view.show_and_run()

    return record_view


if __name__ == '__main__':
    '''
    Demonstrate drag'n'drop webcam feed using Clutter stage.
    '''
    import time

    args = parse_args()
    result = main(args)
