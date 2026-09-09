using System.ComponentModel;
using System.Windows.Media;

namespace EternalVoidPanel;

public sealed class ActivityEntry : INotifyPropertyChanged
{
    public static readonly TimeSpan HighlightDuration = TimeSpan.FromSeconds(1);
    public string Id { get; init; } = "";
    public string Account { get; init; } = "";
    public string Text { get; init; } = "";
    public string AccountColor { get; init; } = "#8BD5FF";
    public double Timestamp { get; init; }
    public TimeSpan HighlightUntil { get; init; }
    public string TimeLabel => DateTimeOffset.FromUnixTimeMilliseconds((long)(Timestamp*1000)).LocalDateTime.ToString("yyyy-MM-dd HH:mm:ss.fff");
    private double highlightStrength;
    public bool Highlighted {
        get => highlightStrength > 0;
        set => SetHighlightStrength(value ? 1 : 0);
    }
    public SolidColorBrush HighlightBackground { get; private set; } = Brush(Color.FromRgb(32,32,32));
    public SolidColorBrush HighlightBorder { get; private set; } = Brush(Color.FromRgb(59,59,59));
    public SolidColorBrush HighlightForeground { get; private set; } = Brush(Color.FromRgb(155,155,155));

    public void UpdateHighlight(TimeSpan now) {
        if(!Highlighted) return;
        // Polling or recycled list rows cannot restart or reverse a fade.
        SetHighlightStrength(Math.Min(highlightStrength,
            Math.Clamp((HighlightUntil-now).TotalSeconds/HighlightDuration.TotalSeconds,0,1)));
    }
    private void SetHighlightStrength(double value) {
        if(highlightStrength==value) return;
        highlightStrength=value;
        var accent=(Color)ColorConverter.ConvertFromString(AccountColor);
        HighlightBackground=Blend(Color.FromArgb(40,accent.R,accent.G,accent.B),Color.FromRgb(32,32,32),value);
        HighlightBorder=Blend(accent,Color.FromRgb(59,59,59),value);
        HighlightForeground=Blend(accent,Color.FromRgb(155,155,155),value);
        PropertyChanged?.Invoke(this,new(nameof(Highlighted)));
        PropertyChanged?.Invoke(this,new(nameof(HighlightBackground)));
        PropertyChanged?.Invoke(this,new(nameof(HighlightBorder)));
        PropertyChanged?.Invoke(this,new(nameof(HighlightForeground)));
    }
    private static SolidColorBrush Blend(Color color,Color gray,double strength) {
        byte Mix(byte from,byte to) => (byte)Math.Round(to+(from-to)*strength);
        return Brush(Color.FromArgb(Mix(color.A,gray.A),Mix(color.R,gray.R),Mix(color.G,gray.G),Mix(color.B,gray.B)));
    }
    private static SolidColorBrush Brush(Color color) {
        var brush=new SolidColorBrush(color);brush.Freeze();return brush;
    }
    public event PropertyChangedEventHandler? PropertyChanged;
}
