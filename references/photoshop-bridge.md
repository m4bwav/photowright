# The Photoshop bridge (and Affinity, Photopea)

Checked 2026-11-16. Reading only: nothing was installed or run. The bridge is optional; no photowright feature may depend on it.

## Photoshop

| Route | How it is driven from outside | Needs | Status | Source |
|---|---|---|---|---|
| COM (Windows) | `win32com.client.Dispatch('Photoshop.Application')` from Python, or VBScript/JScript; can call `DoJavaScript` to run JSX | Windows, desktop Photoshop installed and licensed (Creative Cloud subscription) | Legacy; works in current versions per community, but a user reports a Python-to-COM script that broke between 2024 and 2025 | https://www.tech-artists.org/t/how-to-use-photoshops-com-interface-with-python/3339 , https://community.adobe.com/t5/photoshop-developers-discussions/error-when-running-jsx-es-file-via-python-in-photoshop-2025-but-working-in-photoshop-2024/td-p/15237178 |
| ExtendScript (.jsx) | `Photoshop.exe script.jsx`, COM `DoJavaScript`, or AppleScript `do javascript` on macOS | desktop Photoshop | Legacy (ES3), still runs; UXP is the replacement. No official end date found | https://cgtweb1.tech.purdue.edu/courses/cgt215/Private/Tutorials/Photoshop_CS4_Scripting_Guide.pdf |
| UXP plugin / UXP script (.psjs) | Code runs inside Photoshop; to drive from outside, a plugin opens a socket to a local proxy (the adb-mcp pattern) | Photoshop 2022 (v23)+, UXP Developer Tool to load an unsigned plugin | Current, Adobe's platform; `batchPlay` reaches any action descriptor | https://developer.adobe.com/photoshop/uxp/ , https://github.com/mikechambers/adb-mcp |
| Photoshop API v2 (Firefly Services, cloud) | REST: send PSD or images from cloud storage, run actions, edit layers, text, smart objects, remove background, run UXP scripts; files up to 5 GB | Adobe Developer Console project, OAuth server-to-server credentials, enterprise Firefly Services entitlement (community reports it is enterprise-only and priced per call) | v2 GA; v1 deprecated 2026-04-20, end of life 2026-08-31 | https://developer.adobe.com/firefly-services/docs/photoshop/getting-started/v2-ga/ , https://developer.adobe.com/firefly-services/docs/photoshop/getting-started/deprecation-announcement/ , https://community.adobe.com/t5/adobe-firefly-discussions/best-adobe-plan-for-using-firefly-api-amp-amp-photoshop-api/m-p/15153403 |

### Existing Photoshop MCP servers

| Project | Route | Licence | Notes | Source |
|---|---|---|---|---|
| mikechambers/adb-mcp | MCP server + Node command proxy + UXP plugin (Photoshop, Premiere, InDesign) | MIT | By an Adobe developer advocate; cross-platform; proof-of-concept quality per author's blog | https://github.com/mikechambers/adb-mcp , https://www.mikechambers.com/blog/post/2025-06-06-exploring-ai-integration-with-adobe-photoshop-indesign-and-premiere-pro/ |
| loonghao/photoshop-python-api-mcp-server | COM via photoshop-python-api | MIT | Windows only; `pip install photoshop-mcp-server` | https://github.com/loonghao/photoshop-python-api-mcp-server , https://pypi.org/project/photoshop-mcp-server/0.1.1/ |
| alisaitteke/photoshop-mcp | TypeScript, `npx -y @alisaitteke/photoshop-mcp` | not checked | Photoshop must run locally | https://mcpservers.org/servers/alisaitteke/photoshop-mcp |
| chandrahas455/psmcp | win32com | not checked | Windows | https://awesome.ecosyste.ms/projects/github.com%2Fchandrahas455%2Fpsmcp-mcp-server-for-photoshop |

Recommendation: if a bridge is built, use one small stdlib path: on Windows write a JSX file and run it through COM `DoJavaScript` (no plugin install), with the file exchange as PSD/PNG from photowright's own writer. UXP via adb-mcp is the forward-compatible option but needs a plugin loaded by hand. The cloud API is out of reach for an individual (enterprise entitlement).

## Affinity (Canva)

- Affinity 3.3 (2026-09-15) added a Scripting Studio: JavaScript that automates repetitive tasks across vector, pixel and layout documents; it cannot add tools. https://www.cgchannel.com/2026/09/canva-releases-affinity-3-3/ , https://www.creativebloq.com/design/design-software/affinity-3-3-shows-that-canva-is-serious-about-taking-on-adobe
- 3.2 (2026-04) shipped a Claude connector that writes reusable scripts, free in beta. https://digitalproduction.com/2026/04/28/canva-ships-affinity-3-2/
- A community skill says the app serves its scripting SDK docs locally when the AI connector is on; not confirmed in Canva docs. https://www.skills.sh/jablonkai/skills/affinity
- Needs: Affinity installed (free with a Canva account since 3.0 *unverified*). No documented way found to run a script headless from the command line. Treat as a manual-trigger bridge only.

## Photopea

- Scripting follows Adobe's Photoshop CC 2015 JavaScript interface; `app.echoToOE()` returns strings to the outer page. https://www.photopea.com/learn/scripts
- Live Messaging: the host page embeds Photopea in an iframe and `postMessage`s script strings and file buffers; Photopea replies with results and exported files. https://www.photopea.com/api/live
- Existing MCP: attalla1/photopea-mcp-server drives a browser tab over a WebSocket bridge, including arbitrary scripts. https://github.com/attalla1/photopea-mcp-server
- Needs: a browser and network to photopea.com; free tier shows ads; commercial embedding needs a paid plan per Photopea's API page *unverified*. Useful as a free PSD verifier (open our PSD, export PNG, diff).
