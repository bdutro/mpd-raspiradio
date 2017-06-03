import re
import gui
import timers
from mpd import MPDClient, CommandError
from threading import Thread, Event
import configparser
import atexit

CONFIG_FILE = '/etc/raspiradio.conf'

class RaspiradioFrontend(object):
    def __init__(self, config):
        self.client = MPDClient()
        self.client.connect("localhost", 6600)
        self.gui_update_client = MPDClient()
        self.gui_update_client.connect("localhost", 6600)
        self.cur_ui = None
        self.gui = gui.Gui(config, 'raspiradio')
        self.set_gui_mode(gui.GuiModes.CLOCK)
        self.gui_update_thread = timers.UpdateInterval(1.0/config.getint('raspiradio', 'refresh_rate'), self.playback_position_update)
        self.cur_pos = 0
        self.timeout_thread = timers.Timeout(config.getint('raspiradio', 'inactivity_timeout'), self.switch_to_clock)
        self.mpd_update_thread = Thread(target=self.run)
        self.mpd_stop_event = Event()

    def run(self):
        new_status = self.client.status()
        new_elapsed = self.client.currentsong()['elapsed']

        while not self.mpd_stop_event.is_set():
            status = new_status
            elapsed = new_elapsed

            self.client.idle('player')

            if self.mpd_stop_event.is_set():
                break

            new_status = self.client.status()
            new_elapsed = new_status['elapsed']

            diffkeys = [k for k in status if status[k] != new_status[k]]

            if 'songid' in diffkeys:
                self.track_playback_started(new_elapsed)
                continue

            if 'state' in diffkeys:
                old_state = status['status']
                new_state = new_status['status']
                if new_state == 'stop':
                    self.track_playback_ended(new_elapsed)
                elif new_state == 'play':
                    if old_state == 'stop':
                        self.track_playback_started(new_elapsed)
                    else:
                        self.track_playback_resumed(new_elapsed)
                elif new_state == 'pause':
                    self.track_playback_paused(new_elapsed)
                else:
                    raise ValueError('Unknown value: {}'.format(new_state))
                continue

            if elapsed != new_elapsed:
                self.seeked(new_elapsed)
        self.cancel_timeout()
        self.stop_position_update()

    def start(self):
        self.mpd_update_thread.start()

    def stop(self):
        self.mpd_stop_event.set()
        try:
            self.client.noidle()
        except CommandError:
            pass
        self.mpd_update_thread.join()
        self.client.close()
        self.gui_update_client.close()

    def start_position_update(self):
        self.gui_update_thread.start()

    def stop_position_update(self):
        self.gui_update_thread.stop()

    def playback_position_update(self):
        self.set_progress(self.gui_update_client.status()['elapsed'])

    def switch_to_clock(self):
        self.set_gui_mode(gui.GuiModes.CLOCK)

    def get_gui_mode(self):
        return self.gui.get_mode()

    def set_gui_mode(self, mode):
        self.gui.set_mode(mode)
        self.cur_ui = self.gui.get_ui()

    def start_timeout(self):
        self.timeout_thread.start()

    def cancel_timeout(self):
        self.timeout_thread.stop()
        if self.get_gui_mode() != gui.GuiModes.PLAYBACK:
            self.set_gui_mode(gui.GuiModes.PLAYBACK)

    def track_playback_started(self, elapsed):
        self.cancel_timeout()
        self.stop_position_update()
        track = self.client.currentsong()
        self.cur_ui.set_artist(track['artist'])
        self.cur_ui.set_album(track['album'])
        self.cur_ui.set_title(track['title'])
        self.cur_ui.set_track(track['track'])
        self.cur_ui.set_track_length(track['duration'])
        self.set_progress(elapsed, force_redraw=True)
        self.start_position_update()

    def track_playback_ended(self, time_position):
        self.start_timeout()
        self.stop_position_update()
        self.set_progress(time_position, force_redraw=True)

    def track_playback_paused(self, time_position):
        self.start_timeout()
        self.stop_position_update()
        self.set_progress(time_position, force_redraw=True)

    def track_playback_resumed(self, time_position):
        self.cancel_timeout()
        self.set_progress(time_position, force_redraw=True)
        self.start_position_update()

    def seeked(self, time_position):
        self.stop_position_update()
        self.set_progress(time_position, force_redraw=True)
        self.start_position_update()

    def set_progress(self, new_pos, force_redraw=False):
        if new_pos != self.cur_pos or force_redraw:
            self.cur_pos = new_pos
            self.cur_ui.set_progress(self.cur_pos)
            self.cur_ui.draw()

if __name__ == "__main__":
    config = configparser.ConfigParser()
    config.read(CONFIG_FILE)

    frontend = RaspiradioFrontend(config)
    frontend.start()
    atexit.register(lambda f: f.stop(), frontend)
