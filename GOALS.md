I want us to make an open source software solution that allows anyone to easily create their own ethernet or Wi-Fi hardware "Orb" that links to their Orb account and allows them to have a persistent internet experience "probe"

* The probes will be built on OpenWrt
* The first two devices I want to support are: NanoPi R5C (ethernet + Wi-Fi) and Radxa E20C (ethernet-only)
* The solution will err towards being opinionated rather than extremely configurable
* My thought is that we can extend the firmware-selector-openwrt-org (included in this folder -- we should probably fork it) to create a web interface for selecting the device, installing necessary packages (e.g. Intel BE200 Wi-Fi driver), etc. We want to produce images that can be put on SD cards to flash devices.
* Orb will also need to be installed (https://orb.net/docs/setup-sensor/linux/openwrt)
* I am thinking we will also want to use ASU (also in this folder). It is GPL-2.0 so we shouldn't modify it. Three reasons to use it: 1. We want Orb baked into the image, but it isn't in public OpenWrt repos and 2. To support some devices, we may need to compile branches/forks while we wait for kernel patches/openwrt merges 3. we may want to use proprietary or compiled from source Wi-Fi drivers
* This should be a containerized system that is easy to run on macOS, Windows, or Linux. So we should be able to do something like docker-compose up and the extended firmware selector web interface, ASU, etc all run and you can interact with the system via the web interface
* Another reason that we want this run locally and we don't want to use the public openwrt firmware selector + ASU is we will bake sensitive information such as Wi-Fi credentials into the images via uci-defaults
* By principle/design, these devices should be "set it and forget it". You flash the device and it runs. If you need to reconfigure it, easier to re-flash it than ssh into it and change settings. These devices are "ephemeral"
* Some things should be configurable in the web interface:
** Supported Wi-Fi card
** Wi-Fi network security, SSID, password
** ORB_DEPLOYMENT_TOKEN
** root password
** configure device to select Wi-Fi band automatically or only connect to 2.4 or 5 or 6 GHz
** maybe we want to be able to configure the local ASU server and some automated mechanism to periodically perform upgrades for security purposes? (save for last to implement, but consider as we build)
* Default behaviors
** The Wi-Fi and ethernet connections should act as clients (e.g. DHCP should be disabled)
** The Wi-Fi should act like a normal client by default, not be attached to a specific band