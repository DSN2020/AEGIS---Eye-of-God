using System.ComponentModel;

namespace EternalVoidPanel;

public sealed class ActivityEntry : INotifyPropertyChanged
{
    public string Id { get; init; } = "";
    public string Account { get; init; } = "";
    public string Text { get; init; } = "";
    public string AccountColor { get; init; } = "#8BD5FF";
    public double Timestamp { get; init; }
    public TimeSpan HighlightUntil { get; init; }
    public string TimeLabel => DateTimeOffset.FromUnixTimeMilliseconds((long)(Timestamp*1000)).LocalDateTime.ToString("yyyy-MM-dd HH:mm:ss.fff");
    private bool highlighted;
    public bool Highlighted {
        get => highlighted;
        set {
            if(highlighted==value) return;
            highlighted=value;
            PropertyChanged?.Invoke(this,new(nameof(HighlightBackground)));
            PropertyChanged?.Invoke(this,new(nameof(HighlightBorder)));
        }
    }
    public string HighlightBackground => Highlighted ? "#28"+AccountColor[1..] : "Transparent";
    public string HighlightBorder => Highlighted ? AccountColor : "Transparent";
    public event PropertyChangedEventHandler? PropertyChanged;
}
