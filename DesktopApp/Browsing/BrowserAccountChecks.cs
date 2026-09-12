using System.IO;
using System.Text;
using Microsoft.Web.WebView2.Core;

namespace EternalVoidPanel.Browsing;

internal static class BrowserAccountChecks
{
    internal static async Task RunAsync(BrowserWorkspace workspace, string root, Action<bool, string> check)
    {
        const string user = "Example account", secret = "Only-a-test-credential-837";
        var store = new BrowserAccountStore(root);
        store.Save([(user, secret)]);
        check(new BrowserAccountStore(root).Password(user) == secret && !Encoding.UTF8.GetString(File.ReadAllBytes(store.SecretPath)).Contains(secret), "Browser credentials round-trip through Windows encryption without plaintext on disk");
        store.Save([(user, "")]);
        check(store.Password(user.ToUpperInvariant()) == secret, "Blank passwords retain the saved credential and account lookup ignores case");
        string scanner = Path.Combine(root, "scanner-fixture"); Directory.CreateDirectory(scanner);
        File.Copy(store.SecretPath, Path.Combine(scanner, "account-secrets.dpapi"));
        var consumer = new BrowserAccountStore(Path.Combine(root, "separate-vault"));
        consumer.UseScannerAccounts(scanner, [user]);
        byte[] scannerBefore = File.ReadAllBytes(Path.Combine(scanner, "account-secrets.dpapi"));
        check(consumer.Password(user) == secret, "Saved scanner credentials can be reused through the existing encrypted format");
        consumer.Save([(user, "Separate browser replacement")]);
        check(File.ReadAllBytes(Path.Combine(scanner, "account-secrets.dpapi")).SequenceEqual(scannerBefore), "Saving a browser password does not modify scanner credentials");

        var pane = workspace.Panes[0];
        string folder = pane.DataFolder;
        var core = pane.Browser.CoreWebView2;
        workspace.SaveAccounts(workspace.Panes.Select(p => (p, p == pane ? user : "", "")));
        check(pane.State.Name == user && pane.State.Account == user && ReferenceEquals(core, pane.Browser.CoreWebView2) && pane.DataFolder == folder,
            "Assignment names the browser after its account without replacing the live session");
        check(WorkspaceState.Load(root).Panes[pane.Index].Account == user && !File.ReadAllText(Path.Combine(root, "workspace.json")).Contains(secret), "Account assignment persists separately from secrets");
        var another = workspace.Panes[1];
        bool rejected = false;
        try { workspace.SaveAccounts(workspace.Panes.Select(p => (p, p == pane || p == another ? user : "", ""))); }
        catch (InvalidOperationException) { rejected = true; }
        check(rejected && another.State.Account.Length == 0, "Duplicate assignments are rejected without partially changing browser names");
        string pages = Path.Combine(root, "login-fixture"); Directory.CreateDirectory(pages);
        await File.WriteAllTextAsync(Path.Combine(pages, "login.html"), """
            <!doctype html><meta name="viewport" content="width=device-width,initial-scale=1">
            <style>input{display:block;width:240px;height:35px;margin:10px}.registration{position:absolute;left:540px;top:0}.invisible{position:absolute;top:300px;opacity:0}</style>
            <form id="login" onsubmit="event.preventDefault();window.submitted=true"><input id="login-user" type="text"><input id="login-password" type="password"><button>LOG IN</button></form>
            <div class="registration"><input type="email"><input type="password"><input type="password"></div>
            <div class="invisible"><input type="text"><input type="password"></div>
            <script>window.changes=0;document.addEventListener('input',()=>window.changes++);</script>
            """);
        core.SetVirtualHostNameToFolderMapping("eternal-void.online", pages, CoreWebView2HostResourceAccessKind.DenyCors);
        try
        {
            core.Navigate("https://eternal-void.online/login.html");
            for (int i = 0; i < 200; i++)
            {
                if (await pane.Browser.ExecuteScriptAsync("location.href==='https://eternal-void.online/login.html' && document.querySelectorAll('input').length===7") == "true") break;
                await Task.Delay(100);
            }
            check(await pane.FillLoginAsync(user, secret), "Saved login ignores the game's offscreen registration and transparent inputs");
            check(await pane.Browser.ExecuteScriptAsync("document.querySelector('input[type=text]').value==='Example account' && document.querySelector('input[type=password]').value.length===26 && window.changes===2 && !window.submitted") == "true", "Login filling updates form events without submitting credentials");
            check(await pane.Browser.ExecuteScriptAsync("[...document.querySelectorAll('.registration input,.invisible input')].every(e=>e.value==='')") == "true", "Registration and invisible fields never receive login credentials");
            await pane.Browser.ExecuteScriptAsync("document.body.insertAdjacentHTML('beforeend','<div id=cover style=\"position:fixed;inset:0;background:#222;z-index:100\"></div>')");
            check(!await pane.FillLoginAsync("Should not fill", secret), "A connection overlay covering login prevents filling underneath it");
            await pane.Browser.ExecuteScriptAsync("document.querySelector('#cover').remove();document.querySelector('#login').insertAdjacentHTML('beforeend','<input id=duplicate type=password>')");
            check(!await pane.FillLoginAsync("Should not fill", secret), "Multiple visible password fields are rejected without changing the account");
            await pane.Browser.ExecuteScriptAsync("document.querySelector('#duplicate').remove();document.querySelector('#login-user').type='email'");
            check(await pane.FillLoginAsync("example@example.invalid", secret), "Email identifiers use the same visible login form");
            core.Navigate("about:blank");
            for (int i = 0; i < 100 && core.Source != "about:blank"; i++) await Task.Delay(50);
            check(!await pane.FillLoginAsync(user, secret), "Credentials are refused outside the exact HTTPS game origin");
        }
        finally { core.ClearVirtualHostNameToFolderMapping("eternal-void.online"); }
        workspace.ClosePane(pane);
        var reopened = await workspace.AddBrowserAsync();
        check(reopened?.Index == pane.Index && reopened.State.Account == user && reopened.State.Name == user, "Closing and reopening preserves the account assignment and browser name");
        workspace.SaveAccounts(workspace.Panes.Select(p => (p, "", "")));
    }
}
