#requires -Version 5.1

<#
.SYNOPSIS
Clean regenerable Windows caches.

.DESCRIPTION
Builds and prints one cleanup plan. Nothing is deleted without -Apply.
Quit browsers, packaged apps, and development tools before applying it.
System mode does not walk Windows\Temp: Windows PowerShell 5.1 cannot safely
traverse that shared elevated tree without a reparse-point race.

.PARAMETER Apply
Run the printed cleanup plan after confirmation.

.PARAMETER AllTemp
Delete all unlocked current-user temp entries instead of entries at least
seven days old.

.PARAMETER System
Clean Delivery Optimization and the component store instead of user data.
Requires a 64-bit elevated PowerShell process. Run the normal cleanup first.

.PARAMETER GlobalPackages
Also clear NuGet's global package folder. Projects will need to restore packages.

.PARAMETER Yes
Skip the CLEAN confirmation. Only valid with -Apply.

.PARAMETER SelfTest
Test dry-run, deletion, age, path, and reparse-point guards in a temporary tree.

.EXAMPLE
.\clean.ps1

.EXAMPLE
.\clean.ps1 -Apply

.EXAMPLE
# Run separately in an elevated 64-bit PowerShell process.
.\clean.ps1 -Apply -System
#>

[CmdletBinding()]
param(
    [switch] $Apply,
    [switch] $AllTemp,
    [switch] $System,
    [switch] $GlobalPackages,
    [switch] $Yes,
    [switch] $SelfTest
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$script:Program = Split-Path -Leaf $PSCommandPath
$script:Plan = [System.Collections.Generic.List[object]]::new()
$script:AllowedPaths =
    [System.Collections.Generic.HashSet[string]]::new(
        [System.StringComparer]::OrdinalIgnoreCase
    )
$script:ProtectedPaths =
    [System.Collections.Generic.HashSet[string]]::new(
        [System.StringComparer]::OrdinalIgnoreCase
    )
$script:Failures = 0
$script:Removed = 0
$script:SkippedLinks = 0
$script:TestRoot = ''
$script:UserProfile = ''
$script:LocalAppData = ''
$script:WindowsRoot = ''
$script:UserTemp = ''
$script:IsAdministrator = $false

function Stop-Clean {
    param([string] $Message)
    throw "${script:Program}: $Message"
}

function Get-NormalPath {
    param([string] $Path)

    if ([string]::IsNullOrWhiteSpace($Path)) {
        Stop-Clean 'encountered an empty path'
    }
    $full = [System.IO.Path]::GetFullPath($Path)
    $root = [System.IO.Path]::GetPathRoot($full)
    if ($full.Equals($root, [System.StringComparison]::OrdinalIgnoreCase)) {
        return $root
    }
    $separators = [char[]] @(
        [System.IO.Path]::DirectorySeparatorChar,
        [System.IO.Path]::AltDirectorySeparatorChar
    )
    return $full.TrimEnd($separators)
}

function Test-Descendant {
    param(
        [string] $Path,
        [string] $Base
    )

    $prefix = (Get-NormalPath $Base) +
        [System.IO.Path]::DirectorySeparatorChar
    return (Get-NormalPath $Path).StartsWith(
        $prefix,
        [System.StringComparison]::OrdinalIgnoreCase
    )
}

function Assert-LocalPath {
    param([string] $Path)

    $full = Get-NormalPath $Path
    $root = [System.IO.Path]::GetPathRoot($full)
    if ([string]::IsNullOrEmpty($root) -or $root.StartsWith('\\')) {
        Stop-Clean "refusing non-local path: $full"
    }
    try {
        $drive = [System.IO.DriveInfo]::new($root)
    } catch {
        Stop-Clean "cannot identify the drive for: $full"
    }
    if ($drive.DriveType -ne [System.IO.DriveType]::Fixed) {
        Stop-Clean "refusing non-fixed drive path: $full"
    }
}

function Assert-NoReparseAncestor {
    param([string] $Path)

    $cursor = Get-NormalPath $Path
    $root = [System.IO.Path]::GetPathRoot($cursor)
    while ($true) {
        try {
            $attributes = [System.IO.File]::GetAttributes($cursor)
        } catch {
            Stop-Clean "cannot verify path ancestor: $cursor"
        }
        if (($attributes -band
                [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
            Stop-Clean "refusing reparse-point path: $cursor"
        }
        if ($cursor.Equals(
                $root,
                [System.StringComparison]::OrdinalIgnoreCase
            )) {
            break
        }
        $parent = [System.IO.Directory]::GetParent($cursor)
        if ($null -eq $parent) {
            Stop-Clean "cannot walk path ancestors: $Path"
        }
        $cursor = $parent.FullName
    }
}

function Assert-SafeStep {
    param($Step)

    $path = Get-NormalPath $Step.Path
    Assert-LocalPath $path
    $root = [System.IO.Path]::GetPathRoot($path)
    if ($path.Equals(
            $root,
            [System.StringComparison]::OrdinalIgnoreCase
        ) -or $script:ProtectedPaths.Contains($path)) {
        Stop-Clean "refusing protected path: $path"
    }
    if (-not $script:AllowedPaths.Contains($path)) {
        Stop-Clean "refusing unplanned path: $path"
    }
    if ($Step.Kind -ne 'cache' -and $Step.Kind -ne 'temp') {
        Stop-Clean "refusing unknown cleanup kind: $($Step.Kind)"
    }
    Assert-NoReparseAncestor $path
}

function Add-PathStep {
    param(
        [ValidateSet('cache', 'temp')]
        [string] $Kind,
        [string] $Path
    )

    if (-not [System.IO.Directory]::Exists($Path)) {
        return
    }
    $path = Get-NormalPath $Path
    Assert-LocalPath $path
    $root = [System.IO.Path]::GetPathRoot($path)
    if ($path.Equals(
            $root,
            [System.StringComparison]::OrdinalIgnoreCase
        ) -or $script:ProtectedPaths.Contains($path)) {
        Stop-Clean "refusing protected path: $path"
    }

    $isTestPath = -not [string]::IsNullOrEmpty($script:TestRoot) -and
        (Test-Descendant $path $script:TestRoot)
    if (-not $isTestPath) {
        if ($Kind -eq 'temp') {
            if (-not $path.Equals(
                    $script:UserTemp,
                    [System.StringComparison]::OrdinalIgnoreCase
                )) {
                Stop-Clean "refusing unexpected temp path: $path"
            }
        } elseif (-not (Test-Descendant $path $script:LocalAppData)) {
            Stop-Clean "refusing cache outside LocalAppData: $path"
        }
    }

    if (-not $script:AllowedPaths.Add($path)) {
        return
    }
    $cutoff = $null
    if ($Kind -eq 'temp' -and -not $AllTemp) {
        $cutoff = [System.DateTime]::UtcNow.AddDays(-7)
    }
    $script:Plan.Add([pscustomobject] @{
        Type   = 'Path'
        Kind   = $Kind
        Path   = $path
        Cutoff = $cutoff
    })
}

function Find-Tool {
    param([string] $Name)

    if ($script:IsAdministrator) {
        return $null
    }

    $commands = @(Get-Command -Name $Name `
        -CommandType Application, ExternalScript `
        -ErrorAction SilentlyContinue)
    if ($commands.Count -gt 0) {
        return $commands[0]
    }
    return $null
}

function Add-CommandStep {
    param(
        [string] $Label,
        $Command,
        [string[]] $Arguments,
        [hashtable] $Parameters = @{}
    )

    if ($null -eq $Command) {
        return
    }
    $path = if ($Command.CommandType -eq
        [System.Management.Automation.CommandTypes]::Cmdlet) {
        $Command.Name
    } else {
        $Command.Path
    }
    $script:Plan.Add([pscustomobject] @{
        Type      = 'Command'
        Label     = $Label
        Command   = $Command
        Display   = $path
        Arguments = $Arguments
        Parameters = $Parameters
        ChecksExitCode = $Command.CommandType -eq
            [System.Management.Automation.CommandTypes]::Application -or
            $Command.CommandType -eq
            [System.Management.Automation.CommandTypes]::ExternalScript
    })
}

function Add-DirectoryCaches {
    param(
        [string] $Root,
        [string[]] $RelativePaths
    )

    if (-not [System.IO.Directory]::Exists($Root)) {
        return
    }
    try {
        $directories = [System.IO.Directory]::GetDirectories($Root)
    } catch {
        Write-Warning "could not inspect cache root: $Root"
        $script:Failures++
        return
    }
    foreach ($directory in $directories) {
        foreach ($relative in $RelativePaths) {
            Add-PathStep cache (
                [System.IO.Path]::Combine($directory, $relative)
            )
        }
    }
}

function Build-Plan {
    if ($System) {
        $deliveryModule = [System.IO.Path]::Combine(
            $script:WindowsRoot,
            'System32\WindowsPowerShell\v1.0\Modules',
            'DeliveryOptimization\DeliveryOptimization.psd1'
        )
        if ([System.IO.File]::Exists($deliveryModule)) {
            try {
                Import-Module $deliveryModule -ErrorAction Stop
                $delivery = Get-Command 'Delete-DeliveryOptimizationCache' `
                    -Module DeliveryOptimization `
                    -CommandType Cmdlet `
                    -ErrorAction Stop
                Add-CommandStep `
                    -Label 'Delivery Optimization cache' `
                    -Command $delivery `
                    -Arguments @() `
                    -Parameters @{ Force = $true }
            } catch {
                Write-Warning 'Delivery Optimization cleanup is unavailable'
                $script:Failures++
            }
        } else {
            Write-Warning 'Delivery Optimization is unavailable; skipping it'
        }

        $dismPath = [System.IO.Path]::Combine(
            [System.Environment]::SystemDirectory,
            'Dism.exe'
        )
        $commands = @(Get-Command $dismPath `
            -CommandType Application `
            -ErrorAction SilentlyContinue)
        $dism = if ($commands.Count -gt 0) {
            $commands[0]
        } else {
            $null
        }
        if ($null -eq $dism) {
            Stop-Clean 'DISM is unavailable'
        }
        Add-CommandStep 'Windows component store' $dism @(
            '/Online',
            '/Cleanup-Image',
            '/StartComponentCleanup',
            '/NoRestart'
        )
        return
    }

    Add-PathStep temp $script:UserTemp
    Add-PathStep cache (
        [System.IO.Path]::Combine($script:LocalAppData, 'D3DSCache')
    )
    Add-PathStep cache (
        [System.Environment]::GetFolderPath(
            [System.Environment+SpecialFolder]::InternetCache
        )
    )

    $packages = [System.IO.Path]::Combine(
        $script:LocalAppData,
        'Packages'
    )
    Add-DirectoryCaches $packages @('TempState')

    foreach ($browser in @(
        'Microsoft\Edge\User Data',
        'Google\Chrome\User Data',
        'BraveSoftware\Brave-Browser\User Data',
        'Chromium\User Data'
    )) {
        $root = [System.IO.Path]::Combine(
            $script:LocalAppData,
            $browser
        )
        Add-DirectoryCaches $root @('Cache', 'Code Cache', 'GPUCache')
        foreach ($shared in @('ShaderCache', 'GrShaderCache')) {
            Add-PathStep cache (
                [System.IO.Path]::Combine($root, $shared)
            )
        }
    }
    Add-DirectoryCaches (
        [System.IO.Path]::Combine(
            $script:LocalAppData,
            'Mozilla\Firefox\Profiles'
        )
    ) @('cache2')

    $choco = Find-Tool 'choco'
    Add-CommandStep 'Chocolatey HTTP cache' $choco @(
        'cache', 'remove', '--yes', '--no-progress'
    )

    $scoop = Find-Tool 'scoop'
    Add-CommandStep 'Scoop download cache' $scoop @(
        'cache', 'rm', '--all'
    )

    $nugetCaches = @('http-cache', 'temp', 'plugins-cache')
    if ($GlobalPackages) {
        $nugetCaches += 'global-packages'
    }
    $dotnet = Find-Tool 'dotnet'
    if ($null -ne $dotnet) {
        foreach ($cache in $nugetCaches) {
            Add-CommandStep "NuGet $cache" $dotnet @(
                'nuget', 'locals', $cache, '--clear'
            )
        }
    } else {
        $nuget = Find-Tool 'nuget'
        if ($GlobalPackages -and $null -eq $nuget) {
            Stop-Clean '-GlobalPackages requires dotnet or nuget'
        }
        foreach ($cache in $nugetCaches) {
            Add-CommandStep "NuGet $cache" $nuget @(
                'locals', $cache, '-clear'
            )
        }
    }

}

function Format-Argument {
    param([string] $Value)

    if ($Value -notmatch "[\s']") {
        return $Value
    }
    return "'" + $Value.Replace("'", "''") + "'"
}

function Show-Plan {
    if ($script:Plan.Count -eq 0) {
        Write-Output 'plan: nothing found'
        return
    }
    Write-Output 'plan:'
    foreach ($step in $script:Plan) {
        if ($step.Type -eq 'Path') {
            $scope = if ($null -eq $step.Cutoff) {
                'all contents'
            } else {
                "entries older than $($step.Cutoff.ToString('u'))"
            }
            Write-Output "  $($step.Kind): $($step.Path) ($scope)"
            continue
        }
        $parts = @((Format-Argument $step.Display))
        foreach ($argument in $step.Arguments) {
            $parts += Format-Argument $argument
        }
        foreach ($parameter in $step.Parameters.GetEnumerator()) {
            $parts += "-$($parameter.Key)"
            if ($parameter.Value -isnot [bool]) {
                $parts += Format-Argument ([string] $parameter.Value)
            }
        }
        Write-Output "  command: $($parts -join ' ')"
    }
}

function Remove-FileEntry {
    param(
        [string] $Path,
        [System.IO.FileAttributes] $Attributes,
        [ref] $TargetFailures
    )

    try {
        if (($Attributes -band
                [System.IO.FileAttributes]::ReadOnly) -ne 0) {
            [System.IO.File]::SetAttributes(
                $Path,
                ($Attributes -bxor [System.IO.FileAttributes]::ReadOnly)
            )
        }
        [System.IO.File]::Delete($Path)
        $script:Removed++
    } catch {
        $TargetFailures.Value++
        Write-Verbose "could not delete file: $Path"
    }
}

function Clear-Tree {
    param($Step)

    Assert-SafeStep $Step
    $targetFailures = 0
    $pending = [System.Collections.Stack]::new()
    $directories = [System.Collections.Stack]::new()
    $directoryEligibility = [System.Collections.Stack]::new()

    # ponytail: pure PowerShell cannot close reparse races; use a
    # handle-relative native walker if cleanup ever runs against hostile users.
    try {
        foreach ($child in
            [System.IO.Directory]::EnumerateFileSystemEntries($Step.Path)) {
            $pending.Push($child)
        }
    } catch {
        Write-Warning "could not inspect: $($Step.Path)"
        $script:Failures++
        return
    }

    while ($pending.Count -gt 0) {
        $path = [string] $pending.Pop()
        try {
            $attributes = [System.IO.File]::GetAttributes($path)
            if (($attributes -band
                    [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
                $script:SkippedLinks++
                Write-Verbose "skipping reparse point: $path"
                continue
            }
            $isDirectory = ($attributes -band
                [System.IO.FileAttributes]::Directory) -ne 0
            if (-not $isDirectory) {
                $eligible = $null -eq $Step.Cutoff -or
                    [System.IO.File]::GetLastWriteTimeUtc($path) -lt
                        $Step.Cutoff
                if ($eligible) {
                    Remove-FileEntry $path $attributes (
                        [ref] $targetFailures
                    )
                }
                continue
            }

            $eligible = $null -eq $Step.Cutoff -or
                [System.IO.Directory]::GetLastWriteTimeUtc($path) -lt
                    $Step.Cutoff
            $directories.Push($path)
            $directoryEligibility.Push($eligible)
            foreach ($child in
                [System.IO.Directory]::EnumerateFileSystemEntries($path)) {
                $pending.Push($child)
            }
        } catch {
            $targetFailures++
            Write-Verbose "could not inspect entry: $path"
        }
    }

    while ($directories.Count -gt 0) {
        $path = [string] $directories.Pop()
        $eligible = [bool] $directoryEligibility.Pop()
        if (-not $eligible) {
            continue
        }
        try {
            $attributes = [System.IO.File]::GetAttributes($path)
            if (($attributes -band
                    [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
                $script:SkippedLinks++
                Write-Verbose "skipping reparse point: $path"
                continue
            }
            if (($attributes -band
                    [System.IO.FileAttributes]::ReadOnly) -ne 0) {
                [System.IO.File]::SetAttributes(
                    $path,
                    ($attributes -bxor
                        [System.IO.FileAttributes]::ReadOnly)
                )
            }
            [System.IO.Directory]::Delete($path, $false)
            $script:Removed++
        } catch [System.IO.IOException] {
            # Expected when a directory still contains new or linked entries.
            Write-Verbose "directory not empty: $path"
        } catch {
            $targetFailures++
            Write-Verbose "could not delete directory: $path"
        }
    }

    if ($targetFailures -gt 0) {
        Write-Warning (
            "$targetFailures locked or inaccessible entries remain in " +
            $Step.Path
        )
        $script:Failures += $targetFailures
    }
}

function Invoke-CommandStep {
    param($Step)

    try {
        if ($Step.Parameters.Count -gt 0) {
            $parameters = $Step.Parameters
            & $Step.Command @parameters
            return
        }
        $arguments = $Step.Arguments
        $LASTEXITCODE = 0
        & $Step.Command @arguments
        $succeeded = $?
        $rebootRequired = $Step.Label -eq 'Windows component store' -and
            $LASTEXITCODE -eq 3010
        if ($rebootRequired) {
            Write-Warning 'Windows component cleanup requires a restart'
            return
        }
        if (-not $succeeded -or
            ($Step.ChecksExitCode -and $LASTEXITCODE -ne 0)) {
            throw "exit code $LASTEXITCODE"
        }
    } catch {
        Write-Warning "cleanup command failed: $($Step.Label)"
        Write-Verbose $_
        $script:Failures++
    }
}

function Invoke-Plan {
    foreach ($step in $script:Plan) {
        if ($step.Type -eq 'Path') {
            try {
                Clear-Tree $step
            } catch {
                Write-Warning "skipping unsafe target: $($step.Path)"
                Write-Verbose $_
                $script:Failures++
            }
        } else {
            Invoke-CommandStep $step
        }
    }
}

function Confirm-Plan {
    if (-not $Apply -or $Yes) {
        return
    }
    if ([Console]::IsInputRedirected) {
        Stop-Clean '-Apply requires an interactive terminal or -Yes'
    }
    Write-Warning (
        'This permanently deletes the regenerable data shown above.'
    )
    if ($GlobalPackages) {
        Write-Warning 'NuGet projects will need to restore global packages.'
    }
    $reply = Read-Host 'Type CLEAN to continue'
    if ($reply -cne 'CLEAN') {
        Stop-Clean 'cancelled'
    }
}

function Assert-Test {
    param(
        [bool] $Condition,
        [string] $Message
    )

    if (-not $Condition) {
        Stop-Clean "self-test failed: $Message"
    }
}

function Test-RejectedStep {
    param([string] $Path)

    $step = [pscustomobject] @{
        Kind = 'cache'
        Path = $Path
    }
    try {
        Assert-SafeStep $step
    } catch {
        return $true
    }
    return $false
}

function Invoke-SelfTest {
    $script:AllTemp = $false
    $root = [System.IO.Path]::Combine(
        [System.IO.Path]::GetTempPath(),
        "windows-clean-test-$([guid]::NewGuid().ToString('N'))"
    )
    $outside = "$root-outside"
    $link = [System.IO.Path]::Combine($root, 'cache', 'link')
    try {
        [System.IO.Directory]::CreateDirectory(
            [System.IO.Path]::Combine($root, 'cache', 'nested')
        ) | Out-Null
        [System.IO.Directory]::CreateDirectory(
            [System.IO.Path]::Combine($root, 'temp')
        ) | Out-Null
        [System.IO.Directory]::CreateDirectory($outside) | Out-Null
        [System.IO.File]::WriteAllText(
            [System.IO.Path]::Combine($root, 'cache', 'nested', 'file'),
            'x'
        )
        $hidden = [System.IO.Path]::Combine($root, 'cache', '.hidden')
        [System.IO.File]::WriteAllText($hidden, 'x')
        [System.IO.File]::SetAttributes(
            $hidden,
            [System.IO.FileAttributes]::Hidden -bor
                [System.IO.FileAttributes]::ReadOnly
        )
        $old = [System.IO.Path]::Combine($root, 'temp', 'old')
        $new = [System.IO.Path]::Combine($root, 'temp', 'new')
        [System.IO.File]::WriteAllText($old, 'old')
        [System.IO.File]::WriteAllText($new, 'new')
        [System.IO.File]::SetLastWriteTimeUtc(
            $old,
            [System.DateTime]::UtcNow.AddDays(-8)
        )
        $sentinel = [System.IO.Path]::Combine($outside, 'sentinel')
        [System.IO.File]::WriteAllText($sentinel, 'safe')

        $script:TestRoot = Get-NormalPath $root
        $script:ProtectedPaths.Add($script:TestRoot) | Out-Null
        Add-PathStep cache (
            [System.IO.Path]::Combine($root, 'cache')
        )
        Add-PathStep temp (
            [System.IO.Path]::Combine($root, 'temp')
        )
        New-Item -ItemType Junction -Path $link -Target $outside |
            Out-Null

        Show-Plan | Out-Null
        Assert-Test (
            [System.IO.File]::Exists(
                [System.IO.Path]::Combine(
                    $root,
                    'cache',
                    'nested',
                    'file'
                )
            )
        ) 'dry-run setup changed data'

        foreach ($step in $script:Plan) {
            Clear-Tree $step
        }
        Assert-Test (
            -not [System.IO.File]::Exists($hidden)
        ) 'hidden read-only cache survived'
        Assert-Test (
            -not [System.IO.File]::Exists($old) -and
                [System.IO.File]::Exists($new)
        ) 'stale-temp selection is wrong'
        Assert-Test (
            [System.IO.Directory]::Exists($link) -and
                [System.IO.File]::Exists($sentinel)
        ) 'junction was followed or removed'

        $probe = [System.IO.Path]::Combine(
            $root,
            'temp',
            'command-probe'
        )
        $setContent = Get-Command 'Set-Content' -CommandType Cmdlet
        Add-CommandStep 'positional argument test' $setContent @(
            $probe,
            'positional'
        )
        Invoke-CommandStep $script:Plan[$script:Plan.Count - 1]
        Assert-Test (
            [System.IO.File]::ReadAllText($probe).Trim() -eq 'positional'
        ) 'command arguments were not forwarded'
        Add-CommandStep `
            -Label 'named argument test' `
            -Command $setContent `
            -Arguments @() `
            -Parameters @{
                LiteralPath = $probe
                Value       = 'named'
            }
        Invoke-CommandStep $script:Plan[$script:Plan.Count - 1]
        Assert-Test (
            [System.IO.File]::ReadAllText($probe).Trim() -eq 'named'
        ) 'named command parameters were not forwarded'

        $driveRoot = [System.IO.Path]::GetPathRoot($root)
        Assert-Test (Test-RejectedStep $driveRoot) 'drive root accepted'
        Assert-Test (
            Test-RejectedStep $script:UserProfile
        ) 'profile root accepted'
        Assert-Test (
            Test-RejectedStep $script:WindowsRoot
        ) 'Windows root accepted'
        Assert-Test (
            Test-RejectedStep "$root-sibling"
        ) 'prefix-sibling path accepted'
        Write-Output 'self-test passed'
    } finally {
        if ([System.IO.Directory]::Exists($link)) {
            [System.IO.Directory]::Delete($link, $false)
        }
        if ([System.IO.Directory]::Exists($root)) {
            [System.IO.Directory]::Delete($root, $true)
        }
        if ([System.IO.Directory]::Exists($outside)) {
            [System.IO.Directory]::Delete($outside, $true)
        }
    }
}

function Initialize-Cleaner {
    if ($env:OS -ne 'Windows_NT') {
        Stop-Clean 'Windows is required'
    }
    if ($Yes -and -not $Apply) {
        Stop-Clean '-Yes is only valid with -Apply'
    }
    if ($SelfTest -and
        ($Apply -or $AllTemp -or $System -or $GlobalPackages -or $Yes)) {
        Stop-Clean '-SelfTest cannot be combined with cleanup options'
    }

    $script:UserProfile = Get-NormalPath (
        [System.Environment]::GetFolderPath(
            [System.Environment+SpecialFolder]::UserProfile
        )
    )
    $script:LocalAppData = Get-NormalPath (
        [System.Environment]::GetFolderPath(
            [System.Environment+SpecialFolder]::LocalApplicationData
        )
    )
    $script:WindowsRoot = Get-NormalPath (
        [System.Environment]::GetFolderPath(
            [System.Environment+SpecialFolder]::Windows
        )
    )
    $script:UserTemp = Get-NormalPath (
        [System.IO.Path]::GetTempPath()
    )
    foreach ($path in @(
        $script:UserProfile,
        $script:LocalAppData,
        $script:WindowsRoot,
        $script:UserTemp
    )) {
        Assert-LocalPath $path
    }
    foreach ($path in @(
        [System.IO.Path]::GetPathRoot($script:UserProfile),
        $script:UserProfile,
        $script:LocalAppData,
        $script:WindowsRoot
    )) {
        $script:ProtectedPaths.Add((Get-NormalPath $path)) | Out-Null
    }
    $expectedTemp = Get-NormalPath (
        [System.IO.Path]::Combine($script:LocalAppData, 'Temp')
    )
    if (-not $System -and -not $script:UserTemp.Equals(
        $expectedTemp,
        [System.StringComparison]::OrdinalIgnoreCase
    )) {
        Stop-Clean 'the current-user temp folder is not LocalAppData\Temp'
    }

    $identity = [System.Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = [System.Security.Principal.WindowsPrincipal]::new($identity)
    $administrator =
        [System.Security.Principal.WindowsBuiltInRole]::Administrator
    $script:IsAdministrator = $principal.IsInRole($administrator)

    if ($Apply -and $script:IsAdministrator -and -not $System) {
        Stop-Clean 'run normal cleanup from a non-elevated PowerShell process'
    }
    if ($System) {
        if ($AllTemp -or $GlobalPackages) {
            Stop-Clean '-AllTemp and -GlobalPackages cannot be used with -System'
        }
        if (-not $script:IsAdministrator) {
            Stop-Clean '-System requires an elevated PowerShell process'
        }
        if ([System.Environment]::Is64BitOperatingSystem -and
            -not [System.Environment]::Is64BitProcess) {
            Stop-Clean '-System requires 64-bit PowerShell'
        }
    }
}

function Main {
    Initialize-Cleaner
    if ($SelfTest) {
        Invoke-SelfTest
        return
    }

    Build-Plan
    $mode = if ($Apply) { 'apply' } else { 'dry-run' }
    Write-Output "mode: $mode"
    Show-Plan
    if (-not $Apply) {
        Write-Output 'dry run only; rerun with the same options plus -Apply'
        return
    }

    Confirm-Plan
    Invoke-Plan
    Write-Output (
        "cleanup complete; removed: $($script:Removed) entries; " +
        "links skipped: $($script:SkippedLinks); " +
        "warnings: $($script:Failures)"
    )
    if ($script:Failures -gt 0) {
        exit 1
    }
}

Main
