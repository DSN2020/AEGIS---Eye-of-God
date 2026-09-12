using System.IO;
using System.Security.Cryptography;
using System.Text.Json;

namespace EternalVoidPanel.Browsing;

internal sealed class BrowserAccountStore(string root)
{
    private string? scannerData;
    private string[] scannerAccounts = [];
    internal string SecretPath => Path.Combine(root, "browser-accounts.dpapi");
    public void UseScannerAccounts(string dataPath, IEnumerable<string> names)
    {
        scannerData = dataPath;
        scannerAccounts = names.Where(n => !string.IsNullOrWhiteSpace(n)).Distinct(StringComparer.OrdinalIgnoreCase).ToArray();
    }
    public string[] Names => Read(SecretPath).Keys.Concat(scannerAccounts).Distinct(StringComparer.OrdinalIgnoreCase).Order(StringComparer.OrdinalIgnoreCase).ToArray();
    public string? Password(string name)
    {
        var own = Read(SecretPath);
        if (own.TryGetValue(name.Trim(), out var saved) && saved.Length > 0) return saved[0];
        if (scannerData is null || !scannerAccounts.Contains(name.Trim(), StringComparer.OrdinalIgnoreCase)) return null;
        var scanner = Read(Path.Combine(scannerData, "account-secrets.dpapi"));
        return scanner.TryGetValue(name.Trim(), out var values) ? values.FirstOrDefault() : null;
    }
    public void Save(IEnumerable<(string Account, string Password)> edits)
    {
        var values = Read(SecretPath);
        bool changed = false;
        foreach (var (name, password) in edits)
        {
            if (string.IsNullOrWhiteSpace(name) || string.IsNullOrEmpty(password)) continue;
            values[name.Trim()] = [password]; changed = true;
        }
        if (!changed) return;
        Directory.CreateDirectory(root);
        byte[] plain = JsonSerializer.SerializeToUtf8Bytes(values);
        try
        {
            byte[] encrypted = ProtectedData.Protect(plain, null, DataProtectionScope.CurrentUser);
            File.WriteAllBytes(SecretPath + ".tmp", encrypted);
            File.Move(SecretPath + ".tmp", SecretPath, true);
        }
        finally { CryptographicOperations.ZeroMemory(plain); }
    }
    private static Dictionary<string, string[]> Read(string path)
    {
        if (!File.Exists(path)) return new(StringComparer.OrdinalIgnoreCase);
        byte[] plain = ProtectedData.Unprotect(File.ReadAllBytes(path), null, DataProtectionScope.CurrentUser);
        try
        {
            var values = JsonSerializer.Deserialize<Dictionary<string, string[]>>(plain) ?? throw new InvalidDataException("Invalid account store.");
            return new(values, StringComparer.OrdinalIgnoreCase);
        }
        finally { CryptographicOperations.ZeroMemory(plain); }
    }
}
