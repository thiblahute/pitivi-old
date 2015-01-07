# Pitivi video editor
#
#       pitivi/application.py
#
# Copyright (c) 2005-2009 Edward Hervey <bilboed@bilboed.com>
# Copyright (c) 2008-2009 Alessandro Decina <alessandro.d@gmail.com>
# Copyright (c) 2014 <alexandru.balut@gmail.com>
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
import time

from datetime import datetime

from gi.repository import GObject
from gi.repository import Gio
from gi.repository import Gtk
from gi.repository import Gst

from pitivi.effects import EffectsManager
from pitivi.configure import VERSION, RELEASES_URL
from pitivi.settings import GlobalSettings, xdg_cache_home, get_dir
from pitivi.utils.threads import ThreadMaster
from pitivi.mainwindow import PitiviMainWindow
from pitivi.project import ProjectManager, ProjectLogObserver
from pitivi.undo.undo import UndoableActionLog
from pitivi.undo.timeline import TimelineLogObserver
from pitivi.dialogs.startupwizard import StartUpWizard

from pitivi.utils.misc import quote_uri, path_from_uri
from pitivi.utils.system import getSystem
from pitivi.utils.loggable import Loggable
import pitivi.utils.loggable as log


class Pitivi(Gtk.Application, Loggable):

    """
    Pitivi's application.

    @type effects: L{EffectsManager}
    @ivar gui: The main window of the app.
    @type gui: L{PitiviMainWindow}
    @ivar project_manager: The project manager object used in the application
    @type project_manager: L{ProjectManager}
    @ivar settings: Application-wide settings.
    @type settings: L{GlobalSettings}.
    """

    __gsignals__ = {
        "version-info-received": (GObject.SIGNAL_RUN_LAST, None, (object,))
    }

    def __init__(self):
        Gtk.Application.__init__(self,
                                 application_id="org.pitivi",
                                 flags=Gio.ApplicationFlags.HANDLES_OPEN)
        Loggable.__init__(self)

        self.settings = None
        self.threads = None
        self.effects = None
        self.system = None
        self.project_manager = ProjectManager(self)

        self.action_log = UndoableActionLog(self)
        self.timeline_log_observer = None
        self.project_log_observer = None
        self._last_action_time = Gst.util_get_timestamp()

        self.gui = None
        self.welcome_wizard = None

        self._version_information = {}

        self._scenario_file = None
        self._first_action = True

        self.connect("startup", self._startupCb)
        self.connect("activate", self._activateCb)
        self.connect("open", self.openCb)

    def write_action(self, action, properties={}):
        if self._first_action:
            self._scenario_file.write(
                "description, seek=true, handles-states=true\n")
            self._first_action = False

        now = Gst.util_get_timestamp()
        if now - self._last_action_time > 0.05 * Gst.SECOND:
            # We need to make sure that the waiting time was more than 50 ms.
            st = Gst.Structure.new_empty("wait")
            st["duration"] = float((now - self._last_action_time) / Gst.SECOND)
            self._scenario_file.write(st.to_string() + "\n")
            self._last_action_time = now

        if not isinstance(action, Gst.Structure):
            structure = Gst.Structure.new_empty(action)

            for key, value in properties.items():
                structure[key] = value

            action = structure

        self._scenario_file.write(action.to_string() + "\n")
        self._scenario_file.flush()

    def _startupCb(self, unused_app):
        # Init logging as early as possible so we can log startup code
        enable_color = not os.environ.get(
            'PITIVI_DEBUG_NO_COLOR', '0') in ('', '1')
        # Let's show a human-readable Pitivi debug output by default, and only
        # show a crazy unreadable mess when surrounded by gst debug statements.
        enable_crack_output = "GST_DEBUG" in os.environ
        log.init('PITIVI_DEBUG', enable_color, enable_crack_output)

        self.info('starting up')
        self.settings = GlobalSettings()
        self.threads = ThreadMaster()
        self.effects = EffectsManager()
        self.system = getSystem()

        self.action_log.connect("commit", self._actionLogCommit)
        self.action_log.connect("undo", self._actionLogUndo)
        self.action_log.connect("redo", self._actionLogRedo)
        self.action_log.connect("cleaned", self._actionLogCleaned)
        self.timeline_log_observer = TimelineLogObserver(self.action_log)
        self.project_log_observer = ProjectLogObserver(self.action_log)

        self.project_manager.connect(
            "new-project-loading", self._newProjectLoadingCb)
        self.project_manager.connect(
            "new-project-loaded", self._newProjectLoaded)
        self.project_manager.connect("project-closed", self._projectClosed)

        self._createActions()
        self._checkVersion()

    def _createActions(self):
        self.undo_action = Gio.SimpleAction.new("undo", None)
        self.undo_action.connect("activate", self._undoCb)
        self.add_action(self.undo_action)
        self.add_accelerator("<Control>z", "app.undo", None)

        self.redo_action = Gio.SimpleAction.new("redo", None)
        self.redo_action.connect("activate", self._redoCb)
        self.add_action(self.redo_action)
        self.add_accelerator("<Control><Shift>z", "app.redo", None)

        self.quit_action = Gio.SimpleAction.new("quit", None)
        self.quit_action.connect("activate", self._quitCb)
        self.add_action(self.quit_action)
        self.add_accelerator("<Control>q", "app.quit", None)

    def _activateCb(self, unused_app):
        if self.gui:
            # The app is already started and the window already created.
            # Present the already existing window.
            try:
                # TODO: Use present() instead of present_with_time() when
                # https://bugzilla.gnome.org/show_bug.cgi?id=688830 is fixed.
                from gi.repository import GdkX11
                x11_server_time = GdkX11.x11_get_server_time(self.gui.get_window())
                self.gui.present_with_time(x11_server_time)
            except ImportError:
                # On Wayland or Quartz (Mac OS X) backend there is no GdkX11,
                # so just use present() directly here.
                self.gui.present()
            # No need to show the welcome wizard.
            return
        self.createMainWindow()
        self.welcome_wizard = StartUpWizard(self)
        self.welcome_wizard.show()

    def createMainWindow(self):
        if self.gui:
            return
        self.gui = PitiviMainWindow(self)
        self.add_window(self.gui)
        # We might as well show it.
        self.gui.show()

    def openCb(self, unused_app, giofiles, unused_count, unused_hint):
        assert giofiles
        self.createMainWindow()
        if len(giofiles) > 1:
            self.warning(
                "Can open only one project file at a time. Ignoring the rest!")
        project_file = giofiles[0]
        self.project_manager.loadProject(quote_uri(project_file.get_uri()))
        return True

    def shutdown(self):
        """
        Close Pitivi.

        @return: C{True} if Pitivi was successfully closed, else C{False}.
        @rtype: C{bool}
        """
        self.debug("shutting down")
        # Refuse to close if we are not done with the current project.
        if not self.project_manager.closeRunningProject():
            self.warning(
                "Not closing since running project doesn't want to close")
            return False
        if self.welcome_wizard:
            self.welcome_wizard.hide()
        if self.gui:
            self.gui.destroy()
        self.threads.stopAllThreads()
        self.settings.storeSettings()
        self.quit()
        return True

        self._first_action = True

    def _setScenarioFile(self, uri):
        if 'PITIVI_SCENARIO_FILE' in os.environ:
            uri = quote_uri(os.environ['PITIVI_SCENARIO_FILE'])
        else:
            cache_dir = get_dir(os.path.join(xdg_cache_home(), "scenarios"))
            scenario_name = str(time.strftime("%Y%m%d-%H%M%S"))
            project_path = None
            if uri:
                project_path = path_from_uri(uri)
                scenario_name += os.path.splitext(project_path.replace(os.sep, "_"))[0]

            uri = os.path.join(cache_dir, scenario_name + ".scenario")
            uri = quote_uri(uri)

        self._scenario_file = open(path_from_uri(uri), "w")

        if project_path:
            f = open(project_path)
            content = f.read()
            if not project_path.endswith(".scenario"):
                self.write_action("load-project",
                                  {"serialized-content":
                                   "%s" % content.replace("\n", "")})
            f.close()

    def _newProjectLoadingCb(self, unused_project_manager, uri):
        self._setScenarioFile(uri)

    def _newProjectLoaded(self, unused_project_manager, project, unused_fully_loaded):
        self.action_log.clean()

        self.timeline_log_observer.startObserving(project.timeline)
        self.project_log_observer.startObserving(project)

    def _projectClosed(self, unused_project_manager, project):
        self.project_log_observer.stopObserving(project)
        self.timeline_log_observer.stopObserving(project.timeline)

        if self._scenario_file:
            self.write_action("stop")
            self._scenario_file.close()
            self._scenario_file = None

    def _checkVersion(self):
        """
        Check online for release versions information.
        """
        self.info("Requesting version information async")
        giofile = Gio.File.new_for_uri(RELEASES_URL)
        giofile.load_contents_async(None, self._versionInfoReceivedCb, None)

    def _versionInfoReceivedCb(self, giofile, result, user_data):
        try:
            raw = giofile.load_contents_finish(result)[1]
            if not isinstance(raw, str):
                raw = raw.decode()
            raw = raw.split("\n")
            # Split line at '=' if the line is not empty or a comment line
            data = [element.split("=") for element in raw
                    if element and not element.startswith("#")]

            # search newest version and status
            status = "UNSUPPORTED"
            current_version = None
            for version, version_status in data:
                if VERSION == version:
                    status = version_status
                if version_status.upper() == "CURRENT":
                    # This is the latest.
                    current_version = version
                    self.info("Latest software version is %s", current_version)

            VERSION_split = [int(i) for i in VERSION.split(".")]
            current_version_split = [int(i)
                                     for i in current_version.split(".")]
            if VERSION_split > current_version_split:
                status = "CURRENT"
                self.info(
                    "Running version %s, which is newer than the latest known version. Considering it as the latest current version.", VERSION)
            elif status is "UNSUPPORTED":
                self.warning(
                    "Using an outdated version of Pitivi (%s)", VERSION)

            self._version_information["current"] = current_version
            self._version_information["status"] = status
            self.emit("version-info-received", self._version_information)
        except Exception as e:
            self.warning("Version info could not be read: %s", e)

    def isLatest(self):
        """
        Whether the app's version is the latest as far as we know.
        """
        status = self._version_information.get("status")
        return status is None or status.upper() == "CURRENT"

    def getLatest(self):
        """
        Get the latest version of the app or None.
        """
        return self._version_information.get("current")

    def _quitCb(self, unused_action, unused_param):
        self.shutdown()

    def _undoCb(self, unused_action, unused_param):
        self.action_log.undo()

    def _redoCb(self, unused_action, unused_param):
        self.action_log.redo()

    def _actionLogCommit(self, action_log, unused_stack, nested):
        if nested:
            return
        self._syncDoUndo(action_log)

    def _actionLogUndo(self, action_log, unused_stack):
        self._syncDoUndo(action_log)

    def _actionLogRedo(self, action_log, unused_stack):
        self._syncDoUndo(action_log)

    def _actionLogCleaned(self, action_log):
        self._syncDoUndo(action_log)

    def _syncDoUndo(self, action_log):
        can_undo = bool(action_log.undo_stacks)
        self.undo_action.set_enabled(can_undo)

        can_redo = bool(action_log.redo_stacks)
        self.redo_action.set_enabled(can_redo)

        dirty = action_log.dirty()
        self.project_manager.current_project.setModificationState(dirty)
        # In the tests we do not want to create any gui
        if self.gui is not None:
            self.gui.showProjectStatus()
