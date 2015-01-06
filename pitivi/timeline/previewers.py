# -*- coding: utf-8 -*-
# Pitivi video editor
#
#       pitivi/timeline/previewers.py
#
# Copyright (c) 2013, Daniel Thul <daniel.thul@gmail.com>
#
# This program is free software; you can redistribute it and/or
# modify it under the terms of the GNU Lesser General Public
# License as published by the Free Software Foundation; either
# version 2.1 of the License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public
# License along with this program; if not, write to the
# Free Software Foundation, Inc., 51 Franklin St, Fifth Floor,
# Boston, MA 02110-1301, USA.

from datetime import datetime, timedelta
from random import randrange
import cairo
import numpy
import os
import pickle
import sqlite3

from gi.repository import Cogl
from gi.repository import GES
from gi.repository import GObject
from gi.repository import GLib
from gi.repository import GdkPixbuf
from gi.repository import Gst
from gi.repository import Gtk

# Our C module optimizing waveforms rendering
try:
    from . import renderer
except ImportError:
    # Running uninstalled?
    import renderer

from pitivi.settings import get_dir, xdg_cache_home
from pitivi.utils.loggable import Loggable
from pitivi.utils.misc import binary_search, filename_from_uri, quantize, quote_uri, hash_file, format_ns
from pitivi.utils.system import CPUUsageTracker
from pitivi.utils.timeline import Zoomable
from pitivi.utils.ui import CONTROL_WIDTH
from pitivi.utils.ui import EXPANDED_SIZE


WAVEFORMS_CPU_USAGE = 30

# A little lower as it's more fluctuating
THUMBNAILS_CPU_USAGE = 20

THUMB_MARGIN_PX = 3
WAVEFORM_UPDATE_INTERVAL = timedelta(microseconds=500000)
# For the waveforms, ensures we always have a little extra surface when
# scrolling while playing.
MARGIN = 500
SAMPLE_DURATION_NS = 10 * 1000 * 1000

PREVIEW_GENERATOR_SIGNALS = {
    "done": (GObject.SIGNAL_RUN_LAST, None, ()),
    "error": (GObject.SIGNAL_RUN_LAST, None, ()),
}


"""
Convention throughout this file:
Every GES element which name could be mistaken with a UI element
is prefixed with a little b, example : bTimeline
"""


class PreviewGeneratorManager():

    """
    Manage the execution of PreviewGenerators
    """

    def __init__(self):
        # The current PreviewGenerator per GES.TrackType.
        self._cpipeline = {}
        # The queue of PreviewGenerators.
        self._pipelines = {
            GES.TrackType.AUDIO: [],
            GES.TrackType.VIDEO: []
        }

    def addPipeline(self, pipeline):
        track_type = pipeline.track_type

        current_pipeline = self._cpipeline.get(track_type)
        if pipeline in self._pipelines[track_type] or \
                pipeline is current_pipeline:
            # Already in the queue or already processing.
            return

        if not self._pipelines[track_type] and current_pipeline is None:
            self._setPipeline(pipeline)
        else:
            self._pipelines[track_type].insert(0, pipeline)

    def _setPipeline(self, pipeline):
        self._cpipeline[pipeline.track_type] = pipeline
        pipeline.connect("done", self._nextPipeline)
        pipeline.startGeneration()

    def _nextPipeline(self, controlled):
        track_type = controlled.track_type
        pipeline = self._cpipeline.pop(track_type, None)
        if pipeline:
            pipeline.disconnect_by_func(self._nextPipeline)

        if self._pipelines[track_type]:
            self._setPipeline(self._pipelines[track_type].pop())


class PreviewGenerator(object):

    """
    Interface to be implemented by classes that generate previews
    It is need to implement it so PreviewGeneratorManager can manage
    those classes
    """

    # We only want one instance of PreviewGeneratorManager to be used for
    # all the generators.
    __manager = PreviewGeneratorManager()

    def __init__(self, track_type):
        """
        @param track_type : GES.TrackType.*
        """
        self.track_type = track_type

    def startGeneration(self):
        raise NotImplemented

    def stopGeneration(self):
        raise NotImplemented

    def becomeControlled(self):
        """
        Let the PreviewGeneratorManager control our execution
        """
        PreviewGenerator.__manager.addPipeline(self)


