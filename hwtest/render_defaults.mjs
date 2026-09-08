// Render a sensorbox build's packages and uci-defaults by calling the
// firmware-selector's OWN code, so the harness cannot drift from the web form.
//
// Reads a JSON job on stdin and writes JSON on stdout:
//
//   in : {recipe, common, formValues, selectedOptions, extraDefaults}
//   out: {packages: [...], defaults: "#!/bin/sh ..."}
//
// mergedPackages() and assembleDefaults() are imported from
// firmware-selector/www/js/sensorbox-recipes.js -- the same functions the
// browser calls, using the same vendored Mustache. Reimplementing the
// templating in Python was the alternative, and it would have meant a second
// source of truth for credential injection that could silently diverge.
//
// Two browser globals have to exist first:
//   * window.Mustache -- assembleDefaults() reaches for it by that name.
//   * document        -- utils.js binds document.querySelector at MODULE
//                        scope, so merely importing the chain touches it.
//                        assembleDefaults never calls $ or $$, so no-op
//                        stubs are enough.
// The globals must be set before the dynamic import() below evaluates the
// module, which is why this is not a static import.
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const SELECTOR = path.resolve(HERE, "..", "firmware-selector", "www", "js");

globalThis.document = {
  querySelector: () => null,
  querySelectorAll: () => [],
};
globalThis.window = globalThis.window || {};

// mustache.min.js is a UMD bundle. Evaluated at top level here there is no
// `module`/`exports`, so it takes its browser branch and attaches to the
// global object.
vm.runInThisContext(fs.readFileSync(path.join(SELECTOR, "vendor", "mustache.min.js"), "utf8"));
const Mustache = globalThis.Mustache || globalThis.window.Mustache;
if (!Mustache) {
  console.error("could not load Mustache from the selector's vendor directory");
  process.exit(1);
}
globalThis.window.Mustache = Mustache;

const { mergedPackages, assembleDefaults } = await import(
  path.join(SELECTOR, "sensorbox-recipes.js")
);

const job = JSON.parse(fs.readFileSync(0, "utf8"));
const { recipe, common, formValues = {}, selectedOptions = {}, extraDefaults = "" } = job;

// The selector exposes each option's chosen key as a Mustache boolean so
// templates can gate sections with {{#optname_choicekey}}. Mirror that here or
// every option-gated block silently renders as empty.
const values = { ...formValues };
if (recipe && recipe.options) {
  for (const [optName, opt] of Object.entries(recipe.options)) {
    const chosen = selectedOptions[optName];
    for (const choiceKey of Object.keys(opt.choices || {})) {
      values[`${optName}_${choiceKey}`] = choiceKey === chosen;
    }
  }
}

process.stdout.write(JSON.stringify({
  packages: mergedPackages(common, recipe, selectedOptions),
  defaults: assembleDefaults(common, recipe, values, extraDefaults),
  mustacheVersion: Mustache.version || null,
}, null, 2));
