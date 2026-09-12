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
              const visible = e => {
                const r = e.getBoundingClientRect();
                if (!e.isConnected || e.disabled || e.readOnly || r.width <= 0 || r.height <= 0
                    || r.left < 0 || r.top < 0 || r.right > innerWidth || r.bottom > innerHeight) return false;
                let opacity = 1;
                for (let node = e; node; node = node.parentElement) {
                  const style = getComputedStyle(node);
                  opacity *= Number(style.opacity);
                  if (style.display === 'none' || style.visibility !== 'visible') return false;
                }
                const top = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
                return opacity >= .5 && (top === e || e.contains(top));
              };
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