class VideoPreviewer(Gtk.Layout, PreviewGenerator, Zoomable, Loggable):

    # We could define them in PreviewGenerator, but then for some reason they
    # are ignored.
    __gsignals__ = PREVIEW_GENERATOR_SIGNALS

    def __init__(self, bElement):
        """
        @param bElement : the backend GES.TrackElement
        @param track : the track to which the bElement belongs
        """
        super(VideoPreviewer, self).__init__()
        PreviewGenerator.__init__(self, GES.TrackType.VIDEO)
        Zoomable.__init__(self)
        Loggable.__init__(self)

        # Variables related to the timeline objects
        self.timeline = bElement.get_parent().get_timeline().ui
        self.bElement = bElement
        # Guard against malformed URIs
        self.uri = quote_uri(bElement.props.uri)
        self.duration = bElement.props.duration

        # Variables related to thumbnailing
        self.wishlist = []
        self._thumb_cb_id = None
        self._allAnimated = False
        self._running = False
        # We should have one thumbnail per thumb_period.
        # TODO: get this from the user settings
        self.thumb_period = int(0.5 * Gst.SECOND)
        self.thumb_height = EXPANDED_SIZE - 2 * THUMB_MARGIN_PX
        self.thumb_width = None  # will be set by self._setupPipeline()

        # Maps (quantized) times to Thumbnail objects
        self.thumbs = {}
        self.thumb_cache = get_cache_for_uri(self.uri)

        self.cpu_usage_tracker = CPUUsageTracker()
        self.interval = 500  # Every 0.5 second, reevaluate the situation

        # Connect signals and fire things up
        self.timeline.hadj.connect("value-changed", self._scrollCb)
        self.bElement.connect("notify::duration", self._durationChangedCb)
        self.bElement.connect("notify::in-point", self._inpointChangedCb)
        self.bElement.connect("notify::start", self._startChangedCb)

        self.pipeline = None
        self.becomeControlled()

    # Internal API
    def _update(self, unused_msg_source=None):
        self.props.width_request = self.nsToPixel(self.bElement.get_asset().get_filesource_asset().props.duration)
        self.props.width = self.nsToPixel(self.bElement.get_asset().get_filesource_asset().props.duration)
        if self.thumb_width:
            self._addVisibleThumbnails()
            if self.wishlist:
                self.becomeControlled()

    def _setupPipeline(self):
        """
        Create the pipeline.

        It has the form "playbin ! thumbnailsink" where thumbnailsink
        is a Bin made out of "videorate ! capsfilter ! gdkpixbufsink"
        """
        # TODO: don't hardcode framerate
        self.pipeline = Gst.parse_launch(
            "uridecodebin uri={uri} name=decode ! "
            "videoconvert ! "
            "videorate ! "
            "videoscale method=lanczos ! "
            "capsfilter caps=video/x-raw,format=(string)RGBA,height=(int){height},"
            "pixel-aspect-ratio=(fraction)1/1,framerate=2/1 ! "
            "gdkpixbufsink name=gdkpixbufsink".format(uri=self.uri, height=self.thumb_height))

        # get the gdkpixbufsink and the sinkpad
        self.gdkpixbufsink = self.pipeline.get_by_name("gdkpixbufsink")
        sinkpad = self.gdkpixbufsink.get_static_pad("sink")

        self.pipeline.set_state(Gst.State.PAUSED)

        # Wait for the pipeline to be prerolled so we can check the width
        # that the thumbnails will have and set the aspect ratio accordingly
        # as well as getting the framerate of the video:
        change_return = self.pipeline.get_state(Gst.CLOCK_TIME_NONE)
        if Gst.StateChangeReturn.SUCCESS == change_return[0]:
            neg_caps = sinkpad.get_current_caps()[0]
            self.thumb_width = neg_caps["width"]
        else:
            # the pipeline couldn't be prerolled so we can't determine the
            # correct values. Set sane defaults (this should never happen)
            self.warning("Couldn't preroll the pipeline")
            # assume 16:9 aspect ratio
            self.thumb_width = 16 * self.thumb_height / 9

        decode = self.pipeline.get_by_name("decode")
        decode.connect("autoplug-select", self._autoplugSelectCb)

        # pop all messages from the bus so we won't be flooded with messages
        # from the prerolling phase
        while self.pipeline.get_bus().pop():
            continue
        # add a message handler that listens for the created pixbufs
        self.pipeline.get_bus().add_signal_watch()
        self.pipeline.get_bus().connect("message", self.bus_message_handler)

    def _checkCPU(self):
        """
        Check the CPU usage and adjust the time interval (+10 or -10%) at
        which the next thumbnail will be generated. Even then, it will only
        happen when the gobject loop is idle to avoid blocking the UI.
        """
        usage_percent = self.cpu_usage_tracker.usage()
        if usage_percent < THUMBNAILS_CPU_USAGE:
            self.interval *= 0.9
            self.log(
                'Thumbnailing sped up (+10%%) to a %.1f ms interval for "%s"' %
                (self.interval, filename_from_uri(self.uri)))
        else:
            self.interval *= 1.1
            self.log(
                'Thumbnailing slowed down (-10%%) to a %.1f ms interval for "%s"' %
                (self.interval, filename_from_uri(self.uri)))
        self.cpu_usage_tracker.reset()
        self._thumb_cb_id = GLib.timeout_add(
            self.interval, self._create_next_thumb)

    def _startThumbnailingWhenIdle(self):
        self.debug(
            'Waiting for UI to become idle for: %s', filename_from_uri(self.uri))
        GLib.idle_add(self._startThumbnailing, priority=GLib.PRIORITY_LOW)

    def _startThumbnailing(self):
        if not self.pipeline:
            # Can happen if stopGeneration is called because the clip has been
            # removed from the timeline after the PreviewGeneratorManager
            # started this job.
            return

        self.props.width_request = self.nsToPixel(self.bElement.get_asset().get_filesource_asset().props.duration)
        self.props.width = self.nsToPixel(self.bElement.get_asset().get_filesource_asset().props.duration)

        self.debug(
            'Now generating thumbnails for: %s', filename_from_uri(self.uri))
        query_success, duration = self.pipeline.query_duration(Gst.Format.TIME)
        if not query_success or duration == -1:
            self.debug("Could not determine duration of: %s", self.uri)
            duration = self.duration
        else:
            self.duration = duration

        self.queue = list(range(0, duration, self.thumb_period))

        self._checkCPU()

        self.error("Inpoint = %s" % self.bElement.props.in_point)
        if self.bElement.props.in_point != 0:
            adj = self.get_hadjustment()
            adj.props.page_size = 1.0
            adj.props.value = Zoomable.nsToPixel(self.bElement.props.in_point)
            self.error("Adjustment is %s -- %s -- duration %s px" %
                       (self.get_hadjustment().get_value(),
                        Zoomable.nsToPixel(self.bElement.props.in_point),
                        self.props.width
                        ))
        self._addVisibleThumbnails()
        # Save periodically to avoid the common situation where the user exits
        # the app before a long clip has been fully thumbnailed.
        # Spread timeouts between 30-80 secs to avoid concurrent disk writes.
        random_time = randrange(30, 80)
        GLib.timeout_add_seconds(random_time, self._autosave)

        # Remove the GSource
        return False

    def _create_next_thumb(self):
        if not self.wishlist or not self.queue:
            # nothing left to do
            self.debug("Thumbnails generation complete")
            self.stopGeneration()
            self.thumb_cache.commit()
            return
        else:
            self.debug("Missing %d thumbs", len(self.wishlist))

        wish = self._get_wish()
        if wish:
            time = wish
            self.queue.remove(wish)
        else:
            time = self.queue.pop(0)
        self.log('Creating thumb for "%s"' % filename_from_uri(self.uri))
        # append the time to the end of the queue so that if this seek fails
        # another try will be started later
        self.queue.append(time)
        self.pipeline.seek(1.0,
                           Gst.Format.TIME, Gst.SeekFlags.FLUSH | Gst.SeekFlags.ACCURATE,
                           Gst.SeekType.SET, time,
                           Gst.SeekType.NONE, -1)

        # Remove the GSource
        return False

    def _autosave(self):
        if self.wishlist:
            self.log("Periodic thumbnail autosave")
            self.thumb_cache.commit()
            return True
        else:
            return False  # Stop the timer

    def _get_thumb_duration(self):
        thumb_duration_tmp = Zoomable.pixelToNs(
            self.thumb_width + THUMB_MARGIN_PX)
        # quantize thumb length to thumb_period
        thumb_duration = quantize(thumb_duration_tmp, self.thumb_period)
        # make sure that the thumb duration after the quantization isn't
        # smaller than before
        if thumb_duration < thumb_duration_tmp:
            thumb_duration += self.thumb_period
        # make sure that we don't show thumbnails more often than thumb_period
        return max(thumb_duration, self.thumb_period)

    def _remove_all_children(self):
        for child in self.get_children():
            self.remove(child)

    def _addVisibleThumbnails(self):
        """
        Get the thumbnails to be displayed in the currently visible clip portion
        """
        self._remove_all_children()
        old_thumbs = self.thumbs
        self.thumbs = {}
        self.wishlist = []

        thumb_duration = self._get_thumb_duration()
        element_left, element_right = self._get_visible_range()
        element_left = quantize(element_left, thumb_duration)

        for current_time in range(element_left, element_right, thumb_duration):
            thumb = Thumbnail(self.thumb_width, self.thumb_height)
            self.put(thumb, Zoomable.nsToPixel(current_time - element_left),
                     (self.get_parent().get_allocation().height - self.thumb_height) / 2)
            self.thumbs[current_time] = thumb
            if current_time in self.thumb_cache:
                gdkpixbuf = self.thumb_cache[current_time]
                self.thumbs[current_time].set_from_pixbuf(gdkpixbuf)
                self.thumbs[current_time].set_visible(True)

                # FIXME Handle ANIMATED?
            else:
                self.wishlist.append(current_time)
        self._allAnimated = False

    def _get_wish(self):
        """
        Returns a wish that is also in the queue, or None if no such wish exists
        """
        while True:
            if not self.wishlist:
                return None
            wish = self.wishlist.pop(0)
            if wish in self.queue:
                return wish

    def _setThumbnail(self, time, pixbuf):
        # Q: Is "time" guaranteed to be nanosecond precise?
        # A: Not always.
        # => __tim says: "that's how it should be"
        # => also see gst-plugins-good/tests/icles/gdkpixbufsink-test
        # => Daniel: It is *not* nanosecond precise when we remove the videorate
        #            element from the pipeline
        # => thiblahute: not the case with mpegts
        original_time = time
        if time in self.thumbs:
            thumb = self.thumbs[time]
        else:
            sorted_times = sorted(self.thumbs.keys())
            index = binary_search(sorted_times, time)
            time = sorted_times[index]
            thumb = self.thumbs[time]
            if thumb.has_pixel_data:
                # If this happens, it means the precision of the thumbnail
                # generator is not good enough for the current thumbnail
                # interval.
                # We could consider shifting the thumbnails, but seems like
                # too much trouble for something which does not happen in
                # practice. My last words..
                self.fixme("Thumbnail is already set for time: %s, %s",
                           format_ns(time), format_ns(original_time))
                return
        thumb.set_from_pixbuf(pixbuf)
        if time in self.queue:
            self.queue.remove(time)
        self.thumb_cache[time] = pixbuf

    # Interface (Zoomable)

    def zoomChanged(self):
        self._remove_all_children()
        self._allAnimated = True
        self._update()

    def _get_visible_range(self):
        # Shortcut/convenience variables:
        start = self.bElement.props.start
        in_point = self.bElement.props.in_point
        duration = self.bElement.props.duration
        timeline_left, timeline_right = self._get_visible_timeline_range()

        element_left = timeline_left - start + in_point
        element_left = max(element_left, in_point)
        element_right = timeline_right - start + in_point
        element_right = min(element_right, in_point + duration)

        return (element_left, element_right)

    # TODO: move to Timeline or to utils
    def _get_visible_timeline_range(self):
        # determine the visible left edge of the timeline
        # TODO: isn't there some easier way to get the scroll point of the ScrollActor?
        # timeline_left = -(self.timeline.get_transform().xw - self.timeline.props.x)
        timeline_left = self.timeline.hadj.get_value()
        timeline_right = self.timeline.hadj.get_page_size() + timeline_left

        # convert to nanoseconds
        time_left = Zoomable.pixelToNs(timeline_left)
        time_right = Zoomable.pixelToNs(timeline_right)

        return (time_left, time_right)

    # Callbacks

    def bus_message_handler(self, unused_bus, message):
        if message.type == Gst.MessageType.ELEMENT and \
                message.src == self.gdkpixbufsink:
            struct = message.get_structure()
            struct_name = struct.get_name()
            if struct_name == "preroll-pixbuf":
                stream_time = struct.get_value("stream-time")
                pixbuf = struct.get_value("pixbuf")
                self._setThumbnail(stream_time, pixbuf)
        elif message.type == Gst.MessageType.ASYNC_DONE and \
                message.src == self.pipeline:
            self._checkCPU()
        return Gst.BusSyncReply.PASS

    def _autoplugSelectCb(self, unused_decode, unused_pad, unused_caps, factory):
        # Don't plug audio decoders / parsers.
        if "Audio" in factory.get_klass():
            return True
        return False

    def _scrollCb(self, unused):
        self._update()

    def _startChangedCb(self, unused_bElement, unused_value):
        self._update()

    def _inpointChangedCb(self, unused_bElement, unused_value):
        self.get_hadjustment().set_value(Zoomable.nsToPixel(self.bElement.props.in_point))
        self._update()

    def _durationChangedCb(self, unused_bElement, unused_value):
        new_duration = max(self.duration, self.bElement.props.duration)
        if new_duration > self.duration:
            self.duration = new_duration
            self._update()

    def startGeneration(self):
        self._setupPipeline()
        self._startThumbnailingWhenIdle()

    def stopGeneration(self):
        if self._thumb_cb_id:
            GLib.source_remove(self._thumb_cb_id)
            self._thumb_cb_id = None

        if self.pipeline:
            self.pipeline.set_state(Gst.State.NULL)
            self.pipeline.get_state(Gst.CLOCK_TIME_NONE)
            self.pipeline = None
        self.emit("done")

    def cleanup(self):
        self.stopGeneration()
        Zoomable.__del__(self)


