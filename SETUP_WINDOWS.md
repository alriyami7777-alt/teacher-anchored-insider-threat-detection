# Windows Setup

## Create the local repository

```powershell
$source = "<path-to-this-starter-folder>"
$destination = "C:\PhD\07_Projects\teacher-anchored-insider-threat-detection"

Copy-Item -Recurse -Force $source $destination
Set-Location $destination

git init -b main
git add .
git commit -m "Initial paper reproducibility repository scaffold"
```

## Create the GitHub repository

Create a new **private** GitHub repository named:

```text
teacher-anchored-insider-threat-detection
```

Do not initialise it with a README, licence, or `.gitignore`, because those files already exist locally.

Then connect and push:

```powershell
git remote add origin https://github.com/<your-account>/teacher-anchored-insider-threat-detection.git
git push -u origin main
```

## Before copying implementation code

- select one authoritative source branch for each experiment;
- remove absolute paths;
- remove dataset identifiers and answer files;
- exclude checkpoints and prediction arrays;
- confirm that result tables match the locked manifests;
- retain branch and commit provenance in `manifests/`.
