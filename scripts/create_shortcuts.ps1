# Crea los accesos directos de NeonWhisper en el escritorio y en el menu Inicio
# (el menu Inicio es lo que hace que aparezca en la busqueda de Windows).
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$pythonw = Join-Path $Root ".venv\Scripts\pythonw.exe"
$launcher = Join-Path $Root "NeonWhisper.pyw"
$icon = Join-Path $Root "assets\icon.ico"
$AppId = "Luisart.NeonWhisper"  # igual al AppUserModelID de la app: agrupa y fija bien en la barra de tareas

Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;

public static class LnkAppId {
    [StructLayout(LayoutKind.Sequential, Pack = 4)]
    public struct PROPERTYKEY { public Guid fmtid; public uint pid; }

    [ComImport, Guid("886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    interface IPropertyStore {
        void GetCount(out uint cProps);
        void GetAt(uint iProp, out PROPERTYKEY pkey);
        void GetValue(ref PROPERTYKEY key, IntPtr pv);
        void SetValue(ref PROPERTYKEY key, IntPtr pv);
        void Commit();
    }

    [ComImport, Guid("0000010b-0000-0000-C000-000000000046"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    interface IPersistFile {
        void GetClassID(out Guid pClassID);
        [PreserveSig] int IsDirty();
        void Load([MarshalAs(UnmanagedType.LPWStr)] string pszFileName, uint dwMode);
        void Save([MarshalAs(UnmanagedType.LPWStr)] string pszFileName, bool fRemember);
        void SaveCompleted([MarshalAs(UnmanagedType.LPWStr)] string pszFileName);
        void GetCurFile([MarshalAs(UnmanagedType.LPWStr)] out string ppszFileName);
    }

    [ComImport, Guid("00021401-0000-0000-C000-000000000046")]
    class CShellLink { }

    public static void Set(string lnkPath, string appId) {
        object link = new CShellLink();
        IPersistFile file = (IPersistFile)link;
        file.Load(lnkPath, 2);
        IPropertyStore store = (IPropertyStore)link;
        PROPERTYKEY key = new PROPERTYKEY();
        key.fmtid = new Guid("9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3");
        key.pid = 5;
        IntPtr pv = Marshal.AllocCoTaskMem(24);
        IntPtr str = Marshal.StringToCoTaskMemUni(appId);
        try {
            for (int i = 0; i < 24; i++) Marshal.WriteByte(pv, i, 0);
            Marshal.WriteInt16(pv, 0, 31);  // VT_LPWSTR
            Marshal.WriteIntPtr(pv, 8, str);
            store.SetValue(ref key, pv);
            store.Commit();
            file.Save(lnkPath, true);
        } finally {
            Marshal.FreeCoTaskMem(str);
            Marshal.FreeCoTaskMem(pv);
        }
    }
}
"@

$shell = New-Object -ComObject WScript.Shell
$targets = @(
    [Environment]::GetFolderPath("Desktop"),
    [Environment]::GetFolderPath("Programs")  # menu Inicio del usuario
)
foreach ($dir in $targets) {
    $path = Join-Path $dir "NeonWhisper.lnk"
    $lnk = $shell.CreateShortcut($path)
    $lnk.TargetPath = $pythonw
    $lnk.Arguments = "`"$launcher`""
    $lnk.WorkingDirectory = $Root
    $lnk.IconLocation = "$icon,0"
    $lnk.Description = "Dictado por voz local con Whisper"
    $lnk.Save()
    try { [LnkAppId]::Set($path, $AppId) } catch { Write-Host "     (No se pudo asignar AppUserModelID: $_)" }
    Write-Host "     $path"
}
