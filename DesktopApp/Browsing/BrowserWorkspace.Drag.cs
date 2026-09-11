using System.Windows;
using System.Windows.Input;

namespace EternalVoidPanel.Browsing;

public partial class BrowserWorkspace
{
    private const string DragFormat = "EOG.InternalBrowserPane";
    private BrowserPane? draggedPane;

    private void ScrollDuringDrag(object sender, DragEventArgs e)
    {
        if (draggedPane is null || !e.Data.GetDataPresent(DragFormat)) return;
        var point = e.GetPosition(BrowserScroll);
        const double edge = 40, step = 18;
        if (point.X < edge) BrowserScroll.ScrollToHorizontalOffset(BrowserScroll.HorizontalOffset - step);
        else if (point.X > BrowserScroll.ViewportWidth - edge) BrowserScroll.ScrollToHorizontalOffset(BrowserScroll.HorizontalOffset + step);
        if (point.Y < edge) BrowserScroll.ScrollToVerticalOffset(BrowserScroll.VerticalOffset - step);
        else if (point.Y > BrowserScroll.ViewportHeight - edge) BrowserScroll.ScrollToVerticalOffset(BrowserScroll.VerticalOffset + step);
    }

    private void ConfigureDragSource(FrameworkElement handle, BrowserPane pane)
    {
        Point origin = default;
        bool armed = false;
        handle.PreviewMouseLeftButtonDown += (_, e) => { origin = e.GetPosition(handle); armed = true; handle.CaptureMouse(); e.Handled = true; };
        handle.PreviewMouseLeftButtonUp += (_, _) => { armed = false; if (handle.IsMouseCaptured) handle.ReleaseMouseCapture(); };
        handle.MouseLeave += (_, _) => { if (Mouse.LeftButton != MouseButtonState.Pressed) armed = false; };
        handle.PreviewMouseMove += (_, e) =>
        {
            if (!armed || e.LeftButton != MouseButtonState.Pressed || draggedPane is not null) return;
            var position = e.GetPosition(handle);
            if (Math.Abs(position.X - origin.X) < SystemParameters.MinimumHorizontalDragDistance && Math.Abs(position.Y - origin.Y) < SystemParameters.MinimumVerticalDragDistance) return;
            armed = false; e.Handled = true; handle.ReleaseMouseCapture();
            draggedPane = pane;
            try
            {
                foreach (var candidate in Panes) candidate.ShowDropTarget(true);
                DragDrop.DoDragDrop(handle, new DataObject(DragFormat, pane), DragDropEffects.Move);
            }
            finally
            {
                draggedPane = null;
                foreach (var candidate in Panes) { candidate.ShowDropTarget(false); candidate.HighlightDropTarget(false); }
            }
        };
    }
    private void ConfigureDropTarget(BrowserPane target)
    {
        target.AllowDrop = true;
        bool Valid(DragEventArgs e) => draggedPane is not null && draggedPane != target && e.Data.GetDataPresent(DragFormat) && ReferenceEquals(e.Data.GetData(DragFormat), draggedPane);
        target.DragOver += (_, e) => { e.Effects = Valid(e) ? DragDropEffects.Move : DragDropEffects.None; target.HighlightDropTarget(Valid(e)); e.Handled = true; };
        target.DragLeave += (_, _) => target.HighlightDropTarget(false);
        target.Drop += (_, e) =>
        {
            if (Valid(e)) { SwapPanes(draggedPane!.Index, target.Index); e.Effects = DragDropEffects.Move; }
            else e.Effects = DragDropEffects.None;
            e.Handled = true;
        };
    }
}
