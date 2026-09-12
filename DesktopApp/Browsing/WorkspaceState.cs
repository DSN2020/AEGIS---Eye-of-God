using System.IO;
using System.Text.Json;

namespace EternalVoidPanel.Browsing;

public sealed class PaneState
{
    public string Name { get; set; } = "";
    public string Account { get; set; } = "";
    public string Url { get; set; } = "";
    public double Zoom { get; set; } = 1;
    public bool Muted { get; set; }
    public bool Temporary { get; set; }
    public bool IsOpen { get; set; } = true;
    public long ClosedAt { get; set; }
}

public sealed class WorkspaceState
{
    public int Rows { get; set; } = 1;
    public double PaneWidth { get; set; } = 320;
    public bool AutoFit { get; set; } = true;
    public int[] Order { get; set; } = [0, 1, 2, 3, 4, 5];
    public PaneState[] Panes { get; set; } = Enumerable.Range(1, 6).Select(i => new PaneState { Name = $"Browser {i:00}" }).ToArray();
    public static WorkspaceState Load(string root)
    {
        try
        {
            var value = JsonSerializer.Deserialize<WorkspaceState>(File.ReadAllText(Path.Combine(root, "workspace.json")));
            if (value is null || value.Panes is null || value.Panes.Any(p => p is null)) return new();
            value.Rows = value.Rows == 2 ? 2 : 1;
            value.PaneWidth = double.IsFinite(value.PaneWidth) ? Math.Clamp(value.PaneWidth, 260, 480) : 320;
            // IDs remain positions in the saved profile array, including closed profiles.
            value.Order = (value.Order ?? []).Where(i => i >= 0 && i < value.Panes.Length)
                .Concat(Enumerable.Range(0, value.Panes.Length)).Distinct().ToArray();
            foreach (var pane in value.Panes) pane.Zoom = double.IsFinite(pane.Zoom) ? Math.Clamp(pane.Zoom, .25, 3) : 1;
            return value;
        }
        catch { return new(); }
    }
    public void Save(string root)
    {
        Directory.CreateDirectory(root);
        string path = Path.Combine(root, "workspace.json");
        File.WriteAllText(path + ".tmp", JsonSerializer.Serialize(this, new JsonSerializerOptions { WriteIndented = true }));
        File.Move(path + ".tmp", path, true);
    }
}