class Thumbnail(Gtk.Image):

    def __init__(self, width, height):
        super(Thumbnail, self).__init__()
        self.width = width
        self.height = height
        self.props.width_request = self.width
        self.props.height_request = self.height
        self.has_pixel_data = False

caches = {}


def get_cache_for_uri(uri):
    if uri in caches:
        return caches[uri]
    else:
        cache = ThumbnailCache(uri)
        caches[uri] = cache
        return cache


class ThumbnailCache(Loggable):

    """Caches thumbnails by key using LRU policy, implemented with heapq.

    Uses a two stage caching mechanism. A limited number of elements are
    held in memory, the rest is being cached on disk using an sqlite db."""

    def __init__(self, uri):
        Loggable.__init__(self)
        self._filehash = hash_file(Gst.uri_get_location(uri))
        self._filename = filename_from_uri(uri)
        thumbs_cache_dir = get_dir(os.path.join(xdg_cache_home(), "thumbs"))
        dbfile = os.path.join(thumbs_cache_dir, self._filehash)
        self._db = sqlite3.connect(dbfile)
        self._cur = self._db.cursor()  # Use this for normal db operations
        self._cur.execute("CREATE TABLE IF NOT EXISTS Thumbs\
                          (Time INTEGER NOT NULL PRIMARY KEY,\
                          Jpeg BLOB NOT NULL)")

    def __contains__(self, key):
        # check if item is present in on disk cache
        self._cur.execute("SELECT Time FROM Thumbs WHERE Time = ?", (key,))
        if self._cur.fetchone():
            return True
        return False

    def __getitem__(self, key):
        self._cur.execute("SELECT * FROM Thumbs WHERE Time = ?", (key,))
        row = self._cur.fetchone()
        if not row:
            raise KeyError(key)
        jpeg = row[1]
        loader = GdkPixbuf.PixbufLoader.new()
        # TODO: what do to if any of the following calls fails?
        loader.write(jpeg)
        loader.close()
        pixbuf = loader.get_pixbuf()
        return pixbuf

    def __setitem__(self, key, value):
        success, jpeg = value.save_to_bufferv(
            "jpeg", ["quality", None], ["90"])
        if not success:
            self.warning("JPEG compression failed")
            return
        blob = sqlite3.Binary(jpeg)
        # Replace if a row with the same time already exists.
        self._cur.execute("DELETE FROM Thumbs WHERE  time=?", (key,))
        self._cur.execute("INSERT INTO Thumbs VALUES (?,?)", (key, blob,))

    def commit(self):
        self.debug(
            'Saving thumbnail cache file to disk for: %s', self._filename)
        self._db.commit()
        self.log("Saved thumbnail cache file: %s" % self._filehash)


