# Building the Windows download

Users download the release ZIP, extract it, and open `EOG.exe`. These instructions are for maintainers.

The build machine needs Windows x64, a .NET 8 SDK and Visual Studio C++ Build Tools (the x64 redistributable files). It does not need a preinstalled Python or Chrome. Run from the repository:

```powershell
.\packaging\Build-Windows.ps1 -Version 0.1.0
```

The script builds self-contained .NET, downloads a checksum-pinned CPython 3.12.14 distribution, installs the pinned Windows dependencies, includes app-local Microsoft C++ runtimes and downloads the matching Chromium browser. It copies an explicit application-file allowlist. Local settings, accounts, browser profiles and scan data are never copied. All dependency license files remain in the package.

Before producing the ZIP and SHA-256 file in `dist`, it runs offline OCR, browser, child-process and fresh WPF startup checks with developer tools removed from PATH. Reports and a first-run PNG are saved under `.build/check-*`. Repeat validation against an extracted package with `Test-WindowsPackage.ps1 -PackageRoot <folder>`.

The Windows download workflow builds pull requests and manual runs as downloadable Actions artifacts. Pushing a `v` version tag runs the same checks and publishes the release ZIP and checksum to GitHub Releases only after all checks pass. Never tag an untested change. The read-only build job cannot publish; only the tag-triggered release job has write permission.

The build refuses to reuse an existing output folder. Move old outputs or choose another version. Runtime paths are relative; settings live in `%LOCALAPPDATA%\EOG`. Source launches preserve their existing root-local settings. Existing source profiles are not silently migrated.

Maintain the pinned Python distribution, dependency lock and .NET SDK as security updates arrive. Python 3.12 is required by the current RapidOCR package. The zip is unsigned; use a trusted signing certificate for signed public builds. A separate Windows Sandbox or VM check is recommended for release qualification beyond the automated checks.

Runtime references: [Python distribution](https://github.com/astral-sh/python-build-standalone), [Playwright browsers](https://playwright.dev/python/docs/browsers), [.NET deployment](https://learn.microsoft.com/en-us/dotnet/core/deploying/), [Microsoft C++ deployment](https://learn.microsoft.com/en-us/cpp/windows/deployment-in-visual-cpp).
