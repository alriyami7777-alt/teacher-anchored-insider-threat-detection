param(
    [string]$RepositoryRoot = (
        Split-Path -Parent $PSScriptRoot
    )
)

$ErrorActionPreference = "Stop"

$sourceRoot = Join-Path $RepositoryRoot "paper\manuscript\source"
$outputCsv = Join-Path $RepositoryRoot `
    "manifests\PAPER_ARTIFACT_INVENTORY.generated.csv"
$gapReport = Join-Path $RepositoryRoot `
    "review\ARTIFACT_PROVENANCE_GAPS.md"

if (-not (Test-Path -LiteralPath $sourceRoot)) {
    throw "Manuscript source directory not found: $sourceRoot"
}

function Get-BracedArgument {
    param(
        [string]$Text,
        [string]$Command
    )

    $commandIndex = $Text.IndexOf(
        $Command,
        [System.StringComparison]::Ordinal
    )

    if ($commandIndex -lt 0) {
        return ""
    }

    $openIndex = $Text.IndexOf(
        "{",
        $commandIndex + $Command.Length
    )

    if ($openIndex -lt 0) {
        return ""
    }

    $depth = 0

    for ($i = $openIndex; $i -lt $Text.Length; $i++) {
        $character = $Text[$i]

        if ($character -eq "{") {
            $depth++
        }
        elseif ($character -eq "}") {
            $depth--

            if ($depth -eq 0) {
                return $Text.Substring(
                    $openIndex + 1,
                    $i - $openIndex - 1
                ).Trim()
            }
        }
    }

    return ""
}

function Get-LineNumber {
    param(
        [string]$Text,
        [int]$CharacterIndex
    )

    if ($CharacterIndex -le 0) {
        return 1
    }

    return (
        $Text.Substring(0, $CharacterIndex) `
            -split "`n"
    ).Count
}

function Get-PaperSection {
    param([string]$FileName)

    switch ($FileName) {
        "access.tex"                  { return "Front matter" }
        "01_introduction.tex"         { return "Introduction" }
        "02_related_work.tex"         { return "Related Work" }
        "03_methodology.tex"          { return "Methodology" }
        "04_experimental_results.tex" { return "Experimental Results" }
        "05_discussion.tex"           { return "Discussion" }
        "06_conclusion.tex"           { return "Conclusion" }
        "07_back_matter.tex"          { return "Back Matter" }
        default                       { return "Unclassified" }
    }
}

function Resolve-GraphicPath {
    param(
        [string]$GraphicReference,
        [string]$TexDirectory
    )

    $candidate = Join-Path $TexDirectory $GraphicReference

    if (Test-Path -LiteralPath $candidate -PathType Leaf) {
        return (Resolve-Path -LiteralPath $candidate).Path
    }

    foreach ($extension in @(
        ".pdf", ".png", ".jpg", ".jpeg", ".eps", ".svg"
    )) {
        $candidateWithExtension = "$candidate$extension"

        if (
            Test-Path `
                -LiteralPath $candidateWithExtension `
                -PathType Leaf
        ) {
            return (
                Resolve-Path -LiteralPath $candidateWithExtension
            ).Path
        }
    }

    return ""
}

$rows = New-Object System.Collections.Generic.List[object]
$figureNumber = 0
$tableNumber = 0

