# -*- coding: utf-8 -*-
# Pitivi video editor
#
#       pitivi/transitions.py
#
# Copyright (c) 2012, Jean-François Fortin Tam <nekohayo@gmail.com>
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

import os

from gi.repository import GES
from gi.repository import GLib
from gi.repository import GObject
from gi.repository import Gtk
from gi.repository import GdkPixbuf

from gettext import gettext as _

from pitivi.configure import get_pixmap_dir
from pitivi.utils.loggable import Loggable
from pitivi.utils.ui import SPACING


(COL_TRANSITION_ASSET,
 COL_NAME_TEXT,
 COL_DESC_TEXT,
 COL_ICON) = list(range(4))


class TransitionsListWidget(Gtk.VBox, Loggable):

    """
    Widget for configuring the selected transition.

    @type app: L{Pitivi}
    """

    def __init__(self, app):
        Gtk.VBox.__init__(self)
        Loggable.__init__(self)

        self.app = app
        self.element = None
        self._pixdir = os.path.join(get_pixmap_dir(), "transitions")
        icon_theme = Gtk.IconTheme.get_default()
        self._question_icon = icon_theme.load_icon("dialog-question", 48, 0)

        # Tooltip handling
        self._current_transition_name = None
        self._current_tooltip_icon = None

        # Searchbox
        self.searchbar = Gtk.HBox()
        # Prevents being flush against the notebook
        self.searchbar.set_border_width(3)
        self.searchEntry = Gtk.Entry()
        self.searchEntry.set_icon_from_icon_name(
            Gtk.EntryIconPosition.SECONDARY, "edit-clear-symbolic")
        self.searchEntry.set_placeholder_text(_("Search..."))
        self.searchbar.pack_end(self.searchEntry, True, True, 0)

        self.props_widgets = Gtk.VBox()
        borderTable = Gtk.Table(n_rows=2, n_columns=3)

        self.border_mode_normal = Gtk.RadioButton(
            group=None, label=_("Normal"))
        self.border_mode_loop = Gtk.RadioButton(
            group=self.border_mode_normal, label=_("Loop"))
        self.border_mode_normal.set_active(True)
        self.borderScale = Gtk.Scale.new(Gtk.Orientation.HORIZONTAL, None)
        self.borderScale.set_draw_value(False)

        borderTable.attach(self.border_mode_normal, 0, 1, 0, 1,
                           xoptions=Gtk.AttachOptions.FILL, yoptions=Gtk.AttachOptions.FILL)
        borderTable.attach(self.border_mode_loop, 1, 2, 0, 1,
                           xoptions=Gtk.AttachOptions.FILL, yoptions=Gtk.AttachOptions.FILL)
        # The ypadding is a hack to make the slider widget align with the
        # radiobuttons.
        borderTable.attach(self.borderScale, 2, 3, 0, 2, ypadding=SPACING * 2)

        self.invert_checkbox = Gtk.CheckButton(label=_("Reverse direction"))
        self.invert_checkbox.set_border_width(SPACING)

        self.props_widgets.add(borderTable)
        self.props_widgets.add(self.invert_checkbox)

        # Set the default values
        self._borderTypeChangedCb()

        self.infobar = Gtk.InfoBar()
        self.infobar.props.message_type = Gtk.MessageType.OTHER
        txtlabel = Gtk.Label()
        txtlabel.set_line_wrap(True)
        txtlabel.set_text(
            _("Create a transition by overlapping two adjacent clips on the "
                "same layer. Click the transition on the timeline to change "
                "the transition type."))
        self.infobar.get_content_area().add(txtlabel)

        self.storemodel = Gtk.ListStore(GES.Asset, str, str, GdkPixbuf.Pixbuf)

        self.iconview_scrollwin = Gtk.ScrolledWindow()
        self.iconview_scrollwin.set_shadow_type(Gtk.ShadowType.ETCHED_IN)
        # FIXME: the "never" horizontal scroll policy in GTK2 messes up iconview
        # Re-enable this when we switch to GTK3
        # See also http://python.6.n6.nabble.com/Cannot-shrink-width-of-scrolled-textview-tp1945060.html
        # self.iconview_scrollwin.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)

        self.iconview = Gtk.IconView(model=self.storemodel)
        self.iconview.set_pixbuf_column(COL_ICON)
        # We don't show text because we have a searchbar and the names are ugly
        # self.iconview.set_text_column(COL_NAME_TEXT)
        self.iconview.set_item_width(48 + 10)
        self.iconview_scrollwin.add(self.iconview)
        self.iconview.set_property("has_tooltip", True)

        self.searchEntry.connect("changed", self._searchEntryChangedCb)
        self.searchEntry.connect("icon-press", self._searchEntryIconClickedCb)
        self.iconview.connect("selection-changed", self._transitionSelectedCb)
        self.iconview.connect("query-tooltip", self._queryTooltipCb)
        self.borderScale.connect("value-changed", self._borderScaleCb)
        self.invert_checkbox.connect("toggled", self._invertCheckboxCb)
        self.border_mode_normal.connect("released", self._borderTypeChangedCb)
        self.border_mode_loop.connect("released", self._borderTypeChangedCb)

        # Speed-up startup by only checking available transitions on idle
        GLib.idle_add(self._loadAvailableTransitionsCb)

        self.pack_start(self.infobar, False, True, 0)
        self.pack_start(self.searchbar, False, True, 0)
        self.pack_start(self.iconview_scrollwin, True, True, 0)
        self.pack_start(self.props_widgets, False, True, 0)

        # Create the filterModel for searching
        self.modelFilter = self.storemodel.filter_new()
        self.iconview.set_model(self.modelFilter)

        self.infobar.show_all()
        self.iconview_scrollwin.show_all()
        self.iconview.hide()
        self.props_widgets.set_sensitive(False)
        self.props_widgets.hide()
        self.searchbar.hide()

