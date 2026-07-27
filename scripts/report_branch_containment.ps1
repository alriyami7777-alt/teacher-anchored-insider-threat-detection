param(
    [string]$Repository = "C:\PhD\07_Projects\cert-r42-feasibility",
    [string]$Tip = "objective1-r62-model-free-warmup"
)

Set-Location $Repository

$report = foreach ($branch in git for-each-ref --format="%(refname:short)" refs/heads) {
    git merge-base --is-ancestor $branch $Tip
    $included = ($LASTEXITCODE -eq 0)

    [pscustomobject]@{
        Branch        = $branch
        Commit        = git rev-parse --short $branch
        IncludedInTip = $included
        Upstream      = git for-each-ref --format="%(upstream:short)" "refs/heads/$branch"
    }
}

$report |
    Sort-Object IncludedInTip, Branch |
    Format-Table -AutoSize
