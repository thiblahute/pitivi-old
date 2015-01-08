# -*- coding: utf-8 -*-
# Pitivi video editor
#
#       pitivi/timeline/elements.py
#
# Copyright (c) 2013, Mathieu Duponchelle <mduponchelle1@gmail.com>
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

"""
Convention throughout this file:
Every GES element which name could be mistaken with a UI element
is prefixed with a little b, example : bTimeline
"""
import os

from gettext import gettext as _

from gi.repository import GES
from gi.repository import Gtk
from gi.repository import Gdk
from gi.repository import GdkPixbuf

from pitivi.utils import ui
from pitivi import configure
from pitivi.timeline import previewers
from pitivi.utils.loggable import Loggable
from pitivi.utils import timeline as timelineUtils

KEYFRAME_LINE_COLOR = (237, 212, 0)  # "Tango" yellow

CURSORS = {
    GES.Edge.EDGE_START: Gdk.Cursor.new(Gdk.CursorType.LEFT_SIDE),
    GES.Edge.EDGE_END: Gdk.Cursor.new(Gdk.CursorType.RIGHT_SIDE)
}


class TimelineElement(Gtk.Box, timelineUtils.Zoomable, Loggable):

    def __init__(self, element):
        super(TimelineElement, self).__init__()
        timelineUtils.Zoomable.__init__(self)
        Loggable.__init__(self)

        self.bElement = element
        self.bElement.selected = timelineUtils.Selected()

        self.props.vexpand = True

        self._previewer = self._getPreviewer()
        if self._previewer:
            self.add(self._previewer)

        self.show_all()

    def do_get_preferred_width(self):
        wanted_width = max(0, self.nsToPixel(self.bElement.props.duration) - TrimHandle.DEFAULT_WIDTH * 2)

        return wanted_width, wanted_width

    def _getPreviewer(self):
        return None

    def do_draw(self, cr):
        Gtk.Box.do_draw(self, cr)
        self.drawKeyframes(cr)

    def drawKeyframes(self, context):
        if not self.bElement.selected:
            return

        # Add 0.5 so that the line center is at the middle of the pixel,
        # without this the line appears blurry.
        context.set_line_width(ui.PLAYHEAD_WIDTH + 2)
        context.set_source_rgb(*KEYFRAME_LINE_COLOR)
        context.move_to(0, 15)
        context.line_to(self.get_allocated_width(), 15)
        context.stroke()


class VideoUriSource(TimelineElement):

    __gtype_name__ = "PitiviUriVideoSource"

    def __init__(self, element):
        super(VideoUriSource, self).__init__(element)
        self.get_style_context().add_class("VideoUriSource")

    def _getPreviewer(self):
        previewer = previewers.VideoPreviewer(self.bElement)
        previewer.get_style_context().add_class("VideoUriSource")

        return previewer

    def do_get_preferred_height(self):
        return ui.LAYER_HEIGHT / 2, ui.LAYER_HEIGHT


class AudioUriSource(TimelineElement):

    __gtype_name__ = "PitiviAudioUriSource"

    def __init__(self, element):
        super(AudioUriSource, self).__init__(element)
        self.get_style_context().add_class("AudioUriSource")

    def do_get_preferred_height(self):
        return ui.LAYER_HEIGHT / 2, ui.LAYER_HEIGHT

    def _getPreviewer(self):
        previewer = previewers.AudioPreviewer(self.bElement)
        previewer.get_style_context().add_class("AudioUriSource")
        previewer.startLevelsDiscoveryWhenIdle()

        return previewer


class TrimHandle(Gtk.EventBox, Loggable):

    __gtype_name__ = "PitiviTrimHandle"

    DEFAULT_WIDTH = 5

    def __init__(self, clip, edge):
        Gtk.EventBox.__init__(self)
        Loggable.__init__(self)

        self.clip = clip
        self.get_style_context().add_class("Trimbar")
        self.edge = edge

        self.connect("event", self._eventCb)
        self.connect("notify::window", self._windowSetCb)

    def _windowSetCb(self, window, pspec):
        self.props.window.set_cursor(CURSORS[self.edge])

    def _eventCb(self, element, event):
        if event.type == Gdk.EventType.ENTER_NOTIFY:
            # self.error("ENTER Actual Widget is %s" % Gtk.get_event_widget(event))
            self.clip.edit_mode = GES.EditMode.EDIT_TRIM
            self.clip.dragging_edge = self.edge
        elif event.type == Gdk.EventType.LEAVE_NOTIFY:
            self.clip.dragging_edge = GES.Edge.EDGE_NONE
            self.clip.edit_mode = None
            # self.error("LEAVE Actual Widget is %s" % Gtk.get_event_widget(event))

        return False

    def do_get_preferred_width(self):
        return TrimHandle.DEFAULT_WIDTH, TrimHandle.DEFAULT_WIDTH

    def do_draw(self, cr):
        Gtk.EventBox.do_draw(self, cr)
        Gdk.cairo_set_source_pixbuf(cr, GdkPixbuf.Pixbuf.new_from_file(os.path.join(
                                    configure.get_pixmap_dir(), "trimbar-focused.png")), 10, 10)


