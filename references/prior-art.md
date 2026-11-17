# Prior art: image-editing and vectorizing skills, plugins and MCP servers

Checked 2026-11-16. Stars and last push from the GitHub API that day; licences from the repo's licence file as GitHub reports it.

## Finding

No existing project does what photowright plans: an agent-first, own-code, command-line Photoshop substitute with layered files and a licence ledger. What exists falls into four groups: bridges to a host editor (Photoshop, GIMP, Photopea), thin ImageMagick wrappers, single-purpose vectorizers, and image *generation* MCP servers (out of scope). Nothing found for Krita.

## Bridges to an editor

| Project | Stars | Last push | Licence | What it does well | Source |
|---|---|---|---|---|---|
| alisaitteke/photoshop-mcp | 897 | 2026-11-14 | MIT | Most-starred Photoshop MCP; npx install; layer, text, filter tools | https://github.com/alisaitteke/photoshop-mcp |
| mikechambers/adb-mcp | 750 | 2026-07-08 | MIT | UXP plugin + proxy pattern, cross-platform, Photoshop and Premiere; clean tool list to borrow names from | https://github.com/mikechambers/adb-mcp |
| loonghao/photoshop-python-api-mcp-server | 353 | 2026-10-17 | MIT | Python, COM, Windows only; shows the COM route works from Python | https://github.com/loonghao/photoshop-python-api-mcp-server |
| gimp-mcp/gimp-mcp | 294 | 2026-11-16 | GPL-3.0 | GIMP 3 plug-in over a socket; layers, selections, filters, arbitrary Python-Fu | https://github.com/gimp-mcp/gimp-mcp |
| libreearth/gimp-mcp | 126 | 2025-03-18 | GPL-3.0 | Older GIMP bridge; open, resize, crop, text, batch resize | https://github.com/libreearth/gimp-mcp |
| attalla1/photopea-mcp-server | 55 | 2026-11-03 | MIT | Photopea in a browser over WebSocket; exposes a run-script tool; free PSD round-trips without Adobe | https://github.com/attalla1/photopea-mcp-server |

Borrow: adb-mcp's split (agent-facing tool names separate from the host driver) and the photopea server's "run script" escape hatch. Avoid GPL code in our tree (reference only).

## ImageMagick and general image tools

| Project | Stars | Last push | Licence | Notes | Source |
|---|---|---|---|---|---|
| AeyeOps/mcp-imagemagick | 15 | 2025-06-18 | MIT | Conversion via ImageMagick and darktable | https://github.com/AeyeOps/mcp-imagemagick |
| ncipollo/magick-mcp | 3 | 2026-10-22 | MIT | Rust; raw `magick` passthrough plus saved "functions" (named reusable command recipes): worth borrowing as recipes | https://github.com/ncipollo/magick-mcp |
| Yoshino-Yukitaro/imagemagick_mcp_server | 5 | 2025-04-10 | none | small | https://github.com/Yoshino-Yukitaro/imagemagick_mcp_server |
| mcp-image-tools (PyPI) | n/a | n/a | MIT | read, resize, crop, convert, base64 return | https://pypi.org/project/mcp-image-tools |

## Skills

| Skill | Licence | Notes | Source |
|---|---|---|---|
| ComposioHQ awesome-claude-skills `image-enhancer` | repo has no licence file (GitHub reports none) | Prompt-only skill for sharpening screenshots and low-res assets; 79,670 stars on the list repo, not the skill | https://github.com/ComposioHQ/awesome-claude-skills , https://tessl.io/registry/skills/github/ComposioHQ/awesome-claude-skills/image-enhancer |
| sickn33 `photopea-embedded-editor` | not checked | How to embed Photopea and use photopea.js | https://claude-plugins.dev/skills/@sickn33/antigravity-awesome-skills/photopea-embedded-editor |
| jablonkai `affinity` | not checked | Drives Affinity 3 scripting SDK | https://www.skills.sh/jablonkai/skills/affinity |
| photofresco (Hermes) | not checked | MCP server bundled with an Agent Skill for image editing | https://hermes-agent.nousresearch.com/docs/plugins/photofresco |
| anthropics/skills | repo licence per skill | No image-editing skill found in the official repo listing this pass (canvas/art skills generate, not edit) *unverified* | https://github.com/anthropics/skills |

## Vectorizing

| Project | Licence | Notes | Source |
|---|---|---|---|
| visioncortex/vtracer | MIT, 7,547 stars, pushed 2026-11-13 | Colour raster to SVG; Python wheel; the engine most vectorize MCPs wrap | https://github.com/visioncortex/vtracer |
| pic2vector-mcp | not checked | vtracer via npx, local | https://mcpservers.org/servers/pic2vector/pic2vector-mcp |
| @pulsemcp/svg-tracer-mcp-server | not checked | potrace; builds a mask from alpha first | https://www.pkgstats.com/pkg:@pulsemcp/svg-tracer-mcp-server |
| img2svg (Rust crate) | not checked | CLI + MCP; argues against ImageMagick/potrace for colour | https://docs.rs/crate/img2svg/0.1.8 |
| image2svg-mcp (PyPI) | Apache-2.0 | single convert tool | https://pypi.org/project/image2svg-mcp/ |
| ujo78/imagetosvg-mcp | not checked | also inspects, edits, renders SVG | https://glama.ai/mcp/servers/ujo78/imagetosvg-mcp |
| SVG.new hosted MCP | proprietary, account, 3 free vectorizations a day | vectorize, recolor, simplify, background removal | https://mcpservers.org/servers/svg-new-mcp |

## What to borrow

1. Tool vocabulary in Photoshop terms (adb-mcp, photoshop-mcp) so agents trained on Photoshop language map directly.
2. Named, saved command recipes (magick-mcp "functions").
3. An escape hatch to run raw scripts on a bridge (photopea, gimp-mcp).
4. vtracer for colour vectorizing (MIT); potrace (GPL-2) only as an external binary.
5. Gap to fill: none of these write layered files themselves, record licences, or work without a host app.
