Download the **EOG Windows ZIP** from **Assets** below. Its filename ends in **windows-x64.zip**.

1. Right-click the ZIP and choose **Extract All**.
2. Open the extracted folder and double-click **EOG.exe**.
3. Enter your Eternal Void account, select **Save & apply**, then **Resume scan**.

The Windows ZIP includes Python, .NET, Chromium, OCR models and their dependencies. You do not need to install developer tools or run commands. The GitHub-generated **Source code** archives are for developers.

For 64-bit Windows 10/11 on Intel/AMD PCs. Internet access and your own game account are required for scanning. macOS, Linux and native ARM builds are not included.

Settings and results live in `%LOCALAPPDATA%\EOG`. Updates retain them. Pause scans and any Upgrade bot profiles before switching versions. Existing source installations keep their original data; this release starts with a separate profile.

Validation covers fresh desktop startup, bundled Python and native runtimes, offline OCR, isolated/shared browsers and regression tests. These checks do not sign into game accounts. This download is currently unsigned; Windows may show an unknown-publisher warning.
