import assert from 'node:assert/strict'
import { access, readFile } from 'node:fs/promises'
import path from 'node:path'
import test from 'node:test'

const frontendRoot = path.resolve(import.meta.dirname, '..')
const ehisRoot = process.env.EHIS_SOURCE_ROOT
  ? path.resolve(process.env.EHIS_SOURCE_ROOT)
  : path.resolve(frontendRoot, '..', '..', 'ehis', 'eHIS')

async function source(relativePath) {
  return readFile(path.join(ehisRoot, relativePath), 'utf8')
}

test('eHIS dashboard and bootstrap support a missing registration context', async (t) => {
  try {
    await access(ehisRoot)
  } catch {
    return t.skip(`eHIS source is not available at ${ehisRoot}`)
  }

  const controller = await source('Controllers/AiConsultController.cs')
  const model = await source('Models/AiConsultModels.cs')
  const tokenService = await source('Services/AiConsult/AiConsultSecurity.cs')
  const view = await source('Views/AiConsult/Index.cshtml')

  assert.match(controller, /Bootstrap\(int\? regSno/)
  assert.match(controller, /Encounter = encounter == null\s*\? null/)
  assert.match(controller, /CanCreateInvitation = encounter != null/)
  assert.match(controller, /if \(HasMenuPermission\("RuleCenter"\)\)/)
  assert.match(controller, /scopes\.Add\("rules:read"\)/)
  assert.match(controller, /scopes\.Add\("rules:write"\)/)
  assert.match(model, /JsonPropertyName\("capabilities"\)/)
  assert.match(model, /JsonPropertyName\("can_create_invitation"\)/)
  assert.match(tokenService, /if \(regSno\.HasValue\)\s*payload\["reg_sno"\]/)
  assert.match(view, /src="@iframeUrl"/)
  assert.doesNotMatch(view, /@if \(hasValidRegSno\)/)
})

test('eHIS invitation endpoint still requires CSRF and an accessible encounter', async (t) => {
  try {
    await access(ehisRoot)
  } catch {
    return t.skip(`eHIS source is not available at ${ehisRoot}`)
  }

  const controller = await source('Controllers/AiConsultController.cs')
  const tokenService = await source('Services/AiConsult/AiConsultSecurity.cs')

  assert.match(controller, /\[ValidateAntiForgeryToken\][\s\S]*?Task<IActionResult> Invitations/)
  assert.match(controller, /GetAccessibleEncounterAsync\(request\.RegSno, UserInfo\.Sno/)
  assert.match(controller, /new\[\] \{ "invite:create" \}/)
  assert.match(controller, /"ucc_service"/)
  assert.match(tokenService, /tokenUse == "ucc_service" && !regSno\.HasValue/)
})
