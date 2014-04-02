# -*- coding: utf-8 -*-
# Pitivi video editor
#
#       pitivi/mainwindow.py
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

import os

from time import time
from urllib.parse import unquote
from gettext import gettext as _
from hashlib import md5

from gi.repository import GES
from gi.repository import Gdk
from gi.repository import GdkPixbuf
from gi.repository import Gio
from gi.repository import Gst
from gi.repository import Gtk
from gi.repository.GstPbutils import InstallPluginsContext, install_plugins_async

from pitivi.clipproperties import ClipProperties
from pitivi.configure import in_devel, VERSION, APPNAME, APPURL, get_pixmap_dir, get_ui_dir
from pitivi.effects import EffectListWidget
from pitivi.mediafilespreviewer import PreviewWidget
from pitivi.medialibrary import MediaLibraryWidget
from pitivi.settings import GlobalSettings
from pitivi.tabsmanager import BaseTabs
from pitivi.timeline.timeline import TimelineContainer
from pitivi.titleeditor import TitleEditor
from pitivi.transitions import TransitionsListWidget
from pitivi.utils.loggable import Loggable
from pitivi.utils.misc import show_user_manual, path_from_uri
from pitivi.utils.ui import info_name, beautify_time_delta, SPACING, \
    beautify_length
from pitivi.viewer import ViewerContainer


GlobalSettings.addConfigSection("main-window")
GlobalSettings.addConfigOption('mainWindowHPanePosition',
    section="main-window",
    key="hpane-position",
    type_=int)
GlobalSettings.addConfigOption('mainWindowMainHPanePosition',
    section="main-window",
    key="main-hpane-position",
    type_=int)
GlobalSettings.addConfigOption('mainWindowVPanePosition',
    section="main-window",
    key="vpane-position",
    default=200)
GlobalSettings.addConfigOption('mainWindowX',
    section="main-window",
    key="X", default=0, type_=int)
GlobalSettings.addConfigOption('mainWindowY',
    section="main-window",
    key="Y", default=0, type_=int)
GlobalSettings.addConfigOption('mainWindowWidth',
    section="main-window",
    key="width", default=-1, type_=int)
GlobalSettings.addConfigOption('mainWindowHeight',
    section="main-window",
    key="height", default=-1, type_=int)
GlobalSettings.addConfigOption('lastProjectFolder',
    section="main-window",
    key="last-folder",
    environment="PITIVI_PROJECT_FOLDER",
    default=os.path.expanduser("~"))
GlobalSettings.addConfigSection('export')
GlobalSettings.addConfigOption('lastExportFolder',
                            section='export',
                            key="last-export-folder",
                            environment="PITIVI_EXPORT_FOLDER",
                            default=os.path.expanduser("~"))
GlobalSettings.addConfigOption('elementSettingsDialogWidth',
    section='export',
    key='element-settings-dialog-width',
    default=620)
GlobalSettings.addConfigOption('elementSettingsDialogHeight',
    section='export',
    key='element-settings-dialog-height',
    default=460)
GlobalSettings.addConfigSection("effect-configuration")
GlobalSettings.addConfigOption('effectVPanedPosition',
    section='effect-configuration',
    key='effect-vpaned-position',
    type_=int)
GlobalSettings.addConfigSection("version")
GlobalSettings.addConfigOption('displayCounter',
    section='version',
    key='info-displayed-counter',
    default=0)
GlobalSettings.addConfigOption('lastCurrentVersion',
    section='version',
    key='last-current-version',
    default='')
GlobalSettings.addConfigOption('timelineAutoRipple',
    section='user-interface',
    key='timeline-autoripple',
    default=False)


# FIXME PyGi to get stock_add working
Gtk.stock_add = lambda items: None


def create_stock_icons():
    """ Creates the pitivi-only stock icons """
    Gtk.stock_add([
        ('pitivi-split', _('Split'), 0, 0, 'pitivi'),
        ('pitivi-keyframe', _('Keyframe'), 0, 0, 'pitivi'),
        ('pitivi-ungroup', _('Ungroup'), 0, 0, 'pitivi'),
        # Translators: This is an action, the title of a button
        ('pitivi-group', _('Group'), 0, 0, 'pitivi'),
        ('pitivi-align', _('Align'), 0, 0, 'pitivi'),
        ('pitivi-gapless', _('Gapless mode'), 0, 0, 'pitivi'),
    ])
    pixmaps = {
        "pitivi-split": "pitivi-split-24.svg",
        "pitivi-keyframe": "pitivi-keyframe-24.svg",
        "pitivi-ungroup": "pitivi-ungroup-24.svg",
        "pitivi-group": "pitivi-group-24.svg",
        "pitivi-align": "pitivi-align-24.svg",
        "pitivi-gapless": "pitivi-gapless-24.svg",
    }
    factory = Gtk.IconFactory()
    pmdir = get_pixmap_dir()
    for stockid, path in pixmaps.items():
        pixbuf = GdkPixbuf.Pixbuf.new_from_file(os.path.join(pmdir, path))
        iconset = Gtk.IconSet.new_from_pixbuf(pixbuf)
        factory.add(stockid, iconset)
        factory.add_default()


