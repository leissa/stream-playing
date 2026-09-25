/* Panel / system-tray face: album art plus, where there is room, the title. */

import QtQuick
import QtQuick.Layouts

import org.kde.plasma.core as PlasmaCore
import org.kde.plasma.components as PlasmaComponents
import org.kde.plasma.plasmoid
import org.kde.kirigami as Kirigami

import "Formatting.js" as Fmt

MouseArea {
    id: compact

    readonly property bool horizontalPanel:
        Plasmoid.formFactor === PlasmaCore.Types.Horizontal
    readonly property bool showLabel:
        horizontalPanel && Plasmoid.configuration.showTrackInPanel && root.hasTrack
    readonly property string artSource:
        Plasmoid.configuration.useAlbumArtIcon
        ? root.client.itemCover(root.track, 128) : ""

    Layout.minimumWidth: horizontalPanel ? layout.implicitWidth : -1
    Layout.minimumHeight: horizontalPanel ? -1 : layout.implicitHeight
    Layout.preferredWidth: Layout.minimumWidth

    acceptedButtons: Qt.LeftButton | Qt.MiddleButton
    hoverEnabled: true

    onClicked: mouse => {
        if (mouse.button === Qt.MiddleButton) {
            root.client.playPause();
        } else {
            root.expanded = !root.expanded;
        }
    }

    // Scrolling over the icon is the quickest way to nudge the volume.
    onWheel: wheel => {
        if (!Plasmoid.configuration.wheelChangesVolume || !root.client.linked) {
            return;
        }
        const step = wheel.angleDelta.y > 0 ? 0.05 : -0.05;
        const next = Math.max(0, Math.min(1, root.client.playback.volume + step));
        root.client.setVolume(next);
    }

    RowLayout {
        id: layout
        anchors.fill: parent
        spacing: Kirigami.Units.smallSpacing

        Item {
            Layout.alignment: Qt.AlignVCenter
            Layout.preferredHeight: Math.min(compact.height, compact.width)
            Layout.preferredWidth: Layout.preferredHeight

            Kirigami.Icon {
                anchors.fill: parent
                visible: cover.status !== Image.Ready
                source: !root.hasTrack ? Qt.resolvedUrl("../icons/streamplay-symbolic.svg")
                      : root.playing ? "media-playback-start"
                                     : "media-playback-pause"
                isMask: !root.hasTrack
                active: compact.containsMouse
                // Grey the icon out while the daemon is unreachable.
                opacity: root.client.online ? 1.0 : 0.5
            }

            Image {
                id: cover
                anchors.fill: parent
                source: compact.artSource
                fillMode: Image.PreserveAspectCrop
                asynchronous: true
                cache: true
                smooth: true
                visible: status === Image.Ready
            }

            // A small badge so a paused track is distinguishable at a glance.
            Kirigami.Icon {
                visible: cover.status === Image.Ready && !root.playing && root.hasTrack
                source: "media-playback-pause"
                width: parent.width / 2
                height: width
                anchors.right: parent.right
                anchors.bottom: parent.bottom
            }
        }

        PlasmaComponents.Label {
            visible: compact.showLabel
            Layout.fillWidth: true
            Layout.alignment: Qt.AlignVCenter
            elide: Text.ElideRight
            maximumLineCount: 1
            text: Fmt.elide(root.track ? root.track.title : "",
                            Plasmoid.configuration.panelTextLength)
        }
    }
}
