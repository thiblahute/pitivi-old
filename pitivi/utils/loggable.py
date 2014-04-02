# Pitivi video editor
#
#       pitivi/utils/loggable.py
#
# Copyright (c) 2009, Alessandro Decina <alessandro.decina@collabora.co.uk>
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

import errno
import sys
import re
import os
import fnmatch
import time
import types
import traceback
import _thread
import collections


# environment variables controlling levels for each category
_DEBUG = "*:1"
# name of the environment variable controlling our logging
_ENV_VAR_NAME = None
# package names we should scrub filenames for
_PACKAGE_SCRUB_LIST = []

# dynamic dictionary of categories already seen and their level
_categories = {}

# log handlers registered
_log_handlers = []
_log_handlers_limited = []

_initialized = False

_stdout = None
_stderr = None
_old_hup_handler = None


# public log levels
(ERROR,
 WARN,
 FIXME,
 INFO,
 DEBUG,
 LOG) = list(range(1, 7))

COLORS = {ERROR: 'RED',
          WARN: 'YELLOW',
          FIXME: 'MAGENTA',
          INFO: 'GREEN',
          DEBUG: 'BLUE',
          LOG: 'CYAN'}

_FORMATTED_LEVELS = []
_LEVEL_NAMES = ['ERROR', 'WARN', 'FIXME', 'INFO', 'DEBUG', 'LOG']


