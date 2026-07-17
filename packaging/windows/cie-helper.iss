; ============================================================================
;  CIE Helper — Inno Setup installer script
; ----------------------------------------------------------------------------
;  Wraps the `flet build windows` output folder into a single setup.exe.
;
;  Prereq: run the Flet build first so build\windows\ exists:
;      PYTHONIOENCODING=utf-8 PYTHONUTF8=1 uv run flet build windows
;
;  Compile (from anywhere — paths below are relative to THIS .iss file):
;      "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" packaging\windows\cie-helper.iss
;
;  Output: dist\cie-helper-<version>-setup.exe
;
;  Override source/output dirs on the command line if needed:
;      ISCC /DBuildDir="C:\path\to\build\windows" /DOutputDir="C:\out" cie-helper.iss
; ============================================================================

#define MyAppName "CIE Helper"
#define MyAppVersion "0.2.0"
#define MyAppPublisher "Ambitions0x39e"      ; <-- edit to your name/handle
#define MyAppExeName "cie-helper.exe"

; Paths are relative to this .iss file (packaging\windows\).
#ifndef BuildDir
  #define BuildDir "..\..\build\windows"
#endif
#ifndef OutputDir
  #define OutputDir "..\..\dist"
#endif

[Setup]
; AppId uniquely identifies the app for install/upgrade/uninstall.
; KEEP THIS GUID STABLE across versions — changing it makes Windows treat a new
; version as a separate product instead of an upgrade.
AppId={{B7E4B0A9-6C21-4F3D-9A85-1E2C7D9F4A60}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
UninstallDisplayName={#MyAppName}
UninstallDisplayIcon={app}\{#MyAppExeName}
; Per-user install => NO admin/UAC prompt. Best fit for unsigned distribution to
; ordinary users; installs under %LocalAppData%\Programs. Switch to `admin` +
; DefaultDirName={commonpf} if you want a machine-wide Program Files install.
PrivilegesRequired=lowest
OutputDir={#OutputDir}
OutputBaseFilename=cie-helper-{#MyAppVersion}-setup
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
; App is 64-bit (Flet/Flutter x64). x64compatible also covers ARM64-via-emulation.
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; Installer wizard / Add-Remove-Programs icon. The app window + taskbar + shortcut
; icons come from the exe itself, embedded at `flet build` time from assets/icon.png.
SetupIconFile=app.ico

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
; For a Simplified-Chinese wizard, uncomment (ChineseSimplified.isl ships with Inno):
; Name: "chinesesimp"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; Ship the ENTIRE build\windows folder: exe + all DLLs + data\ + Lib\ + DLLs\ +
; site-packages\. Missing any of these and the app won't launch.
Source: "{#BuildDir}\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent
