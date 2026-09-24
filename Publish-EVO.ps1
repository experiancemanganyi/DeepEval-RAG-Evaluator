param(
    [string]$Branch = 'DeepEval-ALL',
    [string]$GitPath,
    [string]$Remote = 'https://github.com/experiancemanganyi/DeepEval-RAG-Evaluator.git',
    [switch]$CheckOnly
)
$ErrorActionPreference = 'Stop'

Set-Location -LiteralPath $PSScriptRoot
function Find-ProjectGit {
    if ($GitPath) {
        if (-not (Test-Path -LiteralPath $GitPath -PathType Leaf)) {
            throw "Git executable not found: $GitPath"
        }
        return (Resolve-Path -LiteralPath $GitPath).Path
    }
    $command = Get-Command git.exe -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($command) { return $command.Source }
    $candidates = @(
        "$env:ProgramFiles\Git\cmd\git.exe",
        "${env:ProgramFiles(x86)}\Git\cmd\git.exe",
        "$env:LOCALAPPDATA\Programs\Git\cmd\git.exe"
    )
    foreach ($root in @($env:ProgramFiles, ${env:ProgramFiles(x86)})) {
        if ($root) {
            $candidates += @(Get-ChildItem -Path "$root\Microsoft Visual Studio\*\*\Common7\IDE\CommonExtensions\Microsoft\TeamFoundation\Team Explorer\Git\cmd\git.exe" -File -ErrorAction SilentlyContinue | Select-Object -ExpandProperty FullName)
        }
    }
    foreach ($candidate in $candidates) {
        if (Test-Path -LiteralPath $candidate -PathType Leaf) { return $candidate }
    }
    throw 'Git was not found. Install Git for Windows, reopen PowerShell, and retry; or supply -GitPath with the full path to git.exe.'
}
$projectGit = Find-ProjectGit
Write-Host "Using Git: $projectGit"
function Invoke-ProjectGit {
    param([string[]]$Arguments)
    & $projectGit --no-pager -c http.sslBackend=openssl @Arguments
    if ($LASTEXITCODE -ne 0) { throw 'Git did not complete. Check the message above; no force push was attempted.' }
}
Invoke-ProjectGit -Arguments @('--version')
Invoke-ProjectGit -Arguments @('rev-parse', '--show-toplevel')
$staged = Invoke-ProjectGit -Arguments @('diff', '--cached', '--name-only')
$publishFiles = @('.gitignore', '.github', 'EVO.py', 'main.py', 'Evaluate.py', 'RAG_DeepEval.py', 'LICENSE.txt', 'processDocuments.py', 'README.md', 'requirements.txt', 'requirements-dev.txt', 'pytest.ini', 'Start-EVO.ps1', 'Publish-EVO.ps1', 'USER_GUIDE.md', 'INTERVIEW_AUTOMATION.md', 'UNIVERSAL_METRICS.md', 'USERS_AND_CLEANUP.md', 'UNIVERSAL_TESTING.md', 'VALIDATION.md', 'docs', 'evo_platform', 'tests', 'web')
foreach ($path in $staged) {
    $allowed = $false
    foreach ($entry in $publishFiles) {
        if ($path -eq $entry -or $path.StartsWith($entry + '/')) { $allowed = $true; break }
    }
    if (-not $allowed -and -not $path.StartsWith('.vs/')) {
        throw "An unrelated file is staged: $path. Review or unstage it before publishing."
    }
}
Invoke-ProjectGit -Arguments @('check-ref-format', '--branch', $Branch)
Invoke-ProjectGit -Arguments @('diff', '--cached', '--stat')
if ($CheckOnly) {
    Write-Host 'Git, staged-file, and repository checks passed. No files, branches, commits, or remote repositories were changed.'
    return
}
$currentBranch = Invoke-ProjectGit -Arguments @('branch', '--show-current')
if ($currentBranch -ne $Branch) {
    $existingBranch = Invoke-ProjectGit -Arguments @('branch', '--list', $Branch)
    if ($existingBranch) {
        throw "Branch $Branch already exists. Switch to it in Visual Studio or Git, then run this script again."
    }
    Invoke-ProjectGit -Arguments @('switch', '-c', $Branch)
}
# Stop tracking IDE state, without deleting the local Visual Studio files.
Invoke-ProjectGit -Arguments @('rm', '-r', '--cached', '--ignore-unmatch', '--', '.vs')
Invoke-ProjectGit -Arguments (@('add', '--') + $publishFiles)
Invoke-ProjectGit -Arguments @('diff', '--cached', '--stat')
if (Invoke-ProjectGit -Arguments @('diff', '--cached', '--name-only')) {
    Invoke-ProjectGit -Arguments @('commit', '-m', 'Add web workspace for universal AI evaluation')
} else {
    Write-Host 'Source is already committed; retrying the push.'
}
Invoke-ProjectGit -Arguments @('push', $Remote, "${Branch}:refs/heads/$Branch")
Write-Host "Published branch: $Branch"
Write-Host "Remote: $Remote"



