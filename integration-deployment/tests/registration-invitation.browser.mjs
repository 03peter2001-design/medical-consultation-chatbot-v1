import http from "node:http";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { spawn } from "node:child_process";

const repositoryRoot = path.resolve(import.meta.dirname, "..", "..");
const assetPath = path.join(repositoryRoot, "integration-deployment", "iis", "registration-invitation.js");
const ehisWwwroot = process.env.EHIS_WWWROOT || "D:/ehis/eHIS/wwwroot";
const ej2Path = path.join(ehisWwwroot, "ej2", "ej2.min.js");
const bootstrapPath = path.join(ehisWwwroot, "lib", "bootstrap", "bootstrap.min.css");
const chromePath = "C:/Program Files/Google/Chrome/Application/chrome.exe";
const port = 43341;
const cdpPort = 43342;
const origin = `http://127.0.0.1:${port}`;
const outputDirectory = path.join(os.tmpdir(), "b01-registration-invitation-qa");
const requestLog = [];

function sendFile(response, filePath, contentType) {
    const body = fs.readFileSync(filePath);
    response.writeHead(200, { "Content-Type": contentType, "Content-Length": body.length });
    response.end(body);
}

const fixture = `<!doctype html>
<html lang="zh-Hant"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>B01 掛號 QR 驗收</title><link rel="stylesheet" href="/bootstrap.css">
<style>body{background:#f4f7fb}.qa-shell{max-width:760px;margin:32px auto}.card{box-shadow:0 8px 28px #1e3a5f18}</style></head>
<body><main class="qa-shell"><div id="divReg"><div class="card mb-2"><div class="card-body">
<h1 class="h4">B01 掛號受理</h1><p class="text-success mb-0">掛號成功（測試掛號流水號 47）</p>
</div></div></div><input type="hidden" name="__RequestVerificationToken" value="csrf-browser-qa"></main>
<script>window.BaseSettings={RootURL:""};</script><script src="/ej2.js"></script>
<script src="/registration-invitation.js"></script>
<script>document.dispatchEvent(new CustomEvent("ehis:registration-succeeded",{detail:{regSno:47}}));</script>
</body></html>`;

const server = http.createServer((request, response) => {
    let raw = "";
    request.on("data", (chunk) => { raw += chunk; });
    request.on("end", () => {
        if (request.url === "/") {
            response.writeHead(200, { "Content-Type": "text/html; charset=utf-8" });
            response.end(fixture);
            return;
        }
        if (request.url === "/registration-invitation.js") return sendFile(response, assetPath, "text/javascript; charset=utf-8");
        if (request.url === "/ej2.js") return sendFile(response, ej2Path, "text/javascript; charset=utf-8");
        if (request.url === "/bootstrap.css") return sendFile(response, bootstrapPath, "text/css; charset=utf-8");
        if (request.url === "/AiConsult/RegistrationInvitations" && request.method === "POST") {
            requestLog.push({ headers: request.headers, body: JSON.parse(raw) });
            const body = JSON.stringify({
                invite_id: "browser-qa",
                public_url: `${origin}/patient/#token=browser-qa-token`,
                expires_at: "2026-09-11T16:00:00+08:00",
                status: "active"
            });
            response.writeHead(200, { "Content-Type": "application/json", "Content-Length": Buffer.byteLength(body) });
            response.end(body);
            return;
        }
        response.writeHead(404);
        response.end();
    });
});

class CdpClient {
    constructor(url) {
        this.socket = new WebSocket(url);
        this.sequence = 0;
        this.pending = new Map();
        this.events = [];
    }
    async open() {
        await new Promise((resolve, reject) => { this.socket.onopen = resolve; this.socket.onerror = reject; });
        this.socket.onmessage = (event) => {
            const message = JSON.parse(event.data);
            if (!message.id) { this.events.push(message); return; }
            const pending = this.pending.get(message.id);
            this.pending.delete(message.id);
            message.error ? pending.reject(new Error(message.error.message)) : pending.resolve(message.result);
        };
    }
    command(method, params = {}) {
        const id = ++this.sequence;
        return new Promise((resolve, reject) => {
            this.pending.set(id, { resolve, reject });
            this.socket.send(JSON.stringify({ id, method, params }));
        });
    }
    close() { this.socket.close(); }
}

