# PiTiVi , Non-linear video editor
#
#       pitivi/timeline/timeline_undo.py
#
# Copyright (c) 2009, Alessandro Decina <alessandro.d@gmail.com>
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

import ges

from pitivi.utils.signal import Signallable
from pitivi.undo.undo import PropertyChangeTracker, UndoableAction
from pitivi.undo.effect import TrackEffectAdded, TrackEffectRemoved

from pitivi.undo.effect import EffectGstElementPropertyChangeTracker


class TimelineObjectPropertyChangeTracker(PropertyChangeTracker):
    # no out-point
    property_names = ["start", "duration", "in-point",
            "media-duration", "priority", "selected"]

    _disabled = False

    def connectToObject(self, obj):
        PropertyChangeTracker.connectToObject(self, obj)
        self.timeline = obj.get_layer().get_timeline()

    def _propertyChangedCb(self, timeline_object, value, property_name):
        if self.timeline.is_updating():
            PropertyChangeTracker._propertyChangedCb(self,
                    timeline_object, value, property_name)


class KeyframeChangeTracker(Signallable):
    __signals__ = {
        "keyframe-moved": ["keyframe"]
    }

    def __init__(self):
        self.keyframes = None
        self.obj = None

    def connectToObject(self, obj):
        self.obj = obj
        self.keyframes = self._takeCurrentSnapshot(obj)
        obj.connect("keyframe-added", self._keyframeAddedCb)
        obj.connect("keyframe-removed", self._keyframeRemovedCb)
        obj.connect("keyframe-moved", self._keyframeMovedCb)

    def _takeCurrentSnapshot(self, obj):
        keyframes = {}
        for keyframe in self.obj.getKeyframes():
            keyframes[keyframe] = self._getKeyframeSnapshot(keyframe)

        return keyframes

    def disconnectFromObject(self, obj):
        self.obj = None
        obj.disconnect_by_func(self._keyframeMovedCb)

    def _keyframeAddedCb(self, interpolator, keyframe):
        self.keyframes[keyframe] = self._getKeyframeSnapshot(keyframe)

    def _keyframeRemovedCb(self, interpolator, keyframe, old_value=None):
        pass

    def _keyframeMovedCb(self, interpolator, keyframe, old_value=None):
        old_snapshot = self.keyframes[keyframe]
        new_snapshot = self._getKeyframeSnapshot(keyframe)
        self.keyframes[keyframe] = new_snapshot

        self.emit("keyframe-moved", interpolator,
                keyframe, old_snapshot, new_snapshot)

    def _getKeyframeSnapshot(self, keyframe):
        return (keyframe.mode, keyframe.time, keyframe.value)


class TimelineObjectPropertyChanged(UndoableAction):
    def __init__(self, timeline_object, property_name, old_value, new_value):
        self.timeline_object = timeline_object
        self.property_name = property_name
        self.old_value = old_value
        self.new_value = new_value

    def do(self):
        setattr(self.timeline_object,
                self.property_name.replace("-", "_"), self.new_value)
        self._done()

    def undo(self):
        setattr(self.timeline_object,
                self.property_name.replace("-", "_"), self.old_value)
        self._undone()


class TimelineObjectAdded(UndoableAction):
    def __init__(self, layer, timeline_object):
        self.layer = layer
        self.timeline_object = timeline_object
        self.tracks = dict((track_object, track_object.get_track())
                for track_object in timeline_object.get_track_objects())

    def do(self):
        for track_object, track in self.tracks.iteritems():
            track.addTrackObject(track_object)

        self.layer.add_object(self.timeline_object)
        self._done()

    def undo(self):
        self.layer.remove_object(self.timeline_object)
        self._undone()


class TimelineObjectRemoved(UndoableAction):
    def __init__(self, timeline, timeline_object):
        self.timeline = timeline
        self.timeline_object = timeline_object
        self.tracks = dict((track_object, track_object.get_track())
                for track_object in timeline_object.get_track_objects())

    def do(self):
        self.timeline.removeTimelineObject(self.timeline_object, deep=True)
        self._done()

    def undo(self):
        for track_object, track in self.tracks.iteritems():
            track.addTrackObject(track_object)

        self.timeline.addTimelineObject(self.timeline_object)

        self._undone()


class InterpolatorKeyframeAdded(UndoableAction):
    def __init__(self, track_object, keyframe):
        self.track_object = track_object
        self.keyframe = keyframe

    def do(self):
        self.track_object.newKeyframe(self.keyframe)
        self._done()

    def undo(self):
        self.track_object.removeKeyframe(self.keyframe)
        self._undone()