class TerminalController:
    """
    A class that can be used to portably generate formatted output to
    a terminal.

    `TerminalController` defines a set of instance variables whose
    values are initialized to the control sequence necessary to
    perform a given action.  These can be simply included in normal
    output to the terminal:

        >>> term = TerminalController()
        >>> print 'This is '+term.GREEN+'green'+term.NORMAL

    Alternatively, the `render()` method can used, which replaces
    '${action}' with the string required to perform 'action':

        >>> term = TerminalController()
        >>> print term.render('This is ${GREEN}green${NORMAL}')

    If the terminal doesn't support a given action, then the value of
    the corresponding instance variable will be set to ''.  As a
    result, the above code will still work on terminals that do not
    support color, except that their output will not be colored.
    Also, this means that you can test whether the terminal supports a
    given action by simply testing the truth value of the
    corresponding instance variable:

        >>> term = TerminalController()
        >>> if term.CLEAR_SCREEN:
        ...     print 'This terminal supports clearning the screen.'

    Finally, if the width and height of the terminal are known, then
    they will be stored in the `COLS` and `LINES` attributes.
    """
    # Cursor movement:
    BOL = ''             # : Move the cursor to the beginning of the line
    UP = ''              # : Move the cursor up one line
    DOWN = ''            # : Move the cursor down one line
    LEFT = ''            # : Move the cursor left one char
    RIGHT = ''           # : Move the cursor right one char

    # Deletion:
    CLEAR_SCREEN = ''    # : Clear the screen and move to home position
    CLEAR_EOL = ''       # : Clear to the end of the line.
    CLEAR_BOL = ''       # : Clear to the beginning of the line.
    CLEAR_EOS = ''       # : Clear to the end of the screen

    # Output modes:
    BOLD = ''            # : Turn on bold mode
    BLINK = ''           # : Turn on blink mode
    DIM = ''             # : Turn on half-bright mode
    REVERSE = ''         # : Turn on reverse-video mode
    NORMAL = ''          # : Turn off all modes

    # Cursor display:
    HIDE_CURSOR = ''     # : Make the cursor invisible
    SHOW_CURSOR = ''     # : Make the cursor visible

    # Terminal size:
    COLS = None          # : Width of the terminal (None for unknown)
    LINES = None         # : Height of the terminal (None for unknown)

    # Foreground colors:
    BLACK = BLUE = GREEN = CYAN = RED = MAGENTA = YELLOW = WHITE = ''

    # Background colors:
    BG_BLACK = BG_BLUE = BG_GREEN = BG_CYAN = ''
    BG_RED = BG_MAGENTA = BG_YELLOW = BG_WHITE = ''

    _STRING_CAPABILITIES = """
    BOL=cr UP=cuu1 DOWN=cud1 LEFT=cub1 RIGHT=cuf1
    CLEAR_SCREEN=clear CLEAR_EOL=el CLEAR_BOL=el1 CLEAR_EOS=ed BOLD=bold
    BLINK=blink DIM=dim REVERSE=rev UNDERLINE=smul NORMAL=sgr0
    HIDE_CURSOR=cinvis SHOW_CURSOR=cnorm""".split()
    _COLORS = """BLACK BLUE GREEN CYAN RED MAGENTA YELLOW WHITE""".split()
    _ANSICOLORS = "BLACK RED GREEN YELLOW BLUE MAGENTA CYAN WHITE".split()

    def __init__(self, term_stream=sys.stdout):
        """
        Create a `TerminalController` and initialize its attributes
        with appropriate values for the current terminal.
        `term_stream` is the stream that will be used for terminal
        output; if this stream is not a tty, then the terminal is
        assumed to be a dumb terminal (i.e., have no capabilities).
        """
        # Curses isn't available on all platforms
        try:
            import curses
        except ImportError:
            return

        # If the stream isn't a tty, then assume it has no capabilities.
        if not term_stream.isatty():
            return

        # Check the terminal type.  If we fail, then assume that the
        # terminal has no capabilities.
        try:
            curses.setupterm()
        except:
            return

        # Look up numeric capabilities.
        self.COLS = curses.tigetnum('cols')
        self.LINES = curses.tigetnum('lines')

        # Look up string capabilities.
        for capability in self._STRING_CAPABILITIES:
            (attrib, cap_name) = capability.split('=')
            setattr(self, attrib, self._tigetstr(cap_name) or b'')

        # Colors
        set_fg = self._tigetstr('setf')
        if set_fg:
            for i, color in zip(list(range(len(self._COLORS))), self._COLORS):
                setattr(self, color, curses.tparm(set_fg, i) or b'')
        set_fg_ansi = self._tigetstr('setaf')
        if set_fg_ansi:
            for i, color in zip(list(range(len(self._ANSICOLORS))),
                                self._ANSICOLORS):
                setattr(self, color, curses.tparm(set_fg_ansi, i) or b'')
        set_bg = self._tigetstr('setb')
        if set_bg:
            for i, color in zip(list(range(len(self._COLORS))), self._COLORS):
                setattr(self, 'BG_' + color, curses.tparm(set_bg, i) or b'')
        set_bg_ansi = self._tigetstr('setab')
        if set_bg_ansi:
            for i, color in zip(list(range(len(self._ANSICOLORS))),
                                self._ANSICOLORS):
                setattr(self, 'BG_' + color, curses.tparm(set_bg_ansi, i) or b'')

    def _tigetstr(self, cap_name):
        # String capabilities can include "delays" of the form "$<2>".
        # For any modern terminal, we should be able to just ignore
        # these, so strip them out.
        import curses
        cap = curses.tigetstr(cap_name) or b''
        return re.sub(r'\$<\d+>[/*]?', '', cap.decode()).encode()

    def render(self, template):
        """
        Replace each $-substitutions in the given template string with
        the corresponding terminal control string (if it's defined) or
        '' (if it's not).
        """
        return re.sub(r'\$\$|\${\w+}', self._render_sub, template)

    def _render_sub(self, match):
        s = match.group()
        if s == '$$':
            return s
        else:
            return getattr(self, s[2:-1])

#######################################################################
# Example use case: progress bar
#######################################################################


class ProgressBar:
    """
    A 3-line progress bar, which looks like::

                                Header
        20% [===========----------------------------------]
                           progress message

    The progress bar is colored, if the terminal supports color
    output; and adjusts to the width of the terminal.
    """
    BAR = '%3d%% ${GREEN}[${BOLD}%s%s${NORMAL}${GREEN}]${NORMAL}\n'
    HEADER = '${BOLD}${CYAN}%s${NORMAL}\n\n'

    def __init__(self, term, header):
        self.term = term
        if not (self.term.CLEAR_EOL and self.term.UP and self.term.BOL):
            raise ValueError("Terminal isn't capable enough -- you "
                             "should use a simpler progress dispaly.")
        self.width = self.term.COLS or 75
        self.bar = term.render(self.BAR)
        self.header = self.term.render(self.HEADER % header.center(self.width))
        self.cleared = 1  # : true if we haven't drawn the bar yet.
        self.update(0, '')

    def update(self, percent, message):
        if self.cleared:
            sys.stdout.write(self.header)
            self.cleared = 0
        n = int((self.width - 10) * percent)
        sys.stdout.write(
            self.term.BOL + self.term.UP + self.term.CLEAR_EOL +
            (self.bar % (100 * percent, '=' * n, '-' * (self.width - 10 - n))) +
            self.term.CLEAR_EOL + message.center(self.width))

    def clear(self):
        if not self.cleared:
            sys.stdout.write(self.term.BOL + self.term.CLEAR_EOL +
                             self.term.UP + self.term.CLEAR_EOL +
                             self.term.UP + self.term.CLEAR_EOL)
            self.cleared = 1


