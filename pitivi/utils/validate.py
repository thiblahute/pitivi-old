# Pitivi video editor
#
#       pitivi/utils/validate.py
#
# Copyright (c) 2014, Thibault Saunier <thibault.saunier@collabora.com>
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
import sys

from gi.repository import Gst
from gi.repository import GES
from gi.repository import GES
from gi.repository import GLib

from pitivi.utils import loggable
from pitivi.utils import timeline as timelineUtils

try:
    from gi.repository import GstValidate
except ImportError:
    GstValidate = None

has_validate = False


def stop(scenario, action):
    sys.stdout.write("STOP action, not doing anything in pitivi")
    sys.stdout.flush()
    return 1


def editContainer(scenario, action):
    timeline = scenario.pipeline.props.timeline
    container = timeline.get_element(action.structure["container-name"])
    res, position = GstValidate.action_get_clocktime(scenario, action, "position")

    if res is False:
        return 0

    if not hasattr(scenario, "dragging") or scenario.dragging is False:
        scenario.dragging = True
        container.ui._dragBeginCb(None, 0, 0)

    container.ui._dragUpdateCb(None, timelineUtils.Zoomable.nsToPixelAccurate(position) - timelineUtils.Zoomable.nsToPixelAccurate(container.props.start), 0)

    next_action = scenario.get_next_action()
    if next_action.type != "edit-container":
        container.ui._dragEndCb(None, timelineUtils.Zoomable.nsToPixelAccurate(position) - timelineUtils.Zoomable.nsToPixelAccurate(container.props.start), 0)

    if abs(container.props.start - position) > Gst.SECOND / 100000:
        GstValidate.report_simple(scenario, GLib.quark_from_string("scenario::execution-error"),
                                  "Element start diffent than wanted: %s != %s"
                                  % (Gst.TIME_ARGS(container.props.start),
                                  Gst.TIME_ARGS(position)))
    return 1


def init():
    global has_validate
    try:
        from gi.repository import GstValidate
        GstValidate.init()
        has_validate = GES.validate_register_action_types()
        GstValidate.register_action_type("stop", "pitivi",
                                         stop, None,
                                         "Pitivi override for the stop action",
                                         GstValidate.ActionTypeFlags.NONE)

        GstValidate.register_action_type("edit-container", "pitivi",
                                         editContainer, None,
                                         "Start dragging a clip in the timeline",
                                         GstValidate.ActionTypeFlags.NONE)
    except ImportError:
        has_validate = False
