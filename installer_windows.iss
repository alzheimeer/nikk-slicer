; Instalador de Nikk Slicer para Windows (Inno Setup 6)
#define MyAppName "Nikk Slicer"
#define MyAppVersion "1.3.0"
#define MyAppPublisher "Niklauss Mauricio Quintero Romero"
#define MyAppURL "https://github.com/alzheimeer/nikk-slicer"
#define MyAppExeName "Nikk Slicer.exe"

[Setup]
AppId={{8F4B9A2C-3D1E-4A7B-9C5D-2E8F1A4B6C90}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
AllowNoIcons=yes
LicenseFile=LICENSE
OutputDir=dist_release
OutputBaseFilename=NikkSlicer_Windows_Setup
SetupIconFile=nikk_slicer.ico
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
ChangesAssociations=yes
PrivilegesRequired=lowest

[Languages]
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"
Name: "assoc3mf"; Description: "Asociar archivos .3mf con Nikk Slicer"; GroupDescription: "Asociaciones de archivos (opcional)"; Flags: unchecked
Name: "assocstl"; Description: "Asociar archivos .stl con Nikk Slicer"; GroupDescription: "Asociaciones de archivos (opcional)"; Flags: unchecked

[Files]
Source: "dist_win\Nikk Slicer\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\nikk_slicer.ico"
Name: "{group}\Desinstalar {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\nikk_slicer.ico"; Tasks: desktopicon

[Registry]
Root: HKA; Subkey: "Software\Classes\.3mf\OpenWithProgids"; ValueType: string; ValueName: "NikkSlicer.3mf"; ValueData: ""; Flags: uninsdeletevalue; Tasks: assoc3mf
Root: HKA; Subkey: "Software\Classes\NikkSlicer.3mf"; ValueType: string; ValueName: ""; ValueData: "Proyecto 3D (.3mf) - Nikk Slicer"; Flags: uninsdeletekey; Tasks: assoc3mf
Root: HKA; Subkey: "Software\Classes\NikkSlicer.3mf\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: "{app}\nikk_slicer.ico,0"; Tasks: assoc3mf
Root: HKA; Subkey: "Software\Classes\NikkSlicer.3mf\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#MyAppExeName}"" ""%1"""; Tasks: assoc3mf

Root: HKA; Subkey: "Software\Classes\.stl\OpenWithProgids"; ValueType: string; ValueName: "NikkSlicer.stl"; ValueData: ""; Flags: uninsdeletevalue; Tasks: assocstl
Root: HKA; Subkey: "Software\Classes\NikkSlicer.stl"; ValueType: string; ValueName: ""; ValueData: "Malla 3D (.stl) - Nikk Slicer"; Flags: uninsdeletekey; Tasks: assocstl
Root: HKA; Subkey: "Software\Classes\NikkSlicer.stl\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: "{app}\nikk_slicer.ico,0"; Tasks: assocstl
Root: HKA; Subkey: "Software\Classes\NikkSlicer.stl\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#MyAppExeName}"" ""%1"""; Tasks: assocstl

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent
