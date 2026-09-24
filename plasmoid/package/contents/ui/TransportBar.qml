/* Seek bar plus the transport buttons; always visible, whatever tab is open. */

import QtQuick
import QtQuick.Layouts

import org.kde.plasma.components as PlasmaComponents
import org.kde.kirigami as Kirigami

import "Formatting.js" as Fmt

ColumnLayout {
    id: transport

    readonly property var client: root.client
    readonly property var playback: client.playback
    readonly property real duration: playback.duration || 0
    readonly property bool canSeek:
        client.linked && !!client.track
        && (playback.capabilities ? playback.capabilities.seek !== false : true)

    spacing: Kirigami.Units.smallSpacing

    RowLayout {
        Layout.fillWidth: true
        spacing: Kirigami.Units.smallSpacing

        PlasmaComponents.Label {
            text: Fmt.duration(client.displayPosition)
            font: Kirigami.Theme.smallFont
            opacity: 0.8
        }

        PlasmaComponents.Slider {
            id: seekSlider
            Layout.fillWidth: true
            enabled: transport.canSeek && transport.duration > 0
            from: 0
            to: Math.max(transport.duration, 0.001)
            // While dragging, the handle owns the value; otherwise the daemon does.
            value: client.displayPosition

            onPressedChanged: {
                client.scrubbing = pressed;
                if (!pressed) {
                    client.seek(value);
                }
            }
            onMoved: client.displayPosition = value
        }

        PlasmaComponents.Label {
            text: Fmt.duration(transport.duration)
            font: Kirigami.Theme.smallFont
            opacity: 0.8
        }
    }

    RowLayout {
        Layout.fillWidth: true
        spacing: 0

        PlasmaComponents.ToolButton {
            icon.name: "media-playlist-shuffle"
            checkable: true
            checked: playback.shuffle === true
            enabled: client.linked
            display: PlasmaComponents.AbstractButton.IconOnly
            text: i18n("Shuffle")
            onClicked: client.toggleShuffle()

            PlasmaComponents.ToolTip.text: text
            PlasmaComponents.ToolTip.visible: hovered
            PlasmaComponents.ToolTip.delay: Kirigami.Units.toolTipDelay
        }

        Item { Layout.fillWidth: true }

        PlasmaComponents.ToolButton {
            icon.name: "media-skip-backward"
            enabled: client.linked && playback.canPrevious
            display: PlasmaComponents.AbstractButton.IconOnly
            text: i18n("Previous Track")
            onClicked: client.previous()
        }

        PlasmaComponents.ToolButton {
            icon.name: playback.status === "playing"
                       ? "media-playback-pause" : "media-playback-start"
            enabled: client.linked
                     && (!!client.track || playback.queueLength > 0)
            display: PlasmaComponents.AbstractButton.IconOnly
            text: playback.status === "playing" ? i18n("Pause") : i18n("Play")
            onClicked: client.playPause()
        }

        PlasmaComponents.ToolButton {
            icon.name: "media-playback-stop"
            enabled: client.linked && playback.status !== "stopped"
            display: PlasmaComponents.AbstractButton.IconOnly
            text: i18n("Stop")
            onClicked: client.stop()
        }

        PlasmaComponents.ToolButton {
            icon.name: "media-skip-forward"
            enabled: client.linked && playback.canNext
            display: PlasmaComponents.AbstractButton.IconOnly
            text: i18n("Next Track")
            onClicked: client.next()
        }

        Item { Layout.fillWidth: true }

        PlasmaComponents.ToolButton {
            icon.name: playback.repeat === "one"
                       ? "media-playlist-repeat-song" : "media-playlist-repeat"
            checkable: true
            checked: playback.repeat !== "none"
            enabled: client.linked
            display: PlasmaComponents.AbstractButton.IconOnly
            text: playback.repeat === "one" ? i18n("Repeat Track")
                : playback.repeat === "all" ? i18n("Repeat Queue")
                                            : i18n("No Repeat")
            onClicked: client.cycleRepeat()

            PlasmaComponents.ToolTip.text: text
            PlasmaComponents.ToolTip.visible: hovered
            PlasmaComponents.ToolTip.delay: Kirigami.Units.toolTipDelay
        }
    }

    RowLayout {
        Layout.fillWidth: true
        spacing: Kirigami.Units.smallSpacing

        PlasmaComponents.ToolButton {
            icon.name: playback.volume <= 0.001 ? "audio-volume-muted"
                     : playback.volume < 0.35   ? "audio-volume-low"
                     : playback.volume < 0.75   ? "audio-volume-medium"
                                                : "audio-volume-high"
            display: PlasmaComponents.AbstractButton.IconOnly
            enabled: client.linked
            text: i18n("Mute")
            property real restoreTo: 0.5
            onClicked: {
                if (playback.volume > 0.001) {
                    restoreTo = playback.volume;
                    client.setVolume(0);
                } else {
                    client.setVolume(restoreTo);
                }
            }
        }

        PlasmaComponents.Slider {
            Layout.fillWidth: true
            enabled: client.linked
            from: 0
            to: 1
            value: playback.volume || 0
            onMoved: client.setVolume(value)
        }
    }
}