class PipelineCpuAdapter(Loggable):

    """
    This pipeline manager will modulate the rate of the provided pipeline.
    It is the responsibility of the caller to set the sync of the sink to True,
    disable QOS and provide a pipeline with a rate of 1.0.
    Doing otherwise would be cheating. Cheating is bad.
    """

    def __init__(self, pipeline):
        Loggable.__init__(self)
        self.pipeline = pipeline
        self.bus = self.pipeline.get_bus()

        self.cpu_usage_tracker = CPUUsageTracker()
        self.rate = 1.0
        self.done = False
        self.ready = False
        self.lastPos = 0
        self._bus_cb_id = None

    def start(self):
        GLib.timeout_add(200, self._modulateRate)
        self._bus_cb_id = self.bus.connect("message", self._messageCb)
        self.done = False

    def stop(self):
        if self._bus_cb_id is not None:
            self.bus.disconnect(self._bus_cb_id)
            self._bus_cb_id = None
        self.pipeline = None
        self.done = True

    def _modulateRate(self):
        """
        Adapt the rate of audio playback (analysis) depending on CPU usage.
        """
        if self.done:
            return False

        usage_percent = self.cpu_usage_tracker.usage()
        self.cpu_usage_tracker.reset()
        if usage_percent >= WAVEFORMS_CPU_USAGE:
            if self.rate < 0.1:
                if not self.ready:
                    self.ready = True
                    self.pipeline.set_state(Gst.State.READY)
                    res, self.lastPos = self.pipeline.query_position(
                        Gst.Format.TIME)
                return True

            if self.rate > 0.0:
                self.rate *= 0.9
                self.log(
                    'Pipeline rate slowed down (-10%%) to %.3f' % self.rate)
        else:
            self.rate *= 1.1
            self.log('Pipeline rate sped up (+10%%) to %.3f' % self.rate)

        if not self.ready:
            res, position = self.pipeline.query_position(Gst.Format.TIME)
        else:
            # This to avoid going back and forth from READY to PAUSED
            if self.rate > 0.5:
                # The message handler will unset ready and seek correctly.
                self.pipeline.set_state(Gst.State.PAUSED)
            return True

        self.pipeline.set_state(Gst.State.PAUSED)
        self.pipeline.seek(self.rate,
                           Gst.Format.TIME,
                           Gst.SeekFlags.FLUSH | Gst.SeekFlags.ACCURATE,
                           Gst.SeekType.SET,
                           position,
                           Gst.SeekType.NONE,
                           -1)
        self.pipeline.set_state(Gst.State.PLAYING)
        self.ready = False
        # Keep the glib timer running:
        return True

    def _messageCb(self, unused_bus, message):
        if not self.ready:
            return
        if message.type == Gst.MessageType.STATE_CHANGED:
            prev, new, pending = message.parse_state_changed()
            if message.src == self.pipeline:
                if prev == Gst.State.READY and new == Gst.State.PAUSED:
                    self.pipeline.seek(1.0,
                                       Gst.Format.TIME,
                                       Gst.SeekFlags.FLUSH | Gst.SeekFlags.ACCURATE,
                                       Gst.SeekType.SET,
                                       self.lastPos,
                                       Gst.SeekType.NONE,
                                       -1)
                    self.ready = False


