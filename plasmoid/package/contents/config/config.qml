import QtQuick

import org.kde.plasma.configuration

ConfigModel {
    ConfigCategory {
        name: i18n("Music Servers")
        icon: "network-server-database"
        source: "config/ConfigServers.qml"
    }
    ConfigCategory {
        name: i18n("General")
        icon: "configure"
        source: "config/ConfigGeneral.qml"
    }
}
