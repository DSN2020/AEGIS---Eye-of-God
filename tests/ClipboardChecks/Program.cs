using System.ComponentModel;
using System.Runtime.InteropServices;
using System.Windows.Threading;
using EternalVoidPanel;

internal static class Program
{
    static int checks;
    static nint desktop,window;
    static void Check(bool value,string label){if(!value)throw new Exception(label);checks++;}
    [STAThread] static int Main(string[] args)
    {
        // This opt-in integration test writes temporary clipboard contents,
        // then leaves an actual saved hive ready to paste. It never reads or
        // logs the user's prior clipboard contents.
        if(args.Length!=2 || args[0]!="--copy-saved-hive")
        {
            Console.Error.WriteLine("Usage: --copy-saved-hive <private player snapshot.json>. This exercises the Windows clipboard and leaves a saved hive copied.");return 2;
        }
        var players=System.Text.Json.JsonSerializer.Deserialize<List<PlayerEntry>>(System.IO.File.ReadAllText(args[1]),new System.Text.Json.JsonSerializerOptions{PropertyNameCaseInsensitive=true})!;
        var hive=HiveDetector.Detect(players).First();
        desktop=GetThreadDesktop(GetCurrentThreadId());window=NewWindow();
        int result=1;
        var dispatcher=Dispatcher.CurrentDispatcher;
        SynchronizationContext.SetSynchronizationContext(new DispatcherSynchronizationContext(dispatcher));
        dispatcher.BeginInvoke(async ()=>
        {
            try
            {
                await Run();await ClipboardCopy.WriteAsync(window,hive.CopyText);
                Check(Read()==hive.CopyText.Replace("\n","\r\n"),"Actual hive output round-trips through the clipboard");
                Console.WriteLine($"{checks} Windows clipboard checks passed; a saved hive is copied and ready to paste");result=0;
            }
            catch(Exception error){Console.Error.WriteLine(error);}
            finally{dispatcher.BeginInvokeShutdown(DispatcherPriority.Background);}
        });
        Dispatcher.Run();DestroyWindow(window);return result;
    }
    static async Task Run()
    {
        string text="Galaxy 2 · Systems 142–144\n村长 [Alliance]\n```\n2:142:5 · 2:144:20\n```";
        await ClipboardCopy.WriteAsync(window,text);
        Check(Read()==text.Replace("\n","\r\n"),"Unicode, Discord fences and line endings must round-trip");
        using(var release=new ManualResetEventSlim())
        using(var locked=new ManualResetEventSlim())
        {
            var holder=Hold(locked,release);Check(locked.Wait(3000),"Test clipboard lock acquired");
            var copy=ClipboardCopy.WriteAsync(window,text+" newer");
            await Task.Delay(150);Check(!copy.IsCompleted,"Copy waits asynchronously for another clipboard owner");
            release.Set();await copy;holder.Join();
            Check(Read().EndsWith(" newer"),"Copy succeeds after brief contention");
        }
        using(var release=new ManualResetEventSlim())
        using(var locked=new ManualResetEventSlim())
        {
            var holder=Hold(locked,release);Check(locked.Wait(3000),"Persistent test lock acquired");
            try
            {
                try{await ClipboardCopy.WriteAsync(window,"must not replace content");throw new Exception("Expected bounded timeout");}
                catch(TimeoutException error){Check(ClipboardCopy.ErrorMessage(error).Contains("Another application"),"Persistent contention gets an accurate message");}
            }
            finally{release.Set();holder.Join();}
            Check(Read().EndsWith(" newer"),"A busy clipboard preserves its previous contents");
        }
        await ClipboardCopy.WriteAsync(window,"Recovered");Check(Read()=="Recovered","A timeout releases the copy gate");
        Check(!ClipboardCopy.ErrorMessage(new Win32Exception(8)).Contains("holding"),"Non-contention failures are not labelled busy");
        try{await ClipboardCopy.WriteAsync(window,"");throw new Exception("Empty copy should fail");}
        catch(ArgumentException){Check(Read()=="Recovered","Empty copy leaves clipboard unchanged");}
    }
    static Thread Hold(ManualResetEventSlim locked,ManualResetEventSlim release)
    {
        var thread=new Thread(()=>
        {
            SetThreadDesktop(desktop);var holder=NewWindow();
            if(!OpenClipboard(holder))return;
            try{locked.Set();release.Wait(10000);}finally{CloseClipboard();DestroyWindow(holder);}
        });thread.SetApartmentState(ApartmentState.STA);thread.Start();return thread;
    }
    static nint NewWindow()
    {
        var handle=CreateWindowEx(0,"STATIC","EOG clipboard test",0,0,0,0,0,0,0,0,0);
        if(handle==0)throw new Win32Exception(Marshal.GetLastWin32Error());return handle;
    }
    static string Read()
    {
        if(!OpenClipboard(window))throw new Win32Exception(Marshal.GetLastWin32Error());
        try{var memory=GetClipboardData(13);var ptr=GlobalLock(memory);try{return Marshal.PtrToStringUni(ptr)??"";}finally{GlobalUnlock(memory);}}
        finally{CloseClipboard();}
    }
    [DllImport("user32.dll")] static extern nint GetThreadDesktop(uint id);
    [DllImport("user32.dll",SetLastError=true)] static extern bool SetThreadDesktop(nint desktop);
    [DllImport("kernel32.dll")] static extern uint GetCurrentThreadId();
    [DllImport("user32.dll",CharSet=CharSet.Unicode,SetLastError=true)] static extern nint CreateWindowEx(uint ex,string cls,string title,uint style,int x,int y,int w,int h,nint parent,nint menu,nint instance,nint param);
    [DllImport("user32.dll")] static extern bool DestroyWindow(nint window);
    [DllImport("user32.dll",SetLastError=true)] static extern bool OpenClipboard(nint window);
    [DllImport("user32.dll")] static extern bool CloseClipboard();
    [DllImport("user32.dll")] static extern nint GetClipboardData(uint format);
    [DllImport("kernel32.dll")] static extern nint GlobalLock(nint memory);
    [DllImport("kernel32.dll")] static extern bool GlobalUnlock(nint memory);
}
