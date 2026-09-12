const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

// eHIS is separately controlled; opt in to checking its local source checkout.
const sourceRoot = process.env.EHIS_SOURCE_ROOT;

test("eHIS QR management scopes retain menu and initial invitation boundaries", {
    skip: sourceRoot ? false : "Set EHIS_SOURCE_ROOT to an eHIS source checkout",
}, () => {
    const source = fs.readFileSync(
        path.join(sourceRoot, "eHIS", "Controllers", "AiConsultController.cs"), "utf8",
    );
    const scopes = source.match(/string\[\] DoctorScopes\s*=\s*\{([^}]+)\}/)[1];
    assert.deepEqual([...scopes.matchAll(/"([^"]+)"/g)].map(match => match[1]), [
        "consultation:read", "consultation:chat", "invite:create",
    ]);
    const bootstrap = source.slice(source.indexOf("public async Task<IActionResult> Bootstrap("),
        source.indexOf("public async Task<IActionResult> Invitations("));
    assert.match(bootstrap, /if \(!HasMenuPermission\("Index"\)\)\s*return Forbid\(\);/);
    assert.ok(bootstrap.indexOf('HasMenuPermission("Index")') < bootstrap.indexOf("_tokenService.Create("));
    assert.match(bootstrap, /GetAccessibleEncounterAsync\(/);
    assert.match(bootstrap, /if \(encounter == null\)\s*return NotFound\(/);
    assert.match(bootstrap, /var scopes = GetDoctorScopes\(\);/);
    assert.match(bootstrap, /encounter\?\.RegSno,\s*scopes,\s*"doctor"/);
    const invitations = source.slice(source.indexOf("public async Task<IActionResult> Invitations("),
        source.indexOf("public async Task<IActionResult> RegistrationInvitations("));
    assert.match(invitations, /if \(!HasMenuPermission\("Index"\)\)\s*return Forbid\(\);/);
    assert.match(invitations, /GetAccessibleEncounterAsync\(request.RegSno, UserInfo.Sno,/);
    assert.match(invitations, /if \(encounter == null\)\s*return NotFound\(/);
    assert.match(source, /new\[\] \{ "invite:create" \},\s*"ucc_service"/);
});