class PitiviMainWindow(Gtk.ApplicationWindow, Loggable):
    """
    Pitivi's main window.

    @cvar app: The application object
    @type app: L{Pitivi}
    """
    def __init__(self, app):
        gtksettings = Gtk.Settings.get_default()
        gtksettings.set_property("gtk-application-prefer-dark-theme", True)
        # Pulseaudio "role" (http://0pointer.de/blog/projects/tagging-audio.htm)
        os.environ["PULSE_PROP_media.role"] = "production"
        os.environ["PULSE_PROP_application.icon_name"] = "pitivi"

        Gtk.ApplicationWindow.__init__(self)
        Loggable.__init__(self, "mainwindow")
        self.app = app
        self.log("Creating MainWindow")
        self.settings = app.settings
        self.prefsdialog = None
        create_stock_icons()

        self.uimanager = Gtk.UIManager()
        self.add_accel_group(self.uimanager.get_accel_group())

        self._createUi()
        self.recent_manager = Gtk.RecentManager()
        self._missingUriOnLoading = False

        pm = self.app.project_manager
        pm.connect("new-project-loading", self._projectManagerNewProjectLoadingCb)
        pm.connect("new-project-loaded", self._projectManagerNewProjectLoadedCb)
        pm.connect("new-project-failed", self._projectManagerNewProjectFailedCb)
        pm.connect("save-project-failed", self._projectManagerSaveProjectFailedCb)
        pm.connect("project-saved", self._projectManagerProjectSavedCb)
        pm.connect("closing-project", self._projectManagerClosingProjectCb)
        pm.connect("reverting-to-saved", self._projectManagerRevertingToSavedCb)
        pm.connect("project-closed", self._projectManagerProjectClosedCb)
        pm.connect("missing-uri", self._projectManagerMissingUriCb)

    def showRenderDialog(self, project):
        """
        Shows the L{RenderDialog} for the given project Timeline.

        @param project: The project
        @type project: L{Project}
        """
        from pitivi.render import RenderDialog

        dialog = RenderDialog(self.app, project)
        dialog.window.connect("destroy", self._renderDialogDestroyCb)
        self.set_sensitive(False)
        self.timeline_ui.disableKeyboardAndMouseEvents()
        dialog.window.show()

    def _renderDialogDestroyCb(self, unused_dialog):
        self.set_sensitive(True)
        self.timeline_ui.enableKeyboardAndMouseEvents()

    def _renderCb(self, unused_button):
        self.showRenderDialog(self.app.project_manager.current_project)

    def _createUi(self):
        """
        Create the graphical interface with the following hierarchy in a vbox:
        -- self.vpaned
        ---- self.mainhpaned (upper half)
        ------ self.secondaryhpaned (upper-left)
        -------- Primary tabs
        -------- Context tabs
        ------ Viewer (upper-right)
        ---- Timeline (bottom half)

        In the window titlebar, there is also a HeaderBar widget.

        The full hierarchy is also visible with accessibility tools like "sniff"
        """
        self.set_title("%s" % APPNAME)
        self.set_icon_name("pitivi")
        vbox = Gtk.VBox(homogeneous=False)
        self.add(vbox)
        vbox.show()

        # Main "toolbar" (using client-side window decorations with HeaderBar)
        self._headerbar = Gtk.HeaderBar()
        self._create_headerbar_buttons()
        builder = Gtk.Builder()
        builder.add_from_file(os.path.join(get_ui_dir(), "mainmenubutton.ui"))
        builder.connect_signals(self)
        self._menubutton = builder.get_object("menubutton")
        self._menubutton_items = {}
        for widget in builder.get_object("menu").get_children():
            self._menubutton_items[Gtk.Buildable.get_name(widget)] = widget

        self._headerbar.pack_end(self._menubutton)
        self._headerbar.set_show_close_button(True)
        self._headerbar.show_all()
        self.set_titlebar(self._headerbar)

        # Set up our main containers, in the order documented above
        self.vpaned = Gtk.VPaned()  # Separates the timeline from tabs+viewer
        self.mainhpaned = Gtk.HPaned()  # Separates the viewer from tabs
        self.secondhpaned = Gtk.HPaned()  # Separates the two sets of tabs
        self.vpaned.pack1(self.mainhpaned, resize=True, shrink=False)
        self.mainhpaned.pack1(self.secondhpaned, resize=True, shrink=False)
        vbox.pack_start(self.vpaned, True, True, 0)
        self.vpaned.show()
        self.secondhpaned.show()
        self.mainhpaned.show()

        # First set of tabs
        self.main_tabs = BaseTabs(self.app)
        self.medialibrary = MediaLibraryWidget(self.app, self.uimanager)
        self.effectlist = EffectListWidget(self.app, self.uimanager)
        self.main_tabs.append_page(self.medialibrary, Gtk.Label(label=_("Media Library")))
        self.main_tabs.append_page(self.effectlist, Gtk.Label(label=_("Effect Library")))
        self.medialibrary.connect('play', self._mediaLibraryPlayCb)
        self.medialibrary.show()
        self.effectlist.show()

        # Second set of tabs
        self.context_tabs = BaseTabs(self.app)
        self.clipconfig = ClipProperties(self.app)
        self.trans_list = TransitionsListWidget(self.app)
        self.title_editor = TitleEditor(self.app)
        self.context_tabs.append_page(self.clipconfig, Gtk.Label(label=_("Clip")))
        self.context_tabs.append_page(self.trans_list, Gtk.Label(label=_("Transition")))
        self.context_tabs.append_page(self.title_editor.widget, Gtk.Label(label=_("Title")))
        self.context_tabs.connect("switch-page", self.title_editor.tabSwitchedCb)
        # Show by default the Title tab, as the Clip and Transition tabs
        # are useful only when a clip or transition is selected, but
        # the Title tab allows adding titles.
        self.context_tabs.set_current_page(2)

        self.secondhpaned.pack1(self.main_tabs, resize=True, shrink=False)
        self.secondhpaned.pack2(self.context_tabs, resize=False, shrink=False)
        self.main_tabs.show()
        self.context_tabs.show()

        # Viewer
        self.viewer = ViewerContainer(self.app)
        self.mainhpaned.pack2(self.viewer, resize=False, shrink=False)

        # Now, the lower part: the timeline
        self.timeline_ui = TimelineContainer(self, self.app, self.uimanager)
        self.timeline_ui.setProjectManager(self.app.project_manager)
        self.vpaned.pack2(self.timeline_ui, resize=True, shrink=False)

        # Enable our shortcuts for HeaderBar buttons and menu items:
        self._set_keyboard_shortcuts()

        # Identify widgets for AT-SPI, making our test suite easier to develop
        # These will show up in sniff, accerciser, etc.
        self.get_accessible().set_name("main window")
        self._headerbar.get_accessible().set_name("headerbar")
        self._menubutton.get_accessible().set_name("main menu button")
        self.vpaned.get_accessible().set_name("contents")
        self.mainhpaned.get_accessible().set_name("upper half")
        self.secondhpaned.get_accessible().set_name("tabs")
        self.main_tabs.get_accessible().set_name("primary tabs")
        self.context_tabs.get_accessible().set_name("secondary tabs")
        self.viewer.get_accessible().set_name("viewer")
        self.timeline_ui.get_accessible().set_name("timeline area")

        # Restore settings (or set defaults) for position and visibility
        if self.settings.mainWindowHPanePosition:
            self.secondhpaned.set_position(self.settings.mainWindowHPanePosition)
        if self.settings.mainWindowMainHPanePosition:
            self.mainhpaned.set_position(self.settings.mainWindowMainHPanePosition)
        if self.settings.mainWindowVPanePosition:
            self.vpaned.set_position(self.settings.mainWindowVPanePosition)
        width = self.settings.mainWindowWidth
        height = self.settings.mainWindowHeight
        # Maximize by default; if the user chose a custom size, resize & move
        if height == -1 and width == -1:
            self.maximize()
        else:
            self.set_default_size(width, height)
            self.move(self.settings.mainWindowX, self.settings.mainWindowY)

        # Connect the main window's signals at the end, to avoid messing around
        # with the restoration of settings above.
        self.connect("delete-event", self._deleteCb)
        self.connect("configure-event", self._configureCb)

        # Focus the timeline by default!
        self.timeline_ui.grab_focus()

    def switchContextTab(self, bElement):
        """
        Switch the tab being displayed on the second set of tabs,
        depending on the context.

        @param bElement: The timeline element which has been focused.
        @type bElement: GES.TrackElement
        """
        if isinstance(bElement, GES.TitleSource):
            page = 2
        elif isinstance(bElement, GES.Source):
            # This covers: VideoUriSource, ImageSource, AudioUriSource.
            page = 0
        elif isinstance(bElement, GES.Transition):
            page = 1
        else:
            self.warning("Unknown element type: %s", bElement)
            return
        self.context_tabs.set_current_page(page)

    def focusTimeline(self):
        self.timeline_ui.grab_focus()

    def _create_headerbar_buttons(self):
        self.undo_button = Gtk.Button.new_from_icon_name("edit-undo-symbolic", Gtk.IconSize.LARGE_TOOLBAR)
        self.undo_button.set_always_show_image(True)
        self.undo_button.set_label(_("Undo"))
        self.undo_button.set_action_name("app.undo")

        self.redo_button = Gtk.Button.new_from_icon_name("edit-redo-symbolic", Gtk.IconSize.LARGE_TOOLBAR)
        self.redo_button.set_always_show_image(True)
        self.redo_button.set_label(_("Redo"))
        self.redo_button.set_action_name("app.redo")

        separator = Gtk.Separator()

        self.save_button = Gtk.Button.new_from_icon_name("document-save", Gtk.IconSize.LARGE_TOOLBAR)
        self.save_button.set_always_show_image(True)
        self.save_button.set_label(_("Save"))

        render_icon = Gtk.Image.new_from_file(os.path.join(get_pixmap_dir(), "pitivi-render-24.png"))
        self.render_button = Gtk.Button()
        self.render_button.set_image(render_icon)
        self.render_button.set_always_show_image(True)
        self.render_button.set_label(_("Render"))
        self.render_button.set_tooltip_text(_("Export your project as a finished movie"))
        self.render_button.set_sensitive(False)  # The only one we have to set.
        self.render_button.connect("clicked", self._renderCb)

        self._headerbar.pack_start(self.undo_button)
        self._headerbar.pack_start(self.redo_button)
        self._headerbar.pack_start(separator)
        self._headerbar.pack_start(self.save_button)
        self._headerbar.pack_start(self.render_button)

    def _set_keyboard_shortcuts(self):
        """
        You can't rely on Glade/GTKBuilder to set accelerators properly
        on menu items or buttons, it just doesn't work.
        GAction and GActionGroup are overkill and a massive PITA.

        This code keeps things *really* simple, and it actually works.
        Bonus points: the accelerators disable themselves when buttons or
        menu items are set_sensitive(False), which is exactly what we want.
        """
        self.save_action = Gio.SimpleAction.new("save", None)
        self.save_action.connect("activate", self._saveProjectCb)
        self.add_action(self.save_action)
        self.app.add_accelerator("<Control>s", "win.save", None)
        self.save_button.set_action_name("win.save")

        self.new_project_action = Gio.SimpleAction.new("new_project", None)
        self.new_project_action.connect("activate", self._newProjectMenuCb)
        self.add_action(self.new_project_action)
        self.app.add_accelerator("<Control>n", "win.new_project", None)

        self.open_project_action = Gio.SimpleAction.new("open_project", None)
        self.open_project_action.connect("activate", self._openProjectCb)
        self.add_action(self.open_project_action)
        self.app.add_accelerator("<Control>o", "win.open_project", None)

        self.save_as_action = Gio.SimpleAction.new("save_as", None)
        self.save_as_action.connect("activate", self._saveProjectAsCb)
        self.add_action(self.save_as_action)
        self.app.add_accelerator("<Control><Shift>s", "win.save_as", None)

        self.help_action = Gio.SimpleAction.new("help", None)
        self.help_action.connect("activate", self._userManualCb)
        self.add_action(self.help_action)
        self.app.add_accelerator("F1", "win.help", None)

        def menuCb(unused_action, unused_param):
            self._menubutton.set_active(not self._menubutton.get_active())

        menu_button_action = Gio.SimpleAction.new("menu_button", None)
        menu_button_action.connect("activate", menuCb)
        self.add_action(menu_button_action)
        self.app.add_accelerator("F10", "win.menu_button", None)

    def showProjectStatus(self):
        dirty = self.app.project_manager.current_project.hasUnsavedModifications()
        self.save_action.set_enabled(dirty)
        if self.app.project_manager.current_project.uri:
            self._menubutton_items["menu_revert_to_saved"].set_sensitive(dirty)
        self.updateTitle()

