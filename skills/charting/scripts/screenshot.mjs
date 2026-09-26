/**
 * screenshot.mjs — render a generated chart HTML file to a PNG.
 *
 * Usage:
 *   node scripts/screenshot.mjs <html> <out.png> \
 *     --width 720 --height 420 --scale 2 --selector '#chart-root' \
 *     [--transparent] [--timeout 20000]
 *   node scripts/screenshot.mjs --check
 *
 * It launches headless Chromium with Playwright, waits until the bundle has
 * mounted (`window.__chartReady`) and the SVG is present, then screenshots one
 * element at the requested CSS size × device scale. Animations are disabled in
 * the boot module, so the image is deterministic. Output is one JSON envelope.
 */
import fs from "node:fs";
import { dirname, resolve } from "node:path";
import { pathToFileURL } from "node:url";
import { chromium } from "playwright";

const CHECK_ARG = "--check";

function emit(payload) {
  process.stdout.write(JSON.stringify(payload) + "\n");
}

function fail(code, message, exitCode = 1) {
  emit({ ok: false, error: { code, message } });
  process.exit(exitCode);
}

function parseArgs(argv) {
  const options = {
    html: null,
    out: null,
    width: 720,
    height: 420,
    scale: 2,
    selector: "#chart-root",
    transparent: false,
    timeout: 20000,
    check: false,
  };
  const positional = [];
  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index];
    if (arg === CHECK_ARG) {
      options.check = true;
    } else if (arg === "--transparent") {
      options.transparent = true;
    } else if (arg.startsWith("--")) {
      const name = arg.slice(2);
      const value = argv[index + 1];
      if (value === undefined || value.startsWith("--")) {
        fail("usage", `missing value for ${arg}`, 2);
      }
      index += 1;
      if (["width", "height", "scale", "timeout"].includes(name)) {
        options[name] = Number(value);
        if (!Number.isFinite(options[name]) || options[name] <= 0) {
          fail("usage", `${arg} must be a positive number`, 2);
        }
      } else if (name === "selector") {
        options.selector = value;
      } else {
        fail("usage", `unknown flag ${arg}`, 2);
      }
    } else {
      positional.push(arg);
    }
  }
  if (!options.check) {
    if (positional.length !== 2) {
      fail("usage", "expected <html> <out.png>", 2);
    }
    [options.html, options.out] = positional;
  }
  return options;
}

async function check() {
  let executable;
  try {
    executable = chromium.executablePath();
  } catch (error) {
    fail("dependency_missing", `Playwright could not resolve Chromium: ${error.message}`);
  }
  if (!executable || !fs.existsSync(executable)) {
    fail(
      "dependency_missing",
      `Chromium is not installed (looked for ${executable}); run: npx playwright install chromium`
    );
  }
  emit({
    ok: true,
    command: "screenshot.check",
    data: { playwright: true, chromium: true, executable },
  });
}

async function render(options) {
  const htmlPath = resolve(options.html);
  const outPath = resolve(options.out);
  if (!fs.existsSync(htmlPath)) {
    fail("not_found", `HTML file not found: ${htmlPath}`);
  }

  const browser = await chromium.launch({
    args: ["--allow-file-access-from-files", "--force-color-profile=srgb", "--hide-scrollbars"],
  });
  try {
    const context = await browser.newContext({
      viewport: { width: options.width, height: options.height },
      deviceScaleFactor: options.scale,
      reducedMotion: "reduce",
    });
    const page = await context.newPage();
    page.on("pageerror", (error) => {
      process.stderr.write(`page error: ${error.message}\n`);
    });
    await page.goto(pathToFileURL(htmlPath).href, { waitUntil: "load", timeout: options.timeout });
    await page.waitForFunction("window.__chartReady === true", null, { timeout: options.timeout });
    await page.evaluate("document.fonts ? document.fonts.ready : true");
    await page.waitForSelector(`${options.selector} svg`, { state: "attached", timeout: options.timeout });
    const element = await page.$(options.selector);
    if (!element) {
      fail("render_failed", `selector ${options.selector} was not found`);
    }
    const box = await element.boundingBox();
    if (!box) {
      fail("render_failed", `selector ${options.selector} has no layout box`);
    }
    if (box.width + 0.5 < options.width || box.height + 0.5 < options.height) {
      process.stderr.write(
        `warning: ${options.selector} is ${box.width}x${box.height}, smaller than ${options.width}x${options.height}\n`
      );
    }
    const buffer = await element.screenshot({ type: "png", omitBackground: options.transparent });
    fs.mkdirSync(dirname(outPath), { recursive: true });
    fs.writeFileSync(outPath, buffer);
    emit({
      ok: true,
      command: "screenshot",
      data: {
        html: htmlPath,
        out: outPath,
        bytes: buffer.length,
        width: options.width,
        height: options.height,
        scale: options.scale,
        selector: options.selector,
        transparent: options.transparent,
      },
    });
  } catch (error) {
    fail("render_failed", error && error.message ? error.message : String(error));
  } finally {
    await browser.close();
  }
}

const options = parseArgs(process.argv.slice(2));
if (options.check) {
  await check();
} else {
  await render(options);
}