class InterpolatorKeyframeRemoved(UndoableAction):
    def __init__(self, track_object, keyframe):
        self.track_object = track_object
        self.keyframe = keyframe

    def do(self):
        self.track_object.removeKeyframe(self.keyframe)
        self._undone()

    def undo(self):
        self.track_object.newKeyframe(self.keyframe.time,
                self.keyframe.value, self.keyframe.mode)
        self._done()


class InterpolatorKeyframeChanged(UndoableAction):
    def __init__(self, track_object, keyframe, old_snapshot, new_snapshot):
        self.track_object = track_object
        self.keyframe = keyframe
        self.old_snapshot = old_snapshot
        self.new_snapshot = new_snapshot

    def do(self):
        self._setSnapshot(self.new_snapshot)
        self._done()

    def undo(self):
        self._setSnapshot(self.old_snapshot)
        self._undone()

    def _setSnapshot(self, snapshot):
        mode, time, value = snapshot
        self.keyframe.setMode(mode)
        self.keyframe.setTime(time)
        self.keyframe.setValue(value)


class ActivePropertyChanged(UndoableAction):
    def __init__(self, effect_action, active):
        self.effect_action = effect_action
        self.active = not active

    def do(self):
        self.effect_action.track_object.active = self.active
        self.active = not self.active
        self._done()

    def undo(self):
        self.effect_action.track_object.active = self.active
        self.active = not self.active
        self._undone()


