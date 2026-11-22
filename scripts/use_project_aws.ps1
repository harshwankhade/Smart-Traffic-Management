# Dot-source this file in a project PowerShell session. No credentials are read
# into PowerShell variables; the SDK profile delegates to AWS CLI browser login.
$projectRoot = Split-Path -Parent $PSScriptRoot
$accountSelection = Join-Path $projectRoot '.data/aws-account.json'
if (-not (Test-Path -LiteralPath $accountSelection)) {
    throw 'Select a verified account with scripts/project_aws.py configure first.'
}
$projectAws = Get-Content -LiteralPath $accountSelection -Raw | ConvertFrom-Json
$observedAccount = & aws sts get-caller-identity --profile $projectAws.profile --region $projectAws.region --query Account --output text
if ($LASTEXITCODE -ne 0 -or $observedAccount.Trim() -ne $projectAws.account_id) {
    throw 'AWS profile identity does not match the selected project account.'
}
# Static credentials take precedence over a profile in some tools. Remove them
# from this shell only; saved profiles and credential files remain untouched.
foreach ($credentialVariable in @('AWS_ACCESS_KEY_ID', 'AWS_SECRET_ACCESS_KEY', 'AWS_SESSION_TOKEN', 'AWS_SECURITY_TOKEN')) {
    Remove-Item -LiteralPath "Env:$credentialVariable" -ErrorAction SilentlyContinue
}
$env:AWS_PROFILE = $projectAws.profile
$env:AWS_REGION = $projectAws.region
$env:AWS_DEFAULT_REGION = $projectAws.region
$env:TF_VAR_expected_account_id = $projectAws.account_id
Write-Output "Project AWS account: $($projectAws.account_id); profile: $($projectAws.profile)"
if ($projectAws.state_layout -eq 'existing') {
    Write-Output 'Preserved original Terraform state is selected; review existing resources before planning.'
} else {
    Write-Output 'Use scripts/project_aws.py terraform for account-isolated Terraform state.'
}
