@YELP_HELP_RULES@

HELP_ID = pitivi
HELP_MEDIA = \
    figures/codecscontainers.jpg\
    figures/fadestep1.png \
    figures/fadestep2.png \
    figures/fadestep3.png \
    figures/keyframecurves.png \
    figures/layers.png \
    figures/logo.png \
    figures/mainwindow.jpg \
    figures/ripple-after.png \
    figures/ripple-before.png \
    figures/roll-after.png \
    figures/roll-before.png \
    figures/ruler.png \
    figures/trimming-individual.png

HELP_FILES = \
    about.page \
    cheatsheet.page \
    codecscontainers.page \
    effects.page \
    gstreamer.page \
    importingmpegts.page \
    importing.page \
    index.page \
    keyframecurves.page \
    layers.page \
    license.page \
    mainwindow.page \
    medialibrary.page \
    movearoundtimeline.page \
    presets.page \
    rendering.page \
    savescreenshot.page \
    selectiongrouping.page \
    splitting.page \
    sysreq.page \
    transitions.page \
    trimming.page \
    usingclips.page \
    usingeffects.page \
    welcomedialog.page \
    workwithprojects.page

HELP_LINGUAS = cs de el es fr sl uk

distdir-help-files: all

html:
	mkdir -p html
	yelp-build cache C/*.page
	yelp-build html -o html C/*.page
