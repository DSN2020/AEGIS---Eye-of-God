using System.ComponentModel;
using System.Runtime.InteropServices;
using System.Text;
using System.Windows;
using System.Windows.Interop;

namespace EternalVoidPanel;

public static class ClipboardCopy
{
    private static readonly SemaphoreSlim Gate=new(1,1);
    public static Task CopyTextAsync(Window owner,string text)
    {
        owner.Dispatcher.VerifyAccess();
        return WriteAsync(new WindowInteropHelper(owner).EnsureHandle(),text);
    }

    // Write Unicode text directly. This avoids OLE's delayed rendering / flush
    // operation; Windows owns the completed buffer even after EOG closes.
    internal static async Task WriteAsync(nint window,string text)
    {
        if(string.IsNullOrEmpty(text))throw new ArgumentException("There is no text to copy.");
        await Gate.WaitAsync();
        try
        {
            for(int attempt=0;attempt<25;attempt++)
            {
                if(!IsWindow(window))throw new InvalidOperationException("The EOG window closed before copying finished.");
                if(TryWrite(window,text))return;
                if(attempt<24)await Task.Delay(100);
            }
            throw new TimeoutException("Another application is still holding the clipboard. Try copying again in a moment.");
        }
        finally{Gate.Release();}
    }

    private static bool TryWrite(nint window,string text)
    {
        // Prepare before opening/emptying the clipboard so allocation failures
        // leave the previous clipboard content intact.
        byte[] bytes=Encoding.Unicode.GetBytes(text.Replace("\r\n","\n").Replace("\n","\r\n")+"\0");
        nint memory=GlobalAlloc(0x0002,(nuint)bytes.Length);
        if(memory==0)throw new Win32Exception(Marshal.GetLastWin32Error(),"Could not allocate clipboard memory.");
        bool opened=false;
        try
        {
            nint pointer=GlobalLock(memory);
            if(pointer==0)throw new Win32Exception(Marshal.GetLastWin32Error(),"Could not prepare clipboard text.");
            try{Marshal.Copy(bytes,0,pointer,bytes.Length);}finally{GlobalUnlock(memory);}
            if(!OpenClipboard(window))return false;
            opened=true;
            if(!EmptyClipboard())throw new Win32Exception(Marshal.GetLastWin32Error(),"Could not update the clipboard.");
            if(SetClipboardData(13,memory)==0)throw new Win32Exception(Marshal.GetLastWin32Error(),"Windows could not accept the copied text.");
            memory=0; // Ownership transferred to Windows. Never free this buffer.
            return true;
        }
        finally
        {
            if(opened)CloseClipboard();
            if(memory!=0)GlobalFree(memory);
        }
    }

    public static string ErrorMessage(Exception error)=>error switch
    {
        TimeoutException=>error.Message,
        Win32Exception native=>$"Could not copy text (Windows error {native.NativeErrorCode}). Try again.",
        ArgumentException=>"There is no text to copy.",
        _=>"Could not copy text. Reopen EOG and try again."
    };

    [DllImport("user32.dll")] private static extern bool IsWindow(nint window);
    [DllImport("user32.dll",SetLastError=true)] private static extern bool OpenClipboard(nint window);
    [DllImport("user32.dll",SetLastError=true)] private static extern bool EmptyClipboard();
    [DllImport("user32.dll",SetLastError=true)] private static extern nint SetClipboardData(uint format,nint memory);
    [DllImport("user32.dll")] private static extern bool CloseClipboard();
    [DllImport("kernel32.dll",SetLastError=true)] private static extern nint GlobalAlloc(uint flags,nuint bytes);
    [DllImport("kernel32.dll",SetLastError=true)] private static extern nint GlobalLock(nint memory);
    [DllImport("kernel32.dll")] private static extern bool GlobalUnlock(nint memory);
    [DllImport("kernel32.dll")] private static extern nint GlobalFree(nint memory);
}
