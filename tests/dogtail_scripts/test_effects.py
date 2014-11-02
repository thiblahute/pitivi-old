#!/usr/bin/env python2

import dogtail.rawinput

from common import PitiviTestCase


class EffectLibraryTest(PitiviTestCase):

    def setUp(self):
        PitiviTestCase.setUp(self)
        self.search = self.effectslibrary.child(
            name="effects library search entry")
        self.view = self.effectslibrary.child(roleName="table")
        self.combotypes = self.effectslibrary.child(
            name="effect category combobox", roleName="combo box")
        self.toggle = self.effectslibrary.child(
            name="effects library audio togglebutton")

    def test_effect_library(self):
        self.import_media()
        self.effectslibrary.click()
        # Some test of video effects and search. The two column headers are
        # also children and are always present, and each row has two children:
        self.search.text = "Crop"
        self.assertEqual(len(self.view.children), 2 + 2 * 3)
        self.combotypes.click()
        self.combotypes.menuItem("Colors").click()
        self.assertEqual(len(self.view.children), 2 + 2 * 0)
        self.combotypes.click()
        self.combotypes.menuItem("Geometry").click()
        self.assertEqual(len(self.view.children), 2 + 2 * 3)

        # Switch to audio effects view
        self.toggle.click()
        self.search.text = "Equa"
        # The effects library listview doesn't show the header row, but
        # it is still one of the children. So when we're looking for the 3
        # rows matching "Equa", we need to add one child (1 header + 3 rows).
        self.assertEqual(len(self.view.children), 4)

    def test_change_effect_settings(self):
        self.force_medialibrary_iconview_mode()

        sample = self.import_media()
        self.insert_clip(sample)
        # Assume that the layer controls are roughly 260 pixels wide,
        # so the clip position should be x + 300, y + 30
        clippos = (self.timeline.position[
                   0] + 300, self.timeline.position[1] + 30)

        self.effectslibrary.click()
        self.clipproperties.click()
        clip_effects_table = self.clipproperties.child(roleName="table")

        dogtail.rawinput.click(clippos[0], clippos[1])
        self.assertTrue(clip_effects_table.sensitive)
        # No effects added. The listview has 3 columns, so it starts at 3.
        # Each time you add an effect, it adds a row, so +3 children.
        self.assertEqual(len(clip_effects_table.children), 3)

        icon = self.search_by_regex(
            "^Agingtv", self.effectslibrary, roleName="table cell")

        # Drag video effect on the clip
        self.improved_drag(self.center(icon), clippos)
        self.assertEqual(len(clip_effects_table.children), 6)
        # Drag video effect to the table
        icon = self.search_by_regex(
            "^3Dflippo", self.effectslibrary, roleName="table cell")
        self.improved_drag(self.center(icon), self.center(clip_effects_table))
        self.assertEqual(len(clip_effects_table.children), 9)

        # Drag audio effect on the clip
        self.toggle.click()
        effect = self.search_by_regex(
            "^Amplifier", self.effectslibrary, roleName="table cell")
        self.improved_drag(self.center(effect), clippos)
        self.assertEqual(len(clip_effects_table.children), 12)

        # Drag audio effect on the table
        effect = self.search_by_regex(
            "^Audiokaraoke", self.effectslibrary, roleName="table cell")
        self.improved_drag(
            self.center(effect), self.center(clip_effects_table))
        self.assertEqual(len(clip_effects_table.children), 15)

        self.clipproperties.child(roleName="table").child(name="Amplifier").click()
        fx_expander = self.clipproperties.child(name="Effects", roleName="toggle button")
        fx_expander.child(name="Normal clipping (default)", roleName="combo box")
        fx_expander.child(roleName="spin button").text = "2"
