# -*- coding: utf-8 -*-
#
# Copyright (c) 2009, Brandon Lewis <brandon_lewis@berkeley.edu>
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

import unittest

from pitivi.dialogs.prefs import PreferencesDialog


class PreferencesDialogTest(unittest.TestCase):

    def testNumeric(self):
        PreferencesDialog.addNumericPreference('numericPreference1',
                                               label="Open Range",
                                               section="Test",
                                               description="This option has no upper bound",
                                               lower=-10)
        self.assertTrue(
            'numericPreference1' in PreferencesDialog.prefs['Test'])

        PreferencesDialog.addNumericPreference('numericPreference2',
                                               label="Closed Range",
                                               section="Test",
                                               description="This option has both upper and lower bounds",
                                               lower=-10,
                                               upper=10000)

    def testText(self):
        PreferencesDialog.addTextPreference('textPreference1',
                                            label="Unfiltered",
                                            section="Test",
                                            description="Anything can go in this box")

        PreferencesDialog.addTextPreference('textPreference2',
                                            label="Numbers only",
                                            section="Test",
                                            description="This input validates its input with a regex",
                                            matches=r"^-?\d+(\.\d+)?$")

    def testOther(self):
        PreferencesDialog.addPathPreference('aPathPreference',
                                            label="Test Path",
                                            section="Test",
                                            description="Test the path widget")

        PreferencesDialog.addChoicePreference('aChoicePreference',
                                              label="Swallow Velocity",
                                              section="Test",
                                              description="What is the airspeed velocity of a coconut-laden swallow?",
                                              choices=(
                                                  ("42 Knots", 32),
                                                  ("9 furlongs per fortnight", 42),
                                                  ("I don't know that!", None)))

        PreferencesDialog.addChoicePreference('aLongChoicePreference',
                                              label="Favorite Color",
                                              section="Test",
                                              description="What is the color of the parrot's plumage?",
                                              choices=(
                                                  ("Mauve", "Mauve"),
                                                  ("Chartreuse", "Chartreuse"),
                                                  ("Magenta", "Magenta"),
                                                  ("Pink", "Pink"),
                                                  ("Norwegian Blue", "Norwegian Blue"),
                                                  ("Yellow Ochre", "Yellow Ochre")))

        PreferencesDialog.addTogglePreference('aTogglePreference',
                                              label="Test Toggle",
                                              section="Test",
                                              description="Test the toggle widget")

        PreferencesDialog.addFontPreference('aFontPreference',
                                            label="Foo Font",
                                            section="Test",
                                            description="Test the font widget")
