const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const invitation = require("../iis/registration-invitation.js");

test("registration invitation POST uses regSno, antiforgery, and no-store", async () => {
    const calls = [];
    const result = await invitation.requestInvitation(47, {
        rootUrl: "/ehis",
        csrfToken: "csrf-test",
        locationLike: { hostname: "127.0.0.1" },
        fetchImpl: async (url, options) => {
            calls.push({ url, options });
            return new Response(JSON.stringify({
                invite_id: "invite-1",
                public_url: "https://patient.example.test/#token=opaque",
                expires_at: "2026-09-11T12:00:00Z"
            }), { status: 200, headers: { "Content-Type": "application/json" } });
        }
    });

    assert.equal(calls.length, 1);
    assert.equal(calls[0].url, "/ehis/AiConsult/RegistrationInvitations");
    assert.equal(calls[0].options.method, "POST");
    assert.equal(calls[0].options.credentials, "same-origin");
    assert.equal(calls[0].options.cache, "no-store");
    assert.equal(calls[0].options.headers.RequestVerificationToken, "csrf-test");
    assert.deepEqual(JSON.parse(calls[0].options.body), { regSno: 47 });
    assert.equal(result.public_url, "https://patient.example.test/#token=opaque");
});

test("invalid registration numbers never reach the endpoint", async () => {
    let called = false;
    for (const value of [0, -1, 1.5, "not-a-number", null]) {
        await assert.rejects(
            () => invitation.requestInvitation(value, {
                fetchImpl: async () => { called = true; }
            }),
            /positive registration number/
        );
    }
    assert.equal(called, false);
});

test("patient URL must be HTTPS except for an all-loopback development flow", async () => {
    assert.equal(
        invitation.normalizePublicUrl("http://127.0.0.1:5174/#token=test", { hostname: "localhost" }),
        "http://127.0.0.1:5174/#token=test"
    );
    assert.throws(
        () => invitation.normalizePublicUrl("http://patient.example.test/#token=test", { hostname: "127.0.0.1" }),
        /non-HTTPS/
    );
    assert.throws(
        () => invitation.normalizePublicUrl("javascript:alert(1)", { hostname: "127.0.0.1" }),
        /non-HTTPS/
    );
});

test("authorization and gateway failures remain separate from registration success", async () => {
    for (const [status, expected] of [
        [403, "沒有建立這筆掛號邀請的權限"],
        [404, "不符合建立邀請的條件"],
        [502, "智慧問診服務目前無法連線"]
    ]) {
        await assert.rejects(
            () => invitation.requestInvitation(47, {
                fetchImpl: async () => new Response(JSON.stringify({ title: "failure" }), {
                    status,
                    headers: { "Content-Type": "application/json" }
                })
            }),
            (error) => error.status === status && error.message.includes(expected)
        );
    }
});

test("deployment installer preserves the B01 success and authorization boundaries", () => {
    const installerPath = path.join(__dirname, "..", "scripts", "install-registration-invitation.ps1");
    const installer = fs.readFileSync(installerPath, "utf8");

    assert.match(installer, /response\.data\.id/);
    assert.doesNotMatch(installer, /response\.data\.number/);
    assert.match(installer, /ehis:registration-succeeded/);
    assert.match(installer, /RegistrationInvitations/);
    assert.match(installer, /HasMenuPermission\("Outpatient", "B01"\)/);
    assert.match(installer, /RegisteredUserId/);
    assert.match(installer, /RegistrationInvitationStates/);
    assert.match(installer, /ValidateAntiForgeryToken/);
});
