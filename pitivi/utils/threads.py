# Pitivi video editor
#
#       threads.py
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

import threading

from gi.repository import GObject

from pitivi.utils.loggable import Loggable

#
# Following code was freely adapted by code from:
#   John Stowers <john.stowers@gmail.com>
#


class Thread(threading.Thread, GObject.Object, Loggable):

    """
    Event-powered thread
    """

    __gsignals__ = {
        "done": (GObject.SIGNAL_RUN_LAST, None, ()),
    }

    def __init__(self):
        GObject.Object.__init__(self)
        threading.Thread.__init__(self)
        Loggable.__init__(self)

    def stop(self):
        """ stop the thread, do not override """
        self.abort()
        self.emit("done")

    def run(self):
        """ thread processing """
        self.process()
        self.emit("done")

    def process(self):
        """ Implement this in subclasses """
        raise NotImplementedError

    def abort(self):
        """ Abort the thread. Subclass have to implement this method ! """
        pass


class ThreadMaster(Loggable):

    """
    Controls all the threads existing in Pitivi.
    """

    def __init__(self):
        Loggable.__init__(self)
        self.threads = []

    def addThread(self, threadclass, *args):
        """ Instantiate the specified Thread class and start it. """
        assert issubclass(threadclass, Thread)
        self.log("Adding thread of type %r", threadclass)
        thread = threadclass(*args)
        thread.connect("done", self._threadDoneCb)
        self.threads.append(thread)
        self.log("starting it...")
        thread.start()
        self.log("started !")

    def _threadDoneCb(self, thread):
        self.log("thread %r is done", thread)
        self.threads.remove(thread)

    def stopAllThreads(self):
        """ Stop all running Thread(s) controlled by this master """
        self.log("stopping all threads")
        joinedthreads = 0
        while joinedthreads < len(self.threads):
            for thread in self.threads:
                self.log("Trying to stop thread %r", thread)
                try:
                    thread.join()
                    joinedthreads += 1
                except:
                    self.warning("what happened ??")
