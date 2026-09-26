/**
 * build.mjs — bundle the browser render helper with esbuild.
 *
 * `boot/chart-boot.js` plus `react`, `react-dom`, and `recharts` are bundled
 * into a single IIFE at `vendor/chart-bundle.js`. The generated HTML loads that
 * file from disk, so rendering works offline and without a module server.
 *
 * Run from anywhere: `node scripts/build.mjs`. Re-run after changing the boot
 * module or upgrading a dependency.
 */
import { build } from "esbuild";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { statSync } from "node:fs";

const here = dirname(fileURLToPath(import.meta.url));
const outfile = join(here, "vendor", "chart-bundle.js");

const result = await build({
  entryPoints: [join(here, "boot", "chart-boot.js")],
  outfile,
  bundle: true,
  format: "iife",
  platform: "browser",
  target: ["chrome110"],
  jsx: "transform",
  minify: true,
  legalComments: "none",
  define: {
    "process.env.NODE_ENV": '"production"',
  },
  logLevel: "warning",
  metafile: true,
});

const { size } = statSync(outfile);
const inputs = Object.keys(result.metafile.inputs).length;
console.log(
  JSON.stringify({
    ok: true,
    command: "build",
    data: { out: outfile, bytes: size, inputs },
  })
);
