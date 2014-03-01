# -*- coding: utf-8 -*-
# Pitivi video editor
#
#       pitivi/utils/ui.py
#
# Copyright (c) 2005, Edward Hervey <bilboed@bilboed.com>
# Copyright (c) 2012, Thibault Saunier <thibault.saunier@collabora.com>
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
UI utilities. This file contain the UI constants, and various functions and
classes that help with UI drawing around the application
"""


import cairo
import decimal
import os
import urllib

from gettext import ngettext, gettext as _

from gi.repository import Clutter
from gi.repository import Cogl
from gi.repository import GLib
from gi.repository import GES
from gi.repository import Gdk
from gi.repository import Gio
from gi.repository import Gst
from gi.repository import Gtk
from gi.repository.GstPbutils import DiscovererVideoInfo, DiscovererAudioInfo,\
    DiscovererStreamInfo, DiscovererSubtitleInfo, DiscovererInfo

from pitivi.utils.loggable import doLog, ERROR

# ---------------------- Constants -------------------------------------------#

##
# UI pixels information constants
##

LAYER_HEIGHT_EXPANDED = 50
LAYER_HEIGHT_COLLAPSED = 15
TRACK_SPACING = 8
EXPANDED_SIZE = 65
CONTROL_WIDTH = 250

PADDING = 6
SPACING = 10

PLAYHEAD_WIDTH = 1
CANVAS_SPACING = 21
KEYFRAME_SIZE = 8

PLAYHEAD_COLOR = Clutter.Color.new(200, 0, 0, 255)

# Layer creation blocking time in s
LAYER_CREATION_BLOCK_TIME = 0.2

##
#   Drag'n drop constants
##
TYPE_TEXT_PLAIN = 24
TYPE_URI_LIST = 25

# FileSourceFactory (or subclasses)
TYPE_PITIVI_FILESOURCE = 26

# What objects to these correspond to ???
TYPE_PITIVI_EFFECT = 27
TYPE_PITIVI_AUDIO_EFFECT = 28
TYPE_PITIVI_VIDEO_EFFECT = 29
TYPE_PITIVI_AUDIO_TRANSITION = 30
TYPE_PITIVI_VIDEO_TRANSITION = 31
TYPE_PITIVI_LAYER_CONTROL = 32

FILE_TARGET_ENTRY = Gtk.TargetEntry.new("text/plain", Gtk.TargetFlags.OTHER_APP, TYPE_TEXT_PLAIN)
URI_TARGET_ENTRY = Gtk.TargetEntry.new("text/uri-list", 0, TYPE_URI_LIST)
FILESOURCE_TARGET_ENTRY = Gtk.TargetEntry.new("pitivi/file-source", 0, TYPE_PITIVI_FILESOURCE)
EFFECT_TARGET_ENTRY = Gtk.TargetEntry.new("pitivi/effect", 0, TYPE_PITIVI_EFFECT)
AUDIO_EFFECT_TARGET_ENTRY = Gtk.TargetEntry.new("pitivi/audio-effect", 0, TYPE_PITIVI_AUDIO_EFFECT)
VIDEO_EFFECT_TARGET_ENTRY = Gtk.TargetEntry.new("pitivi/video-effect", 0, TYPE_PITIVI_VIDEO_EFFECT)
AUDIO_TRANSITION_TARGET_ENTRY = Gtk.TargetEntry.new("pitivi/audio-transition", 0, TYPE_PITIVI_AUDIO_TRANSITION)
VIDEO_TRANSITION_TARGET_ENTRY = Gtk.TargetEntry.new("pitivi/video-transition", 0, TYPE_PITIVI_VIDEO_TRANSITION)
LAYER_CONTROL_TARGET_ENTRY = Gtk.TargetEntry.new("pitivi/layer-control", 0, TYPE_PITIVI_LAYER_CONTROL)


def _get_settings(schema):
    if schema not in Gio.Settings.list_schemas():
        return None
    return Gio.Settings(schema=schema)


def _get_font(font_spec, default):
    raw_font = default
    settings = _get_settings("org.gnome.desktop.interface")
    if settings:
        if font_spec in settings.list_keys():
            raw_font = settings.get_string(font_spec)
    face = raw_font.rsplit(" ", 1)[0]
    return cairo.ToyFontFace(face)

NORMAL_FONT = _get_font("font-name", "Cantarell")
DOCUMENT_FONT = _get_font("document-font-name", "Sans")
MONOSPACE_FONT = _get_font("monospace-font-name", "Monospace")


# ---------------------- ARGB color helper-------------------------------------#
def pack_color_32(red, green, blue, alpha=0xFFFF):
    """Packs the specified 16bit color values in a 32bit RGBA value."""
    red = red >> 8
    green = green >> 8
    blue = blue >> 8
    alpha = alpha >> 8
    return (red << 24 | green << 16 | blue << 8 | alpha)


def pack_color_64(red, green, blue, alpha=0xFFFF):
    """Packs the specified 16bit color values in a 64bit RGBA value."""
    return (red << 48 | green << 32 | blue << 16 | alpha)


def unpack_color(value):
    """Unpacks the specified RGBA value into four 16bit color values.

    Args:
      value: A 32bit or 64bit RGBA value.
    """
    if not (value >> 32):
        return unpack_color_32(value)
    else:
        return unpack_color_64(value)


def unpack_color_32(value):
    """Unpacks the specified 32bit RGBA value into four 16bit color values."""
    red = (value >> 24) << 8
    green = ((value >> 16) & 0xFF) << 8
    blue = ((value >> 8) & 0xFF) << 8
    alpha = (value & 0xFF) << 8
    return red, green, blue, alpha


def unpack_color_64(value):
    """Unpacks the specified 64bit RGBA value into four 16bit color values."""
    red = (value >> 48) & 0xFFFF
    green = (value >> 32) & 0xFFFF
    blue = (value >> 16) & 0xFFFF
    alpha = value & 0xFFFF
    return red, green, blue, alpha


def unpack_cairo_pattern(value):
    """Transforms the specified RGBA value into a SolidPattern object."""
    red, green, blue, alpha = unpack_color(value)
    return cairo.SolidPattern(
        red / 65535.0,
        green / 65535.0,
        blue / 65535.0,
        alpha / 65535.0)


def unpack_cairo_gradient(value):
    """Creates a LinearGradient object out of the specified RGBA value."""
    red, green, blue, alpha = unpack_color(value)
    gradient = cairo.LinearGradient(0, 0, 0, 50)
    gradient.add_color_stop_rgba(
        1.0,
        red / 65535.0,
        green / 65535.0,
        blue / 65535.0,
        alpha / 65535.0)
    gradient.add_color_stop_rgba(
        0,
        (red / 65535.0) * 1.5,
        (green / 65535.0) * 1.5,
        (blue / 65535.0) * 1.5,
        alpha / 65535.0)
    return gradient


def hex_to_rgb(value):
    return tuple(float(int(value[i:i + 2], 16)) / 255.0 for i in range(0, 6, 2))


def create_cogl_color(red, green, blue, alpha):
    color = Cogl.Color()
    color.init_from_4ub(red, green, blue, alpha)
    return color


def set_cairo_color(context, color):
    if type(color) is Clutter.Color:
        color = (color.red, color.green, color.blue)

    if type(color) is Gdk.RGBA:
        cairo_color = (float(color.red), float(color.green), float(color.blue))
    elif type(color) is tuple:
        # Cairo's set_source_rgb function expects values from 0.0 to 1.0
        cairo_color = map(lambda x: max(0, min(1, x / 255.0)), color)
    else:
        raise Exception("Unexpected color parameter: %s, %s" % (type(color), color))
    context.set_source_rgb(*cairo_color)


def beautify_info(info):
    """
    Formats the specified info for display.

    @type info: L{DiscovererInfo}
    """
    ranks = {
        DiscovererVideoInfo: 0,
        DiscovererAudioInfo: 1,
        DiscovererStreamInfo: 2
    }

    def stream_sort_key(stream):
        try:
            return ranks[type(stream)]
        except KeyError:
            return len(ranks)

    info.get_stream_list().sort(key=stream_sort_key)
    nice_streams_txts = []
    for stream in info.get_stream_list():
        try:
            beautified_string = beautify_stream(stream)
        except NotImplementedError:
            doLog(ERROR, "Beautify", "None", "Cannot beautify %s", stream)
            continue
        if beautified_string:
            nice_streams_txts.append(beautified_string)

    return ("<b>" + info_name(info) + "</b>\n" +
        "\n".join(nice_streams_txts))


def info_name(info):
    """
    Return a human-readable filename (without the path and quoting).

    @type info: L{GES.Asset} or L{DiscovererInfo}
    """
    if isinstance(info, GES.Asset):
        filename = urllib.unquote(os.path.basename(info.get_id()))
    elif isinstance(info, DiscovererInfo):
        filename = urllib.unquote(os.path.basename(info.get_uri()))
    else:
        raise Exception("Unsupported argument type: %s" % type(info))
    return GLib.markup_escape_text(filename)


def beautify_stream(stream):
    if type(stream) is DiscovererAudioInfo:
        templ = ngettext("<b>Audio:</b> %d channel at %d <i>Hz</i> (%d <i>bits</i>)",
                "<b>Audio:</b> %d channels at %d <i>Hz</i> (%d <i>bits</i>)",
                stream.get_channels())
        templ = templ % (stream.get_channels(), stream.get_sample_rate(),
            stream.get_depth())
        return templ

    elif type(stream) is DiscovererVideoInfo:
        par = stream.get_par_num() / stream.get_par_denom()
        if not stream.is_image():
            templ = _("<b>Video:</b> %d×%d <i>pixels</i> at %.3f <i>fps</i>")
            try:
                templ = templ % (par * stream.get_width(), stream.get_height(),
                    float(stream.get_framerate_num()) / stream.get_framerate_denom())
            except ZeroDivisionError:
                templ = templ % (par * stream.get_width(), stream.get_height(), 0)
        else:
            templ = _("<b>Image:</b> %d×%d <i>pixels</i>")
            templ = templ % (par * stream.get_width(), stream.get_height())
        return templ

    elif type(stream) is DiscovererSubtitleInfo:
        # Ignore subtitle streams
        return None

    elif type(stream) is DiscovererStreamInfo:
        caps = stream.get_caps().to_string()
        if caps in ("application/x-subtitle", "application/x-id3", "text"):
            # Ignore all audio ID3 tags and subtitle tracks, we don't show them
            return None

    raise NotImplementedError


def time_to_string(value):
    """
    Converts the given time in nanoseconds to a human readable string

    Format HH:MM:SS.XXX
    """
    if value == Gst.CLOCK_TIME_NONE:
        return "--:--:--.---"
    ms = value / Gst.MSECOND
    sec = ms / 1000
    ms = ms % 1000
    mins = sec / 60
    sec = sec % 60
    hours = mins / 60
    mins = mins % 60
    return "%01d:%02d:%02d.%03d" % (hours, mins, sec, ms)


def beautify_length(length):
    """
    Converts the given time in nanoseconds to a human readable string
    """
    sec = length / Gst.SECOND
    mins = sec / 60
    sec = sec % 60
    hours = mins / 60
    mins = mins % 60

    parts = []
    if hours:
        parts.append(ngettext("%d hour", "%d hours", hours) % hours)

    if mins:
        parts.append(ngettext("%d minute", "%d minutes", mins) % mins)

    if not hours and sec:
        parts.append(ngettext("%d second", "%d seconds", sec) % sec)

    return ", ".join(parts)


def beautify_time_delta(seconds):
    """
    Converts the given time in seconds to a human-readable estimate.

    This is intended for "Unsaved changes" and "Backup file found" dialogs.
    """
    mins = seconds / 60
    sec = int(seconds % 60)
    hours = mins / 60
    mins = int(mins % 60)
    days = int(hours / 24)
    hours = int(hours % 24)

    parts = []
    if days > 0:
        parts.append(ngettext("%d day", "%d days", days) % days)
    if hours > 0:
        parts.append(ngettext("%d hour", "%d hours", hours) % hours)

    if days == 0 and mins > 0:
        parts.append(ngettext("%d minute", "%d minutes", mins) % mins)

    if hours == 0 and mins < 2 and sec:
        parts.append(ngettext("%d second", "%d seconds", sec) % sec)

    return ", ".join(parts)


def beautify_ETA(length):
    """
    Converts the given time in nanoseconds to a fuzzy estimate,
    intended for progress ETAs, not to indicate a clip's duration.
    """
    sec = length / Gst.SECOND
    mins = sec / 60
    sec = int(sec % 60)
    hours = int(mins / 60)
    mins = int(mins % 60)

    parts = []
    if hours > 0:
        parts.append(ngettext("%d hour", "%d hours", hours) % hours)

    if mins > 0:
        parts.append(ngettext("%d minute", "%d minutes", mins) % mins)

    if hours == 0 and mins < 2 and sec:
        parts.append(ngettext("%d second", "%d seconds", sec) % sec)
    return ", ".join(parts)


#--------------------- Gtk widget helpers ------------------------------------#
def model(columns, data):
    ret = Gtk.ListStore(*columns)
    for datum in data:
        ret.append(datum)
    return ret


def set_combo_value(combo, value, default_index=-1):
    model = combo.props.model
    for i, row in enumerate(model):
        if row[1] == value:
            combo.set_active(i)
            return
    combo.set_active(default_index)


def get_combo_value(combo):
    active = combo.get_active()
    return combo.props.model[active][1]


def get_value_from_model(model, key):
    """
    For a given key, search a gtk ListStore and return the value as a string.

    If not found and the key is a gst fraction, return a beautified form.
    """
    for row in model:
        if row[1] == key:
            return str(row[0])
    if isinstance(key, Gst.Fraction):
        return "%.3f" % decimal.Decimal(float(key.num) / key.denom)
    return str(key)


def alter_style_class(style_class, target_widget, css_style):
    css_provider = Gtk.CssProvider()
    toolbar_css = "%s { %s }" % (style_class, css_style)
    css_provider.load_from_data(toolbar_css.encode('UTF-8'))
    style_context = target_widget.get_style_context()
    style_context.add_provider(css_provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)


#------------------------ encoding datas ----------------------------------------#
# FIXME This should into a special file
frame_rates = model((str, object), (
    # Translators: fps is for frames per second
    (_("%d fps") % 12, Gst.Fraction(12.0, 1.0)),
    (_("%d fps") % 15, Gst.Fraction(15.0, 1.0)),
    (_("%d fps") % 20, Gst.Fraction(20.0, 1.0)),
    (_("%.3f fps") % 23.976, Gst.Fraction(24000.0, 1001.0)),
    (_("%d fps") % 24, Gst.Fraction(24.0, 1.0)),
    (_("%d fps") % 25, Gst.Fraction(25.0, 1.0)),
    (_("%.2f fps") % 29.97, Gst.Fraction(30000.0, 1001.0)),
    (_("%d fps") % 30, Gst.Fraction(30.0, 1.0)),
    (_("%d fps") % 50, Gst.Fraction(50.0, 1.0)),
    (_("%.2f fps") % 59.94, Gst.Fraction(60000.0, 1001.0)),
    (_("%d fps") % 60, Gst.Fraction(60.0, 1.0)),
    (_("%d fps") % 120, Gst.Fraction(120.0, 1.0)),
))

audio_rates = model((str, int), (
    (_("%d kHz") % 8, 8000),
    (_("%d kHz") % 11, 11025),
    (_("%d kHz") % 22, 22050),
    (_("%.1f kHz") % 44.1, 44100),
    (_("%d kHz") % 48, 48000),
    (_("%d kHz") % 96, 96000)))

audio_channels = model((str, int), (
    (_("6 Channels (5.1)"), 6),
    (_("4 Channels (4.0)"), 4),
    (_("Stereo"), 2),
    (_("Mono"), 1)))

# FIXME: are we sure the following tables correct?

pixel_aspect_ratios = model((str, object), (
    (_("Square"), Gst.Fraction(1, 1)),
    (_("480p"), Gst.Fraction(10, 11)),
    (_("480i"), Gst.Fraction(8, 9)),
    (_("480p Wide"), Gst.Fraction(40, 33)),
    (_("480i Wide"), Gst.Fraction(32, 27)),
    (_("576p"), Gst.Fraction(12, 11)),
    (_("576i"), Gst.Fraction(16, 15)),
    (_("576p Wide"), Gst.Fraction(16, 11)),
    (_("576i Wide"), Gst.Fraction(64, 45)),
))

display_aspect_ratios = model((str, object), (
    (_("Standard (4:3)"), Gst.Fraction(4, 3)),
    (_("DV (15:11)"), Gst.Fraction(15, 11)),
    (_("DV Widescreen (16:9)"), Gst.Fraction(16, 9)),
    (_("Cinema (1.37)"), Gst.Fraction(11, 8)),
    (_("Cinema (1.66)"), Gst.Fraction(166, 100)),
    (_("Cinema (1.85)"), Gst.Fraction(185, 100)),
    (_("Anamorphic (2.35)"), Gst.Fraction(235, 100)),
    (_("Anamorphic (2.39)"), Gst.Fraction(239, 100)),
    (_("Anamorphic (2.4)"), Gst.Fraction(24, 10)),
))
