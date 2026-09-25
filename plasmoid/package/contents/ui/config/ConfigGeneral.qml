import QtQuick
import QtQuick.Controls as QQC2
import QtQuick.Layouts

import org.kde.kcmutils as KCM
import org.kde.kirigami as Kirigami

KCM.SimpleKCM {
    id: page

    property alias cfg_daemonHost: hostField.text
    property alias cfg_daemonPort: portField.value
    property alias cfg_showTrackInPanel: trackInPanel.checked
    property alias cfg_panelTextLength: textLength.value
    property alias cfg_useAlbumArtIcon: albumArtIcon.checked
    property alias cfg_wheelChangesVolume: wheelVolume.checked
    property string cfg_albumSort: "alphabetical"
    property alias cfg_showAlbums: showAlbums.checked
    property alias cfg_showArtists: showArtists.checked
    property alias cfg_showGenres: showGenres.checked
    property alias cfg_showPlaylists: showPlaylists.checked

    Kirigami.FormLayout {
        anchors.left: parent.left
        anchors.right: parent.right

        Item { Kirigami.FormData.isSection: true
               Kirigami.FormData.label: i18n("Service") }

        QQC2.TextField {
            id: hostField
            Kirigami.FormData.label: i18n("Host:")
            Layout.fillWidth: true
        }

        QQC2.SpinBox {
            id: portField
            Kirigami.FormData.label: i18n("Port:")
            from: 1
            to: 65535
            editable: true
            // A plain number, not a formatted one; ports have no thousands mark.
            textFromValue: value => value.toString()
            valueFromText: text => parseInt(text, 10)
        }

        QQC2.Label {
            Layout.fillWidth: true
            wrapMode: Text.WordWrap
            font: Kirigami.Theme.smallFont
            text: i18n("The streamplay service does the playing and holds the "
                     + "queue. Leave this at 127.0.0.1 unless you run it on "
                     + "another machine.")
        }

        Item { Kirigami.FormData.isSection: true
               Kirigami.FormData.label: i18n("Panel") }

        QQC2.CheckBox {
            id: trackInPanel
            Kirigami.FormData.label: i18n("Show:")
            text: i18n("Track title next to the icon")
        }

        QQC2.SpinBox {
            id: textLength
            Kirigami.FormData.label: i18n("Shorten title to:")
            from: 8
            to: 80
            enabled: trackInPanel.checked
            textFromValue: value => i18np("%1 character", "%1 characters", value)
            valueFromText: text => parseInt(text, 10)
        }

        QQC2.CheckBox {
            id: albumArtIcon
            text: i18n("Use album art as the panel icon")
        }

        QQC2.CheckBox {
            id: wheelVolume
            text: i18n("Scrolling over the icon changes the volume")
        }

        Item { Kirigami.FormData.isSection: true
               Kirigami.FormData.label: i18n("Library") }

        QQC2.ComboBox {
            id: sortBox
            Kirigami.FormData.label: i18n("Sort albums by:")
            textRole: "label"
            valueRole: "value"
            model: [
                { value: "alphabetical", label: i18n("Title") },
                { value: "artist",       label: i18n("Artist") },
                { value: "newest",       label: i18n("Recently added") },
                { value: "recent",       label: i18n("Recently played") },
                { value: "frequent",     label: i18n("Most played") },
                { value: "byYear",       label: i18n("Year (oldest first)") },
                { value: "byYearDesc",   label: i18n("Year (newest first)") },
                { value: "random",       label: i18n("Random") },
            ]
            onActivated: page.cfg_albumSort = currentValue
            Component.onCompleted: currentIndex = indexOfValue(page.cfg_albumSort)
        }

        QQC2.CheckBox {
            id: showAlbums
            Kirigami.FormData.label: i18n("Show sections:")
            text: i18n("Albums")
        }

        QQC2.CheckBox {
            id: showArtists
            text: i18n("Artists")
        }

        QQC2.CheckBox {
            id: showGenres
            text: i18n("Genres")
        }

        QQC2.CheckBox {
            id: showPlaylists
            text: i18n("Playlists")
        }

        QQC2.Label {
            Layout.fillWidth: true
            wrapMode: Text.WordWrap
            font: Kirigami.Theme.smallFont
            visible: !showAlbums.checked && !showArtists.checked
                     && !showGenres.checked && !showPlaylists.checked
            color: Kirigami.Theme.negativeTextColor
            text: i18n("At least one section has to stay switched on; "
                     + "Albums will be used otherwise.")
        }
    }
}