class Clip(Gtk.EventBox, timelineUtils.Zoomable, Loggable):

    __gtype_name__ = "PitiviClip"

    def __init__(self, layer, bClip):
        super(Clip, self).__init__()
        timelineUtils.Zoomable.__init__(self)
        Loggable.__init__(self)

        self.z_order = -1
        self.layer = layer
        self.timeline = layer.timeline
        self.app = layer.app

        self.bClip = bClip
        self.bClip.ui = self
        self.bClip.selected = timelineUtils.Selected()

        self._audioSource = None
        self._videoSource = None

        self._setupWidget()
        self._savePositionState()
        self._connectWidgetSignals()

        self.edit_mode = None
        self.dragging_edge = GES.Edge.EDGE_NONE

        self._connectGES()

    def do_get_preferred_width(self):
        return self.nsToPixel(self.bClip.props.duration), self.nsToPixel(self.bClip.props.duration)

    def do_get_preferred_height(self):
        parent = self.get_parent()
        return parent.get_allocated_height(), parent.get_allocated_height()

    def _savePositionState(self):
        self._current_start = self.nsToPixel(self.bClip.props.start)
        self._current_duration = self.nsToPixel(self.bClip.props.duration)
        parent = self.get_parent()
        if parent:
            self._current_parent_height = self.get_parent(
            ).get_allocated_height()
        else:
            self._current_parent_height = 0

    def _updatePosition(self):
        parent = self.get_parent()
        start = self.nsToPixel(self.bClip.props.start)
        duration = self.nsToPixel(self.bClip.props.duration)
        parent_height = parent.get_allocated_height()
        parent_width = parent.get_allocated_width()

        # self.error("Position is %s" % start)
        if start != self._current_start or \
                duration != self._current_duration \
                or parent_height != self._current_parent_height:

            self.layer.move(self, start, 0)
            self.set_size_request(duration, parent_height)
            self._savePositionState()

    def _setupWidget(self):
        pass

    def do_draw(self, cr):
        self._updatePosition()
        # self.error("%s drawing" % self)
        Gtk.EventBox.do_draw(self, cr)

    def _clickedCb(self, unused_action, unused_actor):
        if self.timeline.got_dragged:
            # If the timeline just got dragged and @self
            # is the element initiating the mode,
            # do not do anything when the button is
            # released
            self.timeline.got_dragged = False

            return False

        # TODO : Let's be more specific, masks etc ..
        mode = timelineUtils.SELECT
        if self.timeline._container._controlMask:
            if not self.bClip.selected:
                mode = timelineUtils.SELECT_ADD
                self.timeline.current_group.add(
                    self.bClip.get_toplevel_parent())
            else:
                self.timeline.current_group.remove(
                    self.bClip.get_toplevel_parent())
                mode = timelineUtils.UNSELECT
        elif not self.bClip.selected:
            GES.Container.ungroup(self.timeline.current_group, False)
            self.timeline.createSelectionGroup()
            self.timeline.current_group.add(
                self.bClip.get_toplevel_parent())
            self.timeline._container.gui.switchContextTab(self.bClip)

        children = self.bClip.get_toplevel_parent().get_children(True)
        selection = [elem for elem in children if isinstance(elem, GES.UriClip) or
                     isinstance(elem, GES.TransitionClip)]

        self.timeline.selection.setSelection(selection, mode)

        # if self.keyframedElement:
        #    self.showKeyframes(self.keyframedElement, self.prop)

        return False

    def _connectWidgetSignals(self):
        self.connect("button-release-event", self._clickedCb)
        self.connect("event", self._eventCb)

    def _eventCb(self, element, event):
        if event.type == Gdk.EventType.ENTER_NOTIFY:
            ui.set_children_state_recurse(self, Gtk.StateFlags.PRELIGHT)
        elif event.type == Gdk.EventType.LEAVE_NOTIFY:
            ui.unset_children_state_recurse(self, Gtk.StateFlags.PRELIGHT)

        return False

    def _startChangedCb(self, unused_clip, unused_pspec):
        if self.get_parent() is None:
            # FIXME Check why that happens at all (looks like a GTK bug)
            return

        self.layer.move(self, self.nsToPixel(self.bClip.props.start), 0)

    def _durationChangedCb(self, unused_clip, unused_pspec):
        parent = self.get_parent()
        if parent:
            duration = self.nsToPixel(self.bClip.props.duration)
            parent_height = parent.get_allocated_height()
            self.set_size_request(duration, parent_height)

    def _layerChangedCb(self, bClip, unused_pspec):
        bLayer = bClip.props.layer
        if bLayer:
            self.layer = bLayer.ui
        # self.error("SETTING LAYER! %s (prio is: %s)" % (bLayer, bLayer.props.priority))

    def _connectGES(self):
        self.bClip.connect("notify::start", self._startChangedCb)
        self.bClip.connect("notify::inpoint", self._startChangedCb)
        self.bClip.connect("notify::duration", self._durationChangedCb)
        self.bClip.connect("notify::layer", self._layerChangedCb)