## Missing Plugin Support

    def _installPlugins(self, details, missingPluginsCallback):
        context = InstallPluginsContext()
        context.set_xid(self.window.xid)

        res = install_plugins_async(details, context,
                missingPluginsCallback)
        return res

## UI Callbacks

    def _configureCb(self, unused_widget, event):
        """
        Handle the main window being moved, resized or maximized
        """
        # get_position() takes window manager decoration into account
        position = self.get_position()
        self.settings.mainWindowWidth = event.width
        self.settings.mainWindowHeight = event.height
        self.settings.mainWindowX = position[0]
        self.settings.mainWindowY = position[1]

    def _deleteCb(self, unused_widget, unused_data=None):
        self._saveWindowSettings()
        if not self.app.shutdown():
            return True

        return False

    def _saveWindowSettings(self):
        self.settings.mainWindowHPanePosition = self.secondhpaned.get_position()
        self.settings.mainWindowMainHPanePosition = self.mainhpaned.get_position()
        self.settings.mainWindowVPanePosition = self.vpaned.get_position()

    def _mediaLibraryPlayCb(self, unused_medialibrary, asset):
        """
        If the media library item to preview is an image, show it in the user's
        favorite image viewer. Else, preview the video/sound in Pitivi.
        """
        # Technically, our preview widget can show images, but it's never going
        # to do a better job (sizing, zooming, metadata, editing, etc.)
        # than the user's favorite image viewer.
        if asset.is_image():
            os.system('xdg-open "%s"' % path_from_uri(asset.get_id()))
        else:
            preview_window = PreviewAssetWindow(asset, self)
            preview_window.preview()

    def _projectChangedCb(self, unused_project):
        self.save_action.set_enabled(True)
        self.updateTitle()

    def _mediaLibrarySourceRemovedCb(self, unused_project, asset):
        """When a clip is removed from the Media Library, tell the timeline
        to remove all instances of that clip."""
        self.timeline_ui.purgeObject(asset.get_id())