# UI callbacks

    def _transitionSelectedCb(self, unused_event):
        transition_asset = self.getSelectedItem()
        if not transition_asset:
            # The user clicked between icons
            return False

        self.debug(
            "New transition type selected: %s", transition_asset.get_id())
        if transition_asset.get_id() == "crossfade":
            self.props_widgets.set_sensitive(False)
        else:
            self.props_widgets.set_sensitive(True)

        self.element.get_parent().set_asset(transition_asset)
        self.app.project_manager.current_project.seeker.flush(True)

        return True

    def _borderScaleCb(self, range_changed):
        value = range_changed.get_value()
        self.debug("User changed the border property to %s", value)
        self.element.set_border(int(value))
        self.app.project_manager.current_project.seeker.flush(True)

    def _invertCheckboxCb(self, widget):
        value = widget.get_active()
        self.debug("User changed the invert property to %s", value)
        self.element.set_inverted(value)
        self.app.project_manager.current_project.seeker.flush()

    def _borderTypeChangedCb(self, widget=None):
        """
        The "border" property in gstreamer is unlimited, but if you go over
        25 thousand it "loops" the transition instead of smoothing it.
        """
        if widget == self.border_mode_loop:
            self.borderScale.set_range(50000, 500000)
            self.borderScale.clear_marks()
            self.borderScale.add_mark(
                50000, Gtk.PositionType.BOTTOM, _("Slow"))
            self.borderScale.add_mark(
                200000, Gtk.PositionType.BOTTOM, _("Fast"))
            self.borderScale.add_mark(
                500000, Gtk.PositionType.BOTTOM, _("Epileptic"))
        else:
            self.borderScale.set_range(0, 25000)
            self.borderScale.clear_marks()
            self.borderScale.add_mark(0, Gtk.PositionType.BOTTOM, _("Sharp"))
            self.borderScale.add_mark(
                25000, Gtk.PositionType.BOTTOM, _("Smooth"))

    def _searchEntryChangedCb(self, unused_entry):
        self.modelFilter.refilter()

    def _searchEntryIconClickedCb(self, entry, unused, unused_1):
        entry.set_text("")

# GES callbacks

    def _transitionTypeChangedCb(self, element, unused_prop):
        try:
            self.iconview.disconnect_by_func(self._transitionSelectedCb)
        except TypeError:
            pass
        finally:
            self.selectTransition(element.get_asset())
            self.iconview.connect(
                "button-release-event", self._transitionSelectedCb)

    def _borderChangedCb(self, element, unused_prop):
        """
        The "border" transition property changed in the backend. Update the UI.
        """
        value = element.get_border()
        try:
            self.borderScale.disconnect_by_func(self._borderScaleCb)
        except TypeError:
            pass
        finally:
            self.borderScale.set_value(float(value))
            self.borderScale.connect("value-changed", self._borderScaleCb)

    def _invertChangedCb(self, element, unused_prop):
        """
        The "invert" transition property changed in the backend. Update the UI.
        """
        value = element.is_inverted()
        try:
            self.invert_checkbox.disconnect_by_func(self._invertCheckboxCb)
        except TypeError:
            pass
        finally:
            self.invert_checkbox.set_active(value)
            self.invert_checkbox.connect("toggled", self._invertCheckboxCb)

