# Install the pinned standalone manager privately; no second bar, PATH changes or startup entries.
$ErrorActionPreference = 'Stop'
$version = '3.10.1'
$digest = 'ad4122dd4420690e502e7df3ce8d1e4772bf1246cc815db0dd2aaac0e4dc583f'
$tilingStage = Join-Path ([IO.Path]::GetTempPath()) ('workspace-glazewm-' + [Guid]::NewGuid())
$destination = Join-Path $env:LOCALAPPDATA "workspace\tools\glazewm-v$version"
New-Item -ItemType Directory -Path $tilingStage | Out-Null
try {
    $msi = Join-Path $tilingStage 'glazewm.msi'
    Invoke-WebRequest "https://github.com/glzr-io/glazewm/releases/download/v$version/standalone-glazewm-v$version-x64.msi" -OutFile $msi -UseBasicParsing
    if ((Get-FileHash $msi -Algorithm SHA256).Hash.ToLowerInvariant() -ne $digest) { throw 'GlazeWM installer checksum mismatch' }
    # Read embedded cabinets without installing the per-machine MSI or changing the registry.
    Add-Type -TypeDefinition @'
using System;
using System.IO;
using System.Text;
using System.Runtime.InteropServices;
public static class WorkspaceTilingMsi {
 [DllImport("msi.dll",CharSet=CharSet.Unicode)] static extern uint MsiOpenDatabaseW(string p,IntPtr mode,out uint db);
 [DllImport("msi.dll",CharSet=CharSet.Unicode)] static extern uint MsiDatabaseOpenViewW(uint db,string sql,out uint view);
 [DllImport("msi.dll")] static extern uint MsiViewExecute(uint view,uint record);
 [DllImport("msi.dll")] static extern uint MsiViewFetch(uint view,out uint record);
 [DllImport("msi.dll",CharSet=CharSet.Unicode)] static extern uint MsiRecordGetStringW(uint record,uint field,StringBuilder value,ref uint length);
 [DllImport("msi.dll")] static extern uint MsiRecordReadStream(uint record,uint field,byte[] bytes,ref uint length);
 [DllImport("msi.dll")] static extern uint MsiCloseHandle(uint handle);
 static void Check(uint n) { if(n!=0)throw new Exception("MSI read error "+n); }
 public static void Extract(string path,string target) {
  uint db=0,view=0; Check(MsiOpenDatabaseW(path,IntPtr.Zero,out db));
  try {
   Check(MsiDatabaseOpenViewW(db,"SELECT `Name`, `Data` FROM `_Streams`",out view));Check(MsiViewExecute(view,0));
   uint row,result;
   while((result=MsiViewFetch(view,out row))==0) {
    try {
     var value=new StringBuilder(8192);uint size=8191;Check(MsiRecordGetStringW(row,1,value,ref size));
     string name=value.ToString();if(!name.EndsWith(".cab",StringComparison.OrdinalIgnoreCase))continue;
     using(var file=File.Create(Path.Combine(target,Path.GetFileName(name)))) {
      var bytes=new byte[65536];
      do { size=(uint)bytes.Length;Check(MsiRecordReadStream(row,2,bytes,ref size));file.Write(bytes,0,(int)size); }while(size!=0);
     }
    } finally {MsiCloseHandle(row);}
   }
   if(result!=259)Check(result);
  }finally{if(view!=0)MsiCloseHandle(view);if(db!=0)MsiCloseHandle(db);}
 }
}
'@
    [WorkspaceTilingMsi]::Extract($msi, $tilingStage)
    Get-ChildItem $tilingStage -Filter '*.cab' | ForEach-Object {
        & expand.exe $_.FullName '-F:*' $tilingStage | Out-Null
        if ($LASTEXITCODE -ne 0) { throw 'GlazeWM cabinet extraction failed' }
    }
    # The MSI contains two different glazewm.exe files; preserve the CLI subdirectory.
    $files = @{
        'Custom_RootExe' = 'glazewm.exe'
        'Custom_CliExe' = 'cli\glazewm.exe'
        'Custom_RootWatcherExe' = 'glazewm-watcher.exe'
    }
    foreach ($id in $files.Keys) {
        $source = Join-Path $tilingStage $id
        if ((Get-AuthenticodeSignature $source).Status -ne 'Valid') { throw "Invalid GlazeWM signature: $id" }
    }
    Invoke-WebRequest "https://raw.githubusercontent.com/glzr-io/glazewm/v$version/LICENSE.md" -OutFile (Join-Path $tilingStage 'LICENSE.txt') -UseBasicParsing
    New-Item -ItemType Directory -Force -Path (Join-Path $destination 'cli') | Out-Null
    foreach ($id in $files.Keys) {
        $source = Join-Path $tilingStage $id
        $target = Join-Path $destination $files[$id]
        if ((Test-Path $target) -and (Get-FileHash $source).Hash -eq (Get-FileHash $target).Hash) { continue }
        Copy-Item $source $target -Force
    }
    Copy-Item (Join-Path $tilingStage 'LICENSE.txt') (Join-Path $destination 'LICENSE.txt') -Force
    "GlazeWM v$version. Source and corresponding release: https://github.com/glzr-io/glazewm/tree/v$version" |
        Set-Content (Join-Path $destination 'SOURCE.txt') -Encoding UTF8
    Write-Output "Installed GlazeWM v$version. Restart Workspace to enable automatic tiling."
} finally {
    Remove-Item $tilingStage -Recurse -Force
}
