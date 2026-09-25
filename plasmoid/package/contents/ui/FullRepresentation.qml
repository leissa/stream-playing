/* The popup: what is playing, the shared queue, and the merged library. */

import QtQuick
import QtQuick.Layouts

import org.kde.plasma.components as PlasmaComponents
import org.kde.plasma.extras as PlasmaExtras
import org.kde.kirigami as Kirigami

Item {
    id: full

    readonly property var client: root.client

    Layout.minimumWidth: Kirigami.Units.gridUnit * 20
    Layout.minimumHeight: Kirigami.Units.gridUnit * 24
    Layout.preferredWidth: Kirigami.Units.gridUnit * 26
    Layout.preferredHeight: Kirigami.Units.gridUnit * 30

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: Kirigami.Units.smallSpacing
        spacing: Kirigami.Units.smallSpacing

        HeaderBar {
            Layout.fillWidth: true
        }

        PlasmaComponents.TabBar {
            id: tabs
            Layout.fillWidth: true
            currentIndex: 0

            PlasmaComponents.TabButton {
                icon.name: "media-playback-start"
                text: i18nc("@title:tab", "Playing")
            }
            PlasmaComponents.TabButton {
                icon.name: "view-media-playlist"
                text: i18nc("@title:tab queue of upcoming tracks", "Queue")
            }
            PlasmaComponents.TabButton {
                icon.name: "view-media-album-cover"
                text: i18nc("@title:tab", "Library")
            }
        }

        StackLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            currentIndex: tabs.currentIndex

            NowPlayingPane {}
            QueuePane {}
            LibraryPane {}
        }

        // The daemon reports these in response to something the user just did.
        PlasmaComponents.Label {
            id: notice
            Layout.fillWidth: true
            visible: opacity > 0
            opacity: 0
            wrapMode: Text.WordWrap
            maximumLineCount: 2
            elide: Text.ElideRight
            color: Kirigami.Theme.negativeTextColor
            font: Kirigami.Theme.smallFont

            Behavior on opacity { NumberAnimation { duration: 150 } }

            Timer {
                id: noticeTimer
                interval: 6000
                onTriggered: notice.opacity = 0
            }

            Connections {
                target: full.client
                function onErrorReported(message) {
                    notice.text = message;
                    notice.opacity = 1;
                    noticeTimer.restart();
                }
            }
        }

        TransportBar {
            Layout.fillWidth: true
        }
    }

    // Nothing useful can be shown until the daemon answers.
    PlasmaExtras.PlaceholderMessage {
        anchors.centerIn: parent
        width: parent.width - Kirigami.Units.gridUnit * 4
        visible: !full.client.online
        iconName: "network-disconnect"
        text: i18n("The streamplay service is not running")
        explanation: i18n("Start it with: systemctl --user start streamplay")
    }
}
