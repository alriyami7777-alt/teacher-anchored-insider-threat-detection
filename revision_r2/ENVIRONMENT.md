# Software environment

**Training/evaluation environment (matches the frozen EDITOR-023 and EDITOR-024 run manifests):**
Python 3.11.9 (CPython, Windows 64-bit); PyTorch 2.11.0+cu128 (CUDA 12.8); NumPy 2.4.6; pandas 2.2.3;
scikit-learn 1.9.0; XGBoost 3.2.0; SciPy 1.17.1.

**Hardware:** NVIDIA GeForce RTX 5070 Laptop GPU (8 GB, driver 610.71); AMD Ryzen 7 260 (8 cores / 16 threads); 31.3 GiB RAM; Windows 11 (10.0.26200).

The pinned `requirements.txt` lists only the packages that the analysis code imports. The full `pip freeze` exported on 2026-10-21 is in `ENV_EXPORT_2026-10-21.txt`. It describes the installed environment on that date, attributed to the historical runs by version match. It is not a lockfile recovered from the original runs.

**Correction to the submitted manuscript.** The version line in the submitted manuscript (Python 3.11.15, PyTorch 2.12.1+cu130, NumPy 2.4.4, pandas 3.0.3) describes a separate Conda environment (`cert-r42-gpu`) that does **not** match the frozen EDITOR run fingerprint. The revised manuscript quotes the versions above.
