# Pitivi video editor
#
#       pitivi/dialogs/prefs.py
#
# Copyright (c) 2005, Edward Hervey <bilboed@bilboed.com>
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
Dialog box for user preferences.
"""

from gi.repository import Gtk
import os

import pitivi.utils.widgets as ptvWidgets

from pitivi.configure import get_ui_dir
from pitivi.settings import GlobalSettings
from pitivi.utils.ui import SPACING
from gettext import gettext as _

GlobalSettings.addConfigSection("user-interface")

GlobalSettings.addConfigOption('prefsDialogWidth',
    section="user-interface",
    key="prefs-dialog-width",
    default=600)

GlobalSettings.addConfigOption('prefsDialogHeight',
    section="user-interface",
    key="prefs-dialog-height",
    default=400)


class PreferencesDialog(object):
    """
    This dialog displays preferences for pitivi.
    """
    prefs = {}
    original_values = {}

    def __init__(self, instance):
        self.settings = instance.settings
        self.widgets = {}
        self.resets = {}
        self._current = None

        # Identify the widgets we'll need
        builder = Gtk.Builder()
        builder.add_from_file(os.path.join(get_ui_dir(), "preferences.ui"))
        builder.connect_signals(self)
        self.dialog = builder.get_object("dialog1")
        self.model = builder.get_object("liststore1")
        self.treeview = builder.get_object("treeview1")
        self.contents = builder.get_object("box1")
        self.revert_button = builder.get_object("revertButton")
        self.factory_settings = builder.get_object("resetButton")
        self.restart_warning = builder.get_object("restartWarning")

        self.sections = {}
        self.__fillContents()
        req = self.contents.size_request()
        min_width = req.width
        min_height = req.height
        width = max(min_width, self.settings.prefsDialogWidth)
        height = max(min_height, self.settings.prefsDialogHeight)
        self.dialog.set_transient_for(instance.gui)
        self.dialog.set_default_size(width, height)

    def run(self):
        """Run the internal dialog"""
        self.dialog.run()

## Public API

    @classmethod
    def addPreference(cls, attrname, label, description, section=None,
                    widget_class=None, **args):
        """
        Add a user preference. The preferences dialog will try
        to guess the appropriate widget to use based on the type of the
        option, but you can override this by specifying a custom class.

        @param label: user-visible name for this option
        @type label: C{str}
        @param description: a user-visible description documenting this option
        (ignored unless prefs_label is non-null)
        @type description: C{str}
        @param : user-visible category to which this option
        belongs (ignored unless prefs_label is non-null)
        @type section: C{str}
        @param widget_class: overrides auto-detected widget
        @type widget_class: C{class}
        """
        if not section:
            section = "General"
        if not section in cls.prefs:
            cls.prefs[section] = {}
        cls.prefs[section][attrname] = (label, description, widget_class, args)

    @classmethod
    def addPathPreference(cls, attrname, label, description, section=None):
        """
        Add an auto-generated user preference that will show up as a
        Gtk.FileChooserButton.

        @param label: user-visible name for this option
        @type label: C{str}
        @param description: a user-visible description documenting this option
        (ignored unless prefs_label is non-null)
        @type description: C{str}
        @param section: user-visible category to which this option
        belongs (ignored unless prefs_label is non-null)
        @type section: C{str}
        """
        cls.addPreference(attrname, label, description, section,
            ptvWidgets.PathWidget)

    @classmethod
    def addNumericPreference(cls, attrname, label, description, section=None,
                            upper=None, lower=None):
        """
        Add an auto-generated user preference that will show up as either a
        Gtk.SpinButton or an horizontal Gtk.Scale, depending whether both the
        upper and lower limits are set.

        @param label: user-visible name for this option
        @type label: C{str}
        @param description: a user-visible description documenting this option
        (ignored unless prefs_label is non-null)
        @type description: C{str}
        @param section: user-visible category to which this option
        belongs (ignored unless prefs_label is non-null)
        @type section: C{str}
        @param upper: upper limit for this widget, or None
        @type upper: C{number}
        @param lower: lower limit for this widget, or None
        @type lower: C{number}
        """
        cls.addPreference(attrname, label, description, section,
            ptvWidgets.NumericWidget, upper=upper, lower=lower)

    @classmethod
    def addTextPreference(cls, attrname, label, description, section=None, matches=None):
        """
        Add an auto-generated user preference that will show up as either a
        Gtk.SpinButton or an horizontal Gtk.Scale, depending on the upper and
        lower limits

        @param label: user-visible name for this option
        @type label: C{str}
        @param description: a user-visible description documenting this option
        (ignored unless prefs_label is non-null)
        @type description: C{str}
        @param section: user-visible category to which this option
        belongs (ignored unless prefs_label is non-null)
        @type section: C{str}
        """
        cls.addPreference(attrname, label, description, section,
            ptvWidgets.TextWidget, matches=matches)

    @classmethod
    def addChoicePreference(cls, attrname, label, description, choices, section=None):
        """
        Add an auto-generated user preference that will show up as either a
        Gtk.ComboBox or a group of radio buttons, depending on the number of
        choices.

        @param label: user-visible name for this option
        @type label: C{str}
        @param description: a user-visible description documenting this option
        (ignored unless prefs_label is non-null)
        @type description: C{str}
        @param choices: a sequence of (<label>, <value>) pairs
        @type choices: C{[(str, pyobject), ...]}
        @param section: user-visible category to which this option
        belongs (ignored unless prefs_label is non-null)
        @type section: C{str}
        """
        cls.addPreference(attrname, label, description, section,
            ptvWidgets.ChoiceWidget, choices=choices)

    @classmethod
    def addTogglePreference(cls, attrname, label, description, section=None):
        """
        Add an auto-generated user preference that will show up as a
        Gtk.CheckButton.

        @param label: user-visible name for this option
        @type label: C{str}
        @param description: a user-visible description documenting this option
        (ignored unless prefs_label is non-null)
        @type description: C{str}
        @param section: user-visible category to which this option
        belongs (ignored unless prefs_label is non-null)
        @type section: C{str}
        """
        cls.addPreference(attrname, label, description, section,
            ptvWidgets.ToggleWidget)

    @classmethod
    def addColorPreference(cls, attrname, label, description, section=None, value_type=int):
        """
        Add an auto-generated user preference for specifying colors. The
        colors can be returned as either int, a string colorspec, or a
        Gdk.Color object. See the Gdk.color_parse() function for info
        on colorspecs.

        @param label: user-visible name for this option
        @type label: C{str}
        @param description: a user-visible description documenting this option
        (ignored unless prefs_label is non-null)
        @type description: C{str}
        @param section: user-visible category to which this option
        belongs (ignored unless prefs_label is non-null)
        @type section: C{str}
        """
        cls.addPreference(attrname, label, description, section,
            ptvWidgets.ColorWidget, value_type=value_type)

    @classmethod
    def addFontPreference(cls, attrname, label, description, section=None):
        """
        Add an auto-generated user preference that will show up as a
        font selector.

        @param label: user-visible name for this option
        @type label: C{str}
        @param description: a user-visible description documenting this option
        (ignored unless prefs_label is non-null)
        @type description: C{str}
        @param section: user-visible category to which this option
        belongs (ignored unless prefs_label is non-null)
        @type section: C{str}
        """
        cls.addPreference(attrname, label, description, section,
            ptvWidgets.FontWidget)

## Implementation
    def __fillContents(self):
        for section in sorted(self.prefs):
            options = self.prefs[section]
            self.model.append((_(section), section))
            widgets = Gtk.Table()
            widgets.set_border_width(SPACING)
            widgets.props.column_spacing = SPACING
            widgets.props.row_spacing = SPACING / 2
            self.sections[section] = widgets

            prefs = {}
            for attrname in options:
                label, description, widget_class, args = options[attrname]
                widget = widget_class(**args)
                widget.setWidgetValue(getattr(self.settings, attrname))
                widget.connectValueChanged(self._valueChanged, widget, attrname)
                self.widgets[attrname] = widget
                if isinstance(widget, ptvWidgets.ToggleWidget):
                    # Don't add a semicolon for checkbuttons
                    label_widget = Gtk.Label(label=_(label))
                else:
                    label_widget = Gtk.Label(label=_(label) + ":")
                icon = Gtk.Image()
                icon.set_from_icon_name("edit-clear-all-symbolic", Gtk.IconSize.MENU)
                revert = Gtk.Button()
                revert.add(icon)
                revert.set_tooltip_text(_("Reset to default value"))
                revert.set_relief(Gtk.ReliefStyle.NONE)
                revert.set_sensitive(not self.settings.isDefault(attrname))
                revert.connect("clicked", self._resetOptionCb, attrname)
                revert.show_all()
                self.resets[attrname] = revert
                prefs[label] = (label_widget, widget, description, revert)

            # Sort widgets: I think we only want to sort by the non-localized
            # names, so options appear in the same place across locales ...
            # but then I may be wrong

            for y, unlocalized in enumerate(sorted(prefs)):
                label, widget, description, revert = prefs[unlocalized]
                if isinstance(widget, ptvWidgets.ToggleWidget):
                    # Avoid the separating the label from the checkbox
                    widget.set_label(label.get_text())
                    widgets.attach(widget, 0, 2, y, y + 1, yoptions=0)
                    widgets.attach(revert, 2, 3, y, y + 1, xoptions=0, yoptions=0)
                else:
                    label.set_alignment(1.0, 0.5)
                    label.set_tooltip_text(description)
                    widgets.attach(label, 0, 1, y, y + 1, xoptions=Gtk.AttachOptions.FILL, yoptions=0)
                    widgets.attach(widget, 1, 2, y, y + 1, yoptions=0)
                    widgets.attach(revert, 2, 3, y, y + 1, xoptions=0, yoptions=0)
                    label.show()
                widget.set_tooltip_text(description)
                widget.show()
                revert.show()

            self.contents.pack_start(widgets, True, True, 0)

        self.treeview.get_selection().select_path((0,))
        self.factory_settings.set_sensitive(self._canReset())

    def _treeSelectionChangedCb(self, selection):
        """ Update current when selection changed"""
        model, _iter = selection.get_selected()
        new = self.sections[model[_iter][1]]
        if self._current != new:
            if self._current:
                self._current.hide()
            new.show()
            self._current = new

    def _clearHistory(self):
        # Disable missing docstring
        #pylint: disable=C0111
        self.original_values = {}
        self.revert_button.set_sensitive(False)

    def _factorySettingsButtonCb(self, unused_button):
        """
        Reset all settings to the defaults
        """
        for section in self.prefs.values():
            for attrname in section:
                self._resetOptionCb(self.resets[attrname], attrname)

    def _revertButtonCb(self, unused_button):
        """
        Resets all settings to the values from before the user opened the
        preferences dialog.
        """
        for attrname, value in self.original_values.items():
            self.widgets[attrname].setWidgetValue(value)
            setattr(self.settings, attrname, value)
        self._clearHistory()
        self.factory_settings.set_sensitive(self._canReset())

    def _resetOptionCb(self, button, attrname):
        """
        Reset a particular setting to the factory default
        """
        if not self.settings.isDefault(attrname):
            self.settings.setDefault(attrname)
        self.widgets[attrname].setWidgetValue(getattr(self.settings, attrname))
        button.set_sensitive(False)
        self.factory_settings.set_sensitive(self._canReset())

    def _acceptButtonCb(self, unused_button):
        # Disable missing docstring
        #pylint: disable=C0111
        self._clearHistory()
        self.dialog.hide()

    def _valueChanged(self, unused_fake_widget, real_widget, attrname):
        # Disable missing docstring
        #pylint: disable=C0111
        value = getattr(self.settings, attrname)
        if attrname not in self.original_values:
            self.original_values[attrname] = value
            if attrname + "Changed" not in GlobalSettings.get_signals():
                self.restart_warning.show()
            self.revert_button.set_sensitive(True)

        # convert the value of the widget to whatever type it is currently
        if value is not None:
            value = type(value)(real_widget.getWidgetValue())
        setattr(self.settings, attrname, value)

        # adjust controls as appropriate
        self.resets[attrname].set_sensitive(not self.settings.isDefault(attrname))
        self.factory_settings.set_sensitive(True)

    def _configureCb(self, unused_widget, event):
        # Disable missing docstring
        #pylint: disable=C0111
        self.settings.prefsDialogWidth = event.width
        self.settings.prefsDialogHeight = event.height

    def _canReset(self):
        # Disable missing docstring
        #pylint: disable=C0111
        for section in self.prefs.values():
            for attrname in section:
                if not self.settings.isDefault(attrname):
                    return True
        return False