def getLevelName(level):
    """
    Return the name of a log level.
    @param level: The level we want to know the name
    @type level: int
    @return: The name of the level
    @rtype: str
    """
    assert isinstance(level, int) and level > 0 and level < 7, \
        TypeError("Bad debug level")
    return getLevelNames()[level - 1]


def getLevelNames():
    """
    Return a list with the level names
    @return: A list with the level names
    @rtype: list of str
    """
    return _LEVEL_NAMES


def getLevelInt(levelName):
    """
    Return the integer value of the levelName.
    @param levelName: The string value of the level name
    @type levelName: str
    @return: The value of the level name we are interested in.
    @rtype: int
    """
    assert isinstance(levelName, str) and levelName in getLevelNames(), \
        "Bad debug level name"
    return getLevelNames().index(levelName) + 1


def getFormattedLevelName(level):
    assert isinstance(level, int) and level > 0 and level < len(_LEVEL_NAMES) + 1, \
        TypeError("Bad debug level")
    return _FORMATTED_LEVELS[level - 1]


def registerCategory(category):
    """
    Register a given category in the debug system.
    A level will be assigned to it based on previous calls to setDebug.
    """
    # parse what level it is set to based on _DEBUG
    # example: *:2,admin:4
    global _DEBUG
    global _levels
    global _categories

    level = 0
    chunks = _DEBUG.split(',')
    for chunk in chunks:
        if not chunk:
            continue
        if ':' in chunk:
            spec, value = chunk.split(':')
        else:
            spec = '*'
            value = chunk

        # our glob is unix filename style globbing, so cheat with fnmatch
        # fnmatch.fnmatch didn't work for this, so don't use it
        if category in fnmatch.filter((category, ), spec):
            # we have a match, so set level based on string or int
            if not value:
                continue
            try:
                level = int(value)
            except ValueError:  # e.g. *; we default to most
                level = 5
    # store it
    _categories[category] = level


def getCategoryLevel(category):
    """
    @param category: string

    Get the debug level at which this category is being logged, adding it
    if it wasn't registered yet.
    """
    global _categories
    if not category in _categories:
        registerCategory(category)
    return _categories[category]


def setLogSettings(state):
    """Update the current log settings.
    This can restore an old saved log settings object returned by
    getLogSettings
    @param state: the settings to set
    """

    global _DEBUG
    global _log_handlers
    global _log_handlers_limited

    (_DEBUG,
     _categories,
     _log_handlers,
     _log_handlers_limited) = state

    for category in _categories:
        registerCategory(category)


def getLogSettings():
    """Fetches the current log settings.
    The returned object can be sent to setLogSettings to restore the
    returned settings
    @returns: the current settings
    """
    return (_DEBUG,
            _categories,
            _log_handlers,
            _log_handlers_limited)


def _canShortcutLogging(category, level):
    if _log_handlers:
        # we have some loggers operating without filters, have to do
        # everything
        return False
    else:
        return level > getCategoryLevel(category)


def scrubFilename(filename):
    '''
    Scrub the filename to a relative path for all packages in our scrub list.
    '''
    global _PACKAGE_SCRUB_LIST
    for package in _PACKAGE_SCRUB_LIST:
        i = filename.rfind(package)
        if i > -1:
            return filename[i:]

    return filename