class UriClip(Clip):
    __gtype_name__ = "PitiviUriClip"

    def __init__(self, layer, bClip):
        super(UriClip, self).__init__(layer, bClip)

        self.set_tooltip_markup("<span foreground='blue'>%s</span>" %
                                bClip.get_uri())

    def _setupWidget(self):
        self._vbox = Gtk.Box()
        self._vbox.set_orientation(Gtk.Orientation.HORIZONTAL)
        self.add(self._vbox)

        self.leftHandle = TrimHandle(self, GES.Edge.EDGE_START)
        self._vbox.pack_start(self.leftHandle, False, False, 0)

        self._paned = Gtk.Paned.new(Gtk.Orientation.VERTICAL)
        self._vbox.pack_start(self._paned, True, True, 0)

        self.rightHandle = TrimHandle(self, GES.Edge.EDGE_END)
        self._vbox.pack_end(self.rightHandle, False, False, 0)

        for child in self.bClip.get_children(False):
            self._childAdded(self.bClip, child)

        self.get_style_context().add_class("Clip")

    def _childAdded(self, clip, child):
        if isinstance(child, GES.Source):
            if child.get_track_type() == GES.TrackType.AUDIO:
                self._audioSource = AudioUriSource(child)
                child.ui = self._audioSource
                self._paned.pack2(self._audioSource, True, False)
                self._audioSource.set_visible(True)
            elif child.get_track_type() == GES.TrackType.VIDEO:
                self._videoSource = VideoUriSource(child)
                child.ui = self._videoSource
                self._paned.pack1(self._videoSource, True, False)
                self._videoSource.set_visible(True)
        else:
            child.ui = None

    def _childAddedCb(self, clip, child):
        self._childAdded(clip, child)

    def _childRemoved(self, clip, child):
        if child.ui is not None:
            self._paned.remove(child.ui)
            child.ui = None

    def _connectGES(self):
        super(UriClip, self)._connectGES()
        self.bClip.connect("child-added", self._childAddedCb)
        self.bClip.connect("child-removed", self._childRemovedCb)

    def _childRemovedCb(self, clip, child):
        self._childRemoved(clip, child)


class TransitionClip(Clip):

    __gtype_name__ = "PitiviTransitionClip"

    def __init__(self, layer, bClip):
        super(TransitionClip, self).__init__(layer, bClip)
        # self.error("TRANSITION!!")
        self.get_style_context().add_class("TransitionClip")
        self.z_order = 0

        for child in bClip.get_children(True):
            child.selected = timelineUtils.Selected()
        self.bClip.connect("child-added", self._childAddedCb)
        self.connect("state-flags-changed", self._selectedChangedCb)
        self.connect("button-press-event", self._pressEventCb)

        self.set_tooltip_markup("<span foreground='blue'>%s</span>" %
                                str(bClip.props.vtype.value_nick))

    def _childAddedCb(self, clip, child):
        self.error("Adding %s selected" % child)
        child.selected = timelineUtils.Selected()

    def do_draw(self, cr):
        Clip.do_draw(self, cr)

    def _selectedChangedCb(self, unused_widget, flags):
        if flags & Gtk.StateFlags.SELECTED:
            self.timeline._container.app.gui.trans_list.activate(self.bClip)
        else:
            self.timeline._container.app.gui.trans_list.deactivate()

    def _pressEventCb(self, unused_action, unused_widget):
        self.error("HERE")
        selection = {self.bClip}
        self.timeline.selection.setSelection(selection, timelineUtils.SELECT)
        return False

GES_TYPE_UI_TYPE = {
    GES.UriClip.__gtype__: UriClip,
    GES.TransitionClip.__gtype__: TransitionClip
}