## Toolbar/Menu actions callback

    def _newProjectMenuCb(self, unused_action, unused_param):
        if self.app.project_manager.newBlankProject() is not False:
            self.showProjectSettingsDialog()

    def _openProjectCb(self, unused_action, unused_param):
        self.openProject()

    def _saveProjectCb(self, action, unused_param):
        if not self.app.project_manager.current_project.uri or self.app.project_manager.disable_save:
            self._saveProjectAsCb(action, None)
        else:
            self.app.project_manager.saveProject()

    def _saveProjectAsCb(self, unused_action, unused_param):
        uri = self._showSaveAsDialog(self.app.project_manager.current_project)
        if uri is not None:
            return self.app.project_manager.saveProject(uri)

        return False

    def _revertToSavedProjectCb(self, unused_action):
        return self.app.project_manager.revertToSavedProject()

    def _exportProjectAsTarCb(self, unused_action):
        uri = self._showExportDialog(self.app.project_manager.current_project)
        result = None
        if uri:
            result = self.app.project_manager.exportProject(self.app.project_manager.current_project, uri)

        if not result:
            self.log("Project couldn't be exported")
        return result

    def _projectSettingsCb(self, unused_action):
        self.showProjectSettingsDialog()

    def showProjectSettingsDialog(self):
        from pitivi.project import ProjectSettingsDialog
        ProjectSettingsDialog(self, self.app.project_manager.current_project).window.run()
        self.updateTitle()

    def _userManualCb(self, unused_action, unused_param):
        show_user_manual()

    def _aboutResponseCb(self, dialog, unused_response):
        dialog.destroy()

    def _aboutCb(self, unused_action):
        abt = Gtk.AboutDialog()
        abt.set_program_name(APPNAME)
        abt.set_website(APPURL)

        if in_devel():
            version_str = _("Development version")
        elif not self.app.isLatest():
            version_str = _("Version %(cur_ver)s — %(new_ver)s is available" %
                            {"cur_ver": VERSION,
                             "new_ver": self.app.getLatest()})
        else:
            version_str = _("Version %s" % VERSION)
        abt.set_version(version_str)

        comments = ["",
                    "GES %s" % ".".join(map(str, GES.version())),
                    "GStreamer %s" % ".".join(map(str, Gst.version()))]
        abt.set_comments("\n".join(comments))

        authors = [_("Current maintainers:"),
                   "Jean-François Fortin Tam <nekohayo@gmail.com>",
                   "Thibault Saunier <thibault.saunier@collabora.com>",
                   "Mathieu Duponchelle <mduponchelle1@gmail.com>",
                   "",
                   _("Past maintainers:"),
                   "Edward Hervey <bilboed@bilboed.com>",
                   "Alessandro Decina <alessandro.decina@collabora.co.uk>",
                   "Brandon Lewis <brandon_lewis@berkeley.edu>",
                   "",
                   # Translators: this paragraph is to be translated, the list of contributors is shown dynamically as a clickable link below it
                   _("Contributors:\n" +
                   "A handwritten list here would...\n" +
                   "• be too long,\n" +
                   "• be frequently outdated,\n" +
                   "• not show their relative merit.\n\n" +
                   "Out of respect for our contributors, we point you instead to:\n"),
                   # Translators: keep the %s at the end of the 1st line
                   _("The list of contributors on Ohloh %s\n" +
                   "Or you can run: git shortlog -s -n")
                   % "http://ohloh.net/p/pitivi/contributors", ]
        abt.set_authors(authors)
        translators = _("translator-credits")
        if translators != "translator-credits":
            abt.set_translator_credits(translators)
        documenters = ["Jean-François Fortin Tam <nekohayo@gmail.com>", ]
        abt.set_documenters(documenters)
        abt.set_license_type(Gtk.License.LGPL_2_1)
        abt.set_icon_name("pitivi")
        abt.set_logo_icon_name("pitivi")
        abt.connect("response", self._aboutResponseCb)
        abt.show()

    def openProject(self):
        # Requesting project closure at this point in time prompts users about
        # unsaved changes (if any); much better than having ProjectManager
        # trigger this *after* the user already chose a new project to load...
        if not self.app.project_manager.closeRunningProject():
            return  # The user has not made a decision, don't do anything

        chooser = Gtk.FileChooserDialog(title=_("Open File..."),
            transient_for=self,
            action=Gtk.FileChooserAction.OPEN)
        chooser.add_buttons(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
                Gtk.STOCK_OPEN, Gtk.ResponseType.OK)
        chooser.set_select_multiple(False)
        # TODO: Remove this set_current_folder call when GTK bug 683999 is fixed
        chooser.set_current_folder(self.settings.lastProjectFolder)
        formatter_assets = GES.list_assets(GES.Formatter)
        formatter_assets.sort(key=lambda x: - x.get_meta(GES.META_FORMATTER_RANK))
        for format_ in formatter_assets:
            filt = Gtk.FileFilter()
            filt.set_name(format_.get_meta(GES.META_DESCRIPTION))
            filt.add_pattern("*%s" % format_.get_meta(GES.META_FORMATTER_EXTENSION))
            chooser.add_filter(filt)
        default = Gtk.FileFilter()
        default.set_name(_("All supported formats"))
        default.add_custom(Gtk.FileFilterFlags.URI, self._canLoadUri, None)
        chooser.add_filter(default)

        response = chooser.run()
        if response == Gtk.ResponseType.OK:
            self.app.project_manager.loadProject(chooser.get_uri())
        else:
            self.info("User cancelled loading a new project, but no other project is currently active. Resetting")
            self.app.project_manager.newBlankProject()
        chooser.destroy()
        return True

    def _canLoadUri(self, filterinfo, unused_uri):
        try:
            return GES.Formatter.can_load_uri(filterinfo.uri)
        except:
            return False

    def _prefsCb(self, unused_action):
        if not self.prefsdialog:
            from pitivi.dialogs.prefs import PreferencesDialog
            self.prefsdialog = PreferencesDialog(self.app)
        self.prefsdialog.run()