class AudioPreviewer(Gtk.Layout, PreviewGenerator, Zoomable, Loggable):

    """
    Audio previewer based on the results from the "level" gstreamer element.
    """

    __gsignals__ = PREVIEW_GENERATOR_SIGNALS

    def __init__(self, bElement):
        super(AudioPreviewer, self).__init__()
        PreviewGenerator.__init__(self, GES.TrackType.AUDIO)
        Zoomable.__init__(self)
        Loggable.__init__(self)

        self.pipeline = None
        self.discovered = False
        self.bElement = bElement
        self.timeline = bElement.get_parent().get_timeline().ui

        # Guard against malformed URIs
        self._uri = quote_uri(bElement.props.uri)

        # FIXME, what is that about?
        # self.set_content_scaling_filters(
        #    Clutter.ScalingFilter.NEAREST, Clutter.ScalingFilter.NEAREST)

        self.width = 0
        self._num_failures = 0
        self.lastUpdate = None

        self.adapter = None
        self.surface = None
        self.timeline.hadj.connect("value-changed", self._scrolledCb)

        self._callback_id = 0

    def startLevelsDiscoveryWhenIdle(self):
        self.debug('Waiting for UI to become idle for: %s',
                   filename_from_uri(self._uri))

        GLib.idle_add(self._startLevelsDiscovery, priority=GLib.PRIORITY_LOW)

    def _startLevelsDiscovery(self):
        self.log('Preparing waveforms for "%s"' % filename_from_uri(self._uri))
        filename = hash_file(Gst.uri_get_location(self._uri)) + ".wave"
        cache_dir = get_dir(os.path.join(xdg_cache_home(), "waves"))
        filename = os.path.join(cache_dir, filename)

        if os.path.exists(filename):
            self.samples = pickle.load(open(filename, "rb"))
            self._startRendering()
        else:
            self.wavefile = filename
            self._launchPipeline()

    def _launchPipeline(self):
        self.debug(
            'Now generating waveforms for: %s', filename_from_uri(self._uri))
        self.peaks = None
        self.pipeline = Gst.parse_launch("uridecodebin name=decode uri=" + self._uri +
                                         " ! audioconvert ! level name=wavelevel interval=%i post-messages=true ! fakesink qos=false name=faked" % SAMPLE_DURATION_NS)
        faked = self.pipeline.get_by_name("faked")
        faked.props.sync = True
        self._wavelevel = self.pipeline.get_by_name("wavelevel")
        decode = self.pipeline.get_by_name("decode")
        decode.connect("autoplug-select", self._autoplugSelectCb)
        bus = self.pipeline.get_bus()
        bus.add_signal_watch()

        duration = self.bElement.get_parent().get_asset().get_duration()
        self.nSamples = int(duration / SAMPLE_DURATION_NS)
        bus.connect("message", self._busMessageCb)
        self.becomeControlled()

    def set_size(self, unused_width, unused_height):
        if self.discovered:
            self._maybeUpdate()

    def zoomChanged(self):
        self._maybeUpdate()

    def _maybeUpdate(self):
        if self.discovered:
            self.log('Checking if the waveform for "%s" needs to be redrawn' %
                     self._uri)
            if self.lastUpdate is None or datetime.now() - self.lastUpdate > WAVEFORM_UPDATE_INTERVAL:
                # Last update was long ago or never.
                self._compute_geometry()
            else:
                if self._callback_id:
                    GLib.source_remove(self._callback_id)
                self._callback_id = GLib.timeout_add(
                    500, self._compute_geometry)

    def _compute_geometry(self):
        self._callback_id = 0
        self.log("Computing the clip's geometry for waveforms")
        self.lastUpdate = datetime.now()
        width_px = self.nsToPixel(self.bElement.props.duration)
        if width_px <= 0:
            return
        absolute_left_px = self.nsToPixel(self.bElement.props.start)
        left = absolute_left_px - self.timeline.hadj.get_value()
        # Take into account the timeline width, to avoid building
        # huge clips when the timeline is zoomed in a lot.
        timeline_width = self.timeline.get_allocation().width - CONTROL_WIDTH
        right = min(left + width_px, self.timeline.hadj.get_value() + timeline_width + MARGIN)
        self.width = int(right - left)
        if self.width < 0:
            # Out of the view window.
            return

        # Calculate the first and the last sample to be displayed.
        # We need to take duration and inpoint into account.
        duration = self.bElement.get_asset().get_filesource_asset().get_duration()
        in_point = self.bElement.props.in_point
        self.start = int(self.samples_count * in_point / duration)
        if self.bElement.props.duration:
            duration_samples = self.samples_count * self.bElement.props.duration / duration
        else:
            duration_samples = self.samples_count
        self.end = int(self.start + duration_samples)

        self.set_size(self.width, EXPANDED_SIZE)
        self.props.width_request = self.width
        self.props.height_request = EXPANDED_SIZE

    def _prepareSamples(self):
        # Let's go mono.
        if len(self.peaks) > 1:
            samples = (
                numpy.array(self.peaks[0]) + numpy.array(self.peaks[1])) / 2
        else:
            samples = numpy.array(self.peaks[0])

        self.samples = samples.tolist()
        f = open(self.wavefile, 'wb')
        pickle.dump(self.samples, f)

    def _startRendering(self):
        self.samples_count = len(self.samples)
        self.discovered = True
        self.start = 0
        self.end = self.samples_count
        self._compute_geometry()
        if self.adapter:
            self.adapter.stop()

    def _busMessageCb(self, bus, message):
        if message.src == self._wavelevel:
            s = message.get_structure()
            p = None
            if s:
                p = s.get_value("rms")

            if p:
                st = s.get_value("stream-time")

                if self.peaks is None:
                    self.peaks = []
                    for channel in p:
                        self.peaks.append([0] * int(self.nSamples))

                pos = int(st / SAMPLE_DURATION_NS)
                if pos >= len(self.peaks[0]):
                    return

                for i, val in enumerate(p):
                    if val < 0:
                        val = 10 ** (val / 20) * 100
                        self.peaks[i][pos] = val
                    else:
                        self.peaks[i][pos] = self.peaks[i][pos - 1]
            return

        if message.type == Gst.MessageType.EOS:
            self._prepareSamples()
            self._startRendering()
            self.stopGeneration()

        elif message.type == Gst.MessageType.ERROR:
            if self.adapter:
                self.adapter.stop()
                self.adapter = None
            # Something went wrong TODO : recover
            self.stopGeneration()
            self._num_failures += 1
            if self._num_failures < 2:
                self.warning("Issue during waveforms generation: %s"
                             " for the %ith time, trying again with no rate "
                             " modulation", message.parse_error(),
                             self._num_failures)
                bus.disconnect_by_func(self._busMessageCb)
                self._launchPipeline()
                self.becomeControlled()
            else:
                self.error("Issue during waveforms generation: %s"
                           "Abandonning", message.parse_error())

        elif message.type == Gst.MessageType.STATE_CHANGED:
            prev, new, pending = message.parse_state_changed()
            if message.src == self.pipeline:
                if prev == Gst.State.READY and new == Gst.State.PAUSED:
                    self.pipeline.seek(1.0,
                                       Gst.Format.TIME,
                                       Gst.SeekFlags.FLUSH | Gst.SeekFlags.ACCURATE,
                                       Gst.SeekType.SET,
                                       0,
                                       Gst.SeekType.NONE,
                                       -1)

                # In case we failed previously, we won't modulate next time
                elif not self.adapter and prev == Gst.State.PAUSED and \
                        new == Gst.State.PLAYING and self._num_failures == 0:
                    self.adapter = PipelineCpuAdapter(self.pipeline)
                    self.adapter.start()

    def _autoplugSelectCb(self, unused_decode, unused_pad, unused_caps, factory):
        # Don't plug video decoders / parsers.
        if "Video" in factory.get_klass():
            return True
        return False

    def do_draw(self, context):
        if not self.discovered:
            return
        if self.width < 0:
            # Out of the view window.
            return

        if self.surface:
            self.surface.finish()
        samples = self.samples[self.start:self.end]
        width = int(self.width)
        height = int(self.get_parent().get_allocation().height)
        self.surface = renderer.fill_surface(samples, width, height)

        context.set_operator(cairo.OPERATOR_OVER)
        context.set_source_surface(self.surface, 0, 0)
        context.paint()

    def _scrolledCb(self, unused):
        self._maybeUpdate()

    def startGeneration(self):
        self.pipeline.set_state(Gst.State.PLAYING)
        if self.adapter is not None:
            self.adapter.start()

    def stopGeneration(self):
        if self.adapter is not None:
            self.adapter.stop()
            self.adapter = None

        if self.pipeline:
            self.pipeline.set_state(Gst.State.NULL)
            self.pipeline.get_state(Gst.CLOCK_TIME_NONE)

        self.emit("done")

    def cleanup(self):
        self.stopGeneration()
        self.timeline.disconnect_by_func(self._scrolledCb)
        Zoomable.__del__(self)
