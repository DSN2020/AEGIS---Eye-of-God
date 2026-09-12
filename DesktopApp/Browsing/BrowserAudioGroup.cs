namespace EternalVoidPanel.Browsing;

// A browser and all of its popups have one mute state. Groups never cross profiles.
internal sealed class BrowserAudioGroup(bool muted)
{
    private readonly HashSet<BrowserPane> members = [];
    private bool isMuted = muted;
    public void Register(BrowserPane pane) { members.Add(pane); pane.ApplyMute(isMuted); }
    public void Unregister(BrowserPane pane) => members.Remove(pane);
    public void SetMuted(bool value)
    {
        isMuted = value;
        foreach (var pane in members.ToArray()) pane.ApplyMute(value);
    }
}