## Project management callbacks

    def _projectManagerNewProjectLoadedCb(self, project_manager, unused_project, unused_fully_loaded):
        """
        @type project_manager: L{ProjectManager}
        """
        self.log("A new project is loaded")
        self._connectToProject(self.app.project_manager.current_project)
        self.app.project_manager.current_project.timeline.connect("notify::duration",
                self._timelineDurationChangedCb)
        self.app.project_manager.current_project.pipeline.activatePositionListener()
        self._setProject()

        #FIXME GES we should re-enable this when possible
        #self._syncDoUndo(self.app.action_log)
        self.updateTitle()

        if self._missingUriOnLoading:
            self.app.project_manager.current_project.setModificationState(True)
            self.save_action.set_enabled(True)
            self._missingUriOnLoading = False

        if project_manager.disable_save is True:
            # Special case: we enforce "Save as", but the normal "Save" button
            # redirects to it if needed, so we still want it to be enabled:
            self.save_action.set_enabled(True)

        if self.app.project_manager.current_project.timeline.props.duration != 0:
            self.render_button.set_sensitive(True)

    def _projectManagerNewProjectLoadingCb(self, unused_project_manager, uri):
        if uri:
            self.recent_manager.add_item(uri)
        self.log("A NEW project is loading, deactivate UI")

    def _projectManagerSaveProjectFailedCb(self, unused_project_manager, uri, exception=None):
        project_filename = unquote(uri.split("/")[-1])
        dialog = Gtk.MessageDialog(transient_for=self,
            modal=True,
            message_type=Gtk.MessageType.ERROR,
            buttons=Gtk.ButtonsType.OK,
            text=_('Unable to save project "%s"') % project_filename)
        if exception:
            dialog.set_property("secondary-use-markup", True)
            dialog.set_property("secondary-text", unquote(str(exception)))
        dialog.set_transient_for(self)
        dialog.run()
        dialog.destroy()
        self.error("failed to save project")

    def _projectManagerProjectSavedCb(self, unused_project_manager, project, uri):
        # FIXME GES: Reimplement Undo/Redo
        #self.app.action_log.checkpoint()
        #self._syncDoUndo(self.app.action_log)
        self.updateTitle()

        self.save_action.set_enabled(False)
        if uri:
            self.recent_manager.add_item(uri)

        if project.uri is None:
            project.uri = uri

    def _projectManagerClosingProjectCb(self, project_manager, project):
        """
        @type project_manager: L{ProjectManager}
        @type project: L{Project}
        """
        if not project.hasUnsavedModifications():
            return True

        if project.uri and not project_manager.disable_save:
            save = Gtk.STOCK_SAVE
        else:
            save = Gtk.STOCK_SAVE_AS

        dialog = Gtk.Dialog(title="",
                            transient_for=self, modal=True)
        dialog.add_buttons(_("Close without saving"), Gtk.ResponseType.REJECT,
                Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
                save, Gtk.ResponseType.YES)
        # Even though we set the title to an empty string when creating dialog,
        # seems we really have to do it once more so it doesn't show "pitivi"...
        dialog.set_title("")
        dialog.set_resizable(False)
        dialog.set_default_response(Gtk.ResponseType.CANCEL)
        dialog.set_transient_for(self)
        dialog.get_accessible().set_name("unsaved changes dialog")

        primary = Gtk.Label()
        primary.set_line_wrap(True)
        primary.set_use_markup(True)
        primary.set_alignment(0, 0.5)

        message = _("Save changes to the current project before closing?")
        primary.set_markup("<span weight=\"bold\">" + message + "</span>")

        secondary = Gtk.Label()
        secondary.set_line_wrap(True)
        secondary.set_use_markup(True)
        secondary.set_alignment(0, 0.5)

        if project.uri:
            path = unquote(project.uri).split("file://")[1]
            last_saved = max(os.path.getmtime(path), project_manager.time_loaded)
            time_delta = time() - last_saved
            secondary.props.label = _("If you don't save, "
                "the changes from the last %s will be lost."
                % beautify_time_delta(time_delta))
        else:
            secondary.props.label = _("If you don't save, "
                                    "your changes will be lost.")

        # put the text in a vbox
        vbox = Gtk.VBox(homogeneous=False, spacing=SPACING * 2)
        vbox.pack_start(primary, True, True, 0)
        vbox.pack_start(secondary, True, True, 0)

        # make the [[image] text] hbox
        image = Gtk.Image.new_from_icon_name("dialog-question", Gtk.IconSize.DIALOG)
        hbox = Gtk.HBox(homogeneous=False, spacing=SPACING * 2)
        hbox.pack_start(image, False, True, 0)
        hbox.pack_start(vbox, True, True, 0)
        hbox.set_border_width(SPACING)

        # stuff the hbox in the dialog
        content_area = dialog.get_content_area()
        content_area.pack_start(hbox, True, True, 0)
        content_area.set_spacing(SPACING * 2)
        hbox.show_all()

        response = dialog.run()
        dialog.destroy()
        if response == Gtk.ResponseType.YES:
            if project.uri is not None and project_manager.disable_save is False:
                res = self.app.project_manager.saveProject()
            else:
                res = self._saveProjectAsCb(None)
        elif response == Gtk.ResponseType.REJECT:
            res = True
        else:
            res = False

        return res

    def _projectManagerProjectClosedCb(self, unused_project_manager, project):
        """
        This happens immediately when the user asks to load another project,
        after the user confirmed that unsaved changes can be discarded but
        before the filechooser to pick the new project to load appears...
        We can then expect another project to be loaded soon afterwards.
        """
        # We must disconnect from the project pipeline before it is released:
        if project.pipeline is not None:
            project.pipeline.deactivatePositionListener()

        self.info("Project closed - clearing the media library and timeline")
        self.medialibrary.storemodel.clear()
        self.timeline_ui.setProject(None)
        self.clipconfig.timeline = None
        self.render_button.set_sensitive(False)
        return False

    def _projectManagerRevertingToSavedCb(self, unused_project_manager, unused_project):
        if self.app.project_manager.current_project.hasUnsavedModifications():
            dialog = Gtk.MessageDialog(transient_for=self,
                    modal=True,
                    message_type=Gtk.MessageType.WARNING,
                    buttons=Gtk.ButtonsType.NONE,
                    text=_("Revert to saved project version?"))
            dialog.add_buttons(Gtk.STOCK_CANCEL, Gtk.ResponseType.NO,
                    Gtk.STOCK_REVERT_TO_SAVED, Gtk.ResponseType.YES)
            dialog.set_resizable(False)
            dialog.set_property("secondary-text",
                    _("This will reload the current project. All unsaved changes will be lost."))
            dialog.set_default_response(Gtk.ResponseType.NO)
            dialog.set_transient_for(self)
            response = dialog.run()
            dialog.destroy()
            if response != Gtk.ResponseType.YES:
                return False
        return True

    def _projectManagerNewProjectFailedCb(self, unused_project_manager, uri, exception):
        project_filename = unquote(uri.split("/")[-1])
        dialog = Gtk.MessageDialog(transient_for=self,
                                   modal=True,
                                   message_type=Gtk.MessageType.ERROR,
                                   buttons=Gtk.ButtonsType.OK,
                                   text=_('Unable to load project "%s"') % project_filename)
        dialog.set_property("secondary-use-markup", True)
        dialog.set_property("secondary-text", unquote(str(exception)))
        dialog.set_transient_for(self)
        dialog.run()
        dialog.destroy()

    def _projectManagerMissingUriCb(self, unused_project_manager, unused_project,
            unused_error, asset):
        self._missingUriOnLoading = True
        uri = asset.get_id()
        new_uri = None
        dialog = Gtk.Dialog(title=_("Locate missing file..."),
            transient_for=self,
            modal=True)

        dialog.add_buttons(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
            Gtk.STOCK_OPEN, Gtk.ResponseType.OK)
        dialog.set_border_width(SPACING * 2)
        dialog.get_content_area().set_spacing(SPACING)
        dialog.set_transient_for(self)

        # This box will contain the label and optionally a thumbnail
        hbox = Gtk.HBox()
        hbox.set_spacing(SPACING)

        # Check if we have a thumbnail available.
        # This can happen if the file was moved or deleted by an application
        # that does not manage Freedesktop thumbnails. The user is in luck!
        # This is based on medialibrary's addDiscovererInfo method.
        thumbnail_hash = md5(uri).hexdigest()
        thumb_dir = os.path.expanduser("~/.thumbnails/normal/")
        thumb_path_normal = thumb_dir + thumbnail_hash + ".png"
        if os.path.exists(thumb_path_normal):
            self.debug("A thumbnail file was found for %s", uri)
            thumbnail = Gtk.Image.new_from_file(thumb_path_normal)
            thumbnail.set_padding(0, SPACING)
            hbox.pack_start(thumbnail, False, False, 0)

        # TODO: display the filesize to help the user identify the file
        if asset.get_duration() == Gst.CLOCK_TIME_NONE:
            ## The file is probably an image, not video or audio.
            text = _('The following file has moved: "<b>%s</b>"'
                     '\nPlease specify its new location:'
                     % info_name(asset))
        else:
            length = beautify_length(asset.get_duration())
            text = _('The following file has moved: "<b>%s</b>" (duration: %s)'
                     '\nPlease specify its new location:'
                     % (info_name(asset), length))

        label = Gtk.Label()
        label.set_markup(text)
        hbox.pack_start(label, False, False, 0)
        dialog.get_content_area().pack_start(hbox, False, False, 0)
        hbox.show_all()

        chooser = Gtk.FileChooserWidget(action=Gtk.FileChooserAction.OPEN)
        chooser.set_select_multiple(False)
        previewer = PreviewWidget(self.settings)
        chooser.set_preview_widget(previewer)
        chooser.set_use_preview_label(False)
        chooser.connect('update-preview', previewer.add_preview_request)
        chooser.set_current_folder(self.settings.lastProjectFolder)
        # Use a Gtk FileFilter to only show files with the same extension
        # Note that splitext gives us the extension with the ".", no need to
        # add it inside the filter string.
        unused_filename, extension = os.path.splitext(uri)
        filter_ = Gtk.FileFilter()
        # Translators: this is a format filter in a filechooser. Ex: "AVI files"
        filter_.set_name(_("%s files" % extension))
        filter_.add_pattern("*" + extension.lower())
        filter_.add_pattern("*" + extension.upper())
        default = Gtk.FileFilter()
        default.set_name(_("All files"))
        default.add_pattern("*")
        chooser.add_filter(filter_)
        chooser.add_filter(default)
        dialog.get_content_area().pack_start(chooser, True, True, 0)
        chooser.show()

        # If the window is too big, the window manager will resize it so that
        # it fits on the screen.
        dialog.set_default_size(1024, 1000)
        response = dialog.run()

        if response == Gtk.ResponseType.OK:
            self.log("User chose a new URI for the missing file")
            new_uri = chooser.get_uri()
            self.app.project_manager.current_project.setModificationState(False)
        else:
            # Even if the user clicks Cancel, the discoverer keeps trying to
            # import the rest of the clips...
            # However, since we don't yet have proxy editing, we need to break
            # this async operation, or the filechooser will keep showing up
            # and all sorts of weird things will happen.
            # TODO: bugs #661059, 609136
            attempted_uri = self.app.project_manager.current_project.uri
            reason = _('No replacement file was provided for "<i>%s</i>".\n\n'
                    'Pitivi does not currently support partial projects.'
                    % info_name(asset))
            # Put an end to the async signals spamming us with dialogs:
            self.app.project_manager.disconnect_by_func(self._projectManagerMissingUriCb)
            # Don't overlap the file chooser with our error dialog
            # The chooser will be destroyed further below, so let's hide it now.
            dialog.hide()
            # Reset projectManager and disconnect all the signals:
            self.app.project_manager.newBlankProject(ignore_unsaved_changes=True)
            # Force the project load to fail:
            # This will show an error using _projectManagerNewProjectFailedCb
            # You have to do this *after* successfully creating a blank project,
            # or the startupwizard will still be connected to that signal too.
            self.app.project_manager.emit("new-project-failed", attempted_uri, reason)

        dialog.destroy()
        return new_uri

    def _connectToProject(self, project):
        #FIXME GES we should re-enable this when possible
        #medialibrary.connect("missing-plugins", self._sourceListMissingPluginsCb)
        project.connect("asset-removed", self._mediaLibrarySourceRemovedCb)
        project.connect("project-changed", self._projectChangedCb)

