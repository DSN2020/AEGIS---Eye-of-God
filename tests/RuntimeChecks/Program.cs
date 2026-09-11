using EternalVoidPanel;

string fixture = Path.Combine(Path.GetTempPath(), "EOG runtime " + Guid.NewGuid());
string? previous = Environment.GetEnvironmentVariable("EOG_DATA_ROOT");
void Check(bool condition, string message) { if (!condition) throw new Exception(message); }
try
{
    string app = Path.Combine(fixture, "App folder");
    string data = Path.Combine(fixture, "User settings");
    Directory.CreateDirectory(Path.Combine(app, "runtime", "python"));
    Directory.CreateDirectory(Path.Combine(app, "runtime", "browsers"));
    File.WriteAllText(Path.Combine(app, "app_bridge.py"), "");
    File.WriteAllText(Path.Combine(app, "config.example.json"), "{\"fresh\":true}");
    File.WriteAllText(Path.Combine(app, "eog-release.json"), "{}");
    File.WriteAllText(Path.Combine(app, "runtime", "python", "python.exe"), "");
    Environment.SetEnvironmentVariable("EOG_DATA_ROOT", data);
    var runtime = RuntimeSetup.Prepare(app);
    Check(runtime.Packaged && runtime.DataRoot==data, "Packaged data path was not selected");
    Check(File.ReadAllText(Path.Combine(data, "config.json"))=="{\"fresh\":true}", "Fresh defaults missing");
    File.WriteAllText(Path.Combine(data, "config.json"), "{\"saved\":true}");
    RuntimeSetup.Prepare(app);
    Check(File.ReadAllText(Path.Combine(data, "config.json"))=="{\"saved\":true}", "Upgrade replaced user settings");
    var process = runtime.BridgeProcess();
    Check(process.Environment["EOG_DATA_ROOT"]==data, "Child data path missing");
    Check(process.ArgumentList[1]==Path.Combine(app,"app_bridge.py"), "Script path must be absolute");
    Check(process.FileName==Path.Combine(app,"runtime","python","python.exe"), "Must use included Python");
    Check(!File.Exists(Path.Combine(app,"config.json")), "Must not write settings beside the executable");
    File.Delete(Path.Combine(app,"runtime","python","python.exe"));
    try { RuntimeSetup.Prepare(app); throw new Exception("Missing Python was accepted"); }
    catch(InvalidOperationException ex) { Check(ex.Message.Contains("runtime is missing"), "Missing-runtime recovery instructions absent"); }
    File.Delete(Path.Combine(app,"eog-release.json"));
    Directory.CreateDirectory(Path.Combine(app,".venv","Scripts"));
    File.WriteAllText(Path.Combine(app,".venv","Scripts","python.exe"), "");
    Environment.SetEnvironmentVariable("EOG_DATA_ROOT", null);
    var source = RuntimeSetup.Prepare(app);
    Check(!source.Packaged && source.DataRoot==app, "Source setup compatibility failed");
    Check(source.PythonPath==Path.Combine(app,".venv","Scripts","python.exe"), "Source venv fallback failed");
    Console.WriteLine("Runtime checks passed: fresh defaults, upgrades, spaces, child paths, recovery, source compatibility.");
}
finally
{
    Environment.SetEnvironmentVariable("EOG_DATA_ROOT", previous);
    Directory.Delete(fixture, recursive:true);
}