# UI methods

    def _loadAvailableTransitionsCb(self):
        """
        Get the list of transitions from GES and load the associated thumbnails.
        """
        for trans_asset in GES.list_assets(GES.BaseTransitionClip):
            trans_asset.icon = self._getIcon(trans_asset.get_id())
            self.storemodel.append([trans_asset,
                                    str(trans_asset.get_id()),
                                    str(trans_asset.get_meta(
                                        GES.META_DESCRIPTION)),
                                    trans_asset.icon])

        # Now that the UI is fully ready, enable searching
        self.modelFilter.set_visible_func(self._setRowVisible, data=None)
        # Alphabetical/name sorting instead of based on the ID number
        self.storemodel.set_sort_column_id(
            COL_NAME_TEXT, Gtk.SortType.ASCENDING)

    def activate(self, element):
        """
        Hide the infobar and show the transitions UI.
        """
        self.element = element
        self.element.connect("notify::border", self._borderChangedCb)
        self.element.connect("notify::invert", self._invertChangedCb)
        self.element.connect("notify::type", self._transitionTypeChangedCb)
        transition_asset = element.get_parent().get_asset()
        if transition_asset.get_id() == "crossfade":
            self.props_widgets.set_sensitive(False)
        else:
            self.props_widgets.set_sensitive(True)
        self.iconview.show_all()
        self.props_widgets.show_all()
        self.searchbar.show_all()
        self.selectTransition(transition_asset)
        self.app.gui.switchContextTab(element)
        # We REALLY want the infobar to be hidden as space is really constrained
        # and yet GTK 3.10 seems to be racy in showing/hiding infobars, so
        # this must happen *after* the tab has been made visible/switched to:
        self.infobar.hide()

    def selectTransition(self, transition_asset):
        """
        For a given transition type, select it in the iconview if available.
        """
        model = self.iconview.get_model()
        for row in model:
            if transition_asset == row[COL_TRANSITION_ASSET]:
                path = model.get_path(row.iter)
                self.iconview.select_path(path)
                self.iconview.scroll_to_path(path, False, 0, 0)

    def deactivate(self):
        """
        Show the infobar and hide the transitions UI.
        """
        try:
            self.element.disconnect_by_func(self._borderChangedCb)
            self.element.disconnect_by_func(self._invertChangedCb)
            self.element.disconnect_by_func(self._transitionTypeChangedCb)
        except TypeError:
            pass
        except AttributeError:
            # This happens when selecting a normal track object before any
            # transition object has been created. Normal track objects don't
            # have these signals, so we just ignore them. Anyway, we just want
            # to deactivate the UI now.
            pass
        self.iconview.unselect_all()
        self.iconview.hide()
        self.props_widgets.hide()
        self.searchbar.hide()
        self.infobar.show()

    def _getIcon(self, transition_nick):
        """
        If available, return an icon pixbuf for a given transition nickname.
        """
        name = transition_nick + ".png"
        icon = None
        try:
            icon = GdkPixbuf.Pixbuf.new_from_file(
                os.path.join(self._pixdir, name))
        except:
            icon = self._question_icon
        return icon

    def _queryTooltipCb(self, view, x, y, keyboard_mode, tooltip):
        is_row, x, y, model, path, iter_ = view.get_tooltip_context(
            x, y, keyboard_mode)
        if not is_row:
            return False

        view.set_tooltip_item(tooltip, path)

        name = model.get_value(iter_, COL_TRANSITION_ASSET).get_id()
        if self._current_transition_name != name:
            self._current_transition_name = name
            icon = model.get_value(iter_, COL_ICON)
            self._current_tooltip_icon = icon

        longname = model.get_value(iter_, COL_NAME_TEXT).strip()
        description = model.get_value(iter_, COL_DESC_TEXT)
        txt = "<b>%s:</b>\n%s" % (GLib.markup_escape_text(longname),
                                  GLib.markup_escape_text(description),)
        tooltip.set_markup(txt)
        return True

    def getSelectedItem(self):
        path = self.iconview.get_selected_items()
        if path == []:
            return None
        return self.modelFilter[path[0]][COL_TRANSITION_ASSET]

    def _setRowVisible(self, model, iter, unused_data):
        """
        Filters the icon view depending on the search results
        """
        text = self.searchEntry.get_text().lower()
        return text in model.get_value(iter, COL_DESC_TEXT).lower() or\
            text in model.get_value(iter, COL_NAME_TEXT).lower()
