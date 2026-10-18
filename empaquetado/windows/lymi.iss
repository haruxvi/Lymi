; Instalador de lymi para Windows (Inno Setup 6, https://jrsoftware.org/isinfo.php).
;
; Por usuario y sin pedir administrador: se instala en %LOCALAPPDATA%\Programs\lymi.
; Los datos (ledger, agenda, workflows, memoria) viven aparte, en %LOCALAPPDATA%\lymi,
; y desinstalar no los toca: son tuyos.
;
; Se compila despues de PyInstaller:
;     iscc /DVersion=0.1.0 empaquetado\windows\lymi.iss

#ifndef Version
  #define Version "0.0.0"
#endif

[Setup]
AppId={{6B1C3E52-6F2D-4C2B-9C8E-1D3A7F0B5E21}
AppName=lymi
AppVersion={#Version}
AppVerName=lymi {#Version}
AppPublisher=lymi
AppPublisherURL=https://github.com/haruxvi/Lymi
DefaultDirName={localappdata}\Programs\lymi
DefaultGroupName=lymi
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\..\dist
OutputBaseFilename=lymi-{#Version}-windows-x64
SetupIconFile=..\lymi.ico
UninstallDisplayIcon={app}\lymi.exe
LicenseFile=..\..\LICENSE
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes

[Languages]
Name: "es"; MessagesFile: "compiler:Languages\Spanish.isl"
Name: "en"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "escritorio"; Description: "Crear un acceso directo en el escritorio"; Flags: unchecked
Name: "inicio"; Description: "Abrir lymi al iniciar sesión (así las programaciones corren solas)"; Flags: unchecked

[Files]
Source: "..\..\dist\lymi\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{autoprograms}\lymi"; Filename: "{app}\lymi.exe"
Name: "{autodesktop}\lymi"; Filename: "{app}\lymi.exe"; Tasks: escritorio
Name: "{userstartup}\lymi"; Filename: "{app}\lymi.exe"; Tasks: inicio

[Run]
Filename: "{app}\lymi.exe"; Description: "Abrir lymi"; Flags: nowait postinstall skipifsilent

[Messages]
es.FinishedLabel=lymi quedó instalado. Tus datos viven en %LOCALAPPDATA%\lymi y nunca salen de este equipo sin que lo veas en "Lo que salió".