class TimelineLogObserver(object):
    timelinePropertyChangedAction = TimelineObjectPropertyChanged
    timelineObjectAddedAction = TimelineObjectAdded
    timelineObjectRemovedAction = TimelineObjectRemoved
    trackEffectAddAction = TrackEffectAdded
    trackEffectRemovedAction = TrackEffectRemoved
    interpolatorKeyframeAddedAction = InterpolatorKeyframeAdded
    interpolatorKeyframeRemovedAction = InterpolatorKeyframeRemoved
    interpolatorKeyframeChangedAction = InterpolatorKeyframeChanged
    activePropertyChangedAction = ActivePropertyChanged

    def __init__(self, log):
        self.log = log
        self.timeline_object_property_trackers = {}
        self.interpolator_keyframe_trackers = {}
        self.effect_properties_tracker = EffectGstElementPropertyChangeTracker(log)

    def startObserving(self, timeline):
        self._connectToTimeline(timeline)
        for layer in timeline.get_layers():
            for timeline_object in layer.get_objects():
                self._connectToTimelineObject(timeline_object)
                for track_object in timeline_object.get_track_objects():
                    self._connectToTrackObject(track_object)

    def stopObserving(self, timeline):
        self._disconnectFromTimeline(timeline)
        for timeline_object in timeline.timeline_objects:
            self._disconnectFromTimelineObject(timeline_object)
            for track_object in timeline_object.track_objects:
                self._disconnectFromTrackObject(track_object)

    def _connectToTimeline(self, timeline):
        for layer in timeline.get_layers():
            layer.connect("object-added", self._timelineObjectAddedCb)
            layer.connect("object-removed", self._timelineObjectRemovedCb)

    def _disconnectFromTimeline(self, timeline):
        timeline.disconnect_by_func(self._timelineObjectAddedCb)
        timeline.disconnect_by_func(self._timelineObjectRemovedCb)

    def _connectToTimelineObject(self, timeline_object):
        tracker = TimelineObjectPropertyChangeTracker()
        for property_name in tracker.property_names:
            tracker.connect("notify::" + property_name,
                    self._timelineObjectPropertyChangedCb, property_name)
        self.timeline_object_property_trackers[timeline_object] = tracker

        timeline_object.connect("track-object-added", self._timelineObjectTrackObjectAddedCb)
        timeline_object.connect("track-object-removed", self._timelineObjectTrackObjectRemovedCb)
        track_object.connect("effect-added", self._effectAddedCb)
        track_object.connect("effect-removed", self._effectRemovedCb)
        for obj in timeline_object.get_track_objects():
            self._connectToTrackObject(obj)

    def _disconnectFromTimelineObject(self, timeline_object):
        tracker = self.timeline_object_property_trackers.pop(timeline_object)
        tracker.disconnectFromObject(timeline_object)
        tracker.disconnect_by_func(self._timelineObjectPropertyChangedCb)

    def _connectToTrackObject(self, track_object):
        #for prop, interpolator in track_object.getInterpolators().itervalues():
            #self._connectToInterpolator(interpolator)
        if isinstance(track_object, ges.TrackEffect):
            self.effect_properties_tracker.addEffectElement(track_object.getElement())

    def _disconnectFromTrackObject(self, track_object):
        for prop, interpolator in track_object.getInterpolators().itervalues():
            self._disconnectFromInterpolator(interpolator)

    def _connectToInterpolator(self, interpolator):
        interpolator.connect("keyframe-added", self._interpolatorKeyframeAddedCb)
        interpolator.connect("keyframe-removed",
                self._interpolatorKeyframeRemovedCb)

        tracker = KeyframeChangeTracker()
        tracker.connectToObject(interpolator)
        tracker.connect("keyframe-moved", self._interpolatorKeyframeMovedCb)
        self.interpolator_keyframe_trackers[interpolator] = tracker

    def _disconnectFromInterpolator(self, interpolator):
        tracker = self.interpolator_keyframe_trackers.pop(interpolator)
        tracker.disconnectFromObject(interpolator)
        tracker.disconnect_by_func(self._interpolatorKeyframeMovedCb)

    def _effectAddedCb(self, timeline, track_object):
        action = self.trackEffectAddAction(timeline_object, track_object,
                                               self.effect_properties_tracker)
        #We use the action instead of the track object
        #because the track_object changes when redoing
        track_object.connect("effect-added",
                    self._trackObjectActiveChangedCb, action)
        self.log.push(action)
        element = track_object.getElement()
        if element:
            self.effect_properties_tracker.addEffectElement(element)

    def _effectRemovedCb(self, timeline, track_object):
        track_object.disconnect_by_func(self._effectAddedCb)
        track_object.disconnect_by_func(self._effectRemovedCb)

    def _layerAddedCb(self, timeline="her", layer="What"):
        for tlobj in layer.get_objects():
            tlobj.connect("track-object-added",
                    self._timelineObjectTrackObjectAddedCb)
            tlobj.connect("track-object-removed",
                    self._timelineObjectTrackObjectRemovedCb)
        layer.connect("object-added", self._timelineObjectAddedCb)
        layer.connect("object-removed", self._timelineObjectRemovedCb)

    def _layerRemovedCb(self, timeline, layer):
        for tlobj in layer.get_objects():
            tlobj.disconnect_by_func(self._timelineObjectTrackObjectAddedCb)
            tlobj.disconnect_by_func(self._timelineObjectTrackObjectRemovedCb)

    def _timelineObjectAddedCb(self, timeline, timeline_object):
        self._connectToTimelineObject(timeline_object)
        action = self.timelineObjectAddedAction(timeline, timeline_object)
        self.log.push(action)

    def _timelineObjectRemovedCb(self, timeline, timeline_object):
        self._disconnectFromTimelineObject(timeline_object)
        action = self.timelineObjectRemovedAction(timeline, timeline_object)
        self.log.push(action)

    def _timelineObjectPropertyChangedCb(self, tracker, timeline_object,
            old_value, new_value, property_name):
        action = self.timelinePropertyChangedAction(timeline_object,
                property_name, old_value, new_value)
        self.log.push(action)

    def _timelineObjectTrackObjectAddedCb(self, timeline_object, track_object):
        if isinstance(track_object, ges.TrackEffect):
            action = self.trackEffectAddAction(timeline_object, track_object,
                                               self.effect_properties_tracker)
            #We use the action instead of the track object
            #because the track_object changes when redoing
            track_object.connect("active-changed",
                                 self._trackObjectActiveChangedCb, action)
            self.log.push(action)
            element = track_object.getElement()
            if element:
                self.effect_properties_tracker.addEffectElement(element)
        else:
            self._connectToTrackObject(track_object)

    def _timelineObjectTrackObjectRemovedCb(self, timeline_object,
                                            track_object):
        if isinstance(track_object, ges.TrackEffect):
            action = self.trackEffectRemovedAction(timeline_object,
                                                track_object,
                                                self.effect_properties_tracker)
            self.log.push(action)
        else:
            self._disconnectFromTrackObject(track_object)

    def _interpolatorKeyframeAddedCb(self, track_object, keyframe):
        action = self.interpolatorKeyframeAddedAction(track_object, keyframe)
        self.log.push(action)

    def _interpolatorKeyframeRemovedCb(self, track_object, keyframe,
            old_value=None):
        action = self.interpolatorKeyframeRemovedAction(track_object, keyframe)
        self.log.push(action)

    def _trackObjectActiveChangedCb(self, track_object, active, add_effect_action):
        action = self.activePropertyChangedAction(add_effect_action, active)
        self.log.push(action)

    def _interpolatorKeyframeMovedCb(self, tracker, track_object,
            keyframe, old_snapshot, new_snapshot):
        action = self.interpolatorKeyframeChangedAction(track_object,
                keyframe, old_snapshot, new_snapshot)
        self.log.push(action)