## Pitivi current project callbacks

    def _setProject(self):
        """
        Disconnect and reconnect callbacks to the new current project
        """
        if not self.app.project_manager.current_project:
            self.warning("Current project instance does not exist")
            return False
        try:
            self.app.project_manager.current_project.disconnect_by_func(self._renderingSettingsChangedCb)
        except TypeError:
            # When loading the first project, the signal has never been
            # connected before.
            pass
        self.app.project_manager.current_project.connect("rendering-settings-changed", self._renderingSettingsChangedCb)

        self.viewer.setPipeline(self.app.project_manager.current_project.pipeline)
        self._renderingSettingsChangedCb(self.app.project_manager.current_project)
        if self.timeline_ui:
            self.clipconfig.project = self.app.project_manager.current_project
            #FIXME GES port undo/redo
            #self.app.timelineLogObserver.pipeline = self.app.project_manager.current_project.pipeline

        # When creating a blank project, medialibrary will eventually trigger
        # this _setProject method, but there's no project URI yet.
        if self.app.project_manager.current_project.uri:
            folder_path = os.path.dirname(path_from_uri(self.app.project_manager.current_project.uri))
            self.settings.lastProjectFolder = folder_path

    def _renderingSettingsChangedCb(self, project, unused_item=None, unused_value=None):
        """
        When the project setting change, we reset the viewer aspect ratio
        """
        self.viewer.setDisplayAspectRatio(project.getDAR())
        self.viewer.timecode_entry.setFramerate(project.videorate)

    def _sourceListMissingPluginsCb(self, unused_project, unused_uri, unused_factory,
            details, unused_descriptions, missingPluginsCallback):
        res = self._installPlugins(details, missingPluginsCallback)
        return res

    def _timelineDurationChangedCb(self, timeline, unused_duration):
        """
        When a clip is inserted into a blank timeline, enable the render button.
        This callback is not triggered by loading a project.
        """
        duration = timeline.get_duration()
        self.debug("Timeline duration changed to %s", duration)
        self.render_button.set_sensitive(duration > 0)

