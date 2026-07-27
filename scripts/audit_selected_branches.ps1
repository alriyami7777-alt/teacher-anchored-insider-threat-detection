param(
    [string]$Repository = "C:\PhD\07_Projects\cert-r42-feasibility"
)

Set-Location $Repository
git fetch origin --prune --tags

# These branches are the first candidates for review. The script remains
# read-only and ends with a dry-run push preview.
$branches = @(
    "objective2-teacher-anchored-final-audit",
    "objective2-r52-locked-baselines",
    "objective2-r52-teacher-anchored-reproducibility",
    "objective2-r52-same-information-baselines",
    "objective3-r52-explanation-robustness-portability",
    "objective1-r62-model-free-warmup"
)

# Do not push these lineages without a separate history-cleaning review.
# The eight-tree lineage includes commits that force-tracked checkpoints
# and prediction artefacts. Descendant branches can carry those blobs even
# when the latest commit itself only contains reports.
$highRiskBranches = @(
    "objective2-r52-odst-8tree-ablation",
    "objective2-r52-component-latency-audit"
)

$sensitivePattern = '(?i)(^|/)(data/raw|data/processed|answers|secrets|credentials)(/|$)|(?i)\.(pt|pth|ckpt|npy|npz|pkl|pickle|joblib|parquet|h5|hdf5)$|(?i)(^|/)\.env(\.|$)'

Write-Host "`nHIGH-RISK LINEAGES EXCLUDED FROM DEFAULT PUSH REVIEW:"
$highRiskBranches | ForEach-Object { Write-Host " - $_" }

foreach ($branch in $branches) {
    Write-Host "`n=================================================="
    Write-Host "BRANCH: $branch"
    Write-Host "=================================================="

    git rev-parse --verify $branch *> $null
    if ($LASTEXITCODE -ne 0) {
        Write-Warning "Branch not found."
        continue
    }

    Write-Host "`nCommits not in origin/main:"
    git log --oneline "origin/main..$branch"

    Write-Host "`nPotentially sensitive tracked paths:"
    $matches = git ls-tree -r --name-only $branch | Select-String -Pattern $sensitivePattern
    if ($matches) {
        $matches
    } else {
        Write-Host "None matched by filename pattern."
    }

    Write-Host "`nTracked files at least 10 MB:"
    $large = foreach ($line in git ls-tree -r -l $branch) {
        if ($line -match '^\d+\s+\w+\s+([0-9a-f]+)\s+(\d+)\t(.+)$') {
            $size = [int64]$Matches[2]
            if ($size -ge 10MB) {
                [pscustomobject]@{
                    SizeMB = [math]::Round($size / 1MB, 2)
                    Path   = $Matches[3]
                    Hash   = $Matches[1]
                }
            }
        }
    }

    if ($large) {
        $large | Sort-Object SizeMB -Descending | Format-Table -AutoSize
    } else {
        Write-Host "No tracked files at least 10 MB."
    }

    Write-Host "`nPush preview only:"
    git push --dry-run origin "${branch}:${branch}"
}