def getFileLine(where=-1):
    """
    Return the filename and line number for the given location.

    If where is a negative integer, look for the code entry in the current
    stack that is the given number of frames above this module.
    If where is a function, look for the code entry of the function.

    @param where: how many frames to go back up, or function
    @type  where: int (negative) or function

    @return: tuple of (file, line, function_name)
    @rtype:  tuple of (str, int, str)
    """
    co = None
    lineno = None
    name = None

    if isinstance(where, types.FunctionType):
        co = where.__code__
        lineno = co.co_firstlineno
        name = co.co_name
    elif isinstance(where, types.MethodType):
        co = where.__func__.__code__
        lineno = co.co_firstlineno
        name = co.co_name
    else:
        stackFrame = sys._getframe()
        while stackFrame:
            co = stackFrame.f_code
            if not co.co_filename.endswith('loggable.py'):
                # wind up the stack according to frame
                while where < -1:
                    stackFrame = stackFrame.f_back
                    where += 1
                co = stackFrame.f_code
                lineno = stackFrame.f_lineno
                name = co.co_name
                break
            stackFrame = stackFrame.f_back

    if not co:
        return "<unknown file>", 0, None

    return scrubFilename(co.co_filename), lineno, name


def ellipsize(o):
    """
    Ellipsize the representation of the given object.
    """
    r = repr(o)
    if len(r) < 800:
        return r

    r = r[:60] + ' ... ' + r[-15:]
    return r


def getFormatArgs(startFormat, startArgs, endFormat, endArgs, args, kwargs):
    """
    Helper function to create a format and args to use for logging.
    This avoids needlessly interpolating variables.
    """
    debugArgs = startArgs[:]
    for a in args:
        debugArgs.append(ellipsize(a))

    for items in list(kwargs.items()):
        debugArgs.extend(items)
    debugArgs.extend(endArgs)
    format = startFormat \
        + ', '.join(('%s', ) * len(args)) \
        + (kwargs and ', ' or '') \
        + ', '.join(('%s=%r', ) * len(kwargs)) \
        + endFormat
    return format, debugArgs


def doLog(level, object, category, format, args, where=-1, filePath=None, line=None):
    """
    @param where:     what to log file and line number for;
                      -1 for one frame above log.py; -2 and down for higher up;
                      a function for a (future) code object
    @type  where:     int or callable
    @param filePath:  file to show the message as coming from, if caller
                      knows best
    @type  filePath:  str
    @param line:      line to show the message as coming from, if caller
                      knows best
    @type  line:      int

    @return: dict of calculated variables, if they needed calculating.
             currently contains file and line; this prevents us from
             doing this work in the caller when it isn't needed because
             of the debug level
    """
    ret = {}

    if args:
        message = format % args
    else:
        message = format
    funcname = None

    if level > getCategoryLevel(category):
        handlers = _log_handlers
    else:
        handlers = _log_handlers + _log_handlers_limited

    if handlers:
        if filePath is None and line is None:
            (filePath, line, funcname) = getFileLine(where=where)
        ret['filePath'] = filePath
        ret['line'] = line
        if funcname:
            message = "\033[00m\033[32;01m%s:\033[00m %s" % (funcname, message)
        for handler in handlers:
            try:
                handler(level, object, category, filePath, line, message)
            except TypeError as e:
                raise SystemError("handler %r raised a TypeError: %s" % (
                    handler, getExceptionMessage(e)))

    return ret


def errorObject(object, cat, format, *args):
    """
    Log a fatal error message in the given category.
    This will also raise a L{SystemExit}.
    """
    doLog(ERROR, object, cat, format, args)

    if args:
        raise SystemExit(format % args)
    else:
        raise SystemExit(format)


def warningObject(object, cat, format, *args):
    """
    Log a warning message in the given category.
    This is used for non-fatal problems.
    """
    doLog(WARN, object, cat, format, args)


def fixmeObject(object, cat, format, *args):
    """
    Log a fixme message in the given category.
    This is used for not implemented codepaths or known issues in the code
    """
    doLog(FIXME, object, cat, format, args)


def infoObject(object, cat, format, *args):
    """
    Log an informational message in the given category.
    """
    doLog(INFO, object, cat, format, args)


def debugObject(object, cat, format, *args):
    """
    Log a debug message in the given category.
    """
    doLog(DEBUG, object, cat, format, args)


def logObject(object, cat, format, *args):
    """
    Log a log message.  Used for debugging recurring events.
    """
    doLog(LOG, object, cat, format, args)


def safeprintf(file, format, *args):
    """Write to a file object, ignoring errors.
    """
    try:
        if args:
            file.write(format % args)
        else:
            file.write(format)
    except IOError as e:
        if e.errno == errno.EPIPE:
            # if our output is closed, exit; e.g. when logging over an
            # ssh connection and the ssh connection is closed
            os._exit(os.EX_OSERR)
        # otherwise ignore it, there's nothing you can do


