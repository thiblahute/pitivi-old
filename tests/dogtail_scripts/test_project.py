#!/usr/bin/env python2
from helper_functions import HelpFunc
from dogtail.predicate import IsATextEntryNamed, GenericPredicate
from time import time, sleep
import os

# These are the timecodes we expect for "tears of steel.webm", depending on
# if we insert it once in a blank timeline or twice in a blank timeline.
DURATION_OF_ONE_CLIP = "0:00:01.999"
DURATION_OF_TWO_CLIPS = "0:00:03.999"


class ProjectPropertiesTest(HelpFunc):

    # Convenience methods

    def wait_for_file(self, path, time_out=10):
        """
        Check for the existence of a file, until a timeout is reached.
        This gives enough time for GES/Pitivi to do whatever it needs to do.

        Also checks that the file is not an empty (0 bytes) file.
        """
        time_elapsed = 0
        exists = False
        while (time_elapsed <= time_out) and not exists:
            time_elapsed += 1
            sleep(1)
            exists = os.path.isfile(path) and os.path.getsize(path) > 0
        return exists

    def wait_for_update(self, path, timestamp, time_out=20):
        time_elapsed = 0
        new_timestamp = False
        while (time_elapsed <= time_out) and new_timestamp == timestamp:
            time_elapsed += 2
            sleep(2)
            new_timestamp = os.path.getmtime(path)
        return new_timestamp != timestamp

    # The actual test cases

    def test_settings_video(self):
        # TODO: test the audio and metadata tabs too
        welcome_dialog = self.pitivi.child(name="Welcome", roleName="frame", recursive=False)
        welcome_dialog.button("New").click()
        dialog = self.pitivi.child(name="Project Settings", roleName="dialog", recursive=False)
        video = dialog.tab("Video")

        # Select a different preset
        # CAUTION: changing the resolution changes the pixel aspect ratio!
        video.child(name="720p24", roleName="table cell").click()
        children = video.findChildren(IsATextEntryNamed(""))
        childtext = {}  # The framerate, DAR and PAR custom text entry widgets
        for child in children:
            childtext[child.text] = child
        # Do a quick check to ensure we have all three text entry widgets:
        self.assertIn("1:1", childtext)
        self.assertIn("24M", childtext)
        self.assertIn("16:9", childtext)
        # Then verify the resolution was set correctly from the preset:
        children = video.findChildren(GenericPredicate(roleName="spin button"))
        spintext = {}
        for child in children:
            spintext[child.text] = child
        self.assertIn("1280", spintext)
        self.assertIn("720", spintext)

        #Test frame rate combinations, link button
        frameCombo = video.child(name="23.976 fps", roleName="combo box")
        frameText = childtext["24M"]
        frameCombo.click()
        video.child(name="120 fps", roleName="menu item").click()
        self.assertEqual(frameText.text, "120:1")
        frameText.click()
        frameText.typeText("0")
        video.child(name="12 fps", roleName="combo box")

        # Test pixel and display aspect ratio (PAR and DAR)
        pixelCombo = video.child(name="Square", roleName="combo box")
        pixelText = childtext["1:1"]
        displayCombo = video.child(name="DV Widescreen (16:9)", roleName="combo box")
        displayText = childtext["16:9"]

        pixelCombo.click()
        video.child(name="576p", roleName="menu item").click()
        self.assertEqual(pixelCombo.combovalue, "576p")
        self.assertEqual(pixelText.text, "12:11")
        self.assertEqual(displayText.text, "64:33")

        pixelText.doubleClick()
        pixelText.click()
        pixelText.typeText("3:4")
        self.assertEqual(pixelText.text, "3:4")
        self.assertEqual(displayCombo.combovalue, "Standard (4:3)")
        self.assertEqual(displayText.text, "4:3")

        video.child(name="Display aspect ratio", roleName="radio button").click()
        displayCombo.click()
        video.child(name="Cinema (1.37)", roleName="menu item").click()
        self.assertEqual(displayCombo.combovalue, "Cinema (1.37)")
        self.assertEqual(displayText.text, "11:8")
        self.assertEqual(pixelText.text, "99:128")

        displayText.doubleClick()
        displayText.click()
        displayText.typeText("37:20")
        self.assertEqual(displayCombo.combovalue, "Cinema (1.85)")
        self.assertEqual(pixelText.text, "333:320")  # It changes further below
        # This check is probably useless, but we never know:
        self.assertEqual(displayText.text, "37:20")

        # Test size spin buttons
        # spinbuttonClick and spinbuttonDoubleClick are methods from HelperFunc
        spin = video.findChildren(GenericPredicate(roleName="spin button"))
        oldtext = spin[1].text
        self.spinbuttonDoubleClick(spin[0])
        spin[0].typeText("1000")
        self.assertEqual(spin[1].text, oldtext)
        self.spinbuttonDoubleClick(spin[1])
        spin[1].typeText("2000")
        video.child(name="Link").click()
        self.spinbuttonDoubleClick(spin[1])
        spin[1].typeText("1000")
        self.spinbuttonClick(spin[0])
        self.assertEqual(spin[0].text, "500")  # Final resolution: 500x1000

        # Apply the changes to the newly created project
        dialog.button("OK").click()

        # A blank project was created, test saving without any clips/objects
        settings_test_project_file = "/tmp/auto_pitivi_test_project_settings.xges"
        self.unlink.append(settings_test_project_file)
        self.saveProject(settings_test_project_file)
        self.assertTrue(self.wait_for_file(settings_test_project_file))
        # Really quit to be sure the stuff was correctly serialized
        self.tearDown(clean=False, kill=False)
        self.setUp()
        self.loadProject(settings_test_project_file)
        sleep(1)  # Give enough time for GES to load the project
        self.pitivi.menu("Edit").click()
        self.pitivi.menuItem("Project Settings").click()
        # Since we shut down the whole app, we must reset our shortcut variables:
        dialog = self.pitivi.child(name="Project Settings", roleName="dialog", recursive=False)
        video = dialog.tab("Video")

        # Check the resolution:
        children = video.findChildren(GenericPredicate(roleName="spin button"))
        spintext = {}
        for child in children:
            spintext[child.text] = child
        self.assertIn("500", spintext, "Video height was not saved")
        self.assertIn("1000", spintext, "Video width was not saved")

        # Check the aspect ratios:
        dialog = self.pitivi.child(name="Project Settings", roleName="dialog", recursive=False)
        video = dialog.tab("Video")
        children = video.findChildren(IsATextEntryNamed(""))
        childtext = {}  # The framerate, DAR and PAR custom text entry widgets
        for child in children:
            childtext[child.text] = child
        # You'd expect a PAR of 333:320 and DAR of 37:20... but we changed the
        # resolution (500x1000) right before saving, so the PAR changed to 37:10
        self.assertIn("37:10", childtext, "Pixel aspect ratio was not saved")
        # However, the DAR is expected to be unaffected by the image resolution:
        self.assertEqual(displayCombo.combovalue, "Cinema (1.85)")
        self.assertIn("37:20", childtext, "Display aspect ratio was not saved")

    def test_backup(self):
        # FIXME: this test would fail in listview mode - for now we just force iconview mode.
        self.force_medialibrary_iconview_mode()

        # Import a clip into an empty project and save the project
        sample = self.import_media()
        filename = "auto_pitivi_test_project-%i.xges" % time()
        path = "/tmp/" + filename
        backup_path = path + "~"
        self.unlink.append(backup_path)
        self.saveProject(path)

        #Change somthing
        seektime = self.viewer.child(name="timecode_entry").child(roleName="text")
        self.assertIsNotNone(seektime)
        self.insert_clip(sample)
        self.goToEnd_button = self.viewer.child(name="goToEnd_button")
        self.goToEnd_button.click()
        self.assertEqual(seektime.text, DURATION_OF_ONE_CLIP)

        #It should save after 10 seconds if no changes made
        self.assertTrue(self.wait_for_file(backup_path), "Backup not created")
        self.assertTrue(os.path.getmtime(backup_path) -
                        os.path.getmtime(path) > 0,
                        "Backup is older than saved file")

        #Try to quit, it should warn us
        self.menubar.menu("Project").click()
        self.menubar.menu("Project").menuItem("Quit").click()

        #If finds button, means it warned
        self.pitivi.child(roleName="dialog", recursive=False).button("Cancel").click()
        self.saveProject(saveAs=False)
        #Backup should be deleted, and no warning displayed
        self.menubar.menu("Project").click()
        self.menubar.menu("Project").menuItem("Quit").click()
        self.assertFalse(os.path.exists(backup_path))
        #Test if backup is found
        self.setUp()
        welcome_dialog = self.pitivi.child(name="Welcome", roleName="frame", recursive=False)
        welcome_dialog.child(name=filename).doubleClick()
        sample = self.import_media("flat_colour1_640x480.png")
        self.assertTrue(self.wait_for_file(backup_path, 120), "Backup not created")
        self.tearDown(clean=False, kill=True)
        self.setUp()
        welcome_dialog = self.pitivi.child(name="Welcome", roleName="frame", recursive=False)
        welcome_dialog.child(name=filename).doubleClick()
        #Try restoring from backup
        self.pitivi.child(roleName="dialog", recursive=False).button("Restore from backup").click()
        samples = self.medialibrary.findChildren(GenericPredicate(roleName="icon"))
        self.assertEqual(len(samples), 2)
        self.menubar.menu("Project").click()
        self.assertFalse(self.menubar.menu("Project").menuItem("Save").sensitive)
        #Behaved as saveAs

        # Kill once more
        self.tearDown(clean=False, kill=True)
        timestamp = os.path.getmtime(backup_path)
        self.setUp()
        welcome_dialog = self.pitivi.child(name="Welcome", roleName="frame", recursive=False)
        welcome_dialog.child(name=filename).doubleClick()
        self.pitivi.child(roleName="dialog", recursive=False).button("Ignore backup").click()
        #Backup is not deleted, not changed
        self.assertEqual(timestamp, os.path.getmtime(backup_path))

        #Look if backup updated, even it is newer than saved project

        sample = self.import_media("flat_colour2_640x480.png")
        self.assertTrue(self.wait_for_update(backup_path, timestamp))
        #Try to quit, it should warn us (still newer version)
        self.menubar.menu("Project").click()
        self.menubar.menu("Project").menuItem("Quit").click()

        # Dismiss the unsaved changes warning by cancelling it:
        self.pitivi.child(roleName="dialog", recursive=False).button("Cancel").click()
        self.saveProject(saveAs=False)

        #Backup should be deleted, and no warning displayed
        self.menubar.menu("Project").click()
        self.menubar.menu("Project").menuItem("Quit").click()
        self.assertFalse(os.path.exists(backup_path))

    def test_load_save(self):
        self.goToEnd_button = self.viewer.child(name="goToEnd_button")
        seektime = self.viewer.child(name="timecode_entry").child(roleName="text")
        infobar_media = self.medialibrary.child(name="Information", roleName="alert")
        iconview = self.medialibrary.child(roleName="layered pane")
        filename1 = "/tmp/auto_pitivi_test_project-1.xges"
        filename2 = "/tmp/auto_pitivi_test_project-2.xges"
        self.unlink.append(filename1)
        self.unlink.append(filename2)

        # FIXME: this test would fail in listview mode - for now we just force iconview mode.
        self.force_medialibrary_iconview_mode()

        #Create project
        self.assertTrue(infobar_media.showing)
        sample = self.import_media()
        self.insert_clip(sample)
        self.saveProject(filename1)
        self.assertFalse(infobar_media.showing)

        # Creating a blank project should clear the library and show its infobar
        sleep(0.5)
        self.menubar.menu("Project").click()
        self.menubar.menu("Project").menuItem("New").click()
        self.pitivi.child(name="Project Settings", roleName="dialog", recursive=False).button("OK").click()

        self.goToEnd_button.click()
        self.assertEqual(len(iconview.children), 0,
            "Created a new project, but the media library is not empty")
        self.assertTrue(infobar_media.showing)

        #Create bigger project
        sample = self.import_media()
        self.import_media("flat_colour1_640x480.png")
        self.insert_clip(sample, 2)
        self.saveProject(filename2)
        self.assertFalse(infobar_media.showing)

        #Load first, check if populated
        self.load_project(filename1)
        self.goToEnd_button.click()
        self.assertEqual(len(iconview.children), 1)
        self.assertEqual(seektime.text, DURATION_OF_ONE_CLIP)
        self.assertFalse(infobar_media.showing)

        #Load second, check if populated
        self.load_project(filename2)
        self.goToEnd_button.click()
        self.assertEqual(len(iconview.children), 2)
        self.assertEqual(seektime.text, DURATION_OF_TWO_CLIPS)
        self.assertFalse(infobar_media.showing)