$texFiles = Get-ChildItem `
    -LiteralPath $sourceRoot `
    -Filter "*.tex" `
    -File |
    Sort-Object Name

foreach ($texFile in $texFiles) {
    $content = Get-Content `
        -LiteralPath $texFile.FullName `
        -Raw

    $section = Get-PaperSection $texFile.Name

    $figurePattern =
        '\\begin\{figure\*?\}(.*?)\\end\{figure\*?\}'

    $figureMatches = [regex]::Matches(
        $content,
        $figurePattern,
        [System.Text.RegularExpressions.RegexOptions]::Singleline
    )

    foreach ($match in $figureMatches) {
        $figureNumber++
        $block = $match.Groups[1].Value
        $lineNumber = Get-LineNumber $content $match.Index
        $label = Get-BracedArgument $block "\label"
        $caption = Get-BracedArgument $block "\caption"

        $graphicMatches = [regex]::Matches(
            $block,
            '\\includegraphics(?:\s*\[[^\]]*\])?\s*\{([^}]+)\}'
        )

        $graphicReferences = @(
            foreach ($graphicMatch in $graphicMatches) {
                $graphicMatch.Groups[1].Value.Trim()
            }
        )

        $resolvedPaths = @(
            foreach ($graphicReference in $graphicReferences) {
                $resolvedPath = Resolve-GraphicPath `
                    -GraphicReference $graphicReference `
                    -TexDirectory $texFile.DirectoryName

                if (
                    -not [string]::IsNullOrWhiteSpace(
                        $resolvedPath
                    )
                ) {
                    $resolvedPath
                }
            }
        )

        $repositoryPaths = @(
            foreach ($resolvedPath in $resolvedPaths) {
                $resolvedPath.Substring(
                    $RepositoryRoot.Length + 1
                ).Replace("\", "/")
            }
        )

        $sha256 = ""

        if ($resolvedPaths.Count -eq 1) {
            $sha256 = (
                Get-FileHash `
                    -LiteralPath $resolvedPaths[0] `
                    -Algorithm SHA256
            ).Hash
        }

        $paperLabel = if ($label) {
            $label
        }
        else {
            "figure_environment_$figureNumber"
        }

        $notes = @(
            "Caption: $caption"
            "LaTeX source: paper/manuscript/source/$($texFile.Name)"
            "Line: $lineNumber"
        ) -join " | "

        if ($graphicReferences.Count -eq 0) {
            $notes += " | No includegraphics reference detected"
        }
        elseif ($resolvedPaths.Count -ne $graphicReferences.Count) {
            $notes += " | One or more graphic paths remain unresolved"
        }

        $rows.Add([pscustomobject]@{
            artifact_id        = "FIG-{0:D3}" -f $figureNumber
            artifact_type      = "figure"
            paper_section      = $section
            paper_label        = $paperLabel
            repository_path    = ($repositoryPaths -join ";")
            source_project     = ""
            source_branch      = ""
            source_commit      = ""
            producing_run      = ""
            evidence_role      = ""
            verification_status = "UNRESOLVED"
            sha256             = $sha256
            notes              = $notes
        })
    }

    $tablePattern =
        '\\begin\{table\*?\}(.*?)\\end\{table\*?\}'

    $tableMatches = [regex]::Matches(
        $content,
        $tablePattern,
        [System.Text.RegularExpressions.RegexOptions]::Singleline
    )

    foreach ($match in $tableMatches) {
        $tableNumber++
        $block = $match.Groups[1].Value
        $lineNumber = Get-LineNumber $content $match.Index
        $label = Get-BracedArgument $block "\label"
        $caption = Get-BracedArgument $block "\caption"

        $paperLabel = if ($label) {
            $label
        }
        else {
            "table_environment_$tableNumber"
        }

        $relativeTexPath = $texFile.FullName.Substring(
            $RepositoryRoot.Length + 1
        ).Replace("\", "/")

        $notes = @(
            "Caption: $caption"
            "LaTeX source line: $lineNumber"
            "Producing table or run provenance not yet assigned"
        ) -join " | "

        $rows.Add([pscustomobject]@{
            artifact_id         = "TAB-{0:D3}" -f $tableNumber
            artifact_type       = "table"
            paper_section       = $section
            paper_label         = $paperLabel
            repository_path     = $relativeTexPath
            source_project      = ""
            source_branch       = ""
            source_commit       = ""
            producing_run       = ""
            evidence_role       = ""
            verification_status = "UNRESOLVED"
            sha256              = ""
            notes               = $notes
        })
    }
}

$rows |
    Export-Csv `
        -LiteralPath $outputCsv `
        -NoTypeInformation `
        -Encoding UTF8

$missingFigureFiles = @(
    $rows |
        Where-Object {
            $_.artifact_type -eq "figure" -and
            [string]::IsNullOrWhiteSpace($_.repository_path)
        }
)

$reportLines = @(
    "# Manuscript Artefact Provenance Gaps"
    ""
    "Generated from the versioned manuscript source."
    ""
    "This is an inventory, not evidence verification. Producing-run fields are"
    "intentionally blank until they are recovered from frozen implementation"
    "evidence, producing configurations, manifests, and saved outputs."
    ""
    "## Inventory Summary"
    ""
    "- Figures detected: $figureNumber"
    "- Tables detected: $tableNumber"
    "- Total artefacts: $($rows.Count)"
    "- Figure paths unresolved: $($missingFigureFiles.Count)"
    "- Fully verified artefacts: 0"
    ""
    "## Required Work"
    ""
    "For each data-derived figure and numerical table, recover:"
    ""
    "1. Producing project and worktree."
    "2. Producing branch and frozen commit."
    "3. Producing run/configuration."
    "4. Canonical saved output or source CSV."
    "5. Evidence role: development, validation, guarded test, sensitivity,"
    "   post-hoc, or reproducibility."
    "6. Claim-to-evidence consistency."
    "7. SHA-256 hash of the canonical paper-facing artefact."
    ""
    "Architecture diagrams require design-source provenance but do not require"
    "an experimental producing run."
)

$reportLines |
    Set-Content `
        -LiteralPath $gapReport `
        -Encoding UTF8

Write-Host "Inventory created:"
Write-Host "  $outputCsv"
Write-Host "  $gapReport"
Write-Host ""
Write-Host "Figures: $figureNumber"
Write-Host "Tables:  $tableNumber"
Write-Host "Total:   $($rows.Count)"