async function evaluate(client, expression) {
    const result = await client.command("Runtime.evaluate", { expression, awaitPromise: true, returnByValue: true });
    if (result.exceptionDetails) throw new Error(result.exceptionDetails.text);
    return result.result.value;
}

async function waitFor(client, expression) {
    const deadline = Date.now() + 15000;
    while (Date.now() < deadline) {
        if (await evaluate(client, expression)) return;
        await new Promise((resolve) => setTimeout(resolve, 100));
    }
    throw new Error(`Timed out waiting for: ${expression}`);
}

async function main() {
    fs.mkdirSync(outputDirectory, { recursive: true });
    await new Promise((resolve) => server.listen(port, "127.0.0.1", resolve));
    const profile = fs.mkdtempSync(path.join(os.tmpdir(), "b01-qr-chrome-"));
    const chrome = spawn(chromePath, [
        `--remote-debugging-port=${cdpPort}`,
        "--remote-allow-origins=*",
        `--user-data-dir=${profile}`,
        "--headless=new", "--disable-gpu", "--no-first-run", "--disable-background-networking",
        "--window-size=1100,900", "about:blank"
    ], { stdio: "ignore", windowsHide: true });
    let client;
    try {
        let devtoolsReady = false;
        for (let index = 0; index < 100; index += 1) {
            try {
                if ((await fetch(`http://127.0.0.1:${cdpPort}/json/version`, { signal: AbortSignal.timeout(500) })).ok) {
                    devtoolsReady = true;
                    break;
                }
            } catch (_error) { }
            await new Promise((resolve) => setTimeout(resolve, 100));
        }
        if (!devtoolsReady) throw new Error("Chrome DevTools did not become ready.");
        const target = await (await fetch(`http://127.0.0.1:${cdpPort}/json/new?${encodeURIComponent(origin)}`, {
            method: "PUT",
            signal: AbortSignal.timeout(3000)
        })).json();
        client = new CdpClient(target.webSocketDebuggerUrl);
        await client.open();
        await client.command("Page.enable");
        await client.command("Runtime.enable");
        await waitFor(client, `document.querySelector('#ai-registration-invitation [data-role="qr"] svg') && document.body.innerText.includes('QR Code 已建立')`);

        const state = await evaluate(client, `(() => {
            const panel=document.querySelector('#ai-registration-invitation');
            const qr=panel.querySelector('[data-role="qr"]');
            const rect=qr.getBoundingClientRect();
            return {visible:!panel.hidden, status:panel.querySelector('[data-role="status"]').textContent,
                link:panel.querySelector('[data-role="link"]').href, svg:!!qr.querySelector('svg'),
                overflow:document.documentElement.scrollWidth>innerWidth,
                clip:{x:rect.x,y:rect.y,width:rect.width,height:rect.height,scale:1}};
        })()`);
        const full = await client.command("Page.captureScreenshot", { format: "png" });
        fs.writeFileSync(path.join(outputDirectory, "b01-registration-qr.png"), Buffer.from(full.data, "base64"));
        const qr = await client.command("Page.captureScreenshot", { format: "png", clip: state.clip });
        fs.writeFileSync(path.join(outputDirectory, "registration-qr.png"), Buffer.from(qr.data, "base64"));
        const result = {
            state: { visible: state.visible, status: state.status, link: state.link, svg: state.svg, overflow: state.overflow },
            request: requestLog[0],
            consoleErrors: client.events.filter((event) => event.method === "Runtime.exceptionThrown").length,
            screenshots: [path.join(outputDirectory, "b01-registration-qr.png"), path.join(outputDirectory, "registration-qr.png")]
        };
        fs.writeFileSync(path.join(outputDirectory, "result.json"), JSON.stringify(result, null, 2));
        console.log(JSON.stringify(result, null, 2));
        if (!state.visible || !state.svg || state.overflow || result.consoleErrors || requestLog.length !== 1 ||
            requestLog[0].body.regSno !== 47 || requestLog[0].headers.requestverificationtoken !== "csrf-browser-qa") {
            throw new Error("Browser acceptance assertions failed.");
        }
    } finally {
        client?.close();
        server.close();
        chrome.kill();
    }
}

main().catch((error) => { console.error(error.stack); process.exitCode = 1; });
