using System.Windows;

namespace EternalVoidPanel.Browsing;

public partial class BrowserWorkspace
{
    private BrowserAccountStore accountStore = null!;
    public void UseScannerAccounts(string dataPath, IEnumerable<string> names) => accountStore.UseScannerAccounts(dataPath, names);
    private void Accounts_Click(object sender, RoutedEventArgs e) => ShowAccounts(null);
    private void ShowAccounts(BrowserPane? selected)
    {
        try { new BrowserAccountsDialog(this, OrderedPanes().ToArray(), accountStore, selected).ShowDialog(); }
        catch { TextDialog.Info(Window.GetWindow(this), "Accounts unavailable", "The saved account list could not be opened. Your existing browser sessions are still available."); }
    }
    internal void SaveAccounts(IEnumerable<(BrowserPane Pane, string Account, string Password)> edits)
    {
        var entries = edits.ToArray();
        if(entries.Any(e=>e.Pane.AssistantControlled && (e.Account.Trim()!=e.Pane.State.Account || e.Password.Length>0))) throw new InvalidOperationException("Take control of these browsers before changing account assignments.");
        if (entries.Any(e => !Panes.Contains(e.Pane))) throw new InvalidOperationException("A browser was closed. Reopen Accounts and try again.");
        var assigned = entries.Where(e => !string.IsNullOrWhiteSpace(e.Account)).Select(e => e.Account.Trim()).ToArray();
        if (assigned.Distinct(StringComparer.OrdinalIgnoreCase).Count() != assigned.Length)
            throw new InvalidOperationException("Choose a different account for each browser.");
        try { accountStore.Save(entries.Select(e => (e.Account, e.Password))); }
        catch { throw new InvalidOperationException("Passwords could not be saved securely. Assignments were not changed."); }
        foreach (var entry in entries) entry.Pane.AssignAccount(entry.Account);
        try { state.Save(root); }
        catch { throw new InvalidOperationException("Assignments changed for this session but could not be saved on disk. Try Save assignments again."); }
    }
    internal async Task<string> FillAccountLoginAsync(BrowserPane pane)
    {
        if (string.IsNullOrWhiteSpace(pane.State.Account)) return "Assign an account first.";
        if (!pane.IsGamePage) return "Open eternal-void.online and its login screen in this browser, then choose Fill login.";
        try
        {
            string? password = accountStore.Password(pane.State.Account);
            if (string.IsNullOrEmpty(password)) return "Enter a password in Accounts and save it first.";
            return await pane.FillLoginAsync(pane.State.Account, password)
                ? "Login filled. Press LOG IN in the game to continue."
                : "Open the game’s login screen first. An existing signed-in session is kept as it is.";
        }
        catch { return "Could not fill this login. Reopen the login screen and try again."; }
    }
    private async void FillLogin(BrowserPane pane)
    {
        string message = await FillAccountLoginAsync(pane);
        TextDialog.Info(Window.GetWindow(this), pane.State.Name, message);
    }
}