## other
    def _showExportDialog(self, project):
        self.log("Export requested")
        chooser = Gtk.FileChooserDialog(title=_("Export To..."),
            transient_for=self,
            action=Gtk.FileChooserAction.SAVE)
        chooser.add_buttons(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
            Gtk.STOCK_SAVE, Gtk.ResponseType.OK)

        chooser.set_select_multiple(False)
        chooser.props.do_overwrite_confirmation = True

        asset = GES.Formatter.get_default()
        asset_extension = asset.get_meta(GES.META_FORMATTER_EXTENSION)

        if not project.name:
            chooser.set_current_name(_("Untitled") + "." + asset_extension + "_tar")
        else:
            chooser.set_current_name(project.name + "." + asset_extension + "_tar")

        filt = Gtk.FileFilter()
        filt.set_name(_("Tar archive"))
        filt.add_pattern("*.%s_tar" % asset_extension)
        chooser.add_filter(filt)
        default = Gtk.FileFilter()
        default.set_name(_("Detect automatically"))
        default.add_pattern("*")
        chooser.add_filter(default)

        response = chooser.run()
        if response == Gtk.ResponseType.OK:
            self.log("User chose a URI to export project to")
            # need to do this to work around bug in Gst.uri_construct
            # which escapes all /'s in path!
            uri = "file://" + chooser.get_filename()
            self.log("uri: %s", uri)
            ret = uri
        else:
            self.log("User didn't choose a URI to export project to")
            ret = None

        chooser.destroy()
        return ret

    def _showSaveAsDialog(self, unused_project):
        self.log("Save URI requested")

        chooser = Gtk.FileChooserDialog(title=_("Save As..."),
            transient_for=self,
            action=Gtk.FileChooserAction.SAVE)
        chooser.add_buttons(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
            Gtk.STOCK_SAVE, Gtk.ResponseType.OK)

        asset = GES.Formatter.get_default()
        filt = Gtk.FileFilter()
        filt.set_name(asset.get_meta(GES.META_DESCRIPTION))
        filt.add_pattern("*.%s" % asset.get_meta(GES.META_FORMATTER_EXTENSION))
        chooser.add_filter(filt)

        chooser.set_select_multiple(False)
        chooser.set_current_name(_("Untitled") + "." +
                asset.get_meta(GES.META_FORMATTER_EXTENSION))
        chooser.set_current_folder(self.settings.lastProjectFolder)
        chooser.props.do_overwrite_confirmation = True

        default = Gtk.FileFilter()
        default.set_name(_("Detect automatically"))
        default.add_pattern("*")
        chooser.add_filter(default)

        response = chooser.run()
        if response == Gtk.ResponseType.OK:
            self.log("User chose a URI to save project to")
            # need to do this to work around bug in Gst.uri_construct
            # which escapes all /'s in path!
            uri = "file://" + chooser.get_filename()
            file_filter = chooser.get_filter().get_name()
            self.log("uri:%s , filter:%s", uri, file_filter)
            self.settings.lastProjectFolder = chooser.get_current_folder()
            ret = uri
        else:
            self.log("User didn't choose a URI to save project to")
            ret = None

        chooser.destroy()
        return ret

    def _screenshotCb(self, unused_action):
        """
        Export a snapshot of the current frame as an image file.
        """
        foo = self._showSaveScreenshotDialog()
        if foo:
            path, mime = foo[0], foo[1]
            self.app.project_manager.current_project.pipeline.save_thumbnail(-1, -1, mime, path)

    def _showSaveScreenshotDialog(self):
        """
        Show a filechooser dialog asking the user where to save the snapshot
        of the current frame and what file type to use.

        Returns a list containing the full path and the mimetype if successful,
        returns none otherwise.
        """
        chooser = Gtk.FileChooserDialog(title=_("Save As..."),
            transient_for=self, action=Gtk.FileChooserAction.SAVE)
        chooser.add_buttons(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
            Gtk.STOCK_SAVE, Gtk.ResponseType.OK)
        chooser.set_icon_name("pitivi")
        chooser.set_select_multiple(False)
        chooser.set_current_name(_("Untitled"))
        chooser.props.do_overwrite_confirmation = True
        formats = {_("PNG image"): ["image/png", ("png",)],
                _("JPEG image"): ["image/jpeg", ("jpg", "jpeg")]}
        for format in formats:
            filt = Gtk.FileFilter()
            filt.set_name(format)
            filt.add_mime_type(formats.get(format)[0])
            chooser.add_filter(filt)
        response = chooser.run()
        if response == Gtk.ResponseType.OK:
            chosen_format = formats.get(chooser.get_filter().get_name())
            chosen_ext = chosen_format[1][0]
            chosen_mime = chosen_format[0]
            uri = os.path.join(chooser.get_current_folder(), chooser.get_filename())
            ret = [uri + "." + chosen_ext, chosen_mime]
        else:
            ret = None
        chooser.destroy()
        return ret

    def updateTitle(self):
        name = touched = ""
        if self.app.project_manager.current_project:
            if self.app.project_manager.current_project.name:
                name = self.app.project_manager.current_project.name
            else:
                name = _("Untitled")
            if self.app.project_manager.current_project.hasUnsavedModifications():
                touched = "*"
        title = "%s%s — %s" % (touched, name, APPNAME)
        self._headerbar.set_title(title)
        self.set_title(title)


