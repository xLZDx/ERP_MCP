# Read and dismiss a modal message dialog of ONE Designer process (the child started by ct14_common.run_designer).
# Usage: powershell -File designer_dialog.ps1 <pid>
# Prints "DIALOG: <text>" when a dialog was found and clicks its OK button. Prints nothing otherwise.
param([int]$ProcId)
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
$root = [System.Windows.Automation.AutomationElement]::RootElement
$cond = New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::ProcessIdProperty, $ProcId)
$wins = $root.FindAll([System.Windows.Automation.TreeScope]::Children, $cond)
foreach ($w in $wins) {
  $all = $w.FindAll([System.Windows.Automation.TreeScope]::Descendants, [System.Windows.Automation.Condition]::TrueCondition)
  $text = $null; $ok = $null
  foreach ($t in $all) {
    $n = $t.Current.Name
    if (-not $n) { continue }
    if ($t.Current.ControlType.ProgrammaticName -eq "ControlType.Pane" -and $n.Length -gt 25 -and -not $text) { $text = $n }
    if ($t.Current.ControlType.ProgrammaticName -eq "ControlType.Button" -and ($n -eq "OK" -or $n -eq "Yes" -or $n -eq "Close") -and -not $ok -and $n -eq "OK") { $ok = $t }
  }
  if ($text -and $ok) {
    "DIALOG: " + $text
    $ok.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern).Invoke()
  }
}
