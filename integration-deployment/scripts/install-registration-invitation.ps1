[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$EhisProjectRoot,
    [string]$RepositoryRoot = '',
    [switch]$ValidateOnly
)

$ErrorActionPreference = 'Stop'
$ehisRoot = (Resolve-Path -LiteralPath $EhisProjectRoot).Path
$RepositoryRoot = if ([string]::IsNullOrWhiteSpace($RepositoryRoot)) {
    (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
} else {
    $RepositoryRoot
}
$repositoryRoot = (Resolve-Path -LiteralPath $RepositoryRoot).Path
$utf8 = New-Object Text.UTF8Encoding($false)

function Read-SourceFile([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "Required eHIS source file is missing: $Path"
    }
    $raw = [IO.File]::ReadAllText($Path)
    [PSCustomObject]@{
        Path = $Path
        NewLine = if ($raw.Contains("`r`n")) { "`r`n" } else { "`n" }
        Text = $raw.Replace("`r`n", "`n")
    }
}

function Replace-ExactOnce(
    [string]$Source,
    [string]$Before,
    [string]$After,
    [string]$InstalledNeedle,
    [string]$Label
) {
    if ($Source.Contains($InstalledNeedle)) { return $Source }
    $count = [regex]::Matches($Source, [regex]::Escape($Before)).Count
    if ($count -ne 1) {
        throw "$Label patch expected one source anchor but found $count. Refusing a partial install."
    }
    return $Source.Replace($Before, $After)
}

function Replace-RegexOnce(
    [string]$Source,
    [string]$Pattern,
    [string]$Replacement,
    [string]$InstalledNeedle,
    [string]$Label
) {
    if ($Source.Contains($InstalledNeedle)) { return $Source }
    $matches = [regex]::Matches($Source, $Pattern)
    if ($matches.Count -ne 1) {
        throw "$Label patch expected one source region but found $($matches.Count). Refusing a partial install."
    }
    return [regex]::Replace($Source, $Pattern, [System.Text.RegularExpressions.MatchEvaluator]{ param($match) $Replacement }, 1)
}

$controller = Read-SourceFile (Join-Path $ehisRoot 'Controllers\AiConsultController.cs')
$service = Read-SourceFile (Join-Path $ehisRoot 'Services\AiConsult\AiConsultIntegration.cs')
$models = Read-SourceFile (Join-Path $ehisRoot 'Models\AiConsultModels.cs')
$view = Read-SourceFile (Join-Path $ehisRoot 'Views\Outpatient\B01.cshtml')
$registrationJs = Read-SourceFile (Join-Path $ehisRoot 'wwwroot\page\js\OP01.js')
$assetSource = Join-Path $repositoryRoot 'integration-deployment\iis\registration-invitation.js'
if (-not (Test-Path -LiteralPath $assetSource -PathType Leaf)) {
    throw "Registration invitation browser asset is missing: $assetSource"
}

$service.Text = Replace-ExactOnce $service.Text @'
        Task<AiConsultEncounterPatient> GetAccessibleEncounterAsync(int regSno, int userSno, CancellationToken cancellationToken);
        Task<AiConsultPatientPrefill> GetPrefillAsync(AiConsultEncounterPatient encounter, CancellationToken cancellationToken);
'@ @'
        Task<AiConsultEncounterPatient> GetAccessibleEncounterAsync(int regSno, int userSno, CancellationToken cancellationToken);
        Task<AiConsultEncounterPatient> GetRegistrationEncounterAsync(int regSno, string registrationUserId, CancellationToken cancellationToken);
        Task<AiConsultPatientPrefill> GetPrefillAsync(AiConsultEncounterPatient encounter, CancellationToken cancellationToken);
'@ 'GetRegistrationEncounterAsync(int regSno, string registrationUserId' 'encounter interface'

$encounterMethods = @'
        public async Task<AiConsultEncounterPatient> GetAccessibleEncounterAsync(int regSno, int userSno, CancellationToken cancellationToken)
        {
            if (userSno <= 0)
                return null;

            var encounter = await LoadEncounterAsync(
                regSno,
                AiConsultEncounterEligibility.CurrentStates,
                cancellationToken);
            if (encounter == null)
                return null;

            if (encounter.DoctorSno == userSno)
                return encounter;

            if (!encounter.EncounterDate.HasValue ||
                !int.TryParse(encounter.Period, out var period) ||
                string.IsNullOrWhiteSpace(encounter.DepartmentId))
                return null;

            var isSubstitute = await _context.DaysSchedules.AsNoTracking().AnyAsync(x =>
                x.OpdDay == encounter.EncounterDate.Value.Date &&
                x.Period == period &&
                x.DepartmentId == encounter.DepartmentId &&
                x.DoctorIdSubstitute == userSno,
                cancellationToken);

            return isSubstitute ? encounter : null;
        }

        public async Task<AiConsultEncounterPatient> GetRegistrationEncounterAsync(
            int regSno,
            string registrationUserId,
            CancellationToken cancellationToken)
        {
            if (string.IsNullOrWhiteSpace(registrationUserId))
                return null;

            var encounter = await LoadEncounterAsync(
                regSno,
                AiConsultEncounterEligibility.RegistrationInvitationStates,
                cancellationToken);
            if (encounter == null ||
                !string.Equals(encounter.RegisteredUserId, registrationUserId, StringComparison.OrdinalIgnoreCase))
                return null;

            return encounter;
        }

        private async Task<AiConsultEncounterPatient> LoadEncounterAsync(
            int regSno,
            int[] eligibleStates,
            CancellationToken cancellationToken)
        {
            if (regSno <= 0)
                return null;

            var today = DateTime.Today;
            var data = await (
                from registration in _context.OutpatientRegistereds.AsNoTracking()
                join patient in _context.OutpatientPatients.AsNoTracking()
                    on registration.Patient equals patient.Sno
                where registration.Sno == regSno &&
                      registration.Date == today &&
                      eligibleStates.Contains(registration.OpdState) &&
                      !patient.IsDeleted
                select new
                {
                    RegSno = registration.Sno,
                    PatientSno = patient.Sno,
                    DoctorSno = registration.Doctor,
                    RegisteredUserId = registration.RegisteredUserId,
                    EncounterDate = registration.Date,
                    OpdState = registration.OpdState,
                    Period = registration.Period,
                    DepartmentId = registration.Diagnosis,
                    PatientName = patient.NameCh,
                    Gender = patient.Gender,
                    BirthDate = patient.Birthday,
                    BloodType = patient.BloodType,
                    patient.AllergyHistory,
                    patient.disease_history_allergy,
                    patient.AllergyHistoryMemo,
                    patient.disease_history_memo_allergy,
                    patient.disease_history_medicine,
                    patient.LongtimeHistory,
                    patient.disease_history_memo_medicine,
                    patient.LongtimeHistoryMemo,
                    patient.MedicalHistory,
                    patient.disease_history_self,
                    patient.MedicalHistoryMemo,
                    patient.disease_history_memo_self,
                    patient.OperationHistory,
                    patient.disease_history_surgery,
                    patient.OperationHistoryMemo,
                    patient.disease_history_memo_surgery
                }).SingleOrDefaultAsync(cancellationToken);

            if (data == null)
                return null;

            return new AiConsultEncounterPatient
            {
                RegSno = data.RegSno,
                PatientSno = data.PatientSno,
                DoctorSno = data.DoctorSno,
                RegisteredUserId = data.RegisteredUserId,
                EncounterDate = data.EncounterDate,
                Period = data.Period,
                DepartmentId = data.DepartmentId,
                PatientName = data.PatientName,
                Gender = data.Gender,
                BirthDate = data.BirthDate,
                BloodType = data.BloodType,
                AllergyHistory = JoinNonEmpty(data.AllergyHistory, data.disease_history_allergy),
                AllergyHistoryMemo = JoinNonEmpty(data.AllergyHistoryMemo, data.disease_history_memo_allergy),
                MedicineHistory = JoinNonEmpty(data.disease_history_medicine, data.LongtimeHistory),
                MedicineHistoryMemo = JoinNonEmpty(data.disease_history_memo_medicine, data.LongtimeHistoryMemo),
                MedicalHistory = JoinNonEmpty(data.MedicalHistory, data.disease_history_self),
                MedicalHistoryMemo = JoinNonEmpty(data.MedicalHistoryMemo, data.disease_history_memo_self),
                OperationHistory = JoinNonEmpty(data.OperationHistory, data.disease_history_surgery),
                OperationHistoryMemo = JoinNonEmpty(data.OperationHistoryMemo, data.disease_history_memo_surgery)
            };
        }

'@
$service.Text = Replace-RegexOnce $service.Text '(?s)        public async Task<AiConsultEncounterPatient> GetAccessibleEncounterAsync\(int regSno, int userSno, CancellationToken cancellationToken\).*?(?=        public async Task<AiConsultPatientPrefill> GetPrefillAsync)' $encounterMethods 'private async Task<AiConsultEncounterPatient> LoadEncounterAsync' 'encounter authorization'

$service.Text = Replace-ExactOnce $service.Text @'
        internal static readonly int[] CurrentStates =
        {
            (int)OPDState.UnOutpatient,
            (int)OPDState.Progressing
        };

'@ @'
        internal static readonly int[] CurrentStates =
        {
            (int)OPDState.UnOutpatient,
            (int)OPDState.Progressing
        };

        internal static readonly int[] RegistrationInvitationStates =
        {
            (int)OPDState.UnOutpatient,
            (int)OPDState.Progressing,
            (int)OPDState.NotCheckIn
        };

'@ 'internal static readonly int[] RegistrationInvitationStates' 'registration invitation states'

$models.Text = Replace-ExactOnce $models.Text @'
        public int DoctorSno { get; init; }
        public DateTime? EncounterDate { get; init; }
'@ @'
        public int DoctorSno { get; init; }
        public string RegisteredUserId { get; init; }
        public DateTime? EncounterDate { get; init; }
'@ 'public string RegisteredUserId { get; init; }' 'encounter registration owner'

$controller.Text = Replace-ExactOnce $controller.Text @'
        private static readonly EventId InvitationFailedEvent = new EventId(4101, "AiConsultInvitationFailed");

'@ @'
        private static readonly EventId InvitationFailedEvent = new EventId(4101, "AiConsultInvitationFailed");
        private static readonly EventId RegistrationInvitationCreatedEvent = new EventId(4102, "AiConsultRegistrationInvitationCreated");
        private static readonly EventId RegistrationInvitationFailedEvent = new EventId(4103, "AiConsultRegistrationInvitationFailed");

'@ 'AiConsultRegistrationInvitationCreated' 'registration invitation audit events'

$invitationActions = @'
        [HttpPost]
        [ValidateAntiForgeryToken]
        [ResponseCache(NoStore = true, Location = ResponseCacheLocation.None)]
        public async Task<IActionResult> Invitations(
            [FromBody] CreateAiConsultInvitationRequest request,
            CancellationToken cancellationToken)
        {
            if (!HasMenuPermission("Index"))
                return Forbid();
            if (request == null || request.RegSno <= 0)
                return BadRequest(new ProblemDetails { Title = "A valid regSno is required." });

            var encounter = await _encounterService.GetAccessibleEncounterAsync(request.RegSno, UserInfo.Sno, cancellationToken);
            if (encounter == null)
                return NotFound(new ProblemDetails { Title = "The encounter was not found or is not accessible." });

            return await CreateInvitationAsync(
                encounter,
                InvitationCreatedEvent,
                InvitationFailedEvent,
                "InvitationCreated",
                cancellationToken);
        }

        [HttpPost]
        [ValidateAntiForgeryToken]
        [ResponseCache(NoStore = true, Location = ResponseCacheLocation.None)]
        public async Task<IActionResult> RegistrationInvitations(
            [FromBody] CreateAiConsultInvitationRequest request,
            CancellationToken cancellationToken)
        {
            if (!HasMenuPermission("Outpatient", "B01"))
                return Forbid();
            if (request == null || request.RegSno <= 0)
                return BadRequest(new ProblemDetails { Title = "A valid regSno is required." });

            var loginId = UserInfo?.LoginId;
            var encounter = await _encounterService.GetRegistrationEncounterAsync(
                request.RegSno,
                loginId,
                cancellationToken);
            if (encounter == null)
                return NotFound(new ProblemDetails { Title = "The registration was not found or is not accessible." });

            return await CreateInvitationAsync(
                encounter,
                RegistrationInvitationCreatedEvent,
                RegistrationInvitationFailedEvent,
                "RegistrationInvitationCreated",
                cancellationToken);
        }

        private async Task<IActionResult> CreateInvitationAsync(
            AiConsultEncounterPatient encounter,
            EventId successEvent,
            EventId failureEvent,
            string eventCategory,
            CancellationToken cancellationToken)
        {
            var institutionId = GetInstitutionId();
            var prefill = await _encounterService.GetPrefillAsync(encounter, cancellationToken);
            var correlationId = Guid.NewGuid().ToString("N");
            var serviceToken = _tokenService.Create(
                $"ucc-service:{institutionId}",
                institutionId,
                encounter.RegSno,
                new[] { "invite:create" },
                "ucc_service");

            try
            {
                var response = await _gateway.CreateInvitationAsync(
                    new AiConsultInvitationPayload
                    {
                        InstitutionId = institutionId,
                        PatientSno = encounter.PatientSno,
                        RegSno = encounter.RegSno,
                        Prefill = prefill
                    },
                    serviceToken.Value,
                    cancellationToken);

                _logger.LogInformation(
                    successEvent,
                    "AI consultation event {EventCategory} completed. CorrelationId {CorrelationId}.",
                    eventCategory,
                    correlationId);
                return Json(response);
            }
            catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
            {
                throw;
            }
            catch (Exception)
            {
                _logger.LogError(
                    failureEvent,
                    "AI consultation event {EventCategory} failed. CorrelationId {CorrelationId}.",
                    eventCategory + "GatewayFailure",
                    correlationId);
                return StatusCode(502, new ProblemDetails { Title = "The AI consultation service is unavailable." });
            }
        }

'@
$controller.Text = Replace-RegexOnce $controller.Text '(?s)        \[HttpPost\]\n        \[ValidateAntiForgeryToken\]\n        \[ResponseCache\(NoStore = true, Location = ResponseCacheLocation.None\)\]\n        public async Task<IActionResult> Invitations\(.*?(?=        private IReadOnlyCollection<string> GetDoctorScopes\(\))' $invitationActions 'public async Task<IActionResult> RegistrationInvitations' 'registration invitation action'

$controller.Text = Replace-ExactOnce $controller.Text @'
        private bool HasMenuPermission(string action)
        {
            var result = _menuService.GetMenu();
            return result?.Data?.Any(menu =>
                string.Equals(menu.Controller, "AiConsult", StringComparison.OrdinalIgnoreCase) &&
                string.Equals(menu.Action, action, StringComparison.OrdinalIgnoreCase)) == true;
        }
'@ @'
        private bool HasMenuPermission(string action) => HasMenuPermission("AiConsult", action);

        private bool HasMenuPermission(string controller, string action)
        {
            var result = _menuService.GetMenu();
            return result?.Data?.Any(menu =>
                string.Equals(menu.Controller, controller, StringComparison.OrdinalIgnoreCase) &&
                string.Equals(menu.Action, action, StringComparison.OrdinalIgnoreCase)) == true;
        }
'@ 'private bool HasMenuPermission(string controller, string action)' 'menu authorization overload'

$view.Text = Replace-ExactOnce $view.Text @'
            <script type="text/javascript" src="@Url.Content($"~/page/js/OP01.js")" asp-append-version="true"></script>
'@ @'
            <script type="text/javascript" src="@Url.Content($"~/page/js/OP01.js")" asp-append-version="true"></script>
            <script type="text/javascript" src="@Url.Content($"~/ai-consult-registration/registration-invitation.js")" asp-append-version="true"></script>
'@ '~/ai-consult-registration/registration-invitation.js' 'B01 invitation browser asset'

$registrationJs.Text = Replace-ExactOnce $registrationJs.Text @'
                $("#reg_finished").val("Y");
'@ @'
                $("#reg_finished").val("Y");
                const aiConsultRegSno = Number(response.data && response.data.id);
                if (Number.isSafeInteger(aiConsultRegSno) && aiConsultRegSno > 0) {
                    document.dispatchEvent(new CustomEvent("ehis:registration-succeeded", {
                        detail: { regSno: aiConsultRegSno }
                    }));
                }
'@ 'ehis:registration-succeeded' 'B01 registration success event'

$changes = @($controller, $service, $models, $view, $registrationJs) | Where-Object {
    $original = [IO.File]::ReadAllText($_.Path).Replace("`r`n", "`n")
    $original -ne $_.Text
}
$assetTargetDirectory = Join-Path $ehisRoot 'wwwroot\ai-consult-registration'
$assetTarget = Join-Path $assetTargetDirectory 'registration-invitation.js'
$assetNeedsUpdate = -not (Test-Path -LiteralPath $assetTarget -PathType Leaf) -or
    ([IO.File]::ReadAllText($assetSource) -ne [IO.File]::ReadAllText($assetTarget))

if ($ValidateOnly) {
    Write-Output "Registration invitation integration validated; source files requiring changes: $($changes.Count); asset update required: $assetNeedsUpdate"
    exit 0
}

if ($changes.Count -eq 0 -and -not $assetNeedsUpdate) {
    Write-Output 'Registration invitation integration is already installed.'
    exit 0
}

$resolvedEhisRoot = [IO.Path]::GetFullPath($ehisRoot).TrimEnd('\') + '\'
foreach ($item in $changes) {
    $resolvedPath = [IO.Path]::GetFullPath($item.Path)
    if (-not $resolvedPath.StartsWith($resolvedEhisRoot, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to write outside the eHIS project: $resolvedPath"
    }
}

$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$backup = Join-Path $ehisRoot ".deployment-backups\registration-invitation-$stamp"
New-Item -ItemType Directory -Force -Path $backup | Out-Null
foreach ($item in $changes) {
    $relative = [IO.Path]::GetFullPath($item.Path).Substring($resolvedEhisRoot.Length)
    $backupPath = Join-Path $backup $relative
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $backupPath) | Out-Null
    Copy-Item -LiteralPath $item.Path -Destination $backupPath -Force
}
if (Test-Path -LiteralPath $assetTarget -PathType Leaf) {
    $assetBackup = Join-Path $backup 'wwwroot\ai-consult-registration\registration-invitation.js'
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $assetBackup) | Out-Null
    Copy-Item -LiteralPath $assetTarget -Destination $assetBackup -Force
}

foreach ($item in $changes) {
    $output = if ($item.NewLine -eq "`r`n") { $item.Text.Replace("`n", "`r`n") } else { $item.Text }
    [IO.File]::WriteAllText($item.Path, $output, $utf8)
}
New-Item -ItemType Directory -Force -Path $assetTargetDirectory | Out-Null
Copy-Item -LiteralPath $assetSource -Destination $assetTarget -Force

Write-Output "Registration invitation integration installed. Backup: $backup"
Write-Output 'Build and publish eHIS separately; this installer does not restart IIS.'
