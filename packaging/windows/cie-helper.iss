; ============================================================================
;  CIE Helper — Inno Setup installer script
; ----------------------------------------------------------------------------
;  Wraps the PyInstaller output folder into a single setup.exe.
;
;  Prereqs, in order — the spec bundles frontend/dist as-is, so a stale UI
;  build ships silently:
;      npm run build --prefix frontend
;      uv run pyinstaller packaging/cie-helper.spec --noconfirm
;
;  Compile (from anywhere — paths below are relative to THIS .iss file):
;      "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" packaging\windows\cie-helper.iss
;
;  Output: dist\cie-helper-<version>-setup.exe
;
;  Override source/output dirs on the command line if needed:
;      ISCC /DBuildDir="C:\path\to\dist\cie-helper" /DOutputDir="C:\out" cie-helper.iss
; ============================================================================

#define MyAppName "CIE Helper"
#define MyAppVersion "1.4.1"
#define MyAppPublisher "Ambitions0x39e"      ; <-- edit to your name/handle
#define MyAppExeName "cie-helper.exe"

; Paths are relative to this .iss file (packaging\windows\).
#ifndef BuildDir
  #define BuildDir "..\..\dist\cie-helper"
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
; App is 64-bit. x64compatible also covers ARM64-via-emulation.
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; Installer wizard / Add-Remove-Programs icon. The app window + taskbar + shortcut
; icons come from the exe itself, embedded by the spec's `icon=` from this same file.
SetupIconFile=app.ico

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
; For a Simplified-Chinese wizard, uncomment (ChineseSimplified.isl ships with Inno):
; Name: "chinesesimp"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[InstallDelete]
; Wipe the payload dirs before installing. `ignoreversion` below overwrites
; files but NEVER deletes ones the new build no longer ships, so without this
; every upgrade leaves the previous version behind and the install dir only
; grows. Measured on a real install: 474 stale files / +108 MB accumulated
; (a whole cp314 site-packages + Lib\compression\ from back when
; requires-python had no upper bound, plus pypdfium2 and a second pypdf).
; That is not merely dead weight — the leftovers sit ON sys.path, so Python
; walks them at every startup. Cold-start cost, same machine, same build:
; clean 206 MB = 8.6 s; +108 MB parked outside sys.path = 11.3 s; the same
; 108 MB left in site-packages\ and Lib\ = 17.5 s.
; App data lives in ~/.cie_helper, never under {app}, so this deletes nothing
; the user owns. Scoped to the payload — do NOT wipe {app}\* wholesale, that
; would take out unins000.* and break uninstall registration.
;
; Two payload shapes are listed. `_internal` is this build's; the loose dirs
; below it are what a 1.x install put on disk, and an upgrade from one lands
; in the same {app} — leaving them would park a second interpreter and a
; second copy of every dependency next to the new one, permanently.
Type: filesandordirs; Name: "{app}\_internal"
Type: filesandordirs; Name: "{app}\app"
Type: filesandordirs; Name: "{app}\site-packages"
Type: filesandordirs; Name: "{app}\Lib"
Type: filesandordirs; Name: "{app}\DLLs"
Type: filesandordirs; Name: "{app}\data"
Type: files; Name: "{app}\*.dll"
Type: files; Name: "{app}\*.pyd"

[Files]
; Ship the ENTIRE folder: the exe plus _internal\, which holds the interpreter,
; every dependency, the built frontend and data\. Missing any of it and the app
; won't launch.
Source: "{#BuildDir}\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
; Interactive install only ("Launch CIE Helper" checkbox on the Finished page).
; `skipifsilent` means this does nothing during an auto-update — reopening the
; app after a silent update is handled by the app itself, not from here: an
; entry added here DID launch the app (the Inno log confirmed the Exec), but
; the app died within seconds of Setup deinitializing, most likely taken down
; with Setup's Restart Manager session. modules/updater.py instead chains
; installer-then-launch in a detached cmd, so the launch happens once Setup has
; fully exited. See _windows_relaunch_script there.
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent
