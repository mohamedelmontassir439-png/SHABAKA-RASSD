# Installe le relais local comme tâche planifiée de Windows.
#
# Une fois installé, le relais démarre à chaque ouverture de session et le
# planificateur vérifie toutes les 15 minutes qu'il tourne (sinon il le
# relance). Un seul relais tourne à la fois: les lancements en double
# s'arrêtent d'eux-mêmes.
#
# Lancer: clic droit sur ce fichier → « Exécuter avec PowerShell ».
# Désinstaller: Unregister-ScheduledTask -TaskName "Relais Maroc Entrepreneuriat"

$ErrorActionPreference = "Stop"
$dossier = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$py = (& py -c "import sys,os;print(os.path.join(os.path.dirname(sys.executable),'pythonw.exe'))").Trim()
if (-not (Test-Path $py)) { throw "pythonw.exe introuvable: $py" }

$action = New-ScheduledTaskAction -Execute $py `
    -Argument "`"$dossier\relais\relais_portail.py`"" -WorkingDirectory $dossier
$aLaSession = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$surveillance = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) `
    -RepetitionInterval (New-TimeSpan -Minutes 15)
$reglages = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1)

Register-ScheduledTask -TaskName "Relais Maroc Entrepreneuriat" `
    -Description "Collecte marchespublics.gov.ma depuis ce poste et dépose sur marocentrepreneuriat.com" `
    -Action $action -Trigger @($aLaSession, $surveillance) -Settings $reglages -Force | Out-Null

Write-Host "Relais installé. Journal: $dossier\relais\relais.log"
Read-Host "Appuyez sur Entrée pour fermer"
