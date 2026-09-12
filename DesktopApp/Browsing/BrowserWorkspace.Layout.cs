using System.Windows;
using System.Windows.Controls;
namespace EternalVoidPanel.Browsing;
public partial class BrowserWorkspace
{
    internal const double MinimumPaneWidth = 260;
    internal const double MinimumPaneHeight = 310;
    private const double PaneGap = 6;
    internal int[] PaneOrder => OrderedPanes().Select(p => p.Index).ToArray();
    internal int LayoutRows => state.Rows;
    internal double MobileWidth => state.PaneWidth;
    private void QueueSave() { if (closed || !ready) return; RefreshControlLabels(); saveTimer.Stop(); saveTimer.Start(); }
    private void Save()
    {
        try { state.Save(root); }
        catch (Exception ex) { StatusText.Text = "Could not save workspace: " + ex.Message; }
    }
    public void SetRows(int count) { state.Rows = count == 2 ? 2 : 1; focused = -1; BuildLayout(); QueueSave(); }
    public void SetPaneWidth(double width)
    {
        if (!double.IsFinite(width)) return;
        state.AutoFit = false;
        state.PaneWidth = Math.Clamp(width, MinimumPaneWidth, 480);
        SyncWidthSlider();
        UpdateCanvasSize(); QueueSave();
    }
    public void FitToWindow()
    {
        state.AutoFit = true; UpdateCanvasSize(); QueueSave();
    }
    private void SyncWidthSlider()
    {
        syncingWidth = true;
        try { WidthSlider.Value = state.PaneWidth; }
        finally { syncingWidth = false; }
    }
    public void ToggleFocus(BrowserPane pane) { focused = focused == pane.Index ? -1 : pane.Index; BuildLayout(); }
    public void ShowAll() { focused = -1; BuildLayout(); }
    internal void SwapPanes(int source, int target)
    {
        if (source == target || !Panes.Any(p => p.Index == source) || !Panes.Any(p => p.Index == target)) return;
        int from = Array.IndexOf(state.Order, source), to = Array.IndexOf(state.Order, target);
        (state.Order[from], state.Order[to]) = (state.Order[to], state.Order[from]);
        BuildLayout(); QueueSave();
    }
    private void RefreshControlLabels()
    {
        InstanceCount.Text = $"{Panes.Count} open";
        RemoveButton.IsEnabled = Panes.Count > 0;
        MuteAllButton.IsEnabled = Panes.Count > 0;
        MuteAllButton.Content = Panes.Count > 0 && Panes.All(p => p.State.Muted) ? "Unmute all" : "Mute all";
        WidthLabel.Text = $"{state.PaneWidth:0} px";
        FitButton.Content = state.AutoFit ? "Auto fit ✓" : "Auto fit";
        FitButton.BorderBrush = BrowserPane.Brush(state.AutoFit ? "#786269" : "#363636");
        int across = Math.Max(1, (int)Math.Floor((Math.Max(0, BrowserScroll.ViewportWidth) + PaneGap) / (state.PaneWidth + PaneGap)));
        StatusText.Text = Panes.Count == 0 ? "Saved sessions are kept on this PC." : $"{across} across × {state.Rows} {(state.Rows == 1 ? "row" : "rows")} · {across * state.Rows} fit at this width · {Panes.Count} open";
    }
    private void BuildLayout()
    {
        // Keep composition controls attached while moving them to new grid cells.
        BrowserGrid.RowDefinitions.Clear(); BrowserGrid.ColumnDefinitions.Clear();
        EmptyView.Visibility = Panes.Count == 0 ? Visibility.Visible : Visibility.Collapsed;
        BrowserScroll.Visibility = Panes.Count == 0 ? Visibility.Hidden : Visibility.Visible;
        RestoreButton.Visibility = focused >= 0 ? Visibility.Visible : Visibility.Collapsed;
        OneRowButton.BorderBrush = BrowserPane.Brush(state.Rows == 1 ? "#786269" : "#363636");
        TwoRowsButton.BorderBrush = BrowserPane.Brush(state.Rows == 2 ? "#786269" : "#363636");
        int rows = focused >= 0 ? 1 : Math.Min(state.Rows, Math.Max(1, Panes.Count));
        int columns = focused >= 0 ? 1 : Math.Max(1, (int)Math.Ceiling(Panes.Count / (double)rows));
        for (int c = 0; c < columns * 2 - 1; c++) BrowserGrid.ColumnDefinitions.Add(new() { Width = new(c % 2 == 0 ? state.PaneWidth : PaneGap) });
        for (int r = 0; r < rows * 2 - 1; r++) BrowserGrid.RowDefinitions.Add(new() { Height = r % 2 == 0 ? new(1, GridUnitType.Star) : new(PaneGap) });
        var ordered = OrderedPanes().ToArray();
        for (int position = 0; position < ordered.Length; position++)
        {
            var pane = ordered[position]; bool shown = focused < 0 || focused == pane.Index;
            pane.Visibility = shown ? Visibility.Visible : Visibility.Collapsed; pane.SetFocused(focused == pane.Index);
            Grid.SetRow(pane, focused >= 0 ? 0 : position / columns * 2); Grid.SetColumn(pane, focused >= 0 ? 0 : position % columns * 2);
            if (!BrowserGrid.Children.Contains(pane)) BrowserGrid.Children.Add(pane);
        }
        UpdateCanvasSize();
    }
    private void UpdateCanvasSize()
    {
        if (!ready) return;
        int rows = focused >= 0 ? 1 : Math.Min(state.Rows, Math.Max(1, Panes.Count));
        int columns = focused >= 0 ? 1 : Math.Max(1, (int)Math.Ceiling(Panes.Count / (double)rows));
        if (focused < 0 && state.AutoFit && BrowserScroll.ViewportWidth > 0)
        {
            state.PaneWidth = Math.Clamp(Math.Floor((BrowserScroll.ViewportWidth - PaneGap * (columns - 1)) / columns), MinimumPaneWidth, 480);
            SyncWidthSlider();
        }
        double width = focused >= 0 ? Math.Max(MinimumPaneWidth, BrowserScroll.ViewportWidth) : state.PaneWidth;
        foreach (var column in BrowserGrid.ColumnDefinitions.Where((_, i) => i % 2 == 0)) column.Width = new(width);
        BrowserGrid.Width = columns * width + (columns - 1) * PaneGap;
        BrowserGrid.Height = Math.Max(rows * MinimumPaneHeight + (rows - 1) * PaneGap, BrowserScroll.ViewportHeight);
        RefreshControlLabels();
    }
}