def stderrHandler(level, object, category, file, line, message):
    """
    A log handler that writes to stderr.
    The output will be different depending the value of "_enableCrackOutput";
    in Pitivi's case, that is True when the GST_DEBUG env var is defined.

    @type level:    string
    @type object:   string (or None)
    @type category: string
    @type message:  string
    """

    # Make the file path more compact for readability
    file = os.path.relpath(file)
    where = "(%s:%d)" % (file, line)

    # If GST_DEBUG is not set, we can assume only PITIVI_DEBUG is set, so don't
    # show a bazillion of debug details that are not relevant to Pitivi.
    if not _enableCrackOutput:
        safeprintf(sys.stderr, '%s %-8s %-17s %-2s %s %s\n',
               getFormattedLevelName(level), time.strftime("%H:%M:%S"),
               category, "", message, where)
    else:
        o = ""
        if object:
            o = '"' + object + '"'
        # level   pid     object   cat      time
        # 5 + 1 + 7 + 1 + 32 + 1 + 17 + 1 + 15 == 80
        safeprintf(sys.stderr, '%s [%5d] [0x%12x] %-32s %-17s %-15s %-4s %s %s\n',
                   getFormattedLevelName(level), os.getpid(), _thread.get_ident(),
                   o[:32], category, time.strftime("%b %d %H:%M:%S"), "",
                   message, where)
    sys.stderr.flush()


def logLevelName(level):
    format = '%-5s'
    return format % (_LEVEL_NAMES[level - 1], )


def _preformatLevels(enableColorOutput):

    if enableColorOutput:
        t = TerminalController()

        if type(t.BOLD) == bytes:
            formatter = lambda level: ''.join(
                (t.BOLD.decode(), getattr(t, COLORS[level]).decode(),
                logLevelName(level), t.NORMAL.decode()))
        else:
            formatter = lambda level: ''.join(
                (t.BOLD, getattr(t, COLORS[level]),
                logLevelName(level), t.NORMAL))
    else:
        formatter = lambda level: logLevelName(level)

    for level in ERROR, WARN, FIXME, INFO, DEBUG, LOG:
        _FORMATTED_LEVELS.append(formatter(level))

### "public" useful API

# setup functions


def init(envVarName, enableColorOutput=True, enableCrackOutput=True):
    """
    Initialize the logging system and parse the environment variable
    of the given name.
    Needs to be called before starting the actual application.
    """
    global _initialized
    global _enableCrackOutput
    _enableCrackOutput = enableCrackOutput

    if _initialized:
        return

    global _ENV_VAR_NAME
    _ENV_VAR_NAME = envVarName

    _preformatLevels(enableColorOutput)

    if envVarName in os.environ:
        # install a log handler that uses the value of the environment var
        setDebug(os.environ[envVarName])
    addLimitedLogHandler(stderrHandler)

    _initialized = True


def setDebug(string):
    """Set the DEBUG string.  This controls the log output."""
    global _DEBUG
    global _ENV_VAR_NAME
    global _categories

    _DEBUG = string
    debug('log', "%s set to %s" % (_ENV_VAR_NAME, _DEBUG))

    # reparse all already registered category levels
    for category in _categories:
        registerCategory(category)


def getDebug():
    """
    Returns the currently active DEBUG string.
    @rtype: str
    """
    global _DEBUG
    return _DEBUG


def setPackageScrubList(*packages):
    """
    Set the package names to scrub from filenames.
    Filenames from these paths in log messages will be scrubbed to their
    relative file path instead of the full absolute path.

    @type packages: list of str
    """
    global _PACKAGE_SCRUB_LIST
    _PACKAGE_SCRUB_LIST = packages


def reset():
    """
    Resets the logging system, removing all log handlers.
    """
    global _log_handlers, _log_handlers_limited, _initialized

    _log_handlers = []
    _log_handlers_limited = []
    _initialized = False


