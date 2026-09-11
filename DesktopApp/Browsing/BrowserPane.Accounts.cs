using System.Text.Json;

namespace EternalVoidPanel.Browsing;

public sealed partial class BrowserPane
{
    internal bool IsGamePage => Browser?.CoreWebView2 is { } core && Uri.TryCreate(core.Source, UriKind.Absolute, out var uri)
        && uri.Scheme == "https" && uri.Host.Equals("eternal-void.online", StringComparison.OrdinalIgnoreCase) && uri.IsDefaultPort;

    internal async Task<bool> FillLoginAsync(string account, string password)
    {
        if (!IsGamePage || disposed) return false;
        // Check origin again inside the same script that fills the fields, including after navigation races.
        string script = $$"""
            (() => {
              if (location.origin !== 'https://eternal-void.online') return false;
              const visible = e => !e.disabled && !e.readOnly && e.getClientRects().length && getComputedStyle(e).visibility !== 'hidden';
              const inputs = [...document.querySelectorAll('input')].filter(visible);
              const passwords = inputs.filter(e => e.type === 'password');
              const users = inputs.filter(e => ['text','email'].includes(e.type));
              if (passwords.length !== 1 || users.length !== 1) return false;
              const p = passwords[0], u = users[0];
              if (u.form && p.form && u.form !== p.form) return false;
              const set = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
              for (const [field, value] of [[u, {{JsonSerializer.Serialize(account)}}], [p, {{JsonSerializer.Serialize(password)}}]]) {
                set.call(field, value);
                field.dispatchEvent(new Event('input', {bubbles:true}));
                field.dispatchEvent(new Event('change', {bubbles:true}));
              }
              p.focus(); return true;
            })()
            """;
        return await Browser.ExecuteScriptAsync(script) == "true";
    }
}
