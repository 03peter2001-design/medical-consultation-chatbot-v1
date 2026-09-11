(function (global) {
    "use strict";

    const EVENT_NAME = "ehis:registration-succeeded";
    const ENDPOINT = "/AiConsult/RegistrationInvitations";

    class InvitationRequestError extends Error {
        constructor(status, message) {
            super(message);
            this.name = "InvitationRequestError";
            this.status = status;
        }
    }

    function normalizeRegSno(value) {
        const regSno = Number(value);
        if (!Number.isSafeInteger(regSno) || regSno <= 0) {
            throw new TypeError("A positive registration number is required.");
        }
        return regSno;
    }

    function isLoopback(hostname) {
        return hostname === "localhost" || hostname === "127.0.0.1" || hostname === "::1";
    }

    function normalizePublicUrl(rawUrl, locationLike) {
        if (typeof rawUrl !== "string" || rawUrl.trim() === "") {
            throw new InvitationRequestError(502, "Invitation response did not contain a patient URL.");
        }

        let url;
        try {
            url = new URL(rawUrl);
        } catch (_error) {
            throw new InvitationRequestError(502, "Invitation response contained an invalid patient URL.");
        }

        const locationHost = locationLike && locationLike.hostname;
        const loopbackDevelopment = url.protocol === "http:" && isLoopback(url.hostname) && isLoopback(locationHost);
        if (url.protocol !== "https:" && !loopbackDevelopment) {
            throw new InvitationRequestError(502, "Invitation response contained a non-HTTPS patient URL.");
        }
        return url.href;
    }

    function responseMessage(status) {
        if (status === 400) return "掛號已完成，但邀請資料格式不正確。";
        if (status === 403) return "掛號已完成，但目前帳號沒有建立這筆掛號邀請的權限。";
        if (status === 404) return "掛號已完成，但這筆掛號已逾時、已取消，或不符合建立邀請的條件。";
        if (status === 502 || status === 503) return "掛號已完成，但智慧問診服務目前無法連線，請稍後重試。";
        return "掛號已完成，但 QR Code 建立失敗，請稍後重試。";
    }

    async function requestInvitation(value, options) {
        const settings = options || {};
        const regSno = normalizeRegSno(value);
        const fetchImpl = settings.fetchImpl || global.fetch;
        if (typeof fetchImpl !== "function") {
            throw new InvitationRequestError(0, "Fetch is unavailable.");
        }

        const rootUrl = typeof settings.rootUrl === "string"
            ? settings.rootUrl.replace(/\/$/, "")
            : "";
        const response = await fetchImpl(rootUrl + ENDPOINT, {
            method: "POST",
            credentials: "same-origin",
            cache: "no-store",
            headers: {
                "Accept": "application/json",
                "Content-Type": "application/json;charset=UTF-8",
                "RequestVerificationToken": settings.csrfToken || ""
            },
            body: JSON.stringify({ regSno: regSno }),
            signal: settings.signal
        });

        const contentType = response.headers && response.headers.get
            ? response.headers.get("content-type") || ""
            : "";
        if (!response.ok) {
            throw new InvitationRequestError(response.status, responseMessage(response.status));
        }
        if (!contentType.toLowerCase().includes("application/json")) {
            throw new InvitationRequestError(502, responseMessage(502));
        }

        let payload;
        try {
            payload = await response.json();
        } catch (_error) {
            throw new InvitationRequestError(502, responseMessage(502));
        }
        const publicUrl = normalizePublicUrl(payload.public_url || payload.publicUrl, settings.locationLike || global.location);
        return Object.assign({}, payload, { public_url: publicUrl });
    }

    function createElement(documentLike, tagName, className, textValue) {
        const element = documentLike.createElement(tagName);
        if (className) element.className = className;
        if (typeof textValue === "string") element.textContent = textValue;
        return element;
    }

    function ensurePanel(documentLike) {
        let panel = documentLike.getElementById("ai-registration-invitation");
        if (panel) return panel;

        const host = documentLike.getElementById("divReg");
        if (!host) return null;

        panel = createElement(documentLike, "section", "card border-primary mt-2 mb-2");
        panel.id = "ai-registration-invitation";
        panel.hidden = true;
        panel.setAttribute("aria-labelledby", "ai-registration-invitation-title");

        const body = createElement(documentLike, "div", "card-body p-3");
        const title = createElement(documentLike, "h2", "h5 text-primary mb-2", "患者預問診 QR Code");
        title.id = "ai-registration-invitation-title";
        const note = createElement(
            documentLike,
            "p",
            "mb-2 text-muted",
            "請交由本次掛號患者掃描。QR Code 內含一次性邀請連結，請勿轉傳。"
        );
        const status = createElement(documentLike, "p", "mb-2", "正在建立安全邀請…");
        status.dataset.role = "status";
        status.setAttribute("role", "status");
        status.setAttribute("aria-live", "polite");

        const qrHost = createElement(documentLike, "div", "d-flex justify-content-center bg-white p-2 mb-2");
        qrHost.dataset.role = "qr";
        qrHost.hidden = true;
        const link = createElement(documentLike, "a", "btn btn-outline-primary btn-sm me-2", "開啟患者問診頁");
        link.dataset.role = "link";
        link.target = "_blank";
        link.rel = "noopener noreferrer";
        link.hidden = true;
        const retry = createElement(documentLike, "button", "btn btn-outline-danger btn-sm", "重新建立 QR Code");
        retry.type = "button";
        retry.dataset.role = "retry";
        retry.hidden = true;
        const expiry = createElement(documentLike, "small", "d-block text-muted mt-2");
        expiry.dataset.role = "expiry";

        body.appendChild(title);
        body.appendChild(note);
        body.appendChild(status);
        body.appendChild(qrHost);
        body.appendChild(link);
        body.appendChild(retry);
        body.appendChild(expiry);
        panel.appendChild(body);
        host.appendChild(panel);
        return panel;
    }

    function createController(options) {
        const settings = options || {};
        const documentLike = settings.documentLike || global.document;
        const locationLike = settings.locationLike || global.location;
        const fetchImpl = settings.fetchImpl || global.fetch;
        const rootUrl = settings.rootUrl !== undefined
            ? settings.rootUrl
            : (global.BaseSettings && global.BaseSettings.RootURL) || "";
        let qrControl = null;
        let activeRegSno = null;
        let completedRegSno = null;
        let requestSequence = 0;
        let abortController = null;

        function field(panel, role) {
            return panel.querySelector('[data-role="' + role + '"]');
        }

        function clearQr(panel) {
            if (qrControl && typeof qrControl.destroy === "function") qrControl.destroy();
            qrControl = null;
            const qrHost = field(panel, "qr");
            while (qrHost.firstChild) qrHost.removeChild(qrHost.firstChild);
            qrHost.hidden = true;
            const link = field(panel, "link");
            link.hidden = true;
            link.removeAttribute("href");
            field(panel, "expiry").textContent = "";
        }

        function renderQr(panel, invitation) {
            const QrCode = settings.QrCode || (global.ej && global.ej.barcodegenerator && global.ej.barcodegenerator.QRCodeGenerator);
            if (typeof QrCode !== "function") {
                throw new InvitationRequestError(0, "The local QR renderer is unavailable.");
            }
            const qrHost = field(panel, "qr");
            qrControl = new QrCode({
                width: "224px",
                height: "224px",
                mode: "SVG",
                displayText: { visibility: false },
                value: invitation.public_url
            });
            qrControl.appendTo(qrHost);
            qrHost.hidden = false;

            const link = field(panel, "link");
            link.href = invitation.public_url;
            link.hidden = false;
            if (invitation.expires_at || invitation.expiresAt) {
                const expiresAt = new Date(invitation.expires_at || invitation.expiresAt);
                if (!Number.isNaN(expiresAt.getTime())) {
                    field(panel, "expiry").textContent = "邀請有效至 " + expiresAt.toLocaleString("zh-TW");
                }
            }
        }

        async function showForRegistration(value) {
            const regSno = normalizeRegSno(value);
            const panel = ensurePanel(documentLike);
            if (!panel) return;
            if (completedRegSno === regSno && !panel.hidden) return;

            activeRegSno = regSno;
            const sequence = ++requestSequence;
            if (abortController) abortController.abort();
            abortController = typeof global.AbortController === "function" ? new global.AbortController() : null;
            clearQr(panel);
            panel.hidden = false;
            field(panel, "status").className = "mb-2";
            field(panel, "status").textContent = "掛號成功，正在建立安全邀請…";
            field(panel, "retry").hidden = true;

            try {
                const tokenInput = documentLike.querySelector('input[name="__RequestVerificationToken"]');
                const invitation = await requestInvitation(regSno, {
                    fetchImpl: fetchImpl,
                    rootUrl: rootUrl,
                    csrfToken: tokenInput ? tokenInput.value : "",
                    locationLike: locationLike,
                    signal: abortController ? abortController.signal : undefined
                });
                if (sequence !== requestSequence) return;
                renderQr(panel, invitation);
                completedRegSno = regSno;
                field(panel, "status").className = "mb-2 text-success";
                field(panel, "status").textContent = "QR Code 已建立。掃描後即可開始患者預問診。";
            } catch (error) {
                if (sequence !== requestSequence || (error && error.name === "AbortError")) return;
                clearQr(panel);
                const status = error instanceof InvitationRequestError ? error.status : 0;
                field(panel, "status").className = "mb-2 text-danger";
                field(panel, "status").textContent = responseMessage(status);
                field(panel, "retry").hidden = false;
            }
        }

        function bind() {
            if (!documentLike || documentLike.__aiRegistrationInvitationBound) return;
            documentLike.__aiRegistrationInvitationBound = true;
            documentLike.addEventListener(EVENT_NAME, function (event) {
                const detail = event && event.detail;
                if (!detail) return;
                showForRegistration(detail.regSno).catch(function () { });
            });
            documentLike.addEventListener("click", function (event) {
                const retry = event.target && event.target.closest
                    ? event.target.closest('#ai-registration-invitation [data-role="retry"]')
                    : null;
                if (retry && activeRegSno) showForRegistration(activeRegSno).catch(function () { });
            });
        }

        return { bind: bind, showForRegistration: showForRegistration };
    }

    const api = {
        EVENT_NAME: EVENT_NAME,
        ENDPOINT: ENDPOINT,
        InvitationRequestError: InvitationRequestError,
        normalizeRegSno: normalizeRegSno,
        normalizePublicUrl: normalizePublicUrl,
        responseMessage: responseMessage,
        requestInvitation: requestInvitation,
        createController: createController
    };

    global.AiConsultRegistrationInvitation = api;
    if (global.document) createController().bind();
    if (typeof module !== "undefined" && module.exports) module.exports = api;
})(typeof window !== "undefined" ? window : globalThis);