def addLogHandler(func):
    """
    Add a custom log handler.

    @param func: a function object with prototype (level, object, category,
                 message) where level is either ERROR, WARN, INFO, DEBUG, or
                 LOG, and the rest of the arguments are strings or None. Use
                 getLevelName(level) to get a printable name for the log level.
    @type func:  a callable function

    @raises TypeError: if func is not a callable
    """

    if not isinstance(func, collections.Callable):
        raise TypeError("func must be callable")

    if func not in _log_handlers:
        _log_handlers.append(func)


def addLimitedLogHandler(func):
    """
    Add a custom log handler.

    @param func: a function object with prototype (level, object, category,
                 message) where level is either ERROR, WARN, INFO, DEBUG, or
                 LOG, and the rest of the arguments are strings or None. Use
                 getLevelName(level) to get a printable name for the log level.
    @type func:  a callable function

    @raises TypeError: TypeError if func is not a callable
    """
    if not isinstance(func, collections.Callable):
        raise TypeError("func must be callable")

    if func not in _log_handlers_limited:
        _log_handlers_limited.append(func)


def removeLogHandler(func):
    """
    Remove a registered log handler.

    @param func: a function object with prototype (level, object, category,
                 message) where level is either ERROR, WARN, INFO, DEBUG, or
                 LOG, and the rest of the arguments are strings or None. Use
                 getLevelName(level) to get a printable name for the log level.
    @type func:  a callable function

    @raises ValueError: if func is not registered
    """
    _log_handlers.remove(func)


def removeLimitedLogHandler(func):
    """
    Remove a registered limited log handler.

    @param func: a function object with prototype (level, object, category,
                 message) where level is either ERROR, WARN, INFO, DEBUG, or
                 LOG, and the rest of the arguments are strings or None. Use
                 getLevelName(level) to get a printable name for the log level.
    @type func:  a callable function

    @raises ValueError: if func is not registered
    """
    _log_handlers_limited.remove(func)

# public log functions


def error(cat, format, *args):
    errorObject(None, cat, format, *args)


def warning(cat, format, *args):
    warningObject(None, cat, format, *args)


def fixme(cat, format, *args):
    fixmeObject(None, cat, format, *args)


def info(cat, format, *args):
    infoObject(None, cat, format, *args)


def debug(cat, format, *args):
    debugObject(None, cat, format, *args)


def log(cat, format, *args):
    logObject(None, cat, format, *args)

# public utility functions


def getExceptionMessage(exception, frame=-1, filename=None):
    """
    Return a short message based on an exception, useful for debugging.
    Tries to find where the exception was triggered.
    """
    stack = traceback.extract_tb(sys.exc_info()[2])
    if filename:
        stack = [f for f in stack if f[0].find(filename) > -1]
    #import code; code.interact(local=locals())
    (filename, line, func, text) = stack[frame]
    filename = scrubFilename(filename)
    exc = exception.__class__.__name__
    msg = ""
    # a shortcut to extract a useful message out of most exceptions
    # for now
    if str(exception):
        msg = ": %s" % str(exception)
    return "exception %(exc)s at %(filename)s:%(line)s: %(func)s()%(msg)s" \
        % locals()


def reopenOutputFiles():
    """
    Reopens the stdout and stderr output files, as set by
    L{outputToFiles}.
    """
    if not _stdout and not _stderr:
        debug('log', 'told to reopen log files, but log files not set')
        return

    def reopen(name, fileno, *args):
        oldmask = os.umask(0o026)
        try:
            f = open(name, 'a+', *args)
        finally:
            os.umask(oldmask)

        os.dup2(f.fileno(), fileno)

    if _stdout:
        reopen(_stdout, sys.stdout.fileno())

    if _stderr:
        reopen(_stderr, sys.stderr.fileno(), 0)
        debug('log', 'opened log %r', _stderr)


def outputToFiles(stdout=None, stderr=None):
    """
    Redirect stdout and stderr to named files.

    Records the file names so that a future call to reopenOutputFiles()
    can open the same files. Installs a SIGHUP handler that will reopen
    the output files.

    Note that stderr is opened unbuffered, so if it shares a file with
    stdout then interleaved output may not appear in the order that you
    expect.
    """
    global _stdout, _stderr, _old_hup_handler
    _stdout, _stderr = stdout, stderr
    reopenOutputFiles()

    def sighup(signum, frame):
        info('log', "Received SIGHUP, reopening logs")
        reopenOutputFiles()
        if _old_hup_handler:
            info('log', "Calling old SIGHUP hander")
            _old_hup_handler(signum, frame)

    debug('log', 'installing SIGHUP handler')
    from . import signal
    handler = signal.signal(signal.SIGHUP, sighup)
    if handler == signal.SIG_DFL or handler == signal.SIG_IGN:
        _old_hup_handler = None
    else:
        _old_hup_handler = handler