class PreviewAssetWindow(Gtk.Window):
    """
    Window for previewing a video or audio asset.

    @ivar asset: The asset to be previewed.
    @type asset: L{GES.UriClipAsset}
    @type main_window: L{PitiviMainWindow}
    """

    def __init__(self, asset, main_window):
        Gtk.Window.__init__(self)
        self._asset = asset
        self._main_window = main_window

        self.set_title(_("Preview"))
        self.set_type_hint(Gdk.WindowTypeHint.UTILITY)
        self.set_transient_for(main_window)

        self._previewer = PreviewWidget(main_window.settings, minimal=True)
        self.add(self._previewer)
        self._previewer.previewUri(self._asset.get_id())
        self._previewer.show()

        self.connect("focus-out-event", self._leavePreviewCb)
        self.connect("key-press-event", self._keyPressCb)

    def preview(self):
        """
        Show the window and start the playback.
        """
        width, height = self._calculatePreviewWindowSize()
        self.resize(width, height)
        # Setting the position of the window only works if it's currently hidden
        # otherwise, after the resize the position will not be readjusted
        self.set_position(Gtk.WindowPosition.CENTER_ON_PARENT)
        self.show()

        self._previewer.play()
        # Hack so that we really really force the "utility" window to be focused
        self.present()

    def _calculatePreviewWindowSize(self):
        info = self._asset.get_info()
        video_streams = info.get_video_streams()
        if not video_streams:
            # There is no video/image stream. This is an audio file.
            # Resize to the minimum and let the window manager deal with it.
            return 1, 1
        # For videos and images, automatically resize the window
        # Try to keep it 1:1 if it can fit within 85% of the parent window
        video = video_streams[0]
        img_width = video.get_width()
        img_height = video.get_height()
        mainwindow_width, mainwindow_height = self._main_window.get_size()
        max_width = 0.85 * mainwindow_width
        max_height = 0.85 * mainwindow_height

        controls_height = self._previewer.bbox.size_request().height
        if img_width < max_width and (img_height + controls_height) < max_height:
            # The video is small enough, keep it 1:1
            return img_width, img_height + controls_height
        else:
            # The video is too big, size it down
            # TODO: be smarter, figure out which (width, height) is bigger
            new_height = max_width * img_height / img_width
            return int(max_width), int(new_height + controls_height)

    def _leavePreviewCb(self, window, unused):
        self.destroy()
        return True

    def _keyPressCb(self, unused_widget, event):
        if event.keyval in (Gdk.KEY_Escape, Gdk.KEY_Q, Gdk.KEY_q):
            self.destroy()
        elif event.keyval == Gdk.KEY_space:
            self._previewer.togglePlayback()
        return True
