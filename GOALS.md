sensorbox is an open source software solution that allows anyone to easily create their own ethernet or Wi-Fi hardware that acts as a persistent internet and network experience probe.

*Opinionated.* sensorbox strives to be a robust, secure, and reliable leave-behind network experience and network telemetry sensor.

*Recipe- and community-driven.* Rather than providing generic software you hope will run on your device, sensorbox is powered by recipes that define mixed-and-matched hardware pre-validated by the community.

*Robust.* sensorbox devices are designed to run for years without intervention, using eMMC when available, employing read-only file systems, minimizing writes to disk, shipping pre-configured images, and supporting remote upgrades. sensorbox does not use vendor firmware.

* The sensors will be built on OpenWrt.
* The solution will err towards being opinionated rather than extremely configurable.
* sensorbox should build on existing tools where appropriate.
* sensorbox should be a containerized system that is easy to run on macOS, Windows, or Linux.
* sensorbox should be run locally and we don't want to use the public OpenWrt firmware selector + ASU as we will bake sensitive information such as Wi-Fi credentials into the images via uci-defaults.
* By principle/design, these devices should be "set it and forget it". You flash the device and it runs. If you need to reconfigure it, easier to re-flash it than ssh into it and change settings. These devices are "ephemeral".
* The Wi-Fi and ethernet interfaces should act as clients (e.g. DHCP should be disabled).
* The Wi-Fi interfaces should act like normal clients.