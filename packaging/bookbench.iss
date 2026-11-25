; ======================================================================
;  Installer für Bookbench (Inno Setup 6)
;
;  Normalerweise über  build_windows.bat installer  aufrufen - das baut vorher
;  das Programm und übergibt die Versionsnummer aus bookbench\version.py.
;  Von Hand im Ordner packaging:  ISCC.exe /DAppVersion=0.27 bookbench.iss
;
;  Wie beim Keller-Tool: ohne Administratorrechte in den Benutzerordner
;  (%LOCALAPPDATA%\Programs\Bookbench); wer Admin ist, kann "für alle Benutzer" wählen.
;  Der Updater (bookbench\core\updater.py) startet diese Datei mit /SILENT: dann
;  gelten Ordner und Aufgaben der vorhandenen Installation, und Bookbench startet
;  danach von selbst (letzte Zeile unter [Run]).
; ======================================================================

#ifndef AppVersion
  #define AppVersion "0.0"
#endif
; Dateiversion der .exe braucht reine Zahlen: "1.1-beta1" -> "1.1"
#define AppVersionNum Pos("-", AppVersion) > 0 ? Copy(AppVersion, 1, Pos("-", AppVersion) - 1) : AppVersion
#define AppName "Bookbench"
#define AppExe  "Bookbench.exe"

[Setup]
AppId={{6C2E3B57-1F4A-4D8E-9B0C-2A7D5E91B3F4}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
VersionInfoVersion={#AppVersionNum}
AppPublisher=Sebastian Kopf
AppPublisherURL=https://github.com/kepfle-git/Bookbench
AppUpdatesURL=https://github.com/kepfle-git/Bookbench/releases
DefaultDirName={autopf}\Bookbench
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=dist
OutputBaseFilename=Bookbench_Setup_{#AppVersion}
SetupIconFile=bookbench.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
RestartApplications=no
ShowLanguageDialog=auto

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "german"; MessagesFile: "compiler:Languages\German.isl"

[CustomMessages]
english.DesktopIcon=Create a desktop shortcut
german.DesktopIcon=Verknüpfung auf dem Desktop anlegen
english.Additional=Additional:
german.Additional=Zusätzlich:
english.StartNow=Start Bookbench now
german.StartNow=Bookbench jetzt starten
english.Uninstall=Uninstall Bookbench
german.Uninstall=Bookbench deinstallieren

[Tasks]
Name: "desktopicon"; Description: "{cm:DesktopIcon}"; GroupDescription: "{cm:Additional}"; Flags: unchecked

[InstallDelete]
; Alten Programmunterbau vor dem Kopieren leeren, damit Dateien, die ein neuerer Build
; nicht mehr mitbringt, nicht liegen bleiben. Einstellungen liegen unter %APPDATA%\Bookbench.
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "dist\Bookbench\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion
Source: "..\THIRD_PARTY_LICENSES.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\LICENSE"; DestDir: "{app}"; DestName: "LICENSE.txt"; Flags: ignoreversion

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{group}\{cm:Uninstall}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:StartNow}"; Flags: nowait postinstall skipifsilent
; Update aus Bookbench heraus (still): danach gleich wieder starten
Filename: "{app}\{#AppExe}"; Flags: nowait; Check: WizardSilent