# base class for loggable objects


class BaseLoggable(object):
    """
    Base class for objects that want to be able to log messages with
    different level of severity.  The levels are, in order from least
    to most: log, debug, info, warning, error.

    @cvar logCategory: Implementors can provide a category to log their
       messages under.
    """

    def writeMarker(self, marker, level):
        """
        Sets a marker that written to the logs. Setting this
        marker to multiple elements at a time helps debugging.
        @param marker: A string write to the log.
        @type marker: str
        @param level: The log level. It can be log.ERROR, etc.
        @type  level: int
        """
        logHandlers = {WARN: self.warning,
                       INFO: self.info,
                       DEBUG: self.debug,
                       ERROR: self.error,
                       LOG: self.log}
        logHandler = logHandlers.get(level)
        if logHandler:
            logHandler('%s', marker)

    def error(self, *args):
        """Log an error.  By default this will also raise an exception."""
        if _canShortcutLogging(self.logCategory, ERROR):
            return
        errorObject(self.logObjectName(), self.logCategory, *self.logFunction(*args))

    def warning(self, *args):
        """Log a warning.  Used for non-fatal problems."""
        if _canShortcutLogging(self.logCategory, WARN):
            return
        warningObject(self.logObjectName(), self.logCategory, *self.logFunction(*args))

    def fixme(self, *args):
        """Log a fixme.  Used for FIXMEs ."""
        if _canShortcutLogging(self.logCategory, FIXME):
            return
        fixmeObject(self.logObjectName(), self.logCategory, *self.logFunction(*args))

    def info(self, *args):
        """Log an informational message.  Used for normal operation."""
        if _canShortcutLogging(self.logCategory, INFO):
            return
        infoObject(self.logObjectName(), self.logCategory, *self.logFunction(*args))

    def debug(self, *args):
        """Log a debug message.  Used for debugging."""
        if _canShortcutLogging(self.logCategory, DEBUG):
            return
        debugObject(self.logObjectName(), self.logCategory, *self.logFunction(*args))

    def log(self, *args):
        """Log a log message.  Used for debugging recurring events."""
        if _canShortcutLogging(self.logCategory, LOG):
            return
        logObject(self.logObjectName(), self.logCategory, *self.logFunction(*args))

    def doLog(self, level, where, format, *args, **kwargs):
        """
        Log a message at the given level, with the possibility of going
        higher up in the stack.

        @param level: log level
        @type  level: int
        @param where: how many frames to go back from the last log frame;
                      or a function (to log for a future call)
        @type  where: int (negative), or function

        @param kwargs: a dict of pre-calculated values from a previous
                       doLog call

        @return: a dict of calculated variables, to be reused in a
                 call to doLog that should show the same location
        @rtype:  dict
        """
        if _canShortcutLogging(self.logCategory, level):
            return {}
        args = self.logFunction(*args)
        return doLog(level, self.logObjectName(), self.logCategory,
                  format, args, where=where, **kwargs)

    def logFunction(self, *args):
        """Overridable log function.  Default just returns passed message."""
        return args

    def logObjectName(self):
        """Overridable object name function."""
        # cheat pychecker
        for name in ['logName', 'name']:
            if hasattr(self, name):
                return getattr(self, name)

        return None

    def handleException(self, exc):
        self.warning(getExceptionMessage(exc))


class Loggable(BaseLoggable):
    def __init__(self, logCategory=None):
        if logCategory:
            self.logCategory = logCategory
        elif not hasattr(self, 'logCategory'):
            self.logCategory = self.__class__.__name__.lower()

    def logObjectName(self):
        res = BaseLoggable.logObjectName(self)
        if not res:
            return "<%s at 0x%x>" % (self.__class__.__name__, id(self))
        return res

    def error(self, format, *args):
        if _canShortcutLogging(self.logCategory, ERROR):
            return
        doLog(ERROR, self.logObjectName(), self.logCategory,
            format, self.logFunction(*args), where=-2)
