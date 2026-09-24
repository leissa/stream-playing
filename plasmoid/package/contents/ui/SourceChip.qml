/* Small badge naming which service an item came from. */

import QtQuick

import org.kde.plasma.components as PlasmaComponents
import org.kde.kirigami as Kirigami

Rectangle {
    id: chip

    property string source: ""

    implicitWidth: label.implicitWidth + Kirigami.Units.smallSpacing * 2
    implicitHeight: label.implicitHeight + Kirigami.Units.smallSpacing
    radius: Kirigami.Units.cornerRadius
    visible: !!source
    color: Qt.rgba(Kirigami.Theme.highlightColor.r,
                   Kirigami.Theme.highlightColor.g,
                   Kirigami.Theme.highlightColor.b, 0.18)

    PlasmaComponents.Label {
        id: label
        anchors.centerIn: parent
        font: Kirigami.Theme.smallFont
        text: root.client.sourceName(chip.source)
    }
}
