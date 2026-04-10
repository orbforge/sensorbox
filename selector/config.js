/* exported config */

// orb-forge deployment config for the firmware selector.
// This file is mounted on top of firmware-selector/www/config.js at runtime
// by compose.yaml, so the fork stays pristine for actual feature changes.

var config = {
  show_help: true,

  // Pulled from the upstream OpenWrt CDN — the selector needs .versions.json
  // and .overview.json catalogs to enumerate devices. Customized images still
  // go through asu_url below.
  image_url: "https://downloads.openwrt.org",

  // Empty = same-origin. The selector's nginx reverse-proxies /api/ and
  // /store/ to asu-server, so the browser never crosses origins.
  asu_url: "",

  // Orb devices are "set it and forget it" — no LuCI, no admin UI. Override
  // the upstream default of ["luci", "luci-app-attendedsysupgrade"].
  asu_extra_packages: [],

  info_url: "https://openwrt.org/start?do=search&id=toh&q={title} @toh",
};
