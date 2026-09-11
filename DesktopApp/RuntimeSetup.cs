using System.Diagnostics;
using System.IO;
using System.Text;
using System.Text.Json;

namespace EternalVoidPanel;

internal sealed record RuntimeSetup(string AppRoot, string DataRoot, string PythonPath, bool Packaged)
{
    public static RuntimeSetup Prepare(string baseDirectory)
    {
        var directory = new DirectoryInfo(baseDirectory);
        while (directory != null && !File.Exists(Path.Combine(directory.FullName, "app_bridge.py")))
            directory = directory.Parent;
        string appRoot = directory?.FullName ?? throw new InvalidOperationException(
            "EOG's files could not be found. Extract the entire Windows ZIP before opening EOG.exe, or reinstall EOG.");
        bool packaged = File.Exists(Path.Combine(appRoot, "eog-release.json"));
        string dataRoot = Environment.GetEnvironmentVariable("EOG_DATA_ROOT") ?? (packaged
            ? Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "EOG")
            : appRoot);
        dataRoot = Path.GetFullPath(dataRoot);
        string python = Path.Combine(appRoot, "runtime", "python", "python.exe");
        if (!packaged)
        {
            string runtimeFile = Path.Combine(appRoot, "desktop-runtime.json");
            if (File.Exists(runtimeFile))
            {
                using var document = JsonDocument.Parse(File.ReadAllText(runtimeFile));
                python = Path.GetFullPath(document.RootElement.GetProperty("pythonPath").GetString()
                    ?? throw new InvalidOperationException("The Python runtime path is empty."), appRoot);
            }
            else python = Path.Combine(appRoot, ".venv", "Scripts", "python.exe");
        }
        if (!File.Exists(python)) throw new InvalidOperationException(packaged
            ? "EOG's included runtime is missing. Extract the entire Windows ZIP again, or reinstall EOG."
            : "This is the source edition. Download the Windows release to use EOG, or run Setup.ps1 to prepare a development environment.");
        if (packaged && !Directory.Exists(Path.Combine(appRoot, "runtime", "browsers")))
            throw new InvalidOperationException("EOG's included browser is missing. Extract the entire Windows ZIP again, or reinstall EOG.");
        Directory.CreateDirectory(dataRoot);
        // CreateNew prevents a second launch or an upgrade from overwriting settings.
        string config = Path.Combine(dataRoot, "config.json");
        if (!File.Exists(config))
        {
            byte[] template = File.ReadAllBytes(Path.Combine(appRoot, "config.example.json"));
            FileStream? file = null;
            try { file = new FileStream(config, FileMode.CreateNew); }
            catch (IOException) when (File.Exists(config)) { }
            if (file != null) { using (file) file.Write(template); }
        }
        Directory.CreateDirectory(Path.Combine(dataRoot, "data"));
        return new(appRoot, dataRoot, python, packaged);
    }

    public ProcessStartInfo BridgeProcess()
    {
        var info = new ProcessStartInfo(PythonPath) {
            WorkingDirectory = AppRoot, UseShellExecute = false, CreateNoWindow = true,
            RedirectStandardInput = true, RedirectStandardOutput = true, RedirectStandardError = true,
            StandardInputEncoding = new UTF8Encoding(false), StandardOutputEncoding = Encoding.UTF8
        };
        info.ArgumentList.Add("-u");
        info.ArgumentList.Add(Path.Combine(AppRoot, "app_bridge.py"));
        info.Environment["EOG_DATA_ROOT"] = DataRoot;
        info.Environment["PYTHONUTF8"] = "1";
        if (Packaged) info.Environment["PLAYWRIGHT_BROWSERS_PATH"] = Path.Combine(AppRoot, "runtime", "browsers");
        return info;
    }
}
